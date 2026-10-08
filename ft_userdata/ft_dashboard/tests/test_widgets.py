"""trader.bots widget: builder, bearer check, routes. Synthetic fixture only."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import widgets

STATE = json.loads((Path(__file__).parent / "fixtures" / "widgets" / "api_state.json").read_text())
TOKEN = "synthetic-widgets-token-0123456789abcdef"


def state():
    return {"last_poll": STATE["last_poll"], "bots": STATE["bots"], "status": STATE["status"]}


def test_stat_is_the_live_24h_pnl():
    stat = widgets.build_bots(state())["stat"]
    assert stat == {"value": "+$0.75", "label": "24 h P&L · live", "delta": "3 trades closed", "tone": "good"}


def test_rows_live_first_with_status_tone():
    items = widgets.build_bots(state())["list"]["groups"][0]["items"]
    assert [i["key"] for i in items] == ["bot:alpha", "bot:beta", "bot:gamma"]
    alpha, beta, gamma = items
    assert alpha == {"key": "bot:alpha", "title": "alpha-bot",
                     "subtitle": "live · 24 h +$1.25 · 1 open", "detail": "wallet $101.25"}
    assert beta["tone"] == "warn" and beta["subtitle"] == "live · 24 h −$0.50 · 0 open"
    assert gamma["tone"] == "bad" and gamma["subtitle"].startswith("unreachable · dry-run")
    assert all("actions" not in i for i in items)


def test_spark_sums_live_realized_equity_once_every_bot_has_started():
    spark = widgets.build_bots(state())["spark"]
    assert spark == {"label": "Live equity (realized)", "points": [150.0, 151.0, 150.5, 150.75], "unit": "USD"}


def test_alert_follows_fleet_status():
    data = widgets.build_bots(state())
    assert data["alert"] == {"text": "1 bot(s) stale: gamma", "tone": "warn"}
    assert data["tone"] == "warn"
    green = state() | {"status": {"level": "green", "summary": "all 2 bots reachable"}}
    assert "alert" not in widgets.build_bots(green)
    red = state() | {"status": {"level": "red", "summary": "live bot unreachable: alpha"}}
    assert widgets.build_bots(red)["alert"]["tone"] == "bad"


def test_as_of_is_the_last_poll_in_utc():
    assert widgets.build_bots(state())["as_of"] == "2026-09-21T14:13:20+00:00"


def test_short_history_has_no_spark():
    s = state()
    s["bots"] = {"alpha": STATE["bots"]["alpha"] | {"equity_realized": [[1000, 100.0]]}}
    assert "spark" not in widgets.build_bots(s)


def test_a_live_bot_without_equity_means_no_spark():
    s = state()
    s["bots"] = s["bots"] | {"beta": STATE["bots"]["beta"] | {"equity_realized": []}}
    assert "spark" not in widgets.build_bots(s)   # never alpha alone passed off as the fleet


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WIDGETS_TOKEN", TOKEN)
    current = {"value": state()}
    app = FastAPI()
    widgets.install(app, lambda: current["value"])
    return TestClient(app), current


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_bearer_required(client):
    c, _ = client
    assert c.get("/widgets").status_code == 401
    assert c.get("/widgets", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/widgets", headers={"Authorization": TOKEN}).status_code == 401
    assert c.get("/widgets", headers=AUTH).json()["app"] == "trader"


def test_unset_token_fails_closed(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("WIDGETS_TOKEN", "")
    assert c.get("/widgets", headers=AUTH).status_code == 503
    monkeypatch.setenv("WIDGETS_TOKEN", "short")
    assert c.get("/widgets", headers={"Authorization": "Bearer short"}).status_code == 503


def test_routes(client):
    c, _ = client
    assert c.get("/widgets/bots", headers=AUTH).json()["id"] == "bots"
    assert c.get("/widgets/other", headers=AUTH).status_code == 404
    r = c.post("/widgets/bots/actions/close", headers=AUTH, json={"key": "bot:alpha", "request_id": "x"})
    assert r.status_code == 404 and r.json()["ok"] is False
    assert c.post("/widgets/bots/actions/close", json={}).status_code == 401


def test_no_poll_yet_is_503(client):
    c, current = client
    current["value"] = {"last_poll": None, "bots": {}, "status": {"level": "yellow", "summary": "starting"}}
    assert c.get("/widgets/bots", headers=AUTH).status_code == 503


def test_app_installs_widgets_without_touching_other_routes():
    import app as dashboard
    paths = {r.path for r in dashboard.app.routes}
    assert {"/widgets", "/widgets/{widget_id}", "/widgets/{widget_id}/actions/{action_id}"} <= paths
    assert "/api/state" in paths and "/healthz" in paths


# ── metrics view: the dashboard header (`get hero()` in static/dashboard.js) ──────────

def _bot(**over):
    return {"dry_run": False, "wallet": {}, "pnl": {}, "stats": {}, "delta_24h": {}, "open_trades": []} | over


def _metrics(bots, **extra):
    return widgets.build_metrics({"bots": bots} | extra)["rows"]


# Synthetic fleet. Expected numbers computed by hand from `get hero()` in dashboard.js:
#   live = alpha, beta, gamma (dry_run === false); `paper` is excluded from every row.
#   accounts: acct-a is shared by alpha (bot_owned 200) and beta (bot_owned 120), counted
#     once as max = 200; gamma has no account_group, so its key is the group, and its
#     bot_owned is None, so it falls back to starting_capital 80.
#     equity with no account_health = 200 + 80 = 280.00 (the paper bot's 999 is not counted).
#   realized   = 12.50 + (−4.00) + 0.25                      = +8.75
#   unrealized = 3.25 + (beta's unrealized is None, so −1.00 − (−4.00) = 3.00) + (−0.75) = +5.50
#   closed     = 10 + 5 + 2                                   = 17
#   open       = alpha 2 trades − 1 pending with amount 0 (not a position) = 1
#              + beta 2 trades (a pending entry with amount 0.5 is a position) = 2
#              + gamma 0                                      = 3
#   24 h       = 1.50 + (−0.40) + 0.10                        = +1.20
HERO_BOTS = {
    "alpha": _bot(account_group="acct-a", wallet={"bot_owned": 200.0, "starting_capital": 150.0},
                  pnl={"closed": 12.5, "unrealized": 3.25, "all_coin": 15.75},
                  stats={"closed_trade_count": 10}, delta_24h={"pnl_usd": 1.5},
                  open_trades=[{"pair": "AAA/USDT", "amount": 1.0, "entry": {"state": "filled"}},
                               {"pair": "BBB/USDT", "amount": 0, "entry": {"state": "pending"}}]),
    "beta": _bot(account_group="acct-a", wallet={"bot_owned": 120.0},
                 pnl={"closed": -4.0, "unrealized": None, "all_coin": -1.0},
                 stats={"closed_trade_count": 5}, delta_24h={"pnl_usd": -0.4},
                 open_trades=[{"pair": "CCC/USDT", "amount": 0.5, "entry": {"state": "pending"}},
                              {"pair": "DDD/USDT"}]),
    "gamma": _bot(wallet={"bot_owned": None, "starting_capital": 80.0},
                  pnl={"closed": 0.25, "unrealized": -0.75, "all_coin": -0.5},
                  stats={"closed_trade_count": 2}, delta_24h={"pnl_usd": 0.1}),
    "paper": _bot(dry_run=True, account_group="acct-p", wallet={"bot_owned": 999.0},
                  pnl={"closed": 500.0, "unrealized": 500.0, "all_coin": 1000.0},
                  stats={"closed_trade_count": 99}, delta_24h={"pnl_usd": 77.0},
                  open_trades=[{"pair": "EEE/USDT", "amount": 2.0}]),
}
HERO_BOTS = {name: bot | {"key": name} for name, bot in HERO_BOTS.items()}   # as in /api/state


def test_metrics_match_the_hand_computed_dashboard_header():
    assert _metrics(HERO_BOTS) == [
        {"label": "Account equity", "value": "$280.00", "detail": "shared accounts counted once", "tone": "neutral"},
        {"label": "Realized P&L", "value": "+$8.75", "detail": "17 closed trades · live epochs", "tone": "good"},
        {"label": "Unrealized P&L", "value": "+$5.50", "detail": "3 open positions", "tone": "good"},
        {"label": "24 h P&L", "value": "+$1.20", "detail": "live bots · rolling 24 h", "tone": "good"},
    ]


def test_equity_complete_uses_the_observed_account_health():
    row = _metrics(HERO_BOTS, account_health={"complete": True, "equity": 1234.56})[0]
    assert row == {"label": "Account equity", "value": "$1,234.56",
                   "detail": "shared accounts counted once", "tone": "neutral"}


@pytest.mark.parametrize("health", [
    {"complete": False, "equity": 1234.56, "accounts": {}, "warnings": ["stale"]},
    {"complete": False},
    {},
    {"complete": True, "equity": None},
])
def test_equity_incomplete_is_a_dash_never_the_wallet_sum(health):
    row = _metrics(HERO_BOTS, account_health=health)[0]
    assert row == {"label": "Account equity", "value": "—", "detail": "valuation incomplete", "tone": "warn"}


def test_equity_absent_sums_the_max_wallet_per_account_group():
    for state in ({}, {"account_health": None}):
        assert _metrics(HERO_BOTS, **state)[0]["value"] == "$280.00"
    # two bots on one account count the larger wallet once; a third account adds its own
    bots = {"a": _bot(account_group="g", wallet={"bot_owned": 10.0}),
            "b": _bot(account_group="g", wallet={"bot_owned": 30.0}),
            "c": _bot(wallet={"starting_capital": 5.0})}
    assert _metrics(bots)[0]["value"] == "$35.00"


def test_a_zero_wallet_is_not_replaced_by_the_starting_capital():
    bots = {"a": _bot(wallet={"bot_owned": 0.0, "starting_capital": 50.0})}   # JS `??` keeps 0
    assert _metrics(bots)[0]["value"] == "$0.00"


def test_unrealized_falls_back_to_all_coin_minus_closed_only_when_none():
    one = lambda pnl: _metrics({"a": _bot(pnl=pnl)})[2]
    assert one({"closed": 2.5, "all_coin": 7.0})["value"] == "+$4.50"
    assert one({"closed": 2.5, "all_coin": 7.0, "unrealized": None})["value"] == "+$4.50"
    assert one({"closed": 2.0})["value"] == "−$2.00"            # a missing all_coin counts as 0
    assert one({})["value"] == "$0.00"
    assert one({"closed": 2.0, "all_coin": 9.0, "unrealized": 0})["value"] == "$0.00"   # 0 is a value


def test_pending_entry_is_not_an_open_position():
    pending = {"pair": "AAA/USDT", "amount": 0, "entry": {"state": "pending"}}
    filled = {"pair": "BBB/USDT", "amount": 2.0, "entry": {"state": "filled"}}
    partial = {"pair": "CCC/USDT", "amount": 0.4, "entry": {"state": "pending"}}
    no_amount = {"pair": "DDD/USDT", "entry": {"state": "pending"}}       # Number(undefined) is NaN
    row = lambda trades: _metrics({"a": _bot(open_trades=trades)})[2]["detail"]
    assert row([pending, no_amount]) == "0 open positions"
    assert row([pending, filled, partial]) == "2 open positions"


def test_singular_open_position_and_closed_trade():
    bots = {"a": _bot(open_trades=[{"pair": "AAA/USDT", "amount": 1.0}], stats={"closed_trade_count": 1})}
    rows = _metrics(bots)
    assert rows[2]["detail"] == "1 open position"
    assert rows[1]["detail"] == "1 closed trade · live epochs"


def test_dry_run_bots_are_excluded_from_every_row():
    paper = {k: v for k, v in HERO_BOTS.items() if k == "paper"}
    assert _metrics(paper) == [
        {"label": "Account equity", "value": "$0.00", "detail": "shared accounts counted once", "tone": "neutral"},
        {"label": "Realized P&L", "value": "$0.00", "detail": "0 closed trades · live epochs", "tone": "neutral"},
        {"label": "Unrealized P&L", "value": "$0.00", "detail": "0 open positions", "tone": "neutral"},
        {"label": "24 h P&L", "value": "$0.00", "detail": "live bots · rolling 24 h", "tone": "neutral"},
    ]
    # `dry_run === false` only: a missing or null flag is not live
    odd = {"a": _bot(dry_run=None, wallet={"bot_owned": 9.0}), "b": {"wallet": {"bot_owned": 9.0}}}
    assert _metrics(odd)[0]["value"] == "$0.00"


def test_signs_and_tones_follow_the_value():
    def tones(realized, unrealized, day):
        bots = {"a": _bot(pnl={"closed": realized, "unrealized": unrealized}, delta_24h={"pnl_usd": day})}
        return [(r["value"], r["tone"]) for r in _metrics(bots)[1:]]
    assert tones(4.0, -2.5, 0.0) == [("+$4.00", "good"), ("−$2.50", "bad"), ("$0.00", "neutral")]
    assert tones(-1234.5, 0.0, -0.01) == [("−$1,234.50", "bad"), ("$0.00", "neutral"), ("−$0.01", "bad")]
    # float drift in a sum is not a signed zero
    assert tones(0.1 + 0.2 - 0.3, 0.0, 0.0)[0] == ("$0.00", "neutral")


def test_metrics_view_is_listed_and_served():
    assert widgets.CATALOG["widgets"][0]["views"] == ["stat", "list", "spark", "alert", "metrics"]
    data = widgets.build_bots(state())
    assert data["metrics"] == widgets.build_metrics(state())
    assert 1 <= len(data["metrics"]["rows"]) <= 8


def test_the_route_passes_account_health_through(client):
    c, current = client
    current["value"] = state() | {"account_health": {"complete": True, "equity": 1234.56}}
    assert c.get("/widgets/bots", headers=AUTH).json()["metrics"]["rows"][0]["value"] == "$1,234.56"


def test_app_feeds_the_widget_the_dashboard_account_health(monkeypatch):
    import app as dashboard
    monkeypatch.setenv("WIDGETS_TOKEN", TOKEN)
    monkeypatch.setitem(dashboard._cache, "last_poll_finished_at", STATE["last_poll"])
    monkeypatch.setitem(dashboard._cache, "bots", STATE["bots"])
    monkeypatch.setattr(dashboard, "_account_health", lambda: {"complete": True, "equity": 1234.56})
    body = TestClient(dashboard.app).get("/widgets/bots", headers=AUTH).json()
    assert body["metrics"]["rows"][0]["value"] == "$1,234.56"
