#!/usr/bin/env python3
"""PIT news archive service (#229 Part A, spec §4).

One process, one sequential scheduler loop, no threads. Each v1 source is polled at its
interval; every item is stored with our own received_at, the source-claimed publish
time and the raw payload. Coverage holes are recorded in `gaps`, and items written
across one carry after_gap = 1, so readers can apply the PIT rule (na_store.pit_valid).

The archive never trades and nothing in the fleet imports it. Stdlib only.
"""
import argparse
import fcntl
import gzip
import json
import logging
import logging.handlers
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from email.utils import parsedate_to_datetime

import na_store
from na_fetch import BinanceLimiter, fetch, is_block_signal
from na_sources import SOURCES, diff_universe, universe_names

MAX_BACKOFF_S = 1800
DEADLINE_S = 20.0
DISK_MIN_BYTES = 15 * 1024 ** 3
CLOCK_JUMP_S = 2.0
CLOCK_CHECK_S = 3600.0
PRUNE_S = 86400.0
LIMITER_RETRY_S = 15.0
MAX_RETRY_AFTER_S = 6 * 3600
HL_KEY = "hyperliquid_universe"

LOG = logging.getLogger("news-archive")


class PollError(Exception):
    pass


@dataclass
class SourceState:
    next_due: float            # monotonic seconds
    failures: int = 0
    last_ok: "float | None" = None   # wall seconds of the last OK poll (any process)
    ok_since_start: bool = False


def _retry_after(headers, now_w):
    value = None
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            value = str(v).strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - now_w)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


