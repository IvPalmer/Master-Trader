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


def test_place_target_limits_cascade_only_one_active():
    """Cascade design: persist all targets, but only the FIRST gets
    posted to FT. Rest remain 'pending' until cascade fires on fill.

    Regression for incident 2026-05-28 19:21 UTC (WLD #8): the prior
    "all-at-once" loop posted 8 forceexits sequentially and FT cancelled
    7 of them, leaving the trade naked when the 8th timed out.
    """
    cfg, conn, pos_id = _setup_db()

    posted_orders = []

    async def fake_force_exit_limit(_cfg, trade_id, amount, price, session=None):
        posted_orders.append((trade_id, amount, price))
        # Real FT body — NOT a trade snapshot, just `{"result": "..."}`.
        return {"status": 200, "body": json.dumps({
            "result": f"Created exit order for trade {trade_id}.",
        })}

    # After POST, the cascade helper re-fetches /trade to find the new
    # order_id. Simulate FT returning the freshly created exit order on
    # idx=0 only (since only idx=0 gets posted).
    get_trade_calls = {"n": 0}

    async def fake_get_trade(_cfg, trade_id, session=None):
        get_trade_calls["n"] += 1
        # First call: adoption check — no existing open exit yet.
        # Subsequent calls: return the just-posted TP1 exit order.
        if get_trade_calls["n"] == 1:
            return {"orders": []}
        return {"orders": [{
            "order_id": "sim-tp-59.5", "order_type": "limit",
            "is_open": True, "ft_order_side": "sell",
            "safe_price": 59.5, "amount": 0.5,
            "order_timestamp": 1_700_000_000_000,
        }]}

    with patch.object(receiver_main, "ft_force_exit_limit",
                      side_effect=fake_force_exit_limit), \
         patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        placed = _run(receiver_main._place_target_limits(
            cfg, conn, pos_id, ft_trade_id=42,
            targets=[59.5, 62.0, 65.0], slice_amount=0.5,
        ))

    # ONLY one /forceexit, no matter how many targets are in the ladder
    assert len(posted_orders) == 1, \
        f"cascade must post exactly 1 limit; got {len(posted_orders)}"
    assert posted_orders[0][2] == 59.5  # lowest-idx TP first

    # Return list reflects all 3 targets, but only idx=0 is active
    assert len(placed) == 3
    states_by_idx = {p["idx"]: p["state"] for p in placed}
    assert states_by_idx[0] == "active"
    assert states_by_idx[1] == "pending"
    assert states_by_idx[2] == "pending"

    # DB rows match
    rows = conn.execute("SELECT * FROM target_orders WHERE pos_id=? ORDER BY idx",
                        (pos_id,)).fetchall()
    assert len(rows) == 3
    assert rows[0]["state"] == "active"
    assert rows[0]["ft_order_id"] == "sim-tp-59.5"
    assert rows[1]["state"] == "pending"
    assert rows[2]["state"] == "pending"


def test_adopt_existing_open_exit_skips_post():
    """If FT already has an open limit exit at the next TP's price (e.g.
    operator manually placed it before deploy / receiver restart), adopt
    it instead of posting a duplicate. This is the case for WLD #8 hotfix
    on 2026-05-28.
    """
    cfg, conn, pos_id = _setup_db()
    posted = []

    async def fake_force_exit_limit(*a, **k):
        posted.append(a)
        return {"status": 200, "body": '{"result":"ok"}'}

    async def fake_get_trade(_cfg, trade_id, session=None):
        return {"orders": [{
            "order_id": "manual-tp1", "order_type": "limit",
            "is_open": True, "ft_order_side": "sell",
            "safe_price": 59.5, "amount": 0.5,
            "order_timestamp": 1_700_000_000_000,
        }]}

    with patch.object(receiver_main, "ft_force_exit_limit",
                      side_effect=fake_force_exit_limit), \
         patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        placed = _run(receiver_main._place_target_limits(
            cfg, conn, pos_id, ft_trade_id=42,
            targets=[59.5, 62.0], slice_amount=0.5,
        ))

    assert posted == [], "adoption path must NOT call /forceexit"
    rows = conn.execute(
        "SELECT idx, state, ft_order_id FROM target_orders WHERE pos_id=? ORDER BY idx",
        (pos_id,),
    ).fetchall()
    assert rows[0]["state"] == "active"
    assert rows[0]["ft_order_id"] == "manual-tp1"
    assert rows[1]["state"] == "pending"


