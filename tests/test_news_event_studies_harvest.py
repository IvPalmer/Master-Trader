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


def test_refuses_when_archive_limiter_dir_missing(tmp_path):
    def boom(req):
        raise AssertionError("fetcher called")
    rc = nes_harvest.main(["binance", "--harvest", "161,48", "--scan", "49",
                           "--out", str(tmp_path / "raw"),
                           "--limiter-state", str(tmp_path / "no" / "s.json")], fetcher=boom)
    assert rc == 2


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
