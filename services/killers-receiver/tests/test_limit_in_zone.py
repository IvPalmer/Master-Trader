"""Limit-in-zone entry tests.

Applies the Insiders/Track-A "fill like the signaler" finding to killers:
instead of a MARKET fill that either chases past the signaler's entry zone
or gets thrown away by the slippage gate, rest a LIMIT order at the near
edge of the posted zone. The limit price structurally bounds slippage —
you can never pay worse than the zone edge — so on a breach we place the
resting limit instead of skipping.

Design = "limit on breach" (Mode B):
  - mark within the slippage gate  → unchanged MARKET path
  - mark past the zone (would skip) → resting LIMIT at near-edge
      LONG  → entry_hi   SHORT → entry_lo
  - KILLERS_ENTRY_LIMIT_IN_ZONE=false → old skip behaviour (back-compat)
  - entry bounds unparseable          → still fail-closed (need the price)
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402


class _FakeAppState:
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        self.ft_session = None
        self.public_session = None
        self.notify_tasks = set()


def _setup(conn_path, *, max_slip=3.0, limit_in_zone=True):
    import os
    os.environ["KILLERS_DB"] = conn_path
    os.environ["KILLERS_MAX_ENTRY_SLIPPAGE_PCT"] = str(max_slip)
    os.environ["KILLERS_ENTRY_LIMIT_IN_ZONE"] = "true" if limit_in_zone else "false"
    # Active TP placement off here — we only exercise the entry decision, and
    # leaving it on would try to arm a ladder against a non-running FT.
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "false"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    state = _FakeAppState(conn, cfg)
    receiver_main.app.state = state
    return state


def _payload(*, msg_id, signal_id, symbol, direction, entry_range, sl, targets):
    tline = " - ".join(str(t) for t in targets)
    msg = {
        "id": msg_id,
        "date": "2026-05-31T23:17:00+00:00",
        "text": (
            f"\U0001F4CDSIGNAL ID: #{signal_id}\U0001F4CD\n"
            f"COIN: ${symbol}/USDT (2-5x)\n"
            f"Direction: {direction.upper()}\n"
            f"ENTRY: {entry_range[0]} - {entry_range[1]}\n\n"
            f"TARGETS: {tline}\n\n"
            f"STOP LOSS: {sl}\n"
        ),
    }
    classification = {
        "id": msg_id, "kind": "open", "signal_id": signal_id,
        "symbol": symbol, "direction": direction,
        "entry": None, "entry_range": list(entry_range),
        "sl": sl, "tp": None, "pct": None, "applies_to": None,
        "confidence": 1.0, "notes": "fast-path",
    }
    return receiver_main.EventPayload(msg=msg, classification=classification)


def _arb_long(msg_id=990101):
    """ARB #2146 shape — entry 0.099-0.10, mark 0.1041 = +4.1% past entry_hi."""
    return _payload(msg_id=msg_id, signal_id=2146, symbol="ARB",
                    direction="long", entry_range=[0.099, 0.10], sl=0.09,
                    targets=[0.105, 0.11, 0.12])


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _capturing_force_enter():
    """Returns (fake_coro, calls) — records every ft_force_enter kwargs."""
    calls = []

    async def fake(cfg, pair, direction, stake, leverage, **kwargs):
        calls.append({"pair": pair, "direction": direction,
                      "ordertype": kwargs.get("ordertype"),
                      "price": kwargs.get("price")})
        # Mimic FT accepting a (possibly resting) forceentry.
        return {"status": 200,
                "body": '{"trade_id": 42, "pair": "%s", "is_open": true}' % pair}

    return fake, calls


# ── LONG breach → resting limit at entry_hi ────────────────────────────────


def test_long_breach_places_limit_at_entry_hi():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    payload = _arb_long()
    fake_fe, calls = _capturing_force_enter()

    async def fake_mark(*a, **k):
        return 0.1041  # +4.1% above entry_hi 0.10 → breach

    with patch.object(receiver_main, "get_binance_mark_price", side_effect=fake_mark), \
         patch.object(receiver_main, "ft_force_enter", side_effect=fake_fe):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "force_enter", result
    assert result.get("ordertype") == "limit", result
    assert abs(result.get("limit_price") - 0.10) < 1e-9, result
    # And the actual FT call used a limit at the near edge.
    assert len(calls) == 1
    assert calls[0]["ordertype"] == "limit"
    assert abs(calls[0]["price"] - 0.10) < 1e-9


# ── SHORT breach → resting limit at entry_lo ───────────────────────────────


