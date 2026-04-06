#!/usr/bin/env python3
"""
AI Trade Autopsy — Structured Post-Trade Analysis for Claude
=============================================================

Pulls closed trades from Freqtrade API, formats them into structured autopsy
templates, and outputs text ready for Claude analysis.

Usage:
    python ai_trade_autopsy.py                          # All bots, last 24h
    python ai_trade_autopsy.py --bot SupertrendStrategy  # Single bot
    python ai_trade_autopsy.py --hours 72               # Last 72h
    python ai_trade_autopsy.py --prompt                 # Include Claude analysis prompt
    python ai_trade_autopsy.py --json                   # JSON output
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_USER = "freqtrader"
API_PASS = "mastertrader"
AUTH = HTTPBasicAuth(API_USER, API_PASS)

# ---------------------------------------------------------------------------
# Strategy Rules — used to contextualize each trade autopsy
# ---------------------------------------------------------------------------

STRATEGY_RULES: dict[str, dict[str, str]] = {
    "SupertrendStrategy": {
        "entry": "3x Supertrend (10/1, 11/2, 12/3) all uptrend + BTC SMA50 fast gate + SMA200 guard + regime filters (ADX/RSI)",
        "exit": "Any Supertrend flips down, exit_profit_only at +1%, ROI table 8%/5%/3%/2%",
        "stoploss": "-5% hard stoploss",
        "trailing": "2% trailing stop at 3% offset",
    },
    "MasterTraderV1": {
        "entry": "Multi-indicator confluence: EMA cross + MACD + RSI + Bollinger + volume confirmation",
        "exit": "EMA death cross or RSI overbought or MACD bearish cross, 48h force exit, ROI 7%/4%/2.5%/1.5%",
        "stoploss": "-5% hard stoploss",
        "trailing": "1% trailing stop at 2% offset",
    },
    "BollingerBounceV1": {
        "entry": "BB lower band (2 sigma) bounce + RSI oversold + ADX trending + volume spike + BTC SMA200 gate",
        "exit": "Price reaches BB middle/upper band or RSI overbought, ROI 5%/3%/2%/1%",
        "stoploss": "-5% hard stoploss",
        "trailing": "2% trailing stop at 3% offset",
    },
    "BearCrashShortV1": {
        "entry": "Short failed rallies: BTC bear regime (SMA200+ADX+RSI) + 4-of-6 rolling window + RSI 40-70 bounce entry; Long on regime flip",
        "exit": "RSI < 25, 2-candle confirmed +DI > -DI, BTC flips bullish, volatility spike, 48h hard exit, ROI 8%/5%/3%/1%/0%",
        "stoploss": "-5% hard stoploss (2x leverage = 10% effective)",
        "trailing": "2% trailing stop at 3% offset",
    },
    "AlligatorTrendV1": {
        "entry": "Alligator indicator (jaw/teeth/lips aligned) + trend confirmation + BTC SMA200 gate",
        "exit": "Alligator lips cross below teeth, ATR-based dynamic targets, ROI 50%/30%/15%/5%",
        "stoploss": "-10% ATR-dynamic stoploss (use_custom_stoploss)",
        "trailing": "3% trailing stop at 8% offset",
    },
    "GaussianChannelV1": {
        "entry": "Price breaks above Gaussian channel upper band + trend filter + BTC SMA200 gate",
        "exit": "Price falls below Gaussian channel midline, ROI 50%/30%/15%/5%",
        "stoploss": "-15% hard stoploss",
        "trailing": "3% trailing stop at 8% offset",
    },
}


def _load_bots_config() -> dict[str, dict]:
    """Load bot registry from shared config, fall back to hardcoded defaults."""
    config_path = Path(__file__).parent / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        return {
            name: {k: v for k, v in info.items() if k != "active"}
            for name, info in data["bots"].items()
            if info.get("active", True)
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {
            "SupertrendStrategy": {"port": 8084, "timeframe": "1h"},
            "MasterTraderV1": {"port": 8086, "timeframe": "1h"},
            "AlligatorTrendV1": {"port": 8091, "timeframe": "1d"},
            "GaussianChannelV1": {"port": 8092, "timeframe": "1d"},
            "BearCrashShortV1": {"port": 8093, "timeframe": "1h"},
            "BollingerBounceV1": {"port": 8094, "timeframe": "1h"},
        }


BOTS = _load_bots_config()


# ---------------------------------------------------------------------------
# API Helpers
# ---------------------------------------------------------------------------

def fetch_json(url: str, timeout: int = 10) -> Optional[Any]:
    """Fetch JSON from a Freqtrade API endpoint."""
    try:
        resp = requests.get(url, auth=AUTH, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string from Freqtrade API into a datetime object."""
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
# Core Functions
# ---------------------------------------------------------------------------

