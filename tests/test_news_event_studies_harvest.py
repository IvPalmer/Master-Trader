"""Part C harvesters (#229): full Binance CMS catalogs through the archive's shared limiter,
and the Upbit list and details from the operator's Mac.

Network-free: a fake wall clock that `sleep` advances, a real BinanceLimiter on a tmp
state file, and fake fetchers that serve pages from in-test catalogs.

    python3 -m pytest tests/test_news_event_studies_harvest.py -q
"""
import copy
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_util  # noqa: E402  (puts research/news_archive on sys.path)
import nes_harvest  # noqa: E402
from na_fetch import BinanceLimiter, FetchError, Response  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "news_event_studies"
T0 = 1_790_000_000.0
HOUR_MS = 3_600_000


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def wall(self):
        return self.t

    def sleep(self, s):
        assert s >= 0
        self.t += s


def arts(n, first_id=1000, newest_ms=1_780_000_000_000, prefix="T"):
    """n articles, newest first, one hour apart."""
    return [{"id": first_id + n - 1 - i, "code": "c%d" % (first_id + n - 1 - i),
             "title": "Binance Will Delist %s%d on 2026-01-01" % (prefix, i), "type": 1,
             "releaseDate": newest_ms - i * HOUR_MS} for i in range(n)]


def page_body(catalog_id, articles, total, name="Delisting"):
    j = json.loads((FIX / "cms_page.json").read_text(encoding="utf-8"))
    cat = j["data"]["catalogs"][0]
    cat.update(catalogId=catalog_id, catalogName=name, articles=articles)
    if total is None:
        del cat["total"]
    else:
        cat["total"] = total
    return json.dumps(j).encode()


class FakeCms:
    """Serves CMS pages from `catalogs` {id: [articles newest first]}."""

    def __init__(self, clock, catalogs, totals=None, names=None):
        self.clock, self.catalogs = clock, catalogs
        self.totals, self.names = totals or {}, names or {}
        self.calls = []          # (wall time, catalog id, page no)
        self.hooks = {}          # call index (0-based) -> fn(self), run before serving
        self.overrides = {}      # call index -> Response or Exception

    def __call__(self, req):
        assert req.method == "GET"
        q = parse_qs(urlparse(req.url).query)
        cid, page = int(q["catalogId"][0]), int(q["pageNo"][0])
        assert int(q["pageSize"][0]) == 50
        i = len(self.calls)
        self.calls.append((self.clock.wall(), cid, page))
        if i in self.hooks:
            self.hooks[i](self)
        if i in self.overrides:
            o = self.overrides[i]
            if isinstance(o, Exception):
                raise o
            return o
        items = self.catalogs[cid]
        total = self.totals.get(cid, len(items))
        body = page_body(cid, items[(page - 1) * 50:page * 50], total,
                         self.names.get(cid, "Delisting"))
        return Response(200, body, {})

    def pages(self):
        return [p for _, _, p in self.calls]


def harvester(tmp_path, fake, clock, limiter=None):
    limiter = limiter or BinanceLimiter(str(tmp_path / "state.json"), boot_id=None,
                                        mono=clock.wall)
    out = tmp_path / "raw"
    return nes_harvest.CmsHarvester(limiter, fake, clock.wall, clock.sleep, out), out


