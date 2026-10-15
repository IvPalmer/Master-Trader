"""Scheduled backup of the live databases and receiver state (#99).

The only scheduled backup in the repo read ~/ft_userdata/user_data, where no
live database lives. deploy/vps/backup_live_dbs.py reads the compose
project's docker volumes. These tests build the same layout in tmp_path:
WAL-mode databases held open by a writer (as the running bots and receivers
hold them), with rows that exist only in the WAL.
"""

import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "vps" / "backup_live_dbs.py"
PROJECT = "proj"


def _load():
    spec = importlib.util.spec_from_file_location("backup_live_dbs_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bk():
    return _load()


def _wal_db(path: Path, rows: int) -> sqlite3.Connection:
    """A WAL database whose rows are committed but not checkpointed, left open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, pair TEXT)")
    conn.executemany("INSERT INTO trades (pair) VALUES (?)", [(f"P{i}/USDT",) for i in range(rows)])
    conn.commit()
    return conn


@pytest.fixture
def fleet(tmp_path):
    vols = tmp_path / "volumes"
    data = {v: vols / f"{PROJECT}_{v}" / "_data" for v in
            ("ft_user_data", "killers_receiver_state", "insiders_receiver_state")}
    open_conns = [
        _wal_db(data["ft_user_data"] / "tradesv3.live.KillersScalpV1.hyperliquid.sqlite", 5),
        _wal_db(data["ft_user_data"] / "tradesv3.dryrun.OITrendPullbackV1.sqlite", 3),
        _wal_db(data["killers_receiver_state"] / "receiver-hyperliquid.sqlite", 7),
        _wal_db(data["insiders_receiver_state"] / "receiver-hyperliquid.sqlite", 2),
    ]
    # Not databases the run should pick up.
    (data["ft_user_data"] / "logs").mkdir()
    (data["ft_user_data"] / "fear_greed_history.json").write_text("{}")
    (data["killers_receiver_state"] / "receiver-hyperliquid.sqlite.before-migration-x").write_text("old")
    observer = tmp_path / "killers-bot" / "state.sqlite"
    open_conns.append(_wal_db(observer, 4))
    yield {"vols": vols, "data": data, "observer": observer, "dest": tmp_path / "backups",
           "conns": open_conns}
    for c in open_conns:
        c.close()


def _args(f, *extra):
    return ["--dest", str(f["dest"]), "--volumes-root", str(f["vols"]), "--project", PROJECT,
            "--observer-db", str(f["observer"]), "--no-upload", "--no-alert", *extra]


def _restore(gz: Path, tmp: Path) -> sqlite3.Connection:
    out = tmp / (gz.name + ".restored")
    out.write_bytes(gzip.decompress(gz.read_bytes()))
    return sqlite3.connect(out)


def test_backs_up_every_volume_consistently_while_writers_are_open(bk, fleet, tmp_path):
    assert bk.main(_args(fleet)) == 0
    runs = [p for p in fleet["dest"].iterdir() if p.is_dir()]
    assert len(runs) == 1
    run = runs[0]
    manifest = json.loads((run / "MANIFEST.json").read_text())
    names = sorted(e["name"] for e in manifest["files"])
    assert names == [
        "ft_user_data/tradesv3.live.KillersScalpV1.hyperliquid.sqlite",
        "insiders_receiver_state/receiver-hyperliquid.sqlite",
        "killers_bot/state.sqlite",
        "killers_receiver_state/receiver-hyperliquid.sqlite",
    ]
    expected_rows = {"ft_user_data/tradesv3.live.KillersScalpV1.hyperliquid.sqlite": 5,
                     "killers_receiver_state/receiver-hyperliquid.sqlite": 7,
                     "killers_bot/state.sqlite": 4}
    for entry in manifest["files"]:
        if not entry["name"].endswith(".sqlite"):
            continue
        gz = run / Path(entry["name"]).parent / entry["stored_as"]
        raw = gzip.decompress(gz.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        conn = _restore(gz, tmp_path)
        # Rows that were only in the WAL made it, and the copy stands alone.
        if entry["name"] in expected_rows:
            assert conn.execute("SELECT count(*) FROM trades").fetchone()[0] == expected_rows[entry["name"]]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert entry["integrity_check"] == "ok"
        conn.close()


def test_writers_keep_working_and_sources_are_untouched(bk, fleet):
    src = fleet["data"]["killers_receiver_state"] / "receiver-hyperliquid.sqlite"
    before = src.read_bytes()
    assert bk.main(_args(fleet)) == 0
    assert src.read_bytes() == before  # read-only: no checkpoint into the main file
    writer = fleet["conns"][2]
    writer.execute("INSERT INTO trades (pair) VALUES ('AFTER/USDT')")
    writer.commit()
    assert writer.execute("SELECT count(*) FROM trades").fetchone()[0] == 8


def test_missing_required_volume_fails_and_leaves_no_partial_run(bk, fleet):
    for p in fleet["data"]["insiders_receiver_state"].glob("*.sqlite*"):
        p.unlink()
    assert bk.main(_args(fleet)) == 1
    assert [p for p in fleet["dest"].iterdir() if p.is_dir()] == []


def test_corrupt_database_fails_the_run(bk, fleet):
    conn = fleet["conns"][3]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    db = fleet["data"]["insiders_receiver_state"] / "receiver-hyperliquid.sqlite"
    raw = bytearray(db.read_bytes())
    raw[4096:8192] = b"\xff" * 4096  # trash the table's page
    db.write_bytes(bytes(raw))
    assert bk.main(_args(fleet)) == 1
    assert [p for p in fleet["dest"].iterdir() if p.is_dir()] == []


def test_failure_alerts_trade_webhook_with_only_the_notify_token(bk, fleet, tmp_path, monkeypatch):
    env_file = tmp_path / "ops-bot.env"
    env_file.write_text("OPS_BOT_TOKEN=telegram-secret\nTRADE_WEBHOOK_NOTIFY_TOKEN=abc123def456\n")
    monkeypatch.setattr(bk, "OPS_ENV_FILE", env_file)
    sent = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(bk.urllib.request, "urlopen", lambda req, timeout: sent.append(req) or Resp())
    for p in fleet["data"]["killers_receiver_state"].glob("*.sqlite*"):
        p.unlink()
    args = [a for a in _args(fleet) if a != "--no-alert"]
    assert bk.main(args) == 1
    assert len(sent) == 1
    req = sent[0]
    assert req.full_url == "http://127.0.0.1:8088/freqtrade/event"
    assert req.get_header("X-notify-token") == "abc123def456"
    body = json.loads(req.data)
    assert body["type"] == "warning" and body["bot_name"] == "db-backup"
    assert "killers_receiver_state" in body["status"]
    assert b"telegram-secret" not in req.data


def test_list_prints_the_plan_and_writes_nothing(bk, fleet, capsys):
    assert bk.main(_args(fleet, "--list")) == 0
    out = capsys.readouterr().out
    assert "killers_receiver_state/receiver-hyperliquid.sqlite" in out
    assert "killers_bot/state.sqlite" in out
    assert "tradesv3.live.KillersScalpV1.hyperliquid.sqlite" in out
    assert "tradesv3.dryrun" not in out
    assert "before-migration" not in out and "fear_greed" not in out
    assert not fleet["dest"].exists()


def test_a_held_lock_skips_the_run(bk, fleet):
    import fcntl
    fleet["dest"].mkdir(parents=True)
    with open(fleet["dest"] / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert bk.main(_args(fleet)) == 0
    assert [p for p in fleet["dest"].iterdir() if p.is_dir()] == []


def _stamp(when):
    return when.strftime("%Y%m%dT%H%M%SZ")


def test_retention_keeps_30_days_then_one_per_week_for_eight(bk):
    now = dt.datetime(2026, 10, 3, 3, 30, tzinfo=dt.timezone.utc)
    daily = [_stamp(now - dt.timedelta(days=d)) for d in range(0, 90)]
    doomed = set(bk.runs_to_prune(daily + ["not-a-run"], now))
    kept = [s for s in daily if s not in doomed]
    assert "not-a-run" not in doomed
    assert all(_stamp(now - dt.timedelta(days=d)) in kept for d in range(31))
    assert len(kept) > 31  # weekly tier adds older restore points
    # Past the daily tier, retain only the newest run per ISO week through week 8.
    older = [dt.datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
             for s in kept if s not in {_stamp(now - dt.timedelta(days=d)) for d in range(31)}]
    weeks = [when.isocalendar()[:2] for when in older]
    assert len(weeks) == len(set(weeks))
    assert all(now - when <= dt.timedelta(weeks=8) for when in older)
    assert older
    assert _stamp(now - dt.timedelta(days=60)) in doomed


def test_retention_never_drops_below_the_floor(bk):
    now = dt.datetime(2026, 10, 3, tzinfo=dt.timezone.utc)
    ancient = [_stamp(now - dt.timedelta(days=200 + d)) for d in range(10)]
    doomed = bk.runs_to_prune(ancient, now)
    assert len(ancient) - len(doomed) == 7


def test_rclone_override_and_default_discovery(bk, tmp_path, monkeypatch):
    explicit = tmp_path / "custom-rclone"
    assert bk.resolve_rclone(explicit) == explicit
    monkeypatch.setattr(bk.shutil, "which", lambda name: "/usr/local/bin/rclone")
    assert bk.resolve_rclone(None) == Path("/usr/local/bin/rclone")


def test_drive_upload_is_verified_before_timestamped_remote_pruning(bk, tmp_path):
    run = tmp_path / "20261003T033000Z"
    run.mkdir()
    config = tmp_path / "rclone.conf"
    config.write_text("[operator-drive]\ntype = drive\n")
    binary = tmp_path / "rclone"
    binary.write_text("")
    calls = []

    class Result:
        stdout = json.dumps([
            {"Name": "20261003T033000Z", "IsDir": True},
            {"Name": "20261002T033000Z", "IsDir": True},
            {"Name": "20261001T033000Z", "IsDir": True},
            {"Name": "20260930T033000Z", "IsDir": True},
            {"Name": "20260929T033000Z", "IsDir": True},
            {"Name": "20260928T033000Z", "IsDir": True},
            {"Name": "20260927T033000Z", "IsDir": True},
            {"Name": "20260825T033000Z", "IsDir": True},
            {"Name": "20260801T033000Z", "IsDir": True},
            {"Name": "README", "IsDir": True},
        ])

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result()

    now = dt.datetime(2026, 10, 3, 3, 30, tzinfo=dt.timezone.utc)
    pruned = bk.upload_and_prune(run, "operator-drive:Master-Trader/backups", config,
                                 binary, now, runner=runner)
    assert pruned == ["20260801T033000Z"]
    assert [call[0][1] for call in calls] == ["copy", "check", "lsjson", "purge"]
    assert calls[0][0][-2:] == ["--checksum", "--immutable"]
    assert calls[1][0][-2:] == ["--one-way", "--download"]
    assert calls[-1][0][2].endswith("/20260801T033000Z")


def test_drive_listing_failure_never_prunes(bk, tmp_path):
    run = tmp_path / "20261003T033000Z"
    run.mkdir()
    config = tmp_path / "rclone.conf"
    config.write_text("configured")
    binary = tmp_path / "rclone"
    binary.write_text("")
    commands = []

    class Result:
        stdout = "not json"

    def runner(argv, **kwargs):
        commands.append(argv[1])
        return Result()

    now = dt.datetime(2026, 10, 3, tzinfo=dt.timezone.utc)
    with pytest.raises(bk.BackupError, match="invalid rclone directory listing"):
        bk.upload_and_prune(run, "operator-drive:backups", config, binary, now, runner=runner)
    assert commands == ["copy", "check", "lsjson"]


def test_upload_failure_keeps_local_snapshot_and_skips_local_retention(bk, fleet, monkeypatch):
    old = fleet["dest"] / "20000101T000000Z"
    old.mkdir(parents=True)

    def fail_upload(*args, **kwargs):
        raise RuntimeError("Drive unavailable")

    monkeypatch.setattr(bk, "upload_and_prune", fail_upload)
    args = [arg for arg in _args(fleet) if arg != "--no-upload"]
    assert bk.main(args) == 1
    runs = sorted(p.name for p in fleet["dest"].iterdir() if p.is_dir())
    assert "20000101T000000Z" in runs
    assert len(runs) == 2


def test_prune_clears_staging_from_a_killed_run(bk, tmp_path):
    (tmp_path / ".partial-20261001T000000Z" / "x").mkdir(parents=True)
    bk.prune(tmp_path, dt.datetime(2026, 10, 3, tzinfo=dt.timezone.utc))
    assert not (tmp_path / ".partial-20261001T000000Z").exists()


def test_script_is_stdlib_only():
    """It runs from the Dokploy checkout with the host's /usr/bin/python3."""
    import ast
    import sys
    tree = ast.parse(SCRIPT.read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}
