#!/usr/bin/env python3
"""
Deep analysis of a single signal combo.

Breakdown:
  1. Per-pair performance
  2. Per-year performance (regime consistency)
  3. Drawdown analysis (max DD, duration, recovery)
  4. Trade sequence stats (consecutive wins/losses)
  5. Parameter sensitivity (±1 step on each numeric param)
  6. Monte Carlo ruin probability (1000 shuffles)
  7. Walk-forward across 6 rolling windows

Usage:
    python3 analyze_combo.py \\
        --entry "kelt(20,2.5)+vol(2.0)" \\
        --gate "btc_sma50" \\
        --exit wide
"""

import argparse
import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from strategy_lab.engine import (
    SignalCombo,
    generate_combos,
    get_available_pairs,
    load_all_pairs,
    load_detail_data,
    screen_combo,
)
from strategy_lab.signals import (
    EXIT_PROFILES,
    adx_trending,
    bollinger_bounce,
    btc_above_sma,
    btc_no_crash,
    btc_rsi_floor,
    bullish_engulfing,
    donchian_breakout,
    ema_crossover,
    ichimoku_bullish,
    keltner_bounce,
    macd_crossover,
    rsi_range,
    stoch_oversold,
    supertrend,
    supertrend_all,
    volume_spike,
    vwap_reclaim,
)


def log(msg):
    print(f"[analyze] {msg}", flush=True)


def find_combo(entry: str, gate: str, exit_profile: str) -> SignalCombo:
    """Look up a combo by description strings, or build on-the-fly if not found."""
    all_combos = generate_combos()
    for combo in all_combos:
        if combo.entry_desc == entry and combo.gate_desc == gate and combo.exit_profile == exit_profile:
            return combo
    # Not in pre-generated set — build on-the-fly
    entry_fn = build_entry_fn(entry)
    gate_fn = build_gate_fn(gate)
    if entry_fn is None:
        raise ValueError(f"Could not parse entry: {entry}")
    return SignalCombo(
        name=f"{entry}|{gate}|{exit_profile}",
        entry_fn=entry_fn,
        gate_fn=gate_fn,
        exit_profile=exit_profile,
        entry_desc=entry,
        gate_desc=gate,
    )


def describe_combo_options():
    """Print available entry/gate/exit options."""
    combos = generate_combos()
    entries = sorted(set(c.entry_desc for c in combos))
    gates = sorted(set(c.gate_desc for c in combos))
    exits = sorted(set(c.exit_profile for c in combos))
    print("Available entries:")
    for e in entries:
        print(f"  {e}")
    print("Available gates:")
    for g in gates:
        print(f"  {g}")
    print("Available exits:")
    for x in exits:
        print(f"  {x}")


# ── Per-pair breakdown ─────────────────────────────────────
def per_pair_breakdown(trades, wallet):
    pair_trades = defaultdict(list)
    for t in trades:
        pair_trades[t.pair].append(t)

    rows = []
    for pair, ts in sorted(pair_trades.items()):
        n = len(ts)
        wins = sum(1 for t in ts if t.profit_abs >= 0)
        total_pnl = sum(t.profit_abs for t in ts)
        gross_win = sum(t.profit_abs for t in ts if t.profit_abs >= 0)
        gross_loss = abs(sum(t.profit_abs for t in ts if t.profit_abs < 0))
        pf = gross_win / gross_loss if gross_loss > 0 else 999
        wr = wins / n * 100 if n > 0 else 0
        avg_pnl = total_pnl / n if n > 0 else 0
        rows.append({
            "pair": pair, "trades": n, "wins": wins, "wr": wr,
            "pnl_usd": total_pnl, "pnl_pct": total_pnl / wallet * 100,
            "pf": pf, "avg_usd": avg_pnl,
        })

    rows.sort(key=lambda r: r["pnl_usd"], reverse=True)
    print(f"\n{'Pair':<12} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L $':>9} {'P&L%':>7} {'Avg $':>7}")
    print("-" * 70)
    for r in rows:
        print(f"{r['pair']:<12} {r['trades']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} "
              f"${r['pnl_usd']:>+7.2f} {r['pnl_pct']:>+6.2f}% ${r['avg_usd']:>+6.2f}")

    # Concentration check: what % of profit comes from top-2 pairs?
    if rows:
        profits = [r["pnl_usd"] for r in rows if r["pnl_usd"] > 0]
        top2 = sum(profits[:2])
        total = sum(profits)
        concentration = top2 / total * 100 if total > 0 else 0
        print(f"\nTop-2 pair concentration: {concentration:.1f}% of gross profits")


