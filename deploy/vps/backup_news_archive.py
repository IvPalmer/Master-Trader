#!/usr/bin/env python3
"""Daily backup of the PIT news archive (#229 Part B, spec §5.2).

The archive is irreplaceable by design: no vendor sells the same point-in-time
history, so a disk loss would reset its data clock to zero.

This is a separate job from backup_live_dbs.py on purpose. That job is
all-or-nothing, so adding the archive to it would let an archive failure break
the live trade-DB backup. This one has its own cron entry, lock, destination
(/home/ubuntu/backups/news-archive), retention (7 daily plus 8 weekly copies,
never fewer than the 7 newest) and status file. It imports the consistent
snapshot and prune helpers from backup_live_dbs.py and never modifies it.

How: the archive is opened read-only and copied with SQLite's online backup
API, which reads one consistent snapshot, committed WAL frames included, while
the news-archive service keeps writing. The copy is switched to
journal_mode=DELETE, must pass PRAGMA integrity_check, has its per-table row
counts recorded, and is gzipped. A run lands in <dest>/.partial-<stamp> and is
renamed to <dest>/<stamp> only when complete; a failed run removes its staging.

It cannot fill the bots' disk: before any snapshot it needs 15 GiB free plus
twice the size of archive.sqlite and its -wal file, or it skips. It holds its
own non-blocking flock, so runs never overlap, and runs under nice 10 and
ionice idle.

Off-host is opt-in: with --upload the new run is copied to an rclone remote
(default operator-drive:Master-Trader/news-archive, reusing the live backup's
root-only config), verified with a downloading `rclone check`, and only then is
the same retention applied remotely. A failed upload keeps the new snapshot and
the local retention, and is recorded. --drill local|remote restores the newest
snapshot into a temporary directory and checks its sha256, PRAGMA
integrity_check and row counts against the manifest. The off-host copy counts
only once the latest remote drill has passed.

Each run or drill rewrites <dest>/STATUS.json (mode 0644), which the nightly
health report reads as the ubuntu user. Runs are root-only (0700).

Runs as root from root's crontab, from the root-owned Dokploy checkout. See
docs/ops/news-archive-backup.md for the contract, install and rollback.

Stdlib only: it must run with the host's /usr/bin/python3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from backup_live_dbs import (RCLONE_CONFIG, STAMP_FORMAT, BackupError, _gzip, _remote_child,
                             _sha256, backup_sqlite, resolve_rclone, runs_to_prune)

ARCHIVE_DB = Path("/home/ubuntu/master-trader/research/news_archive/data/archive.sqlite")
DEST = Path("/home/ubuntu/backups/news-archive")
DRIVE_REMOTE = "operator-drive:Master-Trader/news-archive"
RETENTION = {"keep_days": 7, "keep_weeks": 8, "min_keep": 7}
RESERVE_BYTES = 15 * 1024**3
STORED_AS = "archive.sqlite.gz"
STATUS_NAME = "STATUS.json"
STATUS_KEYS = ("last_run_at", "last_run_result", "last_run_error", "latest_snapshot",
               "upload", "local_drill", "offhost_drill")
GIB = 1024**3


class NotEnoughSpace(BackupError):
    pass


def required_free_bytes(db: Path) -> int:
    """15 GiB reserve plus twice the archive, counting an uncheckpointed WAL."""
    if not db.is_file():
        raise BackupError(f"archive database missing: {db}")
    size = db.stat().st_size
    try:
        size += db.with_name(db.name + "-wal").stat().st_size
    except FileNotFoundError:
        pass
    return RESERVE_BYTES + 2 * size


def check_free_space(where: Path, db: Path) -> None:
    need = required_free_bytes(db)
    free = shutil.disk_usage(where).free
    if free < need:
        raise NotEnoughSpace(f"free {free / GIB:.1f} GiB < required {need / GIB:.1f} GiB "
                             f"under {where}")


def row_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name")]
        return {t: conn.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
                for t in tables}
    finally:
        conn.close()


def snapshot(db: Path, dest: Path, now: dt.datetime) -> Path:
    """One verified, gzipped copy of the archive in <dest>/<stamp>/."""
    stamp = now.strftime(STAMP_FORMAT)
    final = dest / stamp
    staging = dest / f".partial-{stamp}"
    if final.exists():
        raise BackupError(f"{final} already exists")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        os.chmod(staging, 0o700)
        copy = staging / "archive.sqlite"
        backup_sqlite(db, copy)
        manifest = {"created_utc": now.isoformat(), "source": str(db),
                    "bytes": copy.stat().st_size, "sha256": _sha256(copy),
                    "integrity_check": "ok", "row_counts": row_counts(copy)}
        manifest["stored_as"] = _gzip(copy).name
        (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def _is_stamp(name: str) -> bool:
    try:
        dt.datetime.strptime(name, STAMP_FORMAT)
    except ValueError:
        return False
    return True


def local_stamps(dest: Path) -> list[str]:
    """Complete local runs, oldest first."""
    return sorted(p.name for p in dest.iterdir()
                  if _is_stamp(p.name) and p.is_dir() and (p / "MANIFEST.json").is_file())


def prune_local(dest: Path, now: dt.datetime) -> list[str]:
    """Apply the archive's retention; also clear staging left by a killed run."""
    for stale in dest.glob(".partial-*"):
        shutil.rmtree(stale, ignore_errors=True)
    stamps = [p.name for p in dest.iterdir() if p.is_dir() and not p.name.startswith(".")]
    doomed = runs_to_prune(stamps, now, **RETENTION)
    for stamp in doomed:
        shutil.rmtree(dest / stamp)
    return doomed


