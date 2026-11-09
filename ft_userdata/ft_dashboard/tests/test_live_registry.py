"""Production dashboard registry and account-group regression tests."""

import json
from datetime import datetime
from pathlib import Path

import yaml

from app import BOTS, _bot_links

FT_USERDATA = Path(__file__).resolve().parents[2]


def _by_key():
    return {bot["key"]: bot for bot in BOTS}


def test_dashboard_tracks_every_current_live_executor():
    bots = _by_key()
    assert set(bots) == {
        "fundingfade",
        "keltner",
        "oi-trend",
        "short-keltner-hl",
        "killers-ft",
        "upbit-fade-hl",
    }
    assert "cascade" not in bots
    assert "insiders-ft" not in bots  # retired 2026-10-29 (#216)


def test_upbit_pilot_matches_its_account_and_prereg_epoch():
    bot = _by_key()["upbit-fade-hl"]
    config = json.loads((FT_USERDATA / "bots_config.json").read_text())
    entry = next(v for v in config["bots"].values() if v.get("service") == "ft-upbit-fade-hl")
    assert bot["account_group"] == entry["capital_account"]
    assert bot["wallet_env"] == entry["wallet_env"]

    registry = json.loads((FT_USERDATA / "preregistrations.json").read_text())
    prereg = next(p for p in registry["preregistrations"]
                  if p["id"] == "upbit-krw-fade-live-pilot-2026-11")
    epoch = datetime.fromisoformat(prereg["frozen"]["epoch_start"][:26] + "+00:00")
    assert bot["epoch_start_ts_ms"] == int(epoch.timestamp() * 1000)


def test_compose_gives_the_dashboard_every_wallet_it_reads():
    compose = yaml.safe_load((FT_USERDATA / "docker-compose.prod.yml").read_text())
    environment = compose["services"]["ft-dashboard"]["environment"]
    assert {bot["wallet_env"] for bot in BOTS if bot.get("wallet_env")} <= set(environment)


def test_short_keltner_points_to_fresh_live_epoch():
    bot = _by_key()["short-keltner-hl"]
    assert bot["url"] == "http://ft-short-keltner-hl-live:8080"
    assert bot["container"] == "ft-short-keltner-hl-live"
    assert bot["freqtrade_ui"] is None

    links = _bot_links(bot, [], [])
    assert links["freqtrade_ui"] is None
    assert links["logs_hint"] == "docker logs ft-short-keltner-hl-live --tail 50"


def test_shared_binance_wallet_has_one_account_group():
    bots = _by_key()
    for key in ("fundingfade", "keltner", "oi-trend"):
        assert bots[key]["account_group"] == "binance-spot"

    assert bots["killers-ft"]["account_group"] != "binance-spot"
    assert bots["short-keltner-hl"]["account_group"] != "binance-spot"


def test_strategy_kinds_distinguish_copiers_from_autonomous_bots():
    bots = _by_key()
    assert bots["killers-ft"]["strategy_kind"] == "copy-trader"
    assert bots["short-keltner-hl"]["strategy_kind"] == "autonomous-quant"
    assert bots["oi-trend"]["strategy_kind"] == "autonomous-quant"