def test_full_harvest_requests_pages_then_closing(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    h, out = harvester(tmp_path, fake, clock)
    res = h.harvest(161)
    assert fake.pages() == [1, 2, 3, 1]
    assert res["completeness"] == {"unique": 120, "total": 120, "total_reported": True,
                                   "shortfall": 0}
    names = sorted(p.name for p in (out / "cat161").iterdir())
    assert names == ["closing.json", "page-0001.json", "page-0002.json", "page-0003.json"]
    meta = json.loads((out / "harvest_meta.json").read_text())
    files = meta["catalogs"]["161"]["files"]
    assert files["cat161/page-0002.json"] == nes_util.sha256_file(out / "cat161" / "page-0002.json")
    assert meta["catalogs"]["161"]["catalog_name"] == "Delisting"


def test_new_article_mid_harvest_is_not_a_shortfall(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    new = {"id": 5000, "code": "c5000", "title": "Binance Will Delist NEW on 2026-01-02",
           "type": 1, "releaseDate": 1_780_000_000_000 + HOUR_MS}
    fake.hooks[1] = lambda f: f.catalogs[161].insert(0, new)   # published after page 1
    h, _ = harvester(tmp_path, fake, clock)
    res = h.harvest(161)
    assert fake.pages() == [1, 2, 3, 1]
    assert res["completeness"] == {"unique": 121, "total": 121, "total_reported": True,
                                   "shortfall": 0}


def test_short_harvest_is_a_shortfall(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(119)}, totals={161: 120})   # page 3 returns 19
    h, _ = harvester(tmp_path, fake, clock)
    res = h.harvest(161)
    assert fake.pages() == [1, 2, 3, 1]
    assert res["completeness"]["shortfall"] == 1
    assert res["completeness"]["unique"] == 119


def test_no_total_reported(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(100)}, totals={161: None})
    h, out = harvester(tmp_path, fake, clock)
    res = h.harvest(161)
    assert fake.pages() == [1, 2, 3, 1]        # pages while full, then closing
    assert res["completeness"] == {"unique": 100, "total": None, "total_reported": False,
                                   "shortfall": 0}


def test_requests_spaced_540s_and_each_acquired(tmp_path):
    clock = Clock()
    limiter = BinanceLimiter(str(tmp_path / "state.json"), boot_id=None, mono=clock.wall)
    assert limiter.try_acquire(clock.wall())       # the archive just polled
    fake = FakeCms(clock, {161: arts(120)})
    h, _ = harvester(tmp_path, fake, clock, limiter)
    h.harvest(161)
    times = [t for t, _, _ in fake.calls]
    assert times[0] >= T0 + 180                    # waited for the archive's slot
    assert all(b - a >= 540 for a, b in zip(times, times[1:]))
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_request"] == times[-1]      # every request went through the limiter


