"""Gate de confianca em SHADOW (#65).

O que precisa ser provado:
- o arquivo versionado e valido e segue a ordem de limiares decidida
- config malformada falha alto; config ausente nao impede o observer
- veredito pass / would_block por tipo; confianca ausente em tipo de acao
  reprova; `chat` nao reprova
- so classificacoes do Claude sao avaliadas; decisoes das regras nao geram linha
- uma falha no gate (tabela quebrada, excecao) nao derruba o processamento
- e o principal: uma classificacao would_block e encaminhada EXATAMENTE como
  antes — shadow nao muda o encaminhamento
"""
import asyncio
import copy
import json
import logging
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from killers_bot import confidence_gate as cg  # noqa: E402
from killers_bot import observer  # noqa: E402

SCHEMA = (ROOT / "killers_bot" / "schema.sql").read_text()

ALL_KINDS = ["open", "close_full", "close_partial", "move_sl", "increase",
             "signal_update", "chat"]
ACTION_KINDS = [k for k in ALL_KINDS if k != "chat"]

PARTIAL = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
Target 1: 0.0945✅
Target 2: 0.0990✅

🔥22.4% Profit (5x)🔥
- Binance Killers®"""

STRICT_OPEN = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
ENTRY: 0.0894 - 0.0900

TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300 - 0.1400 - 0.1500

STOP LOSS: 0.0810"""

AMBIGUO = "CLOSE"     # a regra recusa -> o Claude decide


@pytest.fixture()
def cfg():
    return cg.load_config()


def _valid():
    return json.loads(cg.DEFAULT_PATH.read_text())


# ── arquivo versionado ──────────────────────────────────────────────────────

def test_arquivo_versionado_e_valido_e_em_shadow(cfg):
    assert cfg.enabled and cfg.mode == "shadow" and cfg.schema_version == 1
    assert set(cfg.thresholds) == set(ALL_KINDS)
    assert list(cfg.label_order) == ALL_KINDS
    t = cfg.thresholds
    assert t["chat"] == 0.0
    # close_full / signal_update sao os mais exigentes
    top = max(t.values())
    assert t["close_full"] == t["signal_update"] == top
    assert all(t[k] < top for k in ("open", "close_partial", "chat"))
    assert _valid()["provisional"] is True


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(schema_version=True),
    lambda d: d.pop("schema_version"),
    lambda d: d.update(mode="enforce"),
    lambda d: d.pop("mode"),
    lambda d: d["thresholds"].update(close_full=1.5),
    lambda d: d["thresholds"].update(close_full=-0.1),
    lambda d: d["thresholds"].update(close_full="0.9"),
    lambda d: d["thresholds"].update(close_full=True),
    lambda d: d["thresholds"].pop("signal_update"),
    lambda d: d["thresholds"].update(novo=0.5),
    lambda d: d.update(label_order=["open", "open"]),
    lambda d: d.update(label_order="open"),
    lambda d: d.update(thresholds=[]),
])
def test_config_malformada_falha_alto(tmp_path, mutate):
    d = _valid()
    mutate(d)
    p = tmp_path / "g.json"
    p.write_text(json.dumps(d))
    with pytest.raises(cg.GateConfigError):
        cg.load_config(p)


def test_json_invalido_falha_alto(tmp_path):
    p = tmp_path / "g.json"
    p.write_text("{nao e json")
    with pytest.raises(cg.GateConfigError):
        cg.load_config(p)


def test_config_ausente_desliga_limiares_com_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        c = cg.load_config(tmp_path / "nao_existe.json")
    assert not c.enabled and c.mode == "shadow" and c.schema_version == 0
    assert "ausente" in caplog.text
    v = cg.evaluate(c, {"kind": "close_full", "confidence": 0.1})
    assert v.verdict == cg.DISABLED and v.threshold is None and v.confidence == 0.1


@pytest.fixture()
def base_env(monkeypatch):
    for var, val in (("KILLERS_TG_API_ID", "1"), ("KILLERS_TG_API_HASH", "x"),
                     ("KILLERS_TG_SESSION", "/tmp/x.session")):
        monkeypatch.setenv(var, val)


def test_config_malformada_nao_derruba_o_observer(base_env, monkeypatch, tmp_path, caplog):
    """Revisao: um gate so de observacao nao pode parar o encaminhamento de
    sinais (inclusive fechamentos) por um erro de digitacao no JSON."""
    p = tmp_path / "g.json"
    p.write_text(json.dumps(dict(_valid(), mode="enforce")))
    monkeypatch.setattr(cg, "DEFAULT_PATH", p)
    with caplog.at_level(logging.ERROR):
        c = observer.Config()
    assert c.confidence_gate.enabled is False
    assert "gate DESLIGADO" in caplog.text


