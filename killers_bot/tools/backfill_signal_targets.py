"""Preenche `signal_targets` a partir dos OPENs ja classificados (#62).

Sem isto, o shadow do classificador de regras comeca cego: toda mensagem de
alvo atingido cujo OPEN antecede a instrumentacao cai na recusa
"alvos sem contagem do open". O backfill recupera essa contagem do historico
que ja esta na base.

Idempotente: nao duplica uma (signal_key, msg_id) ja registrada.

Uso:
    python killers_bot/tools/backfill_signal_targets.py [/caminho/state.sqlite]
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rules_classifier import (  # noqa: E402
    declared_target_count, signal_key, signal_symbol,
)


def backfill(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT c.msg_id, r.text, r.posted_at FROM classifications c "
        "JOIN raw_messages r ON r.msg_id = c.msg_id "
        "WHERE c.kind = 'open' ORDER BY c.msg_id"
    ).fetchall()

    inserted = skipped = 0
    for msg_id, text, posted_at in rows:
        key = signal_key(text or "")
        declared = declared_target_count(text or "")
        if not key or not declared:
            skipped += 1
            continue
        exists = conn.execute(
            "SELECT 1 FROM signal_targets WHERE signal_key = ? AND msg_id = ?",
            (key, msg_id),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO signal_targets (signal_key, symbol, declared, msg_id, "
            "posted_at) VALUES (?, ?, ?, ?, ?)",
            (key, signal_symbol(text or ""), declared, msg_id, posted_at),
        )
        inserted += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM signal_targets").fetchone()[0]
    conn.close()
    print(f"opens lidos={len(rows)} inseridos={inserted} pulados={skipped} "
          f"| signal_targets agora={total}")
    return 0


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.getenv(
        "KILLERS_DB", "/var/lib/killers/state.sqlite")
    sys.exit(backfill(path))
