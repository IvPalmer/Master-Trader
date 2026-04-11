#!/usr/bin/env python3
"""
Backtest Engine v2 — Main Orchestrator
=======================================

Single CLI entry point for the 6-stage backtesting pipeline:

    1. data         — Download and validate historical data
    2. calibration  — Compare live vs backtest per strategy
    3. viability    — Screen strategies (kill dead ones)
    4. walk_forward — Optimize via rolling windows
    5. robustness   — Monte Carlo + perturbation
    6. reporting    — Generate reports, send Telegram

Usage:
    python backtest_engine.py --mode rigorous
    python backtest_engine.py --strategy SupertrendStrategy --mode thorough
    python backtest_engine.py --mode fast --stages calibration,viability
    python backtest_engine.py --mode thorough --skip-download
    python backtest_engine.py --list
    python backtest_engine.py --calibrate MasterTraderV1
    python backtest_engine.py --report --telegram
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from engine.registry import (
    get_active_strategies,
    get_strategy,
    get_mode,
    STRATEGIES,
    MODES,
    RESULTS_DIR,
    FT_DIR,
    LOGS_DIR,
)
from engine.data import run_data_stage

# Stage imports — some modules may not be built yet.
# Import gracefully so the pipeline can run stages that do exist.

try:
    from engine.calibration import run_calibration_stage
except ImportError:
    run_calibration_stage = None  # type: ignore[assignment]

try:
    from engine.viability import run_viability_stage
except ImportError:
    run_viability_stage = None  # type: ignore[assignment]

try:
    from engine.walk_forward import run_walk_forward_stage
except ImportError:
    run_walk_forward_stage = None  # type: ignore[assignment]

try:
    from engine.monte_carlo import run_robustness_stage
except ImportError:
    run_robustness_stage = None  # type: ignore[assignment]

try:
    from engine.reporting import run_reporting_stage, build_report_card
except ImportError:
    run_reporting_stage = None  # type: ignore[assignment]
    build_report_card = None  # type: ignore[assignment]


# ── Constants ─────────────────────────────────────────────────────────────

PIPELINE_STAGES = ["data", "calibration", "viability", "walk_forward", "robustness", "reporting"]

STAGE_FUNCS = {
    "data": "run_data_stage",
    "calibration": "run_calibration_stage",
    "viability": "run_viability_stage",
    "walk_forward": "run_walk_forward_stage",
    "robustness": "run_robustness_stage",
    "reporting": "run_reporting_stage",
}


# ── Logging Setup ─────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Configure logging to file and stdout."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "backtest_engine.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("engine")


log = setup_logging()


# ── Helpers ───────────────────────────────────────────────────────────────

def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = int(minutes // 60)
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _run_dir(mode: str) -> Path:
    """Build the results directory for this run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_path = RESULTS_DIR / f"{timestamp}_{mode}"
    run_path.mkdir(parents=True, exist_ok=True)
    return run_path


def _save_results(run_path: Path, results: dict) -> None:
    """Save full pipeline results to disk."""
    out_file = run_path / "pipeline_results.json"
    try:
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        log.info("Results saved: %s", out_file)
    except Exception as e:
        log.error("Failed to save results: %s", e)


