"""PIT news archive scheduler (issue #229, Part A): network-free, fake clocks and fetcher."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import na_store  # noqa: E402
from na_fetch import BinanceLimiter, FetchError, Response  # noqa: E402
from na_sources import SOURCES  # noqa: E402
from news_archive import Archive  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "news_archive"
WALL0 = 1793750000.0          # 2026-11-03T23:53:20Z
GIB = 1024 ** 3


class Env:
    def __init__(self, tmp_path, keys, db="archive.sqlite"):
        self.w, self.m = WALL0, 5000.0
        self.free, self.probe = 100 * GIB, True
        self.routes, self.calls = {}, []
        self.tmp = tmp_path
        self.conn = na_store.connect(str(tmp_path / db))
        self.limiter = BinanceLimiter(str(tmp_path / "binance_cms_state.json"))
        self.keys = keys
        self.arc = self.new_archive()

    def new_archive(self):
        return Archive(self.conn, {k: SOURCES[k] for k in self.keys}, self.limiter, self.fetch,
                       lambda: self.w, lambda: self.m, lambda: self.free, lambda: self.probe,
                       sleep=self.advance)

    def advance(self, s):
        self.w += s
        self.m += s

    def fetch(self, spec):
        self.calls.append(spec.url)
        r = self.routes[spec.url]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        return r

    def q(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()

    def gaps(self, source=None, reason=None):
        rows = self.q("SELECT source, reason, gap_start, gap_end, detail FROM gaps ORDER BY gap_pk")
        return [r for r in rows if (source is None or r[0] == source)
                and (reason is None or r[1] == reason)]


def ok(body, status=200, headers=None):
    return Response(status, body if isinstance(body, bytes) else json.dumps(body).encode(),
                    headers or {})


def tree(*ids):
    return ok([{"_id": i, "title": "t" + i, "time": 1793740000000} for i in ids])


def iso(w):
    return na_store.iso_from_epoch(w)


TREE = SOURCES["tree"].url
TREE_BACKFILL = SOURCES["tree"].backfill()[0].url


def flags(env, source="tree"):
    return dict(env.q("SELECT source_item_id, after_gap FROM items WHERE source=?", source))


def test_first_poll_after_start_marks_after_gap(tmp_path):
    env = Env(tmp_path, ["tree"])
    env.arc.startup()
    env.routes[TREE] = tree("1", "2")
    assert env.arc.poll("tree") is True
    env.advance(60)
    env.routes[TREE] = tree("3", "1", "2")
    assert env.arc.poll("tree") is True
    assert flags(env) == {"1": 1, "2": 1, "3": 0}
    assert env.gaps("tree", "outage") == []


def test_outage_longer_than_two_intervals_marks_after_gap_and_closed_outage_gap(tmp_path):
    env = Env(tmp_path, ["tree"])
    env.arc.startup()
    env.routes[TREE] = tree("1")
    env.arc.poll("tree")
    env.advance(60)
    env.routes[TREE] = tree("2", "1")
    env.arc.poll("tree")
    last_ok = env.w
    env.routes[TREE] = FetchError("connection refused")
    env.advance(60)
    assert env.arc.poll("tree") is False
    assert env.gaps("tree", "outage") == []          # 60 s: not yet an outage
    env.advance(120)
    assert env.arc.poll("tree") is False             # 180 s > 2 x 60 s: outage opens
    assert [g[3] for g in env.gaps("tree", "outage")] == [None]
    env.advance(300)
    env.routes[TREE] = tree("3", "2", "1")
    assert env.arc.poll("tree") is True
    assert flags(env)["3"] == 1 and flags(env)["2"] == 0
    [(src, reason, start, end, _)] = env.gaps("tree", "outage")
    assert (start, end) == (iso(last_ok), iso(env.w))
    assert na_store.open_gaps(env.conn) == []


def test_outage_without_failures_still_closed_gap(tmp_path):
    env = Env(tmp_path, ["tree"])
    env.arc.startup()
    env.routes[TREE] = tree("1")
    env.arc.poll("tree")
    t1 = env.w
    env.advance(600)                                  # e.g. the host was paused
    env.routes[TREE] = tree("2", "1")
    env.arc.poll("tree")
    assert flags(env)["2"] == 1
    assert [(g[2], g[3]) for g in env.gaps("tree", "outage")] == [(iso(t1), iso(env.w))]


def test_backoff_doubles_and_caps_at_1800_and_honours_retry_after(tmp_path):
    env = Env(tmp_path, ["tree", "ff_calendar"])
    env.arc.startup()
    env.routes[TREE] = FetchError("down")
    delays = []
    for _ in range(6):
        env.arc.poll("tree")
        delays.append(env.arc.state["tree"].next_due - env.m)
        env.advance(1)
    assert delays == [120, 240, 480, 960, 1800, 1800]
    env.routes[TREE] = tree("1")
    env.arc.poll("tree")
    assert env.arc.state["tree"].next_due - env.m == 60
    env.routes[TREE] = ok(b"slow down", 429, {"Retry-After": "900"})
    env.arc.poll("tree")
    assert env.arc.state["tree"].next_due - env.m == 900
    # a long-interval source never retries sooner than its base interval
    env.routes[SOURCES["ff_calendar"].url] = FetchError("down")
    env.arc.poll("ff_calendar")
    assert env.arc.state["ff_calendar"].next_due - env.m == 6 * 3600


def test_binance_block_suspends_all_binance_sources_and_opens_gaps(tmp_path):
    env = Env(tmp_path, ["binance_listing", "binance_delisting", "tree"])
    env.arc.startup()
    env.routes[SOURCES["binance_listing"].url] = ok(b"<html>captcha</html>")
    assert env.arc.poll("binance_listing") is False
    assert env.limiter.suspended_until(env.w) == env.w + 6 * 3600
    assert sorted(g[0] for g in env.gaps(reason="suspended") if g[3] is None) == [
        "binance_delisting", "binance_listing"]
    [(okflag, status, err)] = env.q("SELECT ok, http_status, error FROM polls")
    assert (okflag, status) == (0, 200) and "block" in err
    n_calls = len(env.calls)
    env.advance(200)
    assert env.arc.poll("binance_delisting") is False   # suspended: no request at all
    assert len(env.calls) == n_calls
    assert len(env.q("SELECT * FROM polls")) == 1


def test_binance_429_json_is_block_signal(tmp_path):
    env = Env(tmp_path, ["binance_delisting"])
    env.arc.startup()
    env.routes[SOURCES["binance_delisting"].url] = ok({"code": "0"}, 429)
    assert env.arc.poll("binance_delisting") is False
    assert env.limiter.suspended_until(env.w) is not None
    assert [g[0] for g in env.gaps(reason="suspended")] == ["binance_delisting"]


def test_tick_rotates_binance_one_request_per_180s(tmp_path):
    env = Env(tmp_path, ["binance_listing", "binance_delisting"])
    fx48 = (FIX / "binance_cms_48.json").read_bytes()
    fx161 = (FIX / "binance_cms_161.json").read_bytes()
    env.routes[SOURCES["binance_listing"].url] = ok(fx48)
    env.routes[SOURCES["binance_delisting"].url] = ok(fx161)
    env.arc.startup()
    times = []
    for _ in range(int(1100 / 5)):
        before = len(env.calls)
        env.arc.tick()
        times += [(env.w, url) for url in env.calls[before:]]
        env.advance(5)
    gaps = [b[0] - a[0] for a, b in zip(times, times[1:])]
    assert len(times) >= 5 and min(gaps) >= 180
    assert {u for _, u in times} == {SOURCES["binance_listing"].url,
                                     SOURCES["binance_delisting"].url}


def test_overflow_triggers_one_backfill_and_closed_gap(tmp_path):
    for backfill, detail in ((tree("c", "d", "e", "b"), "recovered"),
                             (tree("x", "y"), "unrecovered")):
        env = Env(tmp_path, ["tree"], db=detail + ".sqlite")
        env.arc.startup()
        env.routes[TREE] = tree("a", "b")
        env.arc.poll("tree")
        t1 = env.w
        env.advance(60)
        env.routes[TREE] = tree("c", "d")
        env.routes[TREE_BACKFILL] = backfill
        assert env.arc.poll("tree") is True
        assert env.calls.count(TREE_BACKFILL) == 1
        [(src, reason, start, end, got)] = env.gaps("tree", "overflow")
        assert (start, end, got) == (iso(t1), iso(env.w), detail)
        f = flags(env)
        assert f["c"] == 0 and f["d"] == 0
        assert all(f[k] == 1 for k in f if k not in ("a", "b", "c", "d"))
        assert na_store.open_gaps(env.conn) == []


def test_overflow_backfill_pages_stop_at_deadline(tmp_path):
    env = Env(tmp_path, ["upbit"])
    env.arc.startup()
    page = json.loads((FIX / "upbit.json").read_bytes())

    def upbit(*ids):
        p = json.loads(json.dumps(page))
        p["data"]["notices"] = [{**page["data"]["notices"][0], "id": i} for i in ids]
        return ok(p)
    env.routes[SOURCES["upbit"].url] = upbit(1, 2)
    env.arc.poll("upbit")
    env.advance(120)
    env.routes[SOURCES["upbit"].url] = upbit(10, 11)
    for spec, ids in zip(SOURCES["upbit"].backfill(), ((12, 13), (14, 15), (16, 17))):
        env.routes[spec.url] = upbit(*ids)
    env.arc.poll("upbit")
    # pages are 8 s apart and the poll stops issuing requests after 20 s
    assert len(env.calls) == 1 + 1 + 2
    assert [g[4] for g in env.gaps("upbit", "overflow")] == ["unrecovered"]


def test_no_overflow_check_for_fear_greed(tmp_path):
    env = Env(tmp_path, ["fear_greed"])
    env.arc.startup()
    url = SOURCES["fear_greed"].url
    env.routes[url] = ok({"data": [{"value": "26", "timestamp": "1793664000"}]})
    env.arc.poll("fear_greed")
    env.advance(3600)
    env.routes[url] = ok({"data": [{"value": "30", "timestamp": "1793750400"}]})
    assert env.arc.poll("fear_greed") is True
    assert env.gaps(reason="overflow") == [] and len(env.calls) == 2


def test_disk_guard_stops_writes_and_opens_disk_gap(tmp_path):
    env = Env(tmp_path, ["tree"])
    env.arc.startup()
    env.routes[TREE] = tree("1")
    env.arc.poll("tree")
    env.free = 14 * GIB
    env.advance(60)
    env.routes[TREE] = tree("2", "1")
    assert env.arc.poll("tree") is False
    assert "2" not in flags(env)
    assert [g[3] for g in env.gaps("tree", "disk")] == [None]
    assert env.q("SELECT ok, error FROM polls ORDER BY poll_pk DESC LIMIT 1")[0][0] == 0
    env.free = 20 * GIB
    env.advance(60)
    assert env.arc.poll("tree") is True
    assert flags(env)["2"] == 1                       # written while the disk gap was open
    [(_, _, _, end, _)] = env.gaps("tree", "disk")
    assert end == iso(env.w)


def test_clock_jump_opens_clock_gap_for_all_sources(tmp_path):
    env = Env(tmp_path, ["tree", "upbit"])
    env.routes[TREE] = tree("1")
    env.routes[SOURCES["upbit"].url] = ok((FIX / "upbit.json").read_bytes())
    env.arc.startup()
    env.arc.tick()
    env.advance(5)
    env.w += 30                                       # wall clock jumps, monotonic does not
    env.routes[TREE] = tree("2", "1")
    env.arc.state["tree"].next_due = env.m            # make tree due in this tick
    env.arc.tick()
    assert sorted(g[0] for g in env.gaps(reason="clock") if g[3] is None) == ["tree", "upbit"]
    assert flags(env)["2"] == 1
    assert any("jump" in (r[0] or "") for r in env.q("SELECT detail FROM clock_checks"))
    env.advance(5)
    env.arc.tick()                                    # no further jump: gaps close
    assert env.gaps(reason="clock") and all(g[3] for g in env.gaps(reason="clock"))


def test_ntp_unsynchronized_opens_clock_gap_until_healthy(tmp_path):
    env = Env(tmp_path, ["tree"])
    env.routes[TREE] = tree("1")
    env.probe = False
    env.arc.startup()
    env.arc.tick()
    assert [g[3] for g in env.gaps("tree", "clock")] == [None]
    assert env.q("SELECT ntp_synchronized FROM clock_checks") == [(0,)]
    env.advance(5)
    env.arc.tick()
    assert [g[3] for g in env.gaps("tree", "clock")] == [None]
    env.probe = True
    env.advance(5)
    env.arc.tick()
    assert env.gaps("tree", "clock")[0][3] == iso(env.w)


def test_html_200_records_failed_poll(tmp_path):
    env = Env(tmp_path, ["tree", "rss_coindesk"])
    env.arc.startup()
    env.routes[TREE] = ok(b"<html><body>Attention Required! | Cloudflare</body></html>")
    env.routes[SOURCES["rss_coindesk"].url] = ok(b"<html><body>Just a moment...")
    assert env.arc.poll("tree") is False
    assert env.arc.poll("rss_coindesk") is False
    rows = env.q("SELECT source, ok, http_status, error FROM polls ORDER BY poll_pk")
    assert [(r[0], r[1], r[2]) for r in rows] == [("tree", 0, 200), ("rss_coindesk", 0, 200)]
    assert all(r[3] for r in rows)
    assert env.limiter.suspended_until(env.w) is None
    assert env.q("SELECT COUNT(*) FROM items") == [(0,)]


def test_tick_never_raises_when_the_store_fails(tmp_path):
    env = Env(tmp_path, ["tree"])
    env.arc.startup()
    env.routes[TREE] = tree("1")
    env.conn.close()                                  # every write now raises
    env.arc.tick()                                    # logged, not raised


def test_hyperliquid_universe_snapshots_and_transitions(tmp_path):
    env = Env(tmp_path, ["hyperliquid_universe"])
    env.arc.startup()
    url = SOURCES["hyperliquid_universe"].url
    a, b = (ok((FIX / f).read_bytes()) for f in ("hl_meta_a.json", "hl_meta_b.json"))
    for body in (a, a, b, a):
        env.routes[url] = body
        assert env.arc.poll("hyperliquid_universe") is True
        env.advance(300)
    ids = [r[0] for r in env.q("SELECT source_item_id FROM items ORDER BY item_pk")]
    assert ids == ["universe:1",
                   "universe:2", "add:NEWCOIN:2", "remove:ATOM:2", "delisted:ETH:2",
                   "universe:3", "add:ATOM:3", "add:ETH:3", "remove:NEWCOIN:3"]


def test_restart_closes_cleared_gaps_and_records_downtime(tmp_path):
    env = Env(tmp_path, ["tree", "binance_listing"])
    env.arc.startup()
    env.routes[TREE] = tree("1")
    env.arc.poll("tree")
    t_ok = env.w
    env.routes[SOURCES["binance_listing"].url] = ok(b"<html>blocked</html>")
    env.arc.poll("binance_listing")                   # opens a 6 h suspension
    env.free = 1 * GIB
    env.routes[TREE] = tree("2", "1")
    env.advance(60)
    env.arc.poll("tree")                              # opens a disk gap
    na_store.open_gap(env.conn, "tree", "clock", iso(env.w), "test")

    env.advance(600)                                  # process down for 10 minutes
    env.free = 100 * GIB
    env.arc = env.new_archive()
    env.arc.startup()
    still_open = {(g["source"], g["reason"]) for g in na_store.open_gaps(env.conn)}
    assert still_open == {("binance_listing", "suspended")}   # 6 h have not passed
    [(_, _, start, end, _)] = env.gaps("tree", "restart")
    assert (start, end) == (iso(t_ok), iso(env.w))
    assert env.gaps("binance_listing", "restart") == []       # never had an OK poll
    assert env.q("SELECT enabled FROM sources WHERE source='tree'") == [(1,)]

    env.advance(6 * 3600)
    env.arc = env.new_archive()
    env.arc.startup()
    assert na_store.open_gaps(env.conn) == []


# ---- Task 6: CLI, status, unit file ---------------------------------------------------

import news_archive  # noqa: E402

UNIT = ROOT / "research" / "news_archive" / "news-archive.service"


def test_status_lines_report_each_source_and_open_gaps(tmp_path):
    conn = na_store.connect(str(tmp_path / "a.sqlite"))
    now = iso(WALL0)
    na_store.write_sources(conn, [("tree", 60, True), ("upbit", 120, True)], now)
    na_store.record_poll(conn, "tree", iso(WALL0 - 70), iso(WALL0 - 69), True, 200, 2, 2, 0, None)
    na_store.record_poll(conn, "upbit", iso(WALL0 - 400), iso(WALL0 - 399), True, 200, 1, 1, 0, None)
    for k in (300, 200):
        na_store.record_poll(conn, "upbit", iso(WALL0 - k), iso(WALL0 - k + 1), False, 403,
                             None, None, None, "HTTP 403")
    item = na_store.Item("1", iso(WALL0 - 3600), "t", None, None, None, {"id": "1"})
    na_store.upsert_items(conn, "tree", [item], iso(WALL0 - 69), False)
    old = na_store.Item("0", None, "t", None, None, None, {"id": "0"})
    na_store.upsert_items(conn, "tree", [old], iso(WALL0 - 3 * 86400), False)
    na_store.open_gap(conn, "upbit", "suspended", iso(WALL0 - 7200), "test")
    lines = news_archive.status_lines(conn, now)
    tree_line = next(l for l in lines if l.split()[0] == "tree")
    upbit_line = next(l for l in lines if l.split()[0] == "upbit")
    assert "fails 0" in tree_line and "ok24h 1/1" in tree_line
    assert "items 24h 1 / 7d 2 / total 2" in tree_line
    assert iso(WALL0 - 3600) in tree_line
    assert "fails 2" in upbit_line and "ok24h 1/3" in upbit_line
    assert any("gap" in l and "upbit" in l and "suspended" in l and "2.0 h" in l for l in lines)


def test_unit_file_has_resource_limits():
    text = UNIT.read_text()
    sections, cur = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = sections.setdefault(line[1:-1], {})
        elif line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cur[k] = v
    svc, unit = sections["Service"], sections["Unit"]
    for k, v in {"MemoryMax": "256M", "CPUQuota": "25%", "Nice": "10",
                 "IOSchedulingClass": "idle", "Restart": "always", "RestartSec": "30"}.items():
        assert svc[k] == v, k
    assert unit["StartLimitIntervalSec"] == "600" and unit["StartLimitBurst"] == "5"
    assert svc["WorkingDirectory"] == "/home/ubuntu/master-trader/research/news_archive"
    assert svc["ExecStart"] == ("/usr/bin/python3 /home/ubuntu/master-trader/research/"
                                "news_archive/news_archive.py run")
    assert "/etc/dokploy" not in text


def _cli(tmp_path, *args):
    return ["--data-dir", str(tmp_path / "data"), "--log-file", str(tmp_path / "monitor.log"),
            *args]


def test_once_single_source_exits_zero(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_fetch(spec):
        calls.append(spec.url)
        if spec.key == "fear_greed":
            return ok((FIX / "fear_greed.json").read_bytes())
        return ok(b"<html>blocked</html>", 403)
    monkeypatch.setattr(news_archive, "fetch", fake_fetch)
    assert news_archive.main(_cli(tmp_path, "once", "--source", "fear_greed")) == 0
    assert calls == [SOURCES["fear_greed"].url]
    conn = na_store.connect(str(tmp_path / "data" / "archive.sqlite"))
    assert conn.execute("SELECT source FROM items").fetchall() == [("fear_greed",)]
    assert news_archive.main(_cli(tmp_path, "once", "--source", "upbit")) == 1
    out = capsys.readouterr().out
    assert "OK fear_greed" in out and "FAILED upbit" in out
    assert news_archive.main(_cli(tmp_path, "status")) == 0
    assert "fear_greed" in capsys.readouterr().out
    assert (tmp_path / "monitor.log").read_text().count("[news-archive]") >= 2


def test_once_waits_for_the_shared_binance_limiter(tmp_path, monkeypatch):
    clock = {"w": WALL0, "m": 100.0}

    def sleep(s):
        clock["w"] += s
        clock["m"] += s
    monkeypatch.setattr(news_archive, "_runtime",
                        lambda: (lambda: clock["w"], lambda: clock["m"], sleep))
    monkeypatch.setattr(news_archive, "fetch",
                        lambda spec: ok((FIX / "binance_cms_48.json").read_bytes()))
    (tmp_path / "data").mkdir()
    BinanceLimiter(str(tmp_path / "data" / "binance_cms_state.json")).try_acquire(WALL0 - 10)
    assert news_archive.main(_cli(tmp_path, "once", "--source", "binance_listing")) == 0
    assert clock["w"] >= WALL0 + 170


def test_disabled_sources_are_excluded_and_marked(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_ARCHIVE_DISABLE", "upbit, tree")
    monkeypatch.setattr(news_archive, "fetch",
                        lambda spec: ok((FIX / "fear_greed.json").read_bytes()))
    assert news_archive.main(_cli(tmp_path, "once", "--source", "fear_greed")) == 0
    conn = na_store.connect(str(tmp_path / "data" / "archive.sqlite"))
    enabled = dict(conn.execute("SELECT source, enabled FROM sources"))
    assert "upbit" not in enabled and "tree" not in enabled and enabled["fear_greed"] == 1
    assert news_archive.main(_cli(tmp_path, "once", "--source", "upbit")) == 2


def test_second_writer_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(news_archive, "fetch",
                        lambda spec: ok((FIX / "fear_greed.json").read_bytes()))
    (tmp_path / "data").mkdir()
    with news_archive.writer_lock(str(tmp_path / "data")):
        assert news_archive.main(_cli(tmp_path, "once", "--source", "fear_greed")) == 3