# ── Per-year breakdown ─────────────────────────────────────
def per_year_breakdown(trades, wallet, pair_data, detail_data):
    """Bucket trades by year using open timestamp (from detail data if available)."""
    pair_ts_1h = {p: df["ts"].values for p, df in pair_data.items()}
    year_trades = defaultdict(list)
    for t in trades:
        open_ts = None
        # 1m-simulated trades have open_idx in the detail array
        if detail_data and t.pair in detail_data:
            det = detail_data[t.pair]
            if 0 <= t.open_idx < len(det.ts):
                open_ts = det.ts[t.open_idx]
        # Fall back to 1h array
        if open_ts is None and t.pair in pair_ts_1h:
            ts_arr = pair_ts_1h[t.pair]
            if t.open_idx < len(ts_arr):
                open_ts = ts_arr[t.open_idx]
        if open_ts is None:
            continue
        year = datetime.fromtimestamp(open_ts).year
        year_trades[year].append(t)

    print(f"\n{'Year':>5} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L $':>9} {'P&L%':>7}")
    print("-" * 55)
    for year in sorted(year_trades.keys()):
        ts = year_trades[year]
        n = len(ts)
        wins = sum(1 for t in ts if t.profit_abs >= 0)
        total_pnl = sum(t.profit_abs for t in ts)
        gross_win = sum(t.profit_abs for t in ts if t.profit_abs >= 0)
        gross_loss = abs(sum(t.profit_abs for t in ts if t.profit_abs < 0))
        pf = gross_win / gross_loss if gross_loss > 0 else 999
        wr = wins / n * 100 if n > 0 else 0
        print(f"{year:>5} {n:>7} {wr:>5.1f}% {pf:>6.2f} "
              f"${total_pnl:>+7.2f} {total_pnl/wallet*100:>+6.2f}%")


# ── Drawdown analysis ──────────────────────────────────────
def drawdown_analysis(trades, wallet):
    if not trades:
        return
    # Sort by open timestamp is proxy-sorted via open_idx already
    equity = 0
    peak = 0
    max_dd = 0
    dd_start_trade = 0
    current_dd_start = 0
    longest_dd = 0
    current_dd_length = 0

    for i, t in enumerate(trades):
        equity += t.profit_abs
        if equity > peak:
            peak = equity
            current_dd_length = 0
            current_dd_start = i + 1
        else:
            current_dd_length += 1
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
                dd_start_trade = current_dd_start
            if current_dd_length > longest_dd:
                longest_dd = current_dd_length

    # Longest consecutive losers
    max_consec_loss = 0
    cur_loss = 0
    max_consec_win = 0
    cur_win = 0
    for t in trades:
        if t.profit_abs < 0:
            cur_loss += 1
            cur_win = 0
            max_consec_loss = max(max_consec_loss, cur_loss)
        else:
            cur_win += 1
            cur_loss = 0
            max_consec_win = max(max_consec_win, cur_win)

    print(f"\nMax drawdown:            ${max_dd:>7.2f} ({max_dd/wallet*100:.1f}% of wallet)")
    print(f"Longest DD (trades):     {longest_dd}")
    print(f"Max consecutive losses:  {max_consec_loss}")
    print(f"Max consecutive wins:    {max_consec_win}")


