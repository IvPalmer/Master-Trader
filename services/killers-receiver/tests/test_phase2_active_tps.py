"""Phase 2 tests: active TP-limit-order placement + reconciliation.

Tests the pure-function helpers (_extract_new_exit_order_id,
_find_matching_order) and one integration test that drives
_place_target_limits + _reconcile_target_orders against a fake FT.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402
from app.main import (  # noqa: E402
    _extract_new_exit_order_id, _find_matching_order,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── _extract_new_exit_order_id ────────────────────────────────────────────


def test_extract_exit_order_id_matches_price_amount():
    body = {
        "trade_id": 42,
        "orders": [
            {"order_id": "buy-1", "order_type": "market",
             "is_open": False, "ft_order_side": "buy",
             "safe_price": 60.0, "amount": 1.0},
            {"order_id": "exit-tp1", "order_type": "limit",
             "is_open": True, "ft_order_side": "sell",
             "safe_price": 65.0, "amount": 0.25},
        ],
    }
    assert _extract_new_exit_order_id(body, target_price=65.0,
                                       expected_amount=0.25) == "exit-tp1"


def test_extract_returns_none_when_no_match():
    body = {"orders": [
        {"order_id": "x", "order_type": "limit", "is_open": True,
         "safe_price": 100.0, "amount": 1.0},
    ]}
    assert _extract_new_exit_order_id(body, 65.0, 0.25) is None


def test_extract_skips_closed_orders():
    body = {"orders": [
        {"order_id": "old", "order_type": "limit", "is_open": False,
         "safe_price": 65.0, "amount": 0.25},
        {"order_id": "live", "order_type": "limit", "is_open": True,
         "safe_price": 65.0, "amount": 0.25},
    ]}
    assert _extract_new_exit_order_id(body, 65.0, 0.25) == "live"


def test_extract_skips_market_orders():
    body = {"orders": [
        {"order_id": "mkt", "order_type": "market", "is_open": True,
         "safe_price": 65.0, "amount": 0.25},
    ]}
    assert _extract_new_exit_order_id(body, 65.0, 0.25) is None


# ── _find_matching_order ──────────────────────────────────────────────────


def test_find_by_order_id_wins():
    orders = [
        {"order_id": "abc", "safe_price": 70.0, "amount": 0.3},
        {"order_id": "target-1", "safe_price": 65.0, "amount": 0.25},
    ]
    found = _find_matching_order(orders, "target-1", 65.0, 0.25)
    assert found is not None and found["order_id"] == "target-1"


def test_find_falls_back_to_price_amount():
    """If ft_order_id is None, match by limit + price + amount."""
    orders = [
        {"order_id": "a", "order_type": "limit",
         "safe_price": 65.0, "amount": 0.25},
    ]
    found = _find_matching_order(orders, None, 65.0, 0.25)
    assert found is not None and found["order_id"] == "a"


def test_find_returns_none_on_no_match():
    orders = [{"order_id": "x", "safe_price": 999.0, "amount": 99.0}]
    found = _find_matching_order(orders, "nonexistent", 65.0, 0.25)
    assert found is None


# ── Integration: place limits → reconciler advances state ─────────────────


def _setup_db():
    import os
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "true"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    # Make a position to attach targets to
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, stake_usd, leverage, ft_trade_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (9999, "HYPE", "HYPE/USDT:USDT", "long", "open",
         888888, "2026-05-27T20:00:00+00:00", 20.0, 5.0, 42),
    )
    pos_id = conn.execute("SELECT pos_id FROM positions WHERE open_msg_id=888888"
                          ).fetchone()[0]
    return cfg, conn, pos_id


def test_place_target_limits_persists_rows():
    cfg, conn, pos_id = _setup_db()

    posted_orders = []

    async def fake_force_exit_limit(_cfg, trade_id, amount, price, session=None):
        order_id = f"sim-tp-{price}"
        posted_orders.append((trade_id, amount, price, order_id))
        return {"status": 200, "body": json.dumps({
            "trade_id": trade_id,
            "orders": [{
                "order_id": order_id, "order_type": "limit",
                "is_open": True, "ft_order_side": "sell",
                "safe_price": price, "amount": amount,
            }],
        })}

    with patch.object(receiver_main, "ft_force_exit_limit",
                      side_effect=fake_force_exit_limit):
        placed = _run(receiver_main._place_target_limits(
            cfg, conn, pos_id, ft_trade_id=42,
            targets=[59.5, 62.0, 65.0], slice_amount=0.5,
        ))

    assert len(placed) == 3
    assert all(p["state"] == "active" for p in placed)
    rows = conn.execute("SELECT * FROM target_orders WHERE pos_id=? ORDER BY idx",
                        (pos_id,)).fetchall()
    assert len(rows) == 3
    assert all(r["state"] == "active" for r in rows)
    assert rows[0]["price"] == 59.5
    assert rows[1]["price"] == 62.0
    assert rows[2]["price"] == 65.0
    assert all(r["ft_order_id"] is not None for r in rows)


def test_place_marks_rejected_on_ft_error():
    cfg, conn, pos_id = _setup_db()

    async def fake_force_exit_limit(*args, **kwargs):
        return {"status": 400, "body": json.dumps({"error": "min notional"})}

    with patch.object(receiver_main, "ft_force_exit_limit",
                      side_effect=fake_force_exit_limit):
        placed = _run(receiver_main._place_target_limits(
            cfg, conn, pos_id, ft_trade_id=42,
            targets=[59.5], slice_amount=0.5,
        ))

    assert placed[0]["state"] == "rejected"
    row = conn.execute(
        "SELECT * FROM target_orders WHERE pos_id=?", (pos_id,)
    ).fetchone()
    assert row["state"] == "rejected"
    assert "min notional" in (row["notes"] or "")


def test_reconciler_advances_filled_state():
    """Active target with matching FT order showing status=closed + filled>0
    transitions to 'filled'."""
    cfg, conn, pos_id = _setup_db()
    # Place a target_orders row in 'active' state manually
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (pos_id, 0, 65.0, 0.5, "sim-tp-65", "2026-05-27T20:00:00+00:00"),
    )

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {
            "trade_id": trade_id,
            "orders": [{
                "order_id": "sim-tp-65", "order_type": "limit",
                "is_open": False, "status": "closed",
                "filled": 0.5, "remaining": 0.0,
                "safe_price": 65.0, "amount": 0.5,
            }],
        }

    with patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        summary = _run(receiver_main._reconcile_target_orders(cfg, conn))

    assert summary["filled"] == 1
    row = conn.execute("SELECT * FROM target_orders WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "filled"
    assert row["filled_at"] is not None


def test_reconciler_marks_cancelled_status():
    cfg, conn, pos_id = _setup_db()
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (pos_id, 0, 65.0, 0.5, "sim-tp-65", "2026-05-27T20:00:00+00:00"),
    )

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {"orders": [{
            "order_id": "sim-tp-65", "order_type": "limit",
            "is_open": False, "status": "canceled",
            "filled": 0.0, "amount": 0.5, "safe_price": 65.0,
        }]}

    with patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        summary = _run(receiver_main._reconcile_target_orders(cfg, conn))

    assert summary["cancelled"] == 1
    row = conn.execute("SELECT * FROM target_orders WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "cancelled"


def test_reconciler_leaves_active_when_still_open():
    cfg, conn, pos_id = _setup_db()
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (pos_id, 0, 65.0, 0.5, "sim-tp-65", "2026-05-27T20:00:00+00:00"),
    )

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {"orders": [{
            "order_id": "sim-tp-65", "order_type": "limit",
            "is_open": True, "status": "open",
            "filled": 0.0, "amount": 0.5, "safe_price": 65.0,
        }]}

    with patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        summary = _run(receiver_main._reconcile_target_orders(cfg, conn))

    assert summary["still_active"] == 1
    assert summary["filled"] == 0
    row = conn.execute("SELECT * FROM target_orders WHERE pos_id=?",
                       (pos_id,)).fetchone()
    assert row["state"] == "active"
    assert row["last_check_at"] is not None


def test_reconciler_groups_by_trade_id_one_fetch():
    """Multiple targets on the same trade should produce ONE /trade call."""
    cfg, conn, pos_id = _setup_db()
    for idx, price in enumerate([59.5, 62.0, 65.0]):
        conn.execute(
            "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (pos_id, idx, price, 0.5, f"sim-tp-{price}",
             "2026-05-27T20:00:00+00:00"),
        )
    call_count = {"n": 0}

    async def fake_get_trade(_cfg, trade_id, session=None):
        call_count["n"] += 1
        return {"orders": [
            {"order_id": "sim-tp-59.5", "order_type": "limit",
             "is_open": True, "status": "open", "filled": 0,
             "amount": 0.5, "safe_price": 59.5},
            {"order_id": "sim-tp-62.0", "order_type": "limit",
             "is_open": True, "status": "open", "filled": 0,
             "amount": 0.5, "safe_price": 62.0},
            {"order_id": "sim-tp-65.0", "order_type": "limit",
             "is_open": True, "status": "open", "filled": 0,
             "amount": 0.5, "safe_price": 65.0},
        ]}

    with patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        _run(receiver_main._reconcile_target_orders(cfg, conn))

    assert call_count["n"] == 1  # ONE fetch for the trade, served all 3 targets


# ── Schema migration ──────────────────────────────────────────────────────


def test_close_partial_audit_only_when_active_tp_rows_exist():
    """Phase 2 + close_partial → MUST NOT call ft_force_exit, return audit_only."""
    import os
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "true"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    # Populate a position + an active target_orders row
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, ft_trade_id, pct_open) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (1001, "HYPE", "HYPE/USDT:USDT", "long", "open",
         777001, "2026-05-27T20:00:00+00:00", 50, 100),
    )
    pos_id = conn.execute("SELECT pos_id FROM positions WHERE open_msg_id=777001"
                          ).fetchone()[0]
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (pos_id, 0, 65.0, 0.5, "tp-active-1", "2026-05-27T20:00:00+00:00"),
    )

    class _FakeState:
        def __init__(self, c, cf):
            self.conn = c; self.cfg = cf; self.ft_session = None
            self.public_session = None; self.notify_tasks = set()
    receiver_main.app.state = _FakeState(conn, cfg)

    payload = receiver_main.EventPayload(
        msg={"id": 777002, "date": "2026-05-27T20:30:00+00:00",
             "text": "Target 1: 65.00✅"},
        classification={"kind": "close_partial", "signal_id": 1001,
                         "symbol": "HYPE", "direction": "long", "pct": 50},
    )

    # If ft_force_exit gets called, fail the test
    async def fail_force_exit(*args, **kwargs):
        raise AssertionError("ft_force_exit MUST NOT be called in audit-only path")

    async def quiet_reconcile(*args, **kwargs):
        return {"checked": 0, "filled": 0, "cancelled": 0, "still_active": 0}

    with patch.object(receiver_main, "ft_force_exit",
                      side_effect=fail_force_exit), \
         patch.object(receiver_main, "_reconcile_target_orders",
                      side_effect=quiet_reconcile):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "audit_only"
    assert result["reason"] == "active_tp_limits"
    assert result["phase2_rows"] >= 1
    # Event row written with audit-only response
    row = conn.execute(
        "SELECT response FROM events WHERE pos_id=? AND msg_id=? AND kind='close_partial'",
        (pos_id, 777002),
    ).fetchone()
    assert "audit_only" in row["response"]


def test_close_partial_falls_through_to_market_when_no_phase2_rows():
    """Phase 2 ON but no active TP rows for the position → close_partial
    still does the legacy pct-of-original market exit."""
    import os
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "true"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, ft_trade_id, pct_open) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (1002, "BTC", "BTC/USDT:USDT", "long", "open",
         777010, "2026-05-27T20:00:00+00:00", 60, 100),
    )
    pos_id = conn.execute("SELECT pos_id FROM positions WHERE open_msg_id=777010"
                          ).fetchone()[0]

    class _FakeState:
        def __init__(self, c, cf):
            self.conn = c; self.cfg = cf; self.ft_session = None
            self.public_session = None; self.notify_tasks = set()
    receiver_main.app.state = _FakeState(conn, cfg)

    payload = receiver_main.EventPayload(
        msg={"id": 777011, "date": "2026-05-27T20:30:00+00:00",
             "text": "Target 1: hit"},
        classification={"kind": "close_partial", "signal_id": 1002,
                         "symbol": "BTC", "direction": "long", "pct": 50},
    )

    called = {"force_exit": False}

    async def fake_force_exit(*args, **kwargs):
        called["force_exit"] = True
        return {"status": 200, "body": '{"trade_id":60}'}

    async def quiet_reconcile(*args, **kwargs):
        return {"checked": 0, "filled": 0, "cancelled": 0, "still_active": 0}

    with patch.object(receiver_main, "ft_force_exit",
                      side_effect=fake_force_exit), \
         patch.object(receiver_main, "_reconcile_target_orders",
                      side_effect=quiet_reconcile):
        result = _run(receiver_main._process_event(payload))

    # No Phase 2 rows → fall through to legacy partial path
    assert called["force_exit"], "ft_force_exit should be called when no phase2 rows"
    assert result["action"] == "force_exit"


# ── _extract_new_exit_order_id newest preference ──────────────────────────


def test_extract_prefers_newest_timestamp():
    body = {"orders": [
        {"order_id": "old", "order_type": "limit", "is_open": True,
         "safe_price": 65.0, "amount": 0.25,
         "order_timestamp": 1_000_000_000},
        {"order_id": "new", "order_type": "limit", "is_open": True,
         "safe_price": 65.0, "amount": 0.25,
         "order_timestamp": 2_000_000_000},
    ]}
    assert _extract_new_exit_order_id(body, 65.0, 0.25) == "new"


def test_find_matching_prefers_newest_timestamp_in_fallback():
    orders = [
        {"order_id": "stale", "order_type": "limit",
         "safe_price": 65.0, "amount": 0.25,
         "order_timestamp": 100_000},
        {"order_id": "fresh", "order_type": "limit",
         "safe_price": 65.0, "amount": 0.25,
         "order_timestamp": 999_999},
    ]
    found = _find_matching_order(orders, ft_order_id=None,
                                  target_price=65.0, expected_amount=0.25)
    assert found is not None and found["order_id"] == "fresh"


def test_find_matching_ignores_non_limit_in_fallback():
    orders = [
        {"order_id": "mkt-match", "order_type": "market",
         "safe_price": 65.0, "amount": 0.25},
        {"order_id": "limit-match", "order_type": "limit",
         "safe_price": 65.0, "amount": 0.25},
    ]
    found = _find_matching_order(orders, ft_order_id=None,
                                  target_price=65.0, expected_amount=0.25)
    assert found is not None and found["order_id"] == "limit-match"


def test_target_orders_table_created_on_init():
    cfg, conn, pos_id = _setup_db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(target_orders)")]
    expected = {"target_id", "pos_id", "idx", "price", "amount", "state",
                "ft_order_id", "placed_at", "filled_at", "last_check_at", "notes"}
    assert expected.issubset(set(cols)), f"missing cols: {expected - set(cols)}"


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
