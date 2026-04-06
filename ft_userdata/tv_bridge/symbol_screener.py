"""
Batch Symbol Screener — profiles pairs by trend strength and volatility
to route them to the optimal strategy type.

Uses TradingView MCP batch_run + data_get_study_values to read ADX/ATR
across all watchlist pairs.

Usage: Ask Claude to "run symbol screener" — uses TV MCP tools interactively.
       Or: python3 ft_userdata/tv_bridge/symbol_screener.py (prints instructions)
"""
import json
import os
from datetime import datetime, timezone

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "pair_profiles.json")

PAIRS = [
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

# Classification thresholds
ADX_TRENDING = 25  # ADX > 25 = trending
ADX_RANGING = 20  # ADX < 20 = ranging
ATR_VOLATILE = 0.03  # ATR/close > 3% = volatile

# Strategy routing
STRATEGY_ROUTING = {
    "strong_trend": ["SupertrendStrategy", "AlligatorTrendV1"],
    "weak_trend": ["MasterTraderV1", "GaussianChannelV1"],
    "ranging": ["BollingerBounceV1"],
    "bear_regime": ["BearCrashShortV1"],
}


def classify_pair(adx, atr_pct, rsi):
    """Classify a pair based on indicator values."""
    if adx > ADX_TRENDING and atr_pct > ATR_VOLATILE:
        return "strong_trend"
    elif adx > ADX_RANGING:
        return "weak_trend"
    elif adx < ADX_RANGING:
        return "ranging"
    else:
        return "weak_trend"


def format_screening_results(pair_data):
    """Format results with strategy routing recommendations."""
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pairs": [],
    }

    for pair in pair_data:
        classification = classify_pair(
            pair.get("adx", 0),
            pair.get("atr_pct", 0),
            pair.get("rsi", 50),
        )
        pair["classification"] = classification
        pair["recommended_strategies"] = STRATEGY_ROUTING.get(classification, [])
        results["pairs"].append(pair)

    return results


def save_results(results):
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved to {OUTPUT_PATH}")


def print_instructions():
    """Print MCP tool sequence for Claude to execute."""
    print("=== Symbol Screener Instructions ===\n")
    print("For each pair, Claude should:\n")
    print("1. chart_set_symbol(symbol)")
    print("2. chart_set_timeframe('60')  # 1H")
    print("3. Ensure ADX and ATR indicators are on chart")
    print("4. data_get_study_values()  # Read ADX, ATR, RSI values")
    print("5. data_get_ohlcv(summary=True)  # Get price context")
    print()
    print("Or use batch_run with action='get_ohlcv' across all pairs.\n")
    print("Pairs to screen:")
    for p in PAIRS:
        print(f"  {p}")
    print(f"\nClassification: ADX>{ADX_TRENDING}=trending, ADX<{ADX_RANGING}=ranging")
    print("Routing:")
    for cls, strats in STRATEGY_ROUTING.items():
        print(f"  {cls} → {', '.join(strats)}")


if __name__ == "__main__":
    print_instructions()
