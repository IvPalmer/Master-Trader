"""News-archive section of the nightly health report (#229 Part B, spec §5.1).

The section reads the PIT news archive read-only and reports source freshness,
coverage gaps and the archive backup's state. Fixtures are built with Part A's
na_store, so the schema here cannot drift from the real one. Network-free.

    python3 -m pytest tests/test_health_report_news_archive.py -q
"""

import json
import os
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ft_userdata"))
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import na_store  # noqa: E402
import news_archive_report as nar  # noqa: E402
import strategy_health_report as shr  # noqa: E402

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


# ---- backup state and the report wiring (Task 4) ----------------------------------

RUN_STAMP = "20261105T043000Z"
RUN_AT = "2026-11-05T04:30:00.000000+00:00"
STATUS_KEYS = ("last_run_at", "last_run_result", "last_run_error", "latest_snapshot",
               "upload", "local_drill", "offhost_drill")
OK_RUN = {"last_run_at": RUN_AT, "last_run_result": "ok", "latest_snapshot": RUN_STAMP}


def _status(tmp_path, **keys):
    status = dict.fromkeys(STATUS_KEYS)
    status.update(keys)
    path = tmp_path / "STATUS.json"
    path.write_text(json.dumps(status))
    return str(path)


def _upload(ok, error=None):
    return {"at": RUN_AT, "ok": ok, "error": error, "stamp": RUN_STAMP}


def _drill(ok, error=None):
    return {"at": RUN_AT, "stamp": RUN_STAMP if ok else None, "ok": ok, "error": error}


def test_backup_local_only_until_the_remote_drill(tmp_path):
    expected = "  news-archive backup: local only; latest snapshot 18.5 h ago (20261105T043000Z)"
    assert nar.backup_line(_status(tmp_path, **OK_RUN), NOW) == expected
    # an upload and a passing local drill still do not make the copy count off-host
    assert nar.backup_line(_status(tmp_path, **OK_RUN, upload=_upload(True),
                                   local_drill=_drill(True)), NOW) == expected


def test_failed_upload_shows_before_the_gate(tmp_path):
    path = _status(tmp_path, **{**OK_RUN, "last_run_result": "upload_failed",
                                "last_run_error": "Drive unavailable"},
                   upload=_upload(False, "Drive unavailable"))
    assert nar.backup_line(path, NOW) == (
        "  news-archive backup: local only; off-host upload FAILED 18.5 h ago: Drive unavailable;"
        " latest snapshot 18.5 h ago (20261105T043000Z)")


def test_offhost_counts_only_after_a_passing_remote_drill(tmp_path):
    line = nar.backup_line(_status(tmp_path, **OK_RUN, upload=_upload(True),
                                   offhost_drill=_drill(True)), NOW)
    assert line.startswith("  news-archive backup: off-host OK (last upload 18.5 h ago); latest snapshot")

    line = nar.backup_line(_status(tmp_path, **OK_RUN, upload=_upload(False, "quota"),
                                   offhost_drill=_drill(True)), NOW)
    assert "off-host upload FAILED 18.5 h ago: quota" in line
    assert "off-host OK" not in line

    line = nar.backup_line(_status(tmp_path, **OK_RUN, upload=_upload(True),
                                   offhost_drill=_drill(False, "sha256 of x does not match")), NOW)
    assert line.startswith("  news-archive backup: local only")
    assert "off-host drill FAILED: sha256 of x does not match" in line


def test_local_failure_skip_and_overdue_are_shown(tmp_path):
    line = nar.backup_line(_status(
        tmp_path, last_run_at=ts(hours=30), last_run_result="skipped",
        last_run_error="free 14.2 GiB < required 15.0 GiB"), NOW)
    assert line.startswith("  news-archive backup: local only; no snapshot yet")
    assert "; last run SKIPPED 30.0 h ago: free 14.2 GiB < required 15.0 GiB" in line
    assert "; no run for 30.0 h" in line

    line = nar.backup_line(_status(tmp_path, **{**OK_RUN, "last_run_result": "failed",
                                                "last_run_error": "integrity_check failed"}), NOW)
    assert line.endswith("; last run FAILED 18.5 h ago: integrity_check failed")
    assert "no run for" not in line


def test_unreadable_status_is_one_line(tmp_path):
    path = tmp_path / "STATUS.json"
    path.write_text("{not json")
    assert nar.backup_line(str(path), NOW).startswith(
        "  news-archive backup: local only; status unreadable (JSONDecodeError")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_status_without_read_permission_is_one_line(tmp_path):
    path = _status(tmp_path, **OK_RUN)
    os.chmod(path, 0o000)
    try:
        assert nar.news_archive_lines(str(tmp_path / "archive.sqlite"), path, NOW)[-1].startswith(
            "  news-archive backup: local only; status unreadable (PermissionError")
    finally:
        os.chmod(path, 0o600)


