"""
Setup TradingView dashboard tabs for all Master Trader strategies.
Run interactively with Claude Code — uses TV MCP tools.

Usage: Ask Claude to "run setup_dashboards" or paste this into conversation.
"""
import os

# This script is meant to be executed step-by-step by Claude Code
# using TradingView MCP tools. It's a reference/recipe, not standalone.

PINE_DIR = os.path.join(os.path.dirname(__file__), "pine")

DASHBOARD_TABS = [
    {
        "name": "BTC Guard",
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "60",
        "pine_file": "btc_guard_dashboard.pine",
        "description": "Portfolio-wide BTC guard status for all 6 strategies",
    },
    {
        "name": "Supertrend",
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "60",
        "pine_file": "supertrend_strategy.pine",
        "description": "3-layer Supertrend + SMA50 fast gate",
    },
    {
        "name": "MasterTrader",
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "60",
        "pine_file": "master_trader_v1.pine",
        "description": "EMA 9/21 crossover + RSI filter",
    },
    {
        "name": "Alligator",
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "pine_file": "alligator_trend_v1.pine",
        "description": "Williams Alligator + ATR dynamic stoploss",
    },
    {
        "name": "Gaussian",
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "1D",
        "pine_file": "gaussian_channel_v1.pine",
        "description": "4-pole Gaussian channel, sampling 144",
    },
    {
        "name": "BearCrash",
        "symbol": "BINANCE:ETHUSDT",
        "timeframe": "60",
        "pine_file": "bear_crash_short_v1.pine",
        "description": "Short-only, bear regime gated, failed rally entries",
    },
    {
        "name": "BBounce",
        "symbol": "BINANCE:ETHUSDT",
        "timeframe": "60",
        "pine_file": "bollinger_bounce_v1.pine",
        "description": "Bollinger 2σ bounce + RSI + ADX trending",
    },
    {
        "name": "SignalLab",
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "60",
        "pine_file": None,
        "description": "Dynamic tab for Strategy Lab Pine Script testing",
    },
]


def get_setup_instructions():
    """Return step-by-step MCP tool calls for Claude to execute."""
    steps = []
    for i, tab in enumerate(DASHBOARD_TABS):
        step = {
            "tab_index": i,
            "name": tab["name"],
            "actions": [],
        }
        if i > 0:  # First tab already exists
            step["actions"].append({"tool": "tab_new"})
        step["actions"].append(
            {"tool": "chart_set_symbol", "args": {"symbol": tab["symbol"]}}
        )
        step["actions"].append(
            {"tool": "chart_set_timeframe", "args": {"timeframe": tab["timeframe"]}}
        )
        if tab["pine_file"]:
            pine_path = os.path.join(PINE_DIR, tab["pine_file"])
            step["actions"].append(
                {
                    "tool": "pine_set_source + pine_smart_compile",
                    "args": {"file": pine_path},
                }
            )
        steps.append(step)

    steps.append({"tool": "session_save", "args": {"name": "MasterTrader_Dashboards"}})
    return steps


if __name__ == "__main__":
    print("=== Master Trader TradingView Dashboard Setup ===\n")
    for step in get_setup_instructions():
        if "tab_index" in step:
            print(f"Tab {step['tab_index']}: {step['name']}")
            for action in step["actions"]:
                print(f"  → {action['tool']}: {action.get('args', '')}")
        else:
            print(f"Final: {step['tool']}: {step.get('args', '')}")
    print("\nRun these steps in Claude Code with TV MCP tools.")
