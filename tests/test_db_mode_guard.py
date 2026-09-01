import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "ft_userdata/user_data/configs/guard_db_mode.py"
SPEC = importlib.util.spec_from_file_location("guard_db_mode", GUARD_PATH)
guard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(guard)


def _config(tmp_path, *, dry_run, db_url):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"dry_run": dry_run, "db_url": db_url}))
    return path


def _database(path, *, order_id="exchange-order", is_open=1):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE trades (id INTEGER PRIMARY KEY, pair TEXT, is_open INTEGER);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, ft_trade_id INTEGER, order_id TEXT);
        """
    )
    connection.execute("INSERT INTO trades VALUES (2, 'TRX/USDT', ?)", (is_open,))
    connection.execute("INSERT INTO orders VALUES (3, 2, ?)", (order_id,))
    connection.commit()
    connection.close()


def test_live_database_rejects_open_dry_run_record(tmp_path, monkeypatch):
    database = tmp_path / "tradesv3.live.FundingFadeV1.sqlite"
    _database(database, order_id="dry_run_buy_TRX/USDT_deadbeef")
    config = _config(tmp_path, dry_run=False, db_url=f"sqlite:///{database}")
    monkeypatch.delenv("FREQTRADE__DRY_RUN", raising=False)
    monkeypatch.delenv("FREQTRADE__DB_URL", raising=False)

    with pytest.raises(guard.GuardError, match="open dry-run trade records"):
        guard.validate(config)


def test_live_database_accepts_exchange_order(tmp_path, monkeypatch):
    database = tmp_path / "tradesv3.live.FundingFadeV1.sqlite"
    _database(database, order_id="123456789")
    config = _config(tmp_path, dry_run=False, db_url=f"sqlite:///{database}")
    monkeypatch.delenv("FREQTRADE__DRY_RUN", raising=False)
    monkeypatch.delenv("FREQTRADE__DB_URL", raising=False)

    result = guard.validate(config)

    assert result["dry_run"] is False
    assert result["phantom_trades"] == []


def test_mode_and_database_name_must_agree(tmp_path, monkeypatch):
    config = _config(
        tmp_path,
        dry_run=True,
        db_url="sqlite:////tmp/tradesv3.live.FundingFadeV1.sqlite",
    )
    monkeypatch.delenv("FREQTRADE__DRY_RUN", raising=False)
    monkeypatch.delenv("FREQTRADE__DB_URL", raising=False)

    with pytest.raises(guard.GuardError, match="dry-run process must use"):
        guard.validate(config)


def test_environment_overrides_are_the_effective_mode_and_database(tmp_path, monkeypatch):
    config = _config(
        tmp_path,
        dry_run=False,
        db_url="sqlite:////tmp/tradesv3.live.KillersScalpV1.sqlite",
    )
    monkeypatch.setenv("FREQTRADE__DRY_RUN", "true")
    monkeypatch.setenv(
        "FREQTRADE__DB_URL",
        "sqlite:////tmp/tradesv3.dryrun.KillersScalpV1.sqlite",
    )

    result = guard.validate(config)

    assert result["dry_run"] is True


def test_every_active_bot_entrypoint_runs_the_guard():
    compose = (ROOT / "ft_userdata/docker-compose.prod.yml").read_text()
    assert compose.count("guard_db_mode.py --config") == 6