def test_config_versionada_e_valida():
    """A falha alta fica no CI: o arquivo do repositorio tem de parsear."""
    c = cg.load_config(cg.DEFAULT_PATH)
    assert c.enabled and c.mode == "shadow"


def test_subida_aceita_config_ausente(base_env, monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "DEFAULT_PATH", tmp_path / "nao_existe.json")
    assert observer.Config().confidence_gate.enabled is False


def test_subida_carrega_config_real(base_env):
    c = observer.Config()
    assert c.confidence_gate.enabled and c.confidence_gate.mode == "shadow"


# ── veredito ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_pass_no_limiar(cfg, kind):
    t = cfg.thresholds[kind]
    v = cg.evaluate(cfg, {"kind": kind, "confidence": t})
    assert v.verdict == cg.PASS and v.threshold == t


@pytest.mark.parametrize("kind", ACTION_KINDS)
def test_would_block_abaixo_do_limiar(cfg, kind):
    t = cfg.thresholds[kind]
    v = cg.evaluate(cfg, {"kind": kind, "confidence": t - 0.01})
    assert v.verdict == cg.WOULD_BLOCK and "limiar" in v.reason


def test_close_full_mais_exigente_que_open(cfg):
    # 0.85: passa num open, reprovaria num close_full / signal_update
    assert cg.evaluate(cfg, {"kind": "open", "confidence": 0.85}).verdict == cg.PASS
    for k in ("close_full", "signal_update"):
        assert cg.evaluate(cfg, {"kind": k, "confidence": 0.85}).verdict == cg.WOULD_BLOCK


@pytest.mark.parametrize("kind", ACTION_KINDS)
@pytest.mark.parametrize("conf,motivo", [
    (None, "ausente"), ("0.99", "nao numerica"), (True, "nao numerica"),
    (float("nan"), "nao numerica"), (1.5, "fora"), (-0.2, "fora"),
])
def test_confianca_invalida_em_tipo_de_acao_reprova(cfg, kind, conf, motivo):
    c = {"kind": kind}
    if conf is not None:
        c["confidence"] = conf
    v = cg.evaluate(cfg, c)
    assert v.verdict == cg.WOULD_BLOCK and motivo in v.reason


def test_chat_sem_confianca_passa(cfg):
    assert cg.evaluate(cfg, {"kind": "chat"}).verdict == cg.PASS


@pytest.mark.parametrize("kind", [None, "close_everything", 3])
def test_kind_desconhecido_reprova(cfg, kind):
    v = cg.evaluate(cfg, {"kind": kind, "confidence": 1.0})
    assert v.verdict == cg.WOULD_BLOCK and v.threshold is None


# ── integracao com process_message ─────────────────────────────────────────

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

    def __init__(self):
        self.confidence_gate = cg.load_config()


CLAUDE_LOW = {"kind": "close_full", "symbol": "POL", "direction": "long",
              "signal_id": 2143, "confidence": 0.3, "notes": "", "pct": None}