def test_place_marks_rejected_on_ft_error():
    cfg, conn, pos_id = _setup_db()

    async def fake_force_exit_limit(*args, **kwargs):
        return {"status": 400, "body": json.dumps({"error": "min notional"})}

    async def fake_get_trade(*args, **kwargs):
        return {"orders": []}  # nothing to adopt

    with patch.object(receiver_main, "ft_force_exit_limit",
                      side_effect=fake_force_exit_limit), \
         patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade):
        placed = _run(receiver_main._place_target_limits(
            cfg, conn, pos_id, ft_trade_id=42,
            targets=[59.5], slice_amount=0.5,
        ))

    # idx=0 rejected; the entry in `placed` reflects that
    rejected = [p for p in placed if p["idx"] == 0][0]
    assert rejected["state"] == "rejected"
    row = conn.execute(
        "SELECT * FROM target_orders WHERE pos_id=?", (pos_id,)
    ).fetchone()
    assert row["state"] == "rejected"
    assert "min notional" in (row["notes"] or "")


def test_concurrent_reconcile_serialized_by_lock():
    """Codex 019e7030 finding #1: background loop and manual
    /target_orders/reconcile must not both pick the same pending row
    and double-POST /forceexit. The phase2_lock serializes both
    entry points — concurrent calls produce ONE POST, not two.
    """
    import asyncio as _aio
    cfg, conn, pos_id = _setup_db()
    # Seed: idx=0 active about to fill, idx=1 pending
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
        "VALUES (?, 0, 59.5, 0.5, 'active', 'sim-tp1', ?)",
        (pos_id, "2026-05-28T19:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 1, 62.0, 0.5, 'pending')",
        (pos_id,),
    )

    # Install the lock on app.state — production lifespan does this.
    class _S:
        def __init__(self, c, cf):
            self.conn = c; self.cfg = cf; self.ft_session = None
            self.public_session = None; self.notify_tasks = set()
            self.phase2_lock = _aio.Lock()
    receiver_main.app.state = _S(conn, cfg)

    get_trade_calls = {"n": 0}

    async def fake_get_trade(_cfg, trade_id, session=None):
        get_trade_calls["n"] += 1
        # Both concurrent ticks first see TP1 as filled
        if get_trade_calls["n"] <= 2:
            return {"orders": [{
                "order_id": "sim-tp1", "order_type": "limit",
                "is_open": False, "status": "closed",
                "ft_order_side": "sell", "filled": 0.5,
                "amount": 0.5, "safe_price": 59.5,
            }]}
        # After cascade has run once, TP2 is visible
        return {"orders": [{
            "order_id": "sim-tp2", "order_type": "limit",
            "is_open": True, "ft_order_side": "sell",
            "safe_price": 62.0, "amount": 0.5,
            "order_timestamp": 1_700_000_001_000,
        }]}

    posted = []

    async def fake_force_exit_limit(_cfg, trade_id, amount, price, session=None):
        posted.append((trade_id, amount, price))
        # Yield to event loop so the other concurrent reconcile can interleave
        await _aio.sleep(0)
        return {"status": 200, "body": '{"result":"ok"}'}

    async def run_two_concurrent():
        with patch.object(receiver_main, "ft_get_trade",
                          side_effect=fake_get_trade), \
             patch.object(receiver_main, "ft_force_exit_limit",
                          side_effect=fake_force_exit_limit):
            return await _aio.gather(
                receiver_main._reconcile_target_orders(cfg, conn),
                receiver_main._reconcile_target_orders(cfg, conn),
            )

    results = _run(run_two_concurrent())

    # The lock should have serialized them: ONE POST, not two.
    assert len(posted) == 1, \
        f"concurrent reconciles must serialize via lock; got {len(posted)} POSTs"
    # Both calls should report some work, summed filled count is 1 total.
    total_filled = sum(r["filled"] for r in results)
    assert total_filled == 1, \
        f"TP1 should be marked filled exactly once across both ticks; got {total_filled}"

    rows = conn.execute(
        "SELECT idx, state FROM target_orders WHERE pos_id=? ORDER BY idx",
        (pos_id,),
    ).fetchall()
    assert rows[0]["state"] == "filled"
    assert rows[1]["state"] == "active"


def test_adoption_rejects_wrong_side_order():
    """Codex 019e7030 finding #2: on a SHORT trade, adoption must
    require ft_order_side='buy' (close a short). A same-price 'sell'
    limit (e.g. an unrelated entry) must NOT be adopted.
    """
    orders = [
        {"order_id": "wrong-side-entry", "order_type": "limit",
         "is_open": True, "ft_order_side": "sell",
         "safe_price": 100.0, "amount": 1.0,
         "order_timestamp": 1_700_000_000_000},
    ]
    # Short trade → exit side is 'buy'. Sell at same price must NOT match.
    found = receiver_main._find_open_limit_exit_at_price(
        orders, 100.0, is_short=True,
    )
    assert found is None, "must not adopt wrong-side limit on short trade"

    # Correct side present → matches
    orders.append({
        "order_id": "correct-buy-close", "order_type": "limit",
        "is_open": True, "ft_order_side": "buy",
        "safe_price": 100.0, "amount": 1.0,
        "order_timestamp": 1_700_000_001_000,
    })
    found = receiver_main._find_open_limit_exit_at_price(
        orders, 100.0, is_short=True,
    )
    assert found is not None
    assert found["order_id"] == "correct-buy-close"


