"""
Dynamic Config Builder
======================

Generates temporary Freqtrade config files for backtesting and hyperopt runs.
Handles spot vs futures, pair injection, param overrides, etc.
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Optional

from .registry import FT_DIR, CONFIGS_DIR, get_strategy

log = logging.getLogger("engine.config_builder")

# Base config template (backtest mode)
BASE_CONFIG = {
    "dry_run": True,
    "dry_run_wallet": 1000,
    "trading_mode": "spot",
    "margin_mode": "",
    "stake_currency": "USDT",
    "stake_amount": "unlimited",
    "tradable_balance_ratio": 0.99,
    "fiat_display_currency": "",
    "max_open_trades": 5,
    "amount_reserve_percent": 0.05,
    "entry_pricing": {
        "price_side": "other",
        "use_order_book": True,
        "order_book_top": 1,
    },
    "exit_pricing": {
        "price_side": "other",
        "use_order_book": True,
        "order_book_top": 1,
    },
    "exchange": {
        "name": "binance",
        "key": "",
        "secret": "",
        "pair_whitelist": [],
        "pair_blacklist": [],
    },
    "pairlists": [{"method": "StaticPairList"}],
}


def build_backtest_config(
    strategy_name: str,
    pairs: list[str],
    stake_amount: Optional[float] = None,
    max_open_trades: Optional[int] = None,
    param_overrides: Optional[dict] = None,
) -> str:
    """
    Generate a backtest config for a strategy and write to disk.

    Args:
        strategy_name: Strategy class name
        pairs: Pair whitelist
        stake_amount: Override stake amount (None = use registry)
        max_open_trades: Override max trades (None = use registry)
        param_overrides: Dict of params to inject (stoploss, minimal_roi, trailing_*)

    Returns:
        Container-internal path to the generated config file.
    """
    strat = get_strategy(strategy_name)
    config = json.loads(json.dumps(BASE_CONFIG))  # deep copy

    # Strategy-specific settings
    config["trading_mode"] = strat["trading_mode"]
    if strat["trading_mode"] == "futures":
        config["margin_mode"] = strat.get("margin_mode", "isolated")
    config["max_open_trades"] = max_open_trades or strat["max_open_trades"]
    config["stake_amount"] = stake_amount or strat["stake_amount"]
    config["bot_name"] = f"Backtest-{strategy_name}"

    # Pairs
    config["exchange"]["pair_whitelist"] = pairs
    if strat.get("pair_blacklist"):
        config["exchange"]["pair_blacklist"] = strat["pair_blacklist"]

    # For futures, append :USDT to pairs if not already present
    if strat["trading_mode"] == "futures":
        config["exchange"]["pair_whitelist"] = [
            p if ":USDT" in p else f"{p}:USDT"
            for p in pairs
        ]

    # Parameter overrides (from hyperopt results)
    if param_overrides:
        if "stoploss" in param_overrides:
            config["stoploss"] = param_overrides["stoploss"]
        if "minimal_roi" in param_overrides:
            config["minimal_roi"] = param_overrides["minimal_roi"]
        for key in ["trailing_stop", "trailing_stop_positive",
                     "trailing_stop_positive_offset", "trailing_only_offset_is_reached"]:
            if key in param_overrides:
                config[key] = param_overrides[key]

    # Write to disk
    out_path = CONFIGS_DIR / f"backtest-{strategy_name}.json"
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    log.info("Built config: %s (%d pairs, %s mode)",
             out_path.name, len(pairs), strat["trading_mode"])

    return f"/freqtrade/user_data/configs/backtest-{strategy_name}.json"


def build_hyperopt_config(
    strategy_name: str,
    pairs: list[str],
) -> str:
    """
    Generate a hyperopt config. Same as backtest but named differently
    to avoid overwriting mid-pipeline.

    Returns container-internal path.
    """
    strat = get_strategy(strategy_name)
    config = json.loads(json.dumps(BASE_CONFIG))

    config["trading_mode"] = strat["trading_mode"]
    if strat["trading_mode"] == "futures":
        config["margin_mode"] = strat.get("margin_mode", "isolated")
    config["max_open_trades"] = strat["max_open_trades"]
    config["stake_amount"] = strat["stake_amount"]
    config["bot_name"] = f"Hyperopt-{strategy_name}"
    config["exchange"]["pair_whitelist"] = pairs
    if strat.get("pair_blacklist"):
        config["exchange"]["pair_blacklist"] = strat["pair_blacklist"]

    if strat["trading_mode"] == "futures":
        config["exchange"]["pair_whitelist"] = [
            p if ":USDT" in p else f"{p}:USDT"
            for p in pairs
        ]

    out_path = CONFIGS_DIR / f"hyperopt-{strategy_name}.json"
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    return f"/freqtrade/user_data/configs/hyperopt-{strategy_name}.json"


def build_calibration_config(
    strategy_name: str,
    pairs: list[str],
    stake_amount: float,
    max_open_trades: int,
) -> str:
    """
    Generate a calibration config that exactly mirrors live settings.

    Returns container-internal path.
    """
    strat = get_strategy(strategy_name)
    config = json.loads(json.dumps(BASE_CONFIG))

    config["trading_mode"] = strat["trading_mode"]
    if strat["trading_mode"] == "futures":
        config["margin_mode"] = strat.get("margin_mode", "isolated")
    config["max_open_trades"] = max_open_trades
    config["stake_amount"] = stake_amount
    config["bot_name"] = f"Calibrate-{strategy_name}"
    config["exchange"]["pair_whitelist"] = pairs

    if strat["trading_mode"] == "futures":
        config["exchange"]["pair_whitelist"] = [
            p if ":USDT" in p else f"{p}:USDT"
            for p in pairs
        ]

    out_path = CONFIGS_DIR / f"calibrate-{strategy_name}.json"
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    return f"/freqtrade/user_data/configs/calibrate-{strategy_name}.json"