class Archive:
    def __init__(self, conn, sources, limiter, fetcher, wall, mono, free_bytes, clock_probe,
                 sleep=time.sleep, log=None):
        self.conn = conn
        self.sources = dict(sources)
        self.limiter = limiter
        self.fetcher = fetcher
        self.wall, self.mono = wall, mono
        self.free_bytes = free_bytes
        self.clock_probe = clock_probe
        self.sleep = sleep
        self.log = log or LOG.info
        self.state = {}
        self.started_w = None
        self._offset = None
        self._probe_bad = False
        self._next_clock_check = None
        self._next_prune = None

    # ---- helpers -----------------------------------------------------------------------

    def _now(self):
        return na_store.iso_from_epoch(self.wall())

    def _q1(self, sql, *args):
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    def _backoff(self, spec, failures):
        return max(spec.interval_s, min(spec.interval_s * 2 ** failures, MAX_BACKOFF_S))

    def _outage_start(self, st):
        if st.ok_since_start:
            return st.last_ok
        return max(st.last_ok or self.started_w, self.started_w)

    # ---- startup -----------------------------------------------------------------------

    def startup(self):
        now_w = self.wall()
        now = na_store.iso_from_epoch(now_w)
        self.started_w = now_w
        self._offset = now_w - self.mono()
        self._next_clock_check = self._next_prune = self.mono()
        na_store.write_sources(
            self.conn, [(k, s.interval_s, True) for k, s in self.sources.items()], now)
        for key, spec in self.sources.items():
            last_ok = (self._q1("SELECT MAX(finished_at) FROM polls WHERE source=? AND ok=1", key)
                       or self._q1("SELECT MAX(received_at) FROM items WHERE source=?", key))
            if last_ok:
                na_store.record_closed_gap(self.conn, key, "restart", last_ok, now,
                                           "process restart")
            st = SourceState(next_due=self.mono())
            st.last_ok = na_store.parse_iso(last_ok).timestamp() if last_ok else None
            recent = self.conn.execute(
                "SELECT ok, finished_at FROM polls WHERE source=? ORDER BY poll_pk DESC LIMIT 50",
                (key,)).fetchall()
            for ok, _ in recent:
                if ok:
                    break
                st.failures += 1
            if recent:
                last_poll = na_store.parse_iso(recent[0][1]).timestamp()
                wait = spec.interval_s if not st.failures else self._backoff(spec, st.failures)
                st.next_due = self.mono() + max(0.0, last_poll + wait - now_w)
            self.state[key] = st
        self._close_cleared_gaps(now)
        self.log("startup: %d sources, %d open gaps" % (
            len(self.sources), len(na_store.open_gaps(self.conn))))

    def _close_cleared_gaps(self, now):
        disk_ok = self.free_bytes() >= DISK_MIN_BYTES
        suspended = self.limiter.suspended_until(self.wall()) is not None
        clock_ok = self.clock_probe() is not False
        for g in na_store.open_gaps(self.conn):
            src, reason = g["source"], g["reason"]
            cleared = (src not in self.sources
                       or (reason == "disk" and disk_ok)
                       or (reason == "suspended" and not suspended)
                       or (reason == "clock" and clock_ok))
            if cleared:
                na_store.close_gap(self.conn, src, reason, now)

    # ---- clock and housekeeping --------------------------------------------------------

    def _clock_gap_all(self, now, detail):
        for key in self.sources:
            na_store.open_gap(self.conn, key, "clock", now, detail)

    def _check_clock(self):
        now_w, now_m = self.wall(), self.mono()
        now = na_store.iso_from_epoch(now_w)
        offset = now_w - now_m
        drift = offset - self._offset
        self._offset = offset
        jumped = abs(drift) > CLOCK_JUMP_S
        if jumped:
            detail = "jump %+.3f s wall vs monotonic" % drift
            with na_store.transaction(self.conn):
                self.conn.execute("INSERT INTO clock_checks VALUES (?,?,?,?)",
                                  (now, None, offset, detail))
                self._clock_gap_all(now, detail)
            self.log("clock: " + detail)
        hourly = now_m >= self._next_clock_check
        if hourly or self._probe_bad:
            probe = self.clock_probe()
            if hourly:
                self._next_clock_check = now_m + CLOCK_CHECK_S
                self.conn.execute(
                    "INSERT INTO clock_checks VALUES (?,?,?,?)",
                    (now, None if probe is None else int(bool(probe)), offset,
                     None if probe is not False else "NTP not synchronized"))
            self._probe_bad = probe is False
            if self._probe_bad:
                self._clock_gap_all(now, "NTP not synchronized")
        if not jumped and not self._probe_bad:
            for key in self.sources:
                na_store.close_gap(self.conn, key, "clock", now)

    def tick(self):
        try:
            self._check_clock()
        except Exception as e:  # noqa: BLE001 - the loop must never die
            self.log("clock check failed: %s: %s" % (type(e).__name__, e))
        for key in list(self.sources):
            try:
                if self.mono() >= self.state[key].next_due:
                    self.poll(key)
            except Exception as e:  # noqa: BLE001
                self.log("%s: poll crashed: %s: %s" % (key, type(e).__name__, e))
        try:
            if self.mono() >= self._next_prune:
                self._next_prune = self.mono() + PRUNE_S
                n = na_store.prune_polls(self.conn, self._now())
                if n:
                    self.log("pruned %d polls rows older than 180 days" % n)
        except Exception as e:  # noqa: BLE001
            self.log("prune failed: %s: %s" % (type(e).__name__, e))

    # ---- one poll ----------------------------------------------------------------------

    def _suspend_binance(self, now_w, detail):
        self.limiter.suspend(now_w)
        now = na_store.iso_from_epoch(now_w)
        for key, spec in self.sources.items():
            if spec.binance:
                na_store.open_gap(self.conn, key, "suspended", now, detail)

    def _latest_universe(self, key):
        row = self.conn.execute(
            "SELECT raw_json FROM items WHERE source=? AND substr(source_item_id,1,9)='universe:'"
            " ORDER BY item_pk DESC LIMIT 1", (key,)).fetchone()
        seq = self._q1("SELECT COUNT(*) FROM items WHERE source=?"
                       " AND substr(source_item_id,1,9)='universe:'", key)
        if row is None:
            return None, seq
        return universe_names(na_store.Item("", None, None, None, None, None,
                                            json.loads(row[0]))), seq

    def _universe_items(self, key, items):
        [snap] = items
        cur = universe_names(snap)
        prev, seq = self._latest_universe(key)
        if prev == cur:
            return []
        seq += 1
        out = [replace(snap, source_item_id="universe:%d" % seq)]
        out += diff_universe(prev[0] if prev else None, cur[0], seq, delisted=cur[1])
        return out

    def _backfill(self, spec, started_m):
        """One bounded backfill. Returns ([(received_at, items)], recovered)."""
        pages, recovered = [], False
        for bspec in (spec.backfill() if spec.backfill else []):
            if self.mono() + bspec.min_gap_s - started_m > DEADLINE_S:
                break
            if bspec.min_gap_s:
                self.sleep(bspec.min_gap_s)
            try:
                resp = self.fetcher(bspec)
                received = self._now()
                if resp.status != 200:
                    break
                items = bspec.parse(resp.body)
            except Exception as e:  # noqa: BLE001
                self.log("%s: backfill stopped: %s: %s" % (spec.key, type(e).__name__, e))
                break
            pages.append((received, items))
            if na_store.known_ids(self.conn, spec.key, [i.source_item_id for i in items]):
                recovered = True
                break
        return pages, recovered

    def poll(self, key):
        return self.poll_status(key) == "ok"

    def poll_status(self, key):
        """One poll of one source: "ok", "failed" (recorded), or "denied" (Binance limiter
        said no; nothing was requested or recorded)."""
        spec, st = self.sources[key], self.state[key]
        started_m, started_w = self.mono(), self.wall()
        started = na_store.iso_from_epoch(started_w)
        if spec.binance and not self.limiter.try_acquire(started_w):
            st.next_due = started_m + LIMITER_RETRY_S
            if self.limiter.suspended_until(started_w) is not None:
                for k, s in self.sources.items():
                    if s.binance:
                        na_store.open_gap(self.conn, k, "suspended", started,
                                          "suspended by a shared-limiter caller")
            return "denied"
        status, retry_after = None, None
        try:
            resp = self.fetcher(spec)
            received_w = self.wall()
            received = na_store.iso_from_epoch(received_w)
            status = resp.status
            if spec.binance and is_block_signal(resp):
                self._suspend_binance(received_w, "block signal: HTTP %d" % status)
                raise PollError("binance block signal (HTTP %d): all Binance sources "
                                "suspended for 6 h" % status)
            if status == 429:
                retry_after = _retry_after(resp.headers, received_w)
                raise PollError("HTTP 429")
            if status != 200:
                raise PollError("HTTP %d" % status)
            items = spec.parse(resp.body)
            if key == HL_KEY:
                items = self._universe_items(key, items)
            overflow, pages, recovered = False, [], False
            if spec.list_feed and items and self._q1(
                    "SELECT 1 FROM items WHERE source=? LIMIT 1", key):
                if not na_store.known_ids(self.conn, key, [i.source_item_id for i in items]):
                    overflow = True
                    pages, recovered = self._backfill(spec, started_m)
            if self.free_bytes() < DISK_MIN_BYTES:
                na_store.open_gap(self.conn, key, "disk", received,
                                  "free space below 15 GiB; nothing stored")
                raise PollError("disk guard: free space below 15 GiB, items not stored")
            outage_start = self._outage_start(st)
            after_gap = not st.ok_since_start
            with na_store.transaction(self.conn):
                if outage_start is not None and received_w - outage_start > 2 * spec.interval_s:
                    na_store.open_gap(self.conn, key, "outage",
                                      na_store.iso_from_epoch(outage_start),
                                      "no OK poll for %d s" % (received_w - outage_start))
                    after_gap = True
                n_new, n_rev = na_store.upsert_items(self.conn, key, items, received, after_gap)
                for page_received, page_items in pages:
                    a, b = na_store.upsert_items(self.conn, key, page_items, page_received, True)
                    n_new, n_rev = n_new + a, n_rev + b
                if overflow:
                    na_store.record_closed_gap(
                        self.conn, key, "overflow",
                        na_store.iso_from_epoch(st.last_ok or self.started_w), received,
                        "recovered" if recovered else "unrecovered")
                for reason in ("outage", "disk", "suspended"):
                    na_store.close_gap(self.conn, key, reason, received)
                na_store.record_poll(self.conn, key, started, self._now(), True, status,
                                     len(items), n_new, n_rev, None)
        except Exception as e:  # noqa: BLE001 - every failure is a recorded failed poll
            self._failed(key, spec, st, started_m, started, status, retry_after, e)
            return "failed"
        st.failures, st.last_ok, st.ok_since_start = 0, received_w, True
        st.next_due = started_m + spec.interval_s
        if n_new or n_rev or overflow:
            self.log("%s: %d items, %d new, %d revised%s" % (
                key, len(items), n_new, n_rev,
                ", overflow %s" % ("recovered" if recovered else "unrecovered")
                if overflow else ""))
        return "ok"

    def _failed(self, key, spec, st, started_m, started, status, retry_after, err):
        st.failures += 1
        delay = self._backoff(spec, st.failures)
        if retry_after is not None:
            delay = max(delay, min(retry_after, MAX_RETRY_AFTER_S))
        st.next_due = started_m + delay
        msg = ("%s: %s" % (type(err).__name__, err))[:500]
        self.log("%s: poll failed (%d in a row, next in %d s): %s" % (
            key, st.failures, delay, msg))
        try:
            now_w = self.wall()
            outage_start = self._outage_start(st)
            if outage_start is not None and now_w - outage_start > 2 * spec.interval_s:
                na_store.open_gap(self.conn, key, "outage",
                                  na_store.iso_from_epoch(outage_start),
                                  "no OK poll for more than %d s" % (2 * spec.interval_s))
            na_store.record_poll(self.conn, key, started, na_store.iso_from_epoch(now_w),
                                 False, status, None, None, None, msg)
        except Exception as e:  # noqa: BLE001
            self.log("%s: could not record failed poll: %s: %s" % (key, type(e).__name__, e))


