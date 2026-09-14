"""
Tests for the trade list the Monte Carlo stage runs on.

backtest_engine read `_trades` off the viability result and nothing ever wrote
that key, so run_robustness_stage was handed an empty list and skipped the
shuffle on every run.
"""

import importlib
import json
import zipfile
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
STRATEGY = "KeltnerBounceV1"


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    """Redirect HOME before importing: the engine modules resolve paths off it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(tmp_path_factory.mktemp("home")))
        mp.syspath_prepend(str(FT_DIR))
        yield importlib.import_module("backtest_engine")


@pytest.fixture
def result_file(tmp_path):
    """A backtest-result zip shaped the way viability records one."""
    trades = [
        {
            "pair": "BTC/USDT",
            "open_date": "2026-01-01 00:00:00",
            "close_date": "2026-01-01 04:00:00",
            "open_rate": 100.0,
            "close_rate": 105.0,
            "profit_abs": 5.0,
        },
        {
            "pair": "ETH/USDT",
            "open_date": "2026-01-02 00:00:00",
            "close_date": "2026-01-02 04:00:00",
            "open_rate": 50.0,
            "close_rate": 48.0,
            "profit_abs": -2.0,
        },
    ]
    path = tmp_path / "backtest-result-2026-01-01_00-00-00.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "backtest-result-2026-01-01_00-00-00.json",
            json.dumps({"strategy": {STRATEGY: {"trades": trades}}}),
        )
    return path


def test_viability_trades_are_recovered(engine, result_file):
    """The shuffle needs profit_abs per trade, and viability records only the result file."""
    trades = engine._viability_trades({"_result_file": str(result_file)}, STRATEGY)
    assert [t["profit_abs"] for t in trades] == [5.0, -2.0]


def test_missing_result_file_yields_no_trades(engine):
    """Without a result file the stage must skip rather than raise."""
    assert engine._viability_trades({}, STRATEGY) == []


def test_stale_result_file_yields_no_trades(engine):
    """Saved results carry absolute paths from the machine that produced them."""
    stale = "/Users/nobody/ft_userdata/user_data/backtest_results/gone.zip"
    assert engine._viability_trades({"_result_file": stale}, STRATEGY) == []


def test_robustness_stage_produces_a_score(engine, result_file):
    """run_robustness_stage skips the shuffle on an empty list, so a score proves it ran."""
    from engine.monte_carlo import run_robustness_stage

    trades = engine._viability_trades({"_result_file": str(result_file)}, STRATEGY)
    result = run_robustness_stage(
        strategy_name=STRATEGY,
        trades=trades,
        base_params={},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        mode_config={"mc_iterations": 50, "perturb_pcts": []},
    )

    assert result["monte_carlo"] is not None
    assert result["monte_carlo"]["mc_score"] is not None
