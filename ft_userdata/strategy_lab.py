#!/usr/bin/env python3
"""
Strategy Lab — Discover profitable entry signal combinations.

Phase 1: Precompute all indicators for all pairs + BTC
Phase 2: Screen ~800 signal combos via fast simulation (10-20 min)
Phase 3: Validate top N via real Freqtrade backtest across multiple windows
Phase 4: Export winners as deployable strategy .py files

Usage:
    python3 strategy_lab.py --timerange 20250901-20260331 --top 10
    python3 strategy_lab.py --screen-only --timerange 20250901-20260331
    python3 strategy_lab.py --pairs-from SupertrendStrategy --timerange 20250901-20260331
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from strategy_lab.engine import (
    ComboResult,
    generate_combos,
    get_available_pairs,
    load_all_pairs,
    load_candle_data,
    load_detail_data,
    screen_all,
)
from strategy_lab.exporter import export_strategy
from strategy_lab.signals import EXIT_PROFILES

USER_DATA = Path(__file__).parent / "user_data"
DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"

VALIDATION_WINDOWS = {
    "early":   ("20230101", "20230701", "Early (Jan-Jun 2023)"),
    "mid23":   ("20230701", "20240101", "Mid (Jul-Dec 2023)"),
    "bull24":  ("20240101", "20240701", "Bull (Jan-Jun 2024)"),
    "late24":  ("20240701", "20250101", "Late (Jul-Dec 2024)"),
    "bull25":  ("20250101", "20250701", "Bull (Jan-Jun 2025)"),
    "recent":  ("20250701", "20260415", "Recent (Jul 2025-Apr 2026)"),
}

# Top 8 pairs proven profitable in SupertrendStrategy 3.3yr optimization
TOP_8_PAIRS = [
    "SOL/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT",
    "AVAX/USDT", "NEAR/USDT", "SUI/USDT", "LINK/USDT",
]


def log(msg):
    print(f"[lab] {msg}", flush=True)


def get_pairs_from_config(strategy: str) -> list:
    """Get pairs from a bot's live config."""
    config_path = USER_DATA / "configs" / f"{strategy}.json"
    if not config_path.exists():
        config_path = USER_DATA / "configs" / f"backtest-{strategy}.json"
    if not config_path.exists():
        return []
    with open(config_path) as f:
        config = json.load(f)
    return config.get("exchange", {}).get("pair_whitelist", [])


def parse_timerange(tr: str) -> tuple:
    """Parse YYYYMMDD-YYYYMMDD to timestamps."""
    start_str, end_str = tr.split("-")
    start = datetime.strptime(start_str, "%Y%m%d").timestamp()
    end = datetime.strptime(end_str, "%Y%m%d").timestamp()
    return start, end


def validate_via_freqtrade(strategy_path: Path, config_path: str) -> dict:
    """Run a real Freqtrade backtest on an exported strategy across validation windows."""
    strategy_name = strategy_path.stem
    results = {}

    for wname, (start, end, desc) in VALIDATION_WINDOWS.items():
        timerange = f"{start}-{end}"
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{USER_DATA}:/freqtrade/user_data",
            DOCKER_IMAGE,
            "backtesting",
            "--strategy", strategy_name,
            "--timerange", timerange,
            "--timeframe", "1h",
            "--timeframe-detail", "1m",
            "--config", f"/freqtrade/user_data/configs/{config_path}",
            "--enable-protections",
            "--export", "none",
            "--no-color",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr

        metrics = {"window": wname, "desc": desc}
        for line in output.split("\n"):
            if "Profit factor" in line and "│" in line:
                try:
                    metrics["pf"] = float([p.strip() for p in line.split("│") if p.strip()][1])
                except:
                    pass
            if "Absolute drawdown" in line:
                try:
                    dd = [p.strip() for p in line.split("│") if p.strip()][1]
                    metrics["dd"] = float(dd.split("(")[1].replace("%)", ""))
                except:
                    pass
            if strategy_name in line and "│" in line and "TOTAL" not in line:
                parts = [p.strip() for p in line.split("│") if p.strip()]
                if len(parts) >= 7:
                    try:
                        metrics["trades"] = int(parts[1])
                        metrics["pnl_pct"] = float(parts[4])
                        wdl = parts[6].split()
                        metrics["wr"] = float(wdl[-1]) if wdl else 0
                    except:
                        pass

        results[wname] = metrics

    return results


