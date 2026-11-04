"""News-archive section of the nightly health report (#229 Part B, spec §5.1).

It also reports the state of the archive's own backup job
(deploy/vps/backup_news_archive.py) from the STATUS.json that job writes.

Read-only and stdlib only. It imports no Part A code: the report runs from the
Dokploy checkout, which carries nothing under research/. The archive is opened
with mode=ro plus PRAGMA query_only, so the report can never write to it, and
SQLite reads committed WAL frames, so rows the running service has not
checkpointed yet still count.

Nothing here raises. Any failure becomes one line of the report, and every line
starts with two spaces.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = "/home/ubuntu/master-trader/research/news_archive/data/archive.sqlite"
DEFAULT_BACKUP_STATUS = "/home/ubuntu/backups/news-archive/STATUS.json"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"  # backup run directory names
BACKUP_OVERDUE_S = 26 * 3600  # the job runs daily

# An enabled source is stale when its last OK poll is older than this many
# intervals plus the grace below (spec §5.1). Only liveness counts: some feeds
# are legitimately quiet for weeks, and `sources` carries no expected item rate.
STALE_INTERVALS = 3
STALE_GRACE_S = 600
# A closed non-overflow reason names its sources only up to this many.
MAX_NAMED_SOURCES = 4
ERROR_CHARS = 120


def connect_ro(path: str) -> sqlite3.Connection:
    """Open the archive read-only; never runs DDL and never changes journal mode."""
    conn = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=1")
    except BaseException:
        conn.close()
        raise
    return conn


def fmt_age(seconds: float) -> str:
    """Same buckets as Part A's `status` output."""
    if seconds < 120:
        return "%d s" % seconds
    if seconds < 7200:
        return "%.0f min" % (seconds / 60)
    if seconds < 172800:
        return "%.1f h" % (seconds / 3600)
    return "%.1f d" % (seconds / 86400)


def _iso(when: datetime) -> str:
    """Part A's canonical timestamp format, so stored values compare as strings."""
    return when.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _age(now: datetime, stamp: str) -> str:
    return fmt_age(max(0.0, (now - datetime.fromisoformat(stamp)).total_seconds()))


def _exists(path: str) -> bool:
    """False only for a path that is not there; any other OSError propagates.

    Path.exists() turns some errors into False depending on the Python version,
    which would make an unreadable path read as "not installed".
    """
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())[:ERROR_CHARS]


def _source_lines(conn: sqlite3.Connection, now: datetime) -> list[str]:
    enabled, disabled, stale = [], [], []
    newest_ok = None
    for source, interval_s, is_enabled in conn.execute(
            "SELECT source, interval_s, enabled FROM sources ORDER BY source"):
        if not is_enabled:
            disabled.append(source)
            continue
        enabled.append(source)
        last_ok = conn.execute("SELECT MAX(finished_at) FROM polls WHERE source = ? AND ok = 1",
                               (source,)).fetchone()[0]
        if last_ok is not None and (newest_ok is None or last_ok > newest_ok):
            newest_ok = last_ok
        limit_s = STALE_INTERVALS * interval_s + STALE_GRACE_S
        if last_ok is not None and (now - datetime.fromisoformat(last_ok)).total_seconds() <= limit_s:
            continue
        failed = conn.execute(
            "SELECT finished_at, error FROM polls WHERE source = ? AND ok = 0"
            " ORDER BY finished_at DESC LIMIT 1", (source,)).fetchone()
        line = (f"  STALE {source}: last OK "
                + (f"{_age(now, last_ok)} ago" if last_ok else "never")
                + f" (limit {fmt_age(limit_s)})")
        if failed and (last_ok is None or failed[0] > last_ok):
            line += f"; last error {_age(now, failed[0])} ago: {_one_line(failed[1])}"
        else:
            line += "; no failed poll since (service not polling?)"
        stale.append(line)

    cutoff = _iso(now - timedelta(hours=24))
    items = 0
    for (source,) in conn.execute("SELECT source FROM sources").fetchall():
        items += conn.execute("SELECT COUNT(*) FROM items WHERE source = ? AND received_at >= ?",
                              (source, cutoff)).fetchone()[0]

    n, k = len(enabled), len(stale)
    summary = f"  news-archive: {n - k}/{n} enabled sources OK"
    if k:
        summary += f", {k} STALE"
    if disabled:
        summary += f", {len(disabled)} disabled ({', '.join(disabled)})"
    summary += f"; {items} items in 24 h"
    if n and k == n:
        newest = f"{_age(now, newest_ok)} ago" if newest_ok else "never"
        return [summary, f"  ALL {n} enabled sources STALE: newest OK poll {newest} (service down?)"]
    return [summary, *stale]


def _open_gap_line(conn: sqlite3.Connection, now: datetime) -> str:
    rows = conn.execute("SELECT source, reason, gap_start FROM gaps WHERE gap_end IS NULL"
                        " ORDER BY gap_start, gap_pk").fetchall()
    if not rows:
        return "  open gaps: none"
    by_reason = Counter(reason for _, reason, _ in rows)
    source, reason, start = rows[0]
    counts = ", ".join(f"{r} {c}" for r, c in sorted(by_reason.items()))
    return f"  open gaps: {len(rows)} ({counts}); oldest {_age(now, start)}: {source} {reason}"


