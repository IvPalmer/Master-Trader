"""Production dashboard registry and account-group regression tests."""

from app import BOTS, _bot_links


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
        "insiders-ft",
    }
    assert "cascade" not in bots


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
    assert bots["insiders-ft"]["account_group"] != "binance-spot"
    assert bots["short-keltner-hl"]["account_group"] != "binance-spot"


def test_strategy_kinds_distinguish_copiers_from_autonomous_bots():
    bots = _by_key()
    assert bots["killers-ft"]["strategy_kind"] == "copy-trader"
    assert bots["insiders-ft"]["strategy_kind"] == "copy-trader"
    assert bots["short-keltner-hl"]["strategy_kind"] == "autonomous-quant"
    assert bots["oi-trend"]["strategy_kind"] == "autonomous-quant"
