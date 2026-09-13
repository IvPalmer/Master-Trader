import importlib.util
import json
import sqlite3
import subprocess
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


@pytest.mark.parametrize(
    "service",
    ["ft-killers-scalp", "ft-insiders-scalp", "ft-short-keltner-hl-live"],
)
@pytest.mark.parametrize("dry_run", ["true", "false"])
@pytest.mark.parametrize("guard_status", [0, 78])
def test_hyperliquid_entrypoint_stops_before_trading_when_guard_fails(
    tmp_path, service, dry_run, guard_status
):
    """Execute the deployed shell flow with harmless guard/trader substitutes.

    Merely containing a guard command does not make a multiline entrypoint
    fail closed: a failed guard used to fall through to sleep and Freqtrade.
    """
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((ROOT / "ft_userdata/docker-compose.prod.yml").read_text())
    entrypoint = compose["services"][service]["entrypoint"]
    assert entrypoint[:2] == ["/bin/sh", "-c"]
    # Compose converts doubled dollars before passing the script to /bin/sh.
    script = entrypoint[2].replace("$$", "$")
    trader = tmp_path / "freqtrade"
    trader.write_text(
        '#!/bin/sh\n'
        'printf "trader-started %s %s\\n" "$FREQTRADE__DB_URL" '
        '"${FREQTRADE__ORDER_TYPES__STOPLOSS_ON_EXCHANGE:-unchanged}"\n'
    )
    trader.chmod(0o700)
    substitutes = (
        'python() { printf "guard-called\\n"; return "$GUARD_STATUS"; }\n'
        'sleep() { printf "sleep-called\\n"; }\n'
    )
    result = subprocess.run(
        ["/bin/sh", "-c", substitutes + script],
        env={
            "PATH": str(tmp_path),
            "FREQTRADE__DRY_RUN": dry_run,
            "GUARD_STATUS": str(guard_status),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert "guard-called" in result.stdout
    assert result.returncode == guard_status, result.stderr
    if guard_status:
        assert "sleep-called" not in result.stdout
        assert "trader-started" not in result.stdout
    else:
        # Optional startup staggering must not affect the guard contract.
        assert "trader-started" in result.stdout
        marker = ".dryrun." if dry_run == "true" else ".live."
        assert marker in result.stdout
        expected_stop_mode = "false" if dry_run == "true" else "unchanged"
        assert result.stdout.rstrip().endswith(expected_stop_mode)
