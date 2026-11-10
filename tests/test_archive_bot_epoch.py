"""deploy/vps/archive_bot_epoch.py freezes an ended epoch into a record (#277).

The docker calls are replaced by a runner that answers from the same files:
the FT container's DB URL, Freqtrade's serialization of the temporary copy,
and the dashboard's build. Every trade and name here is synthetic.
"""

import ast
import importlib.util
import json
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

VPS = Path(__file__).resolve().parents[1] / "deploy" / "vps"
SCRIPT = VPS / "archive_bot_epoch.py"
DAY = 86_400_000
START = 1_790_000_000_000
END = START + 10 * DAY
RID = "synthetic-bot.live-r1"
SOURCE = "tradesv3.live.Synthetic.sqlite"


def _date(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _ms(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def ab(monkeypatch):
    monkeypatch.syspath_prepend(str(VPS))
    spec = importlib.util.spec_from_file_location("archive_bot_epoch_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def volume(tmp_path):
    data = tmp_path / "volumes" / "proj_ft_user_data" / "_data"
    data.mkdir(parents=True)
    conn = sqlite3.connect(data / SOURCE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, pair TEXT, open_date TEXT, "
                 "close_date TEXT, is_open INTEGER, close_profit_abs REAL)")
    rows = [(1, START + DAY, 3.0), (2, START + 2 * DAY, -1.25), (3, END + DAY, 7.0)]
    conn.executemany("INSERT INTO trades VALUES (?, 'SOL/USDC:USDC', ?, ?, 0, ?)",
                     [(i, _date(t), _date(t + 3_600_000), p) for i, t, p in rows])
    conn.commit()  # left open in WAL mode, as a bot holds it
    yield SimpleNamespace(root=tmp_path / "volumes", data=data, conn=conn)
    conn.close()


class Runner:
    """Stands in for `docker exec`, answering from the files the script prepared."""

    def __init__(self, data, running="tradesv3.dryrun.Synthetic.sqlite", tamper=None):
        self.data, self.running, self.tamper, self.calls = data, running, tamper, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[-1] == "/proc/1/environ":
            return SimpleNamespace(stdout=b"PATH=/usr/bin\0FREQTRADE__DB_URL=sqlite:////freqtrade/user_data/"
                                   + self.running.encode() + b"\0")
        if "-c" in cmd:
            conn = sqlite3.connect(self.data / Path(cmd[-1]).name)
            rows = conn.execute("SELECT id, pair, open_date, close_date, is_open, close_profit_abs FROM trades").fetchall()
            conn.close()
            trades = [{"trade_id": i, "pair": p, "open_timestamp": _ms(o),
                       "close_timestamp": _ms(c) if c else None, "is_open": bool(op), "profit_abs": pr}
                      for i, p, o, c, op, pr in rows]
            return SimpleNamespace(stdout="migration log line\n" + json.dumps(trades) + "\n")
        if cmd[-1] == "/app/build_epoch_record.py":
            spec = json.loads(kwargs["input"])
            trades = [t for t in spec["trades"] if spec["start_ms"] <= t["close_timestamp"] < spec["end_ms"]]
            trades = self.tamper(trades) if self.tamper else trades
            raw = sum(t["profit_abs"] for t in trades)
            return SimpleNamespace(stdout=json.dumps({
                "record_id": spec["record_id"], "source_sha256": spec["source_sha256"], "trades": trades,
                "totals": {"closed_trades": len(trades), "raw_profit_abs": raw, "corrected_profit_abs": raw - 0.5,
                           "reconciled_trades": 1, "fill_reconciliation": "ok"}}))
        raise AssertionError(f"unexpected command {cmd}")


def _argv(v, *, rid=RID, source=SOURCE):
    return ["--record-id", rid, "--bot-key", "synthetic-bot", "--source-db", source, "--mode", "live",
            "--start-ms", str(START), "--end-ms", str(END), "--starting-capital", "100",
            "--reason", "synthetic stop", "--issue", "999", "--ft-container", "ft-synthetic",
            "--volumes-root", str(v.root), "--project", "proj"]


def _records(v):
    return sorted(p.name for p in (v.data / "epoch-records").glob("*")) if (v.data / "epoch-records").exists() else []


def test_archives_the_window_once_read_only_and_never_overwrites(ab, volume, capsys):
    runner = Runner(volume.data)
    assert ab.main(_argv(volume), runner) == 0
    record_path = volume.data / "epoch-records" / f"{RID}.json"
    record = json.loads(record_path.read_text())
    assert [t["trade_id"] for t in record["trades"]] == [1, 2]  # trade 3 closed after the window
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o444
    assert "raw +1.75 · corrected +1.25" in capsys.readouterr().out
    backup = volume.data / f"archive-{RID}.sqlite"
    conn = sqlite3.connect(backup)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn.close()
    assert not list(volume.data.glob(".epoch-archive-*")), "the temporary copy is removed"
    before = record_path.read_bytes()
    assert ab.main(_argv(volume), runner) == 1
    assert "already exists" in capsys.readouterr().err
    assert record_path.read_bytes() == before


def test_refuses_while_the_bot_still_writes_the_source(ab, volume, capsys):
    runner = Runner(volume.data, running=SOURCE)
    assert ab.main(_argv(volume), runner) == 1
    assert "still ft-synthetic's DB" in capsys.readouterr().err
    assert len(runner.calls) == 1 and _records(volume) == []
    assert not list(volume.data.glob("archive-*"))


def test_refuses_when_the_running_db_cannot_be_read(ab, volume, capsys):
    def runner(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"No such container")
    assert ab.main(_argv(volume), runner) == 1
    assert "No such container" in capsys.readouterr().err
    assert _records(volume) == []


def test_refuses_an_epoch_with_an_open_trade(ab, volume, capsys):
    volume.conn.execute("INSERT INTO trades VALUES (4, 'SOL/USDC:USDC', ?, NULL, 1, NULL)", (_date(END - DAY),))
    volume.conn.commit()
    runner = Runner(volume.data)
    assert ab.main(_argv(volume), runner) == 1
    assert "1 open trade" in capsys.readouterr().err
    assert _records(volume) == [] and not any("-c" in c for c in runner.calls)


@pytest.mark.parametrize("tamper,message", [
    (lambda trades: trades[:1], "identities differ"),
    (lambda trades: [{**t, "profit_abs": t["profit_abs"] + 1} for t in trades], "does not match SQLite"),
])
def test_refuses_a_record_that_disagrees_with_sqlite(ab, volume, capsys, tamper, message):
    assert ab.main(_argv(volume), Runner(volume.data, tamper=tamper)) == 1
    assert message in capsys.readouterr().err
    assert _records(volume) == []


@pytest.mark.parametrize("overrides", [
    {"rid": "synthetic-bot"},  # a running bot's key shape: no epoch suffix
    {"source": "../tradesv3.live.Synthetic.sqlite"},
    {"source": "archive-missing.sqlite"},
])
def test_refuses_bad_names(ab, volume, overrides):
    runner = Runner(volume.data)
    assert ab.main(_argv(volume, **overrides), runner) == 1
    assert runner.calls == [] and _records(volume) == []


def test_links_planted_at_staging_names_never_redirect_a_write(ab, volume):
    """Codex #277 P1: a predictable staging path let a symlink truncate a live DB."""
    victim = volume.data / "tradesv3.live.Other.sqlite"
    conn = sqlite3.connect(victim)
    conn.execute("CREATE TABLE trades (id INTEGER)")
    conn.commit()
    conn.close()
    before = victim.read_bytes()
    for name in (f".epoch-archive-{RID}.sqlite", f".archive-{RID}.sqlite.partial", f".{RID}.json.tmp"):
        (volume.data / name).symlink_to(victim)
    runner = Runner(volume.data)
    assert ab.main(_argv(volume), runner) == 0
    assert victim.read_bytes() == before
    staged = Path([c for c in runner.calls if "-c" in c][0][-1]).name
    assert staged != f".epoch-archive-{RID}.sqlite" and not (volume.data / staged).exists()


def test_refuses_a_planted_backup_link(ab, volume, capsys):
    (volume.data / f"archive-{RID}.sqlite").symlink_to(volume.data / SOURCE)
    assert ab.main(_argv(volume), Runner(volume.data)) == 1
    assert "symlink" in capsys.readouterr().err
    assert _records(volume) == []


def test_one_archive_run_at_a_time(ab, volume, capsys):
    import fcntl, os
    held = os.open(volume.data, os.O_RDONLY)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        runner = Runner(volume.data)
        assert ab.main(_argv(volume), runner) == 1
        assert "another archive run" in capsys.readouterr().err
        assert runner.calls == [] and _records(volume) == []
    finally:
        os.close(held)


def test_script_is_stdlib_only():
    """It runs from the Dokploy checkout with the host's /usr/bin/python3."""
    tree = ast.parse(SCRIPT.read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= set(sys.stdlib_module_names) | {"__future__", "backup_live_dbs"}
