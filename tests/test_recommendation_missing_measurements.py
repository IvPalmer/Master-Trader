"""
Tests for how missing measurements reach the engine's recommendation (#23, #86, #30).

Rule: a measurement that was deliberately not requested is advisory; a
measurement that was requested but is missing (stage crashed, no trades, stage
never ran, error) blocks the permissive verdicts OPTIMIZE and KEEP, which then
fall through to MONITOR.

classify_recommendation used to read any absent mc_score or calibration score
as a pass, so a robustness stage that crashed produced the same OPTIMIZE/KEEP as
one that was never asked to run. The robustness fixtures below are the four
shapes that occur in committed ft_userdata/engine_results/ artifacts, plus the
skip markers run_robustness_stage now records.
"""

import copy
import importlib
import json
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
RESULTS = FT_DIR / "engine_results"

ALL_STAGES = ["data", "calibration", "viability", "walk_forward", "robustness", "reporting"]


def _load(rel: str) -> dict:
    return json.loads((RESULTS / rel).read_text())


# The four committed robustness shapes.
ROB_ERROR = _load("20260417_rigorous/KeltnerBounceV1_robustness.json")
ROB_DEAD_SKIP = _load("20260412_fast/MasterTraderV1_robustness.json")
ROB_LEGACY_NULL_MC = _load("20260412_fast/SupertrendStrategy_robustness.json")
# Calibration stage's own error shape: placeholder score 0 plus error.
CAL_STAGE_ERROR = _load("20260411_fast/BearCrashShortV1_calibration.json")


def _rob_marked(mc_skip_reason, mc_score=None):
    """The shape run_robustness_stage now writes."""
    return {
        "strategy": "X",
        "monte_carlo": None if mc_score is None else {"mc_score": mc_score},
        "perturbation": None,
        "combined_score": mc_score or 0,
        "combined_verdict": "SKIP",
        "mc_skip_reason": mc_skip_reason,
        "perturbation_skip_reason": "disabled",
    }


def _base(consensus=True, stages=ALL_STAGES):
    """VIABLE, calibration 80, walk-forward with or without consensus params."""
    results = {
        "viability": {"classification": "VIABLE"},
        "calibration": {"score": 80},
        "walk_forward": {
            "consensus": {
                "consensus_params": {"stoploss": -0.1} if consensus else None,
                "windows_profitable": 3,
                "windows_total": 4,
            }
        },
    }
    if stages is not None:
        results["stages_requested"] = list(stages)
    return results


