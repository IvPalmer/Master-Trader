"""#64: at most one executing action per (position, source message).

An edited Telegram message is re-forwarded with a new classification. The
events table dedupes on UNIQUE(pos_id, msg_id, kind), so without an extra
gate a message whose kind changes between edits (close_partial → close_full,
signal_update → close_full, or the open message itself → close_full) would
act twice on the same position. FT calls are mocked.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402

OPEN_MSG = 200000
SIGNAL = 3001


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _restore_app_state():
    saved = getattr(receiver_main.app, "state", None)
    try:
        yield
    finally:
        if saved is not None:
            receiver_main.app.state = saved


class _FakeState:
    def __init__(self, c, cf):
        self.conn = c
        self.cfg = cf
        self.ft_session = None
        self.public_session = None
        self.notify_tasks = set()
        self.phase2_lock = None


def _setup(seed_open_event=True):
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    # Plain market-exit close path (no phase-2 audit-only branch).
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "false"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, stake_usd, leverage, ft_trade_id, pct_open) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (SIGNAL, "KITE", "KITE/USDT:USDT", "long", "open", OPEN_MSG,
         "2026-07-01T20:00:00+00:00", 20.0, 5.0, 42, 100),
    )
    pos_id = conn.execute(
        "SELECT pos_id FROM positions WHERE open_msg_id=?", (OPEN_MSG,)
    ).fetchone()[0]
    if seed_open_event:
        conn.execute(
            "INSERT INTO events (pos_id, msg_id, event_at, kind, payload, response) "
            "VALUES (?, ?, ?, 'open', '{}', ?)",
            (pos_id, OPEN_MSG, "2026-07-01T20:00:00+00:00",
             json.dumps({"status": 200})))
    receiver_main.app.state = _FakeState(conn, cfg)
    return cfg, conn, pos_id


def _payload(kind, msg_id, **extra):
    cls = {"kind": kind, "signal_id": SIGNAL, "symbol": "KITE",
           "direction": "long"}
    cls.update(extra)
    return receiver_main.EventPayload(
        msg={"id": msg_id, "date": "2026-07-01T20:30:00+00:00", "text": "x"},
        classification=cls,
    )


class _FT:
    def __init__(self):
        self.calls = []

    async def force_exit(self, _cfg, trade_id, pct=None, session=None):
        self.calls.append(pct)
        return {"status": 200, "body": '{"result":"ok"}'}


def _process(ft, payload):
    with patch.object(receiver_main, "ft_force_exit", side_effect=ft.force_exit):
        return _run(receiver_main._process_event(payload))


def test_close_partial_then_edited_to_close_full_is_not_executed():
    _cfg, conn, pos_id = _setup()
    ft = _FT()
    M = 200010

    r1 = _process(ft, _payload("close_partial", M, pct=50))
    assert r1["action"] == "force_exit"
    assert len(ft.calls) == 1

    r2 = _process(ft, _payload("close_full", M))
    assert r2["action"] == "deduped"
    assert r2["prior_kind"] == "close_partial"
    assert r2["kind"] == "close_full"
    assert r2["pos_id"] == pos_id
    assert "close_partial" in r2["reason"] and "close_full" in r2["reason"]
    assert len(ft.calls) == 1, "edited kind must not reach Freqtrade again"
    # No second events row was claimed for the edit.
    kinds = [r[0] for r in conn.execute(
        "SELECT kind FROM events WHERE pos_id=? AND msg_id=?", (pos_id, M))]
    assert kinds == ["close_partial"]
    row = conn.execute("SELECT state, pct_open FROM positions WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "open" and row["pct_open"] == 50


@pytest.mark.parametrize("seed_open_event", [True, False])
def test_open_message_edited_into_close_full_is_not_executed(seed_open_event):
    _cfg, _conn, pos_id = _setup(seed_open_event=seed_open_event)
    ft = _FT()
    r = _process(ft, _payload("close_full", OPEN_MSG))
    assert r["action"] == "deduped"
    assert r["prior_kind"] == "open"
    assert r["pos_id"] == pos_id
    assert ft.calls == []


def test_signal_update_then_edited_to_close_full_is_not_executed():
    _cfg, _conn, pos_id = _setup()
    ft = _FT()
    M = 200020
    r1 = _process(ft, _payload("signal_update", M, instruction="close_full_now"))
    assert r1["action"] == "force_exit"
    assert len(ft.calls) == 1
    # Position is closed now, so re-open it to prove the gate (not the
    # no_active_position guard) is what blocks the edit.
    _conn.execute("UPDATE positions SET state='open', pct_open=100 WHERE pos_id=?",
                  (pos_id,))
    r2 = _process(ft, _payload("close_full", M))
    assert r2["action"] == "deduped"
    assert r2["prior_kind"] == "signal_update"
    assert len(ft.calls) == 1


def test_close_partial_then_edited_to_signal_update_is_not_executed():
    _cfg, _conn, _pos_id = _setup()
    ft = _FT()
    M = 200025
    assert _process(ft, _payload("close_partial", M, pct=50))["action"] == "force_exit"
    r2 = _process(ft, _payload("signal_update", M, instruction="close_full_now"))
    assert r2["action"] == "deduped"
    assert r2["prior_kind"] == "close_partial"
    assert len(ft.calls) == 1


def test_same_kind_redelivery_keeps_existing_dedupe():
    _cfg, _conn, pos_id = _setup()
    ft = _FT()
    M = 200030
    assert _process(ft, _payload("close_partial", M, pct=50))["action"] == "force_exit"
    r2 = _process(ft, _payload("close_partial", M, pct=50))
    assert r2 == {"action": "deduped", "pos_id": pos_id, "kind": "close_partial"}
    assert len(ft.calls) == 1


def test_different_msg_close_full_still_executes():
    _cfg, conn, pos_id = _setup()
    ft = _FT()
    assert _process(ft, _payload("close_partial", 200040, pct=50))["action"] == "force_exit"
    r2 = _process(ft, _payload("close_full", 200041))
    assert r2["action"] == "force_exit"
    assert len(ft.calls) == 2
    assert conn.execute("SELECT state FROM positions WHERE pos_id=?",
                        (pos_id,)).fetchone()["state"] == "closed"


def test_chat_then_edited_to_close_partial_executes_once():
    _cfg, conn, pos_id = _setup()
    ft = _FT()
    M = 200050
    r0 = _process(ft, _payload("chat", M))
    assert r0["action"] == "ignored"
    assert conn.execute("SELECT COUNT(*) FROM events WHERE msg_id=?",
                        (M,)).fetchone()[0] == 0
    r1 = _process(ft, _payload("close_partial", M, pct=50))
    assert r1["action"] == "force_exit"
    r2 = _process(ft, _payload("close_partial", M, pct=50))
    assert r2["action"] == "deduped"
    assert len(ft.calls) == 1


def test_kind_change_dedupe_renders_operator_alert():
    cfg, _conn, _pos_id = _setup()
    payload = _payload("close_full", 200060)
    result = {"action": "deduped", "pos_id": 7, "kind": "close_full",
              "prior_kind": "close_partial",
              "reason": "msg already acted as close_partial on this position "
                        "(edited message, kind changed to close_full)"}
    text = receiver_main._format_event_summary(cfg, payload, result)
    assert text is not None
    assert "EDIT IGNORED" in text
    assert "msg already acted as close_partial" in text
    # Plain same-kind redelivery stays silent.
    plain = {"action": "deduped", "pos_id": 7, "kind": "close_full"}
    assert receiver_main._format_event_summary(cfg, payload, plain) is None
