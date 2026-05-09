"""
Phase 2: Robustness checks before committing to a strategy.
- Year-by-year breakdown (regime stability check)
- 6-window calendar-half walk-forward
- Threshold sensitivity sweep
- Per-pair recommendations for whitelist
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
ROUND_TRIP_FEE = 0.002


def load_pair(symbol):
    p = DATA_ROOT / f"{symbol}-1h.feather"
    if not p.exists():
        return None
    df = pd.read_feather(p)
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("UTC")
    else:
        df["date"] = df["date"].dt.tz_convert("UTC")
    return df.sort_values("date").reset_index(drop=True)


def detect_and_measure(df, drop_pct, recovery_min, vol_mult, vol_lookback=720,
                       hold_hours=24, take_profit=0.01):
    """Returns DataFrame of trades with realized P&L (TP hit OR timeout)."""
    df = df.copy()
    open_to_low = (df["open"] - df["low"]) / df["open"]
    wick_size = df["open"] - df["low"]
    wick_recovery = np.where(wick_size > 0, (df["close"] - df["low"]) / wick_size, 0)
    vol_mean = df["volume"].rolling(vol_lookback, min_periods=vol_lookback // 2).mean()
    vol_ratio = df["volume"] / vol_mean

    cascade = (open_to_low > drop_pct) & (wick_recovery > recovery_min) & (vol_ratio > vol_mult)
    cascade_idx = df.index[cascade].tolist()

    trades = []
    for idx in cascade_idx:
        if idx + hold_hours >= len(df):
            continue
        entry = df["close"].iloc[idx]
        # Walk forward bar-by-bar; first bar where high >= entry × (1+TP) → exit at TP
        # else exit at close of idx + hold_hours
        exit_p = None
        exit_reason = None
        for k in range(1, hold_hours + 1):
            high = df["high"].iloc[idx + k]
            if high >= entry * (1 + take_profit):
                exit_p = entry * (1 + take_profit)
                exit_reason = "tp"
                exit_idx = idx + k
                break
        if exit_p is None:
            exit_p = df["close"].iloc[idx + hold_hours]
            exit_idx = idx + hold_hours
            exit_reason = "timeout"
        ret_gross = (exit_p - entry) / entry
        ret_net = ret_gross - ROUND_TRIP_FEE
        trades.append({
            "date": df["date"].iloc[idx],
            "exit_date": df["date"].iloc[exit_idx],
            "entry": entry,
            "exit": exit_p,
            "ret_net": ret_net,
            "exit_reason": exit_reason,
        })
    return pd.DataFrame(trades)


def aggregate(trades_dfs, label="all"):
    if not trades_dfs:
        return None
    full = pd.concat([d.assign(pair=p) for p, d in trades_dfs.items() if not d.empty], ignore_index=True)
    if full.empty:
        return None
    n = len(full)
    wr = (full["ret_net"] > 0).mean() * 100
    avg = full["ret_net"].mean() * 100
    pf = full[full["ret_net"] > 0]["ret_net"].sum() / abs(full[full["ret_net"] < 0]["ret_net"].sum()) if (full["ret_net"] < 0).any() else float("inf")
    months = (full["date"].max() - full["date"].min()).days / 30
    pair_count = full["pair"].nunique()
    annualized = avg * n / pair_count / months * 12 if months > 0 else 0
    print(f"\n--- {label} ---")
    print(f"  N={n}, pairs={pair_count}, months={months:.1f}")
    print(f"  WR {wr:.1f}%, avg-net {avg:.3f}%, PF {pf:.2f}, annualized {annualized:+.2f}%/yr/pair")
    if "exit_reason" in full.columns:
        print(f"  Exit mix: {full['exit_reason'].value_counts().to_dict()}")
    return {"wr": wr, "avg": avg, "pf": pf, "n": n, "annualized": annualized}


def main():
    # Default config (from phase 1 success)
    cfg = dict(drop_pct=0.04, recovery_min=0.4, vol_mult=2.0, hold_hours=24, take_profit=0.01)

    # Load all pairs once
    pair_dfs = {}
    for sym in PAIRS_TO_TEST:
        df = load_pair(sym)
        if df is not None and len(df) >= 720:
            pair_dfs[sym] = df

    # Year-by-year
    print("=" * 80)
    print("YEAR-BY-YEAR (default config)")
    print("=" * 80)
    for year in [2023, 2024, 2025, 2026]:
        year_trades = {}
        for sym, df in pair_dfs.items():
            t = detect_and_measure(df, **cfg)
            if not t.empty:
                year_trades[sym] = t[t["date"].dt.year == year]
        aggregate(year_trades, label=f"{year}")

    # 6-window calendar-half walk-forward
    print("\n" + "=" * 80)
    print("6-WINDOW WALK-FORWARD (calendar halves)")
    print("=" * 80)
    halves = [
        ("2023-H1", "2023-01-01", "2023-07-01"),
        ("2023-H2", "2023-07-01", "2024-01-01"),
        ("2024-H1", "2024-01-01", "2024-07-01"),
        ("2024-H2", "2024-07-01", "2025-01-01"),
        ("2025-H1", "2025-01-01", "2025-07-01"),
        ("2025-H2+2026", "2025-07-01", "2026-05-01"),
    ]
    win_count = 0
    for label, start, end in halves:
        s = pd.Timestamp(start, tz="UTC")
        e = pd.Timestamp(end, tz="UTC")
        win_trades = {}
        for sym, df in pair_dfs.items():
            t = detect_and_measure(df, **cfg)
            if not t.empty:
                win_trades[sym] = t[(t["date"] >= s) & (t["date"] < e)]
        r = aggregate(win_trades, label=label)
        if r and r["avg"] > 0 and r["wr"] > 50:
            win_count += 1
    print(f"\nWALK-FORWARD: {win_count}/6 windows positive (WR>50% AND avg>0)")

    # Threshold sensitivity sweep
    print("\n" + "=" * 80)
    print("THRESHOLD SENSITIVITY SWEEP")
    print("=" * 80)
    sweep = []
    for drop in [0.03, 0.04, 0.05, 0.06]:
        for vol in [1.5, 2.0, 2.5, 3.0]:
            for tp in [0.008, 0.01, 0.015, 0.02]:
                for hold in [12, 24, 48]:
                    sym_trades = {}
                    for sym, df in pair_dfs.items():
                        t = detect_and_measure(df, drop_pct=drop, recovery_min=0.4,
                                               vol_mult=vol, hold_hours=hold, take_profit=tp)
                        if not t.empty:
                            sym_trades[sym] = t
                    if not sym_trades:
                        continue
                    full = pd.concat([d.assign(pair=p) for p, d in sym_trades.items() if not d.empty],
                                     ignore_index=True)
                    if len(full) < 50:
                        continue
                    n = len(full)
                    wr = (full["ret_net"] > 0).mean() * 100
                    avg = full["ret_net"].mean() * 100
                    pf = (full[full["ret_net"] > 0]["ret_net"].sum() /
                          abs(full[full["ret_net"] < 0]["ret_net"].sum())) if (full["ret_net"] < 0).any() else float("inf")
                    sweep.append({
                        "drop_pct": drop, "vol_mult": vol, "tp": tp, "hold_h": hold,
                        "n": n, "wr_pct": round(wr, 1), "avg_net_pct": round(avg, 3),
                        "pf": round(pf, 2),
                    })
    sweep_df = pd.DataFrame(sweep).sort_values(["pf", "n"], ascending=[False, False]).head(15)
    print(sweep_df.to_string(index=False))

    print("\n=== Best by PF (min N=50) ===")
    print(sweep_df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