# ── Monte Carlo ruin simulation ────────────────────────────
def monte_carlo_ruin(trades, wallet, n_sims=1000, ruin_threshold=0.5):
    """Shuffle trade order n_sims times. Compute % of sims that hit ruin."""
    if not trades:
        return None
    pct_returns = [t.profit_abs / (wallet / 3) for t in trades]  # per-stake % return

    ruined = 0
    final_pnls = []
    max_dds = []
    random.seed(42)

    for _ in range(n_sims):
        shuffled = pct_returns[:]
        random.shuffle(shuffled)
        equity = wallet
        peak = wallet
        max_dd_pct = 0
        for r in shuffled:
            # Apply as pct of current position, not fixed stake (compounding)
            equity += (wallet / 3) * r  # Flat stake per trade — matches our model
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd_pct:
                max_dd_pct = dd
            if equity < wallet * (1 - ruin_threshold):
                ruined += 1
                break
        final_pnls.append(equity - wallet)
        max_dds.append(max_dd_pct)

    print(f"\nMonte Carlo ({n_sims} trade-order shuffles):")
    print(f"  Ruin probability (>{ruin_threshold*100:.0f}% loss): {ruined/n_sims*100:.2f}%")
    print(f"  Median final P&L:        ${np.median(final_pnls):>+7.2f}")
    print(f"  5th percentile P&L:      ${np.percentile(final_pnls, 5):>+7.2f}")
    print(f"  95th percentile P&L:     ${np.percentile(final_pnls, 95):>+7.2f}")
    print(f"  Median max DD:           {np.median(max_dds)*100:.1f}%")
    print(f"  95th pctile max DD:      {np.percentile(max_dds, 95)*100:.1f}%")
    return ruined / n_sims


# ── Walk-forward across rolling windows ────────────────────
def walk_forward(combo, pair_data, btc_df, detail_data, wallet, max_open,
                 start_ts, end_ts, n_windows=6):
    """Split 3.3yr into n_windows equal windows. Run each separately."""
    total_span = end_ts - start_ts
    window_size = total_span / n_windows

    print(f"\n{'Window':>7} {'Range':>35} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L%':>7} {'Status':>8}")
    print("-" * 85)

    oos_profitable = 0
    for w in range(n_windows):
        w_start = start_ts + w * window_size
        w_end = w_start + window_size
        result = screen_combo(
            combo, pair_data, btc_df, wallet, max_open,
            timerange_start=w_start, timerange_end=w_end,
            detail_data=detail_data,
        )
        start_str = datetime.fromtimestamp(w_start).strftime("%Y-%m-%d")
        end_str = datetime.fromtimestamp(w_end).strftime("%Y-%m-%d")
        status = "PROFIT" if result.profit_factor > 1.0 else "LOSS"
        if result.profit_factor > 1.0:
            oos_profitable += 1
        print(f"{w+1:>7} {start_str}→{end_str:<15} {len(result.trades):>7} "
              f"{result.win_rate:>5.1f}% {result.profit_factor:>6.2f} "
              f"{result.total_pnl_pct:>+6.2f}% {status:>8}")

    print(f"\n{oos_profitable}/{n_windows} windows profitable")
    if oos_profitable >= int(n_windows * 2 / 3):
        print(f"  → ROBUST (≥ {int(n_windows*2/3)}/6)")
    else:
        print(f"  → FRAGILE — edge not consistent across time")
    return oos_profitable


# ── Parameter sensitivity ──────────────────────────────────
def build_entry_fn(desc: str):
    """Build an entry function from a description string by parsing components."""
    import re
    parts = desc.split("+")
    funcs = []
    for p in parts:
        p = p.strip()
        m = re.match(r'kelt\((\d+),([\d.]+)\)', p)
        if m:
            period, mult = int(m.group(1)), float(m.group(2))
            funcs.append(lambda df, pe=period, mu=mult: keltner_bounce(df, pe, mu))
            continue
        m = re.match(r'bb\((\d+),([\d.]+)\)', p)
        if m:
            period, std = int(m.group(1)), float(m.group(2))
            funcs.append(lambda df, pe=period, s=std: bollinger_bounce(df, pe, s))
            continue
        m = re.match(r'vol\(([\d.]+)\)', p)
        if m:
            mult = float(m.group(1))
            funcs.append(lambda df, mu=mult: volume_spike(df, mu))
            continue
        m = re.match(r'rsi\((\d+),(\d+)\)', p)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            funcs.append(lambda df, l=lo, h=hi: rsi_range(df, l, h))
            continue
        m = re.match(r'adx\((\d+)\)', p)
        if m:
            thr = int(m.group(1))
            funcs.append(lambda df, t=thr: adx_trending(df, t))
            continue
        m = re.match(r'donch\((\d+)\)', p)
        if m:
            pe = int(m.group(1))
            funcs.append(lambda df, p=pe: donchian_breakout(df, p))
            continue
        m = re.match(r'vwap\((\d+)\)', p)
        if m:
            pe = int(m.group(1))
            funcs.append(lambda df, p=pe: vwap_reclaim(df, p))
            continue
        m = re.match(r'st\((\d+),(\d+)\)', p)
        if m:
            mult, per = int(m.group(1)), int(m.group(2))
            funcs.append(lambda df, m=mult, p=per: supertrend(df, m, p))
            continue
    if not funcs:
        return None
    def combined(df):
        result = funcs[0](df)
        for f in funcs[1:]:
            result = result & f(df)
        return result
    return combined


