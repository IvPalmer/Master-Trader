"""Upbit fade forward monitor (#229): the A4 resolution at 95% and the single decision.

    python3 -m pytest tests/test_upbit_fade_forward_resolve.py -q
"""
from datetime import datetime, timezone
from decimal import Decimal as D
from fractions import Fraction

import pytest

import uff_fakes as f
import uff_common as uc
import uff_monitor as um
import uff_report as ur
import uff_venues as uv
import nes_returns as nr

FEE = D("0.00045")


def month_ms(year, month, day=10):
    return int(datetime(year, month, day, 6, tzinfo=timezone.utc).timestamp() * 1000)


def put(led, i, t0, net, token=None, funding=True, comparable=True, final=True, start=True,
        seen=False):
    """A finished event whose 24 h net return is `net` (entry 100 at 1, funding 0).
    comparable=False fails a requirement (unverified timing); start=False has no body start
    (start_unknown); seen adds a descriptive KRW-market first-seen record."""
    tok = token or "T%d" % i
    eid, aid = "upbit:n%d:%s" % (i, tok), "upbit:n%d" % i
    iso = uc.iso
    led.append({"rid": "event:" + eid, "kind": "event", "event_id": eid, "announcement_id": aid,
                "notice_id": "n%d" % i, "token": tok, "title": "t", "t0_ms": t0, "t0": iso(t0),
                "published_at": iso(t0), "received_at": iso(t0 + 39_000),
                "detected_ms": t0 + 40_000, "timing": "verified" if comparable else "unverified",
                "trading_start_ms": t0 + f.H if start else None, "start_unknown": not start,
                "began_before_notice": False, "krw_prior": False,
                "binance_prior": {"found": False}, "pre_epoch": False})
    led.append({"rid": "hl:" + eid, "kind": "hl", "status": "eligible", "coin": tok,
                "sz_decimals": 0})
    led.append({"rid": "binance:" + eid, "kind": "binance", "market_pre_t0": True,
                "leaked": False})
    led.append({"rid": "bprior:" + eid, "kind": "bprior", "found": False})
    led.append({"rid": "entry:" + eid, "kind": "entry", "status": "timely", "coin": tok,
                "q": "100", "vwap": "1", "obs_ms": t0 + 5 * f.MIN})
    if seen:
        led.append({"rid": "krwseen:" + eid, "kind": "krwseen", "event_id": eid,
                    "krw_market_first_seen_ms": t0 + 2 * f.H})
    if not final:
        return eid
    x = (1 - FEE - D(str(net))) / (1 + FEE)
    led.append({"rid": "exit:" + eid, "kind": "exit", "status": "ok", "q": "100",
                "vwap": str(x), "obs_ms": t0 + 5 * f.MIN + f.D})
    led.append({"rid": "funding:" + eid, "kind": "funding",
                "status": "complete" if funding else "missing",
                "cashflow": "0" if funding else None})
    return eid


def monitor(tmp_path):
    clock = f.Clock(month_ms(2026, 11))
    return um.Monitor(tmp_path / "data", tmp_path / "none.sqlite", None, None, clock.wall_ms,
                      clock.sleep), clock


