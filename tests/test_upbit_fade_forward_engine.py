"""Upbit fade forward monitor (#229): the paper trade lifecycle, deadlines across restarts,
missing and late outcomes, funding, the market audit and ledger replay.

    python3 -m pytest tests/test_upbit_fade_forward_engine.py -q
"""
import json
from decimal import Decimal as D

import uff_fakes as f
import uff_ledger as ul
import uff_report as ur
import uff_venues as uv
import nes_returns as nr

BODY = "<p>거래지원 개시 시점 : 2026년 11월 10일 17:00 예정</p>"


def started(tmp_path):
    s = f.Scenario(tmp_path, body=BODY)
    s.run(s.t0 - 1000, every_ms=60_000)
    s.publish()
    return s


def event_records(ledger):
    return [r for r in ledger.order if r.get("event_id")]


def test_full_lifecycle_is_a_resolved_comparable_outcome(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 26 * f.H)
    assert s.mon.errors == []
    entry, exit_ = s.rec("entry"), s.rec("exit")
    assert entry["status"] == "timely" and entry["side"] == "sell"
    assert s.t0 + 5 * f.MIN <= entry["obs_ms"] <= s.t0 + 7 * f.MIN
    for name, offset in (("cp30m", 30 * f.MIN), ("cp4h", 4 * f.H), ("exit", f.D)):
        rec = s.rec(name)
        assert rec["status"] == "ok" and rec["side"] == "buy" and rec["q"] == entry["q"]
        assert rec["nominal_ms"] == entry["obs_ms"] + offset
    fund = s.rec("funding")
    assert fund["status"] == "complete" and fund["n_boundaries"] == 24
    assert D(fund["cashflow"]) == 24 * D(entry["q"]) * D("1.0") * D("0.0000125")   # paid to the short
    assert len(s.mon.ledger.kind("oracle")) == 24
    assert s.rec("excursion")["status"] == "ok"
    v = ur.view(s.mon.ledger, s.rec("event"))
    status, n = ur.outcome(v)
    assert status == "resolved" and n == uv.net(entry, exit_, fund)
    assert ur.results([v])[0]["horizons"]["24h"]["net"] == n["net_return"]
    lines = "\n".join(ur.status_lines(ur.summarize(s.mon.ledger, s.mon.markets, s.clock.ms)))
    for head in ("OPEN PAPER POSITIONS (0)", "CLOSED (1)", "COHORTS", "LATENCY", "MISSES",
                 "UNCLASSIFIED", "RESOLUTION", "Tree-clock cohort", "PAPER ONLY"):
        assert head in lines


def test_status_shows_an_open_position(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 40 * f.MIN)
    summary = ur.summarize(s.mon.ledger, s.mon.markets, s.clock.ms)
    assert [r["event_id"] for r in summary["open_positions"]] == [s.eid()]
    assert summary["open_positions"][0]["marks"]["cp30m"]["late"] is False
    assert json.dumps(summary)                      # the --json output is serializable


def test_checkpoint_missed_during_downtime_is_missing_then_late(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 10 * f.MIN)
    entry = s.rec("entry")
    s.clock.to(entry["obs_ms"] + 30 * f.MIN + 11 * f.MIN)      # down through the cp30m deadline
    s.new_monitor()
    s.run(s.t0 + 26 * f.H)
    assert s.rec("cp30m")["status"] == "missing"
    late = s.rec("late:cp30m")
    assert late["status"] == "late" and late["late_by_ms"] > 10 * f.MIN
    assert s.rec("cp4h")["status"] == "ok" and s.rec("exit")["status"] == "ok"
    assert ur.outcome(ur.view(s.mon.ledger, s.rec("event")))[0] == "resolved"


def test_exit_missed_after_a_restart_is_missing_with_a_late_mark(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 23 * f.H)
    entry = s.rec("entry")
    s.clock.to(entry["obs_ms"] + f.D + 30 * f.MIN)              # back 30 min after the exit
    s.new_monitor()
    s.run(s.clock.ms + 5 * f.MIN)
    assert s.rec("exit")["status"] == "missing"
    assert s.rec("late:exit")["status"] == "late"
    assert s.rec("funding") is None                              # no scheduled exit, no net
    status, _ = ur.outcome(ur.view(s.mon.ledger, s.rec("event")))
    assert status == "missing"
    res = ur.results(ur.views(s.mon.ledger))
    assert res[0]["horizons"]["24h"] == {"exit_status": "missing", "net": None, "net_stress": None}
    summary = ur.summarize(s.mon.ledger, s.mon.markets, s.clock.ms)
    assert summary["closed"][0]["exit_late"] is True
    assert {"event_id": s.eid(), "missing": ["exit"]} in summary["misses"]["outcomes"]


def test_notice_detected_after_the_entry_deadline_is_a_missing_entry(tmp_path):
    s = f.Scenario(tmp_path, body=BODY)
    s.run(s.t0 - 1000, every_ms=60_000)
    s.publish()                                     # Tree has it at t0 + 39 s ...
    s.clock.to(s.t0 + 20 * f.MIN)                   # ... the monitor was down until t0 + 20 min
    s.new_monitor()
    s.run(s.t0 + 70 * f.MIN)
    entry = s.rec("entry")
    assert entry["status"] == "missing" and "detected after" in entry["reason"]
    assert s.hl.count("l2Book") == 0 and s.rec("late:entry") is None   # never opened late
    cohort, unknown = ur.classify(ur.view(s.mon.ledger, s.rec("event")))
    assert (cohort, unknown) == ("comparable", ["entry_timely"])         # counts as missing


