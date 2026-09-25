"""POST /test/notify requires X-Notify-Token when configured (#59).

The route relays caller text to the ops Telegram chat from a container on the
shared dokploy-network. With TRADE_WEBHOOK_NOTIFY_TOKEN set, a missing or
wrong header is a 401 and Telegram is never called; unset keeps the legacy
open route (rollout stage 1) but warns at startup.
"""
import importlib
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

TOKEN = "notify-token-for-tests-0123456789abcdef"


def _load(monkeypatch, tmp_path, token):
    """Import app.py fresh so its import-time env reads see `token`."""
    monkeypatch.setenv("TRADES_DIR", str(tmp_path))
    monkeypatch.delenv("OPS_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPS_BOT_CHAT_ID", raising=False)
    if token is None:
        monkeypatch.delenv("TRADE_WEBHOOK_NOTIFY_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", token)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    monkeypatch.setattr(module, "telegram_send", fake_send)
    return module, TestClient(module.app), sent


@pytest.fixture(autouse=True)
def _drop_module():
    yield
    sys.modules.pop("app", None)


@pytest.mark.parametrize("headers", [
    {},
    {"X-Notify-Token": ""},
    {"X-Notify-Token": "wrong"},
    {"X-Notify-Token": TOKEN + "x"},
    {"X-Notify-Token": TOKEN[:-1]},
    {"Authorization": f"Bearer {TOKEN}"},
])
def test_token_set_rejects_missing_or_wrong_header(monkeypatch, tmp_path, headers):
    _, client, sent = _load(monkeypatch, tmp_path, TOKEN)
    r = client.post("/test/notify", json={"text": "spoof"}, headers=headers)
    assert r.status_code == 401
    assert sent == []


def test_token_set_accepts_correct_header(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path, TOKEN)
    r = client.post("/test/notify", json={"text": "hello"},
                    headers={"X-Notify-Token": TOKEN})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "telegram_sent": True}
    assert sent == ["hello"]


def test_token_unset_keeps_legacy_open_route(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="trade-webhook"):
        _, client, sent = _load(monkeypatch, tmp_path, None)
    assert "UNAUTHENTICATED" in caplog.text
    r = client.post("/test/notify", json={"text": "legacy"})
    assert r.status_code == 200
    assert sent == ["legacy"]


def test_short_token_warns_without_logging_it(monkeypatch, tmp_path, caplog):
    short = "short-token"
    with caplog.at_level(logging.WARNING, logger="trade-webhook"):
        _, client, _ = _load(monkeypatch, tmp_path, short)
    assert "shorter than 24" in caplog.text
    assert short not in caplog.text
    # Still enforced, just weak.
    assert client.post("/test/notify", json={"text": "x"}).status_code == 401


def test_other_routes_unaffected_by_token(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path, TOKEN)
    assert client.get("/healthz").status_code == 200
    r = client.post("/freqtrade/event",
                    json={"type": "status", "bot_name": "b", "status": "up"})
    assert r.status_code == 200
    assert (tmp_path / "b.jsonl").is_file()
    assert sent == ["[b] STATUS up"]
