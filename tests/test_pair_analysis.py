"""
Tests for the archive key per-pair analysis matches on.

run_full_backtest runs the `*Viability` wrapper when one exists, so the trade
export is keyed by the wrapper name. analyze_pairs matched the base name the
caller passed, so for any wrapper-backed strategy the comparison never matched
and the function returned "no trades in export".

That failure is one-directional: `concentration_risk` is initialised False and
classify_viability reads it only to downgrade, so missing pair data reads as
the absence of concentration rather than as a missing measurement.

Six wrappers are tracked under ft_userdata/user_data/strategies/, so this was
the normal path for most of the fleet rather than an edge case.
"""

import importlib
import json
import zipfile
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
STRATEGY = "KeltnerBounceV1"
WRAPPER = "KeltnerBounceV1Viability"

# Three pairs, with 90% of the positive profit in the top two, which is what
# the >50% concentration check at viability.py:405-409 looks for.
TRADES = [
    {"pair": "BTC/USDT", "profit_abs": 50.0},
    {"pair": "ETH/USDT", "profit_abs": 40.0},
    {"pair": "SOL/USDT", "profit_abs": 10.0},
    {"pair": "SOL/USDT", "profit_abs": -4.0},
]


@pytest.fixture(scope="module")
def viability(tmp_path_factory):
    """Redirect HOME before importing: the engine modules resolve paths off it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(tmp_path_factory.mktemp("home")))
        mp.syspath_prepend(str(FT_DIR))
        yield importlib.import_module("engine.viability")


@pytest.fixture
def backtest_metrics(tmp_path):
    """The metrics dict run_full_backtest hands to analyze_pairs."""
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
        return metrics
    return build


def _analyze(viability, metrics):
    return viability.analyze_pairs(
        STRATEGY, "20260101-20260201", "config.json", backtest_metrics=metrics,
    )


def test_wrapper_keyed_archive_is_read(viability, backtest_metrics):
    """The normal path: a wrapper exists, so the export is keyed by the wrapper name."""
    result = _analyze(viability, backtest_metrics(WRAPPER, recorded_key=WRAPPER))

    assert "error" not in result
    assert result["total_pairs_traded"] == 3
    assert [p["pair"] for p in result["top_5"]] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_wrapper_backed_concentration_is_reported(viability, backtest_metrics):
    """The measurement classify_viability downgrades on has to survive the lookup."""
    result = _analyze(viability, backtest_metrics(WRAPPER, recorded_key=WRAPPER))

    assert result["concentration_risk"] is True
    assert "BTC/USDT, ETH/USDT" in result["concentration_details"]


def test_base_keyed_archive_is_read(viability, backtest_metrics):
    """No wrapper on disk, so run_full_backtest records the base name."""
    result = _analyze(viability, backtest_metrics(STRATEGY, recorded_key=STRATEGY))

    assert "error" not in result
    assert result["total_pairs_traded"] == 3


def test_unrecorded_key_falls_back_to_the_base_name(viability, backtest_metrics):
    """A record written before _bt_strategy existed keeps the old behaviour."""
    result = _analyze(viability, backtest_metrics(STRATEGY, recorded_key=None))

    assert "error" not in result
    assert result["total_pairs_traded"] == 3


def test_unrecorded_key_does_not_guess_the_wrapper(viability, backtest_metrics):
    """Without a recorded key there is nothing to resolve, so it must not invent one."""
    result = _analyze(viability, backtest_metrics(WRAPPER, recorded_key=None))

    assert result["error"] == "no trades in export"
    assert result["concentration_risk"] is False


def test_recorded_key_absent_from_the_archive_does_not_fall_through(viability, backtest_metrics):
    """A recorded key that does not match must fail, not drop to another strategy."""
    metrics = backtest_metrics(WRAPPER, recorded_key="SomeOtherStrategyViability")
    result = _analyze(viability, metrics)

    assert result["error"] == "no trades in export"
    assert result["concentration_risk"] is False


def test_missing_result_file_reports_the_absence(viability):
    """Without a result file the stage reports rather than raising."""
    result = _analyze(viability, {})

    assert result["error"] == "no backtest result file found"
    assert result["concentration_risk"] is False