def fetch_recent_trades(port: int, hours: int = 24) -> list[dict]:
    """Fetch closed trades from a Freqtrade bot within the given time window."""
    url = f"http://localhost:{port}/api/v1/trades?limit=500"
    data = fetch_json(url)
    if not data or "trades" not in data:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for trade in data["trades"]:
        if not trade.get("close_date"):
            continue
        close_dt = parse_date(trade["close_date"])
        if close_dt and close_dt >= cutoff:
            recent.append(trade)
    return recent


def format_trade_autopsy(trade: dict, strategy: str, strategy_rules: dict) -> str:
    """Format a single trade into a structured autopsy template.

    Args:
        trade: Trade dict from Freqtrade API.
        strategy: Strategy name.
        strategy_rules: Dict with keys: entry, exit, stoploss, trailing.

    Returns:
        Formatted autopsy string ready for Claude analysis.
    """
    pair = trade.get("pair", "UNKNOWN")
    open_date = trade.get("open_date", "N/A")
    close_date = trade.get("close_date", "N/A")
    open_rate = trade.get("open_rate", 0)
    close_rate = trade.get("close_rate", 0)
    profit_abs = trade.get("profit_abs", 0)
    profit_ratio = trade.get("profit_ratio", 0)
    exit_reason = trade.get("exit_reason", "unknown")
    enter_tag = trade.get("enter_tag", "N/A")
    stake = trade.get("stake_amount", 0)
    duration_min = trade.get("trade_duration", 0)

    # Calculate price movement
    if open_rate and open_rate > 0:
        price_change_pct = ((close_rate - open_rate) / open_rate) * 100
    else:
        price_change_pct = 0.0

    # Duration in human-readable format
    if duration_min >= 60:
        duration_str = f"{duration_min // 60}h {duration_min % 60}m"
    else:
        duration_str = f"{duration_min}m"

    outcome = "WIN" if profit_abs > 0 else "LOSS" if profit_abs < 0 else "BREAKEVEN"

    lines = [
        f"=== TRADE AUTOPSY: {pair} ({strategy}) ===",
        f"Outcome: {outcome} | P&L: ${profit_abs:+.2f} ({profit_ratio:+.1%})",
        f"",
        f"TIMING:",
        f"  Entry: {open_date}",
        f"  Exit:  {close_date}",
        f"  Duration: {duration_str} ({duration_min} minutes)",
        f"",
        f"PRICES:",
        f"  Entry price: ${open_rate:.4f}",
        f"  Exit price:  ${close_rate:.4f}",
        f"  Price change: {price_change_pct:+.2f}%",
        f"  Stake: ${stake:.2f}",
        f"",
        f"SIGNALS:",
        f"  Entry tag: {enter_tag}",
        f"  Exit reason: {exit_reason}",
        f"",
        f"STRATEGY RULES ({strategy}):",
        f"  Entry: {strategy_rules.get('entry', 'N/A')}",
        f"  Exit:  {strategy_rules.get('exit', 'N/A')}",
        f"  Stoploss: {strategy_rules.get('stoploss', 'N/A')}",
        f"  Trailing: {strategy_rules.get('trailing', 'N/A')}",
        f"",
        f"QUESTIONS FOR ANALYSIS:",
        f"  1. Was the entry signal correct given market conditions?",
        f"  2. Was the exit optimal, or did it leave money on the table / cut too late?",
        f"  3. Did the stoploss/trailing stop behave as expected?",
        f"  4. What market condition was this trade in (trending/ranging/volatile)?",
        f"  5. Should this trade have been filtered out by any guard?",
    ]
    return "\n".join(lines)


