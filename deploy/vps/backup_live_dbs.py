#!/usr/bin/env python3
"""Scheduled backup of master-trader's live state on the VPS (#99).

Until this existed, nothing backed up the trade databases or the receivers'
state. The one scheduled backup in the repo (automation_scheduler.sh, 02:00)
reads ~/ft_userdata/user_data, where no live database lives, and is not
installed. Dokploy has no backup or volume-backup configured (checked
2026-10-02).

What it copies, from the compose project's docker volumes:

  ft_user_data             every tradesv3.live.*.sqlite
  killers_receiver_state   every *.sqlite (signal -> trade -> TP-ladder state)
  insiders_receiver_state  every *.sqlite

The receiver state cannot be rebuilt from the exchange: it is what ties an
open position to its source signal, posted stop and targets.

How: each database is opened read-only (file:...?mode=ro) and copied with
SQLite's online backup API, which reads one consistent snapshot, including
committed WAL frames, without stopping the bots. The copy is switched to
journal_mode=DELETE (one self-contained file), must pass PRAGMA
integrity_check, and is gzipped. Each run writes one directory
<dest>/<UTC stamp>/ with a MANIFEST.json (source, size, sha256 of the
uncompressed copy). The run lands under a temporary name and is renamed
into place only when every required file succeeded.

After the local snapshot is complete, rclone copies it to an operator-owned
Google Drive remote and checks the remote objects against the local files.
Only then are local and remote snapshot directories older than 30 days pruned.

Runs as root (docker's volume directories are root-only), from root's
crontab. See deploy/vps/README.md "Backups" for install and restore.
On failure it exits non-zero and posts a warning to trade-webhook.

Stdlib only: the script must run from the Dokploy checkout with the host's
/usr/bin/python3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT = "compose-bypass-mobile-port-fbk1m6"
VOLUMES_ROOT = Path("/var/lib/docker/volumes")
DEST = Path("/home/ubuntu/backups/master-trader")
OPS_ENV_FILE = Path("/etc/lake/ops-bot.env")
ALERT_URL = "http://127.0.0.1:8088/freqtrade/event"
RCLONE = Path("/usr/bin/rclone")
RCLONE_CONFIG = Path("/etc/master-trader-backup/rclone.conf")
DRIVE_REMOTE = "operator-drive:Master-Trader/backups"

KEEP_DAYS = 30
MIN_FREE_MB = 1024
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

# (volume, glob, kind, required). A required source with no matching file
# fails the run: a volume that suddenly holds no database is exactly what a
# backup must not hide.
SOURCES = [
    ("ft_user_data", "tradesv3.live.*.sqlite", "sqlite", True),
    ("killers_receiver_state", "*.sqlite", "sqlite", True),
    ("insiders_receiver_state", "*.sqlite", "sqlite", True),
]


class BackupError(RuntimeError):
    pass


def plan(volumes_root: Path, project: str) -> list[tuple[str, Path, str]]:
    """[(name inside the snapshot, source path, kind)] for this run."""
    items: list[tuple[str, Path, str]] = []
    for volume, pattern, kind, required in SOURCES:
        data = volumes_root / f"{project}_{volume}" / "_data"
        found = sorted(p for p in data.glob(pattern) if p.is_file()) if data.is_dir() else []
        if required and not found:
            raise BackupError(f"no {pattern} in {data}")
        items += [(f"{volume}/{p.name}", p, kind) for p in found]
    return items


def backup_sqlite(src: Path, dst: Path) -> None:
    """Consistent online copy of `src` into `dst`, verified, journal_mode=DELETE."""
    source = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
            result = target.execute("PRAGMA integrity_check").fetchall()
        finally:
            target.close()
    finally:
        source.close()
    if result != [("ok",)]:
        raise BackupError(f"integrity_check failed for copy of {src}: {result[:3]}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gzip(path: Path) -> Path:
    out = path.with_name(path.name + ".gz")
    with open(path, "rb") as fin, gzip.open(out, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)
    path.unlink()
    return out


def run_backup(items: list[tuple[str, Path, str]], dest: Path, now: dt.datetime) -> Path:
    stamp = now.strftime(STAMP_FORMAT)
    final = dest / stamp
    staging = dest / f".partial-{stamp}"
    if final.exists():
        raise BackupError(f"{final} already exists")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    manifest = {"created_utc": now.isoformat(), "files": []}
    try:
        for name, src, kind in items:
            out = staging / name
            out.parent.mkdir(parents=True, exist_ok=True)
            if kind == "sqlite":
                backup_sqlite(src, out)
            else:
                shutil.copy2(src, out)
            entry = {"name": name, "source": str(src), "bytes": out.stat().st_size,
                     "sha256": _sha256(out), "integrity_check": "ok"}
            if kind == "sqlite":
                entry["stored_as"] = _gzip(out).name
            manifest["files"].append(entry)
        (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def runs_to_prune(stamps: list[str], now: dt.datetime, keep_days: int = KEEP_DAYS) -> list[str]:
    """Run directories older than the retention window; ignore other names."""
    dated = []
    for s in stamps:
        try:
            dated.append((dt.datetime.strptime(s, STAMP_FORMAT).replace(tzinfo=dt.timezone.utc), s))
        except ValueError:
            continue
    return sorted(s for when, s in dated if now - when > dt.timedelta(days=keep_days))


def prune(dest: Path, now: dt.datetime) -> list[str]:
    """Apply retention; also clear staging left by a run that was killed."""
    for stale in dest.glob(".partial-*"):
        shutil.rmtree(stale, ignore_errors=True)
    stamps = [p.name for p in dest.iterdir() if p.is_dir() and not p.name.startswith(".")]
    doomed = runs_to_prune(stamps, now)
    for s in doomed:
        shutil.rmtree(dest / s)
    return doomed


def _remote_child(remote: str, name: str) -> str:
    return f"{remote.rstrip('/')}/{name}"


def upload_and_prune(run: Path, remote: str, config: Path, rclone: Path,
                     now: dt.datetime, runner=subprocess.run) -> list[str]:
    """Upload, verify, then prune timestamped remote runs older than 30 days."""
    if not config.is_file():
        raise BackupError(f"rclone config missing: {config}")
    if not rclone.is_file():
        raise BackupError(f"rclone binary missing: {rclone}")

    common = ["--config", str(config)]
    target = _remote_child(remote, run.name)
    runner([str(rclone), "copy", str(run), target, *common, "--checksum", "--immutable"],
           check=True)
    runner([str(rclone), "check", str(run), target, *common, "--one-way", "--download"],
           check=True)
    listed = runner([str(rclone), "lsjson", remote, *common, "--dirs-only", "--max-depth", "1"],
                    check=True, capture_output=True, text=True)
    try:
        entries = json.loads(listed.stdout)
        names = [entry["Name"] for entry in entries
                 if isinstance(entry, dict) and isinstance(entry.get("Name"), str)]
    except (json.JSONDecodeError, TypeError) as exc:
        raise BackupError(f"invalid rclone directory listing: {exc}") from exc
    doomed = runs_to_prune(names, now)
    for stamp in doomed:
        runner([str(rclone), "purge", _remote_child(remote, stamp), *common], check=True)
    return doomed


def _read_token(env_file: Path) -> str:
    """Only TRADE_WEBHOOK_NOTIFY_TOKEN; the file also holds the Telegram bot token."""
    try:
        for line in env_file.read_text().splitlines():
            if line.startswith("TRADE_WEBHOOK_NOTIFY_TOKEN="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def alert(message: str) -> bool:
    """Best effort: a failed alert never changes the exit code."""
    body = json.dumps({"type": "warning", "bot_name": "db-backup", "status": message}).encode()
    headers = {"Content-Type": "application/json"}
    token = _read_token(OPS_ENV_FILE)
    if token:
        headers["X-Notify-Token"] = token
    try:
        req = urllib.request.Request(ALERT_URL, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001 - alerting must not raise
        print(f"alert not sent: {exc}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dest", type=Path, default=DEST)
    ap.add_argument("--volumes-root", type=Path, default=VOLUMES_ROOT)
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--rclone", type=Path, default=RCLONE)
    ap.add_argument("--rclone-config", type=Path, default=RCLONE_CONFIG)
    ap.add_argument("--drive-remote", default=DRIVE_REMOTE)
    ap.add_argument("--no-upload", action="store_true",
                    help="make only the local snapshot (manual diagnostics/tests only)")
    ap.add_argument("--no-alert", action="store_true", help="do not post failures to trade-webhook")
    ap.add_argument("--list", action="store_true",
                    help="print what a run would copy and exit; opens and writes nothing")
    args = ap.parse_args(argv)

    if args.list:
        for name, src, kind in plan(args.volumes_root, args.project):
            print(f"{kind:6} {src.stat().st_size:>10} {name}")
        return 0

    os.umask(0o077)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        args.dest.mkdir(parents=True, exist_ok=True)
        free_mb = shutil.disk_usage(args.dest).free // (1 << 20)
        if free_mb < MIN_FREE_MB:
            raise BackupError(f"only {free_mb} MB free under {args.dest}")
        with open(args.dest / ".lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(f"{now.isoformat()} SKIP: another backup run holds the lock")
                return 0
            items = plan(args.volumes_root, args.project)
            final = run_backup(items, args.dest, now)
            remote_pruned = []
            if not args.no_upload:
                remote_pruned = upload_and_prune(
                    final, args.drive_remote, args.rclone_config, args.rclone, now)
            pruned = prune(args.dest, now)
        print(f"{now.isoformat()} OK {final} ({len(items)} files; "
              f"pruned local={len(pruned)} remote={len(remote_pruned)})")
        return 0
    except Exception as exc:  # noqa: BLE001 - report every failure the same way
        message = f"master-trader backup FAILED: {exc}"
        print(f"{now.isoformat()} {message}", file=sys.stderr)
        if not args.no_alert:
            alert(message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