@pytest.fixture(scope="module")
def reporting(tmp_path_factory):
    """Redirect HOME before importing: the engine modules resolve paths off it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(tmp_path_factory.mktemp("home")))
        mp.syspath_prepend(str(FT_DIR))
        yield importlib.import_module("engine.reporting")


@pytest.fixture(scope="module")
def engine(reporting):
    return importlib.import_module("backtest_engine")


def test_committed_fixtures_are_the_expected_shapes():
    assert set(ROB_ERROR) == {"error"}
    assert ROB_DEAD_SKIP["skipped"] is True and "DEAD" in ROB_DEAD_SKIP["reason"]
    assert ROB_LEGACY_NULL_MC["monte_carlo"] is None
    assert "mc_skip_reason" not in ROB_LEGACY_NULL_MC
    assert CAL_STAGE_ERROR["score"] == 0 and CAL_STAGE_ERROR["error"]


# ── Robustness: requested but missing blocks OPTIMIZE/KEEP ─────────────


MISSING_ROBUSTNESS = {
    "stage-error": ROB_ERROR,
    "mc-no-trades": _rob_marked("no_trades"),
    "legacy-no-marker": ROB_LEGACY_NULL_MC,
}


@pytest.mark.parametrize("consensus", [True, False], ids=["consensus", "no-consensus"])
@pytest.mark.parametrize("rob", list(MISSING_ROBUSTNESS.values()), ids=list(MISSING_ROBUSTNESS))
def test_requested_but_missing_mc_is_monitor(reporting, rob, consensus):
    results = _base(consensus=consensus)
    results["robustness"] = copy.deepcopy(rob)
    assert reporting.classify_recommendation(results) == "MONITOR"


@pytest.mark.parametrize("consensus", [True, False], ids=["consensus", "no-consensus"])
def test_robustness_absent_when_requested_is_monitor(reporting, consensus):
    results = _base(consensus=consensus)
    assert "robustness" in results["stages_requested"]
    assert reporting.classify_recommendation(results) == "MONITOR"


@pytest.mark.parametrize("consensus", [True, False], ids=["consensus", "no-consensus"])
def test_robustness_absent_without_stamp_is_monitor(reporting, consensus):
    """No evidence it was left out on purpose: treat as missing."""
    results = _base(consensus=consensus, stages=None)
    assert reporting.classify_recommendation(results) == "MONITOR"


# ── Robustness: deliberately not requested stays advisory ──────────────


def test_mc_disabled_with_consensus_is_optimize(reporting):
    results = _base()
    results["robustness"] = _rob_marked("disabled")
    assert reporting.classify_recommendation(results) == "OPTIMIZE"


def test_mc_disabled_without_consensus_is_keep(reporting):
    results = _base(consensus=False)
    results["robustness"] = _rob_marked("disabled")
    assert reporting.classify_recommendation(results) == "KEEP"


def test_robustness_not_requested_is_advisory(reporting):
    stages = [s for s in ALL_STAGES if s != "robustness"]
    assert reporting.classify_recommendation(_base(stages=stages)) == "OPTIMIZE"
    assert reporting.classify_recommendation(_base(consensus=False, stages=stages)) == "KEEP"


# ── Robustness: measured scores ────────────────────────────────────────


@pytest.mark.parametrize(
    "mc_score, expected",
    [(85, "OPTIMIZE"), (60, "OPTIMIZE"), (50, "MONITOR"), (20, "KILL")],
)
def test_measured_mc_score(reporting, mc_score, expected):
    results = _base()
    results["robustness"] = _rob_marked(None, mc_score=mc_score)
    assert reporting.classify_recommendation(results) == expected


def test_measured_mc_85_without_consensus_is_keep(reporting):
    results = _base(consensus=False)
    results["robustness"] = _rob_marked(None, mc_score=85)
    assert reporting.classify_recommendation(results) == "KEEP"


def test_dead_skip_shape_still_kills(reporting):
    results = _base()
    results["viability"] = {"classification": "DEAD"}
    results["calibration"] = {"score": 60}
    results["robustness"] = copy.deepcopy(ROB_DEAD_SKIP)
    assert reporting.classify_recommendation(results) == "KILL"


# ── Calibration: same rule ─────────────────────────────────────────────


def _with_mc_85(results):
    results["robustness"] = _rob_marked(None, mc_score=85)
    return results


MISSING_CALIBRATION = {
    "engine-exception": {"error": "boom"},
    "stage-error-placeholder-score": CAL_STAGE_ERROR,
}


@pytest.mark.parametrize("consensus", [True, False], ids=["consensus", "no-consensus"])
@pytest.mark.parametrize("cal", list(MISSING_CALIBRATION.values()), ids=list(MISSING_CALIBRATION))
def test_requested_but_errored_calibration_is_monitor(reporting, cal, consensus):
    results = _with_mc_85(_base(consensus=consensus))
    results["calibration"] = copy.deepcopy(cal)
    assert reporting.classify_recommendation(results) == "MONITOR"


@pytest.mark.parametrize("consensus", [True, False], ids=["consensus", "no-consensus"])
def test_calibration_absent_when_requested_is_monitor(reporting, consensus):
    results = _with_mc_85(_base(consensus=consensus))
    del results["calibration"]
    assert reporting.classify_recommendation(results) == "MONITOR"


def test_calibration_absent_without_stamp_is_monitor(reporting):
    results = _with_mc_85(_base(stages=None))
    del results["calibration"]
    assert reporting.classify_recommendation(results) == "MONITOR"


def test_calibration_not_requested_is_advisory(reporting):
    stages = [s for s in ALL_STAGES if s != "calibration"]
    results = _with_mc_85(_base(stages=stages))
    del results["calibration"]
    assert reporting.classify_recommendation(results) == "OPTIMIZE"
    results = _with_mc_85(_base(consensus=False, stages=stages))
    del results["calibration"]
    assert reporting.classify_recommendation(results) == "KEEP"


@pytest.mark.parametrize(
    "score, expected",
    [(85, "OPTIMIZE"), (70, "OPTIMIZE"), (60, "MONITOR"), (30, "INVESTIGATE")],
)
def test_measured_calibration_score(reporting, score, expected):
    results = _with_mc_85(_base())
    results["calibration"] = {"score": score}
    assert reporting.classify_recommendation(results) == expected


def test_errored_calibration_placeholder_is_not_investigate(reporting):
    """score 0 next to an error is a placeholder, not a divergence measurement."""
    results = _with_mc_85(_base())
    results["calibration"] = copy.deepcopy(CAL_STAGE_ERROR)
    assert reporting.classify_recommendation(results) != "INVESTIGATE"


# ── Plumbing: backtest_engine stamps stages_requested ──────────────────


def test_stamp_copies_meta_stages_to_each_strategy(engine):
    results = {
        "meta": {"stages_requested": ["calibration", "viability", "reporting"]},
        "strategies": {"A": {}, "B": {"calibration": {"score": 80}}},
    }
    engine._stamp_stages_requested(results)
    for strat in results["strategies"].values():
        assert strat["stages_requested"] == ["calibration", "viability", "reporting"]


def test_stamp_keeps_an_existing_stamp(engine):
    results = {
        "meta": {"stages_requested": ["viability"]},
        "strategies": {"A": {"stages_requested": ["calibration"]}},
    }
    engine._stamp_stages_requested(results)
    assert results["strategies"]["A"]["stages_requested"] == ["calibration"]


def test_stamp_without_meta_leaves_results_unstamped(engine):
    results = {"strategies": {"A": {}}}
    engine._stamp_stages_requested(results)
    assert "stages_requested" not in results["strategies"]["A"]


def test_committed_run_without_robustness_is_judged_by_its_requested_stages(engine, reporting):
    """A committed calibration+viability run: robustness was never requested."""
    run = json.loads(
        (RESULTS / "20260412_105710_fast" / "pipeline_results.json").read_text()
    )
    assert "robustness" not in run["meta"]["stages_requested"]
    engine._stamp_stages_requested(run)
    strat = run["strategies"]["SupertrendStrategy"]
    assert "robustness" not in strat
    assert reporting._mc_ok(strat, None) is True


# ── monte_carlo: the stage records why each half is absent ─────────────


@pytest.fixture
def mc(reporting, tmp_path, monkeypatch):
    module = importlib.import_module("engine.monte_carlo")
    monkeypatch.setattr(module, "RESULTS_DIR", tmp_path / "engine_results")

    def no_backtests(*args, **kwargs):
        raise AssertionError("no backtest may run in these tests")

    monkeypatch.setattr(module, "build_backtest_config", no_backtests)
    monkeypatch.setattr(module, "_run_docker_backtest", no_backtests)
    monkeypatch.setattr(module.subprocess, "run", no_backtests)
    return module


TRADES = [{"profit_abs": 5.0 if i % 3 else -3.0} for i in range(30)]


def _run(mc, trades, mode_config, base_params=None):
    return mc.run_robustness_stage(
        strategy_name="X",
        trades=trades,
        base_params=base_params or {},
        pairs=["BTC/USDT"],
        timerange="20260101-20260201",
        mode_config=mode_config,
    )


def test_fast_mode_marks_both_halves_disabled(mc):
    result = _run(mc, TRADES, {"mc_iterations": 0, "perturb_pcts": []})
    assert result["mc_skip_reason"] == "disabled"
    assert result["perturbation_skip_reason"] == "disabled"


def test_mc_requested_without_trades_marks_no_trades(mc):
    result = _run(mc, [], {"mc_iterations": 50, "perturb_pcts": []})
    assert result["monte_carlo"] is None
    assert result["mc_skip_reason"] == "no_trades"


def test_mc_ran_marks_none(mc):
    result = _run(mc, TRADES, {"mc_iterations": 50, "perturb_pcts": []})
    assert result["monte_carlo"] is not None
    assert result["mc_skip_reason"] is None


def test_perturbation_skip_reason_is_carried(mc):
    result = _run(mc, TRADES, {"mc_iterations": 0, "perturb_pcts": [10]})
    assert result["perturbation"]["overall"] == "SKIP"
    assert result["perturbation_skip_reason"] == "no numeric parameters to perturb"


def test_stage_output_feeds_classification(mc, reporting):
    """End to end: the stage's own output, not a hand-built marker."""
    fast = _base()
    fast["robustness"] = _run(mc, TRADES, {"mc_iterations": 0, "perturb_pcts": []})
    assert reporting.classify_recommendation(fast) == "OPTIMIZE"

    no_trades = _base()
    no_trades["robustness"] = _run(mc, [], {"mc_iterations": 50, "perturb_pcts": []})
    assert reporting.classify_recommendation(no_trades) == "MONITOR"


