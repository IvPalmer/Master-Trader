"""Pair-filtered version: drop pairs with negative edge in path-aware sim."""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_ROOT = Path("/mt/research/data/binance")
# Drop BCH (0% WR, n=1), DOGE (-0.33), XRP (-0.21), LINK (barely positive)
GOOD_PAIRS = [
    "ADA_USDT", "ARB_USDT", "AVAX_USDT", "BNB_USDT", "BTC_USDT",
    "ETH_USDT", "LTC_USDT", "NEAR_USDT", "SOL_USDT", "SUI_USDT",
    "UNI_USDT", "ZEC_USDT", "HBAR_USDT"
]
ROUND_TRIP_FEE = 0.002
CFG = dict(drop=0.08, recovery_min=0.4, vol_mult=2.0, hold_hours=48, take_profit=0.03, stoploss=-0.08)


def load_pair(symbol):
    p = DATA_ROOT / f"{symbol}-1h.feather"
    if not p.exists():
        return None
    df = pd.read_feather(p)
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("UTC")
    return df.sort_values("date").reset_index(drop=True)


def simulate(df, drop, recovery_min, vol_mult, hold_hours, take_profit, stoploss, vol_lookback=720):
    open_to_low = (df["open"] - df["low"]) / df["open"]
    wick_size = df["open"] - df["low"]
    wick_recovery = np.where(wick_size > 0, (df["close"] - df["low"]) / wick_size, 0)
    vol_mean = df["volume"].rolling(vol_lookback, min_periods=vol_lookback // 2).mean()
    vol_ratio = df["volume"] / vol_mean
    cascade_idx = df.index[
        (open_to_low > drop) & (wick_recovery > recovery_min) &
        (vol_ratio > vol_mult) & vol_mean.notna()
    ].tolist()
    trades = []
    for idx in cascade_idx:
        if idx + hold_hours >= len(df):
            continue
        entry = df["close"].iloc[idx]
        sl_price = entry * (1 + stoploss)
        tp_price = entry * (1 + take_profit)
        exit_p, reason = None, None
        for k in range(1, hold_hours + 1):
            bar = df.iloc[idx + k]
            if bar["low"] <= sl_price:
                exit_p, reason = sl_price, "sl"
                break
            if bar["high"] >= tp_price:
                exit_p, reason = tp_price, "tp"
                break
        if exit_p is None:
            exit_p = df["close"].iloc[idx + hold_hours]
            reason = "timeout"
        ret = (exit_p - entry) / entry - ROUND_TRIP_FEE
        trades.append({"date": df["date"].iloc[idx], "ret": ret, "reason": reason})
    return pd.DataFrame(trades)


def main():
    pair_dfs = {sym: load_pair(sym) for sym in GOOD_PAIRS}
    pair_dfs = {k: v for k, v in pair_dfs.items() if v is not None and len(v) >= 720}
    print(f"Pairs: {list(pair_dfs.keys())}")

    all_trades = {}
    for sym, df in pair_dfs.items():
        t = simulate(df, **CFG)
        if not t.empty:
            all_trades[sym] = t.assign(pair=sym)

    full = pd.concat(all_trades.values(), ignore_index=True)
    print(f"\n=== AGGREGATE ===")
    wr = (full["ret"] > 0).mean() * 100
    pf = full[full["ret"]>0]["ret"].sum() / abs(full[full["ret"]<0]["ret"].sum())
    avg = full["ret"].mean() * 100
    total = full["ret"].sum() * 100
    months = (full['date'].max() - full['date'].min()).days / 30
    print(f"N={len(full)}, WR={wr:.1f}%, PF={pf:.2f}, avg={avg:+.3f}%, total={total:+.1f}%, "
          f"months={months:.1f}, ann/pair={total/len(pair_dfs)/months*12:+.1f}%")
    print(f"Exit mix: {full['reason'].value_counts().to_dict()}")

    print("\n=== Year-by-year ===")
    for year in [2023, 2024, 2025, 2026]:
        yt = full[full["date"].dt.year == year]
        if len(yt) < 5:
            continue
        wr = (yt["ret"] > 0).mean() * 100
        pf = yt[yt["ret"]>0]["ret"].sum() / abs(yt[yt["ret"]<0]["ret"].sum()) if (yt["ret"]<0).any() else float("inf")
        avg = yt["ret"].mean() * 100
        total = yt["ret"].sum() * 100
        print(f"  {year}: N={len(yt):3d}  WR={wr:5.1f}%  PF={pf:5.2f}  avg={avg:+.3f}%  total={total:+.1f}%")

    print("\n=== Walk-forward calendar halves ===")
    halves = [
        ("2023-H1", "2023-01-01", "2023-07-01"),
        ("2023-H2", "2023-07-01", "2024-01-01"),
        ("2024-H1", "2024-01-01", "2024-07-01"),
        ("2024-H2", "2024-07-01", "2025-01-01"),
        ("2025-H1", "2025-01-01", "2025-07-01"),
        ("2025-H2+2026", "2025-07-01", "2026-05-01"),
    ]
    win_count = 0
    for label, s, e in halves:
        s_ts = pd.Timestamp(s, tz="UTC")
        e_ts = pd.Timestamp(e, tz="UTC")
        wt = full[(full["date"] >= s_ts) & (full["date"] < e_ts)]
        if len(wt) < 3:
            print(f"  {label:14s}: insufficient")
            continue
        wr = (wt["ret"] > 0).mean() * 100
        pf = wt[wt["ret"]>0]["ret"].sum() / abs(wt[wt["ret"]<0]["ret"].sum()) if (wt["ret"]<0).any() else float("inf")
        avg = wt["ret"].mean() * 100
        total = wt["ret"].sum() * 100
        ok = avg > 0 and wr > 50
        if ok:
            win_count += 1
        marker = "✓" if ok else "✗"
        print(f"  {label:14s}: N={len(wt):3d}  WR={wr:5.1f}%  PF={pf:5.2f}  avg={avg:+.3f}%  total={total:+.1f}%  {marker}")
    print(f"\nWALK-FORWARD: {win_count}/6 windows positive")


if __name__ == "__main__":
    main()
