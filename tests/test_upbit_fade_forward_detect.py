"""Upbit fade forward monitor (#229): detection from the PIT archive, classification, cursors.

    python3 -m pytest tests/test_upbit_fade_forward_detect.py -q
"""
import json

import uff_fakes as f
import uff_detect as ud
import uff_report as ur


def real_titles():
    return {x["title"]: x for x in f.fixture("tree_upbit.json")}


# --- classification from real Tree titles -------------------------------------------------

def test_real_cards_title_is_a_krw_addition():
    titles = real_titles()
    assert f.CARDS_TITLE in titles
    assert ud.classify(f.CARDS_TITLE, None) == {"kind": "addition", "krw": {"CARDS": True}}
    assert ud.notice_id(titles[f.CARDS_TITLE]["url"]) == "1793858584730"


def test_real_non_listing_titles_do_not_classify_and_are_not_queued():
    titles = real_titles()
    for title in (f.ENJ_TITLE, f.MAINT_TITLE):
        assert title in titles
        assert ud.classify(title, None) == {"kind": "other"}
    # Their notice ids are UUIDs, not numbers.
    assert ud.notice_id(titles[f.ENJ_TITLE]["url"]) == "d1fecdf2-e7a2-437c-8d31-529213bc6705"


def test_unclassified_queue_rules():
    # Mentions 거래지원 but an exclusion word stops O8: queued, never traded.
    assert ud.classify("디지털 자산 신규 거래지원 안내 (거래지원 개시 시점 변경) (KRW 마켓)", None) == \
        {"kind": "unclassified"}
    assert ud.classify("유의 종목 지정 기간 연장 안내 (BTC 마켓)", None)["kind"] == "unclassified"
    # A delisting is classified (an end), not queued.
    assert ud.classify("에이(AAA) 거래지원 종료 안내 (KRW 마켓)", None) == {"kind": "end"}
    # Two tokens, several markets, no body: KRW membership unstated -> None per token.
    two = "에이(AAA), 비(BBB) 신규 거래지원 안내 (KRW, BTC 마켓)"
    assert ud.classify(two, None) == {"kind": "addition", "krw": {"AAA": None, "BBB": None}}
    body = "<p>- KRW 마켓 : AAA</p><p>- BTC 마켓 : AAA, BBB</p>"
    assert ud.classify(two, body) == {"kind": "addition", "krw": {"AAA": True, "BBB": False}}


def test_notice_id_only_for_upbit_notice_pages():
    assert ud.notice_id("https://upbit.com/service_center/notice?id=5555") == "5555"
    assert ud.notice_id("https://www.upbit.com/service_center/notice?id=a-b") == "a-b"
    assert ud.notice_id("https://upbit.com/service_center/notice") is None
    assert ud.notice_id("https://upbit.com/service_center/notice_list?id=1") is None
    assert ud.notice_id("https://evil.example/upbit.com/service_center/notice?id=1") is None
    assert ud.notice_id("https://x.com/a/status/1") is None
    assert ud.notice_id(None) is None


def test_timing_flags():
    pub, rcv = f.T0, f.T0 + 39_000
    assert ud.timing(f.uc.iso(pub), f.uc.iso(rcv)) == (pub, "verified", None)
    assert ud.timing(None, f.uc.iso(rcv))[:2] == (rcv, "unverified")
    assert ud.timing(f.uc.iso(rcv + 1), f.uc.iso(rcv))[:2] == (rcv + 1, "unverified")
    assert ud.timing(f.uc.iso(pub), f.uc.iso(pub + 5 * f.MIN))[1] == "verified"
    assert ud.timing(f.uc.iso(pub), f.uc.iso(pub + 5 * f.MIN + 1))[1] == "unverified"


# --- archive cursors -----------------------------------------------------------------------

def test_first_start_takes_the_epoch_cursors_and_skips_history(tmp_path):
    s = f.Scenario(tmp_path)
    s.publish(received_ms=s.t0 - 2 * f.H + 1, published_ms=s.t0 - 2 * f.H)   # before any start
    s.run(s.t0 - 50 * f.MIN)
    ep = s.mon.ledger.get("epoch")
    assert ep["items_pk"] == 2 and ep["rev_pk"] == 0
    assert s.mon.ledger.kind("event") == [] and s.mon.ledger.kind("seen") == []
    assert json.loads((s.data / "state.json").read_text())["items_pk"] == 2