# ── viability: failed pair analysis cannot yield VIABLE ────────────────


@pytest.fixture(scope="module")
def viability(reporting):
    return importlib.import_module("engine.viability")


VIABLE_METRICS = {
    "total_trades": 200,
    "profit_factor": 2.0,
    "max_drawdown_pct": 5.0,
    "total_profit": 500.0,
    "sharpe": 2.0,
    "win_rate": 60.0,
}
CLEAN = {"passed": True}
NO_RECURSIVE_WARNING = {"warning": False}


def test_assessed_pairs_without_concentration_are_viable(viability):
    pair_analysis = {"concentration_risk": False, "concentration_details": "", "pairs": [1, 2, 3]}
    classification, _ = viability.classify_viability(
        VIABLE_METRICS, CLEAN, NO_RECURSIVE_WARNING, pair_analysis
    )
    assert classification == "VIABLE"


@pytest.mark.parametrize(
    "error", ["no trades in export", "no backtest result file found", "Bad zip file"]
)
def test_unassessed_pair_analysis_is_not_viable(viability, error):
    pair_analysis = {"concentration_risk": False, "concentration_details": "", "error": error}
    classification, reasons = viability.classify_viability(
        VIABLE_METRICS, CLEAN, NO_RECURSIVE_WARNING, pair_analysis
    )
    assert classification == "MARGINAL"
    assert any(f"Pair concentration not assessed: {error}" in r for r in reasons)


