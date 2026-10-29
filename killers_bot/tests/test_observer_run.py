"""observer.run() liga o feed Killers e so ele (#216).

O fan-out Insiders saiu do codigo. O que precisa ser provado, com um cliente
Telethon falso (sem rede, sem sessao):

- o canal Killers e resolvido e recebe os dois handlers (nova e editada),
  com o config Killers inalterado
- uma INSIDERS_TG_CHANNEL_ID esquecida no .env do host nao liga mais nada:
  nenhum segundo canal, nenhum banco do insiders
"""
import asyncio
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from killers_bot import classifier, observer  # noqa: E402

SCHEMA = (ROOT / "killers_bot" / "schema.sql").read_text()


class _Event:
    def __init__(self, kind, chats):
        self.kind, self.chats = kind, chats


class _Client:
    """TelegramClient falso: registra o que o observer pede."""

    instances = []

    def __init__(self, session, api_id, api_hash):
        self.entities, self.handlers = [], []
        _Client.instances.append(self)

    async def start(self):
        return self

    async def get_me(self):
        return types.SimpleNamespace(first_name="t", id=1, phone=None)

    async def get_entity(self, username):
        self.entities.append(username)
        return types.SimpleNamespace(id=777, title="killers")

    def iter_messages(self, *a, **k):  # banco novo: o backfill nao roda
        raise AssertionError("backfill sem last_msg_id")

    def on(self, event):
        def register(fn):
            self.handlers.append((event.kind, tuple(event.chats)))
            return fn
        return register

    async def run_until_disconnected(self):
        return None


@pytest.fixture
def fake_telethon(monkeypatch):
    _Client.instances.clear()
    events = types.SimpleNamespace(
        NewMessage=lambda chats: _Event("new", chats),
        MessageEdited=lambda chats: _Event("edited", chats),
    )
    monkeypatch.setitem(sys.modules, "telethon",
                        types.SimpleNamespace(TelegramClient=_Client, events=events))

    async def no_retry(*a, **k):
        return None

    monkeypatch.setattr(observer, "retry_due", no_retry)
    return _Client


@pytest.fixture
def killers_env(monkeypatch, tmp_path):
    for var, val in (("KILLERS_TG_API_ID", "1"), ("KILLERS_TG_API_HASH", "x"),
                     ("KILLERS_TG_SESSION", str(tmp_path / "k.session"))):
        monkeypatch.setenv(var, val)
    monkeypatch.delenv("KILLERS_TG_CHANNEL_ID", raising=False)
    monkeypatch.delenv("KILLERS_TG_CHANNEL_USERNAME", raising=False)
    monkeypatch.delenv("KILLERS_RULES_PRIMARY", raising=False)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def test_run_sets_up_the_killers_channel(fake_telethon, killers_env):
    config = observer.Config()
    assert (config.feed_label, config.classifier_template) == ("killers", classifier.PROMPT_TEMPLATE)
    assert (config.use_fast_path, config.shadow_rules, config.rules_primary) == (True, True, True)

    asyncio.run(observer.run(config, _conn()))

    [client] = fake_telethon.instances
    assert client.entities == ["BinanceKillers_FreeSignal"]
    assert client.handlers == [("new", (777,)), ("edited", (777,))]


def test_a_leftover_insiders_channel_id_starts_no_second_feed(fake_telethon, killers_env,
                                                              monkeypatch, tmp_path):
    insiders_db = tmp_path / "insiders-bot" / "state.sqlite"
    monkeypatch.setenv("INSIDERS_TG_CHANNEL_ID", "-100123")
    monkeypatch.setenv("INSIDERS_OBSERVER_DB", str(insiders_db))
    monkeypatch.setenv("INSIDERS_RECEIVER_URL", "http://127.0.0.1:9/event")

    asyncio.run(observer.run(observer.Config(), _conn()))

    [client] = fake_telethon.instances
    assert client.entities == ["BinanceKillers_FreeSignal"]
    assert {chats for _, chats in client.handlers} == {(777,)}
    assert not insiders_db.parent.exists()
