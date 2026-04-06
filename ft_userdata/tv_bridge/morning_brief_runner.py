"""
Morning Brief Runner — captures TradingView market analysis and saves for health report integration.

Runs 5 minutes before strategy_health_report.py to provide market context.
Designed to be called by Claude Code (uses TV MCP tools) or via cron with claude CLI.

Usage:
    # Via Claude Code (interactive):
    Ask Claude: "Run morning brief for all watchlist pairs"

    # Via cron (automated):
    55 20 * * * cd ~/Work/Dev/Master\ Trader && claude --print "Run morning_brief MCP tool and save results to ft_userdata/tv_bridge/tv_brief_state.json"
"""
import json
import os
from datetime import datetime, timezone

TV_BRIEF_STATE_PATH = os.path.join(os.path.dirname(__file__), "tv_brief_state.json")

# Watchlist matching rules.json
WATCHLIST = [
    "BINANCE:BTCUSDT",
    "BINANCE:ETHUSDT",
    "BINANCE:SOLUSDT",
    "BINANCE:XRPUSDT",
    "BINANCE:BNBUSDT",
    "BINANCE:ADAUSDT",
    "BINANCE:AVAXUSDT",
    "BINANCE:DOTUSDT",
    "BINANCE:LINKUSDT",
    "BINANCE:MATICUSDT",
]


def save_brief_state(brief_data):
    """Save morning brief results for health report to read."""
    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pairs": brief_data,
    }
    with open(TV_BRIEF_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    print(f"Saved brief state to {TV_BRIEF_STATE_PATH}")


def format_for_telegram(state):
    """Format brief state as Telegram-friendly text."""
    lines = ["📊 *Market Conditions (TradingView)*\n"]

    for pair_data in state.get("pairs", []):
        symbol = pair_data.get("symbol", "???")
        bias = pair_data.get("bias", "unknown")
        note = pair_data.get("note", "")

        emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
            bias.lower(), "⚪"
        )
        ticker = symbol.split(":")[-1].replace("USDT", "") if ":" in symbol else symbol
        line = f"{emoji} *{ticker}*: {bias}"
        if note:
            line += f" — {note}"
        lines.append(line)

    return "\n".join(lines)


def load_brief_state():
    """Load the latest brief state (for health report integration)."""
    if not os.path.exists(TV_BRIEF_STATE_PATH):
        return None

    with open(TV_BRIEF_STATE_PATH) as f:
        state = json.load(f)

    # Check freshness — only use if < 10 minutes old
    ts = datetime.fromisoformat(state["timestamp"])
    age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    if age_seconds > 600:  # 10 minutes
        return None

    return state


if __name__ == "__main__":
    print("=== Morning Brief Runner ===")
    print(f"Watchlist: {len(WATCHLIST)} pairs")
    print(f"Output: {TV_BRIEF_STATE_PATH}")
    print()
    print("To run: ask Claude to execute morning_brief MCP tool,")
    print("then call save_brief_state() with the results.")
    print()
    # Show existing state if any
    state = load_brief_state()
    if state:
        print("Latest brief:")
        print(format_for_telegram(state))
    else:
        print("No fresh brief state found.")
