"""
Walk-Forward Optimization — Stage 4b
=====================================

Rolling window optimization with proper OOS validation. For each window,
hyperopt finds best params on the train period, then those params are INJECTED
into a temp config to test on the OOS (out-of-sample) period.

KEY FIX: The old walk_forward.py optimized params on the train window but then
tested OOS with BASE params — not the optimized ones. This version uses
config_builder.build_backtest_config(param_overrides=optimized_params) to inject
the optimized stoploss/ROI/trailing into the OOS backtest config.
"""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .registry import FT_DIR, get_strategy, get_mode, RESULTS_DIR
from .config_builder import build_backtest_config, build_hyperopt_config
from .hyperopt import run_multi_loss_hyperopt, LOSS_FUNCTIONS
from .parsers import parse_backtest_output

log = logging.getLogger("engine.walk_forward")

# OOS backtest timeout — 10 min max
BACKTEST_TIMEOUT = 600

# Consensus thresholds
MIN_LOSS_FUNCTIONS_PROFITABLE = 2   # out of 3
MIN_WINDOWS_PROFITABLE = 4          # out of 6 (for 6-window mode)
MAX_DRAWDOWN_ANY_WINDOW = 35.0      # percent


def generate_windows(
    num_windows: int = 6,
    train_days: int = 90,
    test_days: int = 30,
) -> list[dict]:
    """
    Generate rolling train/test windows ending at today.

    Windows are chronological (oldest first). Each window slides forward
    by test_days so that test periods are non-overlapping and train periods
    overlap by (train_days - test_days).

    Args:
        num_windows: Number of rolling windows to generate.
        train_days: Length of training period in days.
        test_days: Length of OOS test period in days.

    Returns:
        List of window dicts, oldest first:
        [{
            window_num: 1,
            train_start: "2025-07-01", train_end: "2025-09-29",
            test_start: "2025-09-29", test_end: "2025-10-29",
            train_range: "20250701-20250929",
            test_range: "20250929-20251029",
        }, ...]
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []

    for i in range(num_windows, 0, -1):
        # Work backwards from today: window N ends at today,
        # window N-1 ends test_days before that, etc.
        test_end = today - timedelta(days=(i - 1) * test_days)
        test_start = test_end - timedelta(days=test_days)
        train_end = test_start
        train_start = train_end - timedelta(days=train_days)

        windows.append({
            "window_num": num_windows - i + 1,
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
            "train_range": f"{train_start.strftime('%Y%m%d')}-{train_end.strftime('%Y%m%d')}",
            "test_range": f"{test_start.strftime('%Y%m%d')}-{test_end.strftime('%Y%m%d')}",
        })

    return windows


def _extract_param_overrides(hyperopt_params: dict) -> dict:
    """
    Extract param overrides from hyperopt result params dict.

    Hyperopt returns params in a nested structure. We flatten it into
    the keys that config_builder.build_backtest_config expects:
    stoploss, minimal_roi, trailing_stop, trailing_stop_positive,
    trailing_stop_positive_offset, trailing_only_offset_is_reached.
    """
    overrides = {}

    if not hyperopt_params:
        return overrides

    # Stoploss — direct key or nested under "stoploss"
    if "stoploss" in hyperopt_params:
        overrides["stoploss"] = hyperopt_params["stoploss"]

    # ROI — can be "roi" dict or "minimal_roi" dict
    if "minimal_roi" in hyperopt_params:
        overrides["minimal_roi"] = hyperopt_params["minimal_roi"]
    elif "roi" in hyperopt_params:
        overrides["minimal_roi"] = hyperopt_params["roi"]

    # Trailing — direct keys
    for key in [
        "trailing_stop",
        "trailing_stop_positive",
        "trailing_stop_positive_offset",
        "trailing_only_offset_is_reached",
    ]:
        if key in hyperopt_params:
            overrides[key] = hyperopt_params[key]

    return overrides


def run_oos_backtest(
    strategy_name: str,
    timerange: str,
    config_path: str,
    param_overrides: dict,
    pairs: list[str],
) -> Optional[dict]:
    """
    Run OOS backtest with injected optimized params.

    KEY: Uses build_backtest_config with param_overrides to inject the
    optimized stoploss/ROI/trailing into a config file, then runs the
    backtest with that config.

    Args:
        strategy_name: Strategy class name.
        timerange: Freqtrade timerange for the OOS period.
        config_path: Unused (kept for API compat) — we build a fresh config.
        param_overrides: Dict of optimized params to inject (stoploss, minimal_roi, etc.).
        pairs: Pair whitelist for the backtest config.

    Returns:
        Parsed backtest metrics dict, or None if backtest failed.
    """
    # Build a config with injected optimized params — this is THE key fix
    oos_config_path = build_backtest_config(
        strategy_name=strategy_name,
        pairs=pairs,
        param_overrides=param_overrides,
    )

    strat = get_strategy(strategy_name)
    image = strat["image"]

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data",
        image, "backtesting",
        "--strategy", strategy_name,
        "--config", oos_config_path,
        "--timerange", timerange,
        "--timeframe-detail", "1m",
    ]

    log.info(
        "Running OOS backtest: strategy=%s timerange=%s with %d param overrides",
        strategy_name, timerange, len(param_overrides),
    )

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=BACKTEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error(
            "OOS backtest timed out after %ds: strategy=%s timerange=%s",
            BACKTEST_TIMEOUT, strategy_name, timerange,
        )
        return None

    if result.returncode != 0:
        log.error(
            "OOS backtest failed (rc=%d): strategy=%s timerange=%s\nstderr: %s",
            result.returncode, strategy_name, timerange,
            result.stderr[-500:] if result.stderr else "(empty)",
        )
        return None

    combined_output = result.stdout + "\n" + result.stderr
    parsed = parse_backtest_output(combined_output, strategy_name)

    if parsed is None:
        log.warning(
            "Could not parse OOS backtest output: strategy=%s timerange=%s",
            strategy_name, timerange,
        )
        return None

    parsed["timerange"] = timerange
    parsed["param_overrides"] = param_overrides

    log.info(
        "OOS backtest result: strategy=%s timerange=%s trades=%d profit=%.2f%%",
        strategy_name, timerange,
        parsed.get("total_trades", 0),
        parsed.get("total_profit_pct", 0),
    )

    return parsed


def compute_consensus(window_results: list[dict], num_windows: int = 6) -> dict:
    """
    Score consensus across all loss functions x all windows.

    Criteria:
    - Params must be OOS-profitable under >= 2/3 loss functions
    - Params must be OOS-profitable in >= 4/6 windows (scaled for fewer windows)
    - Reject if any window has DD > 35%

    Args:
        window_results: List of per-window result dicts, each containing
            per-loss-function OOS results.
        num_windows: Total number of windows (for threshold calculation).

    Returns:
        {
            consensus_params: dict or None (best params if consensus reached),
            avg_oos_sharpe: float,
            robustness_pct: float (% of window*loss combos that were profitable),
            per_window_results: list,
            per_loss_results: dict,
            passed: bool,
            rejection_reasons: list[str],
        }
    """
    # Scale the minimum windows threshold proportionally
    min_windows = max(2, int(num_windows * MIN_WINDOWS_PROFITABLE / 6))

    rejection_reasons = []
    per_loss_results = {lf: [] for lf in LOSS_FUNCTIONS}
    all_sharpes = []
    profitable_combos = 0
    total_combos = 0

    # Per-loss-function profitability tracking
    loss_fn_profitable_windows = {lf: 0 for lf in LOSS_FUNCTIONS}
    loss_fn_total_windows = {lf: 0 for lf in LOSS_FUNCTIONS}

    # Per-window profitability tracking (profitable under any loss fn)
    window_profitable_count = 0
    any_window_excessive_dd = False

    for wr in window_results:
        window_num = wr.get("window_num", "?")
        window_has_profitable = False

        for loss_fn in LOSS_FUNCTIONS:
            oos = wr.get("oos_results", {}).get(loss_fn)
            if oos is None:
                continue

            total_combos += 1
            loss_fn_total_windows[loss_fn] += 1

            profit = oos.get("total_profit_pct", 0)
            dd = oos.get("max_drawdown_pct", 0)
            sharpe = oos.get("sharpe", 0)

            per_loss_results[loss_fn].append({
                "window_num": window_num,
                "profit_pct": profit,
                "max_drawdown_pct": dd,
                "sharpe": sharpe,
                "trades": oos.get("total_trades", 0),
            })

            if sharpe:
                all_sharpes.append(sharpe)

            if profit > 0:
                profitable_combos += 1
                loss_fn_profitable_windows[loss_fn] += 1
                window_has_profitable = True

            if dd > MAX_DRAWDOWN_ANY_WINDOW:
                any_window_excessive_dd = True
                rejection_reasons.append(
                    f"Window {window_num} / {loss_fn}: DD {dd:.1f}% > {MAX_DRAWDOWN_ANY_WINDOW}%"
                )

        if window_has_profitable:
            window_profitable_count += 1

    # Check consensus criteria
    passed = True

    # Criterion 1: profitable under >= 2/3 loss functions
    loss_fns_profitable = sum(
        1 for lf in LOSS_FUNCTIONS
        if loss_fn_total_windows[lf] > 0
        and loss_fn_profitable_windows[lf] >= max(1, loss_fn_total_windows[lf] // 2)
    )
    if loss_fns_profitable < MIN_LOSS_FUNCTIONS_PROFITABLE:
        passed = False
        rejection_reasons.append(
            f"Only {loss_fns_profitable}/{len(LOSS_FUNCTIONS)} loss functions "
            f"had majority-profitable windows (need {MIN_LOSS_FUNCTIONS_PROFITABLE})"
        )

    # Criterion 2: profitable in >= min_windows
    if window_profitable_count < min_windows:
        passed = False
        rejection_reasons.append(
            f"Only {window_profitable_count}/{num_windows} windows profitable "
            f"(need {min_windows})"
        )

    # Criterion 3: no excessive drawdown
    if any_window_excessive_dd:
        passed = False
        # Specific reasons already added above

    # Select consensus params: pick params from the loss function with
    # the most profitable windows, breaking ties by average profit
    consensus_params = None
    if passed:
        best_loss_fn = None
        best_score = (-1, -float("inf"))

        for lf in LOSS_FUNCTIONS:
            n_profitable = loss_fn_profitable_windows[lf]
            avg_profit = 0
            if per_loss_results[lf]:
                avg_profit = sum(r["profit_pct"] for r in per_loss_results[lf]) / len(per_loss_results[lf])
            score = (n_profitable, avg_profit)
            if score > best_score:
                best_score = score
                best_loss_fn = lf

        if best_loss_fn:
            # Get params from the most recent window for the best loss function
            for wr in reversed(window_results):
                hyperopt_result = wr.get("hyperopt_results", {}).get(best_loss_fn)
                if hyperopt_result and hyperopt_result.get("params"):
                    consensus_params = _extract_param_overrides(hyperopt_result["params"])
                    break

    robustness_pct = (profitable_combos / total_combos * 100) if total_combos > 0 else 0
    avg_sharpe = sum(all_sharpes) / len(all_sharpes) if all_sharpes else 0

    return {
        "consensus_params": consensus_params,
        "avg_oos_sharpe": round(avg_sharpe, 3),
        "robustness_pct": round(robustness_pct, 1),
        "per_window_results": window_results,
        "per_loss_results": per_loss_results,
        "passed": passed,
        "rejection_reasons": rejection_reasons,
        "windows_profitable": window_profitable_count,
        "windows_total": len(window_results),
        "loss_functions_profitable": loss_fns_profitable,
    }


def run_walk_forward_stage(
    strategy_name: str,
    pairs: list[str],
    mode_config: dict,
) -> dict:
    """
    Main entry point for Stage 4: Walk-Forward Optimization.

    For each window:
        For each loss function:
            1. Run hyperopt on train period
            2. Parse best params
            3. Run OOS backtest with injected params (THE KEY FIX)
            4. Record results

    Compute consensus across all windows and loss functions.

    Args:
        strategy_name: Strategy class name.
        pairs: Pair whitelist for hyperopt/backtest.
        mode_config: Operating mode dict from registry (fast/thorough/rigorous).
            Expected keys: epochs, wf_windows, train_days, test_days.

    Returns:
        Full results dict including consensus scoring.
    """
    num_windows = mode_config.get("wf_windows", 6)
    train_days = mode_config.get("train_days", 90)
    test_days = mode_config.get("test_days", 30)
    epochs = mode_config.get("epochs", 500)

    log.info(
        "Starting walk-forward: strategy=%s windows=%d train=%dd test=%dd epochs=%d pairs=%d",
        strategy_name, num_windows, train_days, test_days, epochs, len(pairs),
    )

    # Generate rolling windows
    windows = generate_windows(
        num_windows=num_windows,
        train_days=train_days,
        test_days=test_days,
    )

    log.info(
        "Windows generated: %s to %s",
        windows[0]["train_start"], windows[-1]["test_end"],
    )

    # Build hyperopt config (pairs + strategy settings, no param overrides)
    hyperopt_config_path = build_hyperopt_config(strategy_name, pairs)

    # Process each window
    window_results = []

    for window in windows:
        wnum = window["window_num"]
        log.info(
            "=== Window %d/%d: train=%s test=%s ===",
            wnum, num_windows, window["train_range"], window["test_range"],
        )

        # Run multi-loss hyperopt on the train period
        hyperopt_results = run_multi_loss_hyperopt(
            strategy_name=strategy_name,
            timerange=window["train_range"],
            config_path=hyperopt_config_path,
            epochs=epochs,
        )

        # Run OOS backtest for each loss function using its optimized params
        oos_results = {}

        for loss_fn in LOSS_FUNCTIONS:
            ho_result = hyperopt_results.get(loss_fn)
            if ho_result is None or not ho_result.get("params"):
                log.warning(
                    "Window %d: No params from %s hyperopt, skipping OOS",
                    wnum, loss_fn,
                )
                oos_results[loss_fn] = None
                continue

            # Extract optimized params for injection
            param_overrides = _extract_param_overrides(ho_result["params"])

            if not param_overrides:
                log.warning(
                    "Window %d: Empty param overrides from %s, skipping OOS",
                    wnum, loss_fn,
                )
                oos_results[loss_fn] = None
                continue

            log.info(
                "Window %d: OOS backtest with %s params: %s",
                wnum, loss_fn, param_overrides,
            )

            oos_result = run_oos_backtest(
                strategy_name=strategy_name,
                timerange=window["test_range"],
                config_path=hyperopt_config_path,  # unused, build_backtest_config makes its own
                param_overrides=param_overrides,
                pairs=pairs,
            )

            oos_results[loss_fn] = oos_result

        window_results.append({
            "window_num": wnum,
            "window": window,
            "hyperopt_results": hyperopt_results,
            "oos_results": oos_results,
        })

        # Log window summary
        oos_profitable = sum(
            1 for r in oos_results.values()
            if r is not None and r.get("total_profit_pct", 0) > 0
        )
        log.info(
            "Window %d complete: %d/%d loss functions OOS-profitable",
            wnum, oos_profitable, len(LOSS_FUNCTIONS),
        )

    # Compute consensus across all windows
    consensus = compute_consensus(window_results, num_windows=num_windows)

    log.info(
        "Walk-forward complete: strategy=%s passed=%s robustness=%.1f%% "
        "windows_profitable=%d/%d sharpe=%.3f",
        strategy_name,
        consensus["passed"],
        consensus["robustness_pct"],
        consensus["windows_profitable"],
        consensus["windows_total"],
        consensus["avg_oos_sharpe"],
    )

    if consensus["rejection_reasons"]:
        for reason in consensus["rejection_reasons"]:
            log.warning("Rejection: %s", reason)

    return {
        "strategy": strategy_name,
        "stage": "walk_forward",
        "mode": {
            "windows": num_windows,
            "train_days": train_days,
            "test_days": test_days,
            "epochs": epochs,
        },
        "pairs": pairs,
        "windows": windows,
        "consensus": consensus,
    }
