"""
Strategy Registry — Single Source of Truth
==========================================

All strategy metadata lives here. Every other module imports from this file
instead of maintaining its own stale copy.
"""

from pathlib import Path

FT_DIR = Path.home() / "ft_userdata"
CONFIGS_DIR = FT_DIR / "user_data" / "configs"
STRATEGIES_DIR = FT_DIR / "user_data" / "strategies"
DATA_DIR = FT_DIR / "user_data" / "data"
RESULTS_DIR = FT_DIR / "engine_results"
LOGS_DIR = FT_DIR / "logs"

WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"
API_USER = "freqtrader"
API_PASS = "mastertrader"

# ── Strategy Registry ─────────────────────────────────────────────────────

STRATEGIES = {
    "SupertrendStrategy": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8084,
        "max_open_trades": 3,
        "stake_amount": "unlimited",
        "dry_run_wallet": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-SupertrendStrategy.json",
        "status": "killed",  # Killed 2026-04-17: 3 configs tested at 1m-detail, all losing.
                              # Live config: -3.23%/3.3yr PF 1.00. Original trailing: -53.98% PF 0.92.
                              # Live peak +$14.72 was regime luck (5 days of post-dip bull). Replaced by KeltnerBounceV1.
    },
    "MasterTraderV1": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8086,
        "max_open_trades": 3,
        "stake_amount": "unlimited",
        "dry_run_wallet": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-MasterTraderV1.json",
        "status": "active",
    },
    "AlligatorTrendV1": {
        "timeframe": "1d",
        "trading_mode": "spot",
        "port": 8091,
        "max_open_trades": 5,
        "stake_amount": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": [],
        "backtest_config": "backtest-AlligatorTrendV1.json",
        "status": "killed",  # Killed Apr 10: 0 trades/30d, PF 0.46 backtest, 7 trades/yr
    },
    "GaussianChannelV1": {
        "timeframe": "1d",
        "trading_mode": "spot",
        "port": 8092,
        "max_open_trades": 5,
        "stake_amount": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": [],
        "backtest_config": "backtest-GaussianChannelV1.json",
        "status": "killed",  # Killed Apr 10: ZERO trades in full-year backtest
    },
    "BearCrashShortV1": {
        "timeframe": "1h",
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "port": 8093,
        "max_open_trades": 2,
        "stake_amount": "unlimited",
        "dry_run_wallet": 22,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-BearCrashShortV1.json",
        "pair_blacklist": ["BTC/USDT:USDT"],
        "status": "active",
    },
    "BollingerBounceV1": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8094,
        "max_open_trades": 3,
        "stake_amount": "unlimited",
        "dry_run_wallet": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-BollingerBounceV1.json",
        "status": "killed",  # Killed 2026-04-17: superseded by KeltnerBounceV1.
                              # Same mean-reversion edge, but Keltner (ATR-based) outperforms Bollinger (std-based) for crypto.
                              # Idle since Apr 7 (10 days). Lab grid scan showed Keltner consistently ranked higher.
    },
    "KeltnerBounceV1": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8095,
        "max_open_trades": 3,
        "stake_amount": "unlimited",
        "dry_run_wallet": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1h"],  # BTC informative at 1h
        "backtest_config": "backtest-KeltnerBounceV1.json",
        "status": "active",  # Deployed dry-run 2026-04-16 via KeltnerBounceV1.json
    },
}


def get_active_strategies() -> dict:
    """Return only strategies with status='active'."""
    return {k: v for k, v in STRATEGIES.items() if v.get("status") == "active"}


def get_strategy(name: str) -> dict:
    """Get a strategy by name. Raises KeyError if not found."""
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy: {name}. Available: {list(STRATEGIES.keys())}")
    return STRATEGIES[name]


def get_all_timeframes() -> set[str]:
    """Return all unique timeframes needed across all active strategies."""
    tfs = set()
    for s in get_active_strategies().values():
        tfs.add(s["timeframe"])
        tfs.update(s.get("informative_tfs", []))
    return tfs


def get_spot_strategies() -> dict:
    """Return active spot strategies."""
    return {k: v for k, v in get_active_strategies().items()
            if v["trading_mode"] == "spot"}


def get_futures_strategies() -> dict:
    """Return active futures strategies."""
    return {k: v for k, v in get_active_strategies().items()
            if v["trading_mode"] == "futures"}


# ── Operating Modes ───────────────────────────────────────────────────────

MODES = {
    "fast": {
        "epochs": 300,
        "wf_windows": 3,
        "train_days": 90,
        "test_days": 30,
        "mc_iterations": 0,
        "perturb_pcts": [],
        "description": "Weekly validation — skip Monte Carlo",
    },
    "thorough": {
        "epochs": 500,
        "wf_windows": 6,
        "train_days": 90,
        "test_days": 30,
        "mc_iterations": 500,
        "perturb_pcts": [10],
        "description": "Monthly deep check",
    },
    "rigorous": {
        "epochs": 1000,
        "wf_windows": 6,
        "train_days": 120,
        "test_days": 30,
        "mc_iterations": 1000,
        "perturb_pcts": [10, 20],
        "description": "Initial / quarterly full analysis",
    },
}


def get_mode(name: str) -> dict:
    """Get mode config. Raises KeyError if not found."""
    if name not in MODES:
        raise KeyError(f"Unknown mode: {name}. Available: {list(MODES.keys())}")
    return MODES[name]
