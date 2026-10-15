import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ft_userdata" / "ft_dashboard"))

from hyperliquid_reconciliation import reconcile_trade  # noqa: E402


def test_reporting_reconciles_avax_stop_and_preserves_freqtrade_audit_value():
    fixture = json.loads(
        (ROOT / "tests/fixtures/hyperliquid_partial_tp_stop.json").read_text()
    )
    accounting = fixture["accounting"]
    raw_profit = -10.04074610245
    trade = {
        "trade_id": 16,
        "is_open": False,
        "is_short": False,
        "open_rate": accounting["open_rate"],
        "fee_open": accounting["fee_open"],
        "fee_close": accounting["fee_close"],
        "profit_abs": raw_profit,
        "orders": [{
            "order_id": fixture["stop_order"]["id"],
            "ft_order_side": "stoploss",
            "is_open": False,
            "filled": fixture["stop_order"]["filled"],
        }],
    }

    corrected = reconcile_trade(trade, fixture["exchange_fills"])

    assert corrected["profit_abs"] == pytest.approx(-8.72941658685)
    assert corrected["freqtrade_profit_abs"] == pytest.approx(raw_profit)
    assert corrected["hyperliquid_fill_mismatch"] is True
    assert corrected["stop_fill_overbooked"] is True
    order = corrected["hyperliquid_fill_reconciliation"]["orders"][0]
    assert order["order_kind"] == "stoploss"
    assert order["freqtrade_filled"] == pytest.approx(8.33)
    assert order["exchange_filled"] == pytest.approx(7.29)
    assert order["overbooked_quantity"] == pytest.approx(1.04)
    assert trade["profit_abs"] == raw_profit  # reporting copy only


def test_active_or_unidentified_orders_are_not_reconciled():
    trade = {
        "open_rate": 10,
        "fee_open": 0,
        "fee_close": 0,
        "profit_abs": -5,
        "orders": [{
            "order_id": "stop-1", "ft_order_side": "stoploss",
            "is_open": True, "status": "open", "filled": 2,
        }],
    }

    assert reconcile_trade(trade, [
        {"oid": "another-order", "sz": "1", "px": "8"}
    ]) == trade
    assert reconcile_trade(trade, []) == trade


def test_terminal_canceled_stop_with_reported_fill_uses_zero_userfills():
    trade = {
        "open_rate": 10,
        "fee_open": 0,
        "fee_close": 0,
        "profit_abs": -2,
        "orders": [{
            "order_id": "stop-canceled", "ft_order_side": "stoploss",
            "is_open": False, "status": "canceled", "filled": 1,
            "safe_price": 8,
        }],
    }

    corrected = reconcile_trade(trade, [])

    assert corrected["profit_abs"] == pytest.approx(0)
    assert corrected["hyperliquid_fill_mismatch"] is True
    assert corrected["stop_fill_overbooked"] is True
    order = corrected["hyperliquid_fill_reconciliation"]["orders"][0]
    assert order["order_status"] == "canceled"
    assert order["freqtrade_filled"] == 1
    assert order["exchange_filled"] == 0
    assert order["pnl_correction_status"] == "corrected"


def test_terminal_take_profit_sums_userfills_and_flags_either_direction():
    trade = {
        "open_rate": 10,
        "fee_open": 0,
        "fee_close": 0,
        "profit_abs": 1,
        "orders": [{
            "order_id": "tp-1", "ft_order_side": "sell",
            "is_open": False, "status": "closed", "filled": 0.5,
            "safe_price": 12,
        }],
    }

    corrected = reconcile_trade(trade, [
        {"oid": "tp-1", "sz": "0.4", "px": "12"},
        {"oid": "tp-1", "sz": "0.6", "px": "12"},
    ])

    assert corrected["profit_abs"] == pytest.approx(2)
    assert corrected["hyperliquid_fill_mismatch"] is True
    assert corrected["stop_fill_overbooked"] is False
    order = corrected["hyperliquid_fill_reconciliation"]["orders"][0]
    assert order["order_kind"] == "take_profit"
    assert order["freqtrade_filled"] == pytest.approx(0.5)
    assert order["exchange_filled"] == pytest.approx(1)
    assert order["quantity_difference"] == pytest.approx(0.5)


def test_terminal_short_take_profit_is_a_buy_but_entry_sell_is_ignored():
    trade = {
        "is_short": True,
        "open_rate": 10,
        "fee_open": 0,
        "fee_close": 0,
        "profit_abs": 1,
        "orders": [
            {"order_id": "entry", "ft_order_side": "sell", "is_open": False,
             "status": "closed", "filled": 1, "safe_price": 10},
            {"order_id": "tp", "ft_order_side": "buy", "is_open": False,
             "status": "canceled", "filled": 0.5, "safe_price": 8},
        ],
    }

    corrected = reconcile_trade(trade, [])

    assert corrected["profit_abs"] == pytest.approx(0)
    orders = corrected["hyperliquid_fill_reconciliation"]["orders"]
    assert [order["order_id"] for order in orders] == ["tp"]


def test_hyperliquid_native_userfills_shape_matches_oid():
    trade = {
        "open_rate": 10,
        "fee_open": 0,
        "fee_close": 0,
        "profit_abs": -4,
        "orders": [{
            "order_id": 1234, "ft_order_side": "stoploss",
            "is_open": False, "filled": 2,
        }],
    }
    corrected = reconcile_trade(trade, [
        {"oid": 1234, "sz": "0.4", "px": "8"},
        {"oid": 1234, "sz": "0.6", "px": "8"},
    ])
    assert corrected["profit_abs"] == pytest.approx(-2)
    assert corrected["hyperliquid_fill_reconciliation"]["orders"][0]["exchange_filled"] == 1
