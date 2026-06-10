#!/usr/bin/env python3
"""
Strategy Health Report
======================

Daily automated analysis of all Freqtrade bots. Computes health scores,
flags issues, and sends a structured Telegram report.

Usage:
    python strategy_health_report.py              # Full report to Telegram
    python strategy_health_report.py --stdout      # Print to stdout only
    python strategy_health_report.py --json        # Output raw JSON metrics

Cron (daily 23:00 UTC = 20:00 São Paulo):
    0 23 * * * cd ~/ft_userdata && python3 strategy_health_report.py >> logs/health_report.log 2>&1
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth


def _load_dotenv() -> None:
    """Load .env from repo root so rotated FREQTRADE__ creds propagate when the
    script is invoked without the shell having sourced .env first (cron, ad-hoc,
    double-click). setdefault preserves any explicit shell-level overrides."""
    for root in (Path.home() / "Work/Dev/master-trader", Path(__file__).resolve().parent.parent):
        env_file = root / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v)
            return


_load_dotenv()

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
        # Extract only active bots, keeping port/timeframe/type fields
        return {
            name: {k: v for k, v in info.items() if k != "active"}
            for name, info in data["bots"].items()
            if info.get("active", True)
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {
            "SupertrendStrategy":     {"port": 8084, "timeframe": "1h", "type": "trend-follower"},
            "MasterTraderV1":         {"port": 8086, "timeframe": "1h", "type": "hybrid"},
            "AlligatorTrendV1":       {"port": 8091, "timeframe": "1d", "type": "trend-follower"},
            "GaussianChannelV1":      {"port": 8092, "timeframe": "1d", "type": "trend-follower"},
            "BearCrashShortV1":       {"port": 8093, "timeframe": "1h", "type": "bear-short"},
            "BollingerBounceV1":      {"port": 8094, "timeframe": "1h", "type": "mean-reversion"},
        }

BOTS = _load_bots_config()

API_USER = os.environ.get("FREQTRADE__API_SERVER__USERNAME", "freqtrader")
API_PASS = os.environ.get("FREQTRADE__API_SERVER__PASSWORD", "mastertrader")
AUTH = HTTPBasicAuth(API_USER, API_PASS)
INITIAL_CAPITAL = 528.0   # 6x R$500/bot = R$3,000 = $528 USDT
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "http://localhost:8088/webhooks/freqtrade")
FT_DIR = Path(os.environ.get("FT_DIR", str(Path.home() / "ft_userdata")))
DB_DIR = FT_DIR / "user_data"
STATE_FILE = FT_DIR / "health_report_state.json"
LOGS_DIR = FT_DIR / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

def _setup_logging(json_mode: bool = False) -> logging.Logger:
    """Configure logging. In --json mode, console logs go to stderr to keep stdout clean."""
    stream = sys.stderr if json_mode else sys.stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "health_report.log"),
            logging.StreamHandler(stream),
        ],
    )
    return logging.getLogger("health-report")


# Placeholder — replaced in main() after arg parsing
log = logging.getLogger("health-report")

# ---------------------------------------------------------------------------
# Health Score Thresholds
# ---------------------------------------------------------------------------

# A strategy is HEALTHY if:
#   - Win rate >= 55% (or >= 30% for trend-followers with R:R >= 2.0)
#   - Risk/reward ratio >= 1.0 (avg_win / avg_loss)
#   - Profit factor >= 1.0
#   - Force-exit rate < 20% of total exits
#   - No single trade > 30% of total loss
#
# Health score: 0-100
#   90-100: Excellent
#   70-89:  Good
#   50-69:  Warning
#   30-49:  Poor
#   0-29:   Critical — recommend pausing
#
# IMPORTANT: Scores are discounted when sample size < 10 trades (insufficient data)
# Strategy type affects win rate expectations:
#   - trend-follower: low WR (30-40%) is normal if R:R >= 2.0
#   - dip-buyer / mean-reversion: expect WR >= 55%

# Minimum trades for a score to be considered reliable
MIN_TRADES_RELIABLE = 10

SCORE_WEIGHTS = {
    "win_rate": 20,          # Max 20 points
    "risk_reward": 25,       # Max 25 points
    "profit_factor": 20,     # Max 20 points
    "exit_quality": 15,      # Max 15 points (low force-exit rate)
    "consistency": 10,       # Max 10 points (low variance in returns)
    "activity": 10,          # Max 10 points (trading regularly)
}


# ---------------------------------------------------------------------------
# Data Collection
# ---------------------------------------------------------------------------

def fetch_json(port: int, endpoint: str, timeout: int = 10) -> Optional[Any]:
    """Fetch JSON from Freqtrade API with retry logic."""
    return _api_get_with_retry(port, endpoint, timeout=timeout)


def get_trades_from_api(port: int, limit: int = 500) -> Optional[list]:
    data = fetch_json(port, f"trades?limit={limit}")
    if data and "trades" in data:
        return data["trades"]
    return data if isinstance(data, list) else None


def get_open_trades(port: int) -> Optional[list]:
    return fetch_json(port, "status")


def get_profit_data(port: int) -> Optional[dict]:
    return fetch_json(port, "profit")


def get_bot_config(port: int) -> Optional[dict]:
    return fetch_json(port, "show_config")


# ---------------------------------------------------------------------------
# Metrics Computation
# ---------------------------------------------------------------------------

def compute_bot_metrics(strategy: str, info: dict) -> dict:
    """Compute comprehensive metrics for a single bot."""
    port = info["port"]
    metrics = {
        "strategy": strategy,
        "timeframe": info["timeframe"],
        "type": info["type"],
        "online": False,
        "health_score": 0,
        "health_label": "OFFLINE",
        "flags": [],
        "recommendations": [],
    }

    # Fetch data
    trades = get_trades_from_api(port)
    open_trades = get_open_trades(port)
    profit_data = get_profit_data(port)

    if trades is None:
        metrics["flags"].append("Bot unreachable")
        return metrics

    metrics["online"] = True

    # Separate closed vs open
    closed = [t for t in trades if t.get("close_date") is not None]
    open_list = open_trades if isinstance(open_trades, list) else []

    metrics["total_trades"] = len(closed)
    metrics["open_trades"] = len(open_list)

    if not closed:
        metrics["health_label"] = "NO DATA"
        metrics["flags"].append("Zero closed trades")
        if len(open_list) == 0:
            metrics["recommendations"].append("Investigate: no trades taken. Check pairlist/entry conditions.")
        return metrics

    # --- P&L ---
    closed_pnl = sum((t.get("profit_abs", 0) or 0) for t in closed)
    open_pnl = sum((t.get("profit_abs", 0) or 0) for t in open_list)
    true_pnl = closed_pnl + open_pnl

    metrics["closed_pnl"] = round(closed_pnl, 2)
    metrics["open_pnl"] = round(open_pnl, 2)
    metrics["true_pnl"] = round(true_pnl, 2)

    # --- Win Rate ---
    winners = [t for t in closed if t.get("profit_ratio", 0) > 0]
    losers = [t for t in closed if t.get("profit_ratio", 0) <= 0]
    win_rate = len(winners) / len(closed) * 100 if closed else 0
    metrics["win_rate"] = round(win_rate, 1)
    metrics["winners"] = len(winners)
    metrics["losers"] = len(losers)

    # --- Average Win vs Average Loss ---
    avg_win = sum((t.get("profit_abs", 0) or 0) for t in winners) / len(winners) if winners else 0
    avg_loss = abs(sum((t.get("profit_abs", 0) or 0) for t in losers) / len(losers)) if losers else 0
    risk_reward = avg_win / avg_loss if avg_loss > 0 else (10.0 if avg_win > 0 else 0)
    metrics["avg_win"] = round(avg_win, 2)
    metrics["avg_loss"] = round(avg_loss, 2)
    metrics["risk_reward"] = round(risk_reward, 2)

    # --- Profit Factor ---
    gross_profit = sum((t.get("profit_abs", 0) or 0) for t in winners)
    gross_loss = abs(sum((t.get("profit_abs", 0) or 0) for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0)
    metrics["profit_factor"] = round(profit_factor, 2)

    # --- Max Drawdown & Profit/Drawdown Ratio ---
    max_dd = 0.0
    if profit_data and isinstance(profit_data, dict):
        max_dd = abs(profit_data.get("max_drawdown", 0)) * 100  # Convert to percentage
    metrics["max_drawdown_pct"] = round(max_dd, 2)

    # Profit/Drawdown ratio: primary ranking metric (higher = better)
    # Formula: Net Profit % / Max Drawdown %
    closed_profit_pct = profit_data.get("profit_closed_percent_sum", 0) if profit_data else 0
    if max_dd > 0:
        profit_dd_ratio = abs(closed_profit_pct) / max_dd if closed_profit_pct > 0 else -(abs(closed_profit_pct) / max_dd)
    else:
        profit_dd_ratio = closed_profit_pct * 10 if closed_profit_pct > 0 else 0  # No DD = excellent
    metrics["profit_dd_ratio"] = round(profit_dd_ratio, 2)

    # --- Exit Reason Analysis ---
    exit_reasons = defaultdict(int)
    for t in closed:
        reason = t.get("exit_reason", "unknown")
        exit_reasons[reason] += 1
    metrics["exit_reasons"] = dict(exit_reasons)

    force_exits = exit_reasons.get("force_exit", 0) + exit_reasons.get("emergency_exit", 0)
    stoploss_exits = exit_reasons.get("stop_loss", 0) + exit_reasons.get("stoploss", 0)
    force_exit_rate = force_exits / len(closed) * 100 if closed else 0
    metrics["force_exit_rate"] = round(force_exit_rate, 1)

    # --- Trade Duration ---
    durations = []
    for t in closed:
        dur = t.get("trade_duration")
        if dur and isinstance(dur, (int, float)):
            durations.append(dur)
    if durations:
        metrics["avg_duration_min"] = round(sum(durations) / len(durations), 1)
        metrics["max_duration_min"] = round(max(durations), 1)
    else:
        metrics["avg_duration_min"] = 0
        metrics["max_duration_min"] = 0

    # --- Worst Single Trade ---
    if closed:
        worst = min(closed, key=lambda t: (t.get("profit_abs", 0) or 0))
        metrics["worst_trade"] = {
            "pair": worst.get("pair", "?"),
            "profit": round(worst.get("profit_abs", 0) or 0, 2),
            "pct": round(worst.get("profit_pct", 0) or 0, 1),
            "exit_reason": worst.get("exit_reason", "?"),
        }
        # Check if single trade dominates losses
        if gross_loss > 0:
            worst_pct_of_loss = abs(worst.get("profit_abs", 0) or 0) / gross_loss * 100
            metrics["worst_trade_loss_pct"] = round(worst_pct_of_loss, 1)

    # --- Return Consistency (daily returns std) ---
    daily_returns = _compute_daily_returns(closed)
    if len(daily_returns) >= 2:
        import statistics
        metrics["return_std"] = round(statistics.stdev(daily_returns), 4)
        metrics["return_mean"] = round(statistics.mean(daily_returns), 4)
    else:
        metrics["return_std"] = 0
        metrics["return_mean"] = 0

    # --- Recent Performance (last 24h) ---
    now = datetime.now(timezone.utc)
    last_24h = [t for t in closed if _parse_date(t.get("close_date")) >= now - timedelta(hours=24)]
    metrics["trades_24h"] = len(last_24h)
    metrics["pnl_24h"] = round(sum((t.get("profit_abs", 0) or 0) for t in last_24h), 2)

    # --- Open Position Health ---
    if open_list:
        worst_open = min(open_list, key=lambda t: (t.get("profit_abs", 0) or 0))
        metrics["worst_open"] = {
            "pair": worst_open.get("pair", "?"),
            "profit": round(worst_open.get("profit_abs", 0) or 0, 2),
            "pct": round(worst_open.get("profit_pct", 0) or 0, 1),
        }
        stale_trades = [t for t in open_list if _trade_age_hours(t) > 8]
        metrics["stale_positions"] = len(stale_trades)
    else:
        metrics["stale_positions"] = 0

    # --- Compute Health Score ---
    score = _compute_health_score(metrics)
    metrics["health_score"] = score
    metrics["health_label"] = _score_label(score, metrics.get("total_trades", 0))

    # --- Per-pair drift (last 30 days) ---
    metrics["pair_drift"] = _compute_pair_drift(closed, window_days=30)

    # --- Generate Flags and Recommendations ---
    _generate_flags(metrics)

    return metrics


def _compute_daily_returns(trades: list) -> list:
    daily = defaultdict(float)
    for t in trades:
        close_dt = _parse_date(t.get("close_date"))
        if close_dt:
            day = close_dt.strftime("%Y-%m-%d")
            daily[day] += (t.get("profit_abs", 0) or 0)
    return list(daily.values())


def _compute_pair_drift(closed_trades: list, window_days: int = 30) -> list[dict]:
    """Per-pair drift detection. Flags pairs with concerning loss patterns
    in the last `window_days` so the operator can review BEFORE the strategy
    accumulates more loss on a structurally weak pair (e.g. ARB-style
    "informed shorts" situations on FundingFade).

    Triggers (any of):
    - 3+ losses on the same pair in the window
    - Trailing 3-trade loss streak on the pair
    - Pair PF < 0.7 with at least 4 trades in the window

    Returns list of flagged pair dicts. Empty list = no drift.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for t in closed_trades:
        close_dt = _parse_date(t.get("close_date"))
        if not close_dt or close_dt < cutoff:
            continue
        by_pair[t.get("pair") or "?"].append(t)

    flagged: list[dict] = []
    for pair, plist in by_pair.items():
        # Sort newest first for streak detection
        plist_sorted = sorted(plist, key=lambda x: _parse_date(x.get("close_date")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        n = len(plist_sorted)
        wins = [t for t in plist_sorted if (t.get("profit_abs") or 0) > 0]
        losses = [t for t in plist_sorted if (t.get("profit_abs") or 0) <= 0]
        gross_win = sum((t.get("profit_abs") or 0) for t in wins)
        gross_loss = abs(sum((t.get("profit_abs") or 0) for t in losses))
        pf = (gross_win / gross_loss) if gross_loss > 0 else (10.0 if gross_win > 0 else 0)

        # Trailing loss streak: count consecutive losses from newest backward
        streak = 0
        for t in plist_sorted:
            if (t.get("profit_abs") or 0) <= 0:
                streak += 1
            else:
                break

        flags: list[str] = []
        if len(losses) >= 3:
            flags.append(f"{len(losses)} losses / {n} trades")
        if streak >= 3:
            flags.append(f"loss streak = {streak}")
        if n >= 4 and pf < 0.7:
            flags.append(f"pair PF {pf:.2f}")

        if flags:
            net_pnl = sum((t.get("profit_abs") or 0) for t in plist_sorted)
            flagged.append({
                "pair": pair,
                "trades": n,
                "wins": len(wins),
                "losses": len(losses),
                "pf": round(pf, 2),
                "loss_streak": streak,
                "net_pnl": round(net_pnl, 2),
                "flags": flags,
            })

    # Newest-first rough sort by absolute net PnL drag
    flagged.sort(key=lambda x: x["net_pnl"])
    return flagged


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(date_str)
    except Exception:
        return None


def _trade_age_hours(trade: dict) -> float:
    open_date = _parse_date(trade.get("open_date"))
    if not open_date:
        return 0
    return (datetime.now(timezone.utc) - open_date).total_seconds() / 3600


def _compute_health_score(m: dict) -> int:
    score = 0
    strategy_type = m.get("type", "unknown")
    is_trend_follower = strategy_type == "trend-follower"

    # Win rate scoring — adjusted by strategy type
    # Trend-followers: 30%+ WR with R:R >= 2.0 is perfectly healthy
    # Others: 55%+ expected
    wr = m.get("win_rate", 0)
    rr = m.get("risk_reward", 0)

    if is_trend_follower:
        # Trend-follower: score on combined WR * R:R (expectancy proxy)
        # 30% WR with 2.0 R:R = full points; scale down from there
        if wr >= 30 and rr >= 2.0:
            score += SCORE_WEIGHTS["win_rate"]
        elif wr >= 25 and rr >= 1.5:
            score += int(SCORE_WEIGHTS["win_rate"] * 0.7)
        elif wr >= 20:
            score += int(SCORE_WEIGHTS["win_rate"] * 0.3)
    else:
        if wr >= 55:
            score += SCORE_WEIGHTS["win_rate"]
        elif wr >= 30:
            score += int(SCORE_WEIGHTS["win_rate"] * (wr - 30) / 25)

    # Risk/reward: 1.5+ = full points, linear 0-1.5
    if rr >= 1.5:
        score += SCORE_WEIGHTS["risk_reward"]
    elif rr > 0:
        score += int(SCORE_WEIGHTS["risk_reward"] * min(rr / 1.5, 1.0))

    # Profit factor: 1.5+ = full, linear 0.5-1.5
    pf = m.get("profit_factor", 0)
    if pf >= 1.5:
        score += SCORE_WEIGHTS["profit_factor"]
    elif pf >= 0.5:
        score += int(SCORE_WEIGHTS["profit_factor"] * (pf - 0.5) / 1.0)

    # Exit quality: low force-exit rate = good
    fer = m.get("force_exit_rate", 0)
    if fer <= 5:
        score += SCORE_WEIGHTS["exit_quality"]
    elif fer <= 20:
        score += int(SCORE_WEIGHTS["exit_quality"] * (1 - (fer - 5) / 15))

    # Consistency: low return std relative to mean
    std = m.get("return_std", 0)
    mean = m.get("return_mean", 0)
    if std > 0 and mean != 0:
        cv = abs(std / mean) if mean != 0 else 999
        if cv < 1:
            score += SCORE_WEIGHTS["consistency"]
        elif cv < 3:
            score += int(SCORE_WEIGHTS["consistency"] * (1 - (cv - 1) / 2))

    # Activity: trading regularly (at least 1 trade/day for 5m, 1 trade/2 days for 1h)
    total = m.get("total_trades", 0)
    trades_24h = m.get("trades_24h", 0)
    if trades_24h >= 2:
        score += SCORE_WEIGHTS["activity"]
    elif trades_24h >= 1:
        score += SCORE_WEIGHTS["activity"] // 2
    elif total > 0:
        score += 2  # At least it has traded

    # --- Sample size discount ---
    # With < MIN_TRADES_RELIABLE trades, scores are unreliable.
    # Discount proportionally: 1 trade = 10% of score, 5 trades = 50%, 10+ = 100%
    if total < MIN_TRADES_RELIABLE:
        discount = total / MIN_TRADES_RELIABLE
        score = int(score * discount)

    return min(score, 100)


def _score_label(score: int, total_trades: int = 0) -> str:
    # Sample-size-aware: scores get heavily discounted below MIN_TRADES_RELIABLE,
    # which made a healthy young bot (e.g. 3 trades all winners → effective
    # score 27) look "CRITICAL" alongside actually-dying bots. Split that out.
    if total_trades < MIN_TRADES_RELIABLE:
        if total_trades == 0:
            return "NO TRADES"
        return "PRELIMINARY"
    if score >= 90:
        return "EXCELLENT"
    elif score >= 70:
        return "GOOD"
    elif score >= 50:
        return "WARNING"
    elif score >= 30:
        return "POOR"
    else:
        return "CRITICAL"


def _generate_flags(m: dict) -> None:
    flags = m["flags"]
    recs = m["recommendations"]
    strategy_type = m.get("type", "unknown")
    total_trades = m.get("total_trades", 0)
    is_trend_follower = strategy_type == "trend-follower"

    # --- Sample size warning (most important flag) ---
    if 0 < total_trades < MIN_TRADES_RELIABLE:
        flags.append(f"Low sample size: {total_trades} trades (need {MIN_TRADES_RELIABLE}+ for reliable metrics)")

    # Risk/reward inverted — but NOT for trend-followers (they compensate with high R:R)
    rr = m.get("risk_reward", 0)
    if rr < 1.0 and total_trades >= MIN_TRADES_RELIABLE:
        flags.append(f"Risk/reward inverted: {rr:.2f} (avg win ${m['avg_win']:.2f} < avg loss ${m['avg_loss']:.2f})")
        recs.append("Monitor closely — avg losses exceed avg wins")

    # Negative closed P&L
    if m.get("closed_pnl", 0) < -10:
        flags.append(f"Significant closed loss: ${m['closed_pnl']:.2f}")

    # High force-exit rate
    if m.get("force_exit_rate", 0) > 15:
        flags.append(f"High force-exit rate: {m['force_exit_rate']:.0f}%")
        recs.append("Review time-based exit thresholds — trades getting stuck")

    # Single trade dominates losses — flag but note it may be a historical outlier
    if m.get("worst_trade_loss_pct", 0) > 50:
        wt = m.get("worst_trade", {})
        flags.append(f"Single trade caused {m['worst_trade_loss_pct']:.0f}% of all losses: {wt.get('pair', '?')} ${wt.get('profit', 0):.2f}")
        # Only recommend action if this is a recent trade (stoploss bugs were fixed 2026-03-12)
        if total_trades < 20:
            recs.append("Outlier trade dominates stats — metrics will normalize as more trades accumulate")

    # Stale positions
    if m.get("stale_positions", 0) > 0:
        flags.append(f"{m['stale_positions']} stale positions (>8h open)")

    # Low win rate — strategy-type-aware
    wr = m.get("win_rate", 0)
    if total_trades >= MIN_TRADES_RELIABLE:
        if is_trend_follower:
            # Trend-followers: only flag if WR < 25% (very low even for trend)
            if wr < 25:
                flags.append(f"Very low win rate for trend-follower: {wr:.0f}%")
        else:
            if wr < 50:
                flags.append(f"Low win rate: {wr:.0f}%")

    # No recent trades
    if m.get("trades_24h", 0) == 0 and total_trades > 0:
        flags.append("No trades in last 24h")

    # Very high avg duration for 5m strategy
    if m.get("timeframe") == "5m" and m.get("avg_duration_min", 0) > 120:
        flags.append(f"Avg trade duration {m['avg_duration_min']:.0f}min — long for 5m strategy")

    # Profit factor < 1 means losing money per trade on average
    if m.get("profit_factor", 0) < 1.0 and total_trades >= MIN_TRADES_RELIABLE:
        flags.append(f"Profit factor below 1.0: {m['profit_factor']:.2f}")
        recs.append("Strategy is net-negative — monitor for improvement or consider parameter adjustment")

    # Score-based recommendation (only if enough trades for reliable score)
    score = m.get("health_score", 0)
    if total_trades >= MIN_TRADES_RELIABLE:
        if score < 30:
            recs.append(f"CRITICAL: Health score {score}/100 — strongly recommend pausing this strategy")
        elif score < 50:
            recs.append(f"POOR: Health score {score}/100 — reduce allocation and monitor closely")
    elif total_trades > 0:
        # Score is unreliable with few trades — say so
        recs.append(f"Score {score}/100 is preliminary ({total_trades} trades) — wait for {MIN_TRADES_RELIABLE}+ trades before acting")


# ---------------------------------------------------------------------------
# Portfolio-Level Analysis
# ---------------------------------------------------------------------------

def compute_portfolio_metrics(bot_metrics: list[dict]) -> dict:
    """Compute portfolio-level aggregates."""
    online = [m for m in bot_metrics if m["online"]]

    total_closed_pnl = sum(m.get("closed_pnl", 0) for m in online)
    total_open_pnl = sum(m.get("open_pnl", 0) for m in online)
    total_true_pnl = total_closed_pnl + total_open_pnl
    total_trades = sum(m.get("total_trades", 0) for m in online)
    total_open = sum(m.get("open_trades", 0) for m in online)
    bots_online = len(online)

    # Best and worst bots
    if online:
        best = max(online, key=lambda m: m.get("true_pnl", 0))
        worst = min(online, key=lambda m: m.get("true_pnl", 0))
    else:
        best = worst = {"strategy": "N/A", "true_pnl": 0}

    # Pair concentration across bots
    pair_exposure = defaultdict(list)
    for m in online:
        # Check open trades for pair overlap
        port = BOTS[m["strategy"]]["port"]
        open_trades = get_open_trades(port)
        if isinstance(open_trades, list):
            for t in open_trades:
                pair_exposure[t.get("pair", "?")].append(m["strategy"])

    overlapping_pairs = {p: bots for p, bots in pair_exposure.items() if len(bots) > 1}

    # Average health score
    scores = [m["health_score"] for m in online if m["health_score"] > 0]
    avg_health = round(sum(scores) / len(scores), 0) if scores else 0

    portfolio_flags = []
    if overlapping_pairs:
        for pair, bots in overlapping_pairs.items():
            portfolio_flags.append(f"Correlated exposure: {pair} held by {', '.join(bots)}")

    # Only flag bots as "critical" if they have a RELIABLE sample size AND a low
    # score. PRELIMINARY/NO TRADES bots aren't critical, they're just new.
    critical_bots = [
        m["strategy"] for m in online
        if m.get("health_score", 0) < 30
        and m.get("total_trades", 0) >= MIN_TRADES_RELIABLE
    ]
    if critical_bots:
        portfolio_flags.append(f"Critical bots: {', '.join(critical_bots)}")

    return {
        "closed_pnl": round(total_closed_pnl, 2),
        "open_pnl": round(total_open_pnl, 2),
        "true_pnl": round(total_true_pnl, 2),
        "portfolio_value": round(INITIAL_CAPITAL + total_true_pnl, 2),
        "return_pct": round(total_true_pnl / INITIAL_CAPITAL * 100, 2),
        "total_trades": total_trades,
        "open_positions": total_open,
        "bots_online": bots_online,
        "bots_total": len(BOTS),
        "best_bot": best["strategy"],
        "best_pnl": best.get("true_pnl", 0),
        "worst_bot": worst["strategy"],
        "worst_pnl": worst.get("true_pnl", 0),
        "avg_health_score": avg_health,
        "overlapping_pairs": overlapping_pairs,
        "flags": portfolio_flags,
    }


# ---------------------------------------------------------------------------
# Trend Detection (compare with previous report)
# ---------------------------------------------------------------------------

def load_previous_state() -> Optional[dict]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_state(bot_metrics: list[dict], portfolio: dict) -> None:
    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio,
        "bots": {
            m["strategy"]: {
                "health_score": m.get("health_score", 0),
                "true_pnl": m.get("true_pnl", 0),
                "closed_pnl": m.get("closed_pnl", 0),
                "total_trades": m.get("total_trades", 0),
                "win_rate": m.get("win_rate", 0),
                "risk_reward": m.get("risk_reward", 0),
            }
            for m in bot_metrics
        },
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error("Failed to save state: %s", e)


def compute_trends(current: list[dict], previous: Optional[dict]) -> dict:
    """Compare current metrics with previous report."""
    if not previous or "bots" not in previous:
        return {}

    trends = {}
    for m in current:
        strat = m["strategy"]
        prev = previous["bots"].get(strat)
        if not prev:
            continue

        trend = {}
        # P&L change
        pnl_delta = m.get("true_pnl", 0) - prev.get("true_pnl", 0)
        trend["pnl_delta"] = round(pnl_delta, 2)

        # Health score change
        score_delta = m.get("health_score", 0) - prev.get("health_score", 0)
        trend["score_delta"] = score_delta

        # Trade count change
        trade_delta = m.get("total_trades", 0) - prev.get("total_trades", 0)
        trend["new_trades"] = trade_delta

        # Win rate change
        wr_delta = m.get("win_rate", 0) - prev.get("win_rate", 0)
        trend["win_rate_delta"] = round(wr_delta, 1)

        trends[strat] = trend
    return trends


# ---------------------------------------------------------------------------
# Report Formatting
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pre-registration checks
# ---------------------------------------------------------------------------

PREREG_FILE = Path(__file__).resolve().parent / "preregistrations.json"


def check_preregistrations() -> list[str]:
    """Surface pre-registered review windows/triggers in the daily report.

    Two pre-registrations rotted silently in May 2026 — the FF ARB 3rd-loss
    trigger (fired 2026-05-14, evaluated 26 days late) and the Cascade 30-day
    dry-run gate (expired unevaluated) — because they lived only in commit
    messages and session memory. Anything in preregistrations.json with
    status "open" is reported daily, with an OVERDUE marker once review_by
    passes, until a human closes it with a resolution.
    """
    try:
        registry = json.loads(PREREG_FILE.read_text())
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        return [f"  [PREREG] registry unreadable: {e}"]

    lines: list[str] = []
    today = datetime.now(timezone.utc).date()
    for entry in registry.get("preregistrations", []):
        if entry.get("status") != "open":
            continue
        eid = entry.get("id", "?")
        registered = entry.get("registered", "?")
        review_by = entry.get("review_by")
        min_trades = entry.get("min_closed_trades")

        closed_since = None
        port = BOTS.get(entry.get("bot"), {}).get("port")
        if port:
            trades = get_trades_from_api(port)
            reg_dt = _parse_date(f"{registered} 00:00:00")
            if trades is not None and reg_dt is not None:
                closed_since = sum(
                    1 for t in trades
                    if not t.get("is_open")
                    and (_parse_date(t.get("close_date")) or reg_dt) > reg_dt
                )

        status_bits = []
        if review_by:
            days_left = (datetime.strptime(review_by, "%Y-%m-%d").date() - today).days
            status_bits.append(
                f"OVERDUE {-days_left}d — EVALUATE NOW" if days_left < 0
                else f"review in {days_left}d"
            )
        if min_trades is not None:
            shown = "?" if closed_since is None else str(closed_since)
            evaluable = closed_since is not None and closed_since >= min_trades
            status_bits.append(
                f"{shown}/{min_trades} closed trades since {registered}"
                + ("" if evaluable else " — rules not yet evaluable")
            )
        lines.append(f"  [{eid}] {' · '.join(status_bits) or 'open'}")
        for rule in entry.get("rules", []):
            lines.append(f"    rule: {rule}")
    return lines


def format_telegram_report(bot_metrics: list[dict], portfolio: dict, trends: dict,
                           prereg_lines: Optional[list[str]] = None) -> str:
    """Format a structured Telegram report."""
    lines = []
    now = datetime.now(timezone.utc)
    lines.append(f"DAILY STRATEGY HEALTH REPORT")
    lines.append(f"{now.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")

    # Portfolio summary
    lines.append("PORTFOLIO")
    lines.append(f"  Value: ${portfolio['portfolio_value']:,.2f} ({portfolio['return_pct']:+.2f}%)")
    lines.append(f"  Closed P&L: ${portfolio['closed_pnl']:+.2f}")
    lines.append(f"  Open P&L: ${portfolio['open_pnl']:+.2f}")
    lines.append(f"  True P&L: ${portfolio['true_pnl']:+.2f}")
    lines.append(f"  Trades: {portfolio['total_trades']} closed, {portfolio['open_positions']} open")
    lines.append(f"  Bots: {portfolio['bots_online']}/{portfolio.get('bots_total', portfolio['bots_online'])} online")
    lines.append(f"  Avg Health: {portfolio['avg_health_score']:.0f}/100")
    lines.append("")

    # Per-bot breakdown sorted by health score
    sorted_bots = sorted(bot_metrics, key=lambda m: m.get("health_score", 0), reverse=True)

    lines.append("BOT HEALTH SCORES")
    for m in sorted_bots:
        if not m["online"]:
            lines.append(f"  {m['strategy']}: OFFLINE")
            continue

        score = m.get("health_score", 0)
        label = m.get("health_label", "?")
        true_pnl = m.get("true_pnl", 0)
        wr = m.get("win_rate", 0)
        rr = m.get("risk_reward", 0)
        trades = m.get("total_trades", 0)

        # Trend arrow
        trend = trends.get(m["strategy"], {})
        pnl_delta = trend.get("pnl_delta", 0)
        arrow = "+" if pnl_delta > 0 else ""

        stype = m.get("type", "?")
        sample_note = "" if trades >= MIN_TRADES_RELIABLE else f" [{trades} trades — preliminary]"
        line = f"  {score:3d}/100 {label:9s} | {m['strategy']} ({stype}){sample_note}"
        lines.append(line)
        dd = m.get("max_drawdown_pct", 0)
        pdr = m.get("profit_dd_ratio", 0)
        lines.append(f"    P&L: ${true_pnl:+.2f} (24h: {arrow}${pnl_delta:.2f}) | WR: {wr:.0f}% | R:R {rr:.1f} | PF: {m.get('profit_factor', 0):.2f} | DD: {dd:.1f}% | P/DD: {pdr:.1f} | {trades} trades")

        # Exit reason summary
        exits = m.get("exit_reasons", {})
        if exits:
            exit_parts = []
            for reason, count in sorted(exits.items(), key=lambda x: -x[1]):
                exit_parts.append(f"{reason}:{count}")
            lines.append(f"    Exits: {', '.join(exit_parts)}")

    # Flags section
    all_flags = []
    for m in sorted_bots:
        for flag in m.get("flags", []):
            all_flags.append(f"  [{m['strategy']}] {flag}")
    for flag in portfolio.get("flags", []):
        all_flags.append(f"  [PORTFOLIO] {flag}")

    if all_flags:
        lines.append("")
        lines.append("RED FLAGS")
        for f in all_flags:
            lines.append(f)

    # Pre-registered review windows / triggers (see preregistrations.json)
    if prereg_lines:
        lines.append("")
        lines.append("PRE-REGISTRATIONS")
        lines.extend(prereg_lines)

    # Per-pair drift section (last 30 days, only render if any drift)
    pair_drift_lines: list[str] = []
    for m in sorted_bots:
        for pd in m.get("pair_drift", []) or []:
            pair_drift_lines.append(
                f"  [{m['strategy']}] {pd['pair']}: "
                f"{pd['wins']}W {pd['losses']}L · PF {pd['pf']} · "
                f"net ${pd['net_pnl']:+.2f}"
            )
            for f in pd["flags"]:
                pair_drift_lines.append(f"    → {f}")
    if pair_drift_lines:
        lines.append("")
        lines.append("PAIR DRIFT (30d)")
        lines.extend(pair_drift_lines)

    # Recommendations
    all_recs = []
    for m in sorted_bots:
        for rec in m.get("recommendations", []):
            all_recs.append(f"  [{m['strategy']}] {rec}")

    if all_recs:
        lines.append("")
        lines.append("RECOMMENDATIONS")
        for r in all_recs:
            lines.append(r)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram Delivery
# ---------------------------------------------------------------------------

def send_telegram(message: str) -> bool:
    try:
        # trade-webhook (FastAPI) expects JSON body; the old form-encoded
        # `data=` path was a Mac claude-assistant convention from before
        # the migration. Sending as JSON now → 200 OK + Telegram delivery.
        payload = {"type": "status", "status": message, "bot_name": "health-report"}
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 201, 204):
            log.info("Report sent to Telegram")
            return True
        log.warning("Webhook returned HTTP %d", resp.status_code)
        return False
    except Exception as e:
        log.error("Failed to send report: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global log
    parser = argparse.ArgumentParser(description="Daily Strategy Health Report")
    parser.add_argument("--stdout", action="store_true", help="Print report to stdout only")
    parser.add_argument("--json", action="store_true", help="Output raw JSON metrics")
    args = parser.parse_args()

    log = _setup_logging(json_mode=args.json)

    log.info("=" * 50)
    log.info("Strategy Health Report - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 50)

    # Collect metrics from all bots
    bot_metrics = []
    for strategy, info in BOTS.items():
        log.info("Analyzing %s...", strategy)
        metrics = compute_bot_metrics(strategy, info)
        bot_metrics.append(metrics)
        log.info("  %s: score=%d (%s), P&L=$%.2f, %d trades",
                 strategy, metrics.get("health_score", 0), metrics.get("health_label", "?"),
                 metrics.get("true_pnl", 0), metrics.get("total_trades", 0))

    # Portfolio-level analysis
    portfolio = compute_portfolio_metrics(bot_metrics)

    # Trend comparison
    previous = load_previous_state()
    trends = compute_trends(bot_metrics, previous)

    # Save current state for next comparison
    save_state(bot_metrics, portfolio)

    if args.json:
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "portfolio": portfolio,
            "bots": {m["strategy"]: m for m in bot_metrics},
            "trends": trends,
        }
        print(json.dumps(output, indent=2, default=str))
        return

    # Format report
    prereg_lines = check_preregistrations()
    report = format_telegram_report(bot_metrics, portfolio, trends, prereg_lines)

    if args.stdout:
        print(report)
        return

    # Send to Telegram
    print(report)
    send_telegram(report)

    log.info("Health report complete.")


if __name__ == "__main__":
    main()
