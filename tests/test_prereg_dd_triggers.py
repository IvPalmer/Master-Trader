"""Pre-registration drawdown-trigger evaluation in the daily health report.

Why this exists: on 2026-07-29 04:19 UTC the FundingFadeV1 pre-registered
MaxDD trigger (`ff-gate-v2-review`) fired and nothing noticed. The daily report
evaluated pre-registrations only by closed-trade count and review date, so for
two days it printed "rules not yet evaluable" — true of the PF rule, which
needs 30+ trades, and irrelevant to the standing drawdown trigger sitting
right above it. A trigger that only a human re-reading the registry can notice
is the same failure mode `check_preregistrations` was written to prevent.

The fixture is FundingFadeV1's real closed-trade sequence. That makes test 1 a
cross-check against freqtrade's own engine rather than against our arithmetic:
the API reported max_drawdown 0.08595132 for exactly this sequence, so if our
implementation disagrees, ours is wrong.

    python3 -m pytest tests/test_prereg_dd_triggers.py -q
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ft_userdata"))

from strategy_health_report import (  # noqa: E402
    _closed_equity_maxdd,
    _evaluate_dd_triggers,
)

# FundingFadeV1 live, bot start 2026-04-21 → 2026-07-31. (close_date, profit_abs)
FF_TRADES_RAW = [
    ('2026-04-23 03:38:07', -0.77761487),
    ('2026-05-02 10:05:29', 0.30143428),
    ('2026-05-03 22:09:38', 0.74999109),
    ('2026-05-04 11:28:26', -0.76121796),
    ('2026-05-04 21:57:08', 0.73892861),
    ('2026-05-05 20:11:19', 0.73298326),
    ('2026-05-05 20:53:37', 0.30492129),
    ('2026-05-05 21:03:26', 1.41903255),
    ('2026-05-06 05:24:16', 0.76139397),
    ('2026-05-08 18:24:14', 0.30045048),
    ('2026-05-10 15:29:21', 0.75763523),
    ('2026-05-10 17:18:41', 1.28087216),
    ('2026-05-11 07:10:12', -0.76876468),
    ('2026-05-13 13:38:21', -0.75104457),
    ('2026-05-15 05:59:17', -0.77366611),
    ('2026-05-15 13:51:21', -0.80435025),
    ('2026-05-16 10:08:31', -0.7696291),
    ('2026-07-11 10:51:11', -0.7709638),
    ('2026-07-12 00:31:26', -0.76398527),
    ('2026-07-20 18:01:45', 0.29965625),
    ('2026-07-24 13:04:22', -0.77450204),
    ('2026-07-27 15:38:47', -0.76451265),
    ('2026-07-29 04:19:17', -0.78978703),
]

FF_STARTING_CAPITAL = 80.6534979624
# Reported by the live bot's /api/v1/profit for the sequence above.
FF_ENGINE_MAX_DRAWDOWN = 0.08595131702355367


def _trades(raw=FF_TRADES_RAW):
    return [
        {"close_date": d, "profit_abs": p, "is_open": False}
        for d, p in raw
    ]


def test_full_run_maxdd_matches_freqtrade_engine():
    """Our MaxDD must equal what freqtrade computes for the same trades."""
    dd = _closed_equity_maxdd(_trades(), FF_STARTING_CAPITAL)

    assert dd is not None
    assert dd["ratio"] == pytest.approx(FF_ENGINE_MAX_DRAWDOWN, abs=1e-6), (
        f"computed {dd['ratio']:.8f} vs engine {FF_ENGINE_MAX_DRAWDOWN:.8f} — "
        "our drawdown definition has drifted from freqtrade's"
    )
    assert dd["trough_date"].startswith("2026-07-29"), dd["trough_date"]


def test_since_basis_excludes_pre_registration_history():
    """`since` must re-baseline the peak, not just filter the trade list.

    The full-run peak is 2026-05-10, nine days before gate v2 was registered.
    Carrying that peak into a gate-v2-era measurement would attribute a
    pre-existing drawdown to the thing being measured.
    """
    dd = _closed_equity_maxdd(_trades(), FF_STARTING_CAPITAL, since="2026-05-19")

    assert dd is not None
    assert dd["ratio"] == pytest.approx(0.0432, abs=5e-4), dd["ratio"]
    assert dd["trough_date"].startswith("2026-07-29"), dd["trough_date"]
    # Equity at the boundary = starting capital + P&L banked before it.
    assert dd["peak"] == pytest.approx(82.595, abs=5e-3), dd["peak"]


def test_no_drawdown_when_only_winners():
    dd = _closed_equity_maxdd(
        _trades([("2026-06-01 00:00:00", 1.0), ("2026-06-02 00:00:00", 2.0)]),
        100.0,
    )
    assert dd is not None
    assert dd["ratio"] == 0.0
    assert dd["trough_date"] is None


def test_empty_trades_returns_none():
    assert _closed_equity_maxdd([], 100.0) is None
    assert _closed_equity_maxdd(_trades(), 0.0) is None


def _entry(threshold, basis="both"):
    return {
        "id": "ff-gate-v2-review",
        "registered": "2026-05-19",
        "triggers": [{
            "id": "maxdd-rollback",
            "metric": "max_drawdown_pct",
            "basis": basis,
            "op": ">",
            "threshold": threshold,
            "action": "Rollback gate v2",
        }],
    }


def test_breached_trigger_is_reported_with_worst_point_date():
    """The date reported is the WORST point, not the threshold-crossing point.

    Those differ: on the full-run reading FF crossed 3.60% back on 2026-05-16,
    while the deepest drawdown is 2026-07-29. `_closed_equity_maxdd` computes
    the latter and the report says "worst point" — this pins that wording so
    nobody later reads it as "the trigger fired on this date".
    """
    lines = _evaluate_dd_triggers(
        _entry(3.60), _trades(), FF_STARTING_CAPITAL
    )
    blob = "\n".join(lines)

    assert "BREACHED" in blob, blob
    assert "maxdd-rollback" in blob, blob
    assert "Rollback gate v2" in blob, blob
    assert "worst point 2026-07-29" in blob, blob


def test_unbreached_trigger_reports_headroom_not_silence():
    """A trigger that has NOT fired must still print.

    Silence is indistinguishable from "not evaluated", which is precisely how
    the 2026-07-29 breach went unseen.
    """
    lines = _evaluate_dd_triggers(
        _entry(25.0), _trades(), FF_STARTING_CAPITAL
    )
    blob = "\n".join(lines)

    assert lines, "unbreached trigger produced no output at all"
    assert "BREACHED" not in blob, blob
    assert "8.60" in blob, f"current value not shown: {blob}"


def test_both_basis_uses_the_worse_of_the_two():
    """`basis: both` is the conservative reading for an ambiguous rule.

    3.60% is under the full-run 8.60% but also under the since-registered
    4.32%; a threshold between them (say 5%) must still breach on full-run.
    """
    blob = "\n".join(_evaluate_dd_triggers(_entry(5.0), _trades(), FF_STARTING_CAPITAL))
    assert "BREACHED" in blob, blob

    # Above both readings → no breach.
    blob = "\n".join(_evaluate_dd_triggers(_entry(9.0), _trades(), FF_STARTING_CAPITAL))
    assert "BREACHED" not in blob, blob


def test_since_basis_alone_does_not_breach_on_full_run_drawdown():
    """Guards against silently widening a scoped rule into a global one."""
    blob = "\n".join(
        _evaluate_dd_triggers(_entry(5.0, basis="since_registered"),
                              _trades(), FF_STARTING_CAPITAL)
    )
    assert "BREACHED" not in blob, (
        "since_registered basis (4.32%) must not fire on a 5% threshold — "
        f"full-run drawdown leaked into a scoped trigger: {blob}"
    )


def test_entry_without_triggers_is_silent():
    assert _evaluate_dd_triggers({"id": "x"}, _trades(), FF_STARTING_CAPITAL) == []


def test_malformed_trigger_does_not_raise():
    entry = {"id": "x", "triggers": [{"metric": "unknown_metric", "threshold": 1}]}
    lines = _evaluate_dd_triggers(entry, _trades(), FF_STARTING_CAPITAL)
    assert all("BREACHED" not in ln for ln in lines)


# --- wiring -----------------------------------------------------------------
# _evaluate_dd_triggers being correct is worth nothing if check_preregistrations
# never calls it. That gap IS the bug: the trigger was always computable, just
# never computed.


def test_check_preregistrations_actually_evaluates_triggers(monkeypatch, tmp_path):
    import strategy_health_report as shr

    registry = {
        "preregistrations": [{
            "id": "ff-gate-v2-review",
            "bot": "FundingFadeV1",
            "status": "open",
            "registered": "2026-05-19",
            "review_by": "2026-08-17",
            "min_closed_trades": 30,
            "rules": ["Rollback gate v2 if account MaxDD > 3.60%"],
            "triggers": [{
                "id": "maxdd-registry-3.60",
                "metric": "max_drawdown_pct",
                "basis": "both",
                "op": ">",
                "threshold": 3.6,
                "action": "Rollback gate v2",
            }],
        }]
    }
    reg_file = tmp_path / "preregistrations.json"
    reg_file.write_text(json.dumps(registry))

    monkeypatch.setattr(shr, "PREREG_FILE", reg_file)
    monkeypatch.setattr(shr, "BOTS", {"FundingFadeV1": {"port": 8096}})
    monkeypatch.setattr(shr, "get_trades_from_api", lambda port, **kw: _trades())
    monkeypatch.setattr(
        shr, "fetch_json",
        lambda port, endpoint, **kw: {"starting_capital": FF_STARTING_CAPITAL}
        if endpoint == "balance" else None,
    )

    blob = "\n".join(shr.check_preregistrations())

    assert "BREACHED" in blob, (
        "check_preregistrations did not evaluate the drawdown trigger — this is "
        f"exactly the 2026-07-29 blind spot regressing:\n{blob}"
    )
    # The old count-based line must survive alongside it, not be replaced.
    assert "rules not yet evaluable" in blob, blob


def test_triggers_report_when_bot_is_unreachable(monkeypatch, tmp_path):
    """An unreachable bot must say so, never look like a passing check."""
    import strategy_health_report as shr

    registry = {"preregistrations": [{
        "id": "x", "bot": "FundingFadeV1", "status": "open",
        "registered": "2026-05-19",
        "triggers": [{
            "id": "t", "metric": "max_drawdown_pct", "op": ">",
            "threshold": 3.6, "action": "a",
        }],
    }]}
    reg_file = tmp_path / "preregistrations.json"
    reg_file.write_text(json.dumps(registry))

    monkeypatch.setattr(shr, "PREREG_FILE", reg_file)
    monkeypatch.setattr(shr, "BOTS", {"FundingFadeV1": {"port": 8096}})
    monkeypatch.setattr(shr, "get_trades_from_api", lambda port, **kw: None)

    blob = "\n".join(shr.check_preregistrations())
    assert "NOT evaluated" in blob, blob
