"""The receiver authenticates to trade-webhook's /test/notify (#59).

X-Notify-Token is sent iff TRADE_WEBHOOK_NOTIFY_TOKEN is set, on both the
shared-session path and the one-off ClientSession path, and the token never
reaches the logs.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402

TOKEN = "notify-token-for-tests-0123456789abcdef"


class _Resp:
    def __init__(self, status=200):
        self.status = status

    async def read(self):
        return b"{}"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Resp(self.status)


def _cfg(monkeypatch, token):
    if token is None:
        monkeypatch.delenv("TRADE_WEBHOOK_NOTIFY_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", token)
    monkeypatch.setenv("KILLERS_NOTIFY_URL", "http://trade-webhook:8088/test/notify")
    return receiver_main.Config()


def _headers_sent(session):
    assert len(session.calls) == 1
    return session.calls[0][1].get("headers") or {}


def test_header_sent_when_token_set(monkeypatch):
    cfg = _cfg(monkeypatch, TOKEN)
    sess = _Session()
    asyncio.run(receiver_main._notify_telegram(cfg, "hi", session=sess))
    assert _headers_sent(sess) == {"X-Notify-Token": TOKEN}
    assert sess.calls[0][1]["json"] == {"text": "hi"}


def test_no_header_when_token_unset(monkeypatch):
    cfg = _cfg(monkeypatch, None)
    sess = _Session()
    asyncio.run(receiver_main._notify_telegram(cfg, "hi", session=sess))
    assert "X-Notify-Token" not in _headers_sent(sess)


def test_blank_token_treated_as_unset(monkeypatch):
    cfg = _cfg(monkeypatch, "   ")
    sess = _Session()
    asyncio.run(receiver_main._notify_telegram(cfg, "hi", session=sess))
    assert "X-Notify-Token" not in _headers_sent(sess)


def test_header_sent_on_one_off_session_path(monkeypatch):
    cfg = _cfg(monkeypatch, TOKEN)
    created = []

    class _ClientSession(_Session):
        def __init__(self, *a, **k):
            super().__init__()
            created.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(receiver_main.aiohttp, "ClientSession", _ClientSession)
    asyncio.run(receiver_main._notify_telegram(cfg, "hi"))
    assert _headers_sent(created[0]) == {"X-Notify-Token": TOKEN}


def test_rejection_warns_without_leaking_token(monkeypatch, caplog):
    cfg = _cfg(monkeypatch, TOKEN)
    sess = _Session(status=401)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(receiver_main._notify_telegram(cfg, "hi", session=sess))
    assert "rejected (401)" in caplog.text
    assert TOKEN not in caplog.text
