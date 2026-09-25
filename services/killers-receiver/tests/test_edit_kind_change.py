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


def test_message_that_closed_cannot_be_edited_into_a_new_open():
    """Review finding: the open path only deduped on open_msg_id, so a close
    edited into `open` could open a second leveraged position."""
    _cfg, conn, pos_id = _setup()
    ft = _FT()
    M = 200070
    r1 = _process(ft, _payload("close_partial", M, pct=50))
    assert r1["action"] == "force_exit"

    with patch.object(receiver_main, "ft_force_enter") as enter:
        r2 = _process(ft, _payload("open", M, entry_range=[1.0, 1.1], sl=0.9))
    assert r2["action"] == "deduped"
    assert r2["prior_kind"] == "close_partial"
    assert r2["kind"] == "open"
    enter.assert_not_called()
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1


def test_ignored_edit_alert_is_not_suppressed_by_the_first_alert():
    """Review finding: the per-msg_id alert suppression ran after the
    formatter, so the EDIT IGNORED line for an already-alerted msg was dropped."""
    _cfg, _conn, _pos_id = _setup()
    M = 200080
    receiver_main._notified_msg_ids.clear()
    results = iter([
        {"action": "force_exit", "pos_id": 1, "ft": {"status": 200},
         "pct_closed_of_original": 50.0, "pct_open_after": 50.0},
        {"action": "deduped", "pos_id": 1, "kind": "close_full",
         "prior_kind": "close_partial",
         "reason": "msg already acted as close_partial on this position "
                   "(edited message, kind changed to close_full)"},
        {"action": "deduped", "pos_id": 1, "kind": "close_full",
         "prior_kind": "close_partial",
         "reason": "msg already acted as close_partial on this position "
                   "(edited message, kind changed to close_full)"},
    ])
    sent = []

    async def fake_process(_payload):
        return next(results)

    async def fake_notify(_cfg, text, session=None):
        sent.append(text)

    async def deliver(payload):
        await receiver_main.handle_event(payload)
        await asyncio.gather(*receiver_main.app.state.notify_tasks)

    with patch.object(receiver_main, "_process_event", side_effect=fake_process), \
         patch.object(receiver_main, "_notify_telegram", side_effect=fake_notify):
        _run(deliver(_payload("close_partial", M, pct=50)))
        _run(deliver(_payload("close_full", M)))
        _run(deliver(_payload("close_full", M)))  # redelivered edit stays quiet

    assert len(sent) == 2, sent
    assert "CLOSE_PARTIAL" in sent[0]
    assert "EDIT IGNORED" in sent[1]
