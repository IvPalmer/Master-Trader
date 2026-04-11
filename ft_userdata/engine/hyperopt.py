"""
Multi-Loss Hyperopt Tournament — Stage 4a
==========================================

Runs Freqtrade hyperopt with multiple loss functions (Sharpe, Sortino, Calmar)
and returns parsed results for consensus scoring in walk_forward.py.

CRITICAL: Always uses --disable-param-export to prevent the auto-export bug
where Freqtrade writes a <Strategy>.json that silently overrides .py params.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .registry import FT_DIR, get_strategy
from .config_builder import build_hyperopt_config
from .parsers import parse_hyperopt_output

log = logging.getLogger("engine.hyperopt")

LOSS_FUNCTIONS = [
    "SharpeHyperOptLossDaily",
    "SortinoHyperOptLossDaily",
    "CalmarHyperOptLoss",
]

# Hyperopt can be slow — 30 min timeout
HYPEROPT_TIMEOUT = 1800


def run_hyperopt(
    strategy_name: str,
    timerange: str,
    config_path: str,
    epochs: int = 500,
    loss_function: str = "SharpeHyperOptLossDaily",
    min_trades: int = 10,
) -> Optional[dict]:
    """
    Run hyperopt on a time window with a single loss function.

    Args:
        strategy_name: Strategy class name (must exist in registry).
        timerange: Freqtrade timerange format, e.g. "20250601-20250901".
        config_path: Container-internal path to config file
                     (e.g. "/freqtrade/user_data/configs/hyperopt-SupertrendStrategy.json").
        epochs: Number of hyperopt epochs.
        loss_function: Loss function class name.
        min_trades: Minimum trades required for a valid result.

    Returns:
        Dict with {best_profit_pct, best_trades, params: {stoploss, minimal_roi, trailing_*}}
        or None if hyperopt failed or produced no valid result.
    """
    strat = get_strategy(strategy_name)
    image = strat["image"]

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data",
        image, "hyperopt",
        "--strategy", strategy_name,
        "--config", config_path,
        "--hyperopt-loss", loss_function,
        "--spaces", "roi", "stoploss", "trailing",
        "--epochs", str(epochs),
        "--timerange", timerange,
        "--print-json",
        "--disable-param-export",
        "-j", "1",
        "--min-trades", str(min_trades),
    ]

    log.info(
        "Running hyperopt: strategy=%s loss=%s timerange=%s epochs=%d",
        strategy_name, loss_function, timerange, epochs,
    )

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=HYPEROPT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error(
            "Hyperopt timed out after %ds: strategy=%s loss=%s timerange=%s",
            HYPEROPT_TIMEOUT, strategy_name, loss_function, timerange,
        )
        return None

    if result.returncode != 0:
        log.error(
            "Hyperopt failed (rc=%d): strategy=%s loss=%s\nstderr: %s",
            result.returncode, strategy_name, loss_function,
            result.stderr[-500:] if result.stderr else "(empty)",
        )
        return None

    combined_output = result.stdout + "\n" + result.stderr
    parsed = parse_hyperopt_output(combined_output)

    if parsed is None:
        log.warning(
            "Could not parse hyperopt output: strategy=%s loss=%s timerange=%s",
            strategy_name, loss_function, timerange,
        )
        return None

    # Tag result with metadata
    parsed["loss_function"] = loss_function
    parsed["timerange"] = timerange
    parsed["strategy"] = strategy_name
    parsed["epochs"] = epochs

    log.info(
        "Hyperopt result: strategy=%s loss=%s profit=%.2f%% trades=%d",
        strategy_name, loss_function,
        parsed.get("best_profit_pct", 0),
        parsed.get("best_trades", 0),
    )

    return parsed


def run_multi_loss_hyperopt(
    strategy_name: str,
    timerange: str,
    config_path: str,
    epochs: int = 500,
    min_trades: int = 10,
) -> dict:
    """
    Run hyperopt with all 3 loss functions and return results keyed by loss name.

    Args:
        strategy_name: Strategy class name.
        timerange: Freqtrade timerange format.
        config_path: Container-internal path to hyperopt config.
        epochs: Number of hyperopt epochs per loss function.
        min_trades: Minimum trades for valid result.

    Returns:
        Dict mapping loss function name to hyperopt result (or None if that run failed).
        Example: {
            "SharpeHyperOptLossDaily": {best_profit_pct: 5.2, params: {...}},
            "SortinoHyperOptLossDaily": None,  # failed
            "CalmarHyperOptLoss": {best_profit_pct: 3.1, params: {...}},
        }
    """
    results = {}

    for loss_fn in LOSS_FUNCTIONS:
        log.info(
            "Multi-loss tournament [%d/%d]: %s for %s",
            LOSS_FUNCTIONS.index(loss_fn) + 1, len(LOSS_FUNCTIONS),
            loss_fn, strategy_name,
        )
        results[loss_fn] = run_hyperopt(
            strategy_name=strategy_name,
            timerange=timerange,
            config_path=config_path,
            epochs=epochs,
            loss_function=loss_fn,
            min_trades=min_trades,
        )

    successful = sum(1 for r in results.values() if r is not None)
    log.info(
        "Multi-loss tournament complete: strategy=%s timerange=%s — %d/%d succeeded",
        strategy_name, timerange, successful, len(LOSS_FUNCTIONS),
    )

    return results
