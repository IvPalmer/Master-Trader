"""Parameter sweep on opposite-sign earn — threshold × min-hold."""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_ROOT = Path("/mt/research/data")
PAIRS = ["ICP_USDT", "DASH_USDT", "ZEC_USDT"]

BINANCE_TAKER = 0.0004
HL_TAKER = 0.00045
RT_FEES_TAKER = 2 * (BINANCE_TAKER + HL_TAKER)  # 0.17%
RT_FEES_MAKER = 2 * (0.0002 + (-0.0001))  # 0.02%


def load_pair(symbol):
    b_path = DATA_ROOT / "binance" / "funding" / f"{symbol}-funding.feather"
    h_path = DATA_ROOT / "hyperliquid" / "funding" / f"{symbol}-funding.feather"
    if not b_path.exists() or not h_path.exists():
        return None
    b = pd.read_feather(b_path).rename(columns={"funding_rate": "b_rate_8h"})
    h = pd.read_feather(h_path).rename(columns={"funding_rate": "h_rate_1h"})
    b["date"] = pd.to_datetime(b["date"]).dt.floor("1h")
    h["date"] = pd.to_datetime(h["date"]).dt.floor("1h")
    start = max(b["date"].min(), h["date"].min())
    end = min(b["date"].max(), h["date"].max())
    if start >= end:
        return None
    idx = pd.date_range(start, end, freq="1h", tz="UTC")
    df = pd.DataFrame({"date": idx})
    b_resampled = b.drop_duplicates("date").set_index("date").reindex(idx).ffill().reset_index()
    df["b_rate_8h"] = b_resampled["b_rate_8h"].values
    df["b_rate_1h"] = df["b_rate_8h"] / 8.0
    h_dedup = h.drop_duplicates("date", keep="last")
    h_resampled = h_dedup.set_index("date").reindex(idx).ffill().reset_index()
    df["h_rate_1h"] = h_resampled["h_rate_1h"].values
    df["pair"] = symbol
    return df.dropna()


def simulate(df, fees_rt, threshold=1e-5, min_combined=0.0, min_hold_hours=0,
             notional=100.0):
    """
    threshold: per-leg sign-magnitude floor
    min_combined: |b_rate_8h| + |h_rate_1h| × 8 minimum (compares 8h-equivalent magnitudes)
    min_hold_hours: minimum hours to hold before allowing flip
    """
    pos = 0
    hold_hours = 0
    equity = 0.0
    flips = 0
    hours_in_pos = 0
    earn_gross = 0.0
    fees_paid = 0.0

    rows = df[["b_rate_8h", "b_rate_1h", "h_rate_1h"]].values
    for r in rows:
        b8, b1, h1 = r
        combined = abs(b8) + abs(h1) * 8
        if combined < min_combined:
            target = 0
        elif b8 < -threshold and h1 > threshold:
            target = 1
        elif b8 > threshold and h1 < -threshold:
            target = -1
        else:
            target = 0
        # Min-hold lockout
        if pos != 0 and target != pos and hold_hours < min_hold_hours:
            target = pos
        # Rebalance
        if target != pos:
            if pos != 0:
                fees_paid += fees_rt * notional / 2.0
                equity -= fees_rt * notional / 2.0
                flips += 1
            if target != 0:
                fees_paid += fees_rt * notional / 2.0
                equity -= fees_rt * notional / 2.0
            pos = target
            hold_hours = 0
        # Earn
        if pos == 1:
            hour_earn = (-b1 + h1) * notional
            equity += hour_earn
            earn_gross += hour_earn
            hours_in_pos += 1
        elif pos == -1:
            hour_earn = (b1 - h1) * notional
            equity += hour_earn
            earn_gross += hour_earn
            hours_in_pos += 1
        if pos != 0:
            hold_hours += 1

    return {
        "earn_gross": earn_gross,
        "fees_paid": fees_paid,
        "net": equity,
        "flips": flips,
        "hours_in_pos": hours_in_pos,
        "hours_total": len(rows),
    }


def main():
    dfs = {sym: load_pair(sym) for sym in PAIRS}
    dfs = {k: v for k, v in dfs.items() if v is not None}
    total_months = sum(len(v) for v in dfs.values()) / 24 / 30

    sweep_results = []
    for fee_label, fees in [("TAKER", RT_FEES_TAKER), ("MAKER", RT_FEES_MAKER)]:
        for min_combined in [0, 1e-4, 5e-4, 1e-3, 2e-3]:
            for min_hold in [0, 4, 8, 24]:
                total_net = 0.0
                total_gross = 0.0
                total_fees = 0.0
                total_flips = 0
                for sym, df in dfs.items():
                    r = simulate(df, fees, min_combined=min_combined, min_hold_hours=min_hold)
                    total_net += r["net"]
                    total_gross += r["earn_gross"]
                    total_fees += r["fees_paid"]
                    total_flips += r["flips"]
                annualized_pct_per_pair = (total_net / len(dfs)) / total_months * 12
                sweep_results.append({
                    "fees": fee_label,
                    "min_combined_8h": min_combined,
                    "min_hold_h": min_hold,
                    "net_total": round(total_net, 2),
                    "gross_total": round(total_gross, 2),
                    "fees_total": round(total_fees, 2),
                    "flips_total": total_flips,
                    "annualized_per_pair_pct": round(annualized_pct_per_pair, 2),
                })
    df = pd.DataFrame(sweep_results)
    print(df.sort_values(["fees", "annualized_per_pair_pct"], ascending=[True, False]).to_string(index=False))

    print("\n--- Best taker config ---")
    print(df[df["fees"] == "TAKER"].sort_values("annualized_per_pair_pct", ascending=False).head(3).to_string(index=False))
    print("\n--- Best maker config ---")
    print(df[df["fees"] == "MAKER"].sort_values("annualized_per_pair_pct", ascending=False).head(3).to_string(index=False))


if __name__ == "__main__":
    main()