# ---- status (Part B reuses these queries) -----------------------------------------------

def _age(now_dt, ts):
    s = max(0.0, (now_dt - na_store.parse_iso(ts)).total_seconds())
    if s < 120:
        return "%d s" % s
    if s < 7200:
        return "%.0f min" % (s / 60)
    if s < 172800:
        return "%.1f h" % (s / 3600)
    return "%.1f d" % (s / 86400)


def status_lines(conn, now):
    """One line per source plus one per open gap."""
    now_dt = na_store.parse_iso(now)
    d1 = na_store.iso(now_dt - timedelta(days=1))
    d7 = na_store.iso(now_dt - timedelta(days=7))
    q1 = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    sources = conn.execute(
        "SELECT source, interval_s, enabled FROM sources ORDER BY source").fetchall()
    gaps = conn.execute("SELECT source, reason, gap_start, detail FROM gaps"
                        " WHERE gap_end IS NULL ORDER BY gap_start, gap_pk").fetchall()
    lines = ["news-archive status at %s: %d sources, %d open gaps" % (
        now, len(sources), len(gaps))]
    for src, interval_s, enabled in sources:
        last_ok = q1("SELECT MAX(finished_at) FROM polls WHERE source=? AND ok=1", src)
        fails = q1("SELECT COUNT(*) FROM polls WHERE source=? AND ok=0 AND poll_pk >"
                   " COALESCE((SELECT MAX(poll_pk) FROM polls WHERE source=? AND ok=1), 0)",
                   src, src)
        n_ok, n_all = conn.execute(
            "SELECT COALESCE(SUM(ok), 0), COUNT(*) FROM polls WHERE source=? AND started_at >= ?",
            (src, d1)).fetchone()
        i24 = q1("SELECT COUNT(*) FROM items WHERE source=? AND received_at >= ?", src, d1)
        i7 = q1("SELECT COUNT(*) FROM items WHERE source=? AND received_at >= ?", src, d7)
        itot = q1("SELECT COUNT(*) FROM items WHERE source=?", src)
        newest = q1("SELECT MAX(published_at) FROM items WHERE source=?", src)
        lines.append("%-20s %slast_ok %s  fails %d  ok24h %d/%d  items 24h %d / 7d %d / total %d"
                     "  newest_pub %s" % (
                         src, "" if enabled else "(disabled) ",
                         "%s (%s ago)" % (last_ok, _age(now_dt, last_ok)) if last_ok else "never",
                         fails, n_ok, n_all, i24, i7, itot, newest or "-"))
    for src, reason, start, detail in gaps:
        lines.append("gap open  %-20s %-9s since %s (%s)  %s" % (
            src, reason, start, _age(now_dt, start), detail or ""))
    return lines


