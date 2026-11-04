"""Part C Phase 2 returns, criteria and verdict (#229): hand-computed cases (O2-O4, O13-O15).

    python3 -m pytest tests/test_news_event_studies_returns.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_util as nu  # noqa: E402
import nes_returns as nr  # noqa: E402

T0 = 1709294430000          # 2024-03-01T12:00:30Z; entry candle = BASE + 5 min
MIN, H = 60_000, 3_600_000
BASE = T0 - T0 % MIN


def rows(closes, highs=None):
    highs = highs or {}
    return {BASE + off * MIN: [c, highs.get(off, c), c, c] for off, c in closes.items()}


def full(last=1445 + 10, **override):
    """Every minute from -15 to `last` at close "100"; override offsets via o<offset>=close or None."""
    closes = {off: "100" for off in range(-15, last + 1)}
    for k, v in override.items():
        off = int(k[1:].replace("m", "-"))
        if v is None:
            closes.pop(off, None)
        else:
            closes[off] = v
    return rows(closes)


def series(r, absent=()):
    return {"rows": r, "absent_dates": list(absent)}


EVENT = {"announcement_id": "binance:1", "t0_ms": T0, "token": "AAA", "kind": "full_delist"}


def test_price_at_uses_close_of_containing_minute():
    r = rows({5: "100"})
    assert nr.price_at(r, T0 + 300_000) == "100"
    assert nr.price_at(r, T0 + 360_000) is None


def test_net_long_short_and_costs():
    assert nr.net("100", "98", "long", "hyperliquid", 10) == pytest.approx(-0.0229, abs=1e-12)
    assert nr.net("100", "98", "short", "hyperliquid", 10) == pytest.approx(0.0171, abs=1e-12)
    assert nr.net("100", "98", "long", "binance_spot", 10) == pytest.approx(-0.0235, abs=1e-12)
    assert nr.net("100", "98", "short", "hyperliquid", 25) == pytest.approx(0.0141, abs=1e-12)


def test_fade_is_negated_long_gross_minus_costs():
    r = full(o245="98")
    long = nr.evaluate(EVENT, series(r), series(full()), "long", "hyperliquid")
    fade = nr.evaluate(EVENT, series(r), series(full()), "short", "hyperliquid")
    assert fade["horizons"]["4h"]["net"] == pytest.approx(-long["horizons"]["4h"]["gross"] - 0.0029,
                                                          abs=1e-12)


@pytest.mark.parametrize("later,flag", [("102", False), ("102.01", True), ("98", False),
                                        ("97.99", True), (None, None)])
def test_leak_strictly_above_two_percent(later, flag):
    closes = {-10: "100"}
    if later is not None:
        closes[-2] = later
    assert nr.leaked(rows(closes), T0) is flag


def test_halt_exit_first_candle_within_72h():
    sched = T0 + 300_000 + 4 * H                          # candle BASE + 245 min
    assert nr.exit_at(rows({245: "99"}), sched) == ("ok", "99", BASE + 245 * MIN)
    assert nr.exit_at(rows({305: "97"}), sched) == ("halted", "97", BASE + 305 * MIN)
    edge = 245 + 72 * 60
    assert nr.exit_at(rows({edge: "96"}), sched) == ("halted", "96", BASE + edge * MIN)
    assert nr.exit_at(rows({edge + 1: "96"}), sched) == ("unresolved", None, None)


def test_archive_hole_is_missing_only_with_a_resumption_candle():
    sched = T0 + 300_000 + 4 * H
    day = nu.utc_date(BASE + 245 * MIN)
    assert nr.exit_at(rows({305: "97"}), sched, [day]) == ("missing", None, None)
    assert nr.exit_at(rows({}), sched, [day]) == ("unresolved", None, None)


def test_missing_leak_or_entry_candle_makes_event_missing():
    for gone in ("om10", "om2", "o5"):
        res = nr.evaluate(EVENT, series(full(**{gone: None})), series(full()), "short", "hyperliquid")
        assert res["status"] == "missing", gone


def test_halted_and_unresolved_event_status():
    res = nr.evaluate(EVENT, series(full(o245=None)), series(full()), "short", "hyperliquid")
    assert res["status"] == "halted" and res["horizons"]["4h"]["exit_status"] == "halted"
    res = nr.evaluate(EVENT, series(full(last=1444)), series(full()), "short", "hyperliquid")
    assert res["status"] == "unresolved"
    assert res["horizons"]["30m"]["exit_status"] == "ok" and res["horizons"]["24h"]["net"] is None


def test_status_order_unresolved_beats_missing_hole():
    r = full(last=1444, o245=None)
    day = nu.utc_date(BASE + 245 * MIN)
    res = nr.evaluate(EVENT, series(r, [day]), series(full()), "short", "hyperliquid")
    assert res["status"] == "unresolved"
    res = nr.evaluate(EVENT, series(full(o245=None), [day]), series(full()), "short", "hyperliquid")
    assert res["status"] == "missing"


def test_missing_leak_candle_does_not_hide_unresolved_exit():
    res = nr.evaluate(EVENT, series(full(om10=None, last=1444)), series(full()), "short", "hyperliquid")
    assert res["status"] == "unresolved"
    res = nr.evaluate(EVENT, series(full(om10=None)), series(full()), "short", "hyperliquid")
    assert res["status"] == "missing"


def test_mae_short_from_highs_none_on_gap():
    r = rows({5: "100", 6: "100", 7: "100"}, highs={6: "101", 7: "104"})
    assert nr.mae_short(r, T0 + 300_000, BASE + 7 * MIN, "100") == pytest.approx(0.04)
    r = rows({5: "100", 7: "100"}, highs={7: "104"})
    assert nr.mae_short(r, T0 + 300_000, BASE + 7 * MIN, "100") is None


def test_btc_adjusted_net():
    res = nr.evaluate(EVENT, series(full(o245="98")), series(full(o245="99")), "long", "hyperliquid")
    assert res["horizons"]["4h"]["btc_adj_net"] == pytest.approx(-0.0129, abs=1e-12)
    res = nr.evaluate(EVENT, series(full(o245="98")), series(full(o245=None)), "long", "hyperliquid")
    assert res["horizons"]["4h"]["btc_adj_net"] is None


def test_mae_only_for_shorts_and_t60_entry():
    r = full(o1="99", o31="98")
    short = nr.evaluate(EVENT, series(r), series(full()), "short", "hyperliquid")
    long = nr.evaluate(EVENT, series(r), series(full()), "long", "hyperliquid")
    assert short["horizons"]["30m"]["mae"] == pytest.approx(0.0) and long["horizons"]["30m"]["mae"] is None
    assert long["t60"]["30m"] == pytest.approx(98 / 99 - 1 - 0.0029, abs=1e-12)


def _res(aid, t0, net, status="ok", leaked=False, h="4h"):
    return {"announcement_id": aid, "t0_ms": t0, "token": aid, "status": status, "leaked": leaked,
            "horizons": {h: {"net": net}}}


def test_announcement_is_mean_of_its_tokens():
    res = [_res("binance:1", T0, 0.01), _res("binance:1", T0, -0.03)]
    assert nr.announcements(res, "4h") == [(T0, "binance:1", pytest.approx(-0.01))]


def test_leaked_dropped_from_primary_kept_in_sensitivity():
    res = [_res("a", T0, 0.01), _res("b", T0 + 1, 0.05, leaked=True), _res("c", T0 + 2, 0.02, "missing")]
    assert [a[1] for a in nr.announcements(res, "4h")] == ["a"]
    assert [a[1] for a in nr.announcements(res, "4h", include_leaked=True)] == ["a", "b"]


def test_halves_by_date_order():
    anns = [(T0 + i, "x%d" % i, v) for i, v in enumerate([0.01, -0.02, 0.03, 0.04, -0.05])]
    c = nr.criteria(anns)
    assert c["half_medians"] == [pytest.approx(-0.005), pytest.approx(0.03)]
    assert c["n"] == 5 and c["median"] == pytest.approx(0.01)


def test_top_decile_ceil_and_nonpositive_sum():
    anns = [(T0 + i, "x%02d" % i, v) for i, v in enumerate([0.05, 0.04] + [0.001] * 18)]
    c = nr.criteria(anns)
    assert c["top_decile_share"] == pytest.approx(0.09 / 0.108) and c["passes"]["concentration"] is False
    c = nr.criteria([(T0 + i, "x%02d" % i, 0.01) for i in range(20)])
    assert c["top_decile_share"] == pytest.approx(0.1) and c["passes"]["concentration"] is True
    c = nr.criteria([(T0 + i, "x%02d" % i, v) for i, v in enumerate([0.01, -0.02])])
    assert c["passes"]["concentration"] is False and c["top_decile_share"] is None


def test_coverage_counts_shortfall_in_both_terms():
    counts = {"candidates": 40, "unknown": 5, "missing": 3, "harvest_shortfall": 2}
    res = [_res("a%d" % i, T0 + i, 0.01) for i in range(39)] + [_res("m", T0, None, "missing")]
    assert nr.coverage(counts, res) == pytest.approx(11 / 50)


def _counts(n, **kw):
    return {"candidates": n, "unknown": 0, "missing": 0, "harvest_shortfall": 0,
            "harvest_complete": True, **kw}


CASES = {
    "harvest_incomplete": (_counts(20, harvest_complete=False), [0.01] * 20, 0),
    "one_unresolved": (_counts(21), [0.01] * 20, 1),
    "coverage_0.22": (_counts(39, unknown=11), [0.01] * 20, 0),
    "n_19": (_counts(19), [0.01] * 19, 0),
    "all_pass": (_counts(20), [0.01] * 20, 0),
    "halves_fail": (_counts(20), [-0.01] * 10 + [0.03] * 10, 0),
}


@pytest.mark.parametrize("case,verdict", [("harvest_incomplete", "INCONCLUSIVE-by-data"),
                                          ("one_unresolved", "INCONCLUSIVE"),
                                          ("coverage_0.22", "INCONCLUSIVE-by-data"),
                                          ("n_19", "INCONCLUSIVE-by-data"), ("all_pass", "PASS"),
                                          ("halves_fail", "FAIL")])
def test_verdict_order(case, verdict):
    counts, values, unresolved = CASES[case]
    res = [_res("x%02d" % i, T0 + i, v) for i, v in enumerate(values)]
    res += [_res("u%d" % i, T0, None, "unresolved") for i in range(unresolved)]
    got, reasons = nr.verdict(counts, res)
    assert got == verdict and reasons


def test_verdict_collects_every_reason():
    res = [_res("x%02d" % i, T0 + i, 0.01) for i in range(5)] + [_res("u", T0, None, "unresolved")]
    got, reasons = nr.verdict(_counts(6, harvest_complete=False), res)
    assert got == "INCONCLUSIVE-by-data" and len(reasons) >= 3


def test_bootstrap_deterministic():
    vals = [0.01, -0.02, 0.03, 0.005, -0.001, 0.02]
    a, b = nr.bootstrap_median_ci(vals), nr.bootstrap_median_ci(vals)
    assert a == b and a[0] <= a[1]
    assert nr.bootstrap_median_ci([]) == (None, None)


def test_constants_match_prereg():
    reg = json.loads((ROOT / "ft_userdata" / "preregistrations.json").read_text(encoding="utf-8"))
    ids = ("binance-delisting-reaction-2026-11", "upbit-krw-listing-reaction-2026-11",
           "upbit-krw-listing-fade-2026-11")
    for f in [e["frozen"] for e in reg["preregistrations"] if e.get("id") in ids]:
        assert f["entry_offset_s"] * 1000 == nr.ENTRY_OFFSET_MS
        assert f["descriptive_entry_offset_s"] * 1000 == nr.T60_OFFSET_MS
        assert [s * 1000 for s in f["horizons_s"]] == list(nr.HORIZONS_MS.values())
        assert f["primary_horizon_s"] * 1000 == nr.HORIZONS_MS[nr.PRIMARY]
        assert f["fee_bps_per_side"] == nr.FEE_BPS
        assert (f["slippage_bps_per_side"], f["stress_slippage_bps_per_side"]) == (nr.SLIP_BPS, nr.STRESS_SLIP_BPS)
        assert str(nr.LEAK_GT) == f["leak_abs_drift_gt"]
        assert [s * 1000 for s in f["leak_window_s"]] == [nr.LEAK_FROM_MS, nr.LEAK_TO_MS]
        assert f["halt_resume_window_s"] * 1000 == nr.HALT_WINDOW_MS
        assert (f["min_announcements"], f["top_decile_share_lt"], f["coverage_gate_gt"]) == \
            (nr.MIN_ANN, nr.TOP_DECILE_LT, nr.COVERAGE_GT)
        assert (f["bootstrap_resamples"], f["bootstrap_seed"]) == (nr.BOOT_N, nr.BOOT_SEED)