def test_thin_book_attempts_are_rejected_then_the_entry_fills(tmp_path):
    s = started(tmp_path)
    nominal = s.t0 + 5 * f.MIN
    s.hl.book_fn = lambda coin, now: f.book(coin, now, sizes=(10, 10) if now < nominal + 40_000
                                            else (60, 60, 60))
    s.run(s.t0 + 10 * f.MIN)
    rejects = [r for r in s.mon.ledger.kind("reject") if r["of"] == "entry:" + s.eid()]
    assert rejects and {r["reason"] for r in rejects} == {"thin_book"}
    entry = s.rec("entry")
    assert entry["status"] == "timely" and entry["attempts"] == len(rejects) + 1


def test_an_entry_never_filled_by_the_deadline_is_missing(tmp_path):
    s = started(tmp_path)
    s.hl.book_fn = lambda coin, now: f.book(coin, now, age_ms=10_000)
    s.run(s.t0 + 30 * f.MIN, every_ms=5_000)
    entry = s.rec("entry")
    rejects = [r for r in s.mon.ledger.kind("reject") if r["of"] == "entry:" + s.eid()]
    assert entry["status"] == "missing" and entry["attempts"] == len(rejects) >= 50
    assert s.rec("cp30m") is None and s.rec("exit") is None


def test_a_missed_oracle_observation_makes_funding_missing(tmp_path):
    s = started(tmp_path)
    hour = (s.t0 // f.H + 3) * f.H
    s.run(hour - 10_000)
    s.hl.fail.add("metaAndAssetCtxs")              # down through one funding hour's window
    s.run(hour + 2 * f.MIN)
    s.hl.fail.discard("metaAndAssetCtxs")
    s.run(s.t0 + 26 * f.H)
    fund = s.rec("funding")
    assert fund["status"] == "missing" and fund["cashflow"] is None
    assert [m["oracle"] for m in fund["missing"]] == [False]
    status, n = ur.outcome(ur.view(s.mon.ledger, s.rec("event")))
    assert status == "missing" and n["net_return"] is None and n["net_ex_funding_return"]
    parts = nr.announcement_parts(ur.results(ur.views(s.mon.ledger)), "24h")
    assert [p[3:] for p in parts] == [(0, 1)]       # counted missing in the tipping point


def test_funding_waits_for_the_last_settlement_record(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 25 * f.H)
    exit_ms = s.rec("exit")["obs_ms"]
    reads = [t for t, b in s.hl.requests if b["type"] == "fundingHistory" and t >= exit_ms]
    assert reads and s.rec("funding")["status"] == "complete"


def test_restart_mid_hold_replays_the_ledger_idempotently(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 2 * f.H)
    before = [json.dumps(r, sort_keys=True) for r in event_records(s.mon.ledger)]
    s.new_monitor()
    s.mon.tick()                                    # same instant: nothing new for the event
    after = [json.dumps(r, sort_keys=True) for r in event_records(s.mon.ledger)]
    assert after == before
    s.run(s.t0 + 26 * f.H)
    assert s.rec("exit")["status"] == "ok" and s.rec("funding")["status"] == "complete"
    rids = [r["rid"] for r in s.mon.ledger.order]
    assert len(rids) == len(set(rids))


def test_ledger_replay_skips_repeats_and_a_torn_line(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = ul.Ledger(path)
    assert led.append({"rid": "a", "kind": "x", "v": 1}) is True
    assert led.append({"rid": "a", "kind": "x", "v": 2}) is False
    with open(path, "ab") as fh:
        fh.write(b'{"rid":"a","kind":"x","v":3}\n')          # a repeated rid
        fh.write(b'{"rid":"b","kind":"x","v":1}\n')
        fh.write(b'{"rid":"c","ki')                           # torn by a crash
    replay = ul.Ledger(path)
    assert [(r["rid"], r["v"]) for r in replay.order] == [("a", 1), ("b", 1)]
    assert replay.skipped == 1
    replay.append({"rid": "d", "kind": "x", "v": 1})
    again = ul.Ledger(path)
    assert [r["rid"] for r in again.order] == ["a", "b", "d"] and again.skipped == 1
    assert [r["rid"] for r in again.kind("x")] == ["a", "b", "d"]


def test_new_krw_market_without_a_notice_is_a_missed_detection(tmp_path):
    s = f.Scenario(tmp_path, body=BODY)
    s.run(s.t0 - 1000, every_ms=60_000)
    s.http.markets_fn = lambda now: ["KRW-BTC", "KRW-ETH", "KRW-NEWX"]
    s.run(s.t0 + 25 * f.H, every_ms=5 * f.MIN)
    audit = s.mon.ledger.kind("audit")
    assert [(a["market"], a["status"]) for a in audit] == [("KRW-NEWX", "missed")]
    assert s.mon.markets.kind("new_market")[0]["first_seen_ms"] >= s.t0


def test_new_krw_market_with_a_detected_notice_is_matched(tmp_path):
    s = started(tmp_path)
    s.run(s.t0 + 2 * f.H)
    s.http.markets_fn = lambda now: ["KRW-BTC", "KRW-ETH", "KRW-CARDS"]
    s.run(s.t0 + 3 * f.H)
    audit = s.mon.ledger.kind("audit")
    assert [(a["market"], a["status"], a["events"]) for a in audit] == [
        ("KRW-CARDS", "matched", [s.eid()])]


def test_market_snapshots_are_timestamped_and_deduplicated(tmp_path):
    s = f.Scenario(tmp_path)
    s.run(s.t0 - 1000, every_ms=60_000)
    polls = s.mon.markets.kind("market_poll")
    assert len(polls) == 12 and len(s.mon.markets.kind("market_set")) == 1
    assert all(b["obs_ms"] - a["obs_ms"] >= 5 * f.MIN for a, b in zip(polls, polls[1:]))