def generate_autopsy_prompt(autopsies: list[str]) -> str:
    """Generate a Claude analysis super-prompt from multiple trade autopsies.

    Args:
        autopsies: List of formatted autopsy strings.

    Returns:
        Complete prompt string for Claude to analyze the trades.
    """
    trade_block = "\n\n".join(autopsies)
    num_trades = len(autopsies)

    prompt = f"""You are an expert crypto trading analyst. Below are {num_trades} recent trade autopsies from my Freqtrade bots. Analyze them and provide actionable insights.

---
{trade_block}
---

ANALYSIS INSTRUCTIONS:

1. **Pattern Recognition**: Look across all trades for recurring patterns — do certain exit reasons dominate losses? Are specific pairs underperforming? Are there time-of-day patterns?

2. **Most Important Findings**: Rank the top 3 most important findings that could improve future performance. Focus on what is actionable.

3. **Exit Quality**: For each losing trade, assess whether the exit was too early (left money on the table) or too late (should have been stopped out sooner). For winners, assess if trailing stops captured enough of the move.

4. **Entry Quality**: Were any entries taken against the prevailing trend? Did the entry signals align with market conditions?

5. **Strategy-Specific Recommendations**: For each strategy that had trades, provide one specific parameter or rule change that could improve performance. Be concrete (e.g., "tighten ROI from 8% to 6% at 60 candles" not "adjust ROI").

6. **Risk Assessment**: Flag any concerning patterns — correlated losses, drawdown acceleration, or strategies that may need to be paused.

Format your response as a structured report with clear sections and bullet points. Be direct and specific — no generic advice."""

    return prompt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AI Trade Autopsy — structured post-trade analysis for Claude"
    )
    parser.add_argument(
        "--bot", type=str, default=None,
        help="Analyze a specific bot (strategy name)"
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Look back N hours for closed trades (default: 24)"
    )
    parser.add_argument(
        "--prompt", action="store_true",
        help="Include Claude analysis prompt in output"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw trade data as JSON"
    )
    args = parser.parse_args()

    # Determine which bots to query
    if args.bot:
        if args.bot not in BOTS:
            print(f"Error: Unknown bot '{args.bot}'. Available: {', '.join(BOTS.keys())}", file=sys.stderr)
            sys.exit(1)
        bots_to_query = {args.bot: BOTS[args.bot]}
    else:
        bots_to_query = BOTS

    # Fetch trades from all selected bots
    all_trades: list[tuple[str, dict]] = []
    for strategy, bot_info in bots_to_query.items():
        port = bot_info["port"]
        trades = fetch_recent_trades(port, args.hours)
        for t in trades:
            all_trades.append((strategy, t))

    if not all_trades:
        print(f"No closed trades found in the last {args.hours}h.", file=sys.stderr)
        sys.exit(0)

    # JSON mode — raw output
    if args.json:
        output = []
        for strategy, trade in all_trades:
            trade["_strategy"] = strategy
            output.append(trade)
        print(json.dumps(output, indent=2, default=str))
        return

    # Generate autopsies
    autopsies = []
    for strategy, trade in all_trades:
        rules = STRATEGY_RULES.get(strategy, {
            "entry": "Unknown", "exit": "Unknown",
            "stoploss": "Unknown", "trailing": "Unknown",
        })
        autopsy = format_trade_autopsy(trade, strategy, rules)
        autopsies.append(autopsy)

    # Print autopsies
    for autopsy in autopsies:
        print(autopsy)
        print()

    # Print summary
    wins = sum(1 for _, t in all_trades if t.get("profit_abs", 0) > 0)
    losses = sum(1 for _, t in all_trades if t.get("profit_abs", 0) < 0)
    total_pnl = sum(t.get("profit_abs", 0) for _, t in all_trades)
    print(f"--- SUMMARY: {len(all_trades)} trades | {wins}W/{losses}L | P&L: ${total_pnl:+.2f} ---")
    print()

    # Optionally include Claude prompt
    if args.prompt:
        prompt = generate_autopsy_prompt(autopsies)
        print("=" * 70)
        print("CLAUDE ANALYSIS PROMPT")
        print("=" * 70)
        print(prompt)


if __name__ == "__main__":
    main()
