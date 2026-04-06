#!/usr/bin/env python3
"""
optimize_params.py — Grid search for optimal strategy parameters across multiple time windows.

Modifies strategy params in-place, runs backtest, collects results, restores original.
Tests each parameter combination across multiple market regimes.

Usage:
    python3 optimize_params.py <StrategyName> [--config backtest-config.json]
"""

import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
USER_DATA = BASE_DIR / "user_data"
CONFIGS_DIR = USER_DATA / "configs"
DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"

# ── Time Windows ────────────────────────────────────────────
WINDOWS = {
    "full_12m":    ("20250601", "20260331", "Full 12 months (all regimes)"),
    "bull_2025":   ("20250601", "20251101", "Bull market (Jun-Oct 2025)"),
    "bear_2025":   ("20251101", "20260301", "Bear market (Nov 2025-Feb 2026)"),
    "recent_3m":   ("20260101", "20260331", "Recent 3 months"),
    "recovery":    ("20260201", "20260331", "Recovery period (Feb-Mar 2026)"),
}

# ── Parameter Grids ─────────────────────────────────────────
PARAM_GRIDS = {
    "SupertrendStrategy": {
        "stoploss": [-0.02, -0.03, -0.04, -0.05, -0.07],
        "trailing_stop_positive": [0.015, 0.02, 0.03],
        "trailing_stop_positive_offset": [0.02, 0.03, 0.04, 0.05],
        "exit_profit_only": [True],
        "exit_profit_offset": [0.005, 0.01],
        "roi_profile": [
            ("tight",   {"0": 0.03, "360": 0.02, "720": 0.015, "1440": 0.008}),
            ("current", {"0": 0.05, "360": 0.03, "720": 0.02, "1440": 0.01}),
            ("wide",    {"0": 0.08, "360": 0.05, "720": 0.03, "1440": 0.015}),
            ("wider",   {"0": 0.10, "360": 0.07, "720": 0.04, "1440": 0.02}),
        ],
    },
    "MasterTraderV1": {
        "stoploss": [-0.02, -0.03, -0.04, -0.05, -0.07],
        "trailing_stop_positive": [0.01, 0.015, 0.02],
        "trailing_stop_positive_offset": [0.015, 0.02, 0.03, 0.04],
        "exit_profit_only": [True],  # Backtest proved False is disastrous
        "exit_profit_offset": [0.005, 0.01],
        "roi_profile": [
            ("tight",   {"0": 0.05, "360": 0.03, "720": 0.02, "1440": 0.01}),
            ("current", {"0": 0.07, "360": 0.04, "720": 0.025, "1440": 0.015}),
            ("wide",    {"0": 0.10, "360": 0.06, "720": 0.035, "1440": 0.02}),
            ("wider",   {"0": 0.15, "360": 0.08, "720": 0.05, "1440": 0.025}),
        ],
    },
}

# Phase 1: Quick scan on full_12m only to find top candidates
# Phase 2: Validate top 10 across all windows
PHASE1_WINDOWS = {
    "full_12m": ("20250601", "20260331", "Full 12 months"),
}
PHASE2_WINDOWS = WINDOWS  # All 5 windows


def log(msg):
    print(f"[opt] {msg}", flush=True)


def modify_strategy(strat_path: Path, params: dict, backup_path: Path):
    """Modify strategy file with new params. Saves backup first."""
    if not backup_path.exists():
        shutil.copy2(str(strat_path), str(backup_path))

    with open(strat_path) as f:
        content = f.read()

    # Replace simple scalar params
    for key in ["stoploss", "trailing_stop_positive", "trailing_stop_positive_offset",
                 "exit_profit_only", "exit_profit_offset"]:
        if key in params:
            val = params[key]
            if isinstance(val, bool):
                val_str = "True" if val else "False"
            else:
                val_str = str(val)
            # Match: key = <value>  with optional comment
            pattern = rf'(\s+{key}\s*=\s*)([^\n#]+)'
            replacement = rf'\g<1>{val_str}'
            content = re.sub(pattern, replacement, content)

    # Replace ROI table
    if "roi_profile" in params:
        roi_name, roi_dict = params["roi_profile"]
        roi_str = json.dumps(roi_dict).replace('"', "'")  # Python dict style
        roi_str = roi_str.replace("'", '"')  # Actually, use proper formatting
        # Build proper Python dict literal
        roi_items = ", ".join(f'"{k}": {v}' for k, v in roi_dict.items())
        roi_str = "{\n        " + roi_items.replace(", ", ",\n        ") + "\n    }"
        pattern = r'(minimal_roi\s*=\s*)\{[^}]+\}'
        content = re.sub(pattern, rf'\g<1>{roi_str}', content, flags=re.DOTALL)

    with open(strat_path, "w") as f:
        f.write(content)


