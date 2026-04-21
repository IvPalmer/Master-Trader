"""
BVC-VPIN pipeline for the master-trader project.

Computes Bulk Volume Classification - Volume-synchronized Probability of
Informed Trading on 1m OHLCV feather files.

Method (Easley, Lopez de Prado, O'Hara 2012):
  1. Volume buckets: group minute bars until cumulative volume >= V.
  2. Within each bucket classify buy/sell volume using the BVC formula:
       buy_vol  = bucket_vol * Phi( delta_close / sigma_returns )
       sell_vol = bucket_vol - buy_vol
     where delta_close is the price change across the bucket and sigma_returns
     is a rolling stddev of bucket returns.
  3. Order imbalance = |buy_vol - sell_vol| / bucket_vol.
  4. VPIN = moving average of imbalance over last N buckets (default 50).

Output: parquet per pair at analysis/vpin_cache/<SYMBOL>_vpin.parquet
Schema: bucket_end_date (UTC), vpin, buy_vol, sell_vol, bucket_vol

Also produces a minute-level mapping file aligning each 1m timestamp to the
VPIN value in force AT THAT MINUTE (strictly past information, no lookahead):
  analysis/vpin_cache/<SYMBOL>_vpin_minute.parquet
  Schema: date, vpin

Use only past data at each minute: the vpin value assigned to minute t is the
VPIN computed from the most recently COMPLETED bucket whose final minute is
strictly before t. This guarantees live-reproducibility.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm


DATA_DIR = Path("/Users/palmer/Work/Dev/master-trader/ft_userdata/user_data/data/binance")
CACHE_DIR = Path("/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis/vpin_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_1m(symbol: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol}_USDT-1m.feather"
    df = pd.read_feather(path)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_vpin(
    df: pd.DataFrame,
    n_buckets_per_day: int = 50,
    window: int = 50,
    sigma_lookback: int = 50,
) -> pd.DataFrame:
    """Compute bucket-level VPIN from 1m OHLCV.

    n_buckets_per_day: tunes V = daily_avg_volume / n_buckets_per_day.
    window: moving average length (N) over bucket imbalances.
    sigma_lookback: rolling stddev lookback for bucket returns.
    """
    if df.empty:
        return pd.DataFrame(columns=["bucket_end_date", "vpin", "buy_vol", "sell_vol", "bucket_vol"])

    # Daily avg volume estimate over the first ~30 days for V sizing.
    # Then V = daily_avg / n_buckets_per_day.
    first_day = df["date"].iloc[0].normalize()
    cut = first_day + pd.Timedelta(days=30)
    seed = df[df["date"] < cut]
    if seed.empty:
        seed = df.head(min(len(df), 30 * 1440))
    daily_avg = seed["volume"].sum() / max(1, (seed["date"].max() - seed["date"].min()).days)
    V = max(daily_avg / n_buckets_per_day, 1e-9)

    # Accumulate volume into buckets. Numpy loop for clarity and speed-fine at ~1.7M bars.
    vol = df["volume"].to_numpy()
    close = df["close"].to_numpy()
    dates = df["date"].to_numpy()

    bucket_end_idx: list[int] = []
    bucket_start_idx: list[int] = []
    bucket_vols: list[float] = []

    acc = 0.0
    start = 0
    for i in range(len(vol)):
        acc += vol[i]
        if acc >= V:
            bucket_start_idx.append(start)
            bucket_end_idx.append(i)
            bucket_vols.append(acc)
            acc = 0.0
            start = i + 1

    if not bucket_end_idx:
        return pd.DataFrame(columns=["bucket_end_date", "vpin", "buy_vol", "sell_vol", "bucket_vol"])

    bucket_end_idx = np.asarray(bucket_end_idx)
    bucket_start_idx = np.asarray(bucket_start_idx)
    bucket_vols_arr = np.asarray(bucket_vols)

    # Bucket return = close[end] - close[start-1] when start > 0; for first bucket use close[start].
    prev_close = np.where(
        bucket_start_idx > 0,
        close[np.clip(bucket_start_idx - 1, 0, len(close) - 1)],
        close[bucket_start_idx],
    )
    end_close = close[bucket_end_idx]
    delta = end_close - prev_close

    # Rolling stddev of bucket returns, using past buckets only (shift by 1).
    delta_series = pd.Series(delta)
    sigma = delta_series.shift(1).rolling(sigma_lookback, min_periods=5).std()
    sigma = sigma.replace(0, np.nan).ffill().bfill()
    sigma = sigma.fillna(delta_series.std() if delta_series.std() > 0 else 1.0)

    z = delta / sigma.to_numpy()
    z = np.clip(z, -10, 10)
    buy_frac = norm.cdf(z)
    buy_vol = bucket_vols_arr * buy_frac
    sell_vol = bucket_vols_arr * (1 - buy_frac)
    imbalance = np.abs(buy_vol - sell_vol) / np.maximum(bucket_vols_arr, 1e-12)

    # VPIN = trailing average of imbalance over last `window` buckets.
    imb_series = pd.Series(imbalance)
    vpin = imb_series.rolling(window, min_periods=max(5, window // 5)).mean()

    out = pd.DataFrame({
        "bucket_end_date": pd.to_datetime(dates[bucket_end_idx], utc=True),
        "vpin": vpin.values,
        "buy_vol": buy_vol,
        "sell_vol": sell_vol,
        "bucket_vol": bucket_vols_arr,
    })
    return out


def build_minute_vpin(df_1m: pd.DataFrame, vpin_bucket: pd.DataFrame) -> pd.DataFrame:
    """Map each minute to the most recent COMPLETED bucket's VPIN.

    To avoid lookahead the mapping uses `merge_asof` with `direction='backward'`
    on a timestamp AFTER the bucket ends (bucket_end_date + 1 minute). This
    guarantees the VPIN value at minute t was computable strictly from data
    strictly BEFORE t.
    """
    if vpin_bucket.empty:
        return pd.DataFrame({"date": df_1m["date"], "vpin": np.nan})

    lookup = vpin_bucket[["bucket_end_date", "vpin"]].copy()
    lookup["available_at"] = lookup["bucket_end_date"] + pd.Timedelta(minutes=1)
    lookup = lookup.sort_values("available_at").reset_index(drop=True)

    left = df_1m[["date"]].sort_values("date").reset_index(drop=True)
    merged = pd.merge_asof(
        left,
        lookup[["available_at", "vpin"]],
        left_on="date",
        right_on="available_at",
        direction="backward",
    )
    return merged[["date", "vpin"]]


def process_symbol(symbol: str, n_buckets_per_day=50, window=50, sigma_lookback=50) -> dict:
    df = load_1m(symbol)
    vpin_bucket = compute_vpin(df, n_buckets_per_day=n_buckets_per_day, window=window, sigma_lookback=sigma_lookback)
    minute_df = build_minute_vpin(df, vpin_bucket)

    bucket_path = CACHE_DIR / f"{symbol}_vpin.parquet"
    minute_path = CACHE_DIR / f"{symbol}_vpin_minute.parquet"
    vpin_bucket.to_parquet(bucket_path, index=False)
    minute_df.to_parquet(minute_path, index=False)

    return {
        "symbol": symbol,
        "buckets": len(vpin_bucket),
        "minutes": len(minute_df),
        "vpin_mean": float(vpin_bucket["vpin"].mean()) if not vpin_bucket.empty else float("nan"),
        "vpin_std": float(vpin_bucket["vpin"].std()) if not vpin_bucket.empty else float("nan"),
        "bucket_path": str(bucket_path),
        "minute_path": str(minute_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--buckets-per-day", type=int, default=50)
    parser.add_argument("--window", type=int, default=50)
    parser.add_argument("--sigma-lookback", type=int, default=50)
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols
    else:
        # Default = Keltner-run pairs.
        symbols = [
            "AAVE","ADA","APT","ARB","AVAX","BCH","BNB","BTC","DOGE","DOT",
            "ENA","ETH","FET","FIL","HBAR","INJ","LINK","LTC","NEAR","ONDO",
            "RENDER","SOL","SUI","TAO","TRUMP","TRX","UNI","VIRTUAL","WLD",
            "XLM","XRP","ZEC",
        ]

    for s in symbols:
        try:
            info = process_symbol(
                s,
                n_buckets_per_day=args.buckets_per_day,
                window=args.window,
                sigma_lookback=args.sigma_lookback,
            )
            print(f"{s}: buckets={info['buckets']} mean_vpin={info['vpin_mean']:.4f} std={info['vpin_std']:.4f}")
        except Exception as e:
            print(f"{s}: ERROR {e}")
