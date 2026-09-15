"""
Tests for the trade list the Monte Carlo stage runs on.

backtest_engine read `_trades` off the viability result and nothing ever wrote
that key, so run_robustness_stage was handed an empty list and skipped the
shuffle on every run.

Two things decide whether the trades come back, and a fixture that gets either
of them wrong passes while the pipeline still recovers nothing:

  * `run_pipeline` hands over the whole viability stage result, so the recorded
    path sits at `["metrics"]["_result_file"]`, not at the top level.
  * `run_full_backtest` runs the `*Viability` wrapper when one exists, so the
    archive is keyed by the wrapper name, not the base strategy name.
"""

import importlib
import json
import zipfile
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
STRATEGY = "KeltnerBounceV1"
WRAPPER = "KeltnerBounceV1Viability"

TRADES = [
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


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    """Redirect HOME before importing: the engine modules resolve paths off it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(tmp_path_factory.mktemp("home")))
        mp.syspath_prepend(str(FT_DIR))
        yield importlib.import_module("backtest_engine")


@pytest.fixture
def viability_result(tmp_path):
    """A viability stage result shaped the way run_viability_stage saves one."""
    def build(archive_key: str, recorded_key: str | None = None) -> dict:
        path = tmp_path / f"backtest-result-{archive_key}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "backtest-result-2026-01-01_00-00-00.json",
                json.dumps({"strategy": {archive_key: {"trades": TRADES}}}),
            )
        metrics = {"total_trades": len(TRADES), "_result_file": str(path)}
        if recorded_key is not None:
            metrics["_bt_strategy"] = recorded_key
        return {
            "strategy": STRATEGY,
            "classification": "VIABLE",
            "reasons": [],
            "lookahead": {"passed": True},
            "recursive": {"warning": False},
            "metrics": metrics,
            "pair_analysis": {},
        }
    return build


def test_wrapper_backed_trades_are_recovered(engine, viability_result):
    """The normal path: a wrapper exists, so the archive is keyed by the wrapper name."""
    via_data = viability_result(WRAPPER, recorded_key=WRAPPER)
    trades = engine._viability_trades(via_data)
    assert [t["profit_abs"] for t in trades] == [5.0, -2.0]


def test_base_strategy_trades_are_recovered(engine, viability_result):
    """No wrapper on disk, so run_full_backtest records the base name."""
    via_data = viability_result(STRATEGY, recorded_key=STRATEGY)
    trades = engine._viability_trades(via_data)
    assert [t["profit_abs"] for t in trades] == [5.0, -2.0]


def test_flat_result_yields_no_trades(engine, viability_result):
    """run_pipeline passes the stage result, so a top-level path is not the real shape."""
    via_data = viability_result(WRAPPER, recorded_key=WRAPPER)
    flat = dict(via_data["metrics"])
    assert engine._viability_trades(flat) == []


def test_unrecorded_strategy_key_yields_no_trades(engine, viability_result):
    """Results saved before the key was recorded must skip, not guess a strategy."""
    via_data = viability_result(WRAPPER, recorded_key=None)
    assert engine._viability_trades(via_data) == []


def test_missing_result_file_yields_no_trades(engine):
    """Without a result file the stage must skip rather than raise."""
    assert engine._viability_trades({}) == []
    assert engine._viability_trades({"metrics": {}}) == []


def test_stale_result_file_yields_no_trades(engine):
    """Saved results carry absolute paths from the machine that produced them."""
    stale = "/Users/nobody/ft_userdata/user_data/backtest_results/gone.zip"
    via_data = {"metrics": {"_result_file": stale, "_bt_strategy": WRAPPER}}
    assert engine._viability_trades(via_data) == []


def test_robustness_stage_produces_a_score(engine, viability_result):
    """run_robustness_stage skips the shuffle on an empty list, so a score proves it ran."""
    from engine.monte_carlo import run_robustness_stage

    trades = engine._viability_trades(viability_result(WRAPPER, recorded_key=WRAPPER))
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
