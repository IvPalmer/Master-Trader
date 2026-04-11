"""
Backtest Engine v2 — Unified backtesting, optimization, and validation pipeline.

Modules:
    registry        Strategy registry (single source of truth)
    parsers         Freqtrade output parsing (shared)
    config_builder  Dynamic config generation
    data            Stage 1: Data preparation
    calibration     Stage 2: Live vs backtest calibration
    viability       Stage 3: Viability screening
    walk_forward    Stage 4: Walk-forward optimization
    hyperopt        Stage 4: Multi-loss hyperopt tournament
    monte_carlo     Stage 5: Robustness validation
    reporting       Stage 6: Report generation
"""

__version__ = "2.0.0"
