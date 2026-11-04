"""News-archive section of the nightly health report (#229 Part B, spec §5.1).

The section reads the PIT news archive read-only and reports source freshness,
coverage gaps and the archive backup's state. Fixtures are built with Part A's
na_store, so the schema here cannot drift from the real one. Network-free.

    python3 -m pytest tests/test_health_report_news_archive.py -q
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ft_userdata"))
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import na_store  # noqa: E402
import news_archive_report as nar  # noqa: E402

NOW = datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)


def ts(**delta):
    return na_store.iso(NOW - timedelta(**delta))


def _items(source, n, published_at=None):
    return [na_store.Item(f"{source}-{i}", published_at, "t", None, None, None,
                          {"source": source, "id": i}) for i in range(n)]


def _archive(tmp_path, sources, polls=(), items=(), gaps=()):
    """sources: [(source, interval_s, enabled)]; polls: [(source, finished_at, ok, error)];
    items: [(source, n, received_at, published_at)];
    gaps: [(source, reason, start, end_or_None, detail)]."""
    path = tmp_path / "archive.sqlite"
    conn = na_store.connect(str(path))
    na_store.write_sources(conn, sources, ts(days=1))
    for source, finished, ok, error in polls:
        na_store.record_poll(conn, source, finished, finished, ok, 200 if ok else 503,
                             0, 0, 0, error)
    for source, n, received_at, published_at in items:
        na_store.upsert_items(conn, source, _items(source, n, published_at), received_at, False)
    for source, reason, start, end, detail in gaps:
        if end is None:
            na_store.open_gap(conn, source, reason, start, detail)
        else:
            na_store.record_closed_gap(conn, source, reason, start, end, detail)
    conn.close()
    return str(path)


TWO = [("tree", 60, True), ("rss_coindesk", 300, True)]


def _fresh(*sources):
    return [(s, ts(minutes=1), True, None) for s in sources]


def test_missing_db_is_not_installed(tmp_path):
    assert nar.archive_lines(str(tmp_path / "archive.sqlite"), NOW) == [
        "  news-archive: not installed"]


def test_all_fresh_is_one_summary_line(tmp_path):
    db = _archive(tmp_path, TWO + [("upbit", 120, False)],
                  polls=_fresh("tree", "rss_coindesk")
                  + [("upbit", ts(minutes=1), False, "PollError: HTTP 403")],
                  items=[("tree", 5, ts(hours=1), None)])
    assert nar.archive_lines(db, NOW) == [
        "  news-archive: 2/2 enabled sources OK, 1 disabled (upbit); 5 items in 24 h",
        "  open gaps: none",
        "  gaps closed 24 h: none",
        "  unrecovered 7 d: none",
    ]


@pytest.mark.parametrize("failed, tail", [
    (True, "; last error 5 min ago: PollError: HTTP 503"),
    (False, "; no failed poll since (service not polling?)"),
])
def test_one_stale_source_line(tmp_path, failed, tail):
    polls = [("tree", ts(hours=2), True, None)] + _fresh("rss_coindesk")
    if failed:
        polls.append(("tree", ts(minutes=5), False, "PollError: HTTP 503"))
    lines = nar.archive_lines(_archive(tmp_path, TWO, polls=polls), NOW)
    assert lines[0] == "  news-archive: 1/2 enabled sources OK, 1 STALE; 0 items in 24 h"
    assert lines[1] == "  STALE tree: last OK 2.0 h ago (limit 13 min)" + tail


def test_stale_source_that_never_polled_ok(tmp_path):
    lines = nar.archive_lines(_archive(tmp_path, TWO, polls=_fresh("rss_coindesk")), NOW)
    assert lines[1] == ("  STALE tree: last OK never (limit 13 min)"
                        "; no failed poll since (service not polling?)")


def test_quiet_feed_that_polls_ok_is_not_stale(tmp_path):
    db = _archive(tmp_path, [("rss_blockworks", 300, True)],
                  polls=[("rss_blockworks", ts(minutes=3), True, None)],
                  items=[("rss_blockworks", 1, ts(days=300), ts(days=300))])
    lines = nar.archive_lines(db, NOW)
    assert lines[0] == "  news-archive: 1/1 enabled sources OK; 0 items in 24 h"
    assert not any("STALE" in line for line in lines)


def test_disabled_source_is_never_stale(tmp_path):
    db = _archive(tmp_path, [("tree", 60, True), ("upbit", 120, False)],
                  polls=_fresh("tree"))
    lines = nar.archive_lines(db, NOW)
    assert lines[0] == "  news-archive: 1/1 enabled sources OK, 1 disabled (upbit); 0 items in 24 h"
    assert not any("STALE upbit" in line for line in lines)


def test_all_sources_stale_collapse_to_one_line(tmp_path):
    db = _archive(tmp_path, TWO, polls=[(s, ts(hours=6), True, None) for s in ("tree", "rss_coindesk")])
    lines = nar.archive_lines(db, NOW)
    assert lines[0] == "  news-archive: 0/2 enabled sources OK, 2 STALE; 0 items in 24 h"
    assert lines[1] == "  ALL 2 enabled sources STALE: newest OK poll 6.0 h ago (service down?)"
    assert not any(line.startswith("  STALE ") for line in lines)


def test_open_gaps_shown_even_when_fresh(tmp_path):
    names = ("binance_listing", "binance_delisting", "tree")
    db = _archive(tmp_path, [(s, 60, True) for s in names], polls=_fresh(*names),
                  gaps=[("binance_listing", "suspended", ts(hours=3), None, "block"),
                        ("binance_delisting", "suspended", ts(hours=1), None, "block"),
                        ("tree", "clock", ts(minutes=10), None, "jump")])
    lines = nar.archive_lines(db, NOW)
    assert lines[0].startswith("  news-archive: 3/3 enabled sources OK;")
    assert "  open gaps: 3 (clock 1, suspended 2); oldest 3.0 h: binance_listing suspended" in lines


def test_closed_gaps_24h_and_unrecovered_7d(tmp_path):
    five = ("tree", "rss_decrypt", "rss_coindesk", "binance_listing", "okx_delistings")
    gaps = [(s, "restart", ts(hours=1, minutes=2), ts(hours=1), "") for s in five]
    gaps += [("tree", "overflow", ts(hours=2, minutes=1), ts(hours=2), "unrecovered"),
             ("rss_decrypt", "overflow", ts(hours=3, minutes=1), ts(hours=3), "recovered"),
             ("tree", "overflow", ts(days=3, minutes=1), ts(days=3), "unrecovered"),
             ("tree", "overflow", ts(days=8, minutes=1), ts(days=8), "unrecovered")]
    db = _archive(tmp_path, [(s, 60, True) for s in five], polls=_fresh(*five), gaps=gaps)
    lines = nar.archive_lines(db, NOW)
    assert ("  gaps closed 24 h: 7 — overflow 2 (rss_decrypt 1 recovered, tree 1 unrecovered);"
            " restart 5 (5 sources)") in lines
    assert "  unrecovered 7 d: tree 2" in lines


def test_closed_gaps_name_up_to_four_sources(tmp_path):
    gaps = [("tree", "outage", ts(hours=5), ts(hours=4), ""),
            ("tree", "outage", ts(hours=3), ts(hours=2), ""),
            ("rss_fed", "outage", ts(hours=3), ts(hours=2), "")]
    db = _archive(tmp_path, [("tree", 60, True), ("rss_fed", 600, True)],
                  polls=_fresh("tree", "rss_fed"), gaps=gaps)
    assert "  gaps closed 24 h: 3 — outage 3 (rss_fed, tree×2)" in nar.archive_lines(db, NOW)


def test_corrupt_db_is_one_line(tmp_path):
    path = tmp_path / "archive.sqlite"
    path.write_bytes(b"not a database" * 100)
    assert nar.archive_lines(str(path), NOW) == [
        "  news-archive: database unreadable (DatabaseError: file is not a database)"]


def test_reads_wal_rows_and_never_writes(tmp_path):
    path = tmp_path / "archive.sqlite"
    writer = na_store.connect(str(path))
    writer.execute("PRAGMA wal_autocheckpoint=0")
    try:
        na_store.write_sources(writer, [("tree", 60, True)], ts(days=1))
        na_store.record_poll(writer, "tree", ts(minutes=1), ts(minutes=1), True, 200, 3, 3, 0, None)
        na_store.upsert_items(writer, "tree", _items("tree", 3), ts(hours=1), False)
        before = path.read_bytes()
        lines = nar.archive_lines(str(path), NOW)
        assert "3 items in 24 h" in lines[0]
        assert path.read_bytes() == before
        ro = nar.connect_ro(str(path))
        try:
            with pytest.raises(sqlite3.OperationalError):
                ro.execute("INSERT INTO sources VALUES ('x', 1, 1, 't')")
        finally:
            ro.close()
    finally:
        writer.close()
