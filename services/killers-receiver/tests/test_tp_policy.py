"""Source allocation behavior; synthetic prices and fills only."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app import main as receiver
from app.tp_policy import parse_policy, snapshot_policy, preflight, executable_source_targets
from .test_tp_reliability import trade
from .test_phase2_active_tps import _setup_db, _run
from .test_signal_update import _setup


@pytest.fixture(autouse=True)
def restore_state():
    saved = receiver.app.state
    yield
    receiver.app.state = saved


def policy(text="1:50,2:50", prices=(1.1, 1.2), entry=1, short=False):
    return snapshot_policy(parse_policy(text), prices, entry, short)


@pytest.mark.parametrize("text", ["1:50,1:50", "2:50,1:50", "0:100", "1:99", "1:nan", "1:inf", "1:-2,2:102", "1:50,", "1.5:100"])
def test_invalid_config_rejected(text):
    with pytest.raises(ValueError):
        parse_policy(text)


def test_preserves_exact_source_indices_prices_and_filled_inventory():
    p = policy("1:50,3:25,4:25", [1.1, 1.2, 1.3, 1.4])
    result = executable_source_targets(trade(81), p)
    assert result == [(0, 1.1, 40), (2, 1.3, 20), (3, 1.4, 21)]
    assert sum(x[2] for x in result) == 81


def test_small_position_does_not_silently_move_to_last_target():
    with pytest.raises(ValueError, match="below"):
        executable_source_targets(trade(15), policy())
    with pytest.raises(ValueError, match="below"):
        preflight(policy(), 15, 1)
    # A single source-target exit is possible only if explicitly configured.
    assert executable_source_targets(trade(15), policy("1:100")) == [(0, 1.1, 15)]


def test_short_last_order_and_residual_both_checked():
    p = policy(prices=[.9, .8], short=True)
    assert executable_source_targets(trade(40, True), p) == [(0, .9, 20), (1, .8, 20)]
    with pytest.raises(ValueError):
        executable_source_targets(trade(25, True), p)


def test_rounding_can_fail_even_when_notional_preflight_passes():
    p = policy(prices=[10.1, 11], entry=10)
    preflight(p, 30, 10)
    t = trade(3)
    t["amount_precision"] = 2
    with pytest.raises(ValueError):
        executable_source_targets(t, p)


@pytest.mark.parametrize("prices", [[], [.9, 1.2], [1.2, 1.1]])
def test_missing_crossed_or_unordered_targets_rejected(prices):
    with pytest.raises(ValueError):
        policy(prices=prices)


def test_unsupported_price_precision_does_not_move_target():
    t = trade(100)
    t["price_precision"] = .3
    with pytest.raises(ValueError, match="precision"):
        executable_source_targets(t, policy())


def test_waits_for_finished_entry():
    t = trade(100, orders=[{"is_open": True, "ft_order_side": "buy"}])
    assert executable_source_targets(t, policy()) == []


def test_frozen_policy_survives_config_change_and_repeated_arming(monkeypatch):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")
    cfg, conn, pos_id = _setup_db()
    cfg.tp_allocations = parse_policy("2:100")
    conn.execute("UPDATE positions SET tp_policy=? WHERE pos_id=?", (json.dumps(policy()), pos_id))
    order = {"order_id": "synthetic-tp", "is_open": True, "order_type": "limit", "ft_order_side": "sell", "safe_price": 1.1, "amount": 20}
    with patch.object(receiver, "ft_get_trade", new=AsyncMock(side_effect=[trade(40), trade(40, orders=[order])])), patch.object(receiver, "ft_force_exit_limit", new=AsyncMock(return_value={"status": 200, "body": "{}"})) as post:
        rows = _run(receiver._place_target_limits(cfg, conn, pos_id, 42, [1.1, 1.2], 20))
        again = _run(receiver._place_target_limits(cfg, conn, pos_id, 42, [1.1, 1.2], 20))
    assert [(r['idx'], r['price'], r['amount'], r['state']) for r in rows] == [(0, 1.1, 20, 'active'), (1, 1.2, 20, 'pending')]
    assert len(again) == 2
    assert post.call_count == 1


@pytest.mark.parametrize("notional,expected", [(15, "skipped"), (60, "opened")])
def test_entry_preflight_and_snapshot_before_submission(monkeypatch, notional, expected):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")
    cfg, conn, _ = _setup()
    cfg.tp_allocations = parse_policy("1:50,2:50")
    payload = receiver.EventPayload(msg={"id": 234567, "date": "2026-09-18T00:00:00Z", "text": "TARGETS: 1.1 - 1.2"}, classification={"kind": "open", "symbol": "ABC", "direction": "long", "entry": 1., "sl": .95})
    async def enter(*args, **kwargs):
        row = conn.execute("SELECT tp_policy FROM positions WHERE open_msg_id=234567").fetchone()
        assert json.loads(row[0]) == policy()
        return {"status": 200, "body": '{}'}
    with patch.object(receiver, "get_execution_mark_price", new=AsyncMock(return_value=1.)), patch.object(receiver, "compute_stake", return_value=(notional / 2, 2, .05)), patch.object(receiver, "ft_force_enter", new=AsyncMock(side_effect=enter)) as post:
        result = _run(receiver._process_event(payload))
    if expected == "skipped":
        assert result["reason"] == "tp_policy_infeasible"
        post.assert_not_called()
        assert conn.execute("SELECT COUNT(*) FROM positions WHERE open_msg_id=234567").fetchone()[0] == 0
    else:
        assert post.call_count == 1


def test_actual_fill_infeasible_blocks_without_fallback_post(monkeypatch):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")
    cfg, conn, pos_id = _setup_db()
    conn.execute("UPDATE positions SET tp_policy=? WHERE pos_id=?", (json.dumps(policy("1:50,3:50", [1.1, 1.2, 1.3])), pos_id))
    with patch.object(receiver, "ft_get_trade", new=AsyncMock(return_value=trade(15))), patch.object(receiver, "ft_force_exit_limit", new=AsyncMock()) as post:
        rows = _run(receiver._place_target_limits(cfg, conn, pos_id, 42, [1.1, 1.2, 1.3], 5))
    assert [(r['idx'], r['state']) for r in rows] == [(0, 'blocked'), (2, 'blocked')]
    assert all(r['amount'] == 0 for r in rows)
    post.assert_not_called()


@pytest.mark.parametrize('venue,active', [('binance', 'true'), ('hyperliquid', 'false')])
def test_config_rejects_incompatible_execution_modes(monkeypatch, venue, active):
    monkeypatch.setenv('KILLERS_TP_ALLOCATIONS', '1:50,2:50')
    monkeypatch.setenv('KILLERS_EXECUTION_VENUE', venue)
    monkeypatch.setenv('KILLERS_ACTIVE_TP_LIMITS', active)
    with pytest.raises(ValueError, match='requires active Hyperliquid'):
        receiver.Config()
