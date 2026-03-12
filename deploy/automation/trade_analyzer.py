#!/usr/bin/env python3
"""
Trade Analyzer — Deep Trade Analysis for Claude Agent
=====================================================

Outputs structured trade data with entry/exit quality analysis that a Claude
agent can interpret to suggest specific strategy improvements.

Usage:
    python trade_analyzer.py                # Full analysis (JSON)
    python trade_analyzer.py --summary      # Human-readable summary
    python trade_analyzer.py --bot SupertrendStrategy  # Single bot

Output is designed to be consumed by the Claude scheduled agent for
automated improvement suggestions.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOTS = {
    "ClucHAnix":              {"port": 8080, "timeframe": "5m", "type": "dip-buyer"},
    "NASOSv5":                {"port": 8082, "timeframe": "5m", "type": "dip-buyer"},
    "ElliotV5":               {"port": 8083, "timeframe": "5m", "type": "dip-buyer"},
    "SupertrendStrategy":     {"port": 8084, "timeframe": "1h", "type": "trend-follower"},
    "MasterTraderV1":         {"port": 8086, "timeframe": "1h", "type": "hybrid"},
    "MasterTraderAI":         {"port": 8087, "timeframe": "1h", "type": "ml-based"},
    "NostalgiaForInfinityX6": {"port": 8089, "timeframe": "5m", "type": "multi-signal"},
}

API_USER = "freqtrader"
API_PASS = "mastertrader"
AUTH = HTTPBasicAuth(API_USER, API_PASS)
INITIAL_CAPITAL_PER_BOT = 1000.0


def fetch_json(url: str, timeout: int = 10) -> Optional[Any]:
    try:
        resp = requests.get(url, auth=AUTH, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
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


# ---------------------------------------------------------------------------
# Per-Trade Analysis
# ---------------------------------------------------------------------------

def analyze_trade(trade: dict, strategy_info: dict) -> dict:
    """Analyze a single trade for entry/exit quality."""
    analysis = {
        "pair": trade.get("pair", "?"),
        "open_date": trade.get("open_date", "?"),
        "close_date": trade.get("close_date"),
        "is_open": trade.get("is_open", True),
        "profit_pct": round(trade.get("profit_pct", 0), 2),
        "profit_abs": round(trade.get("profit_abs", 0), 2),
        "open_rate": trade.get("open_rate", 0),
        "close_rate": trade.get("close_rate", 0),
        "current_rate": trade.get("current_rate"),
        "exit_reason": trade.get("exit_reason", ""),
        "enter_tag": trade.get("enter_tag", ""),
        "trade_duration_min": trade.get("trade_duration", 0),
        "stake_amount": trade.get("stake_amount", 0),
    }

    # Max adverse excursion (if available)
    if "min_rate" in trade and trade.get("open_rate"):
        open_rate = trade["open_rate"]
        min_rate = trade["min_rate"]
        mae_pct = (min_rate - open_rate) / open_rate * 100 if open_rate else 0
        analysis["mae_pct"] = round(mae_pct, 2)

    # Max favorable excursion
    if "max_rate" in trade and trade.get("open_rate"):
        open_rate = trade["open_rate"]
        max_rate = trade["max_rate"]
        mfe_pct = (max_rate - open_rate) / open_rate * 100 if open_rate else 0
        analysis["mfe_pct"] = round(mfe_pct, 2)

        # How much profit was given back? (MFE - actual profit)
        if not trade.get("is_open"):
            profit_pct = trade.get("profit_pct", 0)
            giveback = mfe_pct - profit_pct
            analysis["profit_giveback_pct"] = round(giveback, 2)

    # Trade age for open trades
    if trade.get("is_open"):
        open_dt = parse_date(trade.get("open_date"))
        if open_dt:
            age_hours = (datetime.now(timezone.utc) - open_dt).total_seconds() / 3600
            analysis["age_hours"] = round(age_hours, 1)

            # Flag if stale
            tf = strategy_info.get("timeframe", "5m")
            stale_threshold = 48 if tf == "1h" else 8
            analysis["is_stale"] = age_hours > stale_threshold

    return analysis


# ---------------------------------------------------------------------------
# Strategy-Level Analysis
# ---------------------------------------------------------------------------

def analyze_strategy(strategy: str, info: dict) -> dict:
    """Deep analysis of a single strategy's trades."""
    port = info["port"]

    result = {
        "strategy": strategy,
        "timeframe": info["timeframe"],
        "type": info["type"],
        "online": False,
        "config": {},
        "trade_analysis": [],
        "patterns": {},
        "issues": [],
        "suggestions": [],
    }

    # Fetch config
    config = fetch_json(f"http://127.0.0.1:{port}/api/v1/show_config")
    if config:
        result["online"] = True
        result["config"] = {
            "stoploss": config.get("stoploss"),
            "trailing_stop": config.get("trailing_stop"),
            "trailing_stop_positive": config.get("trailing_stop_positive"),
            "trailing_stop_positive_offset": config.get("trailing_stop_positive_offset"),
            "trailing_only_offset_is_reached": config.get("trailing_only_offset_is_reached"),
            "minimal_roi": config.get("minimal_roi"),
        }
    else:
        result["issues"].append("Bot unreachable")
        return result

    # Fetch all trades
    trades_data = fetch_json(f"http://127.0.0.1:{port}/api/v1/trades?limit=500")
    trades = trades_data.get("trades", []) if trades_data else []

    open_trades_data = fetch_json(f"http://127.0.0.1:{port}/api/v1/status")
    open_trades = open_trades_data if isinstance(open_trades_data, list) else []

    # Analyze each trade
    all_trades = []
    for t in trades:
        all_trades.append(analyze_trade(t, info))
    for t in open_trades:
        # Mark open trades from status endpoint
        t["is_open"] = True
        analysis = analyze_trade(t, info)
        # Avoid duplicates (status endpoint trades may overlap with trades endpoint)
        if not any(a["pair"] == analysis["pair"] and a["open_date"] == analysis["open_date"]
                    for a in all_trades if a.get("is_open")):
            all_trades.append(analysis)

    result["trade_analysis"] = all_trades

    closed = [t for t in all_trades if not t.get("is_open")]
    opens = [t for t in all_trades if t.get("is_open")]

    # --- Pattern Detection ---
    patterns = {}

    # 1. Profit giveback pattern (entering profitable trades that give back gains)
    givebacks = [t for t in closed if t.get("profit_giveback_pct", 0) > 3]
    if givebacks:
        avg_giveback = sum(t["profit_giveback_pct"] for t in givebacks) / len(givebacks)
        patterns["profit_giveback"] = {
            "count": len(givebacks),
            "avg_giveback_pct": round(avg_giveback, 2),
            "worst": max(givebacks, key=lambda t: t["profit_giveback_pct"])["pair"],
            "description": f"{len(givebacks)} trades gave back >{3}% of peak profit (avg {avg_giveback:.1f}%)",
        }

    # 2. Entry at tops pattern (trades that immediately go negative)
    immediate_losers = [t for t in closed if t.get("mae_pct", 0) < -3 and t.get("trade_duration_min", 999) < 60]
    if immediate_losers:
        patterns["bad_entries"] = {
            "count": len(immediate_losers),
            "description": f"{len(immediate_losers)} trades dropped >3% within 1h of entry",
        }

    # 3. Exit timing (trades closed at loss that had profit potential)
    missed_profit = [t for t in closed if t.get("profit_pct", 0) < 0 and t.get("mfe_pct", 0) > 2]
    if missed_profit:
        patterns["missed_exits"] = {
            "count": len(missed_profit),
            "description": f"{len(missed_profit)} losing trades had MFE >2% but closed at a loss",
        }

    # 4. Pair concentration
    pair_counts = defaultdict(int)
    pair_pnl = defaultdict(float)
    for t in all_trades:
        pair_counts[t["pair"]] += 1
        pair_pnl[t["pair"]] += t.get("profit_abs", 0)
    worst_pairs = sorted(pair_pnl.items(), key=lambda x: x[1])[:3]
    best_pairs = sorted(pair_pnl.items(), key=lambda x: x[1], reverse=True)[:3]
    patterns["pair_performance"] = {
        "worst": [(p, round(v, 2)) for p, v in worst_pairs],
        "best": [(p, round(v, 2)) for p, v in best_pairs],
        "most_traded": sorted(pair_counts.items(), key=lambda x: -x[1])[:3],
    }

    # 5. Exit reason analysis
    exit_reasons = defaultdict(lambda: {"count": 0, "total_pnl": 0, "avg_pnl": 0})
    for t in closed:
        reason = t.get("exit_reason", "unknown")
        exit_reasons[reason]["count"] += 1
        exit_reasons[reason]["total_pnl"] += t.get("profit_abs", 0)
    for reason in exit_reasons:
        c = exit_reasons[reason]["count"]
        exit_reasons[reason]["avg_pnl"] = round(exit_reasons[reason]["total_pnl"] / c, 2) if c else 0
        exit_reasons[reason]["total_pnl"] = round(exit_reasons[reason]["total_pnl"], 2)
    patterns["exit_reasons"] = dict(exit_reasons)

    # 6. Time-of-day analysis
    hour_pnl = defaultdict(lambda: {"count": 0, "pnl": 0})
    for t in closed:
        dt = parse_date(t.get("open_date"))
        if dt:
            h = dt.hour
            hour_pnl[h]["count"] += 1
            hour_pnl[h]["pnl"] += t.get("profit_abs", 0)
    if hour_pnl:
        worst_hour = min(hour_pnl.items(), key=lambda x: x[1]["pnl"])
        best_hour = max(hour_pnl.items(), key=lambda x: x[1]["pnl"])
        patterns["time_analysis"] = {
            "worst_hour_utc": worst_hour[0],
            "worst_hour_pnl": round(worst_hour[1]["pnl"], 2),
            "best_hour_utc": best_hour[0],
            "best_hour_pnl": round(best_hour[1]["pnl"], 2),
        }

    # 7. Open position health
    if opens:
        total_unrealized = sum(t.get("profit_abs", 0) for t in opens)
        stale = [t for t in opens if t.get("is_stale")]
        patterns["open_positions"] = {
            "count": len(opens),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "stale_count": len(stale),
            "positions": [
                {
                    "pair": t["pair"],
                    "profit_pct": t["profit_pct"],
                    "age_hours": t.get("age_hours", 0),
                    "is_stale": t.get("is_stale", False),
                }
                for t in opens
            ],
        }

    result["patterns"] = patterns

    # --- Issue Detection ---
    issues = result["issues"]
    suggestions = result["suggestions"]

    # Trailing stop effectiveness
    cfg = result["config"]
    if cfg.get("trailing_stop") and cfg.get("trailing_stop_positive_offset"):
        offset = cfg["trailing_stop_positive_offset"]
        # Check if any closed trades actually reached the trailing offset
        trades_reaching_offset = [t for t in closed if t.get("mfe_pct", 0) / 100 >= offset]
        if closed and not trades_reaching_offset:
            issues.append(
                f"Trailing stop offset ({offset*100:.1f}%) never reached by any trade. "
                f"Best MFE was {max(t.get('mfe_pct', 0) for t in closed):.1f}%. "
                f"Trailing stop is effectively disabled."
            )
            suggestions.append(
                f"Lower trailing_stop_positive_offset to match actual MFE distribution. "
                f"Suggest: {max(t.get('mfe_pct', 0) for t in closed) * 0.6:.1f}% offset"
            )

    # ROI effectiveness
    roi = cfg.get("minimal_roi", {})
    if roi:
        roi_exits = [t for t in closed if t.get("exit_reason") == "roi"]
        if closed and len(roi_exits) / len(closed) < 0.1 and len(closed) > 5:
            issues.append(
                f"ROI rarely triggers ({len(roi_exits)}/{len(closed)} trades). "
                f"ROI targets may be too aggressive."
            )

    # Profit giveback issue
    if "profit_giveback" in patterns:
        gb = patterns["profit_giveback"]
        if gb["avg_giveback_pct"] > 5:
            issues.append(f"Avg profit giveback is {gb['avg_giveback_pct']:.1f}% — profits not being locked in")
            suggestions.append("Tighten trailing stop or lower ROI targets to capture profits earlier")

    # Force exit issue
    exits = patterns.get("exit_reasons", {})
    force_count = exits.get("force_exit", {}).get("count", 0)
    if force_count > 0 and closed:
        force_pnl = exits.get("force_exit", {}).get("total_pnl", 0)
        issues.append(f"{force_count} force exits totaling ${force_pnl:.2f}")
        if force_pnl < -10:
            suggestions.append("Trades getting stuck and force-exited at a loss — review entry conditions")

    # Zero trades
    if not closed and not opens:
        issues.append("No trades taken — strategy may have entry conditions that never fire")
        suggestions.append("Review entry signal logic or pairlist — strategy is idle")

    # Summary stats
    if closed:
        total_pnl = sum(t.get("profit_abs", 0) for t in closed)
        winners = [t for t in closed if t.get("profit_pct", 0) > 0]
        result["summary"] = {
            "total_closed": len(closed),
            "total_open": len(opens),
            "closed_pnl": round(total_pnl, 2),
            "win_rate": round(len(winners) / len(closed) * 100, 1) if closed else 0,
            "avg_trade_pnl": round(total_pnl / len(closed), 2),
            "best_trade": round(max(t.get("profit_pct", 0) for t in closed), 2),
            "worst_trade": round(min(t.get("profit_pct", 0) for t in closed), 2),
        }

    return result


