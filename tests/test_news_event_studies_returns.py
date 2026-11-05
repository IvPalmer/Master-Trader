"""Part C Phase 2 returns, criteria and verdict (#229): hand-computed cases (O2-O4, O13-O15).

    python3 -m pytest tests/test_news_event_studies_returns.py -q
"""
import json
import sys
from fractions import Fraction
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


def test_missing_entry_candle_does_not_hide_unresolved_exit():
    # Entry candle absent, the +30 min and +4 h exits present, and no candle from the scheduled
    # +24 h exit through its 72 h resumption window. O4: `unresolved` at any horizon beats `missing`.
    r = full(o5=None, last=1444)
    res = nr.evaluate(EVENT, series(r), series(full()), "short", "hyperliquid")
    assert res["status"] == "unresolved"
    assert [res["horizons"][h]["exit_status"] for h in ("30m", "4h", "24h")] == ["ok", "ok", "unresolved"]
    assert all(res["horizons"][h]["net"] is None for h in nr.HORIZONS_MS)
    res = nr.evaluate(EVENT, series(full(o5=None)), series(full()), "short", "hyperliquid")
    assert res["status"] == "missing"
    # Study level: any unresolved event makes the study INCONCLUSIVE, whatever the 20 others show.
    passing = [_res("x%02d" % i, T0 + i, 0.01) for i in range(20)]
    gone = nr.evaluate(EVENT, series(r), series(full()), "short", "hyperliquid")
    assert nr.verdict(_counts(20), passing)[0] == "PASS"
    got, reasons = nr.verdict(_counts(21), passing + [gone])
    assert got == "INCONCLUSIVE" and "1 unresolved post-entry event(s)" in reasons


def test_exact_break_even_cannot_pass():
    # 100 -> 99.71 short on Hyperliquid: gross 0.0029 equals 2 x (4.5 + 10) bps, so net is exactly 0.
    # "median net return > 0" fails, and concentration fails because the sum is not > 0.
    r = full(o245="99.71")
    results = [nr.evaluate({**EVENT, "announcement_id": "binance:%d" % i, "token": "T%d" % i},
                           series(r), series(full()), "short", "hyperliquid") for i in range(20)]
    assert all(e["horizons"]["4h"]["net"] == 0 for e in results)
    c = nr.criteria(nr.announcements(results, "4h"))
    assert c["n"] == 20 and c["median"] == 0 and c["half_medians"] == [0, 0] and c["sum"] == 0
    assert c["passes"] == {"n": True, "median": False, "halves": False, "concentration": False}
    got, reasons = nr.verdict(_counts(20), results)
    assert got == "FAIL"
    assert {"criterion failed: median", "criterion failed: halves",
            "criterion failed: concentration"} <= set(reasons)
    # The exact values survive storage as strings, so a recomputed resolution agrees.
    stored = json.loads(json.dumps(results, default=str))
    assert {e["horizons"]["4h"]["net"] for e in stored} == {"0"}
    assert nr.verdict(_counts(20), stored)[0] == "FAIL"


def test_net_is_exact_from_price_strings():
    assert nr.net("100", "98", "long", "hyperliquid", 10) == Fraction("-0.0229")
    assert nr.net("100", "99.71", "short", "hyperliquid", 10) == 0
    assert nr.net("3", "1", "long", "binance_spot", 25) == Fraction(-2, 3) - Fraction("0.0065")
    # A tenth, two tenths and minus three tenths average to exactly zero.
    res = [_res("binance:1", T0, v) for v in ("1/10", "2/10", "-3/10")]
    assert nr.announcements(res, "4h") == [(T0, "binance:1", 0)]


@pytest.mark.parametrize("eps,passes", [(0, False), (Fraction(1, 10 ** 20), True)])
def test_concentration_threshold_is_exact(eps, passes):
    # Top decile (2 of 20) holds 60% - eps of a sum of 1: "less than 60%" is decided exactly,
    # not against the binary float 0.6 (which is just below 3/5).
    values = [(Fraction(3, 5) - eps) / 2] * 2 + [(Fraction(2, 5) + eps) / 18] * 18
    c = nr.criteria([(T0 + i, "x%02d" % i, v) for i, v in enumerate(values)])
    assert c["top_decile_share"] == Fraction(3, 5) - eps and c["passes"]["concentration"] is passes


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
    """The horizon's own exit carries `status` (per-horizon eligibility, A4)."""
    return {"announcement_id": aid, "t0_ms": t0, "token": aid, "status": status, "leaked": leaked,
            "horizons": {h: {"net": net, "net_stress": net, "exit_status": status}}}


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


# --- A4 (operator directive 2026-11-05): per-horizon eligibility and estimates ----------

M = 31 * 24 * H          # one month apart is enough to land in different calendar months


def test_unresolved_24h_keeps_valid_4h_return():
    # Codex 2026-11-05: an unresolved 24 h exit used to drop the event's valid 30 m and 4 h returns.
    res = nr.evaluate(EVENT, series(full(o245="98", last=1444)), series(full()), "short", "hyperliquid")
    assert res["status"] == "unresolved" and res["horizons"]["24h"]["exit_status"] == "unresolved"
    anns = nr.announcements([res], "4h")
    assert [a[1] for a in anns] == ["binance:1"] and anns[0][2] == res["horizons"]["4h"]["net"]
    assert nr.announcements([res], "24h") == []


