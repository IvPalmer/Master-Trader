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


# ── New Entry Signal Modules (added 2026-04-16) ─────────────

def donchian_breakout(df: pd.DataFrame, period: int) -> pd.Series:
    """Price closes above the N-period high (from prior bars). Turtle-style."""
    col = f"donch_{period}"
    if col not in df.columns:
        # Shift by 1 so we don't include current bar in the rolling max
        df[col] = df["high"].rolling(period).max().shift(1)
    return (df["close"] > df[col]) & (df["close"].shift(1) <= df[col].shift(1))


def ichimoku_bullish(df: pd.DataFrame) -> pd.Series:
    """Price crosses above Ichimoku cloud (both senkou_a and senkou_b)."""
    if "ichi_sa" not in df.columns:
        tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        df["ichi_sa"] = ((tenkan + kijun) / 2).shift(26)
        df["ichi_sb"] = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2).shift(26)
    above_now = (df["close"] > df["ichi_sa"]) & (df["close"] > df["ichi_sb"])
    below_prev = (df["close"].shift(1) <= df["ichi_sa"].shift(1)) | \
                 (df["close"].shift(1) <= df["ichi_sb"].shift(1))
    return above_now & below_prev


def vwap_reclaim(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Price crosses above rolling VWAP (volume-weighted avg price over period)."""
    col = f"vwap_{period}"
    if col not in df.columns:
        typical = (df["high"] + df["low"] + df["close"]) / 3
        tv = typical * df["volume"]
        df[col] = tv.rolling(period).sum() / (df["volume"].rolling(period).sum() + 1e-10)
    return (df["close"] > df[col]) & (df["close"].shift(1) <= df[col].shift(1))


def keltner_bounce(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> pd.Series:
    """Price crosses above Keltner lower channel (SMA - atr_mult * ATR). ATR-based BB variant."""
    col = f"kelt_lower_{period}_{atr_mult}"
    if col not in df.columns:
        sma = df["close"].rolling(period).mean()
        atr = _atr(df, period)
        df[col] = sma - atr_mult * atr
    return (df["close"] > df[col]) & (df["close"].shift(1) <= df[col].shift(1))


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Current green candle's body engulfs previous red candle's body."""
    prev_red = df["close"].shift(1) < df["open"].shift(1)
    curr_green = df["close"] > df["open"]
    engulf_body = (df["open"] < df["close"].shift(1)) & (df["close"] > df["open"].shift(1))
    curr_body = (df["close"] - df["open"]).abs()
    prev_body = (df["close"].shift(1) - df["open"].shift(1)).abs()
    bigger_body = curr_body > prev_body
    return prev_red & curr_green & engulf_body & bigger_body


# ── Funding Rate Signals ────────────────────────────────────
# Loaded from user_data/data/binance/funding/{PAIR}-funding.feather
# These align with the pair's 1h candles via nearest-past funding rate.

_FUNDING_CACHE = {}  # pair -> DataFrame with date, funding_rate


def _load_funding(pair: str):
    """Lazily load and cache funding rate data for a pair."""
    if pair in _FUNDING_CACHE:
        return _FUNDING_CACHE[pair]
    from pathlib import Path
    p = Path(__file__).parent.parent / "user_data" / "data" / "binance" / "funding" / f"{pair.replace('/', '_')}-funding.feather"
    if not p.exists():
        _FUNDING_CACHE[pair] = None
        return None
    df = pd.read_feather(p)
    # Normalize to unix seconds — handle ms or ns precision datetime
    df["ts"] = df["date"].apply(lambda x: x.timestamp()).astype(np.float64)
    _FUNDING_CACHE[pair] = df.sort_values("ts").reset_index(drop=True)
    return _FUNDING_CACHE[pair]


def _align_funding_to_pair(pair_df: pd.DataFrame, funding_df: pd.DataFrame) -> pd.Series:
    """For each pair_df row, return the funding rate active at that timestamp.

    Uses nearest-past funding rate (funding fixes every 4-8h; carry-forward between fixes).
    """
    if funding_df is None or funding_df.empty:
        return pd.Series(np.nan, index=pair_df.index)
    pair_ts = pair_df["ts"].values
    funding_ts = funding_df["ts"].values
    funding_rates = funding_df["funding_rate"].values
    # For each pair ts, find the latest funding_ts <= pair_ts
    idx = np.searchsorted(funding_ts, pair_ts, side="right") - 1
    idx = np.clip(idx, 0, len(funding_rates) - 1)
    valid = idx >= 0
    result = np.where(valid, funding_rates[idx], np.nan)
    return pd.Series(result, index=pair_df.index)


def funding_extreme_negative(df: pd.DataFrame, percentile: float = 0.05, lookback_periods: int = 1000) -> pd.Series:
    """
    Fire when funding rate is in its bottom percentile (e.g. p5) over lookback.

    Extreme negative funding = perps trading below spot = shorts paying longs =
    crowded short positioning. Often precedes upward reversion.

    percentile: e.g. 0.05 for bottom 5%. Lower = more extreme.
    lookback_periods: window for percentile computation (1000 periods ~= 333 days at 8h funding).
    """
    pair = df.attrs.get("pair", None)
    if pair is None:
        return pd.Series(False, index=df.index)
    funding_df = _load_funding(pair)
    if funding_df is None:
        return pd.Series(False, index=df.index)

    col = f"funding_{int(percentile*100)}_{lookback_periods}"
    if col not in df.columns:
        f_aligned = _align_funding_to_pair(df, funding_df)
        # Rolling percentile threshold
        threshold = f_aligned.rolling(lookback_periods, min_periods=100).quantile(percentile)
        df["_funding_aligned"] = f_aligned
        df[col] = f_aligned <= threshold

    return df[col].fillna(False)


def funding_extreme_positive(df: pd.DataFrame, percentile: float = 0.95, lookback_periods: int = 1000) -> pd.Series:
    """
    Fire when funding rate is in its top percentile.

    Extreme positive funding = longs paying shorts heavily = crowded long positioning.
    Often precedes downward reversion. USE FOR SHORT ENTRIES (not long-only strategies).
    """
    pair = df.attrs.get("pair", None)
    if pair is None:
        return pd.Series(False, index=df.index)
    funding_df = _load_funding(pair)
    if funding_df is None:
        return pd.Series(False, index=df.index)

    col = f"funding_hi_{int(percentile*100)}_{lookback_periods}"
    if col not in df.columns:
        f_aligned = _align_funding_to_pair(df, funding_df)
        threshold = f_aligned.rolling(lookback_periods, min_periods=100).quantile(percentile)
        df[col] = f_aligned >= threshold

    return df[col].fillna(False)


def funding_negative(df: pd.DataFrame) -> pd.Series:
    """Simpler signal: funding rate is outright negative (rare — crowded shorts)."""
    pair = df.attrs.get("pair", None)
    if pair is None:
        return pd.Series(False, index=df.index)
    funding_df = _load_funding(pair)
    if funding_df is None:
        return pd.Series(False, index=df.index)

    if "funding_neg" not in df.columns:
        f_aligned = _align_funding_to_pair(df, funding_df)
        df["funding_neg"] = f_aligned < 0

    return df["funding_neg"].fillna(False)


def funding_below_mean(df: pd.DataFrame, lookback_periods: int = 500) -> pd.Series:
    """Fire when current funding is 1+ std below its rolling mean (relative-extreme)."""
    pair = df.attrs.get("pair", None)
    if pair is None:
        return pd.Series(False, index=df.index)
    funding_df = _load_funding(pair)
    if funding_df is None:
        return pd.Series(False, index=df.index)

    col = f"funding_below_{lookback_periods}"
    if col not in df.columns:
        f_aligned = _align_funding_to_pair(df, funding_df)
        roll_mean = f_aligned.rolling(lookback_periods, min_periods=50).mean()
        roll_std = f_aligned.rolling(lookback_periods, min_periods=50).std()
        df[col] = f_aligned < (roll_mean - roll_std)

    return df[col].fillna(False)


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
    "roi_only": {
        # Per engine v2 finding: trailing stops subtract value; ROI-only works better
        "stoploss": -0.05,
        "trailing_stop_positive": 0,
        "trailing_stop_positive_offset": 0,
        "minimal_roi": {"0": 0.08, "360": 0.05, "720": 0.03, "1440": 0.02},
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