def _closed_gap_line(conn: sqlite3.Connection, now: datetime) -> str:
    rows = conn.execute("SELECT source, reason, detail FROM gaps"
                        " WHERE gap_end IS NOT NULL AND gap_end >= ?",
                        (_iso(now - timedelta(hours=24)),)).fetchall()
    if not rows:
        return "  gaps closed 24 h: none"
    parts = []
    for reason in sorted({r for _, r, _ in rows}):
        mine = [(s, d or "") for s, r, d in rows if r == reason]
        if reason == "overflow":
            named = ", ".join(f"{s} {c} {d}".rstrip() for (s, d), c in sorted(Counter(mine).items()))
        else:
            per_source = Counter(s for s, _ in mine)
            if len(per_source) <= MAX_NAMED_SOURCES:
                named = ", ".join(s if c == 1 else f"{s}×{c}" for s, c in sorted(per_source.items()))
            else:
                named = f"{len(per_source)} sources"
        parts.append(f"{reason} {len(mine)} ({named})")
    return f"  gaps closed 24 h: {len(rows)} — " + "; ".join(parts)


def _unrecovered_line(conn: sqlite3.Connection, now: datetime) -> str:
    rows = conn.execute("SELECT source, COUNT(*) FROM gaps WHERE reason = 'overflow'"
                        " AND detail = 'unrecovered' AND gap_end IS NOT NULL AND gap_end >= ?"
                        " GROUP BY source", (_iso(now - timedelta(days=7)),)).fetchall()
    if not rows:
        return "  unrecovered 7 d: none"
    rows.sort(key=lambda r: (-r[1], r[0]))
    return "  unrecovered 7 d: " + ", ".join(f"{s} {c}" for s, c in rows)


def archive_lines(db_path: str, now: datetime) -> list[str]:
    """Freshness and gap lines for the archive at `db_path`. Never raises."""
    try:
        if not _exists(db_path):
            return ["  news-archive: not installed"]
        conn = connect_ro(db_path)
        try:
            return [*_source_lines(conn, now), _open_gap_line(conn, now),
                    _closed_gap_line(conn, now), _unrecovered_line(conn, now)]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - the section must never break the report
        return [f"  news-archive: database unreadable ({type(exc).__name__}: {exc})"]


def backup_line(status_path: str, now: datetime) -> str:
    """One line on the archive backup, from its STATUS.json. Never raises.

    The off-host copy counts only once the latest remote restore drill passed
    (spec §5.2); until then the line starts "local only".
    """
    head = "  news-archive backup: "
    try:
        try:
            with open(status_path) as f:
                status = json.load(f)
        except FileNotFoundError:
            return head + "local only; no snapshot yet"
        if not isinstance(status, dict):
            raise ValueError(f"expected a JSON object, got {type(status).__name__}")
        upload = status.get("upload") or {}
        offhost = status.get("offhost_drill") or {}
        upload_failed = None
        if upload and not upload.get("ok"):
            upload_failed = (f"off-host upload FAILED {_age(now, upload['at'])} ago: "
                             f"{_one_line(upload.get('error'))}")
        if offhost.get("ok"):
            if upload.get("ok"):
                parts = [f"off-host OK (last upload {_age(now, upload['at'])} ago)"]
            else:
                parts = [upload_failed or "off-host OK (no upload recorded)"]
        else:
            parts = ["local only"]
            if upload_failed:
                parts.append(upload_failed)
            if offhost:
                parts.append(f"off-host drill FAILED: {_one_line(offhost.get('error'))}")

        stamp = status.get("latest_snapshot")
        if stamp:
            taken = datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=timezone.utc)
            parts.append(f"latest snapshot {fmt_age(max(0.0, (now - taken).total_seconds()))}"
                         f" ago ({stamp})")
        else:
            parts.append("no snapshot yet")

        result, run_at = status.get("last_run_result"), status.get("last_run_at")
        if result in ("failed", "skipped"):
            parts.append(f"last run {result.upper()} {_age(now, run_at)} ago: "
                         f"{_one_line(status.get('last_run_error'))}")
        if run_at and (now - datetime.fromisoformat(run_at)).total_seconds() > BACKUP_OVERDUE_S:
            parts.append(f"no run for {_age(now, run_at)}")
        return head + "; ".join(parts)
    except Exception as exc:  # noqa: BLE001 - the section must never break the report
        return f"{head}local only; status unreadable ({type(exc).__name__}: {exc})"


def news_archive_lines(db_path: str | None = None, status_path: str | None = None,
                       now: datetime | None = None) -> list[str]:
    """The report's NEWS ARCHIVE block. Paths come from the environment at call time."""
    db_path = db_path or os.environ.get("NEWS_ARCHIVE_DB") or DEFAULT_DB
    status_path = (status_path or os.environ.get("NEWS_ARCHIVE_BACKUP_STATUS")
                   or DEFAULT_BACKUP_STATUS)
    now = now or datetime.now(timezone.utc)
    try:
        db_there = _exists(db_path)
    except OSError:
        db_there = True  # archive_lines reports it as unreadable
    try:
        status_there = _exists(status_path)
    except OSError:
        status_there = True  # backup_line reports it as unreadable
    if not db_there:
        if not status_there:
            return ["  news-archive: not installed"]
        # Backups exist, so the archive was installed: a vanished database is loud.
        return [f"  news-archive: DATABASE MISSING at {db_path}", backup_line(status_path, now)]
    return [*archive_lines(db_path, now), backup_line(status_path, now)]