def test_revision_cursor_sees_a_title_revised_into_a_listing(tmp_path):
    s = f.Scenario(tmp_path)
    s.run(s.t0 - 50 * f.MIN)
    s.title = f.MAINT_TITLE
    s.publish()                                   # first version: not a listing
    s.run(s.t0 + 2 * f.MIN)
    assert s.mon.ledger.kind("event") == []
    assert [r["class"]["kind"] for r in s.mon.ledger.kind("seen")] == ["other"]
    s.title = f.CARDS_TITLE
    s.publish(received_ms=s.t0 + 8 * f.MIN)       # Tree revises the same item 8 min later
    s.run(s.t0 + 9 * f.MIN)
    ev = s.rec("event")
    assert ev["ref"].startswith("item_revisions:")
    assert ev["t0_ms"] == s.t0                     # Tree's time is unchanged by the revision
    assert ev["timing"] == "unverified"           # received 8 min after published
    state = json.loads((s.data / "state.json").read_text())
    assert state["rev_pk"] == 1 and state["items_pk"] == 2


def test_restart_resumes_from_the_cursors_without_duplicates(tmp_path):
    s = f.Scenario(tmp_path)
    s.run(s.t0 - 50 * f.MIN)
    s.publish()
    s.run(s.t0 + 60_000)
    before = len(s.mon.ledger)
    events = [e["rid"] for e in s.mon.ledger.kind("event")]
    s.new_monitor()                                # restart: replay the ledger, reload cursors
    s.mon.tick()
    assert [e["rid"] for e in s.mon.ledger.kind("event")] == events
    assert len(s.mon.ledger.kind("seen")) == 1
    (s.data / "state.json").unlink()               # state lost: back to the epoch cursors
    s.new_monitor()
    s.mon.tick()
    assert [e["rid"] for e in s.mon.ledger.kind("event")] == events
    assert len(s.mon.ledger) >= before
    assert s.mon.errors == []


def test_one_event_per_notice_id_and_token(tmp_path):
    s = f.Scenario(tmp_path)
    s.run(s.t0 - 50 * f.MIN)
    s.publish(_id="tree-a")
    s.publish(_id="tree-b", received_ms=s.t0 + 45_000)   # a second Tree item, same notice URL
    s.run(s.t0 + 60_000)
    assert [e["event_id"] for e in s.mon.ledger.kind("event")] == [s.eid()]
    assert len(s.mon.ledger.kind("seen")) == 1     # identical content is recorded once


def test_non_upbit_tree_items_and_other_sources_are_skipped(tmp_path):
    s = f.Scenario(tmp_path)
    s.run(s.t0 - 50 * f.MIN)
    s.archive.other([{"_id": "tw2", "title": "CARDS 신규 거래지원 KRW", "source": "Twitter",
                      "url": "https://x.com/b/2", "time": s.t0}], s.t0 + 1000)
    s.archive.binance(48001, "Binance Will List CARDS (CARDS)", s.t0, s.t0 + 2000)
    s.run(s.t0 + 60_000)
    assert s.mon.ledger.kind("event") == [] and s.mon.ledger.kind("seen") == []
    assert json.loads((s.data / "state.json").read_text())["items_pk"] == 3


def test_unclassified_notice_is_queued_and_never_traded(tmp_path):
    s = f.Scenario(tmp_path)
    s.title = "에이(AAA), 비(BBB) 신규 거래지원 안내 (KRW, BTC 마켓)"
    s.run(s.t0 - 50 * f.MIN)
    s.publish()
    s.run(s.t0 + 20 * f.MIN)
    assert s.mon.ledger.kind("event") == []
    queued = [(u["token"], u["reason"]) for u in s.mon.ledger.kind("unclassified")]
    assert queued == [("AAA", "market_unstated"), ("BBB", "market_unstated")]
    assert s.hl.count("l2Book") == 0
    summary = ur.summarize(s.mon.ledger, s.mon.markets, s.clock.ms)
    assert [u["reason"] for u in summary["unclassified"]] == ["market_unstated"] * 2


def test_archive_health_and_pit_diagnostics(tmp_path):
    s = f.Scenario(tmp_path)
    s.run(s.t0 - 50 * f.MIN)
    f.na_store.open_gap(s.archive.conn, "tree", "outage", f.uc.iso(s.t0 - 10 * f.MIN), "test")
    s.publish()
    s.run(s.t0 + 60_000)
    assert s.rec("event")["pit"] == {"after_gap": 1, "pit_valid": False}
    with ud.open_archive(s.archive.path) as conn:
        h = ud.health(conn, s.clock.ms)
    assert h["tree"]["open_gaps"][0][0] == "outage" and h["tree"]["gaps_7d"] == 1
