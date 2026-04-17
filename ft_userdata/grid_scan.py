#!/usr/bin/env python3
"""Quick grid scan of kelt × vol × exit combinations on 3.3yr data."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from strategy_lab.engine import (
    SignalCombo, get_available_pairs, load_all_pairs, load_detail_data, screen_combo,
)
from strategy_lab.signals import EXIT_PROFILES, btc_above_sma, keltner_bounce, volume_spike

pairs = get_available_pairs(require_detail=True)
if "BTC/USDT" not in pairs:
    pairs.append("BTC/USDT")

print("Loading...")
pair_data = load_all_pairs(pairs)
btc_df = pair_data["BTC/USDT"]
trading_data = {k: v for k, v in pair_data.items() if k != "BTC/USDT"}
detail_data = load_detail_data(list(trading_data.keys()) + ["BTC/USDT"])

tr_start = datetime.strptime("20230101", "%Y%m%d").timestamp()
tr_end = datetime.strptime("20260415", "%Y%m%d").timestamp()

# Grid
kelt_params = [(15, 2.0), (15, 2.5), (20, 2.0), (20, 2.5), (20, 3.0), (25, 2.5), (25, 3.0)]
vol_params = [1.25, 1.5, 1.75, 2.0, 2.25]
exits = ["tight", "balanced", "wide", "roi_only"]
gates = ["btc_sma50", "btc_sma50+sma200"]

print(f"\n{'entry':<38} {'gate':<20} {'exit':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L%':>7}")
print("-" * 110)

t0 = time.time()
results = []
count = 0
total = len(kelt_params) * len(vol_params) * len(exits) * len(gates)

for (kp, km) in kelt_params:
    for vm in vol_params:
        entry_desc = f"kelt({kp},{km})+vol({vm})"
        entry_fn = (lambda df, p=kp, m=km, v=vm:
                    keltner_bounce(df, p, m) & volume_spike(df, v))
        for gate in gates:
            if gate == "btc_sma50":
                gate_fn = lambda df: btc_above_sma(df, 50)
            else:
                gate_fn = lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200)

            for exit_p in exits:
                count += 1
                combo = SignalCombo(
                    name=f"{entry_desc}|{gate}|{exit_p}",
                    entry_fn=entry_fn, gate_fn=gate_fn, exit_profile=exit_p,
                    entry_desc=entry_desc, gate_desc=gate,
                )
                r = screen_combo(combo, trading_data, btc_df, 88, 3,
                                 tr_start, tr_end, detail_data)
                results.append((r, entry_desc, gate, exit_p))

print(f"Scanned {count} combos in {time.time()-t0:.0f}s\n")

# Sort by score = PF * sqrt(trades) if trades >= 50 else -inf
def score(r):
    if len(r.trades) < 50:
        return -999
    return r.profit_factor * (len(r.trades) ** 0.5) * (1 if r.max_drawdown_pct < 25 else 0.5)

results.sort(key=lambda x: score(x[0]), reverse=True)

print("TOP 15 BY SCORE (PF × √trades, penalize DD >25%):")
print(f"{'entry':<38} {'gate':<20} {'exit':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L%':>7} {'DD%':>5}")
print("-" * 115)
for r, e, g, x in results[:15]:
    print(f"{e:<38} {g:<20} {x:<10} {len(r.trades):>7} "
          f"{r.win_rate:>5.1f}% {r.profit_factor:>6.2f} {r.total_pnl_pct:>+6.2f}% "
          f"{r.max_drawdown_pct:>4.1f}%")
