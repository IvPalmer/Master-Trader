"""SQLite storage for the point-in-time (PIT) news archive (#229, spec §4.3).

Stdlib only. Every timestamp is ISO-8601 UTC with microseconds, so plain string
comparison orders them. The database runs in WAL mode with a 5 s busy timeout, so
a read-only reader (health report, backup) never makes the writer fail.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (source TEXT PRIMARY KEY, interval_s INTEGER NOT NULL,
                      enabled INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
  item_pk        INTEGER PRIMARY KEY AUTOINCREMENT,
  source         TEXT NOT NULL,
  source_item_id TEXT NOT NULL,
  received_at    TEXT NOT NULL,
  published_at   TEXT,
  title          TEXT,
  body           TEXT,
  url            TEXT,
  symbols        TEXT,
  after_gap      INTEGER NOT NULL DEFAULT 0,
  content_hash   TEXT NOT NULL,
  raw_json       TEXT NOT NULL,
  UNIQUE(source, source_item_id)
);
CREATE TABLE IF NOT EXISTS item_revisions (
  rev_pk INTEGER PRIMARY KEY AUTOINCREMENT, item_pk INTEGER NOT NULL REFERENCES items(item_pk),
  received_at TEXT NOT NULL, prev_hash TEXT NOT NULL, content_hash TEXT NOT NULL,
  after_gap INTEGER NOT NULL DEFAULT 0, raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gaps (
  gap_pk INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
  gap_start TEXT NOT NULL, gap_end TEXT,
  reason TEXT NOT NULL,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS clock_checks (
  checked_at TEXT NOT NULL, ntp_synchronized INTEGER, wall_minus_mono_s REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS polls (
  poll_pk INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, ok INTEGER NOT NULL,
  http_status INTEGER, n_items INTEGER, n_new INTEGER, n_revised INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS items_source_received ON items(source, received_at);
CREATE INDEX IF NOT EXISTS revisions_item ON item_revisions(item_pk);
CREATE INDEX IF NOT EXISTS gaps_source ON gaps(source, reason);
CREATE INDEX IF NOT EXISTS polls_source_started ON polls(source, started_at);
"""


@dataclass(frozen=True)
class Item:
    source_item_id: str
    published_at: "str | None"
    title: "str | None"
    body: "str | None"
    url: "str | None"
    symbols: "list | None"
    raw: dict


def iso(dt):
    """datetime -> canonical ISO-8601 UTC string with microseconds."""
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def iso_from_epoch(seconds):
    return iso(datetime.fromtimestamp(seconds, tz=timezone.utc))


def parse_iso(value):
    return datetime.fromisoformat(value)


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn):
    """One write transaction; nested use joins the outer one."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def canonical_json(raw):
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(raw):
    return hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        if it.source_item_id not in seen:
            seen.add(it.source_item_id)
            out.append(it)
    return out


def upsert_items(conn, source, items, received_at, after_gap):
    """Insert new items and record revisions against each item's latest version.

    Returns (n_new, n_revised). Ids repeated within the batch keep their first
    occurrence. All writes happen in one transaction.
    """
    n_new = n_rev = 0
    with transaction(conn):
        flag = 1 if after_gap else 0
        for it in _dedupe(items):
            h = content_hash(it.raw)
            raw_json = canonical_json(it.raw)
            row = conn.execute(
                "SELECT item_pk, content_hash FROM items WHERE source=? AND source_item_id=?",
                (source, it.source_item_id)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO items (source, source_item_id, received_at, published_at, title,"
                    " body, url, symbols, after_gap, content_hash, raw_json)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (source, it.source_item_id, received_at, it.published_at, it.title, it.body,
                     it.url, None if it.symbols is None else json.dumps(it.symbols),
                     flag, h, raw_json))
                n_new += 1
                continue
            item_pk, first_hash = row
            latest = conn.execute(
                "SELECT content_hash FROM item_revisions WHERE item_pk=?"
                " ORDER BY rev_pk DESC LIMIT 1", (item_pk,)).fetchone()
            latest_hash = latest[0] if latest else first_hash
            if latest_hash != h:
                conn.execute(
                    "INSERT INTO item_revisions (item_pk, received_at, prev_hash, content_hash,"
                    " after_gap, raw_json) VALUES (?,?,?,?,?,?)",
                    (item_pk, received_at, latest_hash, h, flag, raw_json))
                n_rev += 1
    return n_new, n_rev


def known_ids(conn, source, ids):
    ids = list(dict.fromkeys(ids))
    found = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = "SELECT source_item_id FROM items WHERE source=? AND source_item_id IN (%s)" % (
            ",".join("?" * len(chunk)))
        found.update(r[0] for r in conn.execute(q, [source, *chunk]))
    return found


def write_sources(conn, rows, now):
    """rows: [(source, interval_s, enabled)]. Sources absent from rows are disabled."""
    with transaction(conn):
        conn.execute("UPDATE sources SET enabled=0, updated_at=?", (now,))
        conn.executemany(
            "INSERT OR REPLACE INTO sources (source, interval_s, enabled, updated_at)"
            " VALUES (?,?,?,?)",
            [(s, int(i), 1 if e else 0, now) for s, i, e in rows])


def record_poll(conn, source, started_at, finished_at, ok, http_status, n_items, n_new,
                n_revised, error):
    with transaction(conn):
        conn.execute(
            "INSERT INTO polls (source, started_at, finished_at, ok, http_status, n_items,"
            " n_new, n_revised, error) VALUES (?,?,?,?,?,?,?,?,?)",
            (source, started_at, finished_at, 1 if ok else 0, http_status, n_items, n_new,
             n_revised, error))


def prune_polls(conn, now, keep_days=180):
    cutoff = iso(parse_iso(now) - timedelta(days=keep_days))
    with transaction(conn):
        return conn.execute("DELETE FROM polls WHERE started_at < ?", (cutoff,)).rowcount