def print_results(results: list, top_n: int):
    """Print screening results table."""
    print(f"\n{'='*100}")
    print(f" TOP {top_n} SIGNAL COMBINATIONS")
    print(f"{'='*100}")
    print(f"{'#':>3} {'Score':>7} {'PF':>6} {'WR%':>6} {'P&L%':>8} {'DD%':>6} {'Trades':>7}  Combo")
    print("-" * 100)

    for i, r in enumerate(results[:top_n], 1):
        print(
            f"{i:3d} {r.score:>+7.2f} {r.profit_factor:>6.2f} {r.win_rate:>5.1f}% "
            f"{r.total_pnl_pct:>+7.2f}% {r.max_drawdown_pct:>5.1f}% {len(r.trades):>6d}  "
            f"{r.combo.label}"
        )


def main():
    parser = argparse.ArgumentParser(description="Strategy Lab — Signal combo discovery")
    parser.add_argument("--timerange", default="20230101-20260415", help="Screening timerange")
    parser.add_argument("--top", type=int, default=10, help="Top N combos to report/validate")
    parser.add_argument("--screen-only", action="store_true", help="Skip Freqtrade validation")
    parser.add_argument("--pairs-from", default=None, help="Load pairs from a strategy config")
    parser.add_argument("--top-pairs", action="store_true", help="Use top 8 proven profitable pairs")
    parser.add_argument("--wallet", type=float, default=88, help="Wallet size for simulation")
    parser.add_argument("--max-open", type=int, default=3, help="Max concurrent trades")
    parser.add_argument("--no-detail", action="store_true", help="Skip 1m detail (use 1h only)")
    parser.add_argument("--min-trades", type=int, default=200, help="Minimum trades filter")
    parser.add_argument("--min-wr", type=float, default=55, help="Minimum win rate %% filter")
    parser.add_argument("--min-pf", type=float, default=1.2, help="Minimum profit factor filter")
    parser.add_argument("--validate-config", default="backtest-SupertrendStrategy.json",
                        help="Config file for Freqtrade validation")
    args = parser.parse_args()

    start_time = time.time()
    tr_start, tr_end = parse_timerange(args.timerange)

    # ── Phase 1: Load Data ──────────────────────────────────
    log("Phase 1: Loading candle data...")

    require_detail = not args.no_detail
    if args.top_pairs:
        pairs = TOP_8_PAIRS[:]
        log(f"Using top 8 pairs (NOTE: survivorship bias — curated from Supertrend)")
    elif args.pairs_from:
        pairs = get_pairs_from_config(args.pairs_from)
        if not pairs:
            pairs = get_pairs_from_config(f"backtest-{args.pairs_from}")
        if not pairs:
            pairs = get_available_pairs(require_detail=require_detail)
            log(f"Config had no static pairs, using all {len(pairs)} available")
        else:
            log(f"Using {len(pairs)} pairs from {args.pairs_from}")
    else:
        pairs = get_available_pairs(require_detail=require_detail)
        log(f"Found {len(pairs)} pairs with {'1h+1m' if require_detail else '1h'} data")

    if "BTC/USDT" not in pairs:
        pairs.append("BTC/USDT")

    pair_data = load_all_pairs(pairs)
    btc_df = pair_data.get("BTC/USDT")
    if btc_df is None or btc_df.empty:
        print("ERROR: No BTC/USDT data available")
        sys.exit(1)

    # Remove BTC from trading pairs
    trading_data = {k: v for k, v in pair_data.items() if k != "BTC/USDT"}
    log(f"Loaded 1h data for {len(trading_data)} trading pairs + BTC")

    # Load 1m detail data for accurate trade simulation
    detail_data = None
    if not args.no_detail:
        log("Loading 1m detail data for trade simulation...")
        detail_data = load_detail_data(list(trading_data.keys()) + ["BTC/USDT"])
        log(f"Loaded 1m detail for {len(detail_data)} pairs")

    # ── Phase 2: Screen Combos ──────────────────────────────
    log("Phase 2: Generating signal combinations...")
    combos = generate_combos()
    log(f"Generated {len(combos)} combos")

    detail_mode = "1m detail" if detail_data else "1h only"
    log(f"Screening across {args.timerange} ({detail_mode}, wallet=${args.wallet}, max_open={args.max_open})...")
    results = screen_all(
        combos, trading_data, btc_df,
        wallet=args.wallet,
        max_open=args.max_open,
        timerange_start=tr_start,
        timerange_end=tr_end,
        detail_data=detail_data,
    )

    screen_time = time.time() - start_time
    log(f"Screening complete in {screen_time:.0f}s")

    # Filter out combos with 0 trades
    results = [r for r in results if len(r.trades) > 0]
    profitable = [r for r in results if r.profit_factor > 1.0]
    log(f"Results: {len(results)} combos with trades, {len(profitable)} profitable (PF > 1.0)")

    # Apply quality filters
    quality = [r for r in results
               if len(r.trades) >= args.min_trades
               and r.win_rate >= args.min_wr
               and r.profit_factor >= args.min_pf]
    log(f"Quality filter (trades>={args.min_trades}, WR>={args.min_wr}%, PF>={args.min_pf}): {len(quality)} pass")

    print_results(results, args.top)

    if quality:
        print(f"\n{'='*100}")
        print(f" QUALITY FILTER PASSES (trades>={args.min_trades}, WR>={args.min_wr}%, PF>={args.min_pf})")
        print(f"{'='*100}")
        print_results(quality, len(quality))

    if args.screen_only:
        elapsed = time.time() - start_time
        log(f"Total time: {elapsed:.0f}s")
        return

    # ── Phase 3: Validate Winners ───────────────────────────
    if not quality and not profitable:
        log("No combos pass quality filter. Skipping validation.")
        return

    # Validate quality combos first, fall back to top scorers
    validate_list = quality if quality else results
    top_n = min(args.top, len(validate_list))
    log(f"\nPhase 3: Validating top {top_n} via Freqtrade backtest (with 1m detail)...")

    strategies_dir = USER_DATA / "strategies"
    validated = []

    for rank, r in enumerate(validate_list[:top_n], 1):
        log(f"  [{rank}/{top_n}] Exporting: {r.combo.label}")
        strat_path = export_strategy(r.combo, rank, strategies_dir)
        log(f"    Exported: {strat_path.name}")

        log(f"    Validating across {len(VALIDATION_WINDOWS)} windows...")
        val_results = validate_via_freqtrade(strat_path, args.validate_config)

        profitable_windows = 0
        for wname, m in val_results.items():
            pf = m.get("pf", 0)
            pnl = m.get("pnl_pct", 0)
            dd = m.get("dd", 0)
            trades = m.get("trades", 0)
            ok = "OK" if pf >= 1.0 else "FAIL"
            print(f"      {m.get('desc', wname):30s}: PF:{pf:5.2f}  P&L:{pnl:+7.2f}%  DD:{dd:5.1f}%  trades:{trades}  [{ok}]")
            if pf >= 1.0:
                profitable_windows += 1

        robust = profitable_windows >= 4
        status = f"ROBUST ({profitable_windows}/{len(VALIDATION_WINDOWS)})" if robust else f"FRAGILE ({profitable_windows}/{len(VALIDATION_WINDOWS)})"
        log(f"    {status}")

        validated.append({
            "rank": rank,
            "combo": r.combo.label,
            "screen_score": r.score,
            "screen_pf": r.profit_factor,
            "screen_pnl_pct": r.total_pnl_pct,
            "validation": val_results,
            "profitable_windows": profitable_windows,
            "robust": robust,
            "strategy_file": strat_path.name,
        })

    # ── Phase 4: Final Report ───────────────────────────────
    print(f"\n{'='*100}")
    print(f" FINAL VALIDATED RESULTS")
    print(f"{'='*100}")

    robust_combos = [v for v in validated if v["robust"]]
    fragile_combos = [v for v in validated if not v["robust"]]

    if robust_combos:
        print(f"\n ROBUST (profitable in 4+ of {len(VALIDATION_WINDOWS)} windows):")
        for v in robust_combos:
            print(f"  #{v['rank']} {v['combo']}")
            print(f"     Screen: PF:{v['screen_pf']:.2f} P&L:{v['screen_pnl_pct']:+.2f}%")
            for wname, m in v["validation"].items():
                print(f"     {m.get('desc', wname):30s}: PF:{m.get('pf',0):5.2f} P&L:{m.get('pnl_pct',0):+.2f}%")
            print(f"     Strategy: {v['strategy_file']}")
    else:
        print(f"\n No robust combos found (none profitable in 4+ of {len(VALIDATION_WINDOWS)} windows)")

    if fragile_combos:
        print(f"\n FRAGILE (profitable in 0-1 windows):")
        for v in fragile_combos:
            print(f"  #{v['rank']} {v['combo']} — {v['profitable_windows']}/{len(VALIDATION_WINDOWS)} windows")

    # Save results
    results_path = Path(__file__).parent / f"lab_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(results_path, "w") as f:
        json.dump(validated, f, indent=2)
    log(f"Results saved: {results_path}")

    elapsed = time.time() - start_time
    log(f"Total time: {elapsed/60:.1f} minutes")


if __name__ == "__main__":
    main()
