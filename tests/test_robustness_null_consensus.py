"""
Tests for the robustness stage when walk-forward reached no consensus (#86).

Walk-forward writes `consensus_params: None` when no consensus is reached.
backtest_engine read it with `.get(key, {})`, which returns the None, and the
perturbation stage then raised on `"stoploss" in None`. With that fixed, an
empty parameter set reached the perturbation early return, which reported
PASS/100 for zero backtests and carried the combined verdict to ROBUST.
"""

import importlib
import json
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
# A committed rigorous run in which walk-forward reached no consensus.
NO_CONSENSUS_WF = (
    FT_DIR / "engine_results" / "20260417_rigorous" / "KeltnerBounceV1_walk_forward.json"
)
MODE_CONFIG = {"mc_iterations": 1000, "perturb_pcts": [10, 20]}


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    """Redirect HOME before importing: the engine modules resolve paths off it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(tmp_path_factory.mktemp("home")))
        mp.syspath_prepend(str(FT_DIR))
        yield importlib.import_module("backtest_engine")


@pytest.fixture
def mc(engine, tmp_path, monkeypatch):
    """monte_carlo with its results dir in tmp and the backtest runner disarmed."""
    module = importlib.import_module("engine.monte_carlo")
    monkeypatch.setattr(module, "RESULTS_DIR", tmp_path / "engine_results")

    def no_backtests(*args, **kwargs):
        raise AssertionError("no backtest may run when there is nothing to perturb")

    monkeypatch.setattr(module, "build_backtest_config", no_backtests)
    monkeypatch.setattr(module, "_run_docker_backtest", no_backtests)
    monkeypatch.setattr(module.subprocess, "run", no_backtests)
    return module


# ── backtest_engine: consensus params at the call site ──────────────────


def test_committed_no_consensus_run_has_null_params():
    """The fixture must still be the shape that crashed, or the next test proves nothing."""
    wf = json.loads(NO_CONSENSUS_WF.read_text())
    assert "consensus_params" in wf["consensus"]
    assert wf["consensus"]["consensus_params"] is None


def test_null_consensus_params_resolve_to_empty(engine):
    wf = json.loads(NO_CONSENSUS_WF.read_text())
    assert engine._consensus_base_params(wf) == {}


@pytest.mark.parametrize(
    "wf_data",
    [
        {},
        {"consensus": None},
        {"consensus": {}},
        {"consensus": {"consensus_params": None}},
        None,
    ],
    ids=["no-consensus-key", "null-consensus", "empty-consensus", "null-params", "null-wf"],
)
def test_missing_or_null_consensus_resolves_to_empty(engine, wf_data):
    assert engine._consensus_base_params(wf_data) == {}


def test_present_consensus_params_pass_through(engine):
    params = {"stoploss": -0.08, "minimal_roi": {"0": 0.05}}
    wf = {"consensus": {"consensus_params": params}}
    assert engine._consensus_base_params(wf) == params


# ── monte_carlo: nothing to perturb is not a pass ───────────────────────


def test_empty_params_perturbation_reports_skip(mc):
    result = mc.run_parameter_perturbation(
        strategy_name="KeltnerBounceV1",
        base_params={},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        perturb_pcts=[10, 20],
    )
    assert result["overall"] == "SKIP"
    assert result["stability_score"] is None
    assert result["total_backtests_run"] == 0
    assert result["per_param"] == {}


def test_non_numeric_params_perturbation_reports_skip(mc):
    """Params with nothing numeric to perturb are the same as no params."""
    result = mc.run_parameter_perturbation(
        strategy_name="KeltnerBounceV1",
        base_params={"buy_signal": "ema", "minimal_roi": {"0": "x"}},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        perturb_pcts=[10, 20],
    )
    assert result["overall"] == "SKIP"
    assert result["stability_score"] is None


def test_robustness_stage_with_nothing_to_assess_is_not_robust(mc):
    """No trades and no params: neither half ran, so the stage must not read ROBUST/100."""
    result = mc.run_robustness_stage(
        strategy_name="KeltnerBounceV1",
        trades=[],
        base_params={},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        mode_config=MODE_CONFIG,
    )
    assert result["monte_carlo"] is None
    assert result["perturbation"]["overall"] == "SKIP"
    assert result["combined_score"] == 0
    assert result["combined_verdict"] == "SKIP"


def test_robustness_stage_with_mc_only_scores_from_mc(mc):
    """MC ran, perturbation skipped: the combined score is the MC score alone."""
    trades = [
        {"profit_abs": 5.0 if i % 3 else -3.0, "close_date": f"2026-01-{i + 1:02d}"}
        for i in range(30)
    ]
    result = mc.run_robustness_stage(
        strategy_name="KeltnerBounceV1",
        trades=trades,
        base_params={},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        mode_config={"mc_iterations": 50, "perturb_pcts": [10, 20]},
    )
    assert result["monte_carlo"] is not None
    assert result["perturbation"]["stability_score"] is None
    assert result["combined_score"] == result["monte_carlo"]["mc_score"]


def test_report_card_shows_skip_not_pass(engine):
    reporting = importlib.import_module("engine.reporting")
    results = {
        "robustness": {
            "monte_carlo": None,
            "perturbation": {
                "per_param": {},
                "overall": "SKIP",
                "stability_score": None,
                "total_backtests_run": 0,
            },
        }
    }
    card = reporting.build_report_card("KeltnerBounceV1", results)
    line = next(l for l in card.splitlines() if "Perturbation:" in l)
    assert "SKIP" in line
    assert "PASS" not in line
    assert "100" not in line


# ── control: numeric params still reach the backtests ───────────────────


def test_numeric_params_still_run_perturbation(mc, monkeypatch):
    calls = []

    def fake_config(strategy_name, pairs, param_overrides=None):
        calls.append(dict(param_overrides))
        return "config.json"

    def fake_backtest(strategy_name, config_path, timerange):
        return {"total_profit": 100.0, "profit_factor": 1.5, "max_drawdown_pct": 5.0}

    monkeypatch.setattr(mc, "build_backtest_config", fake_config)
    monkeypatch.setattr(mc, "_run_docker_backtest", fake_backtest)

    result = mc.run_parameter_perturbation(
        strategy_name="KeltnerBounceV1",
        base_params={"stoploss": -0.1},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        perturb_pcts=[10, 20],
    )
    # One base run plus four variants (x0.8, x0.9, x1.1, x1.2) of the one param.
    assert result["total_backtests_run"] == 5
    assert len(calls) == 5
    assert set(result["per_param"]) == {"stoploss"}
    assert result["overall"] == "PASS"
    assert result["stability_score"] == 100
