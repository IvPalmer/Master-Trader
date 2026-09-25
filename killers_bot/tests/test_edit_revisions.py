"""Mensagem editada nao pode apagar a trilha de auditoria (#64).

`raw_messages`/`classifications` seguem "a mais recente vence"; as tabelas
`*_revisions` guardam cada versao, append-only.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from killers_bot import observer  # noqa: E402

SCHEMA = (ROOT / "killers_bot" / "schema.sql").read_text()


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def _cls(mid, kind, symbol=None, signal_id=None):
    return {"id": mid, "kind": kind, "symbol": symbol, "signal_id": signal_id,
            "direction": "long" if kind == "open" else None,
            "entry_range": [1.0, 1.1] if kind == "open" else None,
            "sl": 0.9 if kind == "open" else None, "tp": None, "pct": None,
            "confidence": 0.9, "notes": kind}


def test_edit_keeps_both_revisions_and_latest_in_main_tables(conn):
    original = {"id": 500, "date": "2026-09-22T00:00:00", "text": "gm"}
    edited = {"id": 500, "date": "2026-09-22T00:00:00",
              "edit_date": "2026-09-22T00:05:00", "text": "SIGNAL ID: #1 OPEN"}

    observer.persist_raw(conn, original)
    observer.persist_classification(conn, _cls(500, "chat"))
    observer.persist_raw(conn, edited)
    observer.persist_classification(conn, _cls(500, "open", "POL", 1))

    # Tabelas principais: so a versao mais recente (comportamento inalterado).
    raw = conn.execute("SELECT * FROM raw_messages WHERE msg_id=500").fetchall()
    assert len(raw) == 1
    assert raw[0]["text"] == "SIGNAL ID: #1 OPEN"
    assert raw[0]["edited_at"] == "2026-09-22T00:05:00"
    cls = conn.execute("SELECT * FROM classifications WHERE msg_id=500").fetchall()
    assert len(cls) == 1 and cls[0]["kind"] == "open"

    # Revisoes: as duas, em ordem, cada uma com sua propria carga.
    raw_revs = conn.execute(
        "SELECT * FROM raw_message_revisions WHERE msg_id=500 ORDER BY rev_id"
    ).fetchall()
    assert [r["text"] for r in raw_revs] == ["gm", "SIGNAL ID: #1 OPEN"]
    assert [r["edited_at"] for r in raw_revs] == [None, "2026-09-22T00:05:00"]
    assert json.loads(raw_revs[0]["raw_json"])["text"] == "gm"

    cls_revs = conn.execute(
        "SELECT * FROM classification_revisions WHERE msg_id=500 ORDER BY rev_id"
    ).fetchall()
    assert [r["kind"] for r in cls_revs] == ["chat", "open"]
    assert [r["symbol"] for r in cls_revs] == [None, "POL"]
    assert cls_revs[1]["entry_lo"] == 1.0 and cls_revs[1]["sl"] == 0.9
    assert json.loads(cls_revs[0]["raw_json"])["kind"] == "chat"


def test_redelivery_without_edit_is_recorded_as_revision(conn):
    """Reentrega identica e uma leitura real: gera revisao, nao duplica a
    tabela principal."""
    m = {"id": 7, "date": "2026-09-22T00:00:00", "text": "gm"}
    observer.persist_raw(conn, m)
    observer.persist_raw(conn, m)
    assert conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM raw_message_revisions").fetchone()[0] == 2


def test_revision_failure_does_not_break_persist(conn):
    """Auditoria quebrada nao derruba a ingestao."""
    conn.execute("DROP TABLE raw_message_revisions")
    conn.execute("DROP TABLE classification_revisions")
    observer.persist_raw(conn, {"id": 9, "text": "gm"})
    observer.persist_classification(conn, _cls(9, "chat"))
    assert conn.execute("SELECT text FROM raw_messages").fetchone()[0] == "gm"
    assert conn.execute("SELECT kind FROM classifications").fetchone()[0] == "chat"


def test_init_db_migrates_legacy_db(tmp_path):
    """Banco de producao antigo (sem as tabelas novas) ganha as revisoes no
    init_db, sem perder o que ja tinha."""
    p = tmp_path / "legacy.sqlite"
    legacy = sqlite3.connect(p)
    legacy.executescript(SCHEMA.split("-- ── Revisoes de mensagens editadas")[0])
    legacy.execute("INSERT INTO raw_messages (msg_id, received_at, raw_json) "
                   "VALUES (1, 'x', '{}')")
    legacy.commit()
    legacy.close()

    c = observer.init_db(str(p))
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"raw_message_revisions", "classification_revisions"} <= tables
    assert c.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0] == 1
    c.close()
