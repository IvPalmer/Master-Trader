#!/usr/bin/env python3
"""Archive one ended bot epoch as an immutable dashboard record (#277).

Freqtrade opens a different SQLite per mode, so a bot demoted to dry-run,
retired or deleted stops serving its live trades and the dashboard drops them.
This writes the epoch's record to epoch-records/ on the ft_user_data volume,
where the dashboard reads it. Run it as root on the VPS from the Dokploy
checkout, once the bot no longer writes the DB being archived:

  sudo python3 deploy/vps/archive_bot_epoch.py \\
      --record-id killers-ft.live-r5 --bot-key killers-ft \\
      --source-db archive-killers-live-20261110.sqlite --mode live \\
      --start-ms 1787854748304 --end-ms <first ms after the epoch> \\
      --starting-capital 98 --reason "moved to dry-run" --issue 275 \\
      --ft-container ft-killers-scalp

Each step refuses on failure; nothing reaches epoch-records/ unless all pass:
  1. the record id is new;
  2. a tradesv3.* source is no longer the FT container's DB (FREQTRADE__DB_URL
     in /proc/1/environ); an archive-*.sqlite source is a backup already;
  3. a WAL-aware backup (SQLite backup API, journal_mode=DELETE, integrity
     check) is taken, or the given archive is verified; its sha256 is recorded;
  4. the backup holds no open trade;
  5. Freqtrade's own Trade.to_json() serializes the raw trades inside the FT
     container, on a temporary copy, because init_db may migrate it;
  6. ft-dashboard builds the record with its own _poll_bot on frozen inputs
     (build_epoch_record.py); Hyperliquid reconciliation runs there, once;
  7. the record's trades are exactly the SQLite closed trades of the half-open
     window [start, end) and its raw Freqtrade P&L matches; the corrected
     (userFills) total is reported separately;
  8. epoch-records/<record id>.json is written atomically, never over an
     existing file, mode 0444.
One run at a time holds a lock on the volume. Every file the script writes
there is created exclusively under an unpredictable name, never through a
link planted at a known path.

A bot no longer in the dashboard's BOTS needs --bot-config (a JSON object with
at least name and label, plus venue, account_group and wallet_env for
Hyperliquid). --label, --strategy-version and --epoch-label override display.

Stdlib only: the host's /usr/bin/python3 runs it.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backup_live_dbs import PROJECT, VOLUMES_ROOT, BackupError, _sha256, backup_sqlite

# Same rule as ft_dashboard/epoch_records.RECORD_ID_RE: never a running bot key.
RECORD_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9.-]*")
SOURCE_RE = re.compile(r"(tradesv3|archive-)[A-Za-z0-9_.-]*\.sqlite")
FT_MOUNT = "/freqtrade/user_data"
SERIALIZE = (
    "import json, sys\n"
    "from freqtrade.persistence import Trade, init_db\n"
    "init_db('sqlite:///' + sys.argv[1])\n"
    "print(json.dumps([t.to_json() for t in Trade.get_trades([])], default=str))\n"
)


class ArchiveError(RuntimeError):
    pass


def _ms(value: str | None) -> int | None:
    """Freqtrade's open/close_timestamp from its naive-UTC SQLite date."""
    if not value:
        return None
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def running_db(container: str, runner) -> str:
    """Basename of the DB the FT container's process opened."""
    environ = runner(["docker", "exec", container, "cat", "/proc/1/environ"],
                     capture_output=True, check=True).stdout
    for item in environ.split(b"\0"):
        if item.startswith(b"FREQTRADE__DB_URL="):
            return item.split(b"=", 1)[1].decode().split("?", 1)[0].rsplit("/", 1)[-1]
    raise ArchiveError(f"{container} sets no FREQTRADE__DB_URL; cannot show the bot left this DB")


def verify_backup(path: Path) -> Path:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    if integrity != [("ok",)] or journal != "delete":
        raise ArchiveError(f"{path.name}: integrity {integrity[:1]}, journal_mode {journal}")
    return path