def _load_latest_results() -> Optional[dict]:
    """Load results from the most recent pipeline run."""
    if not RESULTS_DIR.exists():
        return None

    run_dirs = sorted(
        [d for d in RESULTS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )

    for run_dir in run_dirs:
        results_file = run_dir / "pipeline_results.json"
        if results_file.exists():
            try:
                with open(results_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load %s: %s", results_file, e)
                continue

    return None


def _is_stage_available(stage: str) -> bool:
    """Check if a stage's module is imported and available."""
    mapping = {
        "data": run_data_stage,
        "calibration": run_calibration_stage,
        "viability": run_viability_stage,
        "walk_forward": run_walk_forward_stage,
        "robustness": run_robustness_stage,
        "reporting": run_reporting_stage,
    }
    return mapping.get(stage) is not None


def _print_registry_table() -> None:
    """Print a formatted table of all registered strategies."""
    header = f"{'Strategy':<25} {'TF':<5} {'Mode':<8} {'Port':<6} {'Stake':<7} {'Status':<8}"
    sep = "-" * len(header)
    print("\nStrategy Registry")
    print(sep)
    print(header)
    print(sep)

    for name, cfg in STRATEGIES.items():
        print(
            f"{name:<25} {cfg['timeframe']:<5} {cfg['trading_mode']:<8} "
            f"{cfg['port']:<6} ${cfg['stake_amount']:<6} {cfg.get('status', 'unknown'):<8}"
        )

    print(sep)
    active = sum(1 for s in STRATEGIES.values() if s.get("status") == "active")
    print(f"Total: {len(STRATEGIES)} strategies ({active} active)")

    print(f"\nModes: {', '.join(MODES.keys())}")
    for mode_name, mode_cfg in MODES.items():
        print(f"  {mode_name}: {mode_cfg['description']}")
    print()


def _print_report_card(results: dict) -> None:
    """Print a summary report card to the console."""
    if build_report_card is not None:
        try:
            strategies_data = results.get("strategies", {})
            for strat_name, strat_results in strategies_data.items():
                card = build_report_card(strat_name, strat_results)
                print(card)
            return
        except Exception as e:
            log.warning("build_report_card failed, using built-in summary: %s", e)

    # Fallback: built-in summary
    print("\n" + "=" * 60)
    print("PIPELINE RESULTS SUMMARY")
    print("=" * 60)

    meta = results.get("meta", {})
    print(f"Mode:       {meta.get('mode', '?')}")
    print(f"Strategies: {', '.join(meta.get('strategies', []))}")
    print(f"Duration:   {meta.get('total_duration', '?')}")
    print(f"Status:     {meta.get('status', '?')}")

    killed = []
    for strat_name, strat_results in results.get("strategies", {}).items():
        viability = strat_results.get("viability", {})
        classification = viability.get("classification", "N/A")
        metrics = viability.get("metrics", {})

        trades = metrics.get("total_trades", "?")
        pf = metrics.get("profit_factor", "?")
        dd = metrics.get("max_drawdown_pct", "?")

        status_icon = {"VIABLE": "[OK]", "MARGINAL": "[!!]", "DEAD": "[XX]"}.get(
            classification, "[??]"
        )

        print(f"\n  {status_icon} {strat_name}")
        print(f"      Classification: {classification}")

        if isinstance(trades, (int, float)):
            print(f"      Trades: {trades}, PF: {pf}, DD: {dd}%")

        reasons = viability.get("reasons", [])
        for r in reasons:
            print(f"      -> {r}")

        if classification == "DEAD":
            killed.append(strat_name)

    if killed:
        print(f"\nFLAGGED FOR REMOVAL: {', '.join(killed)}")
    else:
        print("\nNo strategies flagged.")

    print("=" * 60)


# ── Pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(
    mode: str = "fast",
    strategies: Optional[list[str]] = None,
    stages: Optional[list[str]] = None,
    skip_download: bool = False,
    send_telegram: bool = False,
) -> dict:
    """
    Run the full pipeline or selected stages.

    Flow:
    1. Resolve strategies (--strategy or all active)
    2. Resolve mode config
    3. For each stage in order:
       a. Skip if not in --stages filter
       b. Run stage
       c. Log progress
       d. If viability=DEAD, skip walk_forward+robustness for that strategy
    4. Run reporting
    5. Return full results dict

    Args:
        mode: Operating mode ('fast', 'thorough', 'rigorous')
        strategies: List of strategy names (None = all active)
        stages: List of stage names to run (None = all stages)
        skip_download: If True, skip the data download stage
        send_telegram: If True, send final report via Telegram

    Returns:
        Full results dict with per-strategy results and metadata.
    """
    pipeline_start = time.time()
    mode_cfg = get_mode(mode)

    # Resolve strategies
    if strategies:
        strat_names = []
        for s in strategies:
            try:
                get_strategy(s)
                strat_names.append(s)
            except KeyError as e:
                log.error(str(e))
                sys.exit(2)
    else:
        strat_names = list(get_active_strategies().keys())

    if not strat_names:
        log.error("No strategies to process")
        sys.exit(2)

    # Resolve stages
    active_stages = stages if stages else PIPELINE_STAGES[:]

    # Ensure reporting always runs last
    if "reporting" not in active_stages:
        active_stages.append("reporting")

    # Validate stage names
    for s in active_stages:
        if s not in PIPELINE_STAGES:
            log.error("Unknown stage: %s. Valid stages: %s", s, PIPELINE_STAGES)
            sys.exit(2)

    # Set up results directory
    run_path = _run_dir(mode)

    log.info("=" * 60)
    log.info("BACKTEST ENGINE v2")
    log.info("=" * 60)
    log.info("Mode:       %s — %s", mode, mode_cfg["description"])
    log.info("Strategies: %s", ", ".join(strat_names))
    log.info("Stages:     %s", ", ".join(active_stages))
    log.info("Results:    %s", run_path)
    log.info("=" * 60)

    # Initialize results structure
    results: dict = {
        "meta": {
            "mode": mode,
            "mode_config": mode_cfg,
            "strategies": strat_names,
            "stages_requested": active_stages,
            "stages_completed": [],
            "run_dir": str(run_path),
            "started_at": datetime.now().isoformat(),
            "status": "running",
        },
        "strategies": {name: {} for name in strat_names},
        "stage_durations": {},
    }

    # Track which strategies are dead (skip expensive stages for them)
    dead_strategies: set[str] = set()

    # ── Stage 1: Data ─────────────────────────────────────────────────

    if "data" in active_stages and not skip_download:
        stage_start = time.time()
        log.info("")
        log.info(">>> STAGE 1: DATA PREPARATION <<<")
        log.info("")

        try:
            data_result = run_data_stage(
                mode_name=mode,
                strategies=strat_names,
            )
            results["data"] = data_result
            results["meta"]["stages_completed"].append("data")
        except Exception as e:
            log.error("Data stage failed: %s", e, exc_info=True)
            results["data"] = {"status": "error", "error": str(e)}

        duration = time.time() - stage_start
        results["stage_durations"]["data"] = duration
        log.info("Stage 1 completed in %s", _format_duration(duration))
    elif "data" in active_stages and skip_download:
        log.info("Skipping data download (--skip-download)")
        results["data"] = {"status": "skipped"}
        results["meta"]["stages_completed"].append("data")

    # Extract timerange and pairs from data stage for downstream use
    data_result = results.get("data", {})
    timerange = data_result.get("timerange")
    spot_pairs = data_result.get("spot_pairs", [])
    futures_pairs = data_result.get("futures_pairs", [])

    # If we skipped data or it failed, build a default timerange
    if not timerange:
        from engine.data import _build_timerange
        timerange = _build_timerange(400)
        log.info("Using default timerange: %s", timerange)

    # If pairs are empty (data stage skipped/failed), fetch them now
    if not spot_pairs:
        log.info("No spot pairs from data stage — fetching from Binance API...")
        try:
            from engine.data import fetch_top_pairs_spot
            spot_pairs = fetch_top_pairs_spot(limit=50)
            log.info("Fetched %d spot pairs", len(spot_pairs))
        except Exception as e:
            log.error("Failed to fetch spot pairs: %s", e)
            # Fallback to pairs from backtest_base.json
            try:
                with open(FT_DIR / "user_data" / "configs" / "backtest_base.json") as f:
                    base_cfg = json.load(f)
                spot_pairs = base_cfg.get("exchange", {}).get("pair_whitelist", [])
                log.info("Using %d pairs from backtest_base.json", len(spot_pairs))
            except Exception:
                log.error("No pairs available — downstream stages will fail")

    if not futures_pairs:
        try:
            from engine.data import fetch_top_pairs_futures
            futures_pairs = fetch_top_pairs_futures(limit=20)
            log.info("Fetched %d futures pairs", len(futures_pairs))
        except Exception as e:
            log.warning("Failed to fetch futures pairs: %s", e)

    # ── Stage 2: Calibration ──────────────────────────────────────────

    if "calibration" in active_stages:
        stage_start = time.time()
        log.info("")
        log.info(">>> STAGE 2: CALIBRATION <<<")
        log.info("")

        if not _is_stage_available("calibration"):
            log.warning("Calibration module not implemented yet — skipping")
            results["meta"]["stages_completed"].append("calibration")
        else:
            for strat_name in strat_names:
                try:
                    strat_cfg = get_strategy(strat_name)
                    pairs = futures_pairs if strat_cfg["trading_mode"] == "futures" else spot_pairs
                    cal_result = run_calibration_stage(
                        strategy_name=strat_name,
                    )
                    results["strategies"][strat_name]["calibration"] = cal_result
                    log.info("Calibration %s: complete", strat_name)
                except Exception as e:
                    log.error("Calibration failed for %s: %s", strat_name, e, exc_info=True)
                    results["strategies"][strat_name]["calibration"] = {
                        "error": str(e),
                    }

            results["meta"]["stages_completed"].append("calibration")

        duration = time.time() - stage_start
        results["stage_durations"]["calibration"] = duration
        log.info("Stage 2 completed in %s", _format_duration(duration))

    # ── Stage 3: Viability ────────────────────────────────────────────
    # GATE: Skip viability if calibration score is too low.
    # Low calibration = backtest can't reproduce live trades = viability
    # results are unreliable (garbage in, garbage out).

    CALIBRATION_GATE_SCORE = 50  # minimum calibration to trust viability

    if "viability" in active_stages:
        stage_start = time.time()
        log.info("")
        log.info(">>> STAGE 3: VIABILITY SCREENING <<<")
        log.info("")

        if not _is_stage_available("viability"):
            log.warning("Viability module not implemented yet — skipping")
            results["meta"]["stages_completed"].append("viability")
        else:
            for strat_name in strat_names:
                # Check calibration gate
                cal_result = results["strategies"][strat_name].get("calibration", {})
                cal_score = cal_result.get("score", 0)
                cal_error = cal_result.get("error")

                if "calibration" in active_stages and cal_score < CALIBRATION_GATE_SCORE and not cal_error:
                    log.warning(
                        "Skipping viability for %s — calibration score %.1f < %d "
                        "(backtest unreliable, viability results would be misleading)",
                        strat_name, cal_score, CALIBRATION_GATE_SCORE,
                    )
                    results["strategies"][strat_name]["viability"] = {
                        "classification": "SKIPPED",
                        "reason": f"Calibration score {cal_score:.1f} below gate ({CALIBRATION_GATE_SCORE}). "
                                  "Backtest cannot reproduce live trades — viability results unreliable.",
                        "skipped": True,
                    }
                    continue

                try:
                    strat_cfg = get_strategy(strat_name)
                    pairs = futures_pairs if strat_cfg["trading_mode"] == "futures" else spot_pairs
                    via_result = run_viability_stage(
                        strategy_name=strat_name,
                        pairs=pairs,
                        timerange=timerange,
                    )
                    results["strategies"][strat_name]["viability"] = via_result

                    classification = via_result.get("classification", "UNKNOWN")
                    log.info("Viability %s: %s", strat_name, classification)

                    if classification == "DEAD":
                        dead_strategies.add(strat_name)
                        log.warning(
                            "Strategy %s flagged DEAD — skipping walk_forward and robustness",
                            strat_name,
                        )
                except Exception as e:
                    log.error("Viability failed for %s: %s", strat_name, e, exc_info=True)
                    results["strategies"][strat_name]["viability"] = {
                        "classification": "ERROR",
                        "error": str(e),
                    }

            results["meta"]["stages_completed"].append("viability")

        duration = time.time() - stage_start
        results["stage_durations"]["viability"] = duration
        log.info("Stage 3 completed in %s", _format_duration(duration))

    # ── Stage 4: Walk-Forward Optimization ────────────────────────────

    if "walk_forward" in active_stages:
        stage_start = time.time()
        log.info("")
        log.info(">>> STAGE 4: WALK-FORWARD OPTIMIZATION <<<")
        log.info("")

        if not _is_stage_available("walk_forward"):
            log.warning("Walk-forward module not implemented yet — skipping")
            results["meta"]["stages_completed"].append("walk_forward")
        else:
            for strat_name in strat_names:
                if strat_name in dead_strategies:
                    log.info("Skipping walk_forward for %s (DEAD)", strat_name)
                    results["strategies"][strat_name]["walk_forward"] = {
                        "skipped": True,
                        "reason": "classified DEAD in viability",
                    }
                    continue

                try:
                    strat_cfg = get_strategy(strat_name)
                    pairs = futures_pairs if strat_cfg["trading_mode"] == "futures" else spot_pairs
                    wf_result = run_walk_forward_stage(
                        strategy_name=strat_name,
                        pairs=pairs,
                        mode_config=mode_cfg,
                    )
                    results["strategies"][strat_name]["walk_forward"] = wf_result
                    log.info("Walk-forward %s: complete", strat_name)
                except Exception as e:
                    log.error("Walk-forward failed for %s: %s", strat_name, e, exc_info=True)
                    results["strategies"][strat_name]["walk_forward"] = {
                        "error": str(e),
                    }

            results["meta"]["stages_completed"].append("walk_forward")

        duration = time.time() - stage_start
        results["stage_durations"]["walk_forward"] = duration
        log.info("Stage 4 completed in %s", _format_duration(duration))

    # ── Stage 5: Robustness (Monte Carlo + Perturbation) ──────────────

    if "robustness" in active_stages:
        stage_start = time.time()
        log.info("")
        log.info(">>> STAGE 5: ROBUSTNESS VALIDATION <<<")
        log.info("")

        if not _is_stage_available("robustness"):
            log.warning("Robustness module not implemented yet — skipping")
            results["meta"]["stages_completed"].append("robustness")
        else:
            for strat_name in strat_names:
                if strat_name in dead_strategies:
                    log.info("Skipping robustness for %s (DEAD)", strat_name)
                    results["strategies"][strat_name]["robustness"] = {
                        "skipped": True,
                        "reason": "classified DEAD in viability",
                    }
                    continue

                try:
                    strat_cfg = get_strategy(strat_name)
                    pairs = futures_pairs if strat_cfg["trading_mode"] == "futures" else spot_pairs
                    # Get consensus params from walk-forward results
                    wf_data = results["strategies"][strat_name].get("walk_forward", {})
                    consensus = wf_data.get("consensus", {})
                    base_params = consensus.get("consensus_params", {})
                    # Collect trades from viability backtest for MC shuffle
                    via_data = results["strategies"][strat_name].get("viability", {})
                    trades = via_data.get("_trades", [])
                    rob_result = run_robustness_stage(
                        strategy_name=strat_name,
                        trades=trades,
                        base_params=base_params,
                        pairs=pairs,
                        timerange=timerange,
                        mode_config=mode_cfg,
                    )
                    results["strategies"][strat_name]["robustness"] = rob_result
                    log.info("Robustness %s: complete", strat_name)
                except Exception as e:
                    log.error("Robustness failed for %s: %s", strat_name, e, exc_info=True)
                    results["strategies"][strat_name]["robustness"] = {
                        "error": str(e),
                    }

            results["meta"]["stages_completed"].append("robustness")

        duration = time.time() - stage_start
        results["stage_durations"]["robustness"] = duration
        log.info("Stage 5 completed in %s", _format_duration(duration))

    # ── Stage 6: Reporting ────────────────────────────────────────────

    if "reporting" in active_stages:
        stage_start = time.time()
        log.info("")
        log.info(">>> STAGE 6: REPORTING <<<")
        log.info("")

        if not _is_stage_available("reporting"):
            log.info("Reporting module not implemented yet — using built-in summary")
        else:
            try:
                report_result = run_reporting_stage(
                    all_results=results.get("strategies", {}),
                    mode=mode,
                    send_tg=send_telegram,
                )
                results["reporting"] = report_result
                log.info("Reports generated")
            except Exception as e:
                log.error("Reporting failed: %s", e, exc_info=True)

        results["meta"]["stages_completed"].append("reporting")

        duration = time.time() - stage_start
        results["stage_durations"]["reporting"] = duration
        log.info("Stage 6 completed in %s", _format_duration(duration))

    # ── Finalize ──────────────────────────────────────────────────────

    total_duration = time.time() - pipeline_start
    results["meta"]["total_duration"] = _format_duration(total_duration)
    results["meta"]["finished_at"] = datetime.now().isoformat()

    # Determine exit status
    has_errors = any(
        "error" in results["strategies"].get(s, {}).get("viability", {})
        for s in strat_names
    )
    has_killed = len(dead_strategies) > 0

    if has_errors:
        results["meta"]["status"] = "error"
    elif has_killed:
        results["meta"]["status"] = "killed"
        results["meta"]["killed_strategies"] = sorted(dead_strategies)
    else:
        results["meta"]["status"] = "success"

    # Save results
    _save_results(run_path, results)

    # Print summary
    _print_report_card(results)

    log.info("")
    log.info("Pipeline finished in %s — status: %s",
             _format_duration(total_duration), results["meta"]["status"])
    log.info("Results: %s", run_path)

    return results


# ── CLI ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Backtest Engine v2 — Unified backtesting, optimization, and validation pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --mode rigorous                          Full pipeline, all strategies
  %(prog)s --strategy SupertrendStrategy --mode thorough
  %(prog)s --mode fast --stages calibration,viability
  %(prog)s --mode thorough --skip-download
  %(prog)s --list                                   Show strategy registry
  %(prog)s --calibrate MasterTraderV1               Quick calibration check
  %(prog)s --report --telegram                      Re-generate and send reports
        """,
    )

    parser.add_argument(
        "--mode",
        choices=list(MODES.keys()),
        default="fast",
        help="Operating mode: fast (weekly), thorough (monthly), rigorous (quarterly). Default: fast",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Run pipeline for a single strategy (default: all active)",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default=None,
        help="Comma-separated list of stages to run (default: all). "
             "Valid: data,calibration,viability,walk_forward,robustness,reporting",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip data download (use existing data)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send final report via Telegram",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all registered strategies and exit",
    )
    parser.add_argument(
        "--calibrate",
        type=str,
        metavar="STRATEGY",
        help="Shorthand for --strategy X --stages calibration --mode fast",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Re-load latest results and regenerate reports",
    )

    return parser


def main() -> int:
    """
    Main entry point. Parses CLI args and runs the pipeline.

    Returns:
        Exit code: 0 = success, 1 = strategies killed, 2 = pipeline error.
    """
    parser = build_parser()
    args = parser.parse_args()

    # --list: print registry and exit
    if args.list:
        _print_registry_table()
        return 0

    # --report: reload and regenerate
    if args.report:
        log.info("Reloading latest results for report generation...")
        results = _load_latest_results()
        if results is None:
            log.error("No previous results found in %s", RESULTS_DIR)
            return 2

        if _is_stage_available("reporting"):
            try:
                report_mode = results.get("meta", {}).get("mode", "fast")
                run_reporting_stage(
                    all_results=results.get("strategies", {}),
                    mode=report_mode,
                    send_tg=args.telegram,
                )
            except Exception as e:
                log.error("Reporting failed: %s", e, exc_info=True)
                return 2

        _print_report_card(results)
        return 0

    # --calibrate: shorthand
    if args.calibrate:
        args.strategy = args.calibrate
        args.stages = "calibration"
        args.mode = "fast"

    # Parse strategies
    strategies = None
    if args.strategy:
        strategies = [args.strategy]

    # Parse stages
    stages = None
    if args.stages:
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]

    # Run pipeline
    try:
        results = run_pipeline(
            mode=args.mode,
            strategies=strategies,
            stages=stages,
            skip_download=args.skip_download,
            send_telegram=args.telegram,
        )
    except KeyboardInterrupt:
        log.warning("")
        log.warning("Pipeline interrupted by user (Ctrl+C)")
        log.warning("Partial results may have been saved to %s", RESULTS_DIR)
        return 2
    except Exception as e:
        log.error("Pipeline error: %s", e, exc_info=True)
        return 2

    # Exit code based on pipeline status
    status = results.get("meta", {}).get("status", "error")
    if status == "success":
        return 0
    elif status == "killed":
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