def restore_strategy(strat_path: Path, backup_path: Path):
    """Restore strategy from backup."""
    if backup_path.exists():
        shutil.copy2(str(backup_path), str(strat_path))


def run_backtest(config_path: str, strategy: str, timerange: str) -> dict:
    """Run backtest and return key metrics."""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{USER_DATA}:/freqtrade/user_data",
        DOCKER_IMAGE,
        "backtesting",
        "--strategy", strategy,
        "--timerange", timerange,
        "--timeframe", "1h",
        "--config", f"/freqtrade/user_data/configs/{config_path}",
        "--enable-protections",
        "--export", "none",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return {"error": result.stderr[-200:]}

    # Parse output for key metrics
    output = result.stdout + result.stderr
    metrics = {}

    # Extract from STRATEGY SUMMARY line
    for line in output.split("\n"):
        if strategy in line and "│" in line:
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) >= 7:
                try:
                    metrics["trades"] = int(parts[1])
                    metrics["avg_profit_pct"] = float(parts[2])
                    metrics["total_profit"] = float(parts[3])
                    metrics["total_profit_pct"] = float(parts[4])
                    # Parse win/loss from "40     0    14  74.1" format
                    wdl = parts[6].split()
                    if len(wdl) >= 4:
                        metrics["wins"] = int(wdl[0])
                        metrics["losses"] = int(wdl[2])
                        metrics["win_rate"] = float(wdl[3])
                    # Parse drawdown from "102.184 USDT  9.06%"
                    if len(parts) >= 8:
                        dd_parts = parts[7].split()
                        if len(dd_parts) >= 3:
                            metrics["max_dd_pct"] = float(dd_parts[2].replace("%", ""))
                except (ValueError, IndexError):
                    pass

    # Extract Profit Factor from summary metrics
    for line in output.split("\n"):
        if "Profit factor" in line and "│" in line:
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) >= 2:
                try:
                    metrics["profit_factor"] = float(parts[1])
                except ValueError:
                    pass
        if "Absolute drawdown" in line and "│" in line:
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) >= 2:
                dd_str = parts[1]
                # Extract percentage from "102.184 USDT (9.06%)"
                if "(" in dd_str:
                    pct = dd_str.split("(")[1].replace("%)", "")
                    try:
                        metrics["max_dd_pct"] = float(pct)
                    except ValueError:
                        pass

    # Calculate R:R if we have wins/losses
    if metrics.get("wins") and metrics.get("losses") and metrics.get("total_profit") is not None:
        gw = metrics.get("total_profit", 0) + abs(metrics.get("total_profit", 0))  # approximate
        # Just use PF as the primary quality metric

    return metrics


def generate_param_combos(grid: dict) -> list:
    """Generate all parameter combinations from the grid."""
    # Separate roi_profile from scalar params
    roi_profiles = grid.pop("roi_profile", [("current", {})])
    scalar_keys = list(grid.keys())
    scalar_vals = [grid[k] for k in scalar_keys]

    combos = []
    for roi_name, roi_dict in roi_profiles:
        for vals in itertools.product(*scalar_vals):
            params = dict(zip(scalar_keys, vals))
            params["roi_profile"] = (roi_name, roi_dict)

            # Skip invalid combinations
            # Trailing offset must be > trailing positive
            if params.get("trailing_stop_positive_offset", 0) <= params.get("trailing_stop_positive", 0):
                continue
            # If exit_profit_only is False, skip non-zero offsets
            if not params.get("exit_profit_only", False) and params.get("exit_profit_offset", 0) > 0:
                continue

            combos.append(params)

    return combos


def param_label(params: dict) -> str:
    """Short label for a parameter set."""
    roi_name = params.get("roi_profile", ("?", {}))[0]
    sl = params.get("stoploss", 0)
    tp = params.get("trailing_stop_positive", 0)
    to = params.get("trailing_stop_positive_offset", 0)
    epo = params.get("exit_profit_only", False)
    eo = params.get("exit_profit_offset", 0)
    return f"SL{sl} trail{tp}@{to} ROI:{roi_name} EPO:{epo}/{eo}"


