"""
Path A reformulation #1 — opposite-sign funding earn (Binance perp + Hyperliquid perp).

Hypothesis: when sign(binance_funding) != sign(hyperliquid_funding), a delta-neutral
two-leg position can collect funding on BOTH legs simultaneously. Switch direction
based on which way the signs diverge. Apply realistic fees.

Fee model:
  Binance perp taker: 0.04% per side
  Hyperliquid perp taker: 0.045% per side
  Round-trip per leg-pair (open+close both legs): 0.17%

Funding cadence:
  Binance perp: settles every 8h (rate is per-8h)
  Hyperliquid: settles hourly

Convention: convert Binance to per-hour-equivalent (rate / 8) for direct compare;
this is approximation since payments only fire at boundaries, but for a slow-decision
simulator (rebalances at most once per hour) the effect is small.

Position sign convention:
  funding_rate > 0 → longs PAY shorts → short receives
  funding_rate < 0 → shorts PAY longs → long receives

So the "opposite-sign earn" configurations:
  (a) b > 0 AND h < 0: SHORT binance (receive), LONG hl (receive)
  (b) b < 0 AND h > 0: LONG binance (receive), SHORT hl (receive)

When sign(b) == sign(h), one leg always pays — the bot stays flat.

Output: per-pair edge after fees, aggregate, and a closure or pursue verdict.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

DATA_ROOT = Path("/mt/research/data")
PAIRS = ["ICP_USDT", "DASH_USDT", "ZEC_USDT"]

# Fee model (decimal)
BINANCE_TAKER = 0.0004
HL_TAKER = 0.00045
RT_FEES = 2 * (BINANCE_TAKER + HL_TAKER)  # 0.0017 = 0.17%

# Optional maker variant
BINANCE_MAKER = 0.0002
HL_MAKER = -0.0001  # HL has small rebate
RT_FEES_MAKER = 2 * (BINANCE_MAKER + HL_MAKER)  # 0.0002 = 0.02%

# Funding-rate threshold: skip noise-level signs (avoid flip-flopping on near-zero)
FUNDING_THRESHOLD = 0.00001  # 0.001% / settlement


def load_pair(symbol):
    b_path = DATA_ROOT / "binance" / "funding" / f"{symbol}-funding.feather"
    h_path = DATA_ROOT / "hyperliquid" / "funding" / f"{symbol}-funding.feather"
    if not b_path.exists() or not h_path.exists():
        return None
    b = pd.read_feather(b_path).rename(columns={"funding_rate": "b_rate_8h"})
    h = pd.read_feather(h_path).rename(columns={"funding_rate": "h_rate_1h"})
    # Round timestamps to the hour for matching
    b["date"] = pd.to_datetime(b["date"]).dt.floor("1h")
    h["date"] = pd.to_datetime(h["date"]).dt.floor("1h")
    # Build hourly index over the overlap
    start = max(b["date"].min(), h["date"].min())
    end = min(b["date"].max(), h["date"].max())
    if start >= end:
        return None
    idx = pd.date_range(start, end, freq="1h", tz="UTC")
    df = pd.DataFrame({"date": idx})
    # Forward-fill Binance 8h rate to hourly; convert to hourly-equivalent
    b_resampled = b.set_index("date").reindex(idx).ffill().reset_index().rename(columns={"index": "date"})
    df["b_rate_8h"] = b_resampled["b_rate_8h"].values
    df["b_rate_1h"] = df["b_rate_8h"] / 8.0
    # HL is already hourly
    h_dedup = h.drop_duplicates("date", keep="last")
    h_resampled = h_dedup.set_index("date").reindex(idx).ffill().reset_index().rename(columns={"index": "date"})
    df["h_rate_1h"] = h_resampled["h_rate_1h"].values
    df["pair"] = symbol
    df = df.dropna()
    return df


def simulate(df, fees_rt, threshold=FUNDING_THRESHOLD, notional=100.0):
    """
    State machine: at each hour, decide target config.
      target = +1 (long binance, short hl) when b<-thr AND h>+thr
      target = -1 (short binance, long hl) when b>+thr AND h<-thr
      target = 0 when same-sign or near-zero
    Position changes incur 4 leg-trades = fees_rt × notional.
    Funding earn per hour in position:
      target = +1: receive |b_rate_1h| (long under negative funding) + receive |h_rate_1h| (short under positive funding)
      target = -1: same magnitude
    """
    pos = 0
    equity = 0.0
    flips = 0
    hours_in_pos = 0
    hours_total = len(df)
    earn_gross = 0.0
    fees_paid = 0.0
    eq_series = []

    for _, row in df.iterrows():
        b = row["b_rate_1h"]
        h = row["h_rate_1h"]
        b8 = row["b_rate_8h"]
        # Use 8h-rate sign for Binance (since that's the actual settlement period sign)
        if b8 < -threshold and h > threshold:
            target = 1
        elif b8 > threshold and h < -threshold:
            target = -1
        else:
            target = 0
        # Rebalance if target differs
        if target != pos:
            if pos != 0:
                fees_paid += fees_rt * notional / 2.0  # close legs
                equity -= fees_rt * notional / 2.0
                flips += 1
            if target != 0:
                fees_paid += fees_rt * notional / 2.0  # open legs
                equity -= fees_rt * notional / 2.0
            pos = target
        # Earn this hour
        if pos != 0:
            # When pos = +1: long binance (earn -b * notional but b<0 so positive), short hl (earn -h * notional, h>0 so positive)
            #               net = (-b_rate_1h * 1) + (-h_rate_1h * -1) = -b + h... wait let me re-derive
            # If long binance perp: pay rate × notional when funding > 0; receive when funding < 0
            #   so per-hour PnL on binance leg = -b_rate_1h × notional × pos_b
            # If pos = +1 → long binance (pos_b = +1) → leg_earn_b = -b_rate_1h × notional
            #            and short hl (pos_h = -1) → leg_earn_h = +h_rate_1h × notional
            # If pos = -1 → short binance (pos_b = -1) → leg_earn_b = +b_rate_1h × notional
            #            and long hl (pos_h = +1) → leg_earn_h = -h_rate_1h × notional
            if pos == 1:
                hour_earn = (-b + h) * notional
            else:  # pos == -1
                hour_earn = (b - h) * notional
            equity += hour_earn
            earn_gross += hour_earn
            hours_in_pos += 1
        eq_series.append(equity)

    return {
        "hours_total": hours_total,
        "hours_in_pos": hours_in_pos,
        "pct_time_in_pos": hours_in_pos / max(hours_total, 1),
        "flips": flips,
        "earn_gross": earn_gross,
        "fees_paid": fees_paid,
        "net_pnl": equity,
        "net_pct": equity / notional * 100,
        "eq_series": eq_series,
    }


def main():
    print("=" * 70)
    print(f"Opposite-sign funding earn — taker fees {RT_FEES*100:.2f}% RT, "
          f"maker variant {RT_FEES_MAKER*100:.3f}% RT")
    print("=" * 70)

    aggregated = []
    for symbol in PAIRS:
        df = load_pair(symbol)
        if df is None or len(df) < 24:
            print(f"\n{symbol}: insufficient data")
            continue
        print(f"\n{symbol} — overlap {df['date'].min()} → {df['date'].max()} "
              f"({len(df)} hours, {len(df)/24/30:.1f} months)")
        # Sign distribution
        same_sign = ((df["b_rate_8h"] > 0) & (df["h_rate_1h"] > 0)).mean() + \
                    ((df["b_rate_8h"] < 0) & (df["h_rate_1h"] < 0)).mean()
        opp_sign = ((df["b_rate_8h"] > 0) & (df["h_rate_1h"] < 0)).mean() + \
                   ((df["b_rate_8h"] < 0) & (df["h_rate_1h"] > 0)).mean()
        print(f"  sign distribution: same={same_sign*100:.1f}% opposite={opp_sign*100:.1f}%")
        # Run taker
        for label, fees in [("TAKER (0.17%)", RT_FEES), ("MAKER (0.02%)", RT_FEES_MAKER)]:
            r = simulate(df, fees)
            print(f"  {label}: gross +${r['earn_gross']:.4f}, fees -${r['fees_paid']:.4f}, "
                  f"net {r['net_pct']:+.4f}% on $100, "
                  f"flips={r['flips']}, time-in-pos={r['pct_time_in_pos']*100:.1f}%")
            if label.startswith("TAKER"):
                aggregated.append({
                    "pair": symbol,
                    "hours": len(df),
                    "earn_gross": r["earn_gross"],
                    "fees": r["fees_paid"],
                    "net": r["net_pnl"],
                    "net_pct": r["net_pct"],
                    "flips": r["flips"],
                    "time_in_pos_pct": r["pct_time_in_pos"] * 100,
                })

    print("\n" + "=" * 70)
    print("AGGREGATE (TAKER fees only)")
    print("=" * 70)
    if aggregated:
        agg = pd.DataFrame(aggregated)
        print(agg.to_string(index=False))
        total_net = agg["net"].sum()
        total_hours = agg["hours"].sum()
        total_months = total_hours / 24 / 30
        print(f"\nTotal net across {len(agg)} pairs over {total_months:.1f} pair-months: "
              f"${total_net:+.4f}")
        # Annualized
        if total_months > 0:
            annualized = total_net / total_months * 12
            print(f"Annualized (per-pair $100 notional): ${annualized:+.4f}/yr/pair")
            print(f"Annualized return: {annualized:+.2f}% on $100 notional per pair")
        # Verdict
        if total_net > 0 and total_net > total_hours / 24 * 0.001:  # > $0.001/day per pair
            print("\nVERDICT: SIGNAL POSITIVE AFTER TAKER FEES — investigate further")
        else:
            print("\nVERDICT: NEGATIVE OR NOISE-LEVEL EDGE — taker fees kill the spread")


if __name__ == "__main__":
    main()