def _check_rclone(config: Path, rclone: Path) -> list[str]:
    if not config.is_file():
        raise BackupError(f"rclone config missing: {config}")
    if not rclone.is_file():
        raise BackupError(f"rclone binary missing: {rclone}")
    return ["--config", str(config)]


def _remote_names(remote: str, common: list[str], rclone: Path, runner) -> list[str]:
    listed = runner([str(rclone), "lsjson", remote, *common, "--dirs-only", "--max-depth", "1"],
                    check=True, capture_output=True, text=True)
    try:
        entries = json.loads(listed.stdout)
        if not isinstance(entries, list):
            raise TypeError(f"expected a list, got {type(entries).__name__}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise BackupError(f"invalid rclone directory listing: {exc}") from exc
    return [e["Name"] for e in entries if isinstance(e, dict) and isinstance(e.get("Name"), str)]


def upload(run: Path, remote: str, config: Path, rclone: Path, now: dt.datetime,
           runner=subprocess.run) -> list[str]:
    """Copy `run` off-host, verify it, then apply the archive's retention remotely.

    Nothing is purged unless the copy was verified and the listing parsed.
    """
    common = _check_rclone(config, rclone)
    target = _remote_child(remote, run.name)
    runner([str(rclone), "copy", str(run), target, *common, "--checksum", "--immutable"],
           check=True)
    runner([str(rclone), "check", str(run), target, *common, "--one-way", "--download"],
           check=True)
    doomed = runs_to_prune(_remote_names(remote, common, rclone, runner), now, **RETENTION)
    for stamp in doomed:
        runner([str(rclone), "purge", _remote_child(remote, stamp), *common], check=True)
    return doomed


def _verify(run: Path, restored: Path) -> None:
    manifest = json.loads((run / "MANIFEST.json").read_text())
    with gzip.open(run / STORED_AS, "rb") as fin, open(restored, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    if _sha256(restored) != manifest["sha256"]:
        raise BackupError(f"sha256 of {run.name} does not match its manifest")
    conn = sqlite3.connect(f"{restored.resolve().as_uri()}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    if result != [("ok",)]:
        raise BackupError(f"integrity_check failed for {run.name}: {result[:3]}")
    counts = row_counts(restored)
    if counts != manifest["row_counts"]:
        raise BackupError(f"row count mismatch for {run.name}: restored {counts}, "
                          f"manifest {manifest['row_counts']}")


def drill(source: str, dest: Path, db: Path, remote: str, config: Path, rclone: Path | None,
          runner=subprocess.run) -> str:
    """Restore the newest local or remote snapshot to a temporary path and verify it.

    Returns the stamp; raises BackupError naming the check that failed.
    """
    if source == "local":
        stamps = local_stamps(dest)
    else:
        if rclone is None:
            raise BackupError("a remote drill needs rclone")
        common = _check_rclone(config, rclone)
        stamps = sorted(n for n in _remote_names(remote, common, rclone, runner) if _is_stamp(n))
    if not stamps:
        raise BackupError(f"no {source} snapshot to drill")
    stamp = stamps[-1]
    check_free_space(Path(tempfile.gettempdir()), db)
    with tempfile.TemporaryDirectory(prefix="news-archive-drill-") as tmp:
        if source == "local":
            run = dest / stamp
        else:
            run = Path(tmp) / stamp
            runner([str(rclone), "copy", _remote_child(remote, stamp), str(run), *common],
                   check=True)
        _verify(run, Path(tmp) / "archive.sqlite")
    return stamp


def read_status(dest: Path) -> dict:
    """The last STATUS.json, with every key present (absent reads as None).

    A missing or unreadable file reads as empty: the next write replaces it.
    """
    try:
        loaded = json.loads((dest / STATUS_NAME).read_text())
    except (OSError, ValueError):
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    return {key: loaded.get(key) for key in STATUS_KEYS}


def write_status(dest: Path, status: dict) -> None:
    """Atomic replace; 0644 so the ubuntu-run health report can read it."""
    fd, tmp = tempfile.mkstemp(prefix=f".{STATUS_NAME}.", dir=dest)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(status, f, indent=1, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest / STATUS_NAME)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def lower_priority() -> None:
    """nice 10 and idle IO class, best effort: neither may fail the run."""
    try:
        os.nice(10)
    except OSError:
        pass
    try:
        subprocess.run(["ionice", "-c3", "-p", str(os.getpid())], check=False)
    except OSError:
        pass


def _err(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, BackupError) else f"{type(exc).__name__}: {exc}"


def _run(args: argparse.Namespace, now: dt.datetime, status: dict) -> int:
    """Snapshot, local retention, then the optional upload."""
    status.update(last_run_at=now.isoformat(), last_run_result="failed", last_run_error=None)
    try:
        lower_priority()
        check_free_space(args.dest, args.db)
        run = snapshot(args.db, args.dest, now)
        pruned = prune_local(args.dest, now)
    except NotEnoughSpace as exc:
        status.update(last_run_result="skipped", last_run_error=_err(exc))
        print(f"{now.isoformat()} news-archive backup SKIPPED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - every failure is recorded the same way
        status["last_run_error"] = _err(exc)
        print(f"{now.isoformat()} news-archive backup FAILED: {exc}", file=sys.stderr)
        return 1
    summary = f"pruned local={len(pruned)}"
    if args.upload:
        record = {"at": now.isoformat(), "ok": False, "error": None, "stamp": run.name}
        status["upload"] = record
        try:
            remote_pruned = upload(run, args.drive_remote, args.rclone_config,
                                   resolve_rclone(args.rclone), now, runner=subprocess.run)
        except Exception as exc:  # noqa: BLE001
            record["error"] = _err(exc)
            status.update(last_run_result="upload_failed", last_run_error=record["error"])
            print(f"{now.isoformat()} news-archive backup upload FAILED (snapshot {run} kept): "
                  f"{exc}", file=sys.stderr)
            return 1
        record["ok"] = True
        summary += f" remote={len(remote_pruned)}"
    status["last_run_result"] = "ok"
    print(f"{now.isoformat()} OK {run} ({summary})")
    return 0


def _drill(args: argparse.Namespace, now: dt.datetime, status: dict) -> int:
    """Writes only local_drill or offhost_drill."""
    record = {"at": now.isoformat(), "stamp": None, "ok": False, "error": None}
    status["local_drill" if args.drill == "local" else "offhost_drill"] = record
    try:
        lower_priority()
        rclone = None if args.drill == "local" else resolve_rclone(args.rclone)
        record["stamp"] = drill(args.drill, args.dest, args.db, args.drive_remote,
                                args.rclone_config, rclone, runner=subprocess.run)
    except Exception as exc:  # noqa: BLE001
        record["error"] = _err(exc)
        print(f"{now.isoformat()} news-archive {args.drill} drill FAILED: {exc}", file=sys.stderr)
        return 1
    record["ok"] = True
    print(f"{now.isoformat()} DRILL {args.drill} OK {record['stamp']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--db", type=Path, default=ARCHIVE_DB)
    ap.add_argument("--dest", type=Path, default=DEST)
    ap.add_argument("--upload", action="store_true",
                    help="copy the new run off-host and verify it (opt-in)")
    ap.add_argument("--drive-remote", default=DRIVE_REMOTE)
    ap.add_argument("--rclone", type=Path,
                    help="rclone executable (default: discover it from PATH/system locations)")
    ap.add_argument("--rclone-config", type=Path, default=RCLONE_CONFIG)
    ap.add_argument("--drill", choices=("local", "remote"),
                    help="restore the newest snapshot to a temporary path and verify it; "
                         "makes no snapshot")
    args = ap.parse_args(argv)

    os.umask(0o077)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        args.dest.mkdir(parents=True, exist_ok=True)
        os.chmod(args.dest, 0o755)
        lock = open(args.dest / ".lock", "w")
    except OSError as exc:
        print(f"{now.isoformat()} news-archive backup FAILED: {exc}", file=sys.stderr)
        return 1
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"{now.isoformat()} SKIP: another run holds the lock")
            return 0
        status = read_status(args.dest)
        rc = _drill(args, now, status) if args.drill else _run(args, now, status)
        try:
            if not args.drill:
                status["latest_snapshot"] = (local_stamps(args.dest) or [None])[-1]
            write_status(args.dest, status)
        except Exception as exc:  # noqa: BLE001
            print(f"{now.isoformat()} news-archive backup FAILED to write {STATUS_NAME}: {exc}",
                  file=sys.stderr)
            return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