# ---------------------------------------------------------------------------
# Portfolio-Level Analysis
# ---------------------------------------------------------------------------

def analyze_portfolio(bot_analyses: list[dict]) -> dict:
    """Cross-bot analysis for portfolio-level patterns."""
    portfolio = {
        "total_closed_pnl": 0,
        "total_unrealized_pnl": 0,
        "total_trades": 0,
        "cross_bot_issues": [],
    }

    # Check for correlated positions
    open_positions = {}
    for bot in bot_analyses:
        if not bot["online"]:
            continue
        strategy = bot["strategy"]
        for t in bot.get("trade_analysis", []):
            if t.get("is_open"):
                pair = t["pair"]
                if pair not in open_positions:
                    open_positions[pair] = []
                open_positions[pair].append(strategy)

        summary = bot.get("summary", {})
        portfolio["total_closed_pnl"] += summary.get("closed_pnl", 0)
        portfolio["total_trades"] += summary.get("total_closed", 0)

        opens = bot.get("patterns", {}).get("open_positions", {})
        portfolio["total_unrealized_pnl"] += opens.get("total_unrealized_pnl", 0)

    # Flag correlated exposure
    for pair, bots in open_positions.items():
        if len(bots) > 1:
            portfolio["cross_bot_issues"].append(
                f"Correlated exposure: {pair} held by {', '.join(bots)}"
            )

    portfolio["total_closed_pnl"] = round(portfolio["total_closed_pnl"], 2)
    portfolio["total_unrealized_pnl"] = round(portfolio["total_unrealized_pnl"], 2)
    portfolio["true_pnl"] = round(
        portfolio["total_closed_pnl"] + portfolio["total_unrealized_pnl"], 2
    )

    return portfolio


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Deep Trade Analyzer")
    parser.add_argument("--bot", type=str, help="Analyze a single bot")
    parser.add_argument("--summary", action="store_true", help="Human-readable summary")
    args = parser.parse_args()

    bots_to_analyze = BOTS
    if args.bot:
        if args.bot in BOTS:
            bots_to_analyze = {args.bot: BOTS[args.bot]}
        else:
            print(f"Unknown bot: {args.bot}", file=sys.stderr)
            sys.exit(1)

    analyses = []
    for strategy, info in bots_to_analyze.items():
        analysis = analyze_strategy(strategy, info)
        analyses.append(analysis)

    portfolio = analyze_portfolio(analyses)

    if args.summary:
        # Print human-readable summary
        print(f"=== Trade Analysis — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC ===\n")
        print(f"Portfolio: ${portfolio['true_pnl']:+.2f} "
              f"(closed: ${portfolio['total_closed_pnl']:+.2f}, "
              f"unrealized: ${portfolio['total_unrealized_pnl']:+.2f})\n")

        for a in analyses:
            s = a.get("summary", {})
            print(f"--- {a['strategy']} ({a['timeframe']} {a['type']}) ---")
            if not a["online"]:
                print("  OFFLINE\n")
                continue
            if not s:
                print("  No trades\n")
                continue

            print(f"  P&L: ${s.get('closed_pnl', 0):+.2f} | "
                  f"WR: {s.get('win_rate', 0):.0f}% | "
                  f"Trades: {s.get('total_closed', 0)} closed, {s.get('total_open', 0)} open")

            if a["issues"]:
                print("  ISSUES:")
                for issue in a["issues"]:
                    print(f"    - {issue}")

            if a["suggestions"]:
                print("  SUGGESTIONS:")
                for sug in a["suggestions"]:
                    print(f"    - {sug}")
            print()

        if portfolio["cross_bot_issues"]:
            print("--- PORTFOLIO ISSUES ---")
            for issue in portfolio["cross_bot_issues"]:
                print(f"  - {issue}")
    else:
        # JSON output for Claude agent consumption
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "portfolio": portfolio,
            "strategies": {a["strategy"]: a for a in analyses},
        }
        print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