def test_untested_leak_is_out_of_primary_but_in_leak_included():
    res = [_res("a", T0, 0.01), _res("n", T0 + 1, 0.02, leaked=None)]
    assert [a[1] for a in nr.announcements(res, "4h")] == ["a"]
    assert [a[1] for a in nr.announcements(res, "4h", include_leaked=True)] == ["a", "n"]


def test_no_halt_set_drops_halted_exits():
    res = [_res("a", T0, 0.01), _res("h", T0 + 1, 0.02, "halted")]
    assert [a[1] for a in nr.announcements(res, "4h")] == ["a", "h"]
    assert [a[1] for a in nr.announcements(res, "4h", allow_halted=False)] == ["a"]


def test_mae_short_never_negative():
    r = rows({off: "100" for off in range(0, 10)}, highs={off: "90" for off in range(0, 10)})
    assert nr.mae_short(r, BASE, BASE + 5 * MIN, "100") == 0.0


def test_block_bootstrap_needs_two_months_and_is_deterministic():
    one = [(T0 + i, "x%d" % i, 0.01 * i) for i in range(5)]
    assert nr.block_bootstrap_mean_ci(one) == (None, None)
    two = one + [(T0 + M + i, "y%d" % i, -0.01 * i) for i in range(5)]
    a, b = nr.block_bootstrap_mean_ci(two), nr.block_bootstrap_mean_ci(two)
    assert a == b and a[0] <= a[1]
    assert nr.CI_LEVEL == 1 - Fraction(5, 300)


def _months(values_by_month, missing=0, status="ok"):
    out = []
    for m, vals in enumerate(values_by_month):
        out += [_res("m%d_%d" % (m, i), T0 + m * M + i, v) for i, v in enumerate(vals)]
    out += [_res("gone%d" % i, T0 + i, None, "missing") for i in range(missing)]
    return out


def test_classify_edge_no_edge_and_not_determinable():
    up = [[0.02, 0.03], [0.01, 0.04], [0.03, 0.02], [0.02, 0.05], [0.04, 0.01], [0.03, 0.03]]
    assert nr.classify(_months(up))[0] == "EDGE (proxy)"
    down = [[-a, -b] for a, b in up]
    assert nr.classify(_months(down))[0] == "NO EDGE"
    mixed = [[0.02, 0.03], [-0.03, -0.02], [0.04, 0.0], [-0.04, -0.01], [0.01, 0.02], [-0.02, -0.01]]
    got, reasons = nr.classify(_months(mixed))
    assert got == "NOT DETERMINABLE" and "spans zero" in reasons[0]
    assert nr.classify(_months([[0.02]]))[0] == "NOT DETERMINABLE"     # one month


def test_missingness_counts_partial_and_phase1_tokens():
    # Codex round 2: one +2% token and one missing token per announcement used to look complete.
    res = []
    for m in range(6):
        t = T0 + m * M
        res += [_res("a%d" % m, t, 0.02 + 0.001 * m), _res("a%d" % m, t, None, "missing")]
    miss = nr.missingness(res, extra_missing=[(T0, "a0"), (T0 + 7 * M, "p1")])
    assert miss == {"token_events": 8, "announcements_fully_missing": 1,
                    "announcements_partly_missing": 6}
    got, reasons = nr.classify(res)
    assert got == "EDGE (proxy)" and "6 missing token-event(s)" in reasons[-1]


def test_tipping_point_is_where_the_bound_crosses_zero():
    up = [[0.02, 0.03], [0.01, 0.04], [0.03, 0.02], [0.02, 0.05], [0.04, 0.01], [0.03, 0.03]]
    res = _months(up, missing=4)
    assert nr.classify(res)[0] == "EDGE (proxy)"
    tip = nr.tipping_point(res, "EDGE (proxy)")
    v = tip["value"]
    assert -1 < v < 0.01 and "reverses if the missing events average below" in tip["note"]
    parts = nr.announcement_parts(res, key="net_stress")
    draws = nr._draws([(t0, s_ / (a + m), Fraction(m, a + m)) for t0, _i, s_, a, m in parts])
    assert nr._interval(draws, v + 1e-6)[0] > 0 >= nr._interval(draws, v - 1e-6)[0]
    assert nr.tipping_point(_months(up), "EDGE (proxy)") is None        # nothing missing
    assert nr.tipping_point(res, "NOT DETERMINABLE") is None


def _half_missing(value):
    res = []
    for m in range(6):
        t = T0 + m * M
        res += [_res("a%d" % m, t, value), _res("a%d" % m, t, None, "missing")]
    return res


def test_tipping_point_direction_for_both_classes():
    # Codex round 3: each announcement = (observed + v) / 2, so the bound crosses 0 at v = -observed.
    edge = nr.tipping_point(_half_missing(0.02), "EDGE (proxy)")
    assert edge["value"] == pytest.approx(-0.02, abs=1e-9) and "below" in edge["note"]
    none = nr.tipping_point(_half_missing(-0.02), "NO EDGE")
    assert none["value"] == pytest.approx(0.02, abs=1e-9) and "above" in none["note"]


def test_tipping_point_reports_unbracketed_ranges():
    huge = nr.tipping_point(_half_missing(20.0), "EDGE (proxy)")
    assert huge["value"] is None and "holds even if every missing event returns -1000%" in huge["note"]
    deep = nr.tipping_point(_half_missing(-20.0), "NO EDGE")
    assert deep["value"] is None and "holds even if every missing event returns +1000%" in deep["note"]
    odd = nr.tipping_point(_half_missing(-20.0), "EDGE (proxy)")
    assert odd["value"] is None and "no crossing" in odd["note"]