def test_block_signal_suspends_shared_limiter_and_second_aborts(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[1] = Response(200, b"<html>captcha</html>", {})
    fake.overrides[2] = Response(429, b"", {})
    h, out = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    state = json.loads((tmp_path / "state.json").read_text())
    blocked_at = fake.calls[1][0]
    assert state["suspended_until"] >= blocked_at + 6 * 3600
    assert fake.calls[2][0] >= blocked_at + 6 * 3600    # waited out the first suspension
    assert len(fake.calls) == 3
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert meta["aborted"] == "second suspension"
    assert meta["catalogs"]["161"]["aborted"] == "second suspension"


def test_suspension_by_another_caller_counts_once(tmp_path):
    clock = Clock()
    limiter = BinanceLimiter(str(tmp_path / "state.json"), boot_id=None, mono=clock.wall)
    limiter.suspend(clock.wall())                  # the archive was blocked
    fake = FakeCms(clock, {161: arts(120)})
    h, out = harvester(tmp_path, fake, clock, limiter)
    h.harvest(161)
    assert fake.calls[0][0] >= T0 + 6 * 3600
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert len(meta["suspensions"]) == 1 and meta["aborted"] is None


def test_transient_error_retries_same_page_at_next_slot(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[1] = FetchError("timeout")
    fake.overrides[2] = Response(502, b'{"code":"x"}', {})
    h, out = harvester(tmp_path, fake, clock)
    res = h.harvest(161)
    assert fake.pages() == [1, 2, 2, 2, 3, 1]
    assert res["completeness"]["shortfall"] == 0
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert len(meta["catalogs"]["161"]["errors"]) == 2


def test_repeated_errors_on_one_page_abort(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    for i in range(1, 1 + nes_harvest.MAX_PAGE_FAILURES):
        fake.overrides[i] = Response(500, b'{"code":"x"}', {})
    h, out = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    assert json.loads((out / "harvest_meta.json").read_text())["aborted"] == "page errors"


def test_72h_without_completing_aborts(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.hooks[1] = lambda f: clock.sleep(nes_harvest.MAX_HARVEST_S)
    h, out = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    assert len(fake.calls) == 2
    assert json.loads((out / "harvest_meta.json").read_text())["aborted"] == "72 h without completing"


class Crash(Exception):
    pass


def test_resume_skips_saved_pages(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[2] = Crash()
    h, _ = harvester(tmp_path, fake, clock)
    with pytest.raises(Crash):
        h.harvest(161)
    fake2 = FakeCms(clock, {161: arts(120)})
    h2, _ = harvester(tmp_path, fake2, clock)
    res = h2.harvest(161)
    assert fake2.pages() == [3, 1]
    assert res["completeness"]["unique"] == 120


def test_scan_stops_at_window_start(tmp_path):
    clock = Clock()
    start = nes_util.WINDOW_START_MS
    # 200 articles; index 70 (page 2) is the first one before the window start
    items = arts(200, newest_ms=start + 69 * HOUR_MS + 1)
    fake = FakeCms(clock, {49: items}, names={49: "Latest Binance News"})
    h, out = harvester(tmp_path, fake, clock)
    res = h.scan(49, start)
    assert fake.pages() == [1, 2]
    assert res["catalog_name"] == "Latest Binance News"
    assert not (out / "cat49" / "closing.json").exists()
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert meta["catalogs"]["49"]["completeness"] is None


def _boom(req):
    raise AssertionError("fetcher called")


def test_refuses_when_archive_limiter_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nes_util, "ARCHIVE_LIMITER_STATE", tmp_path / "no" / "s.json")
    rc = nes_harvest.main(["binance", "--harvest", "161,48", "--scan", "49",
                           "--out", str(tmp_path / "raw")], fetcher=_boom)
    assert rc == 2


def test_no_limiter_override_flag(tmp_path):
    with pytest.raises(SystemExit):
        nes_harvest.main(["binance", "--harvest", "161", "--out", str(tmp_path / "raw"),
                          "--limiter-state", str(tmp_path / "s.json")], fetcher=_boom)


def test_default_limiter_is_the_archives():
    assert nes_util.ARCHIVE_LIMITER_STATE == (
        ROOT / "research" / "news_archive" / "data" / "binance_cms_state.json")


def test_canonical_bytes_sorted_compact_utf8():
    assert nes_util.canonical_bytes({"b": 1, "a": "é"}) == b'{"a":"\xc3\xa9","b":1}\n'


def test_time_helpers():
    assert nes_util.iso_ms(1709294430123) == "2024-03-01T12:00:30.123000+00:00"
    assert nes_util.ms_from_iso("2024-03-01T21:00:30.123+09:00") == 1709294430123
    assert nes_util.utc_date(1709337599999) == "2024-03-01"
    assert nes_util.WINDOW_END_MS - nes_util.WINDOW_START_MS == 1400 * nes_util.DAY_MS


# ---- Upbit (operator's Mac) ---------------------------------------------------------

def upbit_notice(nid, first_listed_at, title="테스트(TST) KRW 마켓 디지털 자산 추가"):
    return {"listed_at": first_listed_at, "first_listed_at": first_listed_at, "id": nid,
            "uuid": str(nid), "title": title, "category": "거래",
            "need_new_badge": False, "need_update_badge": False}


class FakeUpbit:
    """Serves the Upbit trade list (20 per page, newest first) and notice details."""

    def __init__(self, clock, notices, fixed=None, total_count=None):
        self.clock, self.notices, self.fixed = clock, notices, fixed or []
        self.total_count = total_count
        self.calls = []        # (wall, "list", page) or (wall, "detail", id)
        self.overrides = {}

    def __call__(self, req):
        assert req.method == "GET"
        i = len(self.calls)
        u = urlparse(req.url)
        if u.path.rstrip("/").endswith("/announcements"):
            q = parse_qs(u.query)
            assert q["category"] == ["trade"] and q["per_page"] == ["20"]
            page = int(q["page"][0])
            self.calls.append((self.clock.wall(), "list", page))
            j = json.loads((FIX / "upbit_list_page.json").read_text(encoding="utf-8"))
            n = len(self.notices)
            j["data"].update(notices=self.notices[(page - 1) * 20:page * 20],
                             fixed_notices=self.fixed,
                             total_count=n if self.total_count is None else self.total_count,
                             total_pages=max(1, -(-n // 20)))
        else:
            nid = int(u.path.rstrip("/").rsplit("/", 1)[1])
            self.calls.append((self.clock.wall(), "detail", nid))
            j = json.loads((FIX / "upbit_detail.json").read_text(encoding="utf-8"))
            n = next(x for x in self.notices if x["id"] == nid)
            j["data"].update(id=nid, title=n["title"], first_listed_at=n["first_listed_at"],
                             listed_at=n["listed_at"])
        if i in self.overrides:
            return self.overrides[i]
        return Response(200, json.dumps(j, ensure_ascii=False).encode(), {})


def upbit_harvester(tmp_path, fake, clock):
    out = tmp_path / "upbit"
    return nes_harvest.UpbitHarvester(fake, clock.wall, clock.sleep, out, "test-host"), out


WIN = (nes_util.WINDOW_START_MS - nes_util.DAY_MS, nes_util.WINDOW_END_MS + nes_util.DAY_MS)


def test_upbit_pages_spaced_10s_then_closing(tmp_path):
    clock = Clock()
    notices = [upbit_notice(5000 - i, "2024-03-01T21:00:00+09:00") for i in range(45)]
    fake = FakeUpbit(clock, notices)
    h, out = upbit_harvester(tmp_path, fake, clock)
    res = h.run(*WIN)
    lists = [p for _, kind, p in fake.calls if kind == "list"]
    assert lists == [1, 2, 3, 1]
    assert [k for _, k, _ in fake.calls[:4]] == ["list"] * 4      # list first, then details
    times = [t for t, _, _ in fake.calls]
    assert all(b - a >= nes_harvest.UPBIT_GAP_S for a, b in zip(times, times[1:]))
    assert res["list"]["shortfall"] == 0 and res["list"]["unique"] == 45
    assert sorted(p.name for p in (out / "list").iterdir()) == [
        "closing.json", "page-01.json", "page-02.json", "page-03.json"]


def test_upbit_block_stops_after_one_request_no_retry(tmp_path):
    clock = Clock()
    fake = FakeUpbit(clock, [upbit_notice(1, "2024-03-01T21:00:00+09:00")])
    fake.overrides[0] = Response(429, b"error code: 1015", {})
    h, out = upbit_harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestBlocked):
        h.run(*WIN)
    assert len(fake.calls) == 1
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert meta["blocked"]


def test_upbit_error_stops_without_retry(tmp_path):
    clock = Clock()
    fake = FakeUpbit(clock, [upbit_notice(1, "2024-03-01T21:00:00+09:00")])
    fake.overrides[1] = Response(500, b'{"success":false}', {})
    h, out = upbit_harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestBlocked):
        h.run(*WIN)
    assert len(fake.calls) == 2
    assert json.loads((out / "harvest_meta.json").read_text())["blocked"].startswith("error")


def test_upbit_details_only_inside_window_margin(tmp_path):
    clock = Clock()
    notices = [upbit_notice(4, "2026-11-02T09:00:00+09:00"),     # 2026-11-02T00:00Z no
               upbit_notice(3, "2026-11-02T08:59:00+09:00"),     # 2026-11-01T23:59Z yes
               upbit_notice(2, "2022-12-31T09:00:00+09:00"),     # 2022-12-31T00:00Z yes
               upbit_notice(1, "2022-12-31T08:59:00+09:00")]     # 2022-12-30T23:59Z no
    fake = FakeUpbit(clock, notices)
    h, out = upbit_harvester(tmp_path, fake, clock)
    res = h.run(*WIN)
    assert sorted(n for _, k, n in fake.calls if k == "detail") == [2, 3]
    assert sorted(res["detail_ids"]) == ["2", "3"]
    assert sorted(p.name for p in (out / "detail").iterdir()) == ["2.json", "3.json"]


def test_upbit_meta_has_host_label_and_hashes(tmp_path):
    clock = Clock()
    fake = FakeUpbit(clock, [upbit_notice(7, "2024-03-01T21:00:00+09:00")])
    h, out = upbit_harvester(tmp_path, fake, clock)
    h.run(*WIN)
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert meta["host_label"] == "test-host"
    assert meta["started_at"] and meta["finished_at"] and meta["blocked"] is None
    assert set(meta["files"]) == {"list/page-01.json", "list/closing.json", "detail/7.json"}
    for rel, sha in meta["files"].items():
        assert sha == nes_util.sha256_file(out / rel)


def test_upbit_completeness_ignores_fixed_notices(tmp_path):
    clock = Clock()
    notices = [upbit_notice(10 + i, "2024-03-01T21:00:00+09:00") for i in range(3)]
    fake = FakeUpbit(clock, notices, fixed=[upbit_notice(99, "2023-06-01T09:00:00+09:00")],
                     total_count=4)
    h, _ = upbit_harvester(tmp_path, fake, clock)
    res = h.run(*WIN)
    assert res["list"] == {"unique": 3, "total": 4, "total_reported": True, "shortfall": 1}
    assert 99 not in [n for _, k, n in fake.calls if k == "detail"]


def test_upbit_resume_skips_saved_files(tmp_path):
    clock = Clock()
    notices = [upbit_notice(20 + i, "2024-03-01T21:00:00+09:00") for i in range(3)]
    fake = FakeUpbit(clock, notices)
    fake.overrides[3] = Response(403, b"<html>Attention Required</html>", {})
    h, _ = upbit_harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestBlocked):
        h.run(*WIN)                       # list, closing, detail 20 saved; detail 21 blocked
    fake2 = FakeUpbit(clock, notices)
    h2, _ = upbit_harvester(tmp_path, fake2, clock)
    res = h2.run(*WIN)
    assert [(k, n) for _, k, n in fake2.calls] == [("list", 1), ("detail", 21), ("detail", 22)]
    assert sorted(res["detail_ids"]) == ["20", "21", "22"]


def test_parse_upbit_detail_fixture():
    d = nes_harvest.parse_upbit_detail((FIX / "upbit_detail.json").read_bytes())
    assert d["id"] == 9003 and d["first_listed_at"] == "2024-03-01T21:00:30+09:00"
    assert "거래지원 개시 시점" in d["body"]
    assert nes_harvest.UPBIT_BODY_KEY == "body"
    assert nes_harvest.UPBIT_DETAIL_URL % 6714 == (
        "https://api-manager.upbit.com/api/v1/announcements/6714")


# ---- Codex review of #238 (round 1) -------------------------------------------------

def test_fetch_error_with_http_status_is_a_block(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[1] = FetchError("response larger than 5000000 bytes", 429)
    h, out = harvester(tmp_path, fake, clock)
    h.harvest(161)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["suspended_until"] >= fake.calls[1][0] + 6 * 3600
    assert fake.calls[2][0] >= fake.calls[1][0] + 6 * 3600


def test_own_gap_survives_resume(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[2] = Crash()
    h, _ = harvester(tmp_path, fake, clock)
    with pytest.raises(Crash):
        h.harvest(161)
    fake2 = FakeCms(clock, {161: arts(120)})
    h2, _ = harvester(tmp_path, fake2, clock)
    h2.harvest(161)
    assert fake2.calls[0][0] - fake.calls[2][0] >= 540


class SteppingClock(Clock):
    """Wall time that can step independently of a monotonic clock."""

    def __init__(self, t=T0):
        super().__init__(t)
        self.m = 1000.0

    def mono(self):
        return self.m

    def sleep(self, s):
        assert s >= 0
        self.t += s
        self.m += s


def test_wall_step_does_not_shorten_own_gap(tmp_path):
    clock = SteppingClock()
    limiter = BinanceLimiter(str(tmp_path / "state.json"), boot_id="b1", mono=clock.mono)
    fake = FakeCms(clock, {161: arts(120)})
    fake.hooks[0] = lambda f: setattr(clock, "t", clock.t + 3600)    # wall jumps +1 h
    out = tmp_path / "raw"
    h = nes_harvest.CmsHarvester(limiter, fake, clock.wall, clock.sleep, out, mono=clock.mono)
    h.harvest(161)
    assert fake.calls[1][0] - fake.calls[0][0] >= 540 + 3600    # mono gap held


def test_aborted_harvest_cannot_resume(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[1] = Response(200, b"<html>captcha</html>", {})
    fake.overrides[2] = Response(429, b"", {})
    h, out = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    fake2 = FakeCms(clock, {161: arts(120)})
    h2, _ = harvester(tmp_path, fake2, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h2.harvest(161)
    assert fake2.calls == []


def test_wall_step_during_suspension_counts_once(tmp_path):
    clock = SteppingClock()
    limiter = BinanceLimiter(str(tmp_path / "state.json"), boot_id="b1", mono=clock.mono)
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[1] = Response(200, b"<html>captcha</html>", {})
    out = tmp_path / "raw"

    def crash_on_long_sleep(s):
        if s > 3600:
            raise Crash()
        clock.sleep(s)
    h = nes_harvest.CmsHarvester(limiter, fake, clock.wall, crash_on_long_sleep, out,
                                 mono=clock.mono)
    with pytest.raises(Crash):
        h.harvest(161)
    clock.t += 120                                   # NTP step while restarting
    fake2 = FakeCms(clock, {161: arts(120)})
    h2 = nes_harvest.CmsHarvester(limiter, fake2, clock.wall, clock.sleep, out, mono=clock.mono)
    h2.harvest(161)
    meta = json.loads((out / "harvest_meta.json").read_text())
    assert len(meta["suspensions"]) == 1 and meta["aborted"] is None


def test_closing_growth_is_reconciled_not_a_shortfall(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    newer = arts(51, first_id=9000, newest_ms=1_790_000_000_000, prefix="N")
    fake.hooks[3] = lambda f: f.catalogs.__setitem__(161, newer + f.catalogs[161])
    h, out = harvester(tmp_path, fake, clock)
    res = h.harvest(161)
    assert fake.pages() == [1, 2, 3, 1, 2]
    assert res["completeness"] == {"unique": 171, "total": 171, "total_reported": True,
                                   "shortfall": 0}
    assert (out / "cat161" / "closing-02.json").exists()


def test_scan_continues_past_short_interior_page(tmp_path):
    clock = Clock()
    start = nes_util.WINDOW_START_MS
    items = arts(200, newest_ms=start + 300 * HOUR_MS)       # all inside the window
    fake = FakeCms(clock, {49: items}, names={49: "Latest Binance News"})
    body = page_body(49, items[:49], 200, "Latest Binance News")
    fake.overrides[0] = Response(200, body, {})              # page 1 returns 49
    h, _ = harvester(tmp_path, fake, clock)
    h.scan(49, start)
    assert fake.pages() == [1, 2, 3, 4]


def test_72h_deadline_caps_waits_and_is_inclusive(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    fake.hooks[1] = lambda f: clock.sleep(71 * 3600 - (clock.t - f.calls[0][0]))
    fake.overrides[1] = Response(200, b"<html>captcha</html>", {})
    h, out = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    first = fake.calls[0][0]
    assert len(fake.calls) == 2
    assert clock.t == first + nes_harvest.MAX_HARVEST_S
    assert json.loads((out / "harvest_meta.json").read_text())["aborted"] == "72 h without completing"


def test_refuses_when_limiter_state_file_missing(tmp_path, monkeypatch):
    (tmp_path / "d").mkdir()
    monkeypatch.setattr(nes_util, "ARCHIVE_LIMITER_STATE", tmp_path / "d" / "s.json")
    rc = nes_harvest.main(["binance", "--harvest", "161", "--out", str(tmp_path / "raw")],
                          fetcher=_boom)
    assert rc == 2


def test_malformed_page_is_a_recorded_error(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    j = json.loads(page_body(161, [], 120))
    j["data"]["catalogs"][0]["articles"] = 42
    fake.overrides[1] = Response(200, json.dumps(j).encode(), {})
    h, out = harvester(tmp_path, fake, clock)
    h.harvest(161)
    assert fake.pages() == [1, 2, 2, 3, 1]
    assert len(json.loads((out / "harvest_meta.json").read_text())["catalogs"]["161"]["errors"]) == 1


def test_upbit_gap_survives_resume(tmp_path):
    clock = Clock()
    notices = [upbit_notice(30 + i, "2024-03-01T21:00:00+09:00") for i in range(2)]
    fake = FakeUpbit(clock, notices)
    fake.overrides[2] = Response(403, b"<html>Attention Required</html>", {})
    h, _ = upbit_harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestBlocked):
        h.run(*WIN)
    fake2 = FakeUpbit(clock, notices)
    h2, _ = upbit_harvester(tmp_path, fake2, clock)
    h2.run(*WIN)
    assert fake2.calls[0][0] - fake.calls[2][0] >= nes_harvest.UPBIT_GAP_S


# ---- Codex review of #238 (round 2) -------------------------------------------------

def test_resuspension_before_acquire_is_a_second_suspension(tmp_path):
    clock = Clock()
    limiter = BinanceLimiter(str(tmp_path / "state.json"), boot_id=None, mono=clock.wall)
    limiter.suspend(clock.wall())                  # the archive was blocked
    done = []

    def sleep(s):
        clock.sleep(s)
        if s > 3600 and not done:                  # the archive is blocked again on expiry
            done.append(1)
            limiter.suspend(clock.wall())
    fake = FakeCms(clock, {161: arts(120)})
    h = nes_harvest.CmsHarvester(limiter, fake, clock.wall, sleep, tmp_path / "raw")
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    assert fake.calls == []
    meta = json.loads((tmp_path / "raw" / "harvest_meta.json").read_text())
    assert meta["aborted"] == "second suspension" and len(meta["suspensions"]) == 2


def test_two_counted_suspensions_refuse_even_without_saved_abort(tmp_path):
    out = tmp_path / "raw"
    out.mkdir()
    (out / "harvest_meta.json").write_text(json.dumps({
        "first_request": None, "first_request_s": None, "last_request_s": None,
        "suspensions": ["a", "b"], "suspension_untils": [1.0, 30000.0], "aborted": None,
        "catalogs": {}}))
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    h, _ = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    assert fake.calls == []


def test_forward_step_across_restart_keeps_mono_gap(tmp_path):
    clock = SteppingClock()
    limiter = BinanceLimiter(str(tmp_path / "state.json"), boot_id="b1", mono=clock.mono)
    out = tmp_path / "raw"
    fake = FakeCms(clock, {161: arts(120)})
    fake.overrides[2] = Crash()
    h = nes_harvest.CmsHarvester(limiter, fake, clock.wall, clock.sleep, out,
                                 mono=clock.mono, boot_id="b1")
    with pytest.raises(Crash):
        h.harvest(161)
    clock.t += 3600                                # wall steps forward during the restart
    fake2 = FakeCms(clock, {161: arts(120)})
    h2 = nes_harvest.CmsHarvester(limiter, fake2, clock.wall, clock.sleep, out,
                                  mono=clock.mono, boot_id="b1")
    h2.harvest(161)
    assert fake2.calls[0][0] - fake.calls[2][0] >= 3600 + 540


def test_upbit_forward_step_within_run_keeps_gap(tmp_path):
    clock = SteppingClock()
    notices = [upbit_notice(40 + i, "2024-03-01T21:00:00+09:00") for i in range(3)]
    fake = FakeUpbit(clock, notices)
    monos = []

    def fetcher(req):
        monos.append(clock.mono())
        r = fake(req)
        clock.t += 3600                            # wall steps forward after each request
        return r
    h = nes_harvest.UpbitHarvester(fetcher, clock.wall, clock.sleep, tmp_path / "u", "t",
                                   mono=clock.mono)
    h.run(*WIN)
    assert all(b - a >= nes_harvest.UPBIT_GAP_S for a, b in zip(monos, monos[1:]))


def test_completion_after_deadline_aborts(tmp_path):
    clock = Clock()
    fake = FakeCms(clock, {161: arts(120)})
    # the closing request starts before the deadline and its response arrives after it
    fake.hooks[3] = lambda f: clock.sleep(f.calls[0][0] + nes_harvest.MAX_HARVEST_S + 1
                                          - clock.t)
    h, out = harvester(tmp_path, fake, clock)
    with pytest.raises(nes_harvest.HarvestAborted):
        h.harvest(161)
    assert json.loads((out / "harvest_meta.json").read_text())["aborted"] == "72 h without completing"