def test_missing_status_file(tmp_path):
    assert nar.backup_line(str(tmp_path / "STATUS.json"), NOW) == \
        "  news-archive backup: local only; no snapshot yet"


def test_missing_db_with_backups_is_loud(tmp_path):
    db = tmp_path / "archive.sqlite"
    lines = nar.news_archive_lines(str(db), _status(tmp_path, **OK_RUN), NOW)
    assert lines[0] == f"  news-archive: DATABASE MISSING at {db}"
    assert lines[1].startswith("  news-archive backup: local only; latest snapshot")
    assert not any("not installed" in line for line in lines)


def test_not_installed_without_db_or_backups(tmp_path):
    assert nar.news_archive_lines(str(tmp_path / "archive.sqlite"),
                                  str(tmp_path / "STATUS.json"), NOW) == [
        "  news-archive: not installed"]


def test_env_paths_are_read_at_call_time(tmp_path, monkeypatch):
    db = _archive(tmp_path, TWO, polls=_fresh("tree", "rss_coindesk"))
    monkeypatch.setenv("NEWS_ARCHIVE_DB", db)
    monkeypatch.setenv("NEWS_ARCHIVE_BACKUP_STATUS", _status(tmp_path, **OK_RUN))
    lines = nar.news_archive_lines(now=NOW)
    assert lines[0] == "  news-archive: 2/2 enabled sources OK; 0 items in 24 h"
    assert lines[-1].startswith("  news-archive backup: local only; latest snapshot 18.5 h ago")


def test_section_failure_never_breaks_the_report(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "news_archive_report",
                        types.SimpleNamespace(news_archive_lines=boom))
    assert shr.news_archive_section() == ["  news-archive: section failed: RuntimeError: boom"]
    monkeypatch.setitem(sys.modules, "news_archive_report", None)
    assert shr.news_archive_section()[0].startswith(
        "  news-archive: section failed: ModuleNotFoundError")


def test_section_reads_the_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_ARCHIVE_DB", str(tmp_path / "archive.sqlite"))
    monkeypatch.setenv("NEWS_ARCHIVE_BACKUP_STATUS", str(tmp_path / "STATUS.json"))
    assert shr.news_archive_section() == ["  news-archive: not installed"]


PORTFOLIO = {"closed_pnl": 0.0, "open_pnl": 0.0, "true_pnl": 0.0, "total_trades": 0,
             "open_positions": 0, "bots_online": 0, "avg_health_score": 0.0}


def test_report_ends_with_the_news_archive_block():
    report = shr.format_telegram_report([], PORTFOLIO, {}, news_lines=["  news-archive: x"])
    assert report.endswith("\n\nNEWS ARCHIVE\n  news-archive: x")
    assert "NEWS ARCHIVE" not in shr.format_telegram_report([], PORTFOLIO, {})


def test_main_prints_the_news_archive_block_last(monkeypatch, capsys):
    import logging

    monkeypatch.setattr(shr, "REPORTING_BOTS", {})
    monkeypatch.setattr(shr, "_setup_logging", lambda json_mode=False: logging.getLogger("t"))
    monkeypatch.setattr(shr, "load_previous_state", lambda: None)
    monkeypatch.setattr(shr, "save_state", lambda *a: None)
    monkeypatch.setattr(shr, "compute_portfolio_metrics", lambda metrics: dict(PORTFOLIO))
    monkeypatch.setattr(shr, "check_preregistrations", lambda: [])
    monkeypatch.setattr(shr, "news_archive_section", lambda: ["  news-archive: x"])
    monkeypatch.setattr(sys, "argv", ["strategy_health_report.py", "--stdout"])
    shr.main()
    assert capsys.readouterr().out.endswith("\n\nNEWS ARCHIVE\n  news-archive: x\n")


def test_multiline_errors_stay_indented(tmp_path, monkeypatch):
    def raise_multiline(*args, **kwargs):
        raise RuntimeError("first\nSECOND")

    db = _archive(tmp_path, TWO, polls=_fresh("tree", "rss_coindesk"))
    status = _status(tmp_path, **OK_RUN, upload=_upload(False, "x"))
    monkeypatch.setattr(nar, "_source_lines", raise_multiline)
    monkeypatch.setattr(nar, "_age", raise_multiline)
    lines = nar.news_archive_lines(db, status, NOW)
    assert lines == ["  news-archive: database unreadable (RuntimeError: first SECOND)",
                     "  news-archive backup: local only; status unreadable (RuntimeError: first SECOND)"]
    monkeypatch.setitem(sys.modules, "news_archive_report",
                        types.SimpleNamespace(news_archive_lines=raise_multiline))
    assert shr.news_archive_section() == ["  news-archive: section failed: RuntimeError: first SECOND"]
