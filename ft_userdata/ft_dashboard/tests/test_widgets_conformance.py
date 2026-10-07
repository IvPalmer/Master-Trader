"""Every /widgets response passes the gateway's own validator, copied from
elder-brain services/session-gateway/widgets/contract.py. Never edit the copy."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import widgets
from tests import widget_contract as contract
from tests.test_widgets import STATE, TOKEN, state


def test_catalog_data_and_action_answer_pass(monkeypatch):
    monkeypatch.setenv("WIDGETS_TOKEN", TOKEN)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    variants = [state(),
                state() | {"status": {"level": "green", "summary": "ok"}},
                state() | {"bots": {"gamma": STATE["bots"]["gamma"]}}]   # paper only: no spark
    for current in variants:
        app = FastAPI()
        widgets.install(app, lambda current=current: current)
        c = TestClient(app)
        entry = contract.check_catalog(c.get("/widgets", headers=auth).json(), "trader")["widgets"][0]
        r = c.get("/widgets/bots", headers=auth)
        assert r.status_code == 200
        contract.check_data(r.json(), entry)
    r = c.post("/widgets/bots/actions/close", headers=auth, json={"key": "bot:alpha", "request_id": "x"})
    assert r.status_code == 404
    contract.check_action_response(r.json())