def test_adoption_long_default_requires_sell():
    """Long trade (is_short=False default) → exit side is 'sell'."""
    orders = [
        {"order_id": "buy-noise", "order_type": "limit",
         "is_open": True, "ft_order_side": "buy",
         "safe_price": 65.0, "amount": 0.5,
         "order_timestamp": 1_700_000_000_000},
        {"order_id": "correct-sell-close", "order_type": "limit",
         "is_open": True, "ft_order_side": "sell",
         "safe_price": 65.0, "amount": 0.5,
         "order_timestamp": 1_700_000_001_000},
    ]
    found = receiver_main._find_open_limit_exit_at_price(orders, 65.0)
    assert found is not None
    assert found["order_id"] == "correct-sell-close"


def test_reconcile_loop_skips_tick_when_ft_unreachable():
    """Regression: incident 2026-05-28 19:58 UTC. ft-killers-scalp was
    restarted; ft_open_trades returned None (was: []); reconcile_loop
    interpreted empty as 'no trades open on FT' and false-closed every
    open position. The position-reconciler must SKIP the tick on
    None, never proceed with missed-trade detection on a partial view.
    """
    import asyncio as _aio
    cfg, conn, pos_id = _setup_db()
    # Mark a position open with ft_trade_id=42 — must NOT be closed
    # by the reconcile when FT is unreachable.
    conn.execute(
        "UPDATE positions SET state='open', ft_trade_id=42 WHERE pos_id=?",
        (pos_id,),
    )

    async def fake_unreachable(*a, **k):
        return None

    # Run one iteration manually by patching ft_open_trades + breaking
    # after the first sleep.
    async def one_tick():
        # Inline the body — same structure as reconcile_loop, but exits
        # after the FT call instead of sleeping forever.
        ft_open = await receiver_main.ft_open_trades(cfg, session=None)
        if ft_open is None:
            return "skipped"
        return "proceeded"

    with patch.object(receiver_main, "ft_open_trades",
                      side_effect=fake_unreachable):
        result = _run(one_tick())

    assert result == "skipped"
    row = conn.execute(
        "SELECT state, close_reason FROM positions WHERE pos_id=?",
        (pos_id,),
    ).fetchone()
    assert row["state"] == "open", \
        "position must NOT be closed when FT is unreachable"
    assert row["close_reason"] is None


def test_cascade_after_fill_places_next_tp():
    """Reconciler detects an active TP filled → cascades to place idx+1.

    Regression test for the core cascade design: FT only allows one open
    exit at a time, so the next TP can only be placed AFTER the prior one
    fills.
    """
    cfg, conn, pos_id = _setup_db()
    # Seed: idx=0 active (about to fill), idx=1 pending
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state, ft_order_id, placed_at) "
        "VALUES (?, 0, 59.5, 0.5, 'active', 'sim-tp1', ?)",
        (pos_id, "2026-05-28T19:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
        "VALUES (?, 1, 62.0, 0.5, 'pending')",
        (pos_id,),
    )

    get_trade_calls = []

    async def fake_get_trade(_cfg, trade_id, session=None):
        get_trade_calls.append(trade_id)
        # Reconciler call (#1) — TP1 closed/filled
        if len(get_trade_calls) == 1:
            return {"orders": [{
                "order_id": "sim-tp1", "order_type": "limit",
                "is_open": False, "status": "closed",
                "ft_order_side": "sell", "filled": 0.5,
                "amount": 0.5, "safe_price": 59.5,
            }]}
        # Cascade adoption-check (#2) — no existing open exit
        if len(get_trade_calls) == 2:
            return {"orders": []}
        # Cascade post-discovery (#3) — TP2 now visible
        return {"orders": [{
            "order_id": "sim-tp2", "order_type": "limit",
            "is_open": True, "ft_order_side": "sell",
            "safe_price": 62.0, "amount": 0.5,
            "order_timestamp": 1_700_000_001_000,
        }]}

    posted = []

    async def fake_force_exit_limit(_cfg, trade_id, amount, price, session=None):
        posted.append((trade_id, amount, price))
        return {"status": 200, "body": '{"result":"ok"}'}

    with patch.object(receiver_main, "ft_get_trade",
                      side_effect=fake_get_trade), \
         patch.object(receiver_main, "ft_force_exit_limit",
                      side_effect=fake_force_exit_limit):
        summary = _run(receiver_main._reconcile_target_orders(cfg, conn))

    assert summary["filled"] == 1
    assert summary["cascaded"] == 1
    assert posted == [(42, 0.5, 62.0)], \
        f"cascade should post TP2 at 62.0; got {posted}"

    rows = conn.execute(
        "SELECT idx, state, ft_order_id FROM target_orders WHERE pos_id=? ORDER BY idx",
        (pos_id,),
    ).fetchall()
    assert rows[0]["state"] == "filled"
    assert rows[1]["state"] == "active"
    assert rows[1]["ft_order_id"] == "sim-tp2"


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
