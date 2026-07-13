"""signal_update classification+execution tests (prereg
killers-fill-realism-2026-07 followup).

Covers the new `signal_update` kind in _process_event:
  - close_full_now → full market close, close_reason=signal_update_close
  - close_at_target_1 with mark AT/BEYOND TP1 → market close now
  - close_at_target_1 with mark BELOW TP1 → cancel ladder + post consolidated
    full-remaining LIMIT at TP1
  - no active position → skipped
  - dedupe: same (pos_id, msg_id, kind) claim fires FT only once
  - tighten_sl / other → loud logged no-op (no FT call)

Mocks the FT REST layer the same way the phase-2 endpoint tests do
(patch.object on receiver_main.<helper>).
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


def _setup(symbol="KITE", pair="KITE/USDT:USDT", direction="long",
           ft_trade_id=42, signal_id=2154, open_msg_id=100000,
           targets_remaining=None):
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "true"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, stake_usd, leverage, ft_trade_id, pct_open, "
        " targets_remaining) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (signal_id, symbol, pair, direction, "open", open_msg_id,
         "2026-07-01T20:00:00+00:00", 20.0, 5.0, ft_trade_id, 100,
         json.dumps(targets_remaining) if targets_remaining is not None else None),
    )
    pos_id = conn.execute(
        "SELECT pos_id FROM positions WHERE open_msg_id=?", (open_msg_id,)
    ).fetchone()[0]
    receiver_main.app.state = _FakeState(conn, cfg)
    return cfg, conn, pos_id


def _payload(instruction, symbol="KITE", signal_id=2154, msg_id=100001,
             raw="We are adjusting the setup to close at first target."):
    return receiver_main.EventPayload(
        msg={"id": msg_id, "date": "2026-07-01T20:30:00+00:00",
             "text": "signal update text"},
        classification={"kind": "signal_update", "signal_id": signal_id,
                        "symbol": symbol, "instruction": instruction,
                        "raw_instruction": raw},
    )


# ── close_full_now ─────────────────────────────────────────────────────────


def test_close_full_now_market_closes_position():
    cfg, conn, pos_id = _setup()

    called = {"force_exit_pct": "unset"}

    async def fake_force_exit(_cfg, trade_id, pct=None, session=None):
        called["force_exit_pct"] = pct
        return {"status": 200, "body": '{"result":"closed"}'}

    with patch.object(receiver_main, "ft_force_exit",
                      side_effect=fake_force_exit):
        result = _run(receiver_main._process_event(
            _payload("close_full_now")))

    assert result["action"] == "force_exit"
    assert result["close_reason"] == "signal_update_close"
    # pct=None → full close
    assert called["force_exit_pct"] is None
    row = conn.execute(
        "SELECT state, pct_open, close_reason FROM positions WHERE pos_id=?",
        (pos_id,)).fetchone()
    assert row["state"] == "closed"
    assert row["pct_open"] == 0
    assert row["close_reason"] == "signal_update_close"


# ── close_at_target_1: mark AT/BEYOND TP1 → market close ────────────────────


def test_close_at_target_1_market_when_mark_beyond_tp1():
    cfg, conn, pos_id = _setup()
    # Seed a pending TP ladder rung at 100 (idx 0) — TP1.
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 0, 100.0, 1.0, 'pending')", (pos_id,))

    forced = {"called": False}
    posted = {"called": False}
    cancelled = {"called": False}

    async def fake_get_trade(_cfg, trade_id, session=None):
        # mark 105 is >= 100 * 0.999 → at/beyond TP1 (long)
        return {"trade_id": trade_id, "is_short": False,
                "current_rate": 105.0, "amount": 1.0, "orders": []}

    async def fake_force_exit(_cfg, trade_id, pct=None, session=None):
        forced["called"] = True
        return {"status": 200, "body": '{"result":"closed"}'}

    async def fake_limit(*a, **k):
        posted["called"] = True
        return {"status": 200, "body": '{"result":"ok"}'}

    async def fake_cancel(*a, **k):
        cancelled["called"] = True
        return {"status": 200, "body": "ok"}

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_force_exit", side_effect=fake_force_exit), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fake_limit), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel):
        result = _run(receiver_main._process_event(
            _payload("close_at_target_1")))

    assert result["action"] == "force_exit"
    assert result["path"] == "market_at_target"
    assert forced["called"] is True
    assert posted["called"] is False, "must NOT post a limit when already at TP1"
    assert cancelled["called"] is False
    row = conn.execute("SELECT state FROM positions WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "closed"


# ── close_at_target_1: mark BELOW TP1 → cancel ladder + post limit ──────────


def test_close_at_target_1_posts_limit_when_mark_below_tp1():
    cfg, conn, pos_id = _setup()
    # Pending ladder rung at TP1=100 plus a higher rung that must be retired.
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id) "
        "VALUES (?, 0, 100.0, 1.0, 'active', 'old-tp1')", (pos_id,))
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 1, 120.0, 1.0, 'pending')", (pos_id,))

    cancelled = {"called": False}
    posted = {"amount": None, "price": None}
    get_trade_calls = {"n": 0}

    async def fake_get_trade(_cfg, trade_id, session=None):
        get_trade_calls["n"] += 1
        if get_trade_calls["n"] == 1:
            # mark 90 < TP1 100 → below target; full remaining amount 2.0
            return {"trade_id": trade_id, "is_short": False,
                    "current_rate": 90.0, "amount": 2.0, "orders": []}
        # After the limit post — discover the new consolidated exit order.
        return {"trade_id": trade_id, "is_short": False, "orders": [{
            "order_id": "consolidated-tp1", "order_type": "limit",
            "is_open": True, "ft_order_side": "sell",
            "safe_price": 100.0, "amount": 2.0,
            "order_timestamp": 1_700_000_000_000,
        }]}

    async def fake_cancel(_cfg, trade_id, session=None):
        cancelled["called"] = True
        return {"status": 200, "body": "cancelled"}

    async def fake_limit(_cfg, trade_id, amount, price, session=None):
        posted["amount"] = amount
        posted["price"] = price
        return {"status": 200, "body": '{"result":"ok"}'}

    async def fake_force_exit(*a, **k):
        raise AssertionError("must NOT market-close when mark below TP1")

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fake_limit), \
         patch.object(receiver_main, "ft_force_exit", side_effect=fake_force_exit):
        result = _run(receiver_main._process_event(
            _payload("close_at_target_1")))

    assert result["action"] == "limit_posted"
    assert result["path"] == "limit_at_tp1"
    assert cancelled["called"] is True, "must cancel resting ladder first"
    assert posted["amount"] == 2.0, "must post FULL remaining base amount"
    assert posted["price"] == 100.0
    assert result["ft_order_id"] == "consolidated-tp1"

    # Position stays OPEN (limit will fill later at TP1).
    row = conn.execute("SELECT state FROM positions WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "open"

    # Old ladder rows retired; a new 'active' consolidated row exists — and
    # NO 'pending' rung remains for the cascade to re-arm over it.
    states = [r["state"] for r in conn.execute(
        "SELECT state FROM target_orders WHERE pos_id=? ORDER BY idx", (pos_id,))]
    assert "pending" not in states, "no pending rung may survive (cascade guard)"
    active_rows = conn.execute(
        "SELECT price, amount, ft_order_id, notes FROM target_orders "
        "WHERE pos_id=? AND state='active'", (pos_id,)).fetchall()
    assert len(active_rows) == 1
    assert active_rows[0]["price"] == 100.0
    assert active_rows[0]["ft_order_id"] == "consolidated-tp1"
    assert "signal_update" in (active_rows[0]["notes"] or "")


def test_close_at_target_1_uses_targets_remaining_when_no_ladder_rows():
    """No target_orders rows (phase-2 off) → TP1 resolved from
    positions.targets_remaining."""
    cfg, conn, pos_id = _setup(targets_remaining=[0.055, 0.060, 0.066])

    posted = {"price": None}

    async def fake_get_trade(_cfg, trade_id, session=None):
        # mark below TP1 (0.055) → limit path
        return {"trade_id": trade_id, "is_short": False,
                "current_rate": 0.050, "amount": 500.0, "orders": []}

    async def fake_cancel(*a, **k):
        return {"status": 200, "body": "ok"}

    async def fake_limit(_cfg, trade_id, amount, price, session=None):
        posted["price"] = price
        return {"status": 200, "body": '{"result":"ok"}'}

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fake_limit):
        result = _run(receiver_main._process_event(
            _payload("close_at_target_1")))

    assert result["action"] == "limit_posted"
    assert posted["price"] == 0.055, "TP1 taken from targets_remaining[0]"


# ── close_at_target_1: limit post fails → retry → market-close fallback ─────


def test_close_at_target_1_limit_fails_retry_then_market_close():
    """cancel=200, both limit posts=500 → retry once, then FULL market close
    and the event finalizes 'limit_failed_market_closed' (position covered)."""
    cfg, conn, pos_id = _setup()
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 0, 100.0, 2.0, 'pending')", (pos_id,))

    limit_calls = {"n": 0}
    market = {"called": False}

    async def fake_get_trade(_cfg, trade_id, session=None):
        # mark 90 < TP1 100 → below target; full remaining amount 2.0
        return {"trade_id": trade_id, "is_short": False,
                "current_rate": 90.0, "amount": 2.0, "orders": []}

    async def fake_cancel(*a, **k):
        return {"status": 200, "body": "cancelled"}

    async def fake_limit(*a, **k):
        limit_calls["n"] += 1
        return {"status": 500, "body": '{"error":"exchange rejected"}'}

    async def fake_force_exit(_cfg, trade_id, pct=None, session=None):
        market["called"] = True
        assert pct is None, "market-close fallback must close FULL remaining"
        return {"status": 200, "body": '{"result":"closed"}'}

    # Patch out the 2s retry sleep so the test is instant.
    async def fake_sleep(_s):
        return None

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fake_limit), \
         patch.object(receiver_main, "ft_force_exit", side_effect=fake_force_exit), \
         patch.object(receiver_main.asyncio, "sleep", side_effect=fake_sleep):
        result = _run(receiver_main._process_event(
            _payload("close_at_target_1")))

    assert limit_calls["n"] == 2, "limit must be retried exactly once (2 posts)"
    assert market["called"] is True, "must fall back to market close"
    assert result["action"] == "limit_failed_market_closed"

    # Position closed at market (covered), not left open/uncovered.
    row = conn.execute(
        "SELECT state, close_reason FROM positions WHERE pos_id=?",
        (pos_id,)).fetchone()
    assert row["state"] == "closed"
    assert row["close_reason"] == "signal_update_close"

    # Event finalized to the terminal status — never left 'pending'.
    ev = conn.execute(
        "SELECT response FROM events WHERE pos_id=? AND kind='signal_update'",
        (pos_id,)).fetchone()
    assert json.loads(ev["response"])["status"] == "limit_failed_market_closed"


def test_close_at_target_1_all_fail_uncovered_alert():
    """cancel=200, both limits=500, market close ALSO 500 →
    UNCOVERED_POSITION_ALERT, position stays open, event still terminal."""
    cfg, conn, pos_id = _setup()
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 0, 100.0, 2.0, 'pending')", (pos_id,))

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {"trade_id": trade_id, "is_short": False,
                "current_rate": 90.0, "amount": 2.0, "orders": []}

    async def fake_cancel(*a, **k):
        return {"status": 200, "body": "cancelled"}

    async def fake_limit(*a, **k):
        return {"status": 500, "body": '{"error":"rejected"}'}

    async def fake_force_exit(_cfg, trade_id, pct=None, session=None):
        return {"status": 500, "body": '{"error":"exchange down"}'}

    async def fake_sleep(_s):
        return None

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fake_limit), \
         patch.object(receiver_main, "ft_force_exit", side_effect=fake_force_exit), \
         patch.object(receiver_main.asyncio, "sleep", side_effect=fake_sleep):
        result = _run(receiver_main._process_event(
            _payload("close_at_target_1")))

    assert result["action"] == "UNCOVERED_POSITION_ALERT"
    # Market close failed → position NOT mutated to closed (honest state).
    row = conn.execute("SELECT state FROM positions WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "open"
    # Event MUST be terminal (never 'pending') even in the all-fail case.
    ev = conn.execute(
        "SELECT response FROM events WHERE pos_id=? AND kind='signal_update'",
        (pos_id,)).fetchone()
    assert json.loads(ev["response"])["status"] == "UNCOVERED_POSITION_ALERT"


def test_close_at_target_1_no_pending_event_after_cancel():
    """P1a assertion: once the cancel has executed, NO signal_update path may
    leave the event 'pending'. Exercise the post-cancel limit-fail branch and
    assert the persisted event status is terminal (not pending/deferred)."""
    cfg, conn, pos_id = _setup()
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 0, 100.0, 2.0, 'pending')", (pos_id,))

    cancel_seen = {"called": False}

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {"trade_id": trade_id, "is_short": False,
                "current_rate": 90.0, "amount": 2.0, "orders": []}

    async def fake_cancel(*a, **k):
        cancel_seen["called"] = True
        return {"status": 200, "body": "cancelled"}

    async def fake_limit(*a, **k):
        return {"status": 503, "body": '{"error":"unavailable"}'}

    async def fake_force_exit(_cfg, trade_id, pct=None, session=None):
        return {"status": 200, "body": '{"result":"closed"}'}

    async def fake_sleep(_s):
        return None

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fake_limit), \
         patch.object(receiver_main, "ft_force_exit", side_effect=fake_force_exit), \
         patch.object(receiver_main.asyncio, "sleep", side_effect=fake_sleep):
        _run(receiver_main._process_event(_payload("close_at_target_1")))

    assert cancel_seen["called"] is True, "cancel must have executed"
    ev = conn.execute(
        "SELECT response FROM events WHERE pos_id=? AND kind='signal_update'",
        (pos_id,)).fetchone()
    status = json.loads(ev["response"])["status"]
    assert status not in ("pending", "deferred"), (
        f"event left non-terminal after cancel: {status}")


def test_close_at_target_1_limit_raises_still_terminal():
    """P1a hardening: if the limit POST helper RAISES (network/timeout) after
    the cancel fired, the exception must NOT escape and leave the event
    'pending' — it is coerced to a failure → market-close fallback."""
    cfg, conn, pos_id = _setup()
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 0, 100.0, 2.0, 'pending')", (pos_id,))

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {"trade_id": trade_id, "is_short": False,
                "current_rate": 90.0, "amount": 2.0, "orders": []}

    async def fake_cancel(*a, **k):
        return {"status": 200, "body": "cancelled"}

    async def raising_limit(*a, **k):
        raise RuntimeError("connection reset")

    async def fake_force_exit(_cfg, trade_id, pct=None, session=None):
        return {"status": 200, "body": '{"result":"closed"}'}

    async def fake_sleep(_s):
        return None

    with patch.object(receiver_main, "ft_get_trade", side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fake_cancel), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=raising_limit), \
         patch.object(receiver_main, "ft_force_exit", side_effect=fake_force_exit), \
         patch.object(receiver_main.asyncio, "sleep", side_effect=fake_sleep):
        result = _run(receiver_main._process_event(
            _payload("close_at_target_1")))

    assert result["action"] == "limit_failed_market_closed"
    ev = conn.execute(
        "SELECT response FROM events WHERE pos_id=? AND kind='signal_update'",
        (pos_id,)).fetchone()
    assert json.loads(ev["response"])["status"] == "limit_failed_market_closed"


# ── no active position ──────────────────────────────────────────────────────


def test_no_active_position_skips():
    cfg, conn, pos_id = _setup(symbol="KITE", signal_id=2154)

    async def fail_any(*a, **k):
        raise AssertionError("no FT call when no active position")

    # Different signal_id/symbol than the open position → no match.
    with patch.object(receiver_main, "ft_force_exit", side_effect=fail_any):
        result = _run(receiver_main._process_event(
            _payload("close_full_now", symbol="DOGE", signal_id=9999)))

    assert result["action"] == "skipped"
    assert result["reason"].startswith("no_active_position")


# ── dedupe ──────────────────────────────────────────────────────────────────


def test_dedupe_second_identical_event_skipped():
    cfg, conn, pos_id = _setup()
    # Pre-seed the claim row for (pos_id, msg_id=100001, kind=signal_update).
    conn.execute(
        "INSERT INTO events (pos_id, msg_id, event_at, kind, payload, response) "
        "VALUES (?, ?, ?, 'signal_update', '{}', ?)",
        (pos_id, 100001, "2026-07-01T20:30:00+00:00",
         json.dumps({"status": "pending"})))

    async def fail_force_exit(*a, **k):
        raise AssertionError("dedupe must prevent a second FT close")

    with patch.object(receiver_main, "ft_force_exit",
                      side_effect=fail_force_exit):
        result = _run(receiver_main._process_event(
            _payload("close_full_now", msg_id=100001)))

    assert result["action"] == "deduped"
    assert result["pos_id"] == pos_id


# ── tighten_sl / other no-op ────────────────────────────────────────────────


def test_tighten_sl_logged_no_op():
    cfg, conn, pos_id = _setup()

    async def fail_any(*a, **k):
        raise AssertionError("tighten_sl must not touch FT")

    with patch.object(receiver_main, "ft_force_exit", side_effect=fail_any), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fail_any), \
         patch.object(receiver_main, "ft_cancel_open_order", side_effect=fail_any):
        result = _run(receiver_main._process_event(
            _payload("tighten_sl", raw="move SL to breakeven")))

    assert result["action"] == "logged"
    assert result["reason"] == "no executable primitive"
    assert result["instruction"] == "tighten_sl"
    row = conn.execute("SELECT state FROM positions WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "open", "position untouched"


def test_other_instruction_logged_no_op():
    cfg, conn, pos_id = _setup()

    async def fail_any(*a, **k):
        raise AssertionError("'other' must not touch FT")

    with patch.object(receiver_main, "ft_force_exit", side_effect=fail_any):
        result = _run(receiver_main._process_event(
            _payload("other", raw="hold and watch price action")))

    assert result["action"] == "logged"
    assert result["instruction"] == "other"


if __name__ == "__main__":
    funcs = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS  {f.__name__}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"FAIL  {f.__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