def build_gate_fn(desc: str):
    """Build a gate function from description."""
    parts = desc.split("+")
    funcs = []
    for p in parts:
        p = p.strip()
        if p == "btc_sma50":
            funcs.append(lambda df: btc_above_sma(df, 50))
        elif p == "btc_sma200":
            funcs.append(lambda df: btc_above_sma(df, 200))
        elif p == "sma200":
            funcs.append(lambda df: btc_above_sma(df, 200))
        elif p == "nc24":
            funcs.append(lambda df: btc_no_crash(df, 24, 3))
        elif p == "rsi35":
            funcs.append(lambda df: btc_rsi_floor(df, 35))
    if not funcs:
        return lambda df: pd.Series(True, index=df.index)
    def combined(df):
        result = funcs[0](df)
        for f in funcs[1:]:
            result = result & f(df)
        return result
    return combined


def parameter_sensitivity(entry_desc, gate_desc, exit_profile,
                          pair_data, btc_df, detail_data, wallet, max_open):
    """Vary each numeric parameter and build combos on-the-fly."""
    import re

    variants = []

    # Keltner: kelt(period, atr_mult) — period ±5, mult ±0.5
    m = re.search(r'kelt\((\d+),([\d.]+)\)', entry_desc)
    if m:
        p, mult = int(m.group(1)), float(m.group(2))
        for dp, dm in [(-5, 0), (5, 0), (0, -0.5), (0, 0.5), (-5, -0.5), (5, 0.5), (0, 0)]:
            new_entry = re.sub(r'kelt\(\d+,[\d.]+\)',
                               f'kelt({p+dp},{mult+dm:.1f})', entry_desc)
            variants.append(new_entry)

    # BB: bb(period, std)
    m = re.search(r'bb\((\d+),(\d+)\)', entry_desc)
    if m:
        p, s = int(m.group(1)), int(m.group(2))
        for dp, ds in [(-5, 0), (5, 0), (0, -1), (0, 1), (0, 0)]:
            new_entry = re.sub(r'bb\(\d+,\d+\)', f'bb({p+dp},{s+ds})', entry_desc)
            variants.append(new_entry)

    # Volume: vol(multiplier)
    m = re.search(r'vol\(([\d.]+)\)', entry_desc)
    if m:
        vm = float(m.group(1))
        for dv in [-0.5, -0.25, 0, 0.25, 0.5]:
            new_entry = re.sub(r'vol\([\d.]+\)', f'vol({vm+dv:.2f})', entry_desc)
            variants.append(new_entry)

    # Dedup variants
    variants = sorted(set(variants))

    if not variants:
        print("\nNo numeric params to vary.")
        return

    print(f"\n{'Variant':<38} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L%':>7}")
    print("-" * 75)

    gate_fn = build_gate_fn(gate_desc)
    for v_entry in variants:
        entry_fn = build_entry_fn(v_entry)
        if entry_fn is None:
            print(f"{v_entry:<38} [build failed]")
            continue
        combo = SignalCombo(
            name=f"{v_entry}|{gate_desc}|{exit_profile}",
            entry_fn=entry_fn,
            gate_fn=gate_fn,
            exit_profile=exit_profile,
            entry_desc=v_entry,
            gate_desc=gate_desc,
        )
        result = screen_combo(combo, pair_data, btc_df, wallet, max_open,
                              timerange_start=0, timerange_end=float("inf"),
                              detail_data=detail_data)
        marker = " ← BASE" if v_entry == entry_desc else ""
        print(f"{v_entry:<38} {len(result.trades):>7} "
              f"{result.win_rate:>5.1f}% {result.profit_factor:>6.2f} "
              f"{result.total_pnl_pct:>+6.2f}%{marker}")


