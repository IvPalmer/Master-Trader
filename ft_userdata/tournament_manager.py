#!/usr/bin/env python3
"""
Strategy Tournament Manager for Freqtrade
==========================================

Monitors all Freqtrade bot instances, tracks performance metrics,
ranks strategies, and dynamically reallocates capital to the best performers.

Usage:
    python tournament_manager.py              # Full run: rank, reallocate, report
    python tournament_manager.py --dry-run    # Show what would happen, no changes
    python tournament_manager.py --report-only # Just send Telegram report

Cron (weekly Sunday 00:00):
    0 0 * * 0 cd ~/ft_userdata && python3 tournament_manager.py >> logs/tournament.log 2>&1

Cron (report-only mid-week Wednesday):
    0 12 * * 3 cd ~/ft_userdata && python3 tournament_manager.py --report-only >> logs/tournament.log 2>&1
"""

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOTS = {
    "ClucHAnix":                    {"port": 8080, "container": "ft-cluchanix"},
    # "CombinedBinHAndCluc":          {"port": 8081, "container": "ft-combinedbinhandcluc"},  # PAUSED
    "NASOSv5":                      {"port": 8082, "container": "ft-nasosv5"},
    "ElliotV5":                     {"port": 8083, "container": "ft-elliotv5"},
    "SupertrendStrategy":           {"port": 8084, "container": "ft-supertrendstrategy"},
    # "DoubleEMACrossoverWithTrend":  {"port": 8085, "container": "ft-doubleemacrossoverwithtrend"},  # PAUSED
    "MasterTraderV1":               {"port": 8086, "container": "ft-mastertraderv1"},
    "MasterTraderAI":               {"port": 8087, "container": "ft-mastertraderai"},
    "BollingerRSIMeanReversion":    {"port": 8089, "container": "ft-bollinger-rsi"},
    # "NostalgiaForInfinityX6":       {"port": 8089, "container": "ft-nostalgiaforinfinityx6"},  # KILLED — 0 trades
}

API_USER = "freqtrader"
API_PASS = "mastertrader"
BASE_URL = "http://127.0.0.1"

TOTAL_CAPITAL = 7000.0
MIN_ALLOC_PCT = 0.05       # 5%  -> $350
MAX_ALLOC_PCT = 0.30       # 30% -> $2100
MIN_ALLOC = TOTAL_CAPITAL * MIN_ALLOC_PCT
MAX_ALLOC = TOTAL_CAPITAL * MAX_ALLOC_PCT

ROLLING_DAYS = 30
WIN_RATE_WINDOW = 50
NEW_STRATEGY_DAYS = 7
PAUSE_NEGATIVE_SHARPE_DAYS = 5
EMA_SPAN = 14              # EMA span for return smoothing

# Health-score integration
HEALTH_PAUSE_THRESHOLD = 30         # Auto-pause if health score below this
HEALTH_REDUCE_THRESHOLD = 50        # Reduce allocation if health score below this
HEALTH_REDUCE_FACTOR = 0.5          # Multiply allocation by this when score is low
HEALTH_PAUSE_CONSECUTIVE_DAYS = 3   # Pause after N consecutive days below threshold

CONFIGS_DIR = Path.home() / "ft_userdata" / "user_data" / "configs"
LOGS_DIR = Path.home() / "ft_userdata" / "logs"
STATE_FILE = Path.home() / "ft_userdata" / "tournament_state.json"
HEALTH_STATE_FILE = Path.home() / "ft_userdata" / "health_report_state.json"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "tournament.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("tournament")

# ---------------------------------------------------------------------------
# Freqtrade API Client
# ---------------------------------------------------------------------------