def read_ledger(path: Path) -> tuple[int, dict]:
    """(open trades, {identity: (close_ms, close_profit_abs)}) of the backup."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        open_count = conn.execute("SELECT count(*) FROM trades WHERE is_open = 1").fetchone()[0]
        rows = conn.execute("SELECT id, pair, open_date, close_date, close_profit_abs "
                            "FROM trades WHERE is_open = 0").fetchall()
    finally:
        conn.close()
    return open_count, {(pair, _ms(opened), int(tid)): (_ms(closed), float(profit or 0))
                        for tid, pair, opened, closed, profit in rows}


def write_record(records_dir: Path, record_id: str, record: dict) -> Path:
    records_dir.mkdir(mode=0o755, exist_ok=True)
    if records_dir.is_symlink():
        raise ArchiveError(f"{records_dir} is a symlink; not writing through it")
    final = records_dir / f"{record_id}.json"
    # mkstemp creates a new file exclusively and never follows a planted link.
    fd, name = tempfile.mkstemp(prefix=f".{record_id}.", suffix=".tmp", dir=records_dir)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), 0o444)
        os.link(tmp, final)  # atomic, and fails rather than replace
    except FileExistsError:
        raise ArchiveError(f"{final} appeared during the run; not overwritten") from None
    finally:
        tmp.unlink()
    return final


def lock_volume(data: Path) -> int:
    """One archive run at a time on this volume; the lock ends with the process."""
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ArchiveError("another archive run holds the lock on this volume") from None
    return fd


def archive(args, runner=subprocess.run) -> tuple[Path, dict]:
    if not RECORD_ID_RE.fullmatch(args.record_id):
        raise ArchiveError("record id must look like <bot key>.<epoch>, e.g. killers-ft.live-r5")
    if not SOURCE_RE.fullmatch(args.source_db):
        raise ArchiveError("source DB must be a tradesv3.*.sqlite or archive-*.sqlite file name")
    if args.start_ms >= args.end_ms or not (math.isfinite(args.starting_capital)
                                           and args.starting_capital > 0):
        raise ArchiveError("need start-ms < end-ms and a positive starting capital")
    data = args.volumes_root / f"{args.project}_ft_user_data" / "_data"
    records_dir = data / "epoch-records"
    lock = lock_volume(data)
    try:
        return _archive(args, runner, data, records_dir)
    finally:
        os.close(lock)


def _archive(args, runner, data: Path, records_dir: Path) -> tuple[Path, dict]:
    # 1. A record is never replaced.
    if (records_dir / f"{args.record_id}.json").exists():
        raise ArchiveError(f"record {args.record_id} already exists")
    # 2-3. The bot must be off this DB; then a self-contained, verified backup.
    if args.source_db.startswith("archive-"):
        backup = data / args.source_db
        if not backup.is_file():
            raise ArchiveError(f"{backup} not found")
    else:
        if running_db(args.ft_container, runner) == args.source_db:
            raise ArchiveError(f"{args.source_db} is still {args.ft_container}'s DB; "
                               "change the bot's mode first")
        backup = data / f"archive-{args.record_id}.sqlite"
        if not backup.exists() and not backup.is_symlink():
            # Built in a new root-only directory, so nothing planted on the
            # volume can redirect the write; rename never follows a link.
            private = Path(tempfile.mkdtemp(prefix=".epoch-archive-", dir=data))
            try:
                backup_sqlite(data / args.source_db, private / "backup.sqlite")
                os.replace(private / "backup.sqlite", backup)
            finally:
                shutil.rmtree(private, ignore_errors=True)
    if backup.is_symlink():
        raise ArchiveError(f"{backup.name} is a symlink; archive only a real backup file")
    sha256 = _sha256(verify_backup(backup))
    # 4. Only an ended epoch: nothing open.
    open_count, ledger = read_ledger(backup)
    if open_count:
        raise ArchiveError(f"{backup.name} has {open_count} open trade(s)")
    expected = {k: v for k, v in ledger.items()
                if v[0] is not None and args.start_ms <= v[0] < args.end_ms}
    if not expected:
        raise ArchiveError("no closed trade in [start-ms, end-ms); check the window")
    # 5. Freqtrade's serialization, on a copy it may migrate. mkstemp creates
    # the copy exclusively under an unpredictable name and never follows a
    # planted link; whatever the FT side does to it, step 7 checks the result
    # against this script's own read of the backup.
    fd, name = tempfile.mkstemp(prefix=".epoch-archive-", suffix=".sqlite", dir=data)
    tmp = Path(name)
    try:
        with open(backup, "rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst)
            os.fchmod(dst.fileno(), 0o666)  # the FT image runs as ftuser
        out = runner(["docker", "exec", args.ft_container, "python", "-c", SERIALIZE,
                      f"{FT_MOUNT}/{tmp.name}"], capture_output=True, check=True, text=True).stdout
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{tmp}{suffix}").unlink(missing_ok=True)
    raw_trades = json.loads(out.strip().splitlines()[-1])
    # 6. The dashboard's own calculation, frozen.
    spec = {
        "record_id": args.record_id, "bot_key": args.bot_key, "mode": args.mode,
        "start_ms": args.start_ms, "end_ms": args.end_ms,
        "starting_capital": args.starting_capital, "reason": args.reason, "issue": args.issue,
        "source_backup": backup.name, "source_sha256": sha256, "trades": raw_trades,
        "bot_config": json.loads(args.bot_config.read_text()) if args.bot_config else None,
        "display": {k: v for k, v in (("label", args.label), ("strategy_version", args.strategy_version),
                                      ("epoch_label", args.epoch_label)) if v},
    }
    out = runner(["docker", "exec", "-i", args.dashboard_container, "python",
                  "/app/build_epoch_record.py"], input=json.dumps(spec),
                 capture_output=True, check=True, text=True).stdout
    record = json.loads(out)
    # 7. Exactly SQLite's closed trades of the window, and Freqtrade's raw P&L.
    trades = {(t["pair"], int(t["open_timestamp"]), int(t["trade_id"])): t for t in record["trades"]}
    if set(trades) != set(expected) or len(trades) != len(record["trades"]):
        raise ArchiveError(f"record holds {len(record['trades'])} trades, SQLite "
                           f"{len(expected)} in the window; identities differ")
    raw = sum(float(t.get("freqtrade_profit_abs", t.get("profit_abs")) or 0) for t in trades.values())
    sqlite_raw = sum(profit for _, profit in expected.values())
    if abs(raw - sqlite_raw) > 1e-6 * len(expected) or abs(record["totals"]["raw_profit_abs"] - raw) > 1e-6:
        raise ArchiveError(f"raw P&L {raw:.8f} does not match SQLite {sqlite_raw:.8f}")
    if (record.get("record_id"), record.get("source_sha256")) != (args.record_id, sha256):
        raise ArchiveError("record does not name this record id and backup")
    # 8. Atomic, never over an existing record, read-only.
    return write_record(records_dir, args.record_id, record), record


def main(argv: list[str] | None = None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--bot-key", required=True)
    ap.add_argument("--source-db", required=True,
                    help="file name on the ft_user_data volume: tradesv3.*.sqlite or archive-*.sqlite")
    ap.add_argument("--mode", required=True, choices=["live", "paper"])
    ap.add_argument("--start-ms", type=int, required=True)
    ap.add_argument("--end-ms", type=int, required=True, help="exclusive")
    ap.add_argument("--starting-capital", type=float, required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--issue", required=True, type=int)
    ap.add_argument("--ft-container", required=True,
                    help="FT container for Trade.to_json(); for a tradesv3 source, the bot that ran it")
    ap.add_argument("--dashboard-container", default="ft-dashboard")
    ap.add_argument("--bot-config", type=Path, help="JSON config for a bot no longer in BOTS")
    ap.add_argument("--label")
    ap.add_argument("--strategy-version")
    ap.add_argument("--epoch-label")
    ap.add_argument("--volumes-root", type=Path, default=VOLUMES_ROOT)
    ap.add_argument("--project", default=PROJECT)
    args = ap.parse_args(argv)
    try:
        path, record = archive(args, runner)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
        print(f"REFUSED: {' '.join(map(str, exc.cmd[:4]))} failed: {(detail or '').strip()[-500:]}",
              file=sys.stderr)
        return 1
    except (ArchiveError, BackupError, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    totals = record["totals"]
    print(f"OK {path}: {totals['closed_trades']} closed trades · Freqtrade raw "
          f"{totals['raw_profit_abs']:+.2f} · corrected {totals['corrected_profit_abs']:+.2f} "
          f"({totals['reconciled_trades']} reconciled, {totals['fill_reconciliation']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
