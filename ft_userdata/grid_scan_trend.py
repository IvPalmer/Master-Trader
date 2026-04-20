#!/usr/bin/env python3
"""Trend-following grid scan: Donchian / EMA / Supertrend / MACD / Ichimoku
× vol / adx confirmations × BTC gates × exit profiles.

Goal: find ONE trend-following candidate passing +20% / PF 1.3 / year-consistency
over the full 3.3-year window with 1m-detail simulation.
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from strategy_lab.engine import (
    SignalCombo, get_available_pairs, load_all_pairs, load_detail_data, screen_combo,
)
from strategy_lab.signals import (
    EXIT_PROFILES,
    adx_trending, btc_above_sma, btc_no_crash, btc_rsi_floor,
    donchian_breakout, ema_crossover, ichimoku_bullish, macd_crossover,
    supertrend, supertrend_all, volume_spike, vwap_reclaim,
)
import pandas as pd

pairs = get_available_pairs(require_detail=True)
if "BTC/USDT" not in pairs:
    pairs.append("BTC/USDT")

print(f"Loading {len(pairs)} pairs with 1m detail...")
pair_data = load_all_pairs(pairs)
btc_df = pair_data["BTC/USDT"]
trading_data = {k: v for k, v in pair_data.items() if k != "BTC/USDT"}
detail_data = load_detail_data(list(trading_data.keys()) + ["BTC/USDT"])

tr_start = datetime.strptime("20230101", "%Y%m%d").timestamp()
tr_end = datetime.strptime("20260415", "%Y%m%d").timestamp()

# ── Trend anchors ──
anchors = [
    ("donch(20)", lambda df: donchian_breakout(df, 20)),
    ("donch(30)", lambda df: donchian_breakout(df, 30)),
    ("donch(55)", lambda df: donchian_breakout(df, 55)),
    ("donch(100)", lambda df: donchian_breakout(df, 100)),
    ("ema(9,21)", lambda df: ema_crossover(df, 9, 21)),
    ("ema(12,26)", lambda df: ema_crossover(df, 12, 26)),
    ("ema(5,21)", lambda df: ema_crossover(df, 5, 21)),
    ("ema(21,55)", lambda df: ema_crossover(df, 21, 55)),
    ("st(3,10)", lambda df: supertrend(df, 3, 10)),
    ("st(5,14)", lambda df: supertrend(df, 5, 14)),
    ("macd", lambda df: macd_crossover(df)),
    ("ichi", lambda df: ichimoku_bullish(df)),
    ("vwap(50)", lambda df: vwap_reclaim(df, 50)),
]

# ── Confirmations ──
confirms = [
    ("", lambda df: pd.Series(True, index=df.index)),
    ("vol(1.5)", lambda df: volume_spike(df, 1.5)),
    ("vol(2.0)", lambda df: volume_spike(df, 2.0)),
    ("adx(20)", lambda df: adx_trending(df, 20)),
    ("adx(25)", lambda df: adx_trending(df, 25)),
    ("adx(25)+vol(1.5)", lambda df: adx_trending(df, 25) & volume_spike(df, 1.5)),
    ("adx(20)+vol(1.5)", lambda df: adx_trending(df, 20) & volume_spike(df, 1.5)),
]

# ── Gates (all require BTC above SMA50 or similar for LONG trend) ──
gates = [
    ("btc_sma50", lambda df: btc_above_sma(df, 50)),
    ("btc_sma200", lambda df: btc_above_sma(df, 200)),
    ("btc_sma50+sma200", lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200)),
    ("btc_sma50+nc24", lambda df: btc_above_sma(df, 50) & btc_no_crash(df, 24, 3)),
]

# ── Exit profiles (roi_only + wide known-good for trend; tight hurts) ──
exits = ["wide", "roi_only", "balanced"]

print(f"\nScanning {len(anchors)} × {len(confirms)} × {len(gates)} × {len(exits)} = "
      f"{len(anchors)*len(confirms)*len(gates)*len(exits)} combos ...")

t0 = time.time()
results = []
count = 0

for a_name, a_fn in anchors:
    for c_name, c_fn in confirms:
        for g_name, g_fn in gates:
            for exit_p in exits:
                count += 1
                entry_desc = f"{a_name}+{c_name}" if c_name else a_name

                def make_entry(a=a_fn, c=c_fn):
                    return lambda df: a(df) & c(df)

                combo = SignalCombo(
                    name=f"{entry_desc}|{g_name}|{exit_p}",
                    entry_fn=make_entry(), gate_fn=g_fn, exit_profile=exit_p,
                    entry_desc=entry_desc, gate_desc=g_name,
                )
                r = screen_combo(combo, trading_data, btc_df, 200, 3,
                                 tr_start, tr_end, detail_data)
                results.append((r, entry_desc, g_name, exit_p))
                if count % 20 == 0:
                    elapsed = time.time() - t0
                    print(f"  [{count}] elapsed {elapsed:.0f}s ...")

print(f"\nScanned {count} combos in {time.time()-t0:.0f}s\n")


# Sort: require enough trades, PF >= 1.0
def score(r):
    if len(r.trades) < 60:
        return -999
    pf = r.profit_factor
    dd_penalty = 1.0 if r.max_drawdown_pct < 25 else 0.5
    return pf * (len(r.trades) ** 0.5) * dd_penalty


results.sort(key=lambda x: score(x[0]), reverse=True)

print("=" * 130)
print("TOP 25 TREND-FOLLOWING COMBOS (score = PF × √trades, penalize DD >25%)")
print("=" * 130)
print(f"{'entry':<40} {'gate':<22} {'exit':<10} {'Trd':>5} {'WR%':>6} "
      f"{'PF':>5} {'P&L%':>7} {'DD%':>5}")
print("-" * 130)
for r, e, g, x in results[:25]:
    print(f"{e:<40} {g:<22} {x:<10} {len(r.trades):>5} "
          f"{r.win_rate:>5.1f}% {r.profit_factor:>5.2f} {r.total_pnl_pct:>+6.2f}% "
          f"{r.max_drawdown_pct:>4.1f}%")

# Also print the 10 combos with highest P&L% regardless of trade count (for context)
by_pnl = sorted(results, key=lambda x: x[0].total_pnl_pct, reverse=True)
print("\n" + "=" * 130)
print("TOP 10 BY RAW P&L%% (any trade count)")
print("=" * 130)
for r, e, g, x in by_pnl[:10]:
    print(f"{e:<40} {g:<22} {x:<10} {len(r.trades):>5} "
          f"{r.win_rate:>5.1f}% {r.profit_factor:>5.2f} {r.total_pnl_pct:>+6.2f}% "
          f"{r.max_drawdown_pct:>4.1f}%")
