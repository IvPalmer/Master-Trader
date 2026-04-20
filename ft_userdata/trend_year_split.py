#!/usr/bin/env python3
"""Year-by-year honesty check on the top trend candidates from grid_scan_trend.

If any year loses hard, strategy fails the year-consistency gate."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from strategy_lab.engine import (
    SignalCombo, get_available_pairs, load_all_pairs, load_detail_data, screen_combo,
)
from strategy_lab.signals import (
    adx_trending, btc_above_sma, donchian_breakout, ema_crossover, volume_spike,
)

pairs = get_available_pairs(require_detail=True)
if "BTC/USDT" not in pairs:
    pairs.append("BTC/USDT")
pair_data = load_all_pairs(pairs)
btc_df = pair_data["BTC/USDT"]
trading_data = {k: v for k, v in pair_data.items() if k != "BTC/USDT"}
detail_data = load_detail_data(list(trading_data.keys()) + ["BTC/USDT"])

candidates = [
    ("donch(100)+adx(20)", "btc_sma200", "roi_only",
     lambda df: donchian_breakout(df, 100) & adx_trending(df, 20),
     lambda df: btc_above_sma(df, 200)),
    ("ema(12,26)+vol(2.0)", "btc_sma50+sma200", "roi_only",
     lambda df: ema_crossover(df, 12, 26) & volume_spike(df, 2.0),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200)),
    ("ema(21,55)+adx(25)+vol(1.5)", "btc_sma200", "wide",
     lambda df: ema_crossover(df, 21, 55) & adx_trending(df, 25) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 200)),
    ("ema(21,55)+adx(20)+vol(1.5)", "btc_sma50+sma200", "balanced",
     lambda df: ema_crossover(df, 21, 55) & adx_trending(df, 20) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200)),
]

windows = [
    ("2023",   "20230101", "20240101"),
    ("2024",   "20240101", "20250101"),
    ("2025",   "20250101", "20260101"),
    ("2026YTD","20260101", "20260415"),
    ("FULL",   "20230101", "20260415"),
]

for name, gate_desc, exit_p, entry_fn, gate_fn in candidates:
    print(f"\n{'='*100}")
    print(f"  {name} | {gate_desc} | {exit_p}")
    print(f"{'='*100}")
    print(f"  {'window':<10} {'Trd':>5} {'WR%':>6} {'PF':>5} {'P&L%':>8} {'DD%':>5}")
    for wname, s, e in windows:
        ts_start = datetime.strptime(s, "%Y%m%d").timestamp()
        ts_end = datetime.strptime(e, "%Y%m%d").timestamp()
        combo = SignalCombo(
            name=f"{name}|{gate_desc}|{exit_p}",
            entry_fn=entry_fn, gate_fn=gate_fn, exit_profile=exit_p,
            entry_desc=name, gate_desc=gate_desc,
        )
        r = screen_combo(combo, trading_data, btc_df, 200, 3,
                         ts_start, ts_end, detail_data)
        print(f"  {wname:<10} {len(r.trades):>5} {r.win_rate:>5.1f}% "
              f"{r.profit_factor:>5.2f} {r.total_pnl_pct:>+7.2f}% "
              f"{r.max_drawdown_pct:>4.1f}%")
