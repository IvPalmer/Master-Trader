"""
Signal modules for Strategy Lab.

Each signal is a function: (df: DataFrame, **params) -> Series[bool]
Entry signals return True when entry conditions are met.
Regime gates return True when market conditions allow trading.
"""

import numpy as np
import pandas as pd


# ── Entry Signal Modules ────────────────────────────────────

def supertrend(df: pd.DataFrame, multiplier: int, period: int) -> pd.Series:
    """Supertrend band is bullish ('up')."""
    col = f"st_{multiplier}_{period}"
    if col not in df.columns:
        _compute_supertrend(df, multiplier, period, col)
    return df[col] == "up"


def supertrend_all(df: pd.DataFrame, configs: list) -> pd.Series:
    """All specified supertrend bands are bullish. configs = [(mult, period), ...]"""
    result = pd.Series(True, index=df.index)
    for mult, period in configs:
        result &= supertrend(df, mult, period)
    return result


def ema_crossover(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    """Fast EMA crosses above slow EMA."""
    f_col = f"ema_{fast}"
    s_col = f"ema_{slow}"
    if f_col not in df.columns:
        df[f_col] = _ema(df["close"], fast)
    if s_col not in df.columns:
        df[s_col] = _ema(df["close"], slow)
    return (df[f_col] > df[s_col]) & (df[f_col].shift(1) <= df[s_col].shift(1))


def rsi_range(df: pd.DataFrame, low: float, high: float, period: int = 14) -> pd.Series:
    """RSI is within [low, high]."""
    col = f"rsi_{period}"
    if col not in df.columns:
        df[col] = _rsi(df["close"], period)
    return (df[col] >= low) & (df[col] <= high)


def macd_crossover(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """MACD line crosses above signal line."""
    m_col = f"macd_{fast}_{slow}"
    s_col = f"macds_{fast}_{slow}_{signal}"
    if m_col not in df.columns:
        ema_fast = _ema(df["close"], fast)
        ema_slow = _ema(df["close"], slow)
        df[m_col] = ema_fast - ema_slow
        df[s_col] = _ema(df[m_col], signal)
    return (df[m_col] > df[s_col]) & (df[m_col].shift(1) <= df[s_col].shift(1))


def bollinger_bounce(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
    """Price was below lower Bollinger band and is now above it (bounce)."""
    lb_col = f"bb_lower_{period}_{std}"
    if lb_col not in df.columns:
        sma = df["close"].rolling(period).mean()
        std_dev = df["close"].rolling(period).std()
        df[lb_col] = sma - std * std_dev
    return (df["close"] > df[lb_col]) & (df["close"].shift(1) <= df[lb_col].shift(1))


def volume_spike(df: pd.DataFrame, multiplier: float, sma_period: int = 20) -> pd.Series:
    """Volume > multiplier * SMA of volume."""
    col = f"vol_sma_{sma_period}"
    if col not in df.columns:
        df[col] = df["volume"].rolling(sma_period).mean()
    return df["volume"] > multiplier * df[col]


def price_above_sma(df: pd.DataFrame, period: int) -> pd.Series:
    """Price above SMA(period)."""
    col = f"sma_{period}"
    if col not in df.columns:
        df[col] = df["close"].rolling(period).mean()
    return df["close"] > df[col]


def adx_trending(df: pd.DataFrame, threshold: float, period: int = 14) -> pd.Series:
    """ADX above threshold — indicates trending market."""
    col = f"adx_{period}"
    if col not in df.columns:
        df[col] = _adx(df, period)
    return df[col] > threshold


def stoch_oversold(df: pd.DataFrame, threshold: float, period: int = 14) -> pd.Series:
    """Stochastic %K below threshold and crossing up (oversold bounce)."""
    k_col = f"stoch_k_{period}"
    if k_col not in df.columns:
        low_min = df["low"].rolling(period).min()
        high_max = df["high"].rolling(period).max()
        df[k_col] = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-10)
    return (df[k_col] > threshold) & (df[k_col].shift(1) <= threshold)


# ── Regime Gate Modules (applied to BTC DataFrame) ──────────

def btc_above_sma(btc_df: pd.DataFrame, period: int) -> pd.Series:
    """BTC close above its SMA(period)."""
    col = f"sma_{period}"
    if col not in btc_df.columns:
        btc_df[col] = btc_df["close"].rolling(period).mean()
    return btc_df["close"] > btc_df[col]


def btc_rsi_floor(btc_df: pd.DataFrame, threshold: float, period: int = 14) -> pd.Series:
    """BTC RSI above threshold."""
    col = f"rsi_{period}"
    if col not in btc_df.columns:
        btc_df[col] = _rsi(btc_df["close"], period)
    return btc_df[col] > threshold


def btc_no_crash(btc_df: pd.DataFrame, lookback: int, pct: float) -> pd.Series:
    """BTC has not dropped more than pct% in the last lookback candles."""
    return btc_df["close"] >= btc_df["close"].shift(lookback) * (1 - pct / 100)


def volatility_regime(df: pd.DataFrame, max_mult: float, atr_period: int = 14, sma_period: int = 50) -> pd.Series:
    """ATR is not above max_mult * ATR SMA — low volatility regime."""
    atr_col = f"atr_{atr_period}"
    atr_sma_col = f"atr_sma_{atr_period}_{sma_period}"
    if atr_col not in df.columns:
        df[atr_col] = _atr(df, atr_period)
    if atr_sma_col not in df.columns:
        df[atr_sma_col] = df[atr_col].rolling(sma_period).mean()
    return df[atr_col] < max_mult * df[atr_sma_col]


# ── Exit Profiles ───────────────────────────────────────────

EXIT_PROFILES = {
    "tight": {
        "stoploss": -0.03,
        "trailing_stop_positive": 0.015,
        "trailing_stop_positive_offset": 0.02,
        "minimal_roi": {"0": 0.03, "360": 0.02, "720": 0.015, "1440": 0.008},
        "exit_profit_only": True,
        "exit_profit_offset": 0.005,
    },
    "balanced": {
        "stoploss": -0.05,
        "trailing_stop_positive": 0.02,
        "trailing_stop_positive_offset": 0.03,
        "minimal_roi": {"0": 0.08, "360": 0.05, "720": 0.03, "1440": 0.02},
        "exit_profit_only": True,
        "exit_profit_offset": 0.01,
    },
    "wide": {
        "stoploss": -0.07,
        "trailing_stop_positive": 0.03,
        "trailing_stop_positive_offset": 0.05,
        "minimal_roi": {"0": 0.10, "360": 0.07, "720": 0.04, "1440": 0.02},
        "exit_profit_only": True,
        "exit_profit_offset": 0.01,
    },
}


# ── Internal Indicator Helpers ──────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _adx(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = _atr(df, period)
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / (atr + 1e-10))
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / (atr + 1e-10))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.ewm(alpha=1/period, min_periods=period).mean()


def _compute_supertrend(df: pd.DataFrame, multiplier: int, period: int, col_name: str):
    """Compute supertrend and store as column."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    length = len(df)

    atr = _atr(df, period).values
    basic_ub = (high + low) / 2 + multiplier * atr
    basic_lb = (high + low) / 2 - multiplier * atr

    final_ub = np.zeros(length)
    final_lb = np.zeros(length)
    for i in range(period, length):
        final_ub[i] = basic_ub[i] if basic_ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1] else final_ub[i-1]
        final_lb[i] = basic_lb[i] if basic_lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1] else final_lb[i-1]

    st = np.zeros(length)
    for i in range(period, length):
        if st[i-1] == final_ub[i-1]:
            st[i] = final_ub[i] if close[i] <= final_ub[i] else final_lb[i]
        elif st[i-1] == final_lb[i-1]:
            st[i] = final_lb[i] if close[i] >= final_lb[i] else final_ub[i]

    stx = np.where(st > 0, np.where(close < st, "down", "up"), "none")
    df[col_name] = stx
