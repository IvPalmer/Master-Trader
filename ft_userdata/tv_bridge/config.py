"""
Strategy → TradingView indicator mappings.
Single source of truth for replicating bot indicators on TV charts.
"""
import json
import os

BOTS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "bots_config.json")
PINE_DIR = os.path.join(os.path.dirname(__file__), "pine")
TRADE_LOGS_DIR = os.path.join(os.path.dirname(__file__), "trade_logs")
LAB_PINE_DIR = os.path.join(os.path.dirname(__file__), "lab_pine")
TV_BRIEF_STATE_PATH = os.path.join(os.path.dirname(__file__), "tv_brief_state.json")

API_USER = "freqtrader"
API_PASS = "mastertrader"

# TradingView full indicator names (for chart_manage_indicator)
TV_INDICATOR_NAMES = {
    "supertrend": "Supertrend",
    "rsi": "Relative Strength Index",
    "adx": "Average Directional Index",
    "ema": "EMA",
    "sma": "SMA",
    "bb": "Bollinger Bands",
    "macd": "MACD",
    "alligator": "Williams Alligator",
    "atr": "Average True Range",
    "di": "Directional Movement Index",
    "volume": "Volume",
}

# Per-strategy indicator setup for TV charts
# Each entry: list of {"name": TV indicator name, "inputs": {param: value}}
STRATEGY_TV_INDICATORS = {
    "SupertrendStrategy": {
        "timeframe": "60",  # TV uses minutes as string
        "pine_file": "supertrend_strategy.pine",
        "builtin_indicators": [
            {"name": "Supertrend", "inputs": {"Factor": 4, "ATR Period": 8}},
            {"name": "Supertrend", "inputs": {"Factor": 7, "ATR Period": 9}},
            {"name": "Supertrend", "inputs": {"Factor": 1, "ATR Period": 8}},
            {"name": "Relative Strength Index", "inputs": {"RSI Length": 14}},
            {"name": "SMA", "inputs": {"Length": 200}},
            {"name": "SMA", "inputs": {"Length": 50}},
            {"name": "Average Directional Index", "inputs": {"ADX Smoothing": 14, "DI Length": 14}},
        ],
    },
    "MasterTraderV1": {
        "timeframe": "60",
        "pine_file": "master_trader_v1.pine",
        "builtin_indicators": [
            {"name": "EMA", "inputs": {"Length": 9}},
            {"name": "EMA", "inputs": {"Length": 21}},
            {"name": "Relative Strength Index", "inputs": {"RSI Length": 14}},
        ],
    },
    "AlligatorTrendV1": {
        "timeframe": "1D",
        "pine_file": "alligator_trend_v1.pine",
        "builtin_indicators": [
            {"name": "Williams Alligator"},
            {"name": "Average True Range", "inputs": {"Length": 14}},
        ],
    },
    "GaussianChannelV1": {
        "timeframe": "1D",
        "pine_file": "gaussian_channel_v1.pine",
        "builtin_indicators": [],  # All custom — Pine Script only
    },
    "BearCrashShortV1": {
        "timeframe": "60",
        "pine_file": "bear_crash_short_v1.pine",
        "builtin_indicators": [
            {"name": "Average Directional Index", "inputs": {"ADX Smoothing": 14, "DI Length": 14}},
            {"name": "Relative Strength Index", "inputs": {"RSI Length": 14}},
            {"name": "MACD", "inputs": {"Fast Length": 12, "Slow Length": 26, "Signal Smoothing": 9}},
            {"name": "SMA", "inputs": {"Length": 200}},
        ],
    },
    "BollingerBounceV1": {
        "timeframe": "60",
        "pine_file": "bollinger_bounce_v1.pine",
        "builtin_indicators": [
            {"name": "Bollinger Bands", "inputs": {"Length": 20, "StdDev": 2.0}},
            {"name": "Relative Strength Index", "inputs": {"RSI Length": 14}},
            {"name": "Average Directional Index", "inputs": {"ADX Smoothing": 14, "DI Length": 14}},
        ],
    },
}

# TV dashboard tab layout
TV_DASHBOARD_TABS = [
    {"name": "BTC Guard", "symbol": "BINANCE:BTCUSDT", "timeframe": "60", "pine": "btc_guard_dashboard.pine"},
    {"name": "Supertrend", "symbol": "BINANCE:BTCUSDT", "timeframe": "60", "pine": "supertrend_strategy.pine"},
    {"name": "MasterTrader", "symbol": "BINANCE:BTCUSDT", "timeframe": "60", "pine": "master_trader_v1.pine"},
    {"name": "Alligator", "symbol": "BINANCE:BTCUSDT", "timeframe": "1D", "pine": "alligator_trend_v1.pine"},
    {"name": "Gaussian", "symbol": "BINANCE:BTCUSDT", "timeframe": "1D", "pine": "gaussian_channel_v1.pine"},
    {"name": "BearCrash", "symbol": "BINANCE:ETHUSDT", "timeframe": "60", "pine": "bear_crash_short_v1.pine"},
    {"name": "BBounce", "symbol": "BINANCE:ETHUSDT", "timeframe": "60", "pine": "bollinger_bounce_v1.pine"},
    {"name": "SignalLab", "symbol": "BINANCE:BTCUSDT", "timeframe": "60", "pine": None},
]

# Strategy Lab signal → Pine Script mapping
SIGNAL_TO_PINE = {
    "bb_lower_bounce": "ta.crossover(close, bb_lower)",
    "rsi_30_70": "(rsi_val >= 30 and rsi_val <= 70)",
    "rsi_oversold": "(rsi_val < 30)",
    "rsi_overbought": "(rsi_val > 70)",
    "adx_trending": "(adx_val > 25)",
    "ema_cross_up": "ta.crossover(ema_fast, ema_slow)",
    "ema_cross_down": "ta.crossunder(ema_fast, ema_slow)",
    "supertrend_up": "(ta.supertrend(3, 10)[1] > 0)",
    "volume_above_avg": "(volume > ta.sma(volume, 20))",
    "close_above_sma200": "(close > ta.sma(close, 200))",
    "close_below_sma200": "(close < ta.sma(close, 200))",
    "macd_bullish": "(macd_line > signal_line)",
    "macd_bearish": "(macd_line < signal_line)",
}


def load_bots_config():
    with open(BOTS_CONFIG_PATH) as f:
        return json.load(f)


def active_bots():
    cfg = load_bots_config()
    return {name: bot for name, bot in cfg["bots"].items() if bot.get("active")}


def pine_path(filename):
    return os.path.join(PINE_DIR, filename)