class FreqtradeAPI:
    """Minimal Freqtrade REST API client with session-based auth."""

    def __init__(self, strategy: str, port: int):
        self.strategy = strategy
        self.port = port
        self.base = f"{BASE_URL}:{port}/api/v1"
        self.session = requests.Session()
        self._token: Optional[str] = None

    def _login(self) -> bool:
        try:
            r = self.session.post(
                f"{self.base}/token/login",
                auth=(API_USER, API_PASS),
                timeout=10,
            )
            if r.status_code == 200:
                self._token = r.json().get("access_token")
                self.session.headers.update({"Authorization": f"Bearer {self._token}"})
                return True
            log.warning("Login failed for %s (port %d): HTTP %d", self.strategy, self.port, r.status_code)
            return False
        except requests.ConnectionError:
            log.warning("Cannot connect to %s (port %d) - bot may be down", self.strategy, self.port)
            return False
        except Exception as e:
            log.error("Login error for %s: %s", self.strategy, e)
            return False

    def _get(self, endpoint: str, params: dict | None = None) -> Optional[dict | list]:
        if self._token is None and not self._login():
            return None
        try:
            r = self.session.get(f"{self.base}/{endpoint}", params=params, timeout=15)
            if r.status_code == 401:
                # Token expired, retry login
                if self._login():
                    r = self.session.get(f"{self.base}/{endpoint}", params=params, timeout=15)
                else:
                    return None
            if r.status_code == 200:
                return r.json()
            log.warning("GET %s on %s returned %d", endpoint, self.strategy, r.status_code)
            return None
        except Exception as e:
            log.error("API error %s/%s: %s", self.strategy, endpoint, e)
            return None

    def get_trades(self, limit: int = 500) -> Optional[list]:
        data = self._get("trades", params={"limit": limit})
        if data and "trades" in data:
            return data["trades"]
        return data if isinstance(data, list) else None

    def get_profit(self) -> Optional[dict]:
        return self._get("profit")

    def get_status(self) -> Optional[list]:
        return self._get("status")

    def get_show_config(self) -> Optional[dict]:
        return self._get("show_config")

    def get_balance(self) -> Optional[dict]:
        return self._get("balance")


# ---------------------------------------------------------------------------
# Metrics Calculation
# ---------------------------------------------------------------------------

def parse_trade_date(date_str: str) -> datetime:
    """Parse Freqtrade date string to datetime."""
    if date_str is None:
        return datetime.now(timezone.utc)
    # Freqtrade returns dates like "2026-03-01 12:34:56" or ISO format
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Try ISO with timezone
    try:
        return datetime.fromisoformat(date_str)
    except Exception:
        return datetime.now(timezone.utc)