# ---- CLI ---------------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TICK_S = 5.0
ONCE_MAX_WAIT_S = 600.0


class WriterLockHeld(Exception):
    pass


@contextmanager
def writer_lock(data_dir):
    """One writer per database: `run` and `once` exclude each other."""
    with open(os.path.join(data_dir, "archive.lock"), "a") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WriterLockHeld(data_dir) from None
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _runtime():
    return time.time, time.monotonic, time.sleep


def ntp_synchronized():
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    v = out.stdout.strip().lower()
    return True if v == "yes" else False if v == "no" else None


def _gzip_rotator(source, dest):
    with open(source, "rb") as fi, gzip.open(dest, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    os.remove(source)


def setup_logging(log_file):
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    for h in list(LOG.handlers):
        LOG.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s [news-archive] %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    fmt.converter = time.gmtime
    fh = logging.handlers.TimedRotatingFileHandler(log_file, when="midnight", backupCount=14,
                                                   utc=True)
    fh.namer = lambda name: name + ".gz"
    fh.rotator = _gzip_rotator
    sh = logging.StreamHandler(sys.stdout)
    for h in (fh, sh):
        h.setFormatter(fmt)
        LOG.addHandler(h)


def enabled_sources():
    """SOURCES minus NEWS_ARCHIVE_DISABLE (comma-separated keys)."""
    disabled = {k.strip() for k in os.environ.get("NEWS_ARCHIVE_DISABLE", "").split(",")
                if k.strip()}
    return {k: v for k, v in SOURCES.items() if k not in disabled}


def build_archive(data_dir, sources):
    wall, mono, sleep = _runtime()
    conn = na_store.connect(os.path.join(data_dir, "archive.sqlite"))
    limiter = BinanceLimiter(os.path.join(data_dir, "binance_cms_state.json"))
    return Archive(conn, sources, limiter, lambda spec: fetch(spec), wall, mono,
                   lambda: shutil.disk_usage(data_dir).free, ntp_synchronized, sleep=sleep)


def _once(arc, keys):
    wall, mono, sleep = _runtime()
    failed = 0
    for key in keys:
        waited = 0.0
        outcome = arc.poll_status(key)
        while outcome == "denied" and waited < ONCE_MAX_WAIT_S:
            if arc.limiter.suspended_until(wall()) is not None:
                break
            sleep(5.0)
            waited += 5.0
            outcome = arc.poll_status(key)
        if outcome == "ok":
            row = arc.conn.execute("SELECT n_items, n_new, n_revised FROM polls WHERE source=?"
                                   " ORDER BY poll_pk DESC LIMIT 1", (key,)).fetchone()
            print("OK %s: %d items, %d new, %d revised" % (key, *row))
            continue
        failed += 1
        if outcome == "denied":
            until = arc.limiter.suspended_until(wall())
            print("FAILED %s: %s" % (key, "Binance suspended until %s" % (
                na_store.iso_from_epoch(until)) if until else "limiter wait exceeded"))
        else:
            err = arc.conn.execute("SELECT error FROM polls WHERE source=? ORDER BY poll_pk DESC"
                                   " LIMIT 1", (key,)).fetchone()[0]
            print("FAILED %s: %s" % (key, err))
    return 1 if failed else 0


def _status(data_dir):
    path = os.path.join(data_dir, "archive.sqlite")
    if not os.path.exists(path):
        print("news-archive: no database at %s" % path)
        return 1
    from pathlib import Path
    conn = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    try:
        print("\n".join(status_lines(conn, na_store.iso_from_epoch(time.time()))))
    finally:
        conn.close()
    return 0


def _term(signum, frame):
    raise SystemExit(0)


def main(argv=None):
    p = argparse.ArgumentParser(prog="news_archive.py",
                                description="PIT news archive (#229 Part A)")
    p.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    p.add_argument("--log-file", default=os.path.join(HERE, "monitor.log"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="the service (systemd)")
    once = sub.add_parser("once", help="one poll per source, then exit")
    once.add_argument("--source", action="append", metavar="KEY")
    sub.add_parser("status", help="per-source health and open gaps")
    args = p.parse_args(argv)
    if args.cmd == "status":
        return _status(args.data_dir)
    sources = enabled_sources()
    keys = list(sources)
    if args.cmd == "once" and args.source:
        bad = [k for k in args.source if k not in sources]
        if bad:
            print("unknown or disabled source(s): %s" % ", ".join(bad))
            return 2
        keys = args.source
    os.makedirs(args.data_dir, exist_ok=True)
    setup_logging(args.log_file)
    try:
        with writer_lock(args.data_dir):
            arc = build_archive(args.data_dir, sources)
            arc.startup()
            if args.cmd == "once":
                return _once(arc, keys)
            signal.signal(signal.SIGTERM, _term)
            _, _, sleep = _runtime()
            try:
                while True:
                    arc.tick()
                    sleep(TICK_S)
            finally:
                LOG.info("stopping")
                arc.conn.close()
    except WriterLockHeld:
        print("news-archive: another writer (run or once) holds %s/archive.lock" % args.data_dir)
        return 3


if __name__ == "__main__":
    sys.exit(main())
