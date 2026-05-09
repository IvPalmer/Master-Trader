"""
Path-aware re-simulation: walk forward bar-by-bar with proper stoploss check.
For each cascade event, exit on whichever fires FIRST: stoploss, take-profit, or timeout.
This matches Freqtrade native behavior.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_ROOT = Path("/mt/research/data/binance")
PAIRS = [
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
    return df.sort_values("date").reset_index(drop=True)


def detect_cascade_idx(df, drop_pct, recovery_min, vol_mult, vol_lookback=720):
    open_to_low = (df["open"] - df["low"]) / df["open"]
    wick_size = df["open"] - df["low"]
    wick_recovery = np.where(wick_size > 0, (df["close"] - df["low"]) / wick_size, 0)
    vol_mean = df["volume"].rolling(vol_lookback, min_periods=vol_lookback // 2).mean()
    vol_ratio = df["volume"] / vol_mean
    return df.index[
        (open_to_low > drop_pct) &
        (wick_recovery > recovery_min) &
        (vol_ratio > vol_mult) &
        vol_mean.notna()
    ].tolist()


def simulate_path_aware(df, drop_pct, recovery_min, vol_mult, hold_hours, take_profit, stoploss):
    """
    For each cascade idx, walk forward bar by bar:
      - If bar's LOW <= entry * (1 + stoploss) → exit at SL
      - elif bar's HIGH >= entry * (1 + take_profit) → exit at TP
      - else continue
      - if hold_hours reached, exit at close
    Note: if both SL and TP would fire in same bar (high TP, low SL), we conservatively assume SL fired first
    (matches Freqtrade default).
    """
    cascade_idx = detect_cascade_idx(df, drop_pct, recovery_min, vol_mult)
    trades = []
    for idx in cascade_idx:
        if idx + hold_hours >= len(df):
            continue
        entry = df["close"].iloc[idx]
        sl_price = entry * (1 + stoploss)
        tp_price = entry * (1 + take_profit)
        exit_p = None
        exit_reason = None
        for k in range(1, hold_hours + 1):
            bar = df.iloc[idx + k]
            # Check SL first (conservative)
            if bar["low"] <= sl_price:
                exit_p = sl_price
                exit_reason = "sl"
                break
            if bar["high"] >= tp_price:
                exit_p = tp_price
                exit_reason = "tp"
                break
        if exit_p is None:
            exit_p = df["close"].iloc[idx + hold_hours]
            exit_reason = "timeout"
        ret = (exit_p - entry) / entry - ROUND_TRIP_FEE
        trades.append({"date": df["date"].iloc[idx], "ret": ret, "reason": exit_reason})
    return pd.DataFrame(trades)


def evaluate(trades_df_dict, label):
    full = pd.concat([d.assign(pair=p) for p, d in trades_df_dict.items() if not d.empty], ignore_index=True)
    if full.empty:
        return None
    n = len(full)
    wr = (full["ret"] > 0).mean() * 100
    avg = full["ret"].mean() * 100
    pf = full[full["ret"] > 0]["ret"].sum() / abs(full[full["ret"] < 0]["ret"].sum()) if (full["ret"] < 0).any() else float("inf")
    months = (full["date"].max() - full["date"].min()).days / 30
    pair_count = full["pair"].nunique()
    annualized = avg * n / pair_count / months * 12
    by_reason = full["reason"].value_counts().to_dict()
    print(f"  {label:50s}: N={n:4d}, WR={wr:5.1f}%, PF={pf:5.2f}, avg={avg:+.3f}%, ann={annualized:+5.1f}%/yr/pair, exits={by_reason}")
    return {"n": n, "wr": wr, "pf": pf, "avg": avg, "annualized": annualized, "exits": by_reason}


def main():
    pair_dfs = {sym: load_pair(sym) for sym in PAIRS}
    pair_dfs = {k: v for k, v in pair_dfs.items() if v is not None and len(v) >= 720}

    print("=" * 100)
    print("Path-aware re-simulation (matches Freqtrade native: SL/TP/timeout walked bar-by-bar)")
    print("=" * 100)

    # Sweep across stoploss × TP × hold_hours, baseline cascade params
    configs = []
    for drop in [0.05, 0.06, 0.08, 0.10]:
        for vol in [2.0, 3.0]:
            for tp in [0.005, 0.01, 0.015, 0.02, 0.03]:
                for sl in [-0.02, -0.03, -0.05, -0.08, -0.15]:
                    for hold in [12, 24, 48]:
                        if abs(sl) >= tp * 5 or abs(sl) <= tp * 0.5:
                            continue  # skip absurd ratios
                        configs.append((drop, vol, tp, sl, hold))

    results = []
    for cfg in configs:
        drop, vol, tp, sl, hold = cfg
        trades = {}
        for sym, df in pair_dfs.items():
            t = simulate_path_aware(df, drop, 0.4, vol, hold, tp, sl)
            if not t.empty:
                trades[sym] = t
        if not trades:
            continue
        full = pd.concat([d.assign(pair=p) for p, d in trades.items() if not d.empty], ignore_index=True)
        if len(full) < 50:
            continue
        n = len(full)
        wr = (full["ret"] > 0).mean() * 100
        avg = full["ret"].mean() * 100
        total_ret = full["ret"].sum() * 100
        pf = full[full["ret"] > 0]["ret"].sum() / abs(full[full["ret"] < 0]["ret"].sum()) if (full["ret"] < 0).any() else float("inf")
        months = (full["date"].max() - full["date"].min()).days / 30
        pair_count = full["pair"].nunique()
        annualized = avg * n / pair_count / months * 12
        results.append({
            "drop": drop, "vol_mult": vol, "tp": tp, "sl": sl, "hold_h": hold,
            "n": n, "wr_pct": round(wr, 1), "pf": round(pf, 2),
            "avg_pct": round(avg, 3), "total_ret_pct": round(total_ret, 1),
            "ann_pct_per_pair": round(annualized, 2),
            "by_reason": full["reason"].value_counts().to_dict(),
        })

    res_df = pd.DataFrame(results).sort_values("ann_pct_per_pair", ascending=False)
    print("\n=== TOP 15 CONFIGS by annualized %/pair (path-aware) ===")
    print(res_df.head(15).drop(columns=["by_reason"]).to_string(index=False))
    print("\n=== TOP 15 by PF (path-aware) ===")
    print(res_df.sort_values(["pf", "n"], ascending=[False, False]).head(15).drop(columns=["by_reason"]).to_string(index=False))

    if not res_df.empty:
        best = res_df.iloc[0]
        print(f"\n=== BEST CONFIG (annualized) ===")
        print(best.to_dict())

    print("\n=== TRY: NO STOPLOSS (trust the recovery, eat occasional cascade-continuation pain) ===")
    no_sl_results = []
    for drop in [0.05, 0.06, 0.08, 0.10]:
        for vol in [2.0, 3.0]:
            for tp in [0.01, 0.02, 0.03, 0.05]:
                for hold in [24, 48, 96]:
                    sl = -0.50  # effectively none
                    trades = {}
                    for sym, df in pair_dfs.items():
                        t = simulate_path_aware(df, drop, 0.4, vol, hold, tp, sl)
                        if not t.empty:
                            trades[sym] = t
                    if not trades:
                        continue
                    full = pd.concat([d.assign(pair=p) for p, d in trades.items() if not d.empty], ignore_index=True)
                    if len(full) < 50:
                        continue
                    n = len(full)
                    wr = (full["ret"] > 0).mean() * 100
                    avg = full["ret"].mean() * 100
                    pf = full[full["ret"] > 0]["ret"].sum() / abs(full[full["ret"] < 0]["ret"].sum()) if (full["ret"] < 0).any() else float("inf")
                    worst = full["ret"].min() * 100
                    no_sl_results.append({
                        "drop": drop, "vol": vol, "tp": tp, "hold": hold,
                        "n": n, "wr": round(wr, 1), "pf": round(pf, 2),
                        "avg": round(avg, 3), "worst_trade_pct": round(worst, 2),
                    })
    no_sl_df = pd.DataFrame(no_sl_results).sort_values("pf", ascending=False)
    print(no_sl_df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