def test_unassessed_pair_analysis_does_not_mask_dead(viability):
    pair_analysis = {"concentration_risk": False, "error": "no trades in export"}
    metrics = dict(VIABLE_METRICS, profit_factor=0.3)
    classification, _ = viability.classify_viability(
        metrics, CLEAN, NO_RECURSIVE_WARNING, pair_analysis
    )
    assert classification == "DEAD"


# ── Legacy fast-mode artifacts keep their verdicts on --report ─────────


@pytest.mark.parametrize("consensus,expected", [(True, "OPTIMIZE"), (False, "KEEP")])
def test_legacy_fast_run_without_marker_is_disabled_not_missing(reporting, consensus, expected):
    """Review finding: re-reporting an older fast run flipped KEEP/OPTIMIZE to
    MONITOR because its robustness predates mc_skip_reason."""
    results = _base(consensus=consensus)
    results["robustness"] = copy.deepcopy(ROB_LEGACY_NULL_MC)
    results["run_mode"] = "fast"
    assert reporting.classify_recommendation(results) == expected


@pytest.mark.parametrize("rob", [ROB_LEGACY_NULL_MC, ROB_ERROR], ids=["legacy", "error"])
def test_legacy_rigorous_run_without_marker_is_still_missing(reporting, rob):
    results = _base()
    results["robustness"] = copy.deepcopy(rob)
    results["run_mode"] = "rigorous"
    assert reporting.classify_recommendation(results) == "MONITOR"


def test_legacy_fast_run_that_crashed_is_still_missing(reporting):
    results = _base()
    results["robustness"] = copy.deepcopy(ROB_ERROR)
    results["run_mode"] = "fast"
    assert reporting.classify_recommendation(results) == "MONITOR"


def test_stamp_copies_meta_mode_to_each_strategy(engine):
    results = {"meta": {"mode": "fast", "stages_requested": ["robustness"]},
               "strategies": {"A": {}}}
    engine._stamp_stages_requested(results)
    assert results["strategies"]["A"]["run_mode"] == "fast"

