"""Backup job for the PIT news archive (#229 Part B, spec §5.2).

deploy/vps/backup_news_archive.py is a separate job from the live-DB backup:
its own lock, destination, retention and free-space rule, so an archive failure
can never break the live trade-DB backup. Fixtures build a WAL-mode archive
with Part A's na_store, held open by a writer, with rows only in the WAL.
Network-free: rclone is never run.

    python3 -m pytest tests/test_backup_news_archive.py -q
"""

import ast
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
import sqlite3
import stat
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "vps" / "backup_news_archive.py"
sys.path.insert(0, str(ROOT / "deploy" / "vps"))
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import backup_live_dbs as live  # noqa: E402
import backup_news_archive as bna  # noqa: E402
import na_store  # noqa: E402

REAL_LOWER_PRIORITY = bna.lower_priority
UTC = dt.timezone.utc
T = "2026-11-05T04:00:00.000000+00:00"


def _free(monkeypatch, free):
    monkeypatch.setattr(bna.shutil, "disk_usage",
                        lambda path: types.SimpleNamespace(total=free * 2, used=free, free=free))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No real renice, plenty of space, and the process umask restored afterwards:
    both jobs set umask 077, which would leak into later tests."""
    monkeypatch.setattr(bna, "lower_priority", lambda: None)
    _free(monkeypatch, 1 << 50)
    old = os.umask(0o022)
    os.umask(old)
    yield
    os.umask(old)


def _items(n, start=0):
    return [na_store.Item(f"tree-{i}", None, "t", None, None, None, {"id": i})
            for i in range(start, start + n)]


@pytest.fixture
def archive_db(tmp_path):
    """1 source and 3 items that exist only in the WAL, with the writer left open."""
    path = tmp_path / "data" / "archive.sqlite"
    path.parent.mkdir()
    conn = na_store.connect(str(path))
    conn.execute("PRAGMA wal_autocheckpoint=0")
    na_store.write_sources(conn, [("tree", 60, True)], T)
    na_store.upsert_items(conn, "tree", _items(3), T, False)
    yield path
    conn.close()


def _args(db, dest, *extra):
    return ["--db", str(db), "--dest", str(dest), *extra]


def _runs(dest):
    if not dest.is_dir():
        return []
    return sorted(p for p in dest.iterdir() if p.is_dir() and not p.name.startswith("."))


def _corrupt(path):
    path.write_bytes(b"not a database" * 100)
    return path


def test_snapshot_is_consistent_while_the_service_writes(archive_db, tmp_path):
    dest = tmp_path / "backups"
    assert bna.main(_args(archive_db, dest)) == 0
    runs = _runs(dest)
    assert len(runs) == 1
    run = runs[0]
    manifest = json.loads((run / "MANIFEST.json").read_text())
    assert manifest["row_counts"]["items"] == 3
    assert manifest["row_counts"]["sources"] == 1
    assert manifest["stored_as"] == "archive.sqlite.gz"
    assert manifest["integrity_check"] == "ok"
    restored = tmp_path / "restored.sqlite"
    with gzip.open(run / "archive.sqlite.gz") as fin:
        restored.write_bytes(fin.read())
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == manifest["sha256"]
    conn = sqlite3.connect(restored)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    status = bna.read_status(dest)
    assert status["last_run_result"] == "ok"
    assert status["latest_snapshot"] == run.name
    assert status["last_run_error"] is None


def test_free_space_rule_counts_the_wal(archive_db, tmp_path, monkeypatch):
    wal = archive_db.with_name("archive.sqlite-wal")
    assert wal.stat().st_size > 0
    required = 15 * 1024**3 + 2 * (archive_db.stat().st_size + wal.stat().st_size)
    assert bna.required_free_bytes(archive_db) == required

    dest = tmp_path / "backups"
    _free(monkeypatch, required - 1)
    assert bna.main(_args(archive_db, dest)) == 1
    assert _runs(dest) == []
    status = bna.read_status(dest)
    assert status["last_run_result"] == "skipped"
    assert "free" in status["last_run_error"]

    _free(monkeypatch, required)
    assert bna.main(_args(archive_db, dest)) == 0


def test_held_lock_skips_and_leaves_status_alone(archive_db, tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    with open(dest / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert bna.main(_args(archive_db, dest)) == 0
    assert _runs(dest) == []
    assert not (dest / "STATUS.json").exists()


def test_failed_run_leaves_no_staging_and_records_failure(tmp_path):
    dest = tmp_path / "backups"
    assert bna.main(_args(_corrupt(tmp_path / "archive.sqlite"), dest)) == 1
    assert not list(dest.glob(".partial-*"))
    assert _runs(dest) == []
    status = bna.read_status(dest)
    assert status["last_run_result"] == "failed"
    assert status["last_run_error"]
    assert status["latest_snapshot"] is None


def test_retention_keeps_7_daily_and_8_weekly(tmp_path):
    now = dt.datetime(2026, 11, 5, 4, 30, tzinfo=UTC)
    dest = tmp_path / "backups"
    dest.mkdir()
    stamps = [(now - dt.timedelta(days=d)).strftime(live.STAMP_FORMAT) for d in range(70)]
    for s in stamps:
        (dest / s).mkdir()
    (dest / "not-a-run").mkdir()
    (dest / ".partial-20261105T043000Z").mkdir()

    bna.prune_local(dest, now)

    kept = sorted(p.name for p in dest.iterdir() if p.name != "not-a-run")
    assert set(stamps[:7]) <= set(kept)
    whens = [dt.datetime.strptime(s, live.STAMP_FORMAT).replace(tzinfo=UTC) for s in kept]
    older = [w for w in whens if now - w > dt.timedelta(days=7)]
    assert older
    assert len({w.isocalendar()[:2] for w in older}) == len(older)
    assert all(now - w <= dt.timedelta(weeks=8) for w in older)
    assert len(kept) <= 17
    assert (dest / "not-a-run").is_dir()


def test_status_is_world_readable_and_runs_are_private(archive_db, tmp_path):
    dest = tmp_path / "backups"
    assert bna.main(_args(archive_db, dest)) == 0
    assert stat.S_IMODE((dest / "STATUS.json").stat().st_mode) == 0o644
    assert stat.S_IMODE(_runs(dest)[0].stat().st_mode) == 0o700
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755


def _live_layout(root):
    for volume, name in (("ft_user_data", "tradesv3.live.X.sqlite"),
                         ("killers_receiver_state", "r.sqlite")):
        data = root / f"proj_{volume}" / "_data"
        data.mkdir(parents=True)
        conn = sqlite3.connect(data / name)
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()


def test_archive_failure_leaves_live_backup_untouched(archive_db, tmp_path):
    volumes = tmp_path / "volumes"
    _live_layout(volumes)
    archive_dest = tmp_path / "news-archive"
    live_dest = tmp_path / "master-trader"

    assert bna.main(_args(_corrupt(tmp_path / "bad.sqlite"), archive_dest)) == 1
    assert live.main(["--dest", str(live_dest), "--volumes-root", str(volumes),
                      "--project", "proj", "--observer-db", str(tmp_path / "none.sqlite"),
                      "--no-upload", "--no-alert"]) == 0
    live_runs = _runs(live_dest)
    assert len(live_runs) == 1
    assert len(json.loads((live_runs[0] / "MANIFEST.json").read_text())["files"]) == 2
    assert not list(live_dest.rglob("archive.sqlite.gz"))

    with open(live_dest / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert bna.main(_args(archive_db, archive_dest)) == 0
    assert len(_runs(archive_dest)) == 1


def test_destinations_are_disjoint_from_the_live_backup():
    assert not bna.DEST.is_relative_to(live.DEST)
    assert not live.DEST.is_relative_to(bna.DEST)
    assert bna.DRIVE_REMOTE != live.DRIVE_REMOTE
    assert not bna.DRIVE_REMOTE.startswith(live.DRIVE_REMOTE + "/")
    assert not live.DRIVE_REMOTE.startswith(bna.DRIVE_REMOTE + "/")


def test_lowers_cpu_and_io_priority(archive_db, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bna.os, "nice", lambda n: calls.append(("nice", n)))
    monkeypatch.setattr(bna.subprocess, "run", lambda argv, **kw: calls.append(("run", argv)))
    REAL_LOWER_PRIORITY()
    assert calls == [("nice", 10), ("run", ["ionice", "-c3", "-p", str(os.getpid())])]

    seen = []
    monkeypatch.setattr(bna, "lower_priority", lambda: seen.append(1))
    assert bna.main(_args(archive_db, tmp_path / "backups")) == 0
    assert seen == [1]


def test_lower_priority_survives_a_missing_ionice(monkeypatch):
    monkeypatch.setattr(bna.os, "nice", lambda n: None)

    def missing(argv, **kw):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(bna.subprocess, "run", missing)
    REAL_LOWER_PRIORITY()


def test_script_is_stdlib_only():
    names = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text())):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split(".")[0])
    assert "backup_live_dbs" in names
    assert names <= set(sys.stdlib_module_names) | {"__future__", "backup_live_dbs"}
