"""
Phase 1: Validate the liquidation-rebound hypothesis on existing 1h OHLCV.

Cascade definition (proxy for forceOrder cascade):
  - 1h candle low-to-open drop > X%  (deep wick)
  - close > low + Y% of (open-low)   (some recovery, not falling-knife)
  - volume > Z * 30d rolling mean    (volume confirms forced flow)

Forward return measurement:
  - From the close of the cascade hour, look at +4h, +12h, +24h, +48h
  - Apply 0.2% round-trip taker fees (spot)
  - Compute win rate at each horizon

Goal: prove (or disprove) that after a forced-flow wick, mean-reversion is statistically
present at retail-tradeable horizons.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_ROOT = Path("/mt/research/data/binance")
PAIRS_TO_TEST = [
    "ADA_USDT", "ARB_USDT", "AVAX_USDT", "BCH_USDT", "BNB_USDT", "BTC_USDT", "DOGE_USDT",
    "ETH_USDT", "HBAR_USDT", "LINK_USDT", "LTC_USDT", "NEAR_USDT", "SOL_USDT", "SUI_USDT",
    "TRX_USDT", "UNI_USDT", "XRP_USDT", "ZEC_USDT"
]
ROUND_TRIP_FEE = 0.002  # 0.1% × 2 spot taker (0.075% with BNB but use conservative)


def load_pair(symbol):
    p = DATA_ROOT / f"{symbol}-1h.feather"
    if not p.exists():
        return None
    df = pd.read_feather(p)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_convert("UTC") if df["date"].dt.tz is not None else pd.to_datetime(df["date"]).dt.tz_localize("UTC")
    return df.sort_values("date").reset_index(drop=True)


def detect_cascades(df, drop_pct=0.04, recovery_min=0.4, vol_mult=2.0, vol_lookback=720):
    """
    drop_pct: minimum (open - low) / open
    recovery_min: (close - low) / (open - low) — fraction of wick recovered
    vol_mult: volume must exceed this multiple of rolling mean
    """
    df = df.copy()
    df["open_to_low"] = (df["open"] - df["low"]) / df["open"]
    wick_size = df["open"] - df["low"]
    df["wick_recovery"] = np.where(wick_size > 0, (df["close"] - df["low"]) / wick_size, 0)
    df["vol_mean"] = df["volume"].rolling(vol_lookback, min_periods=vol_lookback // 2).mean()
    df["vol_ratio"] = df["volume"] / df["vol_mean"]

    cascade = (
        (df["open_to_low"] > drop_pct) &
        (df["wick_recovery"] > recovery_min) &
        (df["vol_ratio"] > vol_mult)
    )
    return df[cascade].copy(), df


def measure_forward_returns(df_full, cascade_idx, horizons=(4, 12, 24, 48)):
    """For each cascade row index, compute forward return from close at +N hours."""
    out = []
    for idx in cascade_idx:
        if idx + max(horizons) >= len(df_full):
            continue
        entry = df_full["close"].iloc[idx]
        row = {
            "date": df_full["date"].iloc[idx],
            "drop_pct": df_full["open_to_low"].iloc[idx],
            "wick_recovery": df_full["wick_recovery"].iloc[idx],
            "vol_ratio": df_full["vol_ratio"].iloc[idx],
            "entry": entry,
        }
        for h in horizons:
            exit_p = df_full["close"].iloc[idx + h]
            ret_gross = (exit_p - entry) / entry
            ret_net = ret_gross - ROUND_TRIP_FEE
            row[f"ret_{h}h_gross"] = ret_gross
            row[f"ret_{h}h_net"] = ret_net
        # Also track best mid-hold return (max favorable)
        for h in horizons:
            window_high = df_full["high"].iloc[idx + 1: idx + h + 1].max()
            best = (window_high - entry) / entry - ROUND_TRIP_FEE
            row[f"best_in_{h}h_net"] = best
        out.append(row)
    return pd.DataFrame(out)


def main():
    all_results = []
    print("=" * 80)
    print("Phase 1: Liquidation-rebound hypothesis validation")
    print(f"Round-trip fee: {ROUND_TRIP_FEE*100:.2f}%")
    print("=" * 80)

    for symbol in PAIRS_TO_TEST:
        df = load_pair(symbol)
        if df is None or len(df) < 720:
            print(f"  {symbol}: no data")
            continue
        cascades, df_full = detect_cascades(df)
        cascades = cascades.dropna(subset=["vol_ratio"])
        if len(cascades) < 5:
            continue
        cascade_idx = cascades.index.tolist()
        forward = measure_forward_returns(df_full, cascade_idx)
        if forward.empty:
            continue
        forward["pair"] = symbol
        all_results.append(forward)
        # Per-pair summary
        for h in (4, 12, 24, 48):
            wr = (forward[f"ret_{h}h_net"] > 0).mean()
            avg = forward[f"ret_{h}h_net"].mean()
            best_avg = forward[f"best_in_{h}h_net"].mean()

    if not all_results:
        print("No cascades detected.")
        return

    full = pd.concat(all_results, ignore_index=True)
    print(f"\nTotal cascade events across {full['pair'].nunique()} pairs: {len(full)}")
    print(f"Date range: {full['date'].min()} → {full['date'].max()}")

    print("\n=== Aggregate forward returns (after 0.2% RT fees) ===")
    summary = []
    for h in (4, 12, 24, 48):
        wr = (full[f"ret_{h}h_net"] > 0).mean() * 100
        avg = full[f"ret_{h}h_net"].mean() * 100
        med = full[f"ret_{h}h_net"].median() * 100
        best_avg = full[f"best_in_{h}h_net"].mean() * 100
        summary.append({
            "horizon_h": h,
            "win_rate_pct": round(wr, 1),
            "avg_return_pct": round(avg, 3),
            "median_return_pct": round(med, 3),
            "best_in_window_avg_pct": round(best_avg, 3),
        })
    print(pd.DataFrame(summary).to_string(index=False))

    # Per-pair breakdown for best horizon
    print("\n=== Per-pair edge (24h hold, after fees) ===")
    perpair = full.groupby("pair").agg(
        n=("ret_24h_net", "size"),
        win_rate=("ret_24h_net", lambda x: (x > 0).mean() * 100),
        avg_net=("ret_24h_net", lambda x: x.mean() * 100),
        med_net=("ret_24h_net", lambda x: x.median() * 100),
    ).round(2).sort_values("avg_net", ascending=False)
    print(perpair.to_string())

    # Strategy preview: hold to first +1% target with 4h timeout
    print("\n=== Strategy preview: enter at cascade close, exit at first +1% high or 24h timeout ===")
    target_returns = []
    for _, row in full.iterrows():
        # crude: best-in-24h captures upside; we use min(best_in_24h, +1% take-profit) - fee
        best_net = row["best_in_24h_net"]
        if best_net > 0.01:  # hit +1% target
            pnl = 0.01 - ROUND_TRIP_FEE
        else:
            pnl = row["ret_24h_net"]
        target_returns.append(pnl)
    target_returns = np.array(target_returns)
    wr = (target_returns > 0).mean() * 100
    avg = target_returns.mean() * 100
    print(f"  N events: {len(target_returns)}")
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Avg P&L per event: {avg:.3f}%")
    print(f"  Total return on $100 over sample: ${(target_returns * 100).sum():.2f}")
    months = (full['date'].max() - full['date'].min()).days / 30
    print(f"  Sample length: {months:.1f} months")
    print(f"  Annualized (per pair, single-trade compound): {avg * len(target_returns) / full['pair'].nunique() / months * 12:.2f}%/yr")


if __name__ == "__main__":
    main()