def main():
    parser = argparse.ArgumentParser(description="Deep analysis of signal combo")
    parser.add_argument("--entry", required=False, help="Entry desc, e.g. 'kelt(20,2.5)+vol(2.0)'")
    parser.add_argument("--gate", required=False, help="Gate desc, e.g. 'btc_sma50'")
    parser.add_argument("--exit", required=False, dest="exit_profile",
                        help="Exit profile: tight/balanced/wide/roi_only")
    parser.add_argument("--list-options", action="store_true", help="List available entry/gate/exit strings")
    parser.add_argument("--wallet", type=float, default=88)
    parser.add_argument("--max-open", type=int, default=3)
    parser.add_argument("--timerange", default="20230101-20260415")
    parser.add_argument("--no-detail", action="store_true")
    parser.add_argument("--skip-mc", action="store_true", help="Skip Monte Carlo")
    parser.add_argument("--skip-wf", action="store_true", help="Skip walk-forward")
    parser.add_argument("--skip-sens", action="store_true", help="Skip parameter sensitivity")
    args = parser.parse_args()

    if args.list_options:
        describe_combo_options()
        return

    if not args.entry or not args.gate or not args.exit_profile:
        print("ERROR: --entry, --gate, --exit all required. Use --list-options to see choices.")
        sys.exit(1)

    tr_start = datetime.strptime(args.timerange.split("-")[0], "%Y%m%d").timestamp()
    tr_end = datetime.strptime(args.timerange.split("-")[1], "%Y%m%d").timestamp()

    log("Loading data...")
    require_detail = not args.no_detail
    pairs = get_available_pairs(require_detail=require_detail)
    if "BTC/USDT" not in pairs:
        pairs.append("BTC/USDT")
    pair_data = load_all_pairs(pairs)
    btc_df = pair_data["BTC/USDT"]
    trading_data = {k: v for k, v in pair_data.items() if k != "BTC/USDT"}

    detail_data = None
    if require_detail:
        log("Loading 1m detail...")
        detail_data = load_detail_data(list(trading_data.keys()) + ["BTC/USDT"])

    log(f"Finding combo: {args.entry} | {args.gate} | {args.exit_profile}")
    combo = find_combo(args.entry, args.gate, args.exit_profile)

    print(f"\n{'='*80}")
    print(f"DEEP ANALYSIS: {combo.label}")
    print(f"Timerange: {args.timerange} | Wallet: ${args.wallet} | Max open: {args.max_open}")
    print(f"{'='*80}")

    log("Running primary screen...")
    t0 = time.time()
    result = screen_combo(combo, trading_data, btc_df, args.wallet, args.max_open,
                          timerange_start=tr_start, timerange_end=tr_end,
                          detail_data=detail_data)
    log(f"Primary screen done in {time.time()-t0:.0f}s")

    print(f"\n── Summary ──")
    print(f"Total trades:        {len(result.trades)}")
    print(f"Win rate:            {result.win_rate:.1f}%")
    print(f"Profit factor:       {result.profit_factor:.2f}")
    print(f"Total P&L:           ${result.total_pnl:+.2f} ({result.total_pnl_pct:+.2f}% of wallet)")
    print(f"Max drawdown:        {result.max_drawdown_pct:.1f}%")

    print(f"\n── Per-pair breakdown ──")
    per_pair_breakdown(result.trades, args.wallet)

    print(f"\n── Per-year breakdown ──")
    per_year_breakdown(result.trades, args.wallet, trading_data, detail_data)

    print(f"\n── Drawdown analysis ──")
    drawdown_analysis(result.trades, args.wallet)

    if not args.skip_mc:
        print(f"\n── Monte Carlo ──")
        monte_carlo_ruin(result.trades, args.wallet)

    if not args.skip_wf:
        print(f"\n── Walk-forward (6 windows) ──")
        walk_forward(combo, trading_data, btc_df, detail_data,
                     args.wallet, args.max_open, tr_start, tr_end)

    if not args.skip_sens:
        print(f"\n── Parameter sensitivity ──")
        parameter_sensitivity(args.entry, args.gate, args.exit_profile,
                              trading_data, btc_df, detail_data,
                              args.wallet, args.max_open)

    print(f"\n{'='*80}")
    print(f"TOTAL ANALYSIS TIME: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
