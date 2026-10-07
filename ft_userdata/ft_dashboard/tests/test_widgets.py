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