def test_short_breach_places_limit_at_entry_lo():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    payload = _payload(msg_id=990102, signal_id=777, symbol="BTC",
                       direction="short", entry_range=[100000, 102000],
                       sl=105000, targets=[98000, 95000])
    fake_fe, calls = _capturing_force_enter()

    async def fake_mark(*a, **k):
        return 95000.0  # 5% below entry_lo → breach

    with patch.object(receiver_main, "get_binance_mark_price", side_effect=fake_mark), \
         patch.object(receiver_main, "ft_force_enter", side_effect=fake_fe):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "force_enter", result
    assert result.get("ordertype") == "limit"
    assert abs(result.get("limit_price") - 100000) < 1e-6
    assert calls[0]["ordertype"] == "limit"
    assert abs(calls[0]["price"] - 100000) < 1e-6


# ── Feature OFF → old skip behaviour (back-compat) ─────────────────────────


def test_breach_with_feature_off_still_skips():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0, limit_in_zone=False)
    payload = _arb_long(msg_id=990103)

    async def fake_mark(*a, **k):
        return 0.1041

    with patch.object(receiver_main, "get_binance_mark_price", side_effect=fake_mark):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "skipped"
    assert result["reason"] == "entry_slippage_exceeded"


# ── Within gate → unchanged MARKET path ────────────────────────────────────


def test_within_gate_uses_market_not_limit():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    payload = _arb_long(msg_id=990104)
    fake_fe, calls = _capturing_force_enter()

    async def fake_mark(*a, **k):
        return 0.10  # exactly at entry_hi → 0% slippage, no breach

    with patch.object(receiver_main, "get_binance_mark_price", side_effect=fake_mark), \
         patch.object(receiver_main, "ft_force_enter", side_effect=fake_fe):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "force_enter"
    assert result.get("ordertype") == "market"
    assert result.get("limit_price") is None
    assert calls[0]["ordertype"] == "market"
    assert calls[0]["price"] is None


# ── Bounds missing → still fail-closed (need price) ────────────────────────


def test_bounds_missing_fails_closed_even_with_feature_on():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    msg = {"id": 990105, "date": "2026-05-31T23:17:00+00:00",
           "text": "\U0001F4CDSIGNAL ID: #999\U0001F4CD\nCOIN: $BTC/USDT\nDirection: LONG\nSTOP LOSS: 90000\n"}
    classification = {
        "id": 990105, "kind": "open", "signal_id": 999,
        "symbol": "BTC", "direction": "long",
        "entry": None, "entry_range": None, "entry_lo": None, "entry_hi": None,
        "sl": 90000, "tp": None, "pct": None, "applies_to": None,
        "confidence": 0.8, "notes": "malformed",
    }
    payload = receiver_main.EventPayload(msg=msg, classification=classification)

    async def fake_mark(*a, **k):
        return 100000.0

    with patch.object(receiver_main, "get_binance_mark_price", side_effect=fake_mark):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "skipped"
    assert result["reason"] == "entry_bounds_missing"


# ── ft_force_enter body construction (market vs limit) ─────────────────────


class _FakeResp:
    def __init__(self, body):
        self._body = body
        self.status = 200

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self):
        self.posted = []

    def post(self, url, json=None, timeout=None):
        self.posted.append(json)
        return _FakeResp('{"trade_id": 1}')


def test_force_enter_market_body_has_no_price():
    cfg = receiver_main.Config()
    sess = _FakeSession()
    _run(receiver_main.ft_force_enter(cfg, "ARB/USDT:USDT", "long", 20.0, 5.0,
                                      session=sess))
    body = sess.posted[0]
    assert body["ordertype"] == "market"
    assert "price" not in body


def test_force_enter_limit_body_carries_price():
    cfg = receiver_main.Config()
    sess = _FakeSession()
    _run(receiver_main.ft_force_enter(cfg, "ARB/USDT:USDT", "long", 20.0, 5.0,
                                      session=sess, ordertype="limit", price=0.10))
    body = sess.posted[0]
    assert body["ordertype"] == "limit"
    assert abs(body["price"] - 0.10) < 1e-9


# ── Delayed-fill TP arming (reconcile step 3) ──────────────────────────────
# A resting limit entry returns trade_id with amount=0, so the open-path
# Phase-2 arming is skipped. Once it fills, the position reconcile must arm
# the posted-TP ladder — the exit half of "fill like the signaler".


def _open_pos_with_targets(conn, *, ft_trade_id, targets, pair="ARB/USDT:USDT",
                           direction="long"):
    import json as _json
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, stake_usd, leverage, ft_trade_id, targets_remaining) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (2146, pair.split("/")[0], pair, direction, "open",
         778899, "2026-05-31T23:17:00+00:00", 20.0, 5.0, ft_trade_id,
         _json.dumps(targets)),
    )
    return conn.execute("SELECT pos_id FROM positions WHERE open_msg_id=778899"
                        ).fetchone()[0]


