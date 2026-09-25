"""Regression tests for #82: orphan 'requested' rows expire in reconcile.

A transport exception on /forceenter leaves the position row 'requested'
with no ft_trade_id. The position reconcile must expire such rows to
'failed' after REQUESTED_ORPHAN_TTL_SEC, but only on a genuine FT response
and only when FT has no trade for the row's (pair, side).
"""
import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402

PAIR = "ARB/USDT:USDT"
# Same SQL as the open-path concurrency gate and /system open_count.
ACTIVE_GATE_SQL = "SELECT COUNT(*) FROM positions WHERE state IN ('open','requested')"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db(monkeypatch):
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    monkeypatch.setenv("KILLERS_DB", tf.name)
    monkeypatch.setenv("KILLERS_ACTIVE_TP_LIMITS", "false")
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    return cfg, conn


def _insert_requested(conn, *, age_sec, msg_id=550001, pair=PAIR, direction="long"):
    born = (datetime.now(timezone.utc) - timedelta(seconds=age_sec)).isoformat()
    cur = conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, stake_usd, leverage, last_event_at) "
        "VALUES (?,?,?,?,'requested',?,?,?,?,?)",
        (2146, pair.split("/")[0], pair, direction, msg_id, born, 20.0, 5.0, born),
    )
    return cur.lastrowid


def _row(conn, pos_id):
    return conn.execute(
        "SELECT state, ft_trade_id, close_reason, close_date FROM positions "
        "WHERE pos_id=?", (pos_id,),
    ).fetchone()


def _reconcile(cfg, conn, ft_open):
    async def fake_open_trades(_cfg, session=None):
        return ft_open

    with patch.object(receiver_main, "ft_open_trades", side_effect=fake_open_trades):
        return _run(receiver_main._reconcile_loop_once(cfg, conn))


STALE = receiver_main.REQUESTED_ORPHAN_TTL_SEC + 60
FRESH = 30


def test_stale_orphan_without_ft_trade_is_failed(db):
    cfg, conn = db
    pos_id = _insert_requested(conn, age_sec=STALE)
    assert conn.execute(ACTIVE_GATE_SQL).fetchone()[0] == 1

    assert _reconcile(cfg, conn, []) == "ok"

    row = _row(conn, pos_id)
    assert row["state"] == "failed"
    assert row["close_reason"] == "requested_expired_no_ft_trade"
    assert row["close_date"] is not None
    assert row["ft_trade_id"] is None
    # No longer counts toward the concurrent-position gate.
    assert conn.execute(ACTIVE_GATE_SQL).fetchone()[0] == 0
    # Nor is it matched by close/update routing.
    pos, reason = receiver_main.find_active_position(conn, 2146, "ARB")
    assert pos is None


def test_stale_orphan_ignores_trades_on_other_pair_or_side(db):
    cfg, conn = db
    pos_id = _insert_requested(conn, age_sec=STALE)
    ft_open = [
        {"trade_id": 7, "pair": PAIR, "is_short": True, "amount": 1.0},
        {"trade_id": 8, "pair": "BTC/USDT:USDT", "is_short": False, "amount": 1.0},
    ]
    _reconcile(cfg, conn, ft_open)
    assert _row(conn, pos_id)["state"] == "failed"


def test_fresh_orphan_is_untouched(db):
    cfg, conn = db
    pos_id = _insert_requested(conn, age_sec=FRESH)

    _reconcile(cfg, conn, [])

    row = _row(conn, pos_id)
    assert row["state"] == "requested"
    assert row["close_reason"] is None
    assert conn.execute(ACTIVE_GATE_SQL).fetchone()[0] == 1


def test_stale_orphan_with_matching_ft_trade_is_linked_not_failed(db):
    """A transport error can hide a /forceenter FT accepted (e.g. a resting
    limit entry, amount=0). FT lists it in /status, so link, never expire."""
    cfg, conn = db
    pos_id = _insert_requested(conn, age_sec=STALE)

    _reconcile(cfg, conn, [{"trade_id": 99, "pair": PAIR, "is_short": False,
                            "amount": 0.0}])

    row = _row(conn, pos_id)
    assert row["state"] == "open"
    assert row["ft_trade_id"] == 99
    assert row["close_reason"] is None


def test_ft_unreachable_expires_nothing(db):
    cfg, conn = db
    pos_id = _insert_requested(conn, age_sec=STALE)

    assert _reconcile(cfg, conn, None) == "skipped"

    row = _row(conn, pos_id)
    assert row["state"] == "requested"
    assert row["close_reason"] is None


def test_unparseable_timestamp_is_never_expired(db):
    cfg, conn = db
    pos_id = _insert_requested(conn, age_sec=STALE)
    conn.execute("UPDATE positions SET last_event_at='garbage', open_date='None' "
                 "WHERE pos_id=?", (pos_id,))

    _reconcile(cfg, conn, [])

    assert _row(conn, pos_id)["state"] == "requested"


def test_forceenter_transport_error_orphan_expires_end_to_end(db, monkeypatch):
    """Drive the real open path with ft_force_enter raising, then reconcile."""
    cfg, conn = db
    monkeypatch.setenv("KILLERS_MIN_NOTIONAL_USD", "0")
    monkeypatch.setenv("KILLERS_MAX_ENTRY_SLIPPAGE_PCT", "3")
    cfg = receiver_main.Config()

    class _State:
        pass

    state = _State()
    state.conn, state.cfg = conn, cfg
    state.ft_session = state.public_session = None
    state.notify_tasks = set()
    saved = getattr(receiver_main.app, "state", None)
    receiver_main.app.state = state
    try:
        msg = {"id": 550099, "date": "2026-05-31T23:17:00+00:00",
               "text": ("\U0001F4CDSIGNAL ID: #2146\U0001F4CD\n"
                        "COIN: $ARB/USDT (2-5x)\nDirection: LONG\n"
                        "ENTRY: 0.099 - 0.10\n\nTARGETS: 0.105 - 0.11\n\n"
                        "STOP LOSS: 0.09\n")}
        classification = {
            "id": 550099, "kind": "open", "signal_id": 2146, "symbol": "ARB",
            "direction": "long", "entry": None, "entry_range": [0.099, 0.10],
            "sl": 0.09, "tp": None, "pct": None, "applies_to": None,
            "confidence": 1.0, "notes": "fast-path",
        }
        payload = receiver_main.EventPayload(msg=msg, classification=classification)

        async def fake_mark(*a, **k):
            return 0.0995

        async def boom(*a, **k):
            raise asyncio.TimeoutError("forceenter transport failure")

        with patch.object(receiver_main, "get_binance_mark_price", side_effect=fake_mark), \
             patch.object(receiver_main, "ft_force_enter", side_effect=boom):
            with pytest.raises(asyncio.TimeoutError):
                _run(receiver_main._process_event(payload))
    finally:
        receiver_main.app.state = saved

    row = conn.execute("SELECT pos_id, state FROM positions WHERE open_msg_id=550099"
                       ).fetchone()
    assert row["state"] == "requested"
    pos_id = row["pos_id"]

    # Within the TTL nothing happens.
    _reconcile(cfg, conn, [])
    assert _row(conn, pos_id)["state"] == "requested"

    # Past the TTL it is expired.
    old = (datetime.now(timezone.utc) - timedelta(seconds=STALE)).isoformat()
    conn.execute("UPDATE positions SET last_event_at=? WHERE pos_id=?", (old, pos_id))
    _reconcile(cfg, conn, [])
    assert _row(conn, pos_id)["state"] == "failed"
    assert conn.execute(ACTIVE_GATE_SQL).fetchone()[0] == 0