@pytest.fixture()
def env(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    calls = {"claude": [], "posted": [], "sim": []}
    state = {"reply": CLAUDE_LOW}

    async def fake_chain(*a, **k):
        return []

    async def fake_claude(msg, chain, **k):
        calls["claude"].append(msg["id"])
        return dict(copy.deepcopy(state["reply"]), id=msg["id"])

    async def fake_post(url, msg, cls, token=""):
        calls["posted"].append((url, copy.deepcopy(msg), copy.deepcopy(cls), token))

    monkeypatch.setattr(observer, "build_reply_chain", fake_chain)
    monkeypatch.setattr(observer.classifier, "classify", fake_claude)
    monkeypatch.setattr(observer, "_post_to_receiver", fake_post)
    monkeypatch.setattr(observer.simulator, "update_paper_position",
                        lambda c, m, cls: calls["sim"].append(cls["kind"]))
    monkeypatch.setattr(observer.simulator, "open_paper_position",
                        lambda c, m, cls: calls["sim"].append(cls["kind"]))
    yield conn, calls, state
    conn.close()


def _run(conn, cfg, mid, text):
    async def go():
        await observer.process_message(None, None, conn, cfg,
                                       {"id": mid, "text": text}, "live")
        for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            await t
    asyncio.run(go())


def _gate_rows(conn):
    return conn.execute(
        "SELECT msg_id, kind, source, confidence, threshold, verdict, mode, "
        "config_schema_version FROM confidence_gate ORDER BY row_id").fetchall()


def test_would_block_e_encaminhado_exatamente_como_antes(env, caplog):
    conn, calls, _ = env
    # Referencia: o MESMO fluxo sem gate nenhum (comportamento pre-#65).
    sem_gate = _Cfg()
    sem_gate.confidence_gate = None
    _run(conn, sem_gate, 30, AMBIGUO)
    antes = (list(calls["posted"]), list(calls["sim"]))
    assert _gate_rows(conn) == []

    calls["posted"].clear(), calls["sim"].clear()
    with caplog.at_level(logging.WARNING, logger="killers_bot.observer"):
        _run(conn, _Cfg(), 30, AMBIGUO)
    depois = (list(calls["posted"]), list(calls["sim"]))

    # Encaminhamento e simulador identicos, payload inteiro.
    assert depois == antes
    assert len(depois[0]) == 1
    url, msg, cls, _tok = depois[0][0]
    assert cls == dict(CLAUDE_LOW, id=30)
    # E o veredito foi gravado + logado.
    assert _gate_rows(conn) == [
        (30, "close_full", "claude", 0.3, 0.9, "would_block", "shadow", 1)]
    assert "CONF-GATE WOULD_BLOCK" in caplog.text
    # A classificacao persistida tambem e a mesma.
    assert conn.execute("SELECT kind, confidence FROM classifications "
                        "WHERE msg_id = 30").fetchone() == ("close_full", 0.3)


def test_pass_do_claude_fica_gravado(env):
    conn, calls, state = env
    state["reply"] = dict(CLAUDE_LOW, confidence=0.95)
    _run(conn, _Cfg(), 31, AMBIGUO)
    assert _gate_rows(conn) == [
        (31, "close_full", "claude", 0.95, 0.9, "pass", "shadow", 1)]
    assert len(calls["posted"]) == 1


def test_signal_update_sem_confianca_would_block_e_encaminhado(env):
    conn, calls, state = env
    su = {k: v for k, v in CLAUDE_LOW.items() if k != "confidence"}
    su.update(kind="signal_update", instruction="close_full_now")
    state["reply"] = su
    _run(conn, _Cfg(), 32, AMBIGUO)
    (row,) = _gate_rows(conn)
    assert row[1] == "signal_update" and row[3] is None and row[5] == "would_block"
    assert calls["posted"][0][2] == dict(su, id=32)


def test_regras_decidindo_nao_sao_avaliadas(env):
    conn, calls, _ = env
    # O OPEN grava os alvos declarados; sem ele a regra recusaria o PARTIAL.
    _run(conn, _Cfg(), 33, STRICT_OPEN)      # strict_open decide
    _run(conn, _Cfg(), 34, PARTIAL)          # rules_classifier decide
    assert _gate_rows(conn) == []
    # o Claude rodou em shadow nas duas, e mesmo assim nao gera linha de gate
    assert calls["claude"] == [33, 34]
    assert [p[2]["kind"] for p in calls["posted"]] == ["open", "close_partial"]


def test_regra_desligada_claude_decide_e_e_avaliado(env):
    conn, calls, _ = env
    c = _Cfg()
    c.rules_primary = False
    _run(conn, c, 35, PARTIAL)
    assert [r[2] for r in _gate_rows(conn)] == ["claude"]


def test_tabela_quebrada_nao_derruba_processamento(env, caplog):
    conn, calls, _ = env
    conn.execute("DROP TABLE confidence_gate")
    conn.commit()
    with caplog.at_level(logging.ERROR, logger="killers_bot.observer"):
        _run(conn, _Cfg(), 36, AMBIGUO)
    assert calls["posted"][0][2] == dict(CLAUDE_LOW, id=36)
    assert calls["sim"] == ["close_full"]
    assert conn.execute("SELECT kind FROM classifications WHERE msg_id = 36"
                        ).fetchone() == ("close_full",)
    assert "[CONF-GATE] falhou" in caplog.text
    assert not conn.in_transaction


def test_excecao_no_evaluate_nao_derruba_processamento(env, monkeypatch):
    conn, calls, _ = env

    def boom(*a, **k):
        raise RuntimeError("bug no gate")
    monkeypatch.setattr(cg, "evaluate", boom)
    _run(conn, _Cfg(), 37, AMBIGUO)
    assert calls["posted"][0][2] == dict(CLAUDE_LOW, id=37)
    assert _gate_rows(conn) == []


def test_edicao_gera_nova_linha_append_only(env):
    conn, calls, state = env
    _run(conn, _Cfg(), 38, AMBIGUO)
    state["reply"] = dict(CLAUDE_LOW, confidence=0.99)
    _run(conn, _Cfg(), 38, AMBIGUO)
    assert [r[5] for r in _gate_rows(conn)] == ["would_block", "pass"]