def score_result(metrics: dict) -> float:
    """Score a backtest result. Higher is better.
    Balances profitability, consistency, and risk management."""
    if "error" in metrics or not metrics.get("trades"):
        return -9999

    pf = metrics.get("profit_factor", 0)
    dd = metrics.get("max_dd_pct", 100)
    trades = metrics.get("trades", 0)
    total_pct = metrics.get("total_profit_pct", 0)

    # Penalize too few trades (unreliable)
    trade_penalty = min(1.0, trades / 50)

    # Primary: profit / drawdown ratio (Ionita's key metric)
    if dd > 0:
        profit_dd_ratio = total_pct / dd
    else:
        profit_dd_ratio = total_pct * 10  # No drawdown = very good

    # Score = PF * profit/DD ratio * trade_penalty
    # Bonus for PF > 1.5, penalty for DD > 20%
    score = pf * max(profit_dd_ratio, -5) * trade_penalty
    if dd > 30:
        score *= 0.5  # Heavy penalty for >30% DD
    if pf < 1.0:
        score *= 0.3  # Heavy penalty for losing strategy

    return round(score, 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("strategy", help="Strategy name")
    parser.add_argument("--config", help="Backtest config filename", default=None)
    parser.add_argument("--top", type=int, default=10, help="Show top N results")
    parser.add_argument("--window", help="Single window to test (default: all)", default=None)
    args = parser.parse_args()

    strategy = args.strategy
    config = args.config or f"backtest-{strategy}.json"
    strat_path = USER_DATA / "strategies" / f"{strategy}.py"
    backup_path = USER_DATA / "strategies" / f"{strategy}.py.optim_backup"

    if strategy not in PARAM_GRIDS:
        print(f"No parameter grid defined for {strategy}")
        sys.exit(1)

    grid = dict(PARAM_GRIDS[strategy])  # Copy
    combos = generate_param_combos(grid)
    log(f"Strategy: {strategy}")
    log(f"Parameter combinations: {len(combos)}")

    windows = {args.window: WINDOWS[args.window]} if args.window else PHASE1_WINDOWS

    log(f"Time windows: {list(windows.keys())}")
    log(f"Total backtests: {len(combos) * len(windows)}")
    log("")

    results = []

    try:
        for i, params in enumerate(combos):
            label = param_label(params)
            log(f"[{i+1}/{len(combos)}] Testing: {label}")

            modify_strategy(strat_path, params, backup_path)

            window_results = {}
            total_score = 0

            for wname, (start, end, desc) in windows.items():
                timerange = f"{start}-{end}"
                metrics = run_backtest(config, strategy, timerange)
                window_results[wname] = metrics
                s = score_result(metrics)
                total_score += s

                pf = metrics.get("profit_factor", 0)
                pnl = metrics.get("total_profit_pct", 0)
                dd = metrics.get("max_dd_pct", 0)
                trades = metrics.get("trades", 0)
                wr = metrics.get("win_rate", 0)
                print(f"    {wname:15s}: {trades:4d} trades  PF:{pf:5.2f}  WR:{wr:5.1f}%  P&L:{pnl:+7.2f}%  DD:{dd:5.1f}%  score:{s:+8.2f}")

            avg_score = total_score / len(windows)
            results.append({
                "params": params,
                "label": label,
                "windows": window_results,
                "total_score": total_score,
                "avg_score": avg_score,
            })
            print(f"    {'AVG SCORE':15s}: {avg_score:+8.2f}")
            print()

    finally:
        restore_strategy(strat_path, backup_path)
        if backup_path.exists():
            os.remove(str(backup_path))
        log("Strategy file restored")

    # Sort by total score
    results.sort(key=lambda r: r["total_score"], reverse=True)

    # Print top results
    print("\n" + "=" * 90)
    print(f" TOP {args.top} PARAMETER COMBINATIONS FOR {strategy}")
    print("=" * 90)

    for rank, r in enumerate(results[:args.top], 1):
        print(f"\n#{rank} (score: {r['avg_score']:+.2f}) — {r['label']}")
        for wname, m in r["windows"].items():
            pf = m.get("profit_factor", 0)
            pnl = m.get("total_profit_pct", 0)
            dd = m.get("max_dd_pct", 0)
            trades = m.get("trades", 0)
            print(f"    {wname:15s}: PF:{pf:5.2f}  P&L:{pnl:+7.2f}%  DD:{dd:5.1f}%  trades:{trades}")

    # Print the winner's full params
    if results:
        winner = results[0]
        print(f"\n{'='*90}")
        print(f" RECOMMENDED PARAMETERS")
        print(f"{'='*90}")
        p = winner["params"]
        roi_name, roi_dict = p.get("roi_profile", ("?", {}))
        print(f"  stoploss = {p.get('stoploss')}")
        print(f"  trailing_stop_positive = {p.get('trailing_stop_positive')}")
        print(f"  trailing_stop_positive_offset = {p.get('trailing_stop_positive_offset')}")
        print(f"  exit_profit_only = {p.get('exit_profit_only')}")
        print(f"  exit_profit_offset = {p.get('exit_profit_offset')}")
        print(f"  minimal_roi = {json.dumps(roi_dict, indent=4)}")

    # ── Phase 2: Validate top 10 across all windows ────────────
    if not args.window and len(results) > 0:
        log("")
        log("=" * 60)
        log(" PHASE 2: Validating top 10 across all time windows")
        log("=" * 60)

        top_n = min(10, len(results))
        phase2_results = []

        try:
            for rank, r in enumerate(results[:top_n], 1):
                label = r["label"]
                log(f"[{rank}/{top_n}] Validating: {label}")
                modify_strategy(strat_path, r["params"], backup_path)

                window_results = {}
                total_score = 0

                for wname, (start, end, desc) in PHASE2_WINDOWS.items():
                    timerange = f"{start}-{end}"
                    metrics = run_backtest(config, strategy, timerange)
                    window_results[wname] = metrics
                    s = score_result(metrics)
                    total_score += s

                    pf = metrics.get("profit_factor", 0)
                    pnl = metrics.get("total_profit_pct", 0)
                    dd = metrics.get("max_dd_pct", 0)
                    trades = metrics.get("trades", 0)
                    wr = metrics.get("win_rate", 0)
                    print(f"    {wname:15s}: {trades:4d} trades  PF:{pf:5.2f}  WR:{wr:5.1f}%  P&L:{pnl:+7.2f}%  DD:{dd:5.1f}%  score:{s:+8.2f}")

                avg_score = total_score / len(PHASE2_WINDOWS)
                phase2_results.append({
                    "params": r["params"],
                    "label": label,
                    "windows": window_results,
                    "total_score": total_score,
                    "avg_score": avg_score,
                    "phase1_rank": rank,
                })
                print(f"    {'AVG SCORE':15s}: {avg_score:+8.2f}")
                print()

        finally:
            restore_strategy(strat_path, backup_path)
            if backup_path.exists():
                os.remove(str(backup_path))

        # Re-sort by phase 2 score
        phase2_results.sort(key=lambda r: r["total_score"], reverse=True)

        print("\n" + "=" * 90)
        print(f" PHASE 2 VALIDATED RESULTS — TOP {top_n} FOR {strategy}")
        print("=" * 90)

        for rank, r in enumerate(phase2_results, 1):
            profitable_windows = sum(
                1 for m in r["windows"].values()
                if m.get("profit_factor", 0) >= 1.0
            )
            print(f"\n#{rank} (phase1:#{r['phase1_rank']}, score:{r['avg_score']:+.2f}, profitable in {profitable_windows}/{len(PHASE2_WINDOWS)} windows)")
            print(f"  {r['label']}")
            for wname, m in r["windows"].items():
                pf = m.get("profit_factor", 0)
                pnl = m.get("total_profit_pct", 0)
                dd = m.get("max_dd_pct", 0)
                trades = m.get("trades", 0)
                marker = "  OK" if pf >= 1.0 else " BAD"
                print(f"    {wname:15s}: PF:{pf:5.2f}  P&L:{pnl:+7.2f}%  DD:{dd:5.1f}%  trades:{trades}{marker}")

        # Use phase2 results for the final recommendation
        results = phase2_results

    # Save full results to JSON
    out_path = BASE_DIR / f"optimization_results_{strategy}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out_path, "w") as f:
        # Convert tuples to lists for JSON
        serializable = []
        for r in results:
            sr = dict(r)
            p = dict(sr["params"])
            if "roi_profile" in p:
                name, roi = p["roi_profile"]
                p["roi_profile_name"] = name
                p["roi_profile"] = roi
            sr["params"] = p
            serializable.append(sr)
        json.dump(serializable, f, indent=2)
    log(f"Full results saved to: {out_path}")


if __name__ == "__main__":
    main()
