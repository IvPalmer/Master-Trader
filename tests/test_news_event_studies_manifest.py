"""Part C Phase 1 manifest builder (#229): outcome-blind event lists (O8-O13, O16, O17).

    python3 -m pytest tests/test_news_event_studies_manifest.py -q
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_util as nu  # noqa: E402
import nes_manifest as nm  # noqa: E402

KST = timezone(timedelta(hours=9))
H, D = 3_600_000, 86_400_000
DEL, LONG, FADE = nm.STUDIES


def ms(s):
    return nu.ms_from_iso(s)


def kst(t):
    return datetime.fromtimestamp(t / 1000, KST).isoformat()


def art(id_, title, t0):
    return {"id": id_, "code": "c%d" % id_, "title": title, "type": 1, "releaseDate": t0}


def notice(id_, title, t0, listed=None):
    return {"id": id_, "uuid": str(id_), "title": title, "category": "거래",
            "first_listed_at": kst(t0), "listed_at": kst(listed if listed is not None else t0)}


def start_body(t):
    return "거래지원 개시 시점 : %s" % datetime.fromtimestamp(t / 1000, KST).strftime(
        "%Y년 %m월 %d일 %H:%M")


# --- raw harvest directories --------------------------------------------------------

def _cms_body(cid, arts, total):
    return json.dumps({"code": "000000", "success": True, "data": {"catalogs": [
        {"catalogId": cid, "catalogName": "cat%d" % cid, "total": total, "articles": arts}]}}).encode()


def write_cms(d, c161=(), c48=(), c49=(), totals=None, aborted=None, skip=()):
    d = Path(d)
    totals = totals or {}
    meta = {"aborted": aborted, "suspensions": [], "catalogs": {}}
    for cid, arts in ((161, c161), (48, c48), (49, c49)):
        if cid in skip:
            continue
        arts = list(arts)
        total = totals.get(cid, len(arts))
        chunks = [arts[i:i + 50] for i in range(0, len(arts), 50)] or [[]]
        files = {"cat%d/page-%04d.json" % (cid, i): _cms_body(cid, c, total)
                 for i, c in enumerate(chunks, 1)}
        if cid != 49:
            files["cat%d/closing.json" % cid] = _cms_body(cid, chunks[0], total)
        for rel, body in files.items():
            nu.write_atomic(d / rel, body)
        meta["catalogs"][str(cid)] = {"catalog_name": "cat%d" % cid, "aborted": None,
                                      "files": {r: nu.sha256_bytes(b) for r, b in files.items()}}
    nu.write_atomic(d / "harvest_meta.json", json.dumps(meta).encode())
    return d


def write_upbit(d, notices=(), details=None, total=None, host="operator-mac", blocked=None):
    d = Path(d)
    notices = list(notices)
    page = json.dumps({"success": True, "data": {
        "total_pages": 1, "total_count": len(notices) if total is None else total,
        "notices": notices}}, ensure_ascii=False).encode()
    files = {"list/page-01.json": page, "list/closing.json": page}
    by_id = {n["id"]: n for n in notices}
    for id_, body in (details or {}).items():
        n = by_id[id_]
        files["detail/%d.json" % id_] = json.dumps({"success": True, "data": {
            "id": id_, "title": n["title"], "body": body, "first_listed_at": n["first_listed_at"],
            "listed_at": n["listed_at"]}}, ensure_ascii=False).encode()
    for rel, body in files.items():
        nu.write_atomic(d / rel, body)
    meta = {"files": {r: nu.sha256_bytes(b) for r, b in files.items()}, "host_label": host,
            "blocked": blocked, "finished_at": None if blocked else "2026-11-04T00:00:00Z"}
    nu.write_atomic(d / "harvest_meta.json", json.dumps(meta).encode())
    return d


class FakeHl:
    def __init__(self, names=("AAA", "BBB", "TST"), evidence=None):
        self.body = json.dumps({"universe": [{"name": n} for n in names]}).encode()
        self.evidence_map, self.calls = dict(evidence or {}), []

    def meta(self):
        return self.body

    def evidence(self, coin, t0_ms, absent_from_meta=False):
        self.calls.append(coin)
        if coin in self.evidence_map:
            return self.evidence_map[coin]
        return [] if absent_from_meta else [t0_ms - 60_000]   # absent names: 500 null


class FakeProbe:
    """`rule(market, symbol, date) -> bool`; default: every `<T>USDT` file exists."""

    def __init__(self, rule=None):
        self.rule = rule or (lambda m, s, d: not s.startswith("1"))
        self.urls = []

    def exists(self, url):
        self.urls.append(url)
        parts = url.split("/")
        return self.rule("um" if "/futures/um/" in url else "spot", parts[-3], parts[-1][-14:-4])


# --- delisting events ---------------------------------------------------------------

T = ms("2024-03-01T12:00:30Z")


def _kept(events):
    return [(e["announcement_id"], e["token"]) for e in events if e["exclusion"] is None]


def test_overlap_keeps_first_and_measures_from_last_kept():
    arts = [art(i + 1, "Binance Will Delist AAA on 2024-03-10", T + h * H)
            for i, h in enumerate((0, 20, 24, 30, 40))]
    events = nm.delisting_events(arts, [])
    assert _kept(events) == [("binance:1", "AAA"), ("binance:4", "AAA")]
    dropped = {e["announcement_id"]: e for e in events if e["exclusion"]}
    assert dropped["binance:2"]["exclusion"] == "same_token_overlap"
    assert dropped["binance:5"]["exclusion_ref"] == "binance:4"


def test_overlap_spans_kinds_and_not_tokens():
    arts = [art(1, "Binance Will Extend the Monitoring Tag to Include AAA on 2024-03-02", T),
            art(2, "Binance Will Delist AAA, BBB on 2024-03-10", T + H)]
    assert _kept(nm.delisting_events(arts, [])) == [("binance:1", "AAA"), ("binance:2", "BBB")]


def test_overlap_runs_before_window():
    arts = [art(1, "Binance Will Delist AAA on 2023-01-05", ms("2022-12-31T12:00:00Z")),
            art(2, "Binance Will Delist AAA on 2023-01-06", ms("2023-01-01T06:00:00Z"))]
    events = nm.delisting_events(arts, [])
    assert _kept(events) == []
    assert [e["exclusion"] for e in events] == ["same_token_overlap"]


def test_window_end_exclusive():
    arts = [art(1, "Binance Will Delist AAA", 1793491199999),
            art(2, "Binance Will Delist BBB", 1793491200000)]
    assert _kept(nm.delisting_events(arts, [])) == [("binance:1", "AAA")]


def test_excluded_titles_make_no_events():
    arts = [art(1, "Notice of Removal of Spot Trading Pairs - 2024-03-01", T),
            art(2, "Binance Will Remove the Monitoring Tag on AAA on 2024-03-02", T)]
    assert nm.delisting_events(arts, []) == []


def test_in_window_unclassified_raises_needs_review():
    title = "Binance Will Delist Ankr (ANKR) on 2024-04-10"
    with pytest.raises(nm.NeedsReview) as e:
        nm.delisting_events([art(1, title, T)], [])
    assert e.value.items[0]["ref"] == "binance:1" and e.value.items[0]["title"] == title
    assert nm.delisting_events([art(1, title, ms("2021-06-01T00:00:00Z"))], []) == []


def test_monitoring_title_in_scan49_raises_needs_review():
    mon = "Binance Will Extend the Monitoring Tag to Include CCC on 2024-02-20"
    with pytest.raises(nm.NeedsReview) as e:
        nm.delisting_events([], [art(7, mon, T)])
    assert e.value.items[0]["reason"] == "monitoring_tag_in_catalog_49"
    assert nm.delisting_events([], [art(7, mon, ms("2022-06-01T00:00:00Z"))]) == []
    assert e.value.items[0]["also_in_catalog_161"] is False
    # O17 is literal: a monitoring title in 49 stops even when 161 has the same article
    with pytest.raises(nm.NeedsReview) as e:
        nm.delisting_events([art(7, mon, T)], [art(7, mon, T)])
    assert e.value.items[0]["also_in_catalog_161"] is True


# --- Upbit events -------------------------------------------------------------------

ADD = "%s(%s) KRW 마켓 디지털 자산 추가"


def _upbit(notices, details=None, cms48=()):
    if details is None:
        details = {n["id"]: start_body(nu.ms_from_iso(n["first_listed_at"]) + 30 * 60_000)
                   for n in notices}
    return nm.upbit_events(notices, {str(k): {"body": v} for k, v in details.items()}, list(cms48))


def test_upbit_replay_already_on_krw():
    a1 = notice(1, ADD % ("에이", "AAA"), ms("2023-03-01T00:00:00Z"))
    a2 = notice(2, ADD % ("에이", "AAA"), ms("2023-05-01T00:00:00Z"))
    events = {e["announcement_id"]: e for e in _upbit([a1, a2])}
    assert events["upbit:1"]["exclusion"] is None
    assert (events["upbit:2"]["exclusion"], events["upbit:2"]["exclusion_ref"]) == \
        ("already_on_krw", "upbit:1")
    b1 = notice(3, ADD % ("비", "BBB"), ms("2023-03-01T00:00:00Z"))
    end = notice(4, "비(BBB) 거래지원 종료 안내", ms("2024-01-10T00:00:00Z"))
    b2 = notice(5, ADD % ("비", "BBB"), ms("2024-06-01T00:00:00Z"))
    events = {e["announcement_id"]: e for e in _upbit([b1, end, b2])}
    assert events["upbit:5"]["exclusion"] is None
    btc_end = notice(6, "비(BBB) BTC 마켓 거래지원 종료 안내", ms("2024-07-01T00:00:00Z"))
    b3 = notice(7, ADD % ("비", "BBB"), ms("2024-08-01T00:00:00Z"))
    events = {e["announcement_id"]: e for e in _upbit([b1, end, b2, btc_end, b3])}
    assert events["upbit:7"]["exclusion"] == "already_on_krw"


def test_upbit_replay_uses_history_before_window():
    a1 = notice(1, ADD % ("에이", "AAA"), ms("2021-03-01T00:00:00Z"))
    a2 = notice(2, ADD % ("에이", "AAA"), ms("2023-05-01T00:00:00Z"))
    events = _upbit([a1, a2], details={2: start_body(ms("2023-05-01T01:00:00Z"))})
    assert [(e["announcement_id"], e["exclusion"]) for e in events] == [("upbit:2", "already_on_krw")]


def test_upbit_binance48_overlap_inclusive_24h():
    n = notice(1, "에이(AAA), 비(BBB) KRW 마켓 디지털 자산 추가", T)
    events = {e["token"]: e for e in _upbit([n], cms48=[art(50, "Binance Will List AAA (AAA)", T + D)])}
    assert (events["AAA"]["exclusion"], events["AAA"]["exclusion_ref"]) == ("binance48_overlap", "binance:50")
    assert events["BBB"]["exclusion"] is None
    events = _upbit([n], cms48=[art(50, "Binance Will List AAA (AAA)", T + D + 1)])
    assert all(e["exclusion"] is None for e in events)
    events = _upbit([n], cms48=[art(50, "Binance Will List AAA (AAA)", T - D)])
    assert {e["token"]: e["exclusion"] for e in events}["AAA"] == "binance48_overlap"


def test_upbit_trading_start_rules():
    n = notice(1, ADD % ("에이", "AAA"), T)
    t_min = T - T % 60_000
    early = _upbit([n], details={1: start_body(t_min - 60_000)})[0]
    assert (early["exclusion"], early["trading_start_ms"]) == ("began_before_notice", t_min - 60_000)
    n0 = notice(2, ADD % ("비", "BBB"), t_min)
    same = _upbit([n0], details={2: start_body(t_min)})[0]
    assert same["exclusion"] is None and same["trading_start_ms"] == t_min
    none = _upbit([n], details={1: "본문에 시간이 없습니다."})[0]
    assert none["exclusion"] is None and none["trading_start_ms"] is None
    no_detail = _upbit([n], details={})[0]
    assert no_detail["trading_start_ms"] is None


def test_upbit_start_line_of_another_token_is_not_borrowed():
    t0 = ms("2024-03-01T12:00:30Z")                    # 21:00:30 KST
    n = notice(1, "에이(AAA), 비(BBB) KRW 마켓 디지털 자산 추가", t0)
    body = "AAA 거래지원 개시 시점: 2024-03-01 20:00\nBBB 거래지원 개시 시점: 추후 공지"
    events = {e["token"]: e for e in _upbit([n], details={1: body})}
    assert (events["AAA"]["exclusion"], events["AAA"]["trading_start_ms"]) == \
        ("began_before_notice", ms("2024-03-01T11:00:00Z"))
    assert (events["BBB"]["exclusion"], events["BBB"]["trading_start_ms"]) == (None, None)   # -> unknown
    body = "에이 거래지원 개시 시점: 2024-03-01 20:00\n비 거래지원 개시 시점: 추후 공지"      # Korean names
    events = {e["token"]: e for e in _upbit([n], details={1: body})}
    assert events["AAA"]["exclusion"] == "began_before_notice"
    assert (events["BBB"]["exclusion"], events["BBB"]["trading_start_ms"]) == (None, None)


def test_upbit_t0_is_first_listed_at():
    n = notice(1, ADD % ("에이", "AAA"), T, listed=T + 2 * H)
    e = _upbit([n])[0]
    assert (e["t0_ms"], e["kind"], e["announcement_id"]) == (T, "krw_addition", "upbit:1")


def test_upbit_t0_requires_first_listed_at():
    n = notice(1, ADD % ("에이", "AAA"), T)
    del n["first_listed_at"]
    with pytest.raises(nm.NeedsReview) as e:
        _upbit([n], details={1: start_body(T + H)})
    assert e.value.items[0]["reason"] == "no_publish_time"


def test_upbit_needs_review_in_window():
    with pytest.raises(nm.NeedsReview) as e:
        _upbit([notice(1, "에이(AAA) KRW 마켓 입금 안내", T)])
    assert e.value.items[0]["ref"] == "upbit:1"
    assert _upbit([notice(1, "에이(AAA) KRW 마켓 입금 안내", ms("2021-01-01T00:00:00Z"))]) == []


# --- study status --------------------------------------------------------------------

PROXY = {"market": "um", "symbol": "AAAUSDT", "tier": "full"}


def _event(kind, exclusion=None, start=0, on=True, spot="AAAUSDT", proxy=PROXY, hl="eligible"):
    return {"kind": kind, "exclusion": exclusion, "trading_start_ms": start,
            "binance": {"on_binance_pre_t0": on, "spot_symbol_pre_t0": spot, "proxy": proxy},
            "hl": {"status": hl, "coin": "AAA", "reason": "x"}}


STATUS_ROWS = [
    (dict(exclusion="already_on_krw"), ("excluded:already_on_krw",) * 3),
    (dict(start=None), ("candidate:hyperliquid", "unknown", "unknown")),
    (dict(on=False, spot=None, proxy=None), ("missing", "excluded:not_on_binance",
                                             "excluded:not_on_binance")),
    (dict(hl="unknown"), ("unknown",) * 3),
    (dict(hl="ineligible"), ("excluded:no_hl", "candidate:binance_spot", "excluded:spot_only")),
    (dict(hl="ineligible", spot=None), ("excluded:no_hl", "excluded:futures_only", "excluded:no_hl")),
    (dict(proxy=None), ("missing",) * 3),
    (dict(), ("candidate:hyperliquid",) * 3),
]


@pytest.mark.parametrize("facts,expected", STATUS_ROWS)
def test_study_status_table(facts, expected):
    got = (nm.study_status(_event("full_delist", **facts), DEL),
           nm.study_status(_event("krw_addition", **facts), LONG),
           nm.study_status(_event("krw_addition", **facts), FADE))
    assert got == expected


# --- build ---------------------------------------------------------------------------

def _dirs(tmp_path, c161=None, c48=(), up=None, details=None, totals=None, up_total=None,
          aborted=None, skip=()):
    c161 = c161 if c161 is not None else [art(1, "Binance Will Delist AAA on 2024-03-10", T)]
    up = up if up is not None else [notice(10, ADD % ("비", "BBB"), T)]
    if details is None:
        details = {n["id"]: start_body(nu.ms_from_iso(n["first_listed_at"]) + 30 * 60_000) for n in up}
    cms = write_cms(tmp_path / "cms", c161, c48, (), totals=totals, aborted=aborted, skip=skip)
    upb = write_upbit(tmp_path / "upbit", up, details, total=up_total)
    return cms, upb


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_manifest_deterministic_and_price_free(tmp_path):
    cms, upb = _dirs(tmp_path)
    a = nm.build(cms, upb, FakeHl(), FakeProbe(), "abc123")
    b = nm.build(cms, upb, FakeHl(), FakeProbe(), "abc123")
    assert [nu.canonical_bytes(m) for m in a] == [nu.canonical_bytes(m) for m in b]
    dm, um = a
    assert dm["studies"] == [DEL] and um["studies"] == [LONG, FADE]
    assert dm["manifest_version"] == 1 and dm["code_commit"] == "abc123"
    assert dm["hl_evidence"] == "fundingHistory"
    assert dm["window_utc"] == ["2023-01-01T00:00:00Z", "2026-11-01T00:00:00Z"]
    assert um["inputs"]["upbit_host_label"] == "operator-mac"
    assert len(dm["inputs"]["hl_meta_sha256"]) == 64
    assert [e["token"] for e in dm["events"]] == ["AAA"]
    assert [e["token"] for e in um["events"]] == ["BBB"]
    banned = {"open", "high", "low", "close", "price", "return"}
    assert not banned & set(_keys(dm)) and not banned & set(_keys(um))


def test_events_sorted(tmp_path):
    c161 = [art(2, "Binance Will Delist BBB, AAA on 2024-03-10", T),
            art(1, "Binance Will Delist CCC on 2024-03-10", T)]
    cms, upb = _dirs(tmp_path, c161=c161)
    dm, _ = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert [(e["announcement_id"], e["token"]) for e in dm["events"]] == [
        ("binance:1", "CCC"), ("binance:2", "AAA"), ("binance:2", "BBB")]


def test_shortfall_and_missing_total_in_counts(tmp_path):
    cms, upb = _dirs(tmp_path / "a", totals={161: 3, 48: 1})
    dm, um = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert nm.manifest_counts(dm, DEL)["harvest_shortfall"] == 2
    assert nm.manifest_counts(um, LONG)["harvest_shortfall"] == 1
    assert nm.manifest_counts(um, FADE)["harvest_shortfall"] == 1
    assert nm.manifest_counts(dm, DEL)["harvest_complete"] is True
    assert nm.manifest_counts(dm, DEL)["candidates"] == 1
    cms, upb = _dirs(tmp_path / "b", up_total=3)
    _, um = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert nm.manifest_counts(um, LONG)["harvest_shortfall"] == 2
    cms, upb = _dirs(tmp_path / "c", totals={161: None})
    dm, um = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert dm["harvest_complete"] is False and um["harvest_complete"] is True
    cms, upb = _dirs(tmp_path / "d", aborted="second suspension")
    dm, um = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert dm["harvest_complete"] is False and um["harvest_complete"] is False
    cms, upb = _dirs(tmp_path / "e", skip=(49,))
    dm, _ = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert dm["harvest_complete"] is False


def test_interrupted_scan49_is_incomplete(tmp_path):
    recent = [art(100 + i, "Binance News %d" % i, T + i) for i in range(120)]
    cms = write_cms(tmp_path / "cms", [art(1, "Binance Will Delist AAA on 2024-03-10", T)], (),
                    recent, totals={49: 120})
    meta = json.loads((cms / "harvest_meta.json").read_text())
    files49 = meta["catalogs"]["49"]["files"]
    for rel in [r for r in files49 if not r.endswith("page-0001.json")]:
        del files49[rel]
    (cms / "harvest_meta.json").write_text(json.dumps(meta))
    upb = write_upbit(tmp_path / "upbit", [notice(10, ADD % ("비", "BBB"), T)],
                      {10: start_body(T + H)})
    dm, _ = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert dm["harvest_complete"] is False
    old = recent[:50] + [art(99, "Binance News old", ms("2022-12-01T00:00:00Z"))]
    cms = write_cms(tmp_path / "cms2", [art(1, "Binance Will Delist AAA on 2024-03-10", T)], (),
                    old, totals={49: 500})
    meta = json.loads((cms / "harvest_meta.json").read_text())
    files49 = meta["catalogs"]["49"]["files"]
    for rel in [r for r in files49 if not r.endswith(("page-0001.json", "page-0002.json"))]:
        del files49[rel]
    (cms / "harvest_meta.json").write_text(json.dumps(meta))
    dm, _ = nm.build(cms, upb, FakeHl(), FakeProbe(), "x")
    assert dm["harvest_complete"] is True


def test_counts_by_status(tmp_path):
    c161 = [art(1, "Binance Will Delist AAA, GONE, NOB on 2024-03-10", T)]
    probe = FakeProbe(lambda m, s, d: s in ("AAAUSDT", "GONEUSDT"))
    hl = FakeHl(names=("AAA", "NOB"), evidence={"GONE": [], "NOB": None})
    cms, upb = _dirs(tmp_path, c161=c161)
    dm, _ = nm.build(cms, upb, hl, probe, "x")
    c = nm.manifest_counts(dm, DEL)
    assert (c["candidates"], c["unknown"], c["missing"]) == (1, 1, 0)
    assert c["excluded"] == {"no_hl": 1}


def test_upbit_hash_mismatch_refuses(tmp_path):
    cms, upb = _dirs(tmp_path)
    (upb / "detail" / "10.json").write_bytes(b'{"tampered": true}')
    with pytest.raises(ValueError):
        nm.load_upbit(upb)
    (cms / "cat161" / "closing.json").write_bytes(b"{}")
    with pytest.raises(ValueError):
        nm.load_cms(cms)


def test_excluded_events_get_no_venue_requests(tmp_path):
    c161 = [art(1, "Binance Will Delist AAA on 2024-03-10", T),
            art(2, "Binance Will Delist AAA on 2024-03-11", T + H)]
    up = [notice(10, ADD % ("비", "BBB"), T), notice(11, ADD % ("비", "BBB"), T + D),
          notice(12, ADD % ("씨", "CCC"), T), notice(13, ADD % ("디", "DDD"), T)]
    details = {10: start_body(T + H), 11: start_body(T + D + H), 12: start_body(T - H),
               13: "시간 없음"}
    hl, probe = FakeHl(), FakeProbe()
    cms, upb = _dirs(tmp_path, c161=c161, up=up, details=details)
    nm.build(cms, upb, hl, probe, "x")
    assert sorted(hl.calls) == ["AAA", "BBB", "kAAA", "kBBB"]
    assert {u.split("/")[-3] for u in probe.urls} <= {"AAAUSDT", "1000AAAUSDT", "1000000AAAUSDT",
                                                      "1MAAAUSDT", "BBBUSDT", "1000BBBUSDT",
                                                      "1000000BBBUSDT", "1MBBBUSDT"}


def test_not_on_binance_skips_hyperliquid(tmp_path):
    hl, probe = FakeHl(), FakeProbe(lambda m, s, d: False)
    cms, upb = _dirs(tmp_path, c161=[])
    _, um = nm.build(cms, upb, hl, probe, "x")
    assert hl.calls == [] and um["events"][0]["hl"] is None
    assert nm.study_status(um["events"][0], LONG) == "excluded:not_on_binance"


def test_build_report_and_main(tmp_path, capsys):
    c161 = [art(1, "Binance Will Delist AAA, GONE, TST on 2024-03-10", T)]
    up = [notice(10, ADD % ("비", "BBB"), T), notice(11, ADD % ("비", "BBB"), T + 2 * D),
          notice(12, ADD % ("씨", "CCC"), T), notice(13, ADD % ("디", "DDD"), T)]
    details = {10: start_body(T + H), 11: start_body(T + 2 * D + H), 12: start_body(T + H),
               13: "시간 없음"}
    c48 = [art(50, "Binance Will List CCC (CCC)", T + H)]
    cms, upb = _dirs(tmp_path, c161=c161, up=up, details=details, c48=c48)
    probe = FakeProbe(lambda m, s, d: s != "DDDUSDT" and not s.startswith("1")
                      and not (s == "TSTUSDT" and d != "2024-02-29"))
    out = tmp_path / "out"
    rc = nm.main(["build", "--cms", str(cms), "--upbit", str(upb), "--out", str(out),
                  "--code-commit", "abc"], hl_client=FakeHl(evidence={"GONE": []}), probe=probe)
    assert rc == 0
    printed = capsys.readouterr().out
    for name in ("delisting-manifest.json", "upbit-manifest.json"):
        assert nu.sha256_file(out / name) in printed
        assert (out / name).read_bytes() == nu.canonical_bytes(json.loads((out / name).read_text()))
    report = (out / "build-report.txt").read_text(encoding="utf-8")
    for needle in ("never_in_meta GONE binance:1", "already_on_krw BBB upbit:11 (upbit:10)",
                   "binance48_overlap CCC upbit:12 (binance:50)", "unknown DDD upbit:13 no_start",
                   "missing TST binance:1"):
        assert needle in report, needle
    for study in nm.STUDIES:
        assert study in report


def test_main_exit_5_on_needs_review(tmp_path, capsys):
    c161 = [art(1, "Binance Will Delist Ankr (ANKR) on 2024-04-10", T)]
    up = [notice(10, "에이(AAA) KRW 마켓 입금 안내", T)]
    cms, upb = _dirs(tmp_path, c161=c161, up=up)
    rc = nm.main(["build", "--cms", str(cms), "--upbit", str(upb), "--out", str(tmp_path / "o"),
                  "--code-commit", "abc"], hl_client=FakeHl(), probe=FakeProbe())
    assert rc == 5
    err = capsys.readouterr().out
    assert "binance:1" in err and "upbit:10" in err
    assert not (tmp_path / "o" / "delisting-manifest.json").exists()
