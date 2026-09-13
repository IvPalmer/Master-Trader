"""Production regressions: rounding is not profit and rejected TPs are not healthy."""

import asyncio
import sqlite3
import time

import pytest

import app


def trade(amount=11, requested=11.40656786, **kwargs):
    return {
        "trade_id": 1, "pair": "GRAM/USDC:USDC", "is_short": False,
        "amount": amount, "amount_requested": requested,
        "nr_of_successful_entries": 1, "nr_of_successful_exits": 0,
        "orders": [
            {"ft_order_side": "buy", "filled": amount, "status": "closed"},
            {"ft_order_side": "stoploss", "filled": 0, "status": "open"},
        ], **kwargs,
    }


@pytest.mark.parametrize("amount,requested", [(11, 11.40656786), (65, 65.42111157)])
def test_gram_and_trx_entry_rounding_is_zero_booked(amount, requested):
    assert app.booked_pct_from_fills(trade(amount, requested)) == 0.0


@pytest.mark.parametrize("short", [False, True])
def test_booked_uses_all_actual_fills_including_canceled_partial_exits(short):
    entry, exit = ("sell", "buy") if short else ("buy", "sell")
    t = trade(is_short=short, amount=7, requested=99, nr_of_successful_exits=1,
              orders=[
                  {"ft_order_side": entry, "filled": 6},
                  {"ft_order_side": entry, "filled": 4},
                  {"ft_order_side": exit, "filled": 2, "status": "closed"},
                  {"ft_order_side": exit, "filled": 1, "status": "canceled"},
                  {"ft_order_side": "stoploss", "filled": 0},
              ])
    assert app.booked_pct_from_fills(t) == 30.0


def test_missing_exit_fill_data_is_unknown_instead_of_requested_quantity_fallback():
    assert app.booked_pct_from_fills(trade(nr_of_successful_exits=1)) is None
    assert app.booked_pct_from_fills(trade(orders=[], nr_of_successful_exits=1)) is None
    assert app.booked_pct_from_fills(trade(orders=[])) == 0.0


def test_partial_entry_is_not_booked_profit():
    assert app.booked_pct_from_fills(trade(nr_of_successful_entries=0)) is None


def receiver_db(path, states):
    with sqlite3.connect(path) as c:
        c.executescript("""
            CREATE TABLE positions (pos_id INTEGER, ft_trade_id INTEGER, state TEXT);
            CREATE TABLE target_orders (pos_id INTEGER, idx INTEGER, price REAL, state TEXT);
            INSERT INTO positions VALUES (1, 1, 'open');
        """)
        c.executemany("INSERT INTO target_orders VALUES (1, ?, ?, ?)",
                      [(i, 1.425 + i * .1, state) for i, state in enumerate(states)])


@pytest.mark.parametrize("first", ["rejected", "blocked"])
def test_rejected_first_tp_and_pending_ladder_is_critical_even_when_bot_reachable(tmp_path, monkeypatch, first):
    path = tmp_path / "receiver.sqlite"
    receiver_db(path, [first] + ["pending"] * 7)
    ladders = app.killers_tp_ladder(str(path), strict=True)
    assert ladders[1]["next_tp"] is None
    assert ladders[1]["status"] == "blocked"
    health = app._tp_execution_health([trade()], ladders)
    monkeypatch.setattr(app, "BOTS", [{"key": "killers-ft"}])
    monkeypatch.setattr(app, "_cache", {
        "bots": {"killers-ft": {"reachable": True, "dry_run": False,
                               "execution_health": health}},
        "last_reachable_at": {"killers-ft": time.time()},
    })
    status = app._fleet_status()
    assert status["level"] == "red"
    assert status["execution_faults"] == ["killers-ft"]
    assert status["stale_bots"] == []
    assert asyncio.run(app.healthz())["ok"] is True


@pytest.mark.parametrize("state", ["retry", "unknown", "placing", "pending", "future-state"])
def test_unconfirmed_target_is_warning(tmp_path, state):
    path = tmp_path / "receiver.sqlite"
    receiver_db(path, [state, "pending"])
    health = app._tp_execution_health([trade()], app.killers_tp_ladder(str(path)))
    assert health["status"] == "warning"


def test_uncertain_order_cannot_be_hidden_by_an_active_target(tmp_path):
    path = tmp_path / "receiver.sqlite"
    receiver_db(path, ["unknown", "active"])
    health = app._tp_execution_health([trade()], app.killers_tp_ladder(str(path)))
    assert health["status"] == "warning"


@pytest.mark.parametrize("states", [["active", "pending"], ["filled", "filled"]])
def test_active_complete_and_manual_cancellation_are_not_stalled(tmp_path, states):
    path = tmp_path / "receiver.sqlite"
    receiver_db(path, states)
    health = app._tp_execution_health([trade()], app.killers_tp_ladder(str(path)))
    assert health["status"] == "ok"


def test_missing_ledger_warns_without_creating_database(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        app.killers_tp_ladder(str(path), strict=True)
    assert not path.exists()
    health = app._tp_execution_health([trade()], {}, "receiver target ledger unavailable")
    assert health["status"] == "warning"
    assert health["issues"][0]["status"] == "unavailable"
    assert app._tp_execution_health([], {}, "unavailable")["status"] == "ok"


@pytest.mark.parametrize("dry,status,expected", [(True, "critical", "yellow"),
                                               (False, "warning", "yellow")])
def test_dry_failures_and_execution_uncertainty_warn(monkeypatch, dry, status, expected):
    monkeypatch.setattr(app, "BOTS", [{"key": "bot"}])
    monkeypatch.setattr(app, "_cache", {
        "bots": {"bot": {"reachable": True, "dry_run": dry,
                         "execution_health": {"status": status}}},
        "last_reachable_at": {"bot": time.time()},
    })
    assert app._fleet_status()["level"] == expected


def test_cancelled_exit_on_open_trade_warns_without_rearming(tmp_path):
    path = tmp_path / 'receiver.sqlite'
    receiver_db(path, ['cancelled', 'cancelled'])
    assert app._tp_execution_health([trade()], app.killers_tp_ladder(str(path)))['status'] == 'warning'


def test_request_degradation_changes_green_fleet_to_yellow(monkeypatch, tmp_path):
    import json
    path = tmp_path / 'health.json'
    path.write_text(json.dumps({'observed_at': time.time(), 'complete': True,
       'gateway': {'observed_at': time.time(), 'status': 'warning', 'faults': 3}}))
    monkeypatch.setenv('ACCOUNT_HEALTH_FILE', str(path))
    monkeypatch.setattr(app, 'BOTS', [])
    assert app._fleet_status()['level'] == 'yellow'
    assert '3 failures' in app._fleet_status()['summary']
    path.unlink()
    assert app._fleet_status()['level'] == 'yellow'
