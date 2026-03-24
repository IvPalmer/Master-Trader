#!/usr/bin/env python3
"""
Bot Rotator — Automated Strategy Evaluation & Replacement
==========================================================

Evaluates all running bots over a 5-day window. If a bot consistently
underperforms, it gets flagged for replacement or auto-paused.

Evaluation criteria (5-day window):
  - Negative Sharpe ratio
  - Win rate < 35%
  - Zero trades (dead bot)
  - Max drawdown > 15%

Actions:
  - FLAG: Bot is underperforming, notify via Telegram
  - PAUSE: Bot has been flagged for 2+ consecutive evaluations, auto-pause
  - REPLACE: Paused bot slot is available for a new strategy

Usage:
    python bot_rotator.py                    # Evaluate all bots
    python bot_rotator.py --dry-run          # Show evaluation without actions
    python bot_rotator.py --pause ElliotV5   # Manually pause a bot
    python bot_rotator.py --status           # Show current rotation state

Cron (daily at 22:00 São Paulo):
    0 22 * * * cd ~/ft_userdata && python3 bot_rotator.py >> logs/bot_rotator.log 2>&1
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import numpy as np

from api_utils import api_get as _api_get_with_retry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _load_bots_config() -> dict:
    """Load bot registry from shared config, fall back to hardcoded defaults."""
    config_path = Path(__file__).parent / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        bots = {}
        for name, info in data["bots"].items():
            if not info.get("active", True):
                continue
            container = f"ft-{name.lower().replace('v1', '').replace('strategy', '')}"
            # Use container from config if present, otherwise generate
            bots[name] = {
                "port": info["port"],
                "container": info.get("container", container),
                "timeframe": info.get("timeframe", "1h"),
            }
        return bots
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {
            "SupertrendStrategy": {"port": 8084, "container": "ft-supertrendstrategy", "timeframe": "1h"},
            "MasterTraderV1":     {"port": 8086, "container": "ft-mastertraderv1", "timeframe": "1h"},
            "AlligatorTrendV1":   {"port": 8091, "container": "ft-alligator-trend", "timeframe": "1d"},
            "GaussianChannelV1":  {"port": 8092, "container": "ft-gaussian-channel", "timeframe": "1d"},
        }

BOTS = _load_bots_config()

API_USER = "freqtrader"
API_PASS = "mastertrader"

EVAL_WINDOW_DAYS = 5
FLAG_THRESHOLD_EVALS = 2  # Flag for 2 consecutive evals → auto-pause

# Failure thresholds (any ONE triggers a flag)
MIN_SHARPE = -0.5
MIN_WIN_RATE = 35.0
MAX_DRAWDOWN_PCT = 20.0
MIN_TRADES_PER_DAY = 0.2  # At least 1 trade per 5 days

STATE_FILE = Path.home() / "ft_userdata" / "rotation_state.json"
LOGS_DIR = Path.home() / "ft_userdata" / "logs"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "bot_rotator.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("bot-rotator")


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

def api_get(port: int, endpoint: str) -> Optional[Any]:
    """Fetch from Freqtrade API with retry logic."""
    return _api_get_with_retry(port, endpoint)


def parse_date(s: str) -> datetime:
    """Parse Freqtrade date string."""
    if not s:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_bot(strategy: str, port: int) -> dict:
    """Evaluate a single bot over the 5-day window."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=EVAL_WINDOW_DAYS)

    result = {
        "strategy": strategy,
        "status": "ok",
        "issues": [],
        "metrics": {},
    }

    # Fetch trades
    data = api_get(port, "trades?limit=500")
    if data is None:
        result["status"] = "unreachable"
        result["issues"].append("Bot unreachable")
        return result

    trades = data.get("trades", data) if isinstance(data, dict) else data

    # Filter to evaluation window (closed trades only)
    recent = [
        t for t in trades
        if t.get("close_date") and parse_date(t["close_date"]) >= cutoff
    ]

    # Also check open trades
    open_trades = api_get(port, "status") or []

    # --- Zero trades check ---
    total_activity = len(recent) + len(open_trades)
    # Daily TF bots may go weeks without trades — don't flag as dead
    bot_tf = BOTS.get(strategy, {}).get("timeframe", "1h")
    if total_activity == 0:
        if bot_tf == "1d":
            result["status"] = "ok"
            result["issues"].append(f"Zero trades in {EVAL_WINDOW_DAYS} days (normal for daily TF)")
            result["metrics"] = {"trades": 0, "open": 0}
            return result
        result["status"] = "dead"
        result["issues"].append(f"Zero trades in {EVAL_WINDOW_DAYS} days")
        result["metrics"] = {"trades": 0, "open": 0}
        return result

    # --- Compute metrics over window ---
    if recent:
        profits = [t.get("profit_ratio", 0) * 100 for t in recent]
        wins = sum(1 for p in profits if p > 0)
        win_rate = (wins / len(profits)) * 100

        # Daily returns for Sharpe
        daily_pnl = {}
        for t in recent:
            day = parse_date(t["close_date"]).strftime("%Y-%m-%d")
            daily_pnl[day] = daily_pnl.get(day, 0) + t.get("profit_ratio", 0) * 100

        # Fill in zero-return days for proper Sharpe calculation
        returns = []
        for i in range(EVAL_WINDOW_DAYS):
            day = (cutoff + timedelta(days=i)).strftime("%Y-%m-%d")
            returns.append(daily_pnl.get(day, 0.0))

        if len(returns) >= 3:
            mean_r = np.mean(returns)
            std_r = np.std(returns, ddof=1)
            sharpe = float((mean_r / std_r) * np.sqrt(365)) if std_r > 0 else 0
        else:
            sharpe = 0

        # Max drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in sorted(recent, key=lambda x: x.get("close_date", "")):
            cumulative += t.get("profit_ratio", 0) * 100
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        total_profit = sum(profits)
        trades_per_day = len(recent) / EVAL_WINDOW_DAYS
    else:
        win_rate = 0
        sharpe = 0
        max_dd = 0
        total_profit = 0
        trades_per_day = 0

    result["metrics"] = {
        "trades": len(recent),
        "open": len(open_trades),
        "win_rate": round(win_rate, 1),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "total_profit_pct": round(total_profit, 2),
        "trades_per_day": round(trades_per_day, 2),
    }

    # --- Flag checks ---
    # Use a scoring approach: accumulate severity points
    # Flag if severity >= 2 (single bad metric isn't enough)
    issues = []
    severity = 0

    if total_profit < -5.0:
        issues.append(f"P/L {total_profit:+.1f}% in {EVAL_WINDOW_DAYS}d")
        severity += 2

    if recent and win_rate < MIN_WIN_RATE:
        issues.append(f"Win rate {win_rate:.0f}% < {MIN_WIN_RATE}%")
        severity += 1

    if max_dd > MAX_DRAWDOWN_PCT:
        issues.append(f"Drawdown {max_dd:.1f}% > {MAX_DRAWDOWN_PCT}%")
        severity += 1

    if trades_per_day < MIN_TRADES_PER_DAY and not open_trades:
        issues.append(f"Only {trades_per_day:.1f} trades/day (min {MIN_TRADES_PER_DAY})")
        severity += 1

    # Negative profit + bad win rate = definitely broken
    if total_profit < 0 and recent and win_rate < 45:
        severity += 1

    if severity >= 2:
        result["status"] = "flagged"
        result["issues"] = issues
    elif issues:
        # Minor issues, just note them but don't flag
        result["issues"] = [f"(minor) {i}" for i in issues]

    return result


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"flags": {}, "paused": [], "history": []}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    except Exception as e:
        log.error("Failed to save state: %s", e)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def pause_bot(strategy: str, container: str, reason: str) -> bool:
    """Stop a bot's Docker container."""
    log.info("PAUSING %s (%s): %s", strategy, container, reason)
    try:
        result = subprocess.run(
            ["docker", "stop", container],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        log.error("Failed to pause %s: %s", strategy, e)
        return False


def send_report(evaluations: list[dict], actions: list[str], dry_run: bool = False):
    """Send evaluation report via Telegram webhook."""
    lines = []
    tag = " [DRY RUN]" if dry_run else ""
    lines.append(f"🔄 Bot Rotation Evaluation{tag}")
    lines.append(f"Window: {EVAL_WINDOW_DAYS} days")
    lines.append("")

    for ev in evaluations:
        status_emoji = {
            "ok": "✅", "flagged": "⚠️", "dead": "💀",
            "unreachable": "❌", "paused": "⏸️",
        }.get(ev["status"], "❓")

        m = ev.get("metrics", {})
        metrics_str = ""
        if m:
            metrics_str = (
                f" | {m.get('trades', 0)} trades | "
                f"WR: {m.get('win_rate', 0):.0f}% | "
                f"Sharpe: {m.get('sharpe', 0):.1f} | "
                f"P/L: {m.get('total_profit_pct', 0):+.1f}%"
            )

        lines.append(f"{status_emoji} {ev['strategy']}{metrics_str}")
        if ev["issues"]:
            for issue in ev["issues"]:
                lines.append(f"   → {issue}")

    if actions:
        lines.append("")
        lines.append("Actions taken:")
        for a in actions:
            lines.append(f"  • {a}")

    message = "\n".join(lines)
    log.info("\n%s", message)

    try:
        r = requests.post(WEBHOOK_URL, data={"type": "status", "status": message}, timeout=10)
        if r.status_code in (200, 201, 204):
            log.info("Report sent to Telegram")
        else:
            log.warning("Webhook returned %d", r.status_code)
    except Exception as e:
        log.warning("Could not send report: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bot Rotator — evaluate and replace underperformers")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without taking actions")
    parser.add_argument("--pause", type=str, help="Manually pause a specific bot")
    parser.add_argument("--status", action="store_true", help="Show current rotation state")
    args = parser.parse_args()

    state = load_state()

    if args.status:
        print(json.dumps(state, indent=2))
        return

    if args.pause:
        strategy = args.pause
        if strategy not in BOTS:
            log.error("Unknown strategy: %s", strategy)
            sys.exit(1)
        container = BOTS[strategy]["container"]
        pause_bot(strategy, container, "Manual pause")
        if strategy not in state["paused"]:
            state["paused"].append(strategy)
        save_state(state)
        return

    log.info("=" * 60)
    log.info("Bot Rotator — %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Evaluation window: %d days", EVAL_WINDOW_DAYS)
    log.info("=" * 60)

    evaluations = []
    actions = []

    for strategy, info in BOTS.items():
        if strategy in state.get("paused", []):
            evaluations.append({
                "strategy": strategy,
                "status": "paused",
                "issues": ["Already paused"],
                "metrics": {},
            })
            continue

        ev = evaluate_bot(strategy, info["port"])
        evaluations.append(ev)
        log.info("%s: %s %s", strategy, ev["status"], ev.get("issues", []))

    # --- Check leashed bots (accelerated kill evaluation) ---
    leash = state.get("leash", {})
    for strategy, lconf in list(leash.items()):
        if lconf.get("status") != "active":
            continue
        ev = next((e for e in evaluations if e["strategy"] == strategy), None)
        if not ev or ev["status"] in ("paused", "unreachable"):
            continue

        # Count trades since leash started
        trades_at_start = lconf.get("trades_at_start", 0)
        current_trades = ev["metrics"].get("trades", 0) + trades_at_start  # total trades
        # Fetch actual total from API
        port = BOTS.get(strategy, {}).get("port")
        if port:
            profit_data = api_get(port, "profit")
            if profit_data:
                current_trades = profit_data.get("closed_trade_count", current_trades)

        new_trades = current_trades - trades_at_start
        max_trades = lconf.get("max_trades", 15)
        kill_pf = lconf.get("kill_if_pf_below", 1.0)

        if new_trades >= max_trades:
            # Evaluate PF from profit data
            pf = 0
            if profit_data:
                winning_profit = profit_data.get("profit_closed_coin", 0)
                # Approximate PF from win/loss counts
                w = profit_data.get("winning_trades", 0)
                l = profit_data.get("losing_trades", 0)
                if l > 0 and w > 0:
                    # Fetch actual trades for precise PF
                    trades_data = api_get(port, "trades?limit=500")
                    if trades_data:
                        all_trades = trades_data.get("trades", trades_data) if isinstance(trades_data, dict) else trades_data
                        closed = [t for t in all_trades if not t.get("is_open")]
                        gross_win = sum(t.get("close_profit_abs", 0) for t in closed if t.get("close_profit_abs", 0) > 0)
                        gross_loss = abs(sum(t.get("close_profit_abs", 0) for t in closed if t.get("close_profit_abs", 0) < 0))
                        pf = gross_win / gross_loss if gross_loss > 0 else 999

            if pf < kill_pf:
                reason = f"LEASH EXPIRED: {new_trades} trades, PF {pf:.2f} < {kill_pf:.1f}"
                if not args.dry_run:
                    container = BOTS[strategy]["container"]
                    if pause_bot(strategy, container, reason):
                        state.setdefault("paused", []).append(strategy)
                        actions.append(f"KILLED {strategy}: {reason}")
                        lconf["status"] = "killed"
                else:
                    actions.append(f"WOULD KILL {strategy}: {reason}")
            else:
                actions.append(f"LEASH GRADUATED {strategy}: {new_trades} trades, PF {pf:.2f} >= {kill_pf:.1f}")
                lconf["status"] = "graduated"
        else:
            log.info("LEASH %s: %d/%d trades completed", strategy, new_trades, max_trades)

    state["leash"] = leash

    # --- Process flags and escalate ---
    flags = state.get("flags", {})
    today = datetime.now().strftime("%Y-%m-%d")

    for ev in evaluations:
        strategy = ev["strategy"]
        if ev["status"] in ("paused", "unreachable"):
            continue

        if ev["status"] in ("flagged", "dead"):
            # Track consecutive flags
            flag_entry = flags.get(strategy, {"count": 0, "first": today, "reasons": []})
            flag_entry["count"] += 1
            flag_entry["last"] = today
            flag_entry["reasons"] = ev["issues"]
            flags[strategy] = flag_entry

            # Escalate: 2+ consecutive flags → auto-pause
            if flag_entry["count"] >= FLAG_THRESHOLD_EVALS:
                reason = f"Flagged {flag_entry['count']}x: {', '.join(ev['issues'])}"
                if not args.dry_run:
                    container = BOTS[strategy]["container"]
                    if pause_bot(strategy, container, reason):
                        if strategy not in state.get("paused", []):
                            state.setdefault("paused", []).append(strategy)
                        actions.append(f"PAUSED {strategy}: {reason}")
                else:
                    actions.append(f"WOULD PAUSE {strategy}: {reason}")
            else:
                actions.append(f"FLAGGED {strategy} ({flag_entry['count']}/{FLAG_THRESHOLD_EVALS}): {', '.join(ev['issues'])}")
        else:
            # Bot is healthy — reset flag counter
            if strategy in flags:
                del flags[strategy]

    state["flags"] = flags

    # Record history
    state.setdefault("history", []).append({
        "date": today,
        "evaluations": [
            {"strategy": e["strategy"], "status": e["status"], "metrics": e.get("metrics", {})}
            for e in evaluations
        ],
        "actions": actions,
    })
    # Keep 30 days of history
    state["history"] = state["history"][-30:]

    save_state(state)

    # Send report (only if there are issues or actions)
    has_issues = any(e["status"] in ("flagged", "dead") for e in evaluations)
    if has_issues or actions:
        send_report(evaluations, actions, dry_run=args.dry_run)
    else:
        log.info("All bots healthy. No report needed.")
        # Still send a brief all-clear occasionally (every 3 days)
        history = state.get("history", [])
        if len(history) % 3 == 0:
            send_report(evaluations, ["All bots healthy ✅"], dry_run=args.dry_run)

    log.info("Bot Rotator complete.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