def _patch_phase2_ft():
    """FT mocks for _place_target_limits: one limit posts, then it re-fetches
    /trade to adopt the new order. Mirrors test_phase2_active_tps."""
    posted = []

    async def fake_force_exit_limit(_cfg, trade_id, amount, price, session=None):
        posted.append((trade_id, amount, price))
        return {"status": 200, "body": '{"result": "Created exit order for trade %d."}' % trade_id}

    calls = {"n": 0}

    async def fake_get_trade(_cfg, trade_id, session=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"orders": []}
        return {"orders": [{"order_id": "sim-tp0", "order_type": "limit",
                            "is_open": True, "ft_order_side": "sell",
                            "safe_price": 0.105, "amount": 0.0,
                            "order_timestamp": 1_700_000_000_000}]}

    return fake_force_exit_limit, fake_get_trade, posted


def test_reconcile_arms_tp_ladder_on_delayed_fill():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        state = _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    # active TP needs to be on for arming; _setup pinned it off, flip on here.
    state.cfg.active_tp_limits = True
    conn = state.conn
    pos_id = _open_pos_with_targets(conn, ft_trade_id=42,
                                    targets=[0.105, 0.11, 0.12])

    # FT reports the entry has FILLED (amount > 0).
    async def fake_open_trades(_cfg, session=None):
        return [{"trade_id": 42, "pair": "ARB/USDT:USDT", "is_short": False,
                 "amount": 1234.5}]

    fe, gt, posted = _patch_phase2_ft()
    with patch.object(receiver_main, "ft_open_trades", side_effect=fake_open_trades), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fe), \
         patch.object(receiver_main, "ft_get_trade", side_effect=gt):
        status = _run(receiver_main._reconcile_loop_once(state.cfg, conn))

    assert status == "ok"
    rows = conn.execute("SELECT idx, state FROM target_orders WHERE pos_id=? ORDER BY idx",
                        (pos_id,)).fetchall()
    assert len(rows) == 3, f"ladder not armed: {rows}"
    assert rows[0]["state"] == "active"     # idx0 posted
    assert rows[1]["state"] == "pending"
    assert rows[2]["state"] == "pending"
    assert len(posted) == 1                 # exactly one limit posted (cascade-safe)


def test_reconcile_does_not_arm_pending_entry():
    """Entry still resting (amount=0) → no ladder armed yet."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        state = _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    state.cfg.active_tp_limits = True
    conn = state.conn
    pos_id = _open_pos_with_targets(conn, ft_trade_id=43,
                                    targets=[0.105, 0.11, 0.12])

    async def fake_open_trades(_cfg, session=None):
        return [{"trade_id": 43, "pair": "ARB/USDT:USDT", "is_short": False,
                 "amount": 0.0}]  # pending, unfilled

    fe, gt, posted = _patch_phase2_ft()
    with patch.object(receiver_main, "ft_open_trades", side_effect=fake_open_trades), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fe), \
         patch.object(receiver_main, "ft_get_trade", side_effect=gt):
        _run(receiver_main._reconcile_loop_once(state.cfg, conn))

    rows = conn.execute("SELECT COUNT(*) c FROM target_orders WHERE pos_id=?",
                        (pos_id,)).fetchone()
    assert rows["c"] == 0, "must not arm a still-pending entry"
    assert len(posted) == 0


def test_reconcile_does_not_rearm_existing_ladder():
    """A position that already has target_orders rows is left alone (never
    re-arm a cancelled/filled ladder — by design)."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        state = _setup(tf.name, max_slip=3.0, limit_in_zone=True)
    state.cfg.active_tp_limits = True
    conn = state.conn
    pos_id = _open_pos_with_targets(conn, ft_trade_id=44,
                                    targets=[0.105, 0.11, 0.12])
    # Simulate an already-cancelled ladder row.
    conn.execute("INSERT INTO target_orders (pos_id, idx, price, amount, state) "
                 "VALUES (?,0,0.105,1.0,'cancelled')", (pos_id,))

    async def fake_open_trades(_cfg, session=None):
        return [{"trade_id": 44, "pair": "ARB/USDT:USDT", "is_short": False,
                 "amount": 1234.5}]

    fe, gt, posted = _patch_phase2_ft()
    with patch.object(receiver_main, "ft_open_trades", side_effect=fake_open_trades), \
         patch.object(receiver_main, "ft_force_exit_limit", side_effect=fe), \
         patch.object(receiver_main, "ft_get_trade", side_effect=gt):
        _run(receiver_main._reconcile_loop_once(state.cfg, conn))

    # Still exactly the one pre-existing cancelled row; nothing new posted.
    rows = conn.execute("SELECT COUNT(*) c FROM target_orders WHERE pos_id=?",
                        (pos_id,)).fetchone()
    assert rows["c"] == 1
    assert len(posted) == 0


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
        for name, e in failed:
            print(f"  {name}: {e}")
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
