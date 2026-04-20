#!/usr/bin/env python3
"""Last-chance refinements on the best trend candidate.

Try:
1. Stricter donchian (150, 200) for even rarer breakouts
2. BTC gate with RSI floor / no-crash to filter chop
3. Restrict to top-cap pairs (BTC/ETH/SOL/BNB/XRP/AVAX) — trend-followers
   are supposed to need liquidity
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from strategy_lab.engine import (
    SignalCombo, load_all_pairs, load_detail_data, screen_combo,
)
from strategy_lab.signals import (
    adx_trending, btc_above_sma, btc_no_crash, btc_rsi_floor,
    donchian_breakout, ema_crossover, volume_spike,
)
import pandas as pd

# Focused pair set — top-cap majors
TOP_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "AVAX/USDT", "NEAR/USDT", "LINK/USDT",
    "DOGE/USDT", "ADA/USDT", "LTC/USDT", "DOT/USDT",
    "TON/USDT", "SUI/USDT", "APT/USDT", "ARB/USDT",
]

print(f"Loading {len(TOP_PAIRS)} pairs...")
pair_data = load_all_pairs(TOP_PAIRS)
btc_df = pair_data["BTC/USDT"]
trading_data = {k: v for k, v in pair_data.items() if k != "BTC/USDT"}
detail_data = load_detail_data(list(trading_data.keys()) + ["BTC/USDT"])

configs = [
    ("donch(150)+adx(25)", "btc_sma50+sma200+rsi40", "roi_only",
     lambda df: donchian_breakout(df, 150) & adx_trending(df, 25),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200) & btc_rsi_floor(df, 40)),
    ("donch(100)+adx(25)+vol(1.5)", "btc_sma50+sma200+rsi40", "roi_only",
     lambda df: donchian_breakout(df, 100) & adx_trending(df, 25) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200) & btc_rsi_floor(df, 40)),
    ("donch(100)+adx(25)+vol(1.5)", "btc_sma50+sma200+nc48", "roi_only",
     lambda df: donchian_breakout(df, 100) & adx_trending(df, 25) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200) & btc_no_crash(df, 48, 5)),
    ("ema(21,55)+adx(25)+vol(1.5)", "btc_sma50+sma200+nc48", "wide",
     lambda df: ema_crossover(df, 21, 55) & adx_trending(df, 25) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200) & btc_no_crash(df, 48, 5)),
    ("ema(21,55)+adx(25)+vol(1.5)", "btc_sma50+sma200+rsi40", "wide",
     lambda df: ema_crossover(df, 21, 55) & adx_trending(df, 25) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200) & btc_rsi_floor(df, 40)),
    ("donch(55)+adx(25)+vol(1.5)", "btc_sma50+sma200+nc48", "roi_only",
     lambda df: donchian_breakout(df, 55) & adx_trending(df, 25) & volume_spike(df, 1.5),
     lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200) & btc_no_crash(df, 48, 5)),
]

windows = [
    ("2023",   "20230101", "20240101"),
    ("2024",   "20240101", "20250101"),
    ("2025",   "20250101", "20260101"),
    ("2026YTD","20260101", "20260415"),
    ("FULL",   "20230101", "20260415"),
]

for name, gate_desc, exit_p, entry_fn, gate_fn in configs:
    print(f"\n{'='*110}")
    print(f"  {name} | {gate_desc} | {exit_p}  (on {len(TOP_PAIRS)-1} majors)")
    print(f"{'='*110}")
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
