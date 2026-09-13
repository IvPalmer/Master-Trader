"""Regression cases from the September 9/11 small-position incidents."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from .test_phase2_active_tps import _setup_db, _run
from .test_signal_update import _setup as setup_signal, _payload as signal_payload
from app import main as receiver
from app.tp_plan import executable_targets


@pytest.fixture(autouse=True)
def restore_state():
    saved = receiver.app.state
    try:
        yield
    finally:
        receiver.app.state = saved


def trade(amount=65, short=False, orders=None, stop_loss_ratio=-0.16):
    return {"amount": amount, "amount_requested": 65.41, "is_open": True,
            "nr_of_successful_entries": 1, "is_short": short,
            "stop_loss_ratio": stop_loss_ratio,
            "amount_precision": 1, "precision_mode": 4,
            "price_precision": .00001, "precision_mode_price": 4,
            "contract_size": 1, "orders": orders or []}


def test_trx_groups_filled_integer_inventory_instead_of_posting_2_80_exit():
    targets = [.35, .36, .37, .38, .39, .40, .41, .42]
    plan = executable_targets(trade(), targets, 10)
    assert plan == [(3, .38, 32), (7, .42, 33)]
    assert sum(p[2] for p in plan) == 65  # requested 65.41 is never allocated
    assert all(p[1] * p[2] >= 10 for p in plan)


def test_short_residual_notional_is_checked_at_last_target():
    plan = executable_targets(trade(65, True), [.42, .41, .40, .39, .38, .37, .36, .35], 10)
    assert sum(p[2] for p in plan) == 65
    assert all(p[1] * p[2] >= 10 for p in plan)


def test_gram_single_executable_group_defers_allocations_to_final_target():
    targets = [1.5 + i * .05 for i in range(8)]
    plan = executable_targets(trade(11), targets, 10)
    assert plan == [(7, 1.85, 11)]


def test_does_not_create_dust_or_increase_total_after_contract_rounding():
    t = trade(1.999)
    t.update(amount_precision=2, precision_mode=2, contract_size=.1)
    plan = executable_targets(t, [30, 31, 32], 10)
    assert sum(p[2] for p in plan) == pytest.approx(1.999)
    assert all(p[2] * p[1] >= 10 for p in plan)


@pytest.mark.parametrize("field,value", [("amount", 0), ("amount", float("nan")),
    ("amount_precision", None), ("precision_mode", 3), ("price_precision", None)])
def test_missing_or_invalid_venue_metadata_fails_closed(field, value):
    t = trade()
    t[field] = value
    with pytest.raises((ValueError, ArithmeticError, TypeError)):
        executable_targets(t, [.35, .36], 10)


def test_unfilled_or_still_filling_entry_never_allocated():
    t = trade()
    t["nr_of_successful_entries"] = 0
    assert executable_targets(t, [.35], 10) == []
    t["nr_of_successful_entries"] = 1
    t["orders"] = [{"is_open": True, "ft_order_side": "buy", "filled": 10}]
    assert executable_targets(t, [.35], 10) == []


def test_remainder_is_valued_at_the_group_price_with_freqtrade_reserve():
    """2026-09-12 re-arm: DOT 19 planned 10.5@1.06 + 8.5@1.40 and GRAM 11
    planned 6@1.80 + 5@2.25; Freqtrade refused both ("Remaining amount of
    9.01 would be too small"): it values the remainder at the order price
    and requires min_cost * (1.05 / (1 - |stop_loss_ratio|)), capped 1.5."""
    dot = trade(19, stop_loss_ratio=-0.4248)
    dot.update(amount_precision=0.1, price_precision=1e-5)
    assert executable_targets(dot, [.86, .9, .95, 1.0, 1.06, 1.13, 1.21, 1.3, 1.4], 10) == [(8, 1.4, 19)]
    gram = trade(11, stop_loss_ratio=-0.1726)
    gram.update(price_precision=1e-4)
    assert executable_targets(gram, [1.425, 1.5, 1.575, 1.675, 1.8, 1.95, 2.1, 2.25], 10) == [(7, 2.25, 11)]
    # TRX passed: remainder 33 * 0.39 = 12.87 >= 10 * 1.05 / (1 - 0.159) = 12.49.
    trx = trade(65, stop_loss_ratio=-0.1592)
    assert executable_targets(trx, [.35, .362, .375, .39, .41, .435, .465, .5], 10)[0] == (3, .39, 32)
    # Missing ratio falls back to the 1.5 cap and fails the same TRX split.
    assert executable_targets(trade(65, stop_loss_ratio=None),
                              [.35, .362, .375, .39, .41, .435, .465, .5], 10) == [(7, .5, 65)]


def test_reject_unexecutable_entire_position():
    with pytest.raises(ValueError, match="cannot support"):
        executable_targets(trade(10), [.35, .36], 10)


def test_hyperliquid_open_path_posts_grouped_first_target(monkeypatch):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")
    cfg, conn, pos_id = _setup_db()
    snapshots = [trade(), trade(orders=[{
        "order_id": "tp1", "is_open": True, "order_type": "limit",
        "ft_order_side": "sell", "safe_price": .38, "amount": 32}])]

    async def get(*a, **k):
        return snapshots.pop(0)

    async def post(*a, **k):
        assert a[2:4] == (32, .38)
        return {"status": 200, "body": "{}"}

    with patch.object(receiver, "ft_get_trade", side_effect=get), \
         patch.object(receiver, "ft_force_exit_limit", side_effect=post) as submit:
        rows = _run(receiver._place_target_limits(
            cfg, conn, pos_id, 42, [.35, .36, .37, .38, .39, .40, .41, .42], 65.41 / 8))
    assert submit.call_count == 1
    assert [(r["idx"], r["amount"], r["state"]) for r in rows] == [
        (3, 32, "active"), (7, 33, "pending")]


def _seed(conn, pos_id, state="pending"):
    conn.execute("INSERT INTO target_orders (pos_id,idx,price,amount,state) VALUES (?,0,59.5,.5,?)",
                 (pos_id, state))


async def _empty(*a, **k):
    return {"is_open": True, "orders": []}


def test_read_outage_never_posts_then_recovers_without_active_row():
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id)
    async def missing(*a, **k):
        return None
    with patch.object(receiver, "ft_get_trade", side_effect=missing), \
         patch.object(receiver, "ft_force_exit_limit") as submit:
        result = _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42))
    assert result["state"] == "retry"
    submit.assert_not_called()
    conn.execute("UPDATE target_orders SET last_check_at=NULL")
    order = {"order_id": "existing", "is_open": True, "order_type": "limit",
             "ft_order_side": "sell", "safe_price": 59.5, "amount": .5}
    async def existing(*a, **k):
        return {"is_open": True, "orders": [order]}
    with patch.object(receiver, "ft_get_trade", side_effect=existing), \
         patch.object(receiver, "ft_force_exit_limit") as submit:
        result = _run(receiver._reconcile_target_orders(cfg, conn))
    assert result["cascaded"] == 1
    submit.assert_not_called()


@pytest.mark.parametrize("response,state", [({"status": 429}, "retry"),
    ({"status": 400, "body": "minimum notional"}, "rejected"),
    ({"status": 502, "body": '{"error":"Error querying /api/v1/forceexit: Remaining amount of 9.01 would be too small."}'}, "rejected"),
    ({"status": 502, "body": "<html>bad gateway</html>"}, "unknown"),
    ({"status": 502, "body": '{"error":"exchange timed out"}'}, "unknown"),
    ({"status": 502}, "unknown"), ({"status": 200}, "unknown")])
def test_response_classification_and_cooldown(response, state):
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id)
    async def post(*a, **k):
        return response
    with patch.object(receiver, "ft_get_trade", side_effect=_empty), \
         patch.object(receiver, "ft_force_exit_limit", side_effect=post) as submit:
        result = _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42))
        _run(receiver._reconcile_target_orders(cfg, conn))
    assert result["state"] == state
    assert submit.call_count == 1


def test_timeout_or_crash_never_blindly_resubmits():
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id)
    async def timeout(*a, **k):
        raise asyncio.TimeoutError()
    with patch.object(receiver, "ft_get_trade", side_effect=_empty), \
         patch.object(receiver, "ft_force_exit_limit", side_effect=timeout) as submit:
        assert _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42))["state"] == "unknown"
        conn.execute("UPDATE target_orders SET state='placing',last_check_at=NULL")
        _run(receiver._reconcile_target_orders(cfg, conn))
        # An empty executor ledger cannot exclude a successful venue order
        # whose response was lost. Repeated observations must never repost.
        assert submit.call_count == 1
        assert conn.execute("SELECT state FROM target_orders").fetchone()[0] == "unknown"
        for _ in range(3):
            conn.execute("UPDATE target_orders SET last_check_at=NULL")
            _run(receiver._reconcile_target_orders(cfg, conn))
    assert submit.call_count == 1


@pytest.mark.parametrize("state", ["unknown", "placing"])
def test_unidentified_exit_order_keeps_submission_unknown(state):
    """A new exit-side order that cannot be matched to the row must never
    be ignored: the row stays unknown and nothing is resubmitted."""
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id, state)
    now = datetime.now(timezone.utc)
    conn.execute("UPDATE target_orders SET submitted_at=?, prior_order_ids=?",
                 (now.isoformat(), json.dumps(["previous"])))
    stray = {"order_id": "stray", "order_type": "limit", "ft_order_side": "sell",
             "status": "open", "price": 61.0, "amount": .25, "filled": 0,
             "is_open": True, "order_timestamp": int(now.timestamp() * 1000)}
    async def get(*a, **k):
        return {"is_open": True, "orders": [stray]}
    with patch.object(receiver, "ft_get_trade", side_effect=get), \
         patch.object(receiver, "ft_force_exit_limit") as submit:
        result = _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42))
    assert result["state"] == "unknown"
    submit.assert_not_called()


def test_missing_intent_metadata_keeps_submission_unknown():
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id, "unknown")  # legacy row: no submitted_at/prior_order_ids
    with patch.object(receiver, "ft_get_trade", side_effect=_empty), \
         patch.object(receiver, "ft_force_exit_limit") as submit:
        result = _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42))
    assert result["state"] == "unknown"
    submit.assert_not_called()


@pytest.mark.parametrize("state", ["cancelled", "rejected", "blocked"])
def test_terminal_ladder_never_automatically_skips_to_next_target(state):
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id, state)
    conn.execute("INSERT INTO target_orders(pos_id,idx,price,amount,state) VALUES (?,1,62,.5,'pending')",
                 (pos_id,))
    with patch.object(receiver, "ft_get_trade") as get, \
         patch.object(receiver, "ft_force_exit_limit") as submit:
        _run(receiver._reconcile_target_orders(cfg, conn))
        assert _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42)) is None
    get.assert_not_called()
    submit.assert_not_called()


def test_concurrent_open_and_delayed_fill_create_one_ladder(monkeypatch):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")
    cfg, conn, pos_id = _setup_db()
    posted = []
    async def get(*a, **k):
        await asyncio.sleep(0)
        orders = ([{"order_id": "tp", "is_open": True, "order_type": "limit",
                    "ft_order_side": "sell", "safe_price": .38, "amount": 32}]
                  if posted else [])
        return trade(orders=orders)
    async def post(*a, **k):
        posted.append(a)
        await asyncio.sleep(0)
        return {"status": 200}
    async def race():
        receiver.app.state = SimpleNamespace(phase2_lock=asyncio.Lock())
        targets = [.35, .36, .37, .38, .39, .40, .41, .42]
        await asyncio.gather(*[receiver._place_target_limits(cfg, conn, pos_id, 42, targets, 65 / 8)
                               for _ in range(2)])
    with patch.object(receiver, "ft_get_trade", side_effect=get), \
         patch.object(receiver, "ft_force_exit_limit", side_effect=post):
        _run(race())
    assert len(posted) == 1
    assert conn.execute("SELECT count(*) FROM target_orders").fetchone()[0] == 2


@pytest.mark.parametrize("timeout", [False, True])
def test_instant_fill_is_identified_and_cascades_without_duplicate(timeout):
    cfg, conn, pos_id = _setup_db()
    _seed(conn, pos_id)
    conn.execute("INSERT INTO target_orders(pos_id,idx,price,amount,state) VALUES (?,1,62,.5,'pending')",
                 (pos_id,))
    posted = []
    async def get(*a, **k):
        orders = []
        if posted:
            orders.append({"order_id": "instant", "order_type": "limit", "is_open": False,
                "status": "closed", "ft_order_side": "sell", "price": 59.5,
                "amount": .5, "filled": .5,
                "order_timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)})
        if len(posted) > 1:
            orders.append({"order_id": "tp2", "order_type": "limit", "is_open": True,
                "ft_order_side": "sell", "price": 62, "amount": .5})
        return {"is_open": True, "orders": orders}
    async def post(*a, **k):
        posted.append(a[3])
        if timeout and len(posted) == 1:
            raise asyncio.TimeoutError()
        return {"status": 200}
    with patch.object(receiver, "ft_get_trade", side_effect=get), \
         patch.object(receiver, "ft_force_exit_limit", side_effect=post):
        _run(receiver._adopt_or_post_next_tp(cfg, conn, pos_id, 42))
        if timeout:
            conn.execute("UPDATE target_orders SET last_check_at=NULL WHERE idx=0")
            _run(receiver._reconcile_target_orders(cfg, conn))
        _run(receiver._reconcile_target_orders(cfg, conn))
    assert posted == [59.5, 62]
    assert conn.execute("SELECT state FROM target_orders WHERE idx=0").fetchone()[0] == "filled"
    assert conn.execute("SELECT state FROM target_orders WHERE idx=1").fetchone()[0] == "active"


@pytest.mark.parametrize("case", ["old_id", "old_time", "wrong_side", "ambiguous"])
def test_uncertain_submission_never_claims_unrelated_fill(case):
    now = datetime.now(timezone.utc)
    row = {"price": 59.5, "amount": .5, "submitted_at": now.isoformat(),
           "prior_order_ids": json.dumps(["previous"])}
    order = {"order_id": "new", "order_type": "limit", "ft_order_side": "sell",
             "status": "closed", "price": 59.5, "amount": .5, "filled": .5,
             "order_timestamp": int(now.timestamp() * 1000)}
    if case == "old_id":
        order["order_id"] = "previous"
    elif case == "old_time":
        order["order_timestamp"] -= 10000
    elif case == "wrong_side":
        order["ft_order_side"] = "buy"
    orders = [order]
    if case == "ambiguous":
        orders.append({**order, "order_id": "other"})
    assert receiver._find_submitted_exit({"orders": orders}, row) is None


@pytest.mark.parametrize("state", ["unknown", "placing"])
@pytest.mark.parametrize("offline", [False, True])
def test_partial_close_defers_for_uncertain_tp_even_without_other_rows(state, offline):
    cfg, conn, pos_id = setup_signal()
    _seed(conn, pos_id, state)
    payload = receiver.EventPayload(
        msg={"id": 100001, "date": "2026-09-11T20:00:00+00:00"},
        classification={"kind": "close_partial", "symbol": "KITE", "signal_id": 2154,
                        "pct": 50, "direction": "long"})
    async def get(*a, **k):
        return None if offline else {"is_open": True, "orders": []}
    with patch.object(receiver, "ft_get_trade", side_effect=get), \
         patch.object(receiver, "ft_force_exit") as market, \
         patch.object(receiver, "ft_force_exit_limit") as limit:
        result = _run(receiver._process_event(payload))
    assert result["action"] == "deferred"
    assert result["reason"] == "tp_submission_unknown"
    market.assert_not_called()
    limit.assert_not_called()


def test_grouped_ladder_does_not_change_explicit_original_tp1_instruction():
    cfg, conn, pos_id = setup_signal(targets_remaining=[70, 80, 85])
    conn.execute("INSERT INTO target_orders(pos_id,idx,price,amount,state) VALUES (?,2,85,1,'pending')",
                 (pos_id,))
    conn.execute("INSERT INTO events(pos_id,msg_id,event_at,kind,payload) VALUES (?,999,'now','open',?)",
                 (pos_id, json.dumps({"signal_targets": [59.5, 70, 80, 85]})))
    receiver.app.state.phase2_lock = asyncio.Lock()
    async def get(*a, **k):
        return {"current_rate": 60, "amount": 1, "orders": []}
    async def close(*a, **k):
        return {"status": 200, "body": "{}"}
    with patch.object(receiver, "ft_get_trade", side_effect=get), \
         patch.object(receiver, "ft_force_exit", side_effect=close) as market, \
         patch.object(receiver, "ft_force_exit_limit") as limit:
        result = _run(asyncio.wait_for(receiver._process_event(signal_payload("close_at_target_1")), 2))
    assert market.call_count == 1  # 60 crossed original TP1=59.5, not grouped TP=85
    limit.assert_not_called()


def test_tp1_update_defers_when_previous_submission_is_unresolved():
    cfg, conn, pos_id = setup_signal(targets_remaining=[59.5, 62])
    _seed(conn, pos_id, "unknown")
    with patch.object(receiver, "ft_force_exit_limit") as limit, \
         patch.object(receiver, "ft_cancel_open_order") as cancel:
        result = _run(receiver._process_event(signal_payload("close_at_target_1")))
    assert result["reason"] == "tp_submission_unknown"
    limit.assert_not_called()
    cancel.assert_not_called()
