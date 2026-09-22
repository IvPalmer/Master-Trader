"""Testes do shadow do classificador de regras no observer (#62).

O shadow e observacional: prova-se aqui que ele grava a comparacao, respeita
reciclagem de SIGNAL ID, e — o mais importante — que uma falha dentro dele
nao propaga para a ingestao.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from killers_bot import observer  # noqa: E402

SCHEMA = (ROOT / "killers_bot" / "schema.sql").read_text()

OPEN_8 = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
ENTRY: 0.0894 - 0.0900

TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300 - 0.1400 - 0.1500

STOP LOSS: 0.0810"""

OPEN_2 = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
ENTRY: 1.00 - 1.10

TARGETS: 1.20 - 1.30

STOP LOSS: 0.90"""

TWO_TARGETS = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Target 1: 0.0945✅
Target 2: 0.0990✅

🔥22.4% Profit (5x)🔥"""

# Mesmo SIGNAL ID, OUTRA moeda: e outra instancia de sinal.
OPEN_8_OUTRA_MOEDA = OPEN_8.replace("$POL/USDT", "$SUI/USDT")
TWO_TARGETS_OUTRA_MOEDA = TWO_TARGETS.replace("$POL/USDT", "$SUI/USDT")


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    yield c
    c.close()


def msg(mid, text, date="2026-09-22T00:00:00"):
    return {"id": mid, "text": text, "date": date}


def test_registra_alvos_declarados_do_open(conn):
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    assert observer.lookup_declared_targets(conn, OPEN_8, 99) == 8


def test_ignora_nao_open(conn):
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "close_partial"})
    assert observer.lookup_declared_targets(conn, OPEN_8, 99) is None


def test_signal_id_reciclado_usa_o_open_anterior_mais_recente(conn):
    """O mesmo #2143 reaparece com 2 alvos. Uma mensagem posterior tem de
    enxergar a contagem NOVA, nao a antiga."""
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    observer.record_signal_targets(conn, msg(50, OPEN_2), {"kind": "open"})
    assert observer.lookup_declared_targets(conn, TWO_TARGETS, 10) == 8
    assert observer.lookup_declared_targets(conn, TWO_TARGETS, 60) == 2


def test_nao_empresta_contagem_de_open_futuro(conn):
    """Um OPEN posterior nao pode decidir uma mensagem anterior."""
    observer.record_signal_targets(conn, msg(100, OPEN_8), {"kind": "open"})
    assert observer.lookup_declared_targets(conn, TWO_TARGETS, 50) is None


def test_id_reciclado_em_outra_moeda_nao_empresta_contagem(conn):
    """O corte cronologico sozinho nao basta: se o OPEN da epoca atual ainda
    nao foi visto, casar so pelo SIGNAL ID emprestaria a contagem do sinal
    antigo. Exigindo o simbolo, a regra recusa em vez de chutar."""
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    assert observer.lookup_declared_targets(conn, TWO_TARGETS_OUTRA_MOEDA, 99) is None
    # e a mesma moeda continua casando
    assert observer.lookup_declared_targets(conn, TWO_TARGETS, 99) == 8


def test_mensagem_sem_moeda_nao_empresta_contagem(conn):
    """Sem COIN na mensagem a instancia do sinal e desconhecida. Casar so pelo
    SIGNAL ID reciclado emprestaria a contagem de outro sinal."""
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    sem_moeda = "📍SIGNAL ID: #2143📍\nTarget 1: 0.0945✅"
    assert observer.lookup_declared_targets(conn, sem_moeda, 99) is None


def test_open_editado_gera_duas_linhas_desempate_por_row_id(conn):
    """Um OPEN editado reaparece com o mesmo msg_id. A leitura tem de pegar a
    versao mais nova, nao a primeira."""
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    observer.record_signal_targets(conn, msg(1, OPEN_2), {"kind": "open"})
    assert observer.lookup_declared_targets(conn, TWO_TARGETS, 99) == 2