def months(n, values):
    """`values` spread over n consecutive months from 2026-11."""
    out = []
    for k, v in enumerate(values):
        y, m = divmod(10 + k % n, 12)
        out.append((month_ms(2026 + y, m + 1, 1 + k // n), v))
    return out


def test_net_record_matches_the_target_return(tmp_path):
    led = um.ul.Ledger(tmp_path / "l.jsonl")
    eid = put(led, 1, month_ms(2026, 11), 0.05)
    v = ur.view(led, led.get("event:" + eid))
    assert float(ur.outcome(v)[1]["net_return"]) == pytest.approx(0.05, abs=1e-12)


def _ledger(tmp_path, pairs, **kw):
    led = um.ul.Ledger(tmp_path / "l.jsonl")
    for i, (t0, v) in enumerate(pairs):
        put(led, i, t0, v, **kw)
    return led


def test_interval_is_the_95_percent_a4_block_bootstrap(tmp_path):
    pairs = months(4, [0.08, 0.02, -0.03, 0.06, 0.10, -0.01, 0.04, 0.07])
    res = ur.results(ur.views(_ledger(tmp_path, pairs)))
    r = ur.resolve(res)
    anns = nr.announcements(res, "24h")
    assert r["ci"] == list(nr.block_bootstrap_mean_ci(anns, level=Fraction(95, 100)))
    wide = nr.block_bootstrap_mean_ci(anns)                       # the helper's 98.33% default
    assert wide[0] <= r["ci"][0] and r["ci"][1] <= wide[1] and tuple(r["ci"]) != wide
    assert r["ci_level"] == "0.95" and r["months"] == 4 and r["n_announcements"] == 8
    assert r["mean"] == pytest.approx(sum(v for _, v in pairs) / 8, abs=1e-9)


def test_classes(tmp_path):
    up = ur.resolve(ur.results(ur.views(_ledger(tmp_path / "a", months(3, [0.05, 0.06, 0.07] * 3)))))
    assert up["class"] == "EDGE" and up["ci"][0] > 0
    down = ur.resolve(ur.results(ur.views(_ledger(tmp_path / "b", months(3, [-0.05, -0.04, -0.06] * 3)))))
    assert down["class"] == "NO EDGE" and down["ci"][1] <= 0
    mixed = ur.resolve(ur.results(ur.views(_ledger(tmp_path / "c", months(3, [0.1, -0.1, 0.02] * 3)))))
    assert mixed["class"] == "NOT DETERMINABLE" and mixed["reason"] == "95% interval spans zero"
    one = ur.resolve(ur.results(ur.views(_ledger(tmp_path / "d", months(1, [0.05] * 5)))))
    assert one["class"] == "NOT DETERMINABLE" and one["ci"] == [None, None]
    assert one["reason"].startswith("fewer than two calendar months")


def test_announcement_level_mean_averages_tokens_of_one_notice(tmp_path):
    led = um.ul.Ledger(tmp_path / "l.jsonl")
    t0 = month_ms(2026, 11)
    led_ids = [put(led, 1, t0, 0.10, token="AAA"), put(led, 1, t0, 0.00, token="BBB")]
    put(led, 2, month_ms(2026, 12), 0.02)
    res = ur.results(ur.views(led))
    assert len(res) == 3 and len(led_ids) == 2
    anns = nr.announcements(res, "24h")
    assert [float(a[2]) for a in anns] == pytest.approx([0.05, 0.02], abs=1e-12)


def test_missing_funding_stays_out_of_the_mean_and_feeds_the_95_percent_tipping_point(tmp_path):
    pairs = months(4, [0.06, 0.05, 0.07, 0.08, 0.06, 0.05, 0.07, 0.09])
    led = _ledger(tmp_path, pairs)
    put(led, 99, month_ms(2027, 1, 20), 0.5, funding=False)       # a big winner, funding missing
    res = ur.results(ur.views(led))
    r = ur.resolve(res)
    assert r["n_announcements"] == 8 and r["missing"]["token_events"] == 1
    assert r["mean"] == pytest.approx(sum(v for _, v in pairs) / 8, abs=1e-9)   # not 0.5
    assert r["class"] == "EDGE"
    tip95 = nr.tipping_point(res, "EDGE (proxy)", "24h", level=Fraction(95, 100))
    assert r["tipping_point"]["value"] == tip95["value"]
    assert r["tipping_point"]["note"].startswith("EDGE reverses")
    assert nr.tipping_point(res, "EDGE (proxy)", "24h")["value"] != tip95["value"]   # 98.33%


def _final_count(led):
    return len(ur.final_comparable(ur.views(led)))


def test_single_decision_at_40_comparable_announcements(tmp_path):
    mon, clock = monitor(tmp_path)
    pairs = months(5, [0.03, -0.01, 0.05, 0.02, 0.04] * 9)       # 45 announcements
    for i, (t0, v) in enumerate(pairs[:19]):
        put(mon.ledger, i, t0, v)
    mon._decide()
    assert "milestone:20" not in mon.ledger and "decision" not in mon.ledger
    for i, (t0, v) in enumerate(pairs[19:30], start=19):
        put(mon.ledger, i, t0, v)
    put(mon.ledger, 500, month_ms(2027, 1, 2), 0.9, comparable=False)   # descriptive: never counts
    mon._decide()
    m20, m30 = mon.ledger.get("milestone:20"), mon.ledger.get("milestone:30")
    assert m20["descriptive_only"] and m30["descriptive_only"] and len(m30["announcements"]) == 30
    assert "decision" not in mon.ledger
    for i, (t0, v) in enumerate(pairs[30:], start=30):
        put(mon.ledger, i, t0, v)
    mon._decide()
    d = mon.ledger.get("decision")
    assert d["trigger"] == "40 comparable announcements" and len(d["announcements"]) == 40
    order = sorted((t0, "upbit:n%d" % i) for i, (t0, _) in enumerate(pairs))
    assert d["announcements"] == [aid for _, aid in order[:40]]
    assert d["ci_level"] == "0.95" and d["prereg"] == uc.PREREG_ID
    assert d["class"] in ("EDGE", "NO EDGE", "NOT DETERMINABLE")
    put(mon.ledger, 900, month_ms(2027, 6), -0.5)                 # later events change nothing
    clock.to(uc.DECISION_DATE_MS + 1)
    mon._decide()
    assert len(mon.ledger.kind("decision")) == 1 and mon.ledger.get("decision") is d
    replay = um.ul.Ledger(mon.ledger.path)
    assert len(replay.kind("decision")) == 1 and replay.get("decision")["class"] == d["class"]


def test_decision_waits_for_an_earlier_pending_event(tmp_path):
    mon, clock = monitor(tmp_path)
    pairs = months(4, [0.02] * 41)
    put(mon.ledger, 0, pairs[0][0] - f.D, 0.0, final=False)       # the earliest is still open
    for i, (t0, v) in enumerate(pairs, start=1):
        put(mon.ledger, i, t0, v)
    mon._decide()
    assert "decision" not in mon.ledger and _final_count(mon.ledger) == 0
    eid = "upbit:n0:T0"
    mon.ledger.append({"rid": "exit:" + eid, "kind": "exit", "status": "ok", "q": "100",
                       "vwap": "1", "obs_ms": 0})
    mon.ledger.append({"rid": "funding:" + eid, "kind": "funding", "status": "complete",
                       "cashflow": "0"})
    mon._decide()
    assert mon.ledger.get("decision")["announcements"][0] == "upbit:n0"


def test_deadline_decision_with_fewer_than_40(tmp_path):
    mon, clock = monitor(tmp_path)
    pairs = months(6, [0.04, 0.05, 0.01, 0.03, 0.06, 0.02] * 2)
    for i, (t0, v) in enumerate(pairs):
        put(mon.ledger, i, t0, v)
    put(mon.ledger, 77, uc.DECISION_DATE_MS + f.H, 0.5)          # after the deadline: left out
    mon._decide()
    assert "decision" not in mon.ledger                           # neither trigger yet
    clock.to(uc.DECISION_DATE_MS)
    mon._decide()
    d = mon.ledger.get("decision")
    assert d["trigger"] == "deadline 2027-11-05" and len(d["announcements"]) == 12
    assert "upbit:n77" not in d["announcements"]


def test_status_reports_the_resolution_numbers(tmp_path):
    led = _ledger(tmp_path, months(3, [0.05, 0.06, 0.04] * 3))
    s = ur.summarize(led, um.ul.Ledger(tmp_path / "m.jsonl"), month_ms(2027, 3))
    assert s["resolution"]["final_comparable_announcements"] == 9
    assert s["resolution"]["interim"]["class"] == "EDGE"
    text = "\n".join(ur.status_lines(s))
    assert "interim, not the decision: EDGE" in text and "decision: not yet taken" in text
    assert uv.fee(D("100")) == D("0.045")


def test_decision_is_over_the_whole_comparable_cohort_with_the_start_known_subset_descriptive(tmp_path):
    mon, clock = monitor(tmp_path)
    pairs = months(4, [0.05, 0.06, 0.04, 0.07] * 10)              # 40 announcements
    for i, (t0, v) in enumerate(pairs):                            # 30 start_unknown, 10 known
        put(mon.ledger, i, t0, v if i % 4 == 0 else -0.06 if i % 4 == 1 else v,
            start=(i % 4 == 0), seen=(i % 2 == 0))
    mon._decide()
    d = mon.ledger.get("decision")
    assert len(d["announcements"]) == 40 and d["n_announcements"] == 40   # start_unknown counted
    assert d["flags"] == {"token_events": 40, "start_unknown": 30, "krw_market_first_seen": 20}
    sub = d["start_known_subset"]
    assert sub["descriptive_only"] is True and sub["n_announcements"] == 10
    whole = ur.resolve(ur.results(ur.views(mon.ledger)))
    assert (d["class"], d["mean"]) == (whole["class"], whole["mean"])
    assert sub["mean"] == pytest.approx(0.05, abs=1e-9) and sub["mean"] != d["mean"]
    text = "\n".join(ur.status_lines(ur.summarize(mon.ledger, um.ul.Ledger(tmp_path / "m.jsonl"),
                                                   clock.ms)))
    assert "DECISION (40 comparable announcements" in text and "whole comparable cohort" in text
    assert "start_unknown=false subset (descriptive only)" in text
    assert "start_unknown 30, krw_market_first_seen 20 (of 40 token-events)" in text


def test_krw_market_first_seen_never_changes_selection(tmp_path):
    pairs = months(4, [0.03, -0.01, 0.05, 0.02] * 11)
    plain, seen = monitor(tmp_path / "a")[0], monitor(tmp_path / "b")[0]
    for i, (t0, v) in enumerate(pairs):
        put(plain.ledger, i, t0, v)
        put(seen.ledger, i, t0, v, seen=(i % 3 == 0))
    for a, b in zip(ur.views(plain.ledger), ur.views(seen.ledger)):
        assert ur.classify(a) == ur.classify(b) and ur.outcome(a) == ur.outcome(b)
    plain._decide()
    seen._decide()
    da, db = plain.ledger.get("decision"), seen.ledger.get("decision")
    assert da["announcements"] == db["announcements"]
    assert (da["class"], da["mean"], da["ci"]) == (db["class"], db["mean"], db["ci"])
    assert da["flags"]["krw_market_first_seen"] == 0 and db["flags"]["krw_market_first_seen"] == 14


def test_krw_seen_scan_starts_strictly_after_t0_on_a_fresh_monitor(tmp_path):
    mon, clock = monitor(tmp_path)
    t0 = month_ms(2026, 11)
    eid = put(mon.ledger, 1, t0, 0.0, token="NEWX", final=False)
    sets = {"a": ["KRW-BTC"], "b": ["KRW-BTC", "KRW-NEWX"]}
    for sha, markets in sets.items():
        mon.markets.append({"rid": "set:" + sha, "kind": "market_set", "sha256": sha,
                            "markets": markets})
    for k, (offset, sha) in enumerate(((-5, "a"), (0, "b"), (5, "a"), (10, "a"), (15, "b"), (20, "b"))):
        mon.markets.append({"rid": "poll:%d" % k, "kind": "market_poll", "obs_ms": t0 + offset * f.MIN,
                            "sha256": sha})
    mon._krw_seen()                       # listed at t0 itself: not after t0, so not "seen"
    seen = mon.ledger.get("krwseen:" + eid)
    assert seen["krw_market_first_seen_ms"] == t0 + 15 * f.MIN
    assert seen["prev_snapshot_ms"] == t0 + 10 * f.MIN and seen["prev_listed"] is False
    mon._krw_seen()
    assert len(mon.ledger.kind("krwseen")) == 1
