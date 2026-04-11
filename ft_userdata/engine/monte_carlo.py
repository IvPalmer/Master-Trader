"""
Monte Carlo Robustness Validation — Stage 5
============================================

Stress-tests strategy parameters via:
  5a) Monte Carlo trade shuffling — pure Python equity curve simulation
  5b) Parameter perturbation — Docker backtests with perturbed numeric params

Usage:
    from engine.monte_carlo import run_robustness_stage
    results = run_robustness_stage(strategy, trades, params, pairs, timerange, mode_config)
"""

import copy
import json
import logging
import random
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from .registry import FT_DIR, get_strategy, RESULTS_DIR
from .config_builder import build_backtest_config
from .parsers import parse_backtest_output

log = logging.getLogger("engine.monte_carlo")

DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"
USER_DATA_HOST = Path.home() / "ft_userdata" / "user_data"
USER_DATA_CONTAINER = "/freqtrade/user_data"


# ── 5a: Monte Carlo Trade Shuffle ────────────────────────────────────────


def _simulate_equity_curve(
    trades: list[dict],
    starting_capital: float,
) -> tuple[float, float, int]:
    """
    Walk through trades sequentially, tracking equity, max drawdown, and
    max consecutive losses.

    Returns: (final_equity, max_drawdown_pct, max_consecutive_losses)
    """
    equity = starting_capital
    peak = starting_capital
    max_dd_pct = 0.0
    consec_losses = 0
    max_consec_losses = 0

    for trade in trades:
        pnl = trade["profit_abs"]
        equity += pnl

        if pnl < 0:
            consec_losses += 1
            max_consec_losses = max(max_consec_losses, consec_losses)
        else:
            consec_losses = 0

        if equity > peak:
            peak = equity

        if peak > 0:
            dd_pct = (peak - equity) / peak * 100
            max_dd_pct = max(max_dd_pct, dd_pct)

    return equity, max_dd_pct, max_consec_losses