def test_falha_ao_registrar_alvos_nao_propaga(conn):
    """record_signal_targets roda ANTES do simulador e do POST ao receiver.
    Uma excecao aqui pularia os dois — observacao derrubando execucao."""
    conn.close()
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})  # nao levanta


def test_rule_shadow_e_append_only(conn):
    """Uma mensagem editada e reavaliada. Sobrescrever apagaria justamente a
    divergencia que esta tabela existe para registrar."""
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    observer.shadow_rules(conn, msg(2, TWO_TARGETS), {"kind": "chat"}, "claude")
    observer.shadow_rules(conn, msg(2, TWO_TARGETS), {"kind": "close_partial"}, "claude")
    rows = conn.execute(
        "SELECT primary_kind, agree FROM rule_shadow WHERE msg_id = 2 "
        "ORDER BY row_id").fetchall()
    assert rows == [("chat", 0), ("close_partial", 1)]


def test_shadow_grava_concordancia(conn):
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    observer.shadow_rules(conn, msg(2, TWO_TARGETS),
                          {"kind": "close_partial"}, "claude")
    row = conn.execute(
        "SELECT primary_kind, primary_source, rule_kind, declared, agree "
        "FROM rule_shadow WHERE msg_id = 2 ORDER BY row_id DESC").fetchone()
    assert row == ("close_partial", "claude", "close_partial", 8, 1)


def test_shadow_grava_divergencia(conn):
    observer.record_signal_targets(conn, msg(1, OPEN_8), {"kind": "open"})
    # a regra diz parcial; o primario disse chat
    observer.shadow_rules(conn, msg(2, TWO_TARGETS), {"kind": "chat"}, "claude")
    row = conn.execute(
        "SELECT rule_kind, agree FROM rule_shadow WHERE msg_id = 2 "
        "ORDER BY row_id DESC").fetchone()
    assert row == ("close_partial", 0)


def test_todos_os_alvos_vira_recusa_no_shadow(conn):
    observer.record_signal_targets(conn, msg(1, OPEN_2), {"kind": "open"})
    observer.shadow_rules(conn, msg(2, TWO_TARGETS),
                          {"kind": "close_partial"}, "claude")
    row = conn.execute(
        "SELECT rule_kind, agree FROM rule_shadow WHERE msg_id = 2 "
        "ORDER BY row_id DESC").fetchone()
    assert row == (None, -1)


def test_shadow_marca_recusa_com_menos_um(conn):
    """Sem OPEN registrado, a regra recusa — agree = -1, nao 0."""
    observer.shadow_rules(conn, msg(2, TWO_TARGETS),
                          {"kind": "close_partial"}, "claude")
    row = conn.execute(
        "SELECT rule_kind, agree FROM rule_shadow WHERE msg_id = 2 "
        "ORDER BY row_id DESC").fetchone()
    assert row == (None, -1)


def test_falha_no_shadow_nao_propaga(conn):
    """Contrato central: o shadow e observacional. Se ele quebrar, a ingestao
    segue. Aqui a conexao esta fechada — a escrita falha por dentro."""
    conn.close()
    observer.shadow_rules(conn, msg(2, TWO_TARGETS),
                          {"kind": "close_partial"}, "claude")  # nao levanta


def test_record_signal_targets_sem_data_nao_quebra(conn):
    observer.record_signal_targets(conn, {"id": 1, "text": OPEN_8},
                                   {"kind": "open"})
    assert observer.lookup_declared_targets(conn, OPEN_8, 99) == 8


def test_insiders_desliga_o_shadow(monkeypatch):
    """As regras sao do formato Killers. No fan-out Insiders cada mensagem
    viraria divergencia falsa, poluindo a medicao."""
    monkeypatch.setenv("INSIDERS_TG_CHANNEL_ID", "-100123")
    for var, val in (("KILLERS_TG_API_ID", "1"), ("KILLERS_TG_API_HASH", "x"),
                     ("KILLERS_TG_SESSION", "/tmp/x.session")):
        monkeypatch.setenv(var, val)
    ins = observer._insiders_config()
    assert ins is not None
    assert ins.shadow_rules is False
    assert ins.use_fast_path is False
    assert observer.Config().shadow_rules is True
