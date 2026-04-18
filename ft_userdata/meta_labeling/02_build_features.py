"""
Compute regime features at each MT entry time — NO LOOK-AHEAD.

For each trade we take the 1h candle CLOSED AT OR BEFORE open_date (i.e. the
bar whose information was available when MT decided to enter).

Features:
 - BTC: SMA slope (20/50/200), RSI, pos vs SMA50, ATR%, vol percentile
 - Pair: ATR%, ADX, RSI
 - Market breadth: fraction of pairs above their SMA50
 - Fear & Greed index (from cached historical file, if available)
 - Realized vol percentile (30d rolling)
 - time_of_day, day_of_week

Output: features.parquet (trades + features)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import talib.abstract as ta  # type: ignore
    import talib as _talib  # type: ignore
    HAVE_TALIB = True
except Exception:
    HAVE_TALIB = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path("/Users/palmer/ft_userdata/user_data/data/binance")
TRADES = Path(__file__).parent / "trades.parquet"
OUT = Path(__file__).parent / "features.parquet"
FNG_CACHE = Path("/Users/palmer/ft_userdata/user_data/fear_greed_history.json")


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    if HAVE_TALIB:
        return pd.Series(_talib.RSI(series.values.astype(float), timeperiod=period), index=series.index)
    # pure-pandas RSI
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / down
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if HAVE_TALIB:
        return pd.Series(
            _talib.ATR(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float), timeperiod=period),
            index=df.index,
        )
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if HAVE_TALIB:
        return pd.Series(
            _talib.ADX(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float), timeperiod=period),
            index=df.index,
        )
    # cheap ADX approximation via directional movement
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_s = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def load_1h(pair: str) -> pd.DataFrame | None:
    f = DATA_DIR / f"{pair.replace('/', '_')}-1h.feather"
    if not f.exists():
        return None
    df = pd.read_feather(f)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()


def enrich_btc(btc: pd.DataFrame) -> pd.DataFrame:
    btc = btc.copy()
    btc["sma20"] = btc["close"].rolling(20).mean()
    btc["sma50"] = btc["close"].rolling(50).mean()
    btc["sma200"] = btc["close"].rolling(200).mean()
    btc["sma20_slope"] = btc["sma20"].pct_change(20)
    btc["sma50_slope"] = btc["sma50"].pct_change(50)
    btc["sma200_slope"] = btc["sma200"].pct_change(200)
    btc["rsi14"] = rsi(btc["close"], 14)
    btc["atr14"] = atr(btc, 14)
    btc["atr_pct"] = btc["atr14"] / btc["close"]
    btc["pos_vs_sma50"] = (btc["close"] - btc["sma50"]) / btc["sma50"]
    btc["pos_vs_sma200"] = (btc["close"] - btc["sma200"]) / btc["sma200"]
    # 30-day realized vol percentile (720 hourly bars ≈ 30d); use ATR% percentile over 720 bars
    btc["atr_pct_p30d"] = btc["atr14"].rolling(720).apply(
        lambda s: (s.iloc[-1] > s).mean() if s.notna().all() else np.nan, raw=False
    )
    btc["log_ret"] = np.log(btc["close"]).diff()
    btc["rv_24h"] = btc["log_ret"].rolling(24).std() * np.sqrt(24)
    btc["rv_percentile_30d"] = btc["rv_24h"].rolling(720).apply(
        lambda s: (s.iloc[-1] > s).mean(), raw=False
    )
    return btc


def enrich_pair(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sma50_pair"] = df["close"].rolling(50).mean()
    df["above_sma50"] = (df["close"] > df["sma50_pair"]).astype(int)
    df["atr14_pair"] = atr(df, 14)
    df["atr_pct_pair"] = df["atr14_pair"] / df["close"]
    df["adx14_pair"] = adx(df, 14)
    df["rsi14_pair"] = rsi(df["close"], 14)
    return df


def load_fng() -> dict[str, int]:
    if not FNG_CACHE.exists():
        log.warning("No F&G history cache — skipping F&G feature")
        return {}
    with open(FNG_CACHE) as f:
        return json.load(f)


def main() -> None:
    trades = pd.read_parquet(TRADES)
    log.info("Loaded %d trades", len(trades))

    pairs = sorted(trades["pair"].unique())
    log.info("Pairs: %s", pairs)

    # Load + enrich all pair frames
    pair_data: dict[str, pd.DataFrame] = {}
    for p in pairs:
        df = load_1h(p)
        if df is None:
            log.warning("No data for %s", p)
            continue
        pair_data[p] = enrich_pair(df)

    # Load BTC for market features
    btc = load_1h("BTC/USDT")
    if btc is None:
        raise RuntimeError("BTC data missing")
    btc = enrich_btc(btc)

    fng = load_fng()

    # Market breadth: across all 20 pairs, fraction above SMA50 at each BTC index point
    # Build dataframe indexed by BTC hours
    breadth_cols = []
    for p, pdf in pair_data.items():
        col = pdf["above_sma50"].reindex(btc.index).ffill()
        breadth_cols.append(col)
    if breadth_cols:
        breadth_df = pd.concat(breadth_cols, axis=1)
        btc["breadth_above_sma50"] = breadth_df.mean(axis=1)
    else:
        btc["breadth_above_sma50"] = np.nan

    rows = []
    for _, tr in trades.iterrows():
        t = tr["open_date"]
        pair = tr["pair"]
        # Entry uses CLOSE of bar that has just CLOSED — we take the bar at t-1h.
        # Freqtrade `open_date` is the open time of the trade (candle open), so
        # the signal was generated at the close of the prior bar. Use t - 1h.
        t_prev = t - pd.Timedelta(hours=1)
        # BTC features
        try:
            b = btc.loc[:t_prev].iloc[-1]
        except (KeyError, IndexError):
            continue
        # Pair features
        if pair not in pair_data:
            continue
        pdf = pair_data[pair]
        try:
            pr = pdf.loc[:t_prev].iloc[-1]
        except (KeyError, IndexError):
            continue

        day_key = t.strftime("%Y-%m-%d")
        fng_val = fng.get(day_key, np.nan) if fng else np.nan

        row = {
            "pair": pair,
            "open_date": t,
            "label": int(tr["label"]),
            "profit_ratio": float(tr["profit_ratio"]),
            # BTC regime
            "btc_sma20_slope": b.get("sma20_slope"),
            "btc_sma50_slope": b.get("sma50_slope"),
            "btc_sma200_slope": b.get("sma200_slope"),
            "btc_rsi14": b.get("rsi14"),
            "btc_atr_pct": b.get("atr_pct"),
            "btc_pos_vs_sma50": b.get("pos_vs_sma50"),
            "btc_pos_vs_sma200": b.get("pos_vs_sma200"),
            "btc_rv_24h": b.get("rv_24h"),
            "btc_rv_pct_30d": b.get("rv_percentile_30d"),
            # Pair features
            "pair_atr_pct": pr.get("atr_pct_pair"),
            "pair_adx14": pr.get("adx14_pair"),
            "pair_rsi14": pr.get("rsi14_pair"),
            "pair_above_sma50": pr.get("above_sma50"),
            # Market breadth
            "breadth_above_sma50": b.get("breadth_above_sma50"),
            # Sentiment
            "fng": fng_val,
            # Calendar
            "hour": t.hour,
            "dow": t.dayofweek,
        }
        rows.append(row)

    out = pd.DataFrame(rows)
    log.info("Built features for %d/%d trades", len(out), len(trades))
    log.info("NaN counts:\n%s", out.isna().sum())
    out.to_parquet(OUT, index=False)
    log.info("Saved -> %s", OUT)


if __name__ == "__main__":
    main()