def run_monte_carlo_shuffle(
    trades: list[dict],
    starting_capital: float = 1000.0,
    iterations: int = 500,
    max_skip_rate: float = 0.15,
) -> dict:
    """
    Randomly shuffle trade execution order and simulate equity curves.

    For each iteration:
    1. Randomly shuffle the trade list
    2. Randomly skip 0-15% of trades (simulate missed entries)
    3. Walk through trades sequentially, tracking equity curve
    4. Record: final equity, max drawdown from peak, max consecutive losses

    Each trade dict has at minimum: {profit_abs: float}
    Additional fields (pair, duration, etc.) are carried through but not required.

    Returns: {
        median_final_equity: float,
        p5_final_equity: float,      # 5th percentile (worst case)
        p95_max_drawdown: float,     # 95th percentile DD (worst case)
        probability_of_ruin: float,  # % of runs where equity < 50% of start
        worst_drawdown: float,       # single worst DD across all runs
        max_consecutive_losses: int,
        mc_score: int,               # 0-100 score
        iterations: int,
        distribution: {
            equity_percentiles: {5, 25, 50, 75, 95},
            dd_percentiles: {5, 25, 50, 75, 95},
        }
    }
    """
    if not trades:
        log.warning("No trades provided for Monte Carlo simulation")
        return {
            "median_final_equity": starting_capital,
            "p5_final_equity": starting_capital,
            "p95_max_drawdown": 0.0,
            "probability_of_ruin": 0.0,
            "worst_drawdown": 0.0,
            "max_consecutive_losses": 0,
            "mc_score": 0,
            "iterations": 0,
            "distribution": {
                "equity_percentiles": {p: starting_capital for p in [5, 25, 50, 75, 95]},
                "dd_percentiles": {p: 0.0 for p in [5, 25, 50, 75, 95]},
            },
        }

    log.info("Running Monte Carlo shuffle: %d trades, %d iterations", len(trades), iterations)

    # Run the baseline (original order, no skips)
    _, base_dd, _ = _simulate_equity_curve(trades, starting_capital)

    final_equities = []
    max_drawdowns = []
    all_consec_losses = []
    ruin_count = 0
    ruin_threshold = starting_capital * 0.5

    for i in range(iterations):
        random.seed(42 + i)

        # Deep copy and shuffle
        shuffled = list(trades)
        random.shuffle(shuffled)

        # Randomly skip 0-max_skip_rate of trades
        skip_rate = random.random() * max_skip_rate
        n_skip = int(len(shuffled) * skip_rate)
        if n_skip > 0:
            skip_indices = set(random.sample(range(len(shuffled)), n_skip))
            shuffled = [t for idx, t in enumerate(shuffled) if idx not in skip_indices]

        final_eq, max_dd, consec_l = _simulate_equity_curve(shuffled, starting_capital)

        final_equities.append(final_eq)
        max_drawdowns.append(max_dd)
        all_consec_losses.append(consec_l)

        if final_eq < ruin_threshold:
            ruin_count += 1

    # Convert to numpy for percentile calculations
    eq_arr = np.array(final_equities)
    dd_arr = np.array(max_drawdowns)

    p5_equity = float(np.percentile(eq_arr, 5))
    p25_equity = float(np.percentile(eq_arr, 25))
    p50_equity = float(np.percentile(eq_arr, 50))
    p75_equity = float(np.percentile(eq_arr, 75))
    p95_equity = float(np.percentile(eq_arr, 95))

    p5_dd = float(np.percentile(dd_arr, 5))
    p25_dd = float(np.percentile(dd_arr, 25))
    p50_dd = float(np.percentile(dd_arr, 50))
    p75_dd = float(np.percentile(dd_arr, 75))
    p95_dd = float(np.percentile(dd_arr, 95))

    worst_dd = float(np.max(dd_arr))
    probability_of_ruin = ruin_count / iterations
    max_consec = int(max(all_consec_losses))

    # Calculate MC score
    mc_score = _calculate_mc_score(
        probability_of_ruin=probability_of_ruin,
        p95_dd=p95_dd,
        base_dd=base_dd,
        median_equity=p50_equity,
        p5_equity=p5_equity,
        starting_capital=starting_capital,
    )

    result = {
        "median_final_equity": round(p50_equity, 2),
        "p5_final_equity": round(p5_equity, 2),
        "p95_max_drawdown": round(p95_dd, 2),
        "probability_of_ruin": round(probability_of_ruin, 4),
        "worst_drawdown": round(worst_dd, 2),
        "max_consecutive_losses": max_consec,
        "mc_score": mc_score,
        "iterations": iterations,
        "distribution": {
            "equity_percentiles": {
                5: round(p5_equity, 2),
                25: round(p25_equity, 2),
                50: round(p50_equity, 2),
                75: round(p75_equity, 2),
                95: round(p95_equity, 2),
            },
            "dd_percentiles": {
                5: round(p5_dd, 2),
                25: round(p25_dd, 2),
                50: round(p50_dd, 2),
                75: round(p75_dd, 2),
                95: round(p95_dd, 2),
            },
        },
    }

    log.info(
        "MC result: score=%d, median_equity=%.2f, p5_equity=%.2f, "
        "p95_dd=%.2f%%, ruin=%.2f%%",
        mc_score, p50_equity, p5_equity, p95_dd, probability_of_ruin * 100,
    )

    return result


def _calculate_mc_score(
    probability_of_ruin: float,
    p95_dd: float,
    base_dd: float,
    median_equity: float,
    p5_equity: float,
    starting_capital: float,
) -> int:
    """
    Score 0-100:
      80-100: Robust — strategy survives trade reordering
      60-79:  Acceptable — some fragility but tradeable
      <60:    Fragile — results depend on specific trade sequence
    """
    score = 100

    # Ruin probability penalty
    if probability_of_ruin > 0.05:
        score -= 30
    elif probability_of_ruin > 0.02:
        score -= 15

    # Drawdown amplification penalty
    if base_dd > 0:
        if p95_dd > 2 * base_dd:
            score -= 20
        elif p95_dd > 1.5 * base_dd:
            score -= 10

    # Median equity below starting capital
    if median_equity < starting_capital:
        score -= 30

    # 5th percentile equity check
    if p5_equity < starting_capital * 0.7:
        score -= 10

    return max(0, score)


# ── 5b: Parameter Perturbation ───────────────────────────────────────────


