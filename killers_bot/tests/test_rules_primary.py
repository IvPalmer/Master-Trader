"""Regras DECIDINDO em producao (#74): roteamento, equivalencia de campos e a
chave de desligar. O que precisa ser provado:

- quando a regra decide, o Claude NAO roda no caminho principal (so em shadow)
- o que vai ao receiver tem os campos que ele usa num fechamento
- quando a regra recusa, o Claude decide como antes
- KILLERS_RULES_PRIMARY=0 volta ao comportamento anterior sem deploy
"""
import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from killers_bot import observer, rules_classifier  # noqa: E402

SCHEMA = (ROOT / "killers_bot" / "schema.sql").read_text()

OPEN_8 = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
ENTRY: 0.0894 - 0.0900

TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300 - 0.1400 - 0.1500

STOP LOSS: 0.0810"""

PARTIAL = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
Target 1: 0.0945✅
Target 2: 0.0990✅

🔥22.4% Profit (5x)🔥
- Binance Killers®"""

SL_HIT = """📍SIGNAL ID: #2134📍
COIN: $SKY/USDT (2-5X)
Direction: LONG
➖➖➖➖➖➖➖

STOP LOSS: 0.0650

🚫19.4% Loss (2x)🚫"""

AMBIGUO = "CLOSE"          # sem cabecalho, com acao: regra recusa


# ── build_classification ────────────────────────────────────────────────────

def test_build_close_partial_tem_o_que_o_receiver_usa():
    c = rules_classifier.build_classification(10, PARTIAL, "close_partial")
    assert (c["kind"], c["signal_id"], c["symbol"], c["direction"]) == \
        ("close_partial", 2143, "POL", "long")
    # pct nulo -> receiver usa DEFAULT_PARTIAL_PCT, igual ao Claude com o prompt atual
    assert c["pct"] is None
    assert c["notes"] == PARTIAL
    assert c["confidence"] == 1.0


def test_build_close_full_por_stop():
    c = rules_classifier.build_classification(11, SL_HIT, "close_full")
    assert (c["kind"], c["signal_id"], c["symbol"]) == ("close_full", 2134, "SKY")


def test_build_chat_nao_carrega_simbolo():
    c = rules_classifier.build_classification(12, "Another month 🚀", "chat")
    assert c["kind"] == "chat" and c["symbol"] is None


@pytest.mark.parametrize("kind", ["open", "signal_update", "move_sl", "increase"])
def test_build_recusa_tipos_fora_do_primario(kind):
    with pytest.raises(ValueError):
        rules_classifier.build_classification(1, PARTIAL, kind)


# ── roteamento em process_message ───────────────────────────────────────────

class _Cfg:
    use_fast_path = True
    shadow_rules = True
    rules_primary = True
    receiver_url = "http://receiver.invalid/event"
    receiver_token = ""
    claude_binary = "claude"
    claude_model = None
    claude_timeout = 1
    classifier_template = None


@pytest.fixture()
def env(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    calls = {"claude": [], "posted": []}

    async def fake_chain(*a, **k):
        return []

    async def fake_claude(msg, chain, **k):
        calls["claude"].append(msg["id"])
        return {"id": msg["id"], "kind": "close_partial", "symbol": "POL",
                "direction": "long", "signal_id": 2143, "confidence": 0.9,
                "notes": "", "pct": None}

    async def fake_post(url, msg, cls, token=""):
        calls["posted"].append((msg["id"], cls["kind"], cls.get("symbol")))

    monkeypatch.setattr(observer, "build_reply_chain", fake_chain)
    monkeypatch.setattr(observer.classifier, "classify", fake_claude)
    monkeypatch.setattr(observer, "_post_to_receiver", fake_post)
    observer.record_signal_targets(conn, {"id": 1, "text": OPEN_8}, {"kind": "open"})
    yield conn, calls
    conn.close()


def _run(conn, cfg, mid, text):
    async def go():
        await observer.process_message(None, None, conn, cfg, {"id": mid, "text": text}, "live")
        # deixa o shadow do Claude (create_task) terminar
        for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            await t
    asyncio.run(go())


def test_regra_decide_e_claude_so_roda_em_shadow(env):
    conn, calls = env
    _run(conn, _Cfg(), 20, PARTIAL)
    # o receiver recebeu a decisao da REGRA
    assert calls["posted"] == [(20, "close_partial", "POL")]
    # o Claude rodou exatamente uma vez: em shadow, depois do POST
    assert calls["claude"] == [20]
    row = conn.execute(
        "SELECT primary_kind, primary_source, rule_kind, agree FROM rule_shadow "
        "WHERE msg_id = 20").fetchall()
    assert row == [("close_partial", "claude-shadow", "close_partial", 1)]


def test_regra_recusa_e_claude_decide_como_antes(env):
    conn, calls = env
    _run(conn, _Cfg(), 21, AMBIGUO)
    assert calls["claude"] == [21]                      # caminho principal
    assert calls["posted"] == [(21, "close_partial", "POL")]  # decisao do Claude (stub)


def test_chave_de_desligar_volta_ao_comportamento_anterior(env):
    conn, calls = env
    cfg = _Cfg()
    cfg.rules_primary = False
    _run(conn, cfg, 22, PARTIAL)
    # sem a regra, o Claude decide e nao ha shadow dele
    assert calls["claude"] == [22]
    assert calls["posted"] == [(22, "close_partial", "POL")]


def test_divergencia_do_claude_fica_gravada(env, monkeypatch):
    conn, calls = env

    async def claude_discorda(msg, chain, **k):
        return {"id": msg["id"], "kind": "close_full", "symbol": "POL",
                "direction": "long", "signal_id": 2143}
    monkeypatch.setattr(observer.classifier, "classify", claude_discorda)
    _run(conn, _Cfg(), 23, PARTIAL)
    row = conn.execute("SELECT primary_kind, rule_kind, agree FROM rule_shadow "
                       "WHERE msg_id = 23").fetchone()
    assert row == ("close_full", "close_partial", 0)


# ── configuracao ────────────────────────────────────────────────────────────

@pytest.fixture()
def base_env(monkeypatch):
    for var, val in (("KILLERS_TG_API_ID", "1"), ("KILLERS_TG_API_HASH", "x"),
                     ("KILLERS_TG_SESSION", "/tmp/x.session")):
        monkeypatch.setenv(var, val)


@pytest.mark.parametrize("valor,esperado", [(None, True), ("1", True), ("0", False),
                                            ("false", False), ("no", False)])
def test_chave_de_ambiente(base_env, monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("KILLERS_RULES_PRIMARY", raising=False)
    else:
        monkeypatch.setenv("KILLERS_RULES_PRIMARY", valor)
    assert observer.Config().rules_primary is esperado


def test_insiders_nunca_usa_a_regra(base_env, monkeypatch):
    monkeypatch.setenv("INSIDERS_TG_CHANNEL_ID", "-100123")
    assert observer._insiders_config().rules_primary is False
