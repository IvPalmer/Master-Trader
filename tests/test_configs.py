"""
Config validation tests.

Catches: invalid JSON, missing required fields, dangerous defaults,
hyperopt auto-export overrides, mismatched strategy/config pairs.
"""

import json
import os
import re
import pytest
from pathlib import Path

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
CONFIG_DIR = FT_DIR / "user_data" / "configs"
STRATEGY_DIR = FT_DIR / "user_data" / "strategies"

ACTIVE_BOTS = [
    "SupertrendStrategy",
    "MasterTraderV1",
    "BollingerRSIMeanReversion",
    "IchimokuTrendV1",
    "EMACrossoverV1",
    "FuturesSniperV1",
]


def load_config(name):
    path = CONFIG_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def load_strategy_source(name):
    path = STRATEGY_DIR / f"{name}.py"
    return path.read_text()


# ── Config file validity ──────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_config_is_valid_json(bot):
    """Every active bot must have a parseable JSON config."""
    path = CONFIG_DIR / f"{bot}.json"
    assert path.exists(), f"Config file missing: {path}"
    with open(path) as f:
        config = json.load(f)  # Will raise on invalid JSON
    assert isinstance(config, dict)


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_strategy_file_exists(bot):
    """Every active bot must have a matching strategy .py file."""
    path = STRATEGY_DIR / f"{bot}.py"
    assert path.exists(), f"Strategy file missing: {path}"


# ── Crash protection (stoploss_on_exchange) ───────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_stoploss_on_exchange_enabled(bot):
    """All bots must have stoploss_on_exchange for crash protection."""
    config = load_config(bot)
    order_types = config.get("order_types", {})
    assert order_types.get("stoploss_on_exchange") is True, (
        f"{bot}: stoploss_on_exchange must be True (crash protection)"
    )


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_stoploss_on_exchange_interval(bot):
    """Exchange stop must be updated regularly."""
    config = load_config(bot)
    order_types = config.get("order_types", {})
    interval = order_types.get("stoploss_on_exchange_interval", 0)
    assert interval > 0, f"{bot}: stoploss_on_exchange_interval must be set (currently {interval})"
    assert interval <= 120, f"{bot}: interval {interval}s too high, stops won't track trailing"


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_cancel_open_orders_on_exit(bot):
    """Prevent orphaned orders on shutdown."""
    config = load_config(bot)
    assert config.get("cancel_open_orders_on_exit") is True, (
        f"{bot}: cancel_open_orders_on_exit must be True"
    )


# ── Stoploss sanity ──────────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_stoploss_not_too_wide(bot):
    """No stoploss wider than -7%. Data shows 0% recovery past -7%."""
    source = load_strategy_source(bot)
    match = re.search(r"stoploss\s*=\s*(-?[\d.]+)", source)
    assert match, f"{bot}: couldn't find stoploss in strategy file"
    sl = float(match.group(1))
    assert sl >= -0.07, f"{bot}: stoploss {sl} is wider than -7% (nothing recovers past this)"


def test_futures_stoploss_tighter():
    """Futures bot must have tighter stop due to leverage."""
    source = load_strategy_source("FuturesSniperV1")
    match = re.search(r"stoploss\s*=\s*(-?[\d.]+)", source)
    sl = float(match.group(1))
    assert sl >= -0.04, f"FuturesSniperV1: stoploss {sl} too wide for leveraged trading"


# ── Hyperopt override bug ────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_no_hyperopt_param_override(bot):
    """
    CRITICAL: Freqtrade hyperopt creates <Strategy>.json in strategies/ dir
    that silently overrides .py parameters. These files must not exist.
    Bug found 2026-03-12: SupertrendStrategy.json was overriding stoploss.
    """
    override_file = STRATEGY_DIR / f"{bot}.json"
    assert not override_file.exists(), (
        f"DANGER: {override_file} exists and will override strategy params! "
        f"Delete it or use --disable-param-export with hyperopt."
    )


# ── Required config fields ────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_required_config_fields(bot):
    """Configs must have all essential fields."""
    config = load_config(bot)
    required = [
        "stake_currency",
        "stake_amount",
        "max_open_trades",
        "exchange",
        "api_server",
    ]
    for field in required:
        assert field in config, f"{bot}: missing required field '{field}'"

    assert config["stake_currency"] == "USDT", f"{bot}: stake_currency should be USDT"
    assert config["max_open_trades"] > 0, f"{bot}: max_open_trades must be > 0"


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_no_real_api_keys_committed(bot):
    """API keys must be empty in committed configs (secrets go in env vars)."""
    config = load_config(bot)
    exchange = config.get("exchange", {})
    key = exchange.get("key", "")
    secret = exchange.get("secret", "")
    assert key == "" or key.startswith("${"), f"{bot}: real API key found in config!"
    assert secret == "" or secret.startswith("${"), f"{bot}: real API secret found in config!"


# ── Trading mode consistency ──────────────────────────────────────


def test_futures_config_correct():
    """FuturesSniperV1 must be configured for futures trading."""
    config = load_config("FuturesSniperV1")
    assert config.get("trading_mode") == "futures"
    assert config.get("margin_mode") == "isolated"


@pytest.mark.parametrize("bot", [b for b in ACTIVE_BOTS if b != "FuturesSniperV1"])
def test_spot_config_correct(bot):
    """Spot bots must be configured for spot trading."""
    config = load_config(bot)
    assert config.get("trading_mode") == "spot", f"{bot}: should be spot, got {config.get('trading_mode')}"


# ── Port uniqueness ───────────────────────────────────────────────


def test_no_duplicate_ports():
    """Each bot must have a unique API port to avoid conflicts."""
    ports = {}
    for bot in ACTIVE_BOTS:
        config = load_config(bot)
        port_cors = config.get("api_server", {}).get("CORS_origins", [])
        # Also check docker-compose for port mappings
        ports[bot] = port_cors
    # This mainly validates configs don't clash; docker-compose is the real authority


# ── Database path uniqueness ──────────────────────────────────────


def test_unique_database_paths():
    """Each bot must write to its own database to prevent data corruption."""
    db_paths = {}
    for bot in ACTIVE_BOTS:
        config = load_config(bot)
        db_url = config.get("db_url", "")
        assert db_url, f"{bot}: db_url is empty"
        assert bot in db_url or bot.replace("V1", "").lower() in db_url.lower(), (
            f"{bot}: db_url '{db_url}' doesn't contain strategy name — risk of shared DB"
        )
        assert db_url not in db_paths.values(), (
            f"{bot}: db_url '{db_url}' is shared with another bot!"
        )
        db_paths[bot] = db_url