def _extract_numeric_params(base_params: dict) -> dict[str, float]:
    """
    Extract all perturbable numeric parameters from base_params.

    Returns flat dict: {"stoploss": -0.05, "roi_0": 0.05, "roi_60": 0.03, ...}
    """
    params = {}

    if "stoploss" in base_params and isinstance(base_params["stoploss"], (int, float)):
        params["stoploss"] = float(base_params["stoploss"])

    if "minimal_roi" in base_params and isinstance(base_params["minimal_roi"], dict):
        for timeframe_key, value in base_params["minimal_roi"].items():
            if isinstance(value, (int, float)):
                params[f"roi_{timeframe_key}"] = float(value)

    if "trailing_stop_positive" in base_params and isinstance(
        base_params["trailing_stop_positive"], (int, float)
    ):
        params["trailing_stop_positive"] = float(base_params["trailing_stop_positive"])

    if "trailing_stop_positive_offset" in base_params and isinstance(
        base_params["trailing_stop_positive_offset"], (int, float)
    ):
        params["trailing_stop_positive_offset"] = float(
            base_params["trailing_stop_positive_offset"]
        )

    return params


def _apply_param_variant(
    base_params: dict,
    param_name: str,
    variant_value: float,
) -> dict:
    """
    Return a copy of base_params with one parameter changed to variant_value.
    """
    params = copy.deepcopy(base_params)

    if param_name == "stoploss":
        params["stoploss"] = variant_value
    elif param_name.startswith("roi_"):
        tf_key = param_name[4:]  # strip "roi_"
        if "minimal_roi" in params:
            params["minimal_roi"][tf_key] = variant_value
    elif param_name in ("trailing_stop_positive", "trailing_stop_positive_offset"):
        params[param_name] = variant_value

    return params