def compute_metrics(trades: list, strategy: str) -> dict:
    """Compute performance metrics from trade history."""

    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=ROLLING_DAYS)

    # Filter closed trades only
    closed = [t for t in trades if t.get("close_date") is not None]
    if not closed:
        return {
            "strategy": strategy,
            "total_trades": 0,
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "total_profit_pct": 0.0,
            "days_active": 0,
            "is_new": True,
            "consecutive_neg_sharpe_days": 0,
            "daily_returns": [],
        }

    # Sort by close date
    closed.sort(key=lambda t: t.get("close_date", ""))

    first_trade_date = parse_trade_date(closed[0].get("open_date"))
    days_active = (now - first_trade_date).days
    is_new = days_active < NEW_STRATEGY_DAYS

    # --- Total profit % ---
    total_profit_pct = sum(t.get("profit_ratio", 0.0) * 100 for t in closed)

    # --- Recent trades (30 days) ---
    recent = [t for t in closed if parse_trade_date(t.get("close_date")) >= cutoff_30d]

    # --- Daily returns for Sharpe ---
    daily_returns = _compute_daily_returns(recent, cutoff_30d, now)

    # --- Rolling 30-day Sharpe ratio ---
    sharpe = _sharpe_ratio(daily_returns)

    # --- Win rate (last N trades) ---
    last_n = closed[-WIN_RATE_WINDOW:]
    wins = sum(1 for t in last_n if t.get("profit_ratio", 0) > 0)
    win_rate = (wins / len(last_n)) * 100 if last_n else 0.0

    # --- Max drawdown (30 days) ---
    max_dd = _max_drawdown(recent)

    # --- Profit factor ---
    gross_profit = sum(t.get("profit_ratio", 0) for t in recent if t.get("profit_ratio", 0) > 0)
    gross_loss = abs(sum(t.get("profit_ratio", 0) for t in recent if t.get("profit_ratio", 0) < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

    # --- Consecutive negative Sharpe days ---
    neg_sharpe_days = _check_negative_sharpe_streak(closed, now)

    return {
        "strategy": strategy,
        "total_trades": len(closed),
        "recent_trades": len(recent),
        "sharpe_ratio": round(sharpe, 3),
        "win_rate": round(win_rate, 1),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "days_active": days_active,
        "is_new": is_new,
        "consecutive_neg_sharpe_days": neg_sharpe_days,
        "daily_returns": daily_returns,
    }


def _compute_daily_returns(trades: list, start: datetime, end: datetime) -> list[float]:
    """Aggregate trades into daily return percentages."""
    if not trades:
        return []

    num_days = max(1, (end - start).days)
    daily = {}

    for t in trades:
        close_dt = parse_trade_date(t.get("close_date"))
        day_key = close_dt.strftime("%Y-%m-%d")
        daily[day_key] = daily.get(day_key, 0.0) + t.get("profit_ratio", 0.0) * 100

    # Fill in zero-return days
    returns = []
    for i in range(num_days):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        returns.append(daily.get(day, 0.0))

    return returns


def _sharpe_ratio(daily_returns: list[float], risk_free_daily: float = 0.0) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(daily_returns) < 3:
        return 0.0
    arr = np.array(daily_returns)
    excess = arr - risk_free_daily
    mean = np.mean(excess)
    std = np.std(excess, ddof=1)
    if std == 0 or np.isnan(std):
        return 0.0 if mean == 0 else (5.0 if mean > 0 else -5.0)
    return float((mean / std) * np.sqrt(365))


def _max_drawdown(trades: list) -> float:
    """Max drawdown percentage from a list of trades."""
    if not trades:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.get("profit_ratio", 0.0) * 100
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _check_negative_sharpe_streak(trades: list, now: datetime) -> int:
    """Check how many consecutive recent days have a negative rolling Sharpe."""
    # We check the rolling 7-day Sharpe going back day by day
    streak = 0
    for days_back in range(1, 60):
        window_end = now - timedelta(days=days_back - 1)
        window_start = window_end - timedelta(days=7)
        window_trades = [
            t for t in trades
            if t.get("close_date") and window_start <= parse_trade_date(t["close_date"]) <= window_end
        ]
        if not window_trades:
            continue
        dr = _compute_daily_returns(window_trades, window_start, window_end)
        s = _sharpe_ratio(dr)
        if s < 0:
            streak += 1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Ranking & Allocation
# ---------------------------------------------------------------------------

def compute_composite_score(m: dict) -> float:
    """
    Composite score from metrics for ranking.

    Weights:
        Profit/DD ratio: 25% (primary quality metric — Net Profit % / Max Drawdown %)
        Sharpe ratio:    25%
        Profit factor:   20%
        Win rate:        15%
        Total profit:    15%
    """
    sharpe_score = np.clip(m["sharpe_ratio"] / 3.0, -1, 1)       # Normalize: 3.0 = perfect
    wr_score = np.clip((m["win_rate"] - 40) / 30, 0, 1)          # 40-70% mapped to 0-1
    pf_score = np.clip((m["profit_factor"] - 0.5) / 2.5, 0, 1)   # 0.5-3.0 mapped to 0-1
    profit_score = np.clip(m["total_profit_pct"] / 10.0, -1, 1)   # +/-10% mapped to +/-1

    # Profit/Drawdown ratio: Net Profit % / Max Drawdown %
    # Higher is better. 5.0+ is excellent, 1.0 is break-even risk/reward
    max_dd = m.get("max_drawdown", 0)
    if max_dd > 0:
        profit_dd_ratio = m["total_profit_pct"] / max_dd
    else:
        profit_dd_ratio = m["total_profit_pct"] * 2 if m["total_profit_pct"] > 0 else 0
    pdd_score = np.clip(profit_dd_ratio / 5.0, -1, 1)  # 5.0 ratio = perfect score

    score = (
        0.25 * pdd_score
        + 0.25 * sharpe_score
        + 0.20 * pf_score
        + 0.15 * wr_score
        + 0.15 * profit_score
    )
    return float(score)


def _load_health_scores() -> dict[str, dict]:
    """Load latest health scores from strategy_health_report.py state file."""
    if not HEALTH_STATE_FILE.exists():
        return {}
    try:
        with open(HEALTH_STATE_FILE) as f:
            state = json.load(f)
        return state.get("bots", {})
    except Exception as e:
        log.warning("Could not load health scores: %s", e)
        return {}


def _load_health_history() -> dict[str, list[int]]:
    """Load historical health scores from tournament state to detect consecutive bad days."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        return state.get("health_history", {})
    except Exception:
        return {}


def compute_allocations(metrics_list: list[dict]) -> dict[str, float]:
    """
    Compute dollar allocations for each strategy using EMA-weighted risk-adjusted returns.
    Integrates health scores for auto-pause and allocation reduction.

    Returns dict of {strategy_name: dollar_allocation}.
    """
    active = []
    paused = []
    reduced = []  # Strategies with reduced allocation due to health

    # Load health scores from daily health report
    health_scores = _load_health_scores()
    health_history = _load_health_history()

    for m in metrics_list:
        strategy = m["strategy"]
        health = health_scores.get(strategy, {})
        h_score = health.get("health_score", 100)  # Default healthy if no data

        # Track consecutive days below pause threshold
        h_hist = health_history.get(strategy, [])
        h_hist.append(h_score)
        health_history[strategy] = h_hist[-30:]  # Keep 30 days max

        # Count consecutive days below pause threshold
        consecutive_bad = 0
        for s in reversed(h_hist):
            if s < HEALTH_PAUSE_THRESHOLD:
                consecutive_bad += 1
            else:
                break

        # Auto-pause: health score critical for N consecutive days
        if consecutive_bad >= HEALTH_PAUSE_CONSECUTIVE_DAYS and not m["is_new"]:
            paused.append(strategy)
            log.info("PAUSED %s: health score %d for %d consecutive days",
                     strategy, h_score, consecutive_bad)
            continue

        # Pause strategies with persistent negative Sharpe
        if m["consecutive_neg_sharpe_days"] >= PAUSE_NEGATIVE_SHARPE_DAYS and not m["is_new"]:
            paused.append(strategy)
            log.info("PAUSED %s: negative Sharpe for %d days", strategy, m["consecutive_neg_sharpe_days"])
            continue

        # Flag for allocation reduction
        if h_score < HEALTH_REDUCE_THRESHOLD and not m["is_new"]:
            reduced.append(strategy)
            log.info("REDUCED %s: health score %d < %d threshold",
                     strategy, h_score, HEALTH_REDUCE_THRESHOLD)

        active.append(m)

    if not active:
        log.warning("All strategies paused! Reverting to equal allocation for all.")
        active = metrics_list

    # New strategies get equal share; compute raw scores for the rest
    new_strats = [m for m in active if m["is_new"]]
    established = [m for m in active if not m["is_new"]]

    allocations: dict[str, float] = {}

    # Reserve equal share for new strategies
    num_active = len(active)
    if new_strats:
        equal_share = TOTAL_CAPITAL / num_active
        for m in new_strats:
            allocations[m["strategy"]] = equal_share

    # For established strategies, use EMA-weighted score
    if established:
        scores = {}
        for m in established:
            # EMA of daily returns
            dr = m.get("daily_returns", [])
            if len(dr) >= 2:
                ema_return = _ema(dr, EMA_SPAN)
            else:
                ema_return = np.mean(dr) if dr else 0.0

            # Risk-adjusted: EMA return / (1 + max_drawdown)
            risk_adj = ema_return / (1 + m["max_drawdown"] / 100.0)

            # Blend with composite score
            composite = compute_composite_score(m)
            scores[m["strategy"]] = 0.6 * composite + 0.4 * np.clip(risk_adj, -1, 1)

        # Shift scores to be positive for allocation (softmax-like)
        min_score = min(scores.values())
        shifted = {s: v - min_score + 0.01 for s, v in scores.items()}
        total_score = sum(shifted.values())

        # Capital left after new strategy allocations
        capital_for_new = sum(allocations.values())
        remaining_capital = TOTAL_CAPITAL - capital_for_new

        for strat, score in shifted.items():
            raw_alloc = (score / total_score) * remaining_capital
            allocations[strat] = raw_alloc

    # Apply health-based reduction before clamping
    for strat in reduced:
        if strat in allocations:
            old_alloc = allocations[strat]
            allocations[strat] = old_alloc * HEALTH_REDUCE_FACTOR
            log.info("  %s: reduced $%.0f -> $%.0f (health penalty)",
                     strat, old_alloc, allocations[strat])

    # Enforce min/max constraints (iterative clamping)
    allocations = _clamp_allocations(allocations)

    # Paused strategies get 0
    for strat in paused:
        allocations[strat] = 0.0

    return allocations


def _ema(data: list[float], span: int) -> float:
    """Compute the last value of exponential moving average."""
    if not data:
        return 0.0
    alpha = 2.0 / (span + 1)
    ema_val = data[0]
    for val in data[1:]:
        ema_val = alpha * val + (1 - alpha) * ema_val
    return float(ema_val)


def _clamp_allocations(allocs: dict[str, float]) -> dict[str, float]:
    """Clamp allocations to min/max bounds and redistribute excess."""
    active_strats = {s: v for s, v in allocs.items() if v > 0}
    if not active_strats:
        return allocs

    for _ in range(10):  # Iterate until stable
        changed = False
        total = sum(active_strats.values())
        if total == 0:
            break

        # Scale to total capital
        factor = TOTAL_CAPITAL / total
        active_strats = {s: v * factor for s, v in active_strats.items()}

        excess = 0.0
        unclamped = {}
        for s, v in active_strats.items():
            if v < MIN_ALLOC:
                excess += MIN_ALLOC - v
                active_strats[s] = MIN_ALLOC
                changed = True
            elif v > MAX_ALLOC:
                excess += v - MAX_ALLOC  # This is negative excess (give back)
                active_strats[s] = MAX_ALLOC
                changed = True
            else:
                unclamped[s] = v

        if not changed or not unclamped:
            break

        # Redistribute excess among unclamped
        unc_total = sum(unclamped.values())
        if unc_total > 0:
            for s in unclamped:
                # Negative excess = we capped highs, distribute the remainder
                active_strats[s] -= excess * (unclamped[s] / unc_total)

    # Final normalization to exactly TOTAL_CAPITAL
    total = sum(active_strats.values())
    if total > 0:
        factor = TOTAL_CAPITAL / total
        active_strats = {s: round(v * factor, 2) for s, v in active_strats.items()}

    # Merge back
    result = dict(allocs)
    result.update(active_strats)
    return result


# ---------------------------------------------------------------------------
# Config Update & Docker
# ---------------------------------------------------------------------------

def update_config_wallet(strategy: str, new_wallet: float) -> bool:
    """Update dry_run_wallet in a strategy's config file."""
    config_path = CONFIGS_DIR / f"{strategy}.json"
    if not config_path.exists():
        log.error("Config not found: %s", config_path)
        return False

    try:
        with open(config_path, "r") as f:
            config = json.load(f)

        old_wallet = config.get("dry_run_wallet", 1000)
        config["dry_run_wallet"] = round(new_wallet, 2)

        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
            f.write("\n")

        log.info("Updated %s: $%.2f -> $%.2f", strategy, old_wallet, new_wallet)
        return True
    except Exception as e:
        log.error("Failed to update config %s: %s", strategy, e)
        return False


def restart_bot(container: str) -> bool:
    """Restart a bot's Docker container."""
    try:
        result = subprocess.run(
            ["docker", "restart", container],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            log.info("Restarted container: %s", container)
            return True
        else:
            log.error("Failed to restart %s: %s", container, result.stderr)
            return False
    except Exception as e:
        log.error("Docker restart error for %s: %s", container, e)
        return False


# ---------------------------------------------------------------------------
# Telegram Webhook Report
# ---------------------------------------------------------------------------

def send_telegram_report(
    rankings: list[dict],
    allocations: dict[str, float],
    total_profit_pct: float,
    total_portfolio_value: float,
    dry_run: bool = False,
) -> bool:
    """Send a formatted report via the Freqtrade webhook."""

    lines = []
    mode_tag = " [DRY RUN]" if dry_run else ""
    lines.append(f"\U0001f4ca Weekly Strategy Tournament{mode_tag}")
    lines.append("")
    lines.append("\U0001f3c6 Rankings:")

    health_scores = _load_health_scores()
    for i, r in enumerate(rankings, 1):
        emoji = ["\U0001f947", "\U0001f948", "\U0001f949"][i - 1] if i <= 3 else f"{i}."
        sharpe_str = f"{r['sharpe_ratio']:+.1f}" if r["sharpe_ratio"] != 0 else "N/A"
        h_score = health_scores.get(r['strategy'], {}).get('health_score', '?')
        lines.append(
            f"{emoji} {r['strategy']}: {r['total_profit_pct']:+.1f}% | "
            f"Sharpe: {sharpe_str} | WR: {r['win_rate']:.0f}% | Health: {h_score}/100"
        )

    lines.append("")
    lines.append("\U0001f4b0 New Allocations:")

    for strat in sorted(allocations, key=lambda s: allocations[s], reverse=True):
        amt = allocations[strat]
        pct = (amt / TOTAL_CAPITAL) * 100 if amt > 0 else 0
        if amt == 0:
            lines.append(f"  {strat}: PAUSED")
        else:
            lines.append(f"  {strat}: ${amt:,.0f} ({pct:.0f}%)")

    lines.append("")
    lines.append(f"\U0001f4c8 Total Portfolio: {total_profit_pct:+.1f}% (${total_portfolio_value:,.0f})")

    message = "\n".join(lines)

    # Send via webhook
    try:
        payload = {"type": "status", "status": message}
        r = requests.post(WEBHOOK_URL, data=payload, timeout=10)
        if r.status_code in (200, 201, 204):
            log.info("Telegram report sent successfully")
            return True
        else:
            log.warning("Webhook returned HTTP %d: %s", r.status_code, r.text[:200])
            return False
    except requests.ConnectionError:
        log.warning("Cannot reach webhook at %s - report not sent", WEBHOOK_URL)
        return False
    except Exception as e:
        log.error("Webhook error: %s", e)
        return False


# ---------------------------------------------------------------------------
# State Persistence
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load persistent state (last run time, historical scores, etc.)."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_run": None, "history": {}}


def save_state(state: dict):
    """Save persistent state."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    except Exception as e:
        log.error("Failed to save state: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Strategy Tournament Manager for Freqtrade")
    parser.add_argument("--dry-run", action="store_true", help="Show report without applying changes")
    parser.add_argument("--report-only", action="store_true", help="Just send Telegram report, no reallocation")
    parser.add_argument("--no-restart", action="store_true", help="Update configs but don't restart bots")
    parser.add_argument("--force", action="store_true", help="Force run even if not enough time since last run")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Strategy Tournament Manager - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Mode: %s", "DRY RUN" if args.dry_run else ("REPORT ONLY" if args.report_only else "LIVE"))
    log.info("=" * 60)

    state = load_state()

    # ------------------------------------------------------------------
    # 1. Connect to all bots and pull trade data
    # ------------------------------------------------------------------
    all_metrics: list[dict] = []
    bot_errors: list[str] = []

    for strategy, info in BOTS.items():
        port = info["port"]
        log.info("Connecting to %s (port %d)...", strategy, port)

        api = FreqtradeAPI(strategy, port)
        trades = api.get_trades(limit=500)

        if trades is None:
            bot_errors.append(strategy)
            log.warning("Skipping %s - could not retrieve trades", strategy)
            continue

        profit_data = api.get_profit()

        metrics = compute_metrics(trades, strategy)

        # Enrich with API profit data if available
        if profit_data:
            api_profit = profit_data.get("profit_all_coin", 0)
            if api_profit and metrics["total_profit_pct"] == 0:
                metrics["total_profit_pct"] = round(
                    profit_data.get("profit_all_ratio_mean", 0) * 100 * metrics["total_trades"], 2
                )

        metrics["composite_score"] = compute_composite_score(metrics)
        all_metrics.append(metrics)
        log.info(
            "  %s: %d trades | Sharpe: %.2f | WR: %.1f%% | PF: %.2f | Profit: %+.2f%%",
            strategy, metrics["total_trades"], metrics["sharpe_ratio"],
            metrics["win_rate"], metrics["profit_factor"], metrics["total_profit_pct"],
        )

    if not all_metrics:
        log.error("No bots reachable! Aborting.")
        sys.exit(1)

    if bot_errors:
        log.warning("Unreachable bots: %s", ", ".join(bot_errors))

    # ------------------------------------------------------------------
    # 2. Rank strategies by composite score
    # ------------------------------------------------------------------
    rankings = sorted(all_metrics, key=lambda m: m["composite_score"], reverse=True)
    log.info("")
    log.info("--- RANKINGS ---")
    for i, r in enumerate(rankings, 1):
        log.info(
            "  #%d  %-30s  Score: %+.3f  Sharpe: %+.2f  WR: %.0f%%  PF: %.1f  DD: %.1f%%",
            i, r["strategy"], r["composite_score"], r["sharpe_ratio"],
            r["win_rate"], r["profit_factor"], r["max_drawdown"],
        )

    # ------------------------------------------------------------------
    # 3. Compute allocations
    # ------------------------------------------------------------------
    allocations = compute_allocations(all_metrics)

    log.info("")
    log.info("--- ALLOCATIONS ---")
    for strat in sorted(allocations, key=lambda s: allocations[s], reverse=True):
        amt = allocations[strat]
        pct = (amt / TOTAL_CAPITAL) * 100 if amt > 0 else 0
        log.info("  %-30s  $%7.2f  (%5.1f%%)", strat, amt, pct)
    log.info("  %-30s  $%7.2f", "TOTAL", sum(allocations.values()))

    # ------------------------------------------------------------------
    # 4. Calculate total portfolio performance
    # ------------------------------------------------------------------
    weighted_profit = 0.0
    total_bots = 0
    for m in all_metrics:
        weighted_profit += m["total_profit_pct"]
        total_bots += 1
    avg_profit = weighted_profit / total_bots if total_bots > 0 else 0
    portfolio_value = TOTAL_CAPITAL * (1 + avg_profit / 100.0)

    # ------------------------------------------------------------------
    # 5. Send Telegram report
    # ------------------------------------------------------------------
    send_telegram_report(rankings, allocations, avg_profit, portfolio_value, dry_run=args.dry_run)

    if args.report_only or args.dry_run:
        if args.dry_run:
            log.info("DRY RUN complete - no changes applied.")
        else:
            log.info("REPORT ONLY complete - no reallocation.")
        save_state({
            "last_run": datetime.now(timezone.utc).isoformat(),
            "last_mode": "dry_run" if args.dry_run else "report_only",
            "history": state.get("history", {}),
        })
        return

    # ------------------------------------------------------------------
    # 6. Apply allocations: update configs
    # ------------------------------------------------------------------
    log.info("")
    log.info("--- APPLYING ALLOCATIONS ---")
    updated = []
    for strategy, amount in allocations.items():
        if amount == 0:
            log.info("Skipping %s (paused)", strategy)
            continue
        if strategy not in BOTS:
            log.warning("Unknown strategy %s, skipping config update", strategy)
            continue
        if update_config_wallet(strategy, amount):
            updated.append(strategy)

    # ------------------------------------------------------------------
    # 7. Restart bots (unless --no-restart)
    # ------------------------------------------------------------------
    if not args.no_restart and updated:
        log.info("")
        log.info("--- RESTARTING BOTS ---")
        # Stagger restarts to avoid overwhelming the system
        for strategy in updated:
            container = BOTS[strategy]["container"]
            restart_bot(container)
            time.sleep(3)  # Brief pause between restarts
    elif args.no_restart:
        log.info("Skipping restarts (--no-restart flag)")
    else:
        log.info("No bots to restart")

    # ------------------------------------------------------------------
    # 8. Save state
    # ------------------------------------------------------------------
    history = state.get("history", {})
    run_key = datetime.now().strftime("%Y-%m-%d")
    history[run_key] = {
        "allocations": {s: round(v, 2) for s, v in allocations.items()},
        "rankings": [
            {"strategy": r["strategy"], "score": r["composite_score"],
             "sharpe": r["sharpe_ratio"], "profit": r["total_profit_pct"]}
            for r in rankings
        ],
        "portfolio_profit_pct": round(avg_profit, 2),
    }
    # Keep only last 52 weeks of history
    if len(history) > 52:
        oldest_keys = sorted(history.keys())[:len(history) - 52]
        for k in oldest_keys:
            del history[k]

    # Persist health history for consecutive-day tracking
    health_history = _load_health_history()
    health_scores = _load_health_scores()
    for strat in BOTS:
        h = health_scores.get(strat, {})
        h_score = h.get("health_score", 100)
        hist = health_history.get(strat, [])
        # Only append if we haven't already for today
        today_key = datetime.now().strftime("%Y-%m-%d")
        if not hist or len(hist) < 1:
            hist.append(h_score)
        health_history[strat] = hist[-30:]

    save_state({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "last_mode": "live",
        "history": history,
        "health_history": health_history,
    })

    log.info("")
    log.info("Tournament Manager run complete.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