def _run_docker_backtest(
    strategy_name: str,
    config_path: str,
    timerange: str,
) -> Optional[dict]:
    """
    Run a Freqtrade backtest in Docker and return parsed metrics.
    """
    strat = get_strategy(strategy_name)
    image = strat.get("image", DOCKER_IMAGE)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{USER_DATA_HOST}:{USER_DATA_CONTAINER}",
        image,
        "backtesting",
        "--strategy", strategy_name,
        "--config", config_path,
        "--timerange", timerange,
    ]

    log.debug("Running backtest: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        combined = result.stdout + "\n" + result.stderr
        metrics = parse_backtest_output(combined, strategy_name)
        if metrics:
            return metrics
        else:
            log.warning("Failed to parse backtest output for %s", strategy_name)
            log.debug("Backtest stdout (last 500 chars): %s", result.stdout[-500:])
            return None
    except subprocess.TimeoutExpired:
        log.error("Backtest timed out for %s", strategy_name)
        return None
    except Exception as e:
        log.error("Backtest failed for %s: %s", strategy_name, e)
        return None


def _classify_sensitivity(pct_change: float, perturb_pct: int) -> str:
    """
    Classify parameter sensitivity.

    HIGH:   ±10% changes P&L > 40% → fragile, likely overfitted
    MEDIUM: ±20% changes P&L 15-40% → normal
    LOW:    ±20% changes P&L < 15% → robust
    """
    if perturb_pct <= 10 and pct_change > 40:
        return "HIGH"
    elif pct_change > 40:
        return "HIGH"
    elif pct_change > 15:
        return "MEDIUM"
    else:
        return "LOW"


def run_parameter_perturbation(
    strategy_name: str,
    base_params: dict,
    pairs: list[str],
    timerange: str,
    perturb_pcts: list[int] = [10, 20],
) -> dict:
    """
    Test sensitivity of each numeric parameter to small changes.

    For each numeric param (stoploss, ROI values, trailing values):
        Create variants at ±perturb_pct% from base
        Run backtest with each variant (other params held at base)
        Record: P&L, PF, DD for each variant

    Sensitivity classification per param:
        LOW:    ±20% changes P&L < 15% → robust
        MEDIUM: ±20% changes P&L 15-40% → normal
        HIGH:   ±10% changes P&L > 40% → fragile, likely overfitted

    Overall stability:
        PASS: no HIGH sensitivity params, avg sensitivity < 25%
        WARN: 1 HIGH sensitivity param
        FAIL: 2+ HIGH sensitivity params

    Returns: {
        per_param: {param_name: {variants: [...], sensitivity, pct_change}},
        overall: PASS/WARN/FAIL,
        stability_score: int (0-100),
        total_backtests_run: int,
    }
    """
    numeric_params = _extract_numeric_params(base_params)

    if not numeric_params:
        log.warning("No numeric parameters found to perturb for %s", strategy_name)
        return {
            "per_param": {},
            "overall": "PASS",
            "stability_score": 100,
            "total_backtests_run": 0,
        }

    log.info(
        "Running parameter perturbation for %s: %d params, perturb_pcts=%s",
        strategy_name, len(numeric_params), perturb_pcts,
    )

    # Determine the largest perturbation range to decide variant multipliers
    max_perturb = max(perturb_pcts)
    if max_perturb == 20:
        multipliers = [0.8, 0.9, 1.0, 1.1, 1.2]
    elif max_perturb == 10:
        multipliers = [0.9, 0.95, 1.0, 1.05, 1.1]
    else:
        # Generic: build multipliers from the largest perturb_pct
        step = max_perturb / 100
        multipliers = [1 - 2 * step, 1 - step, 1.0, 1 + step, 1 + 2 * step]

    # First, run the base backtest to get reference P&L
    log.info("Running base backtest for perturbation reference")
    config_path = build_backtest_config(
        strategy_name, pairs, param_overrides=base_params,
    )
    base_metrics = _run_docker_backtest(strategy_name, config_path, timerange)

    if not base_metrics:
        log.error("Base backtest failed — cannot run perturbation")
        return {
            "per_param": {},
            "overall": "FAIL",
            "stability_score": 0,
            "total_backtests_run": 1,
        }

    base_pnl = base_metrics.get("total_profit", 0.0)
    log.info("Base P&L: %.2f", base_pnl)

    per_param = {}
    total_backtests = 1  # base backtest already counted
    high_count = 0
    all_sensitivities = []

    for param_name, base_value in numeric_params.items():
        log.info("Perturbing %s (base=%.6f)", param_name, base_value)
        variants = []

        for mult in multipliers:
            variant_value = round(base_value * mult, 8)

            # Skip the exact base value (multiplier 1.0) — use cached base result
            if mult == 1.0:
                variants.append({
                    "multiplier": mult,
                    "value": variant_value,
                    "total_profit": base_pnl,
                    "profit_factor": base_metrics.get("profit_factor"),
                    "max_drawdown_pct": base_metrics.get("max_drawdown_pct"),
                    "is_base": True,
                })
                continue

            # Build param overrides with this one param changed
            variant_params = _apply_param_variant(base_params, param_name, variant_value)
            config_path = build_backtest_config(
                strategy_name, pairs, param_overrides=variant_params,
            )

            metrics = _run_docker_backtest(strategy_name, config_path, timerange)
            total_backtests += 1

            if metrics:
                variants.append({
                    "multiplier": mult,
                    "value": round(variant_value, 6),
                    "total_profit": metrics.get("total_profit", 0.0),
                    "profit_factor": metrics.get("profit_factor"),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                    "is_base": False,
                })
            else:
                variants.append({
                    "multiplier": mult,
                    "value": round(variant_value, 6),
                    "total_profit": None,
                    "profit_factor": None,
                    "max_drawdown_pct": None,
                    "is_base": False,
                    "error": True,
                })

        # Calculate max P&L deviation from base
        valid_pnls = [
            v["total_profit"] for v in variants
            if v["total_profit"] is not None and not v.get("is_base")
        ]

        if valid_pnls and abs(base_pnl) > 0.01:
            max_deviation = max(abs(pnl - base_pnl) for pnl in valid_pnls)
            pct_change = (max_deviation / abs(base_pnl)) * 100
        elif valid_pnls:
            # Base PnL near zero — use absolute deviation as pct
            max_deviation = max(abs(pnl - base_pnl) for pnl in valid_pnls)
            pct_change = max_deviation * 100  # treat $1 deviation as 100%
        else:
            pct_change = 0.0

        # Use the smallest perturbation that triggered the deviation for classification
        min_perturb = min(perturb_pcts)
        sensitivity = _classify_sensitivity(pct_change, min_perturb)

        if sensitivity == "HIGH":
            high_count += 1

        all_sensitivities.append(pct_change)

        per_param[param_name] = {
            "base_value": round(base_value, 6),
            "variants": variants,
            "sensitivity": sensitivity,
            "pct_change": round(pct_change, 1),
        }

        log.info(
            "  %s: pct_change=%.1f%%, sensitivity=%s",
            param_name, pct_change, sensitivity,
        )

    # Overall assessment
    avg_sensitivity = sum(all_sensitivities) / len(all_sensitivities) if all_sensitivities else 0
    if high_count >= 2:
        overall = "FAIL"
    elif high_count == 1:
        overall = "WARN"
    else:
        overall = "PASS"

    # Stability score (0-100)
    stability_score = 100
    stability_score -= high_count * 25
    stability_score -= max(0, int(avg_sensitivity) - 15)  # penalize high avg sensitivity
    if overall == "FAIL":
        stability_score = min(stability_score, 40)
    stability_score = max(0, min(100, stability_score))

    result = {
        "per_param": per_param,
        "overall": overall,
        "stability_score": stability_score,
        "total_backtests_run": total_backtests,
        "base_pnl": round(base_pnl, 2),
        "avg_sensitivity_pct": round(avg_sensitivity, 1),
    }

    log.info(
        "Perturbation result: overall=%s, stability=%d, backtests=%d, avg_sensitivity=%.1f%%",
        overall, stability_score, total_backtests, avg_sensitivity,
    )

    return result


# ── Main Entry Point ─────────────────────────────────────────────────────


def run_robustness_stage(
    strategy_name: str,
    trades: list[dict],
    base_params: dict,
    pairs: list[str],
    timerange: str,
    mode_config: dict,
) -> dict:
    """
    Main entry point for Stage 5: Robustness Validation.

    mode_config has:
        mc_iterations (int): 0 = skip Monte Carlo shuffle
        perturb_pcts (list[int]): [] = skip parameter perturbation

    Returns combined results from MC shuffle + perturbation.
    """
    log.info("=" * 60)
    log.info("Stage 5: Robustness Validation for %s", strategy_name)
    log.info("=" * 60)

    results = {
        "strategy": strategy_name,
        "monte_carlo": None,
        "perturbation": None,
        "combined_score": 0,
        "combined_verdict": "SKIP",
    }

    mc_iterations = mode_config.get("mc_iterations", 0)
    perturb_pcts = mode_config.get("perturb_pcts", [])

    # 5a: Monte Carlo Trade Shuffle
    if mc_iterations > 0 and trades:
        log.info("--- 5a: Monte Carlo Trade Shuffle ---")
        mc_result = run_monte_carlo_shuffle(
            trades=trades,
            starting_capital=1000.0,
            iterations=mc_iterations,
            max_skip_rate=0.15,
        )
        results["monte_carlo"] = mc_result
    elif mc_iterations > 0:
        log.warning("MC requested but no trades provided — skipping")
    else:
        log.info("Monte Carlo shuffle skipped (mc_iterations=0)")

    # 5b: Parameter Perturbation
    if perturb_pcts:
        log.info("--- 5b: Parameter Perturbation ---")
        perturb_result = run_parameter_perturbation(
            strategy_name=strategy_name,
            base_params=base_params,
            pairs=pairs,
            timerange=timerange,
            perturb_pcts=perturb_pcts,
        )
        results["perturbation"] = perturb_result
    else:
        log.info("Parameter perturbation skipped (perturb_pcts=[])")

    # Combined scoring
    mc_score = results["monte_carlo"]["mc_score"] if results["monte_carlo"] else None
    stab_score = results["perturbation"]["stability_score"] if results["perturbation"] else None

    if mc_score is not None and stab_score is not None:
        # Weighted average: MC 60%, stability 40%
        combined = int(mc_score * 0.6 + stab_score * 0.4)
    elif mc_score is not None:
        combined = mc_score
    elif stab_score is not None:
        combined = stab_score
    else:
        combined = 0

    results["combined_score"] = combined

    if combined >= 80:
        results["combined_verdict"] = "ROBUST"
    elif combined >= 60:
        results["combined_verdict"] = "ACCEPTABLE"
    elif combined > 0:
        results["combined_verdict"] = "FRAGILE"
    else:
        results["combined_verdict"] = "SKIP"

    log.info(
        "Stage 5 complete: combined_score=%d, verdict=%s",
        combined, results["combined_verdict"],
    )

    # Save results to disk
    _save_results(strategy_name, results)

    return results


def _save_results(strategy_name: str, results: dict) -> None:
    """Save robustness results to engine_results directory."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"robustness-{strategy_name}.json"
    try:
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        log.info("Results saved to %s", out_path)
    except Exception as e:
        log.error("Failed to save results: %s", e)
