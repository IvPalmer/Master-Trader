#!/usr/bin/env python3
"""Reconcile a Hyperliquid stop order with its order-specific executions.

This is an offline diagnostic for GH #184.  It does not connect to an exchange
or mutate a Freqtrade database.  Input must be a sanitized JSON object with a
CCXT-normalized ``stop_order``, its ``exchange_fills``, and optional trade
accounting inputs.  See ``tests/fixtures/hyperliquid_partial_tp_stop.json``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def actual_order_fill(order_id: str, fills: list[dict[str, Any]]) -> tuple[float, float]:
    """Return actual quantity and volume-weighted price for one order's fills."""
    matched: list[tuple[float, float]] = []
    for fill in fills:
        fill_order_id = str(fill.get("order_id", fill.get("order", "")))
        if fill_order_id != str(order_id):
            continue
        amount = _finite_number(fill.get("amount"), "exchange fill amount")
        price = _finite_number(fill.get("price"), "exchange fill price")
        if amount <= 0 or price <= 0:
            raise ValueError("exchange fill amount and price must be positive")
        matched.append((amount, price))
    if not matched:
        raise ValueError(f"no exchange fills found for order {order_id}")
    amount = sum(item[0] for item in matched)
    return amount, sum(qty * price for qty, price in matched) / amount


def ccxt_454_status_fill(order_status: dict[str, Any]) -> float:
    """Reproduce CCXT 4.5.4's Hyperliquid ``origSz - sz`` parsing."""
    entry = order_status.get("order", order_status)
    original = _finite_number(entry.get("origSz"), "order status origSz")
    remaining = _finite_number(entry.get("sz"), "order status sz")
    return original - remaining


def exit_pnl(
    amount: float,
    exit_price: float,
    open_rate: float,
    fee_open: float,
    fee_close: float,
    *,
    is_short: bool = False,
    funding_fee: float = 0.0,
) -> float:
    """Mirror Freqtrade's per-exit value calculation used by GH #184's replay."""
    open_value = amount * open_rate * (1 - fee_open if is_short else 1 + fee_open)
    close_value = amount * exit_price * (1 + fee_close if is_short else 1 - fee_close)
    pnl = open_value - close_value if is_short else close_value - open_value
    return pnl + funding_fee


def audit(payload: dict[str, Any]) -> dict[str, Any]:
    order = payload["stop_order"]
    order_id = str(order["id"])
    reported = _finite_number(order.get("filled"), "reported stop fill")
    actual, average = actual_order_fill(order_id, payload["exchange_fills"])

    result: dict[str, Any] = {
        "order_id": order_id,
        "reported_filled": reported,
        "exchange_filled": actual,
        "exchange_average": average,
        "overbooked_quantity": max(0.0, reported - actual),
        "is_overbooked": reported > actual,
    }

    raw_status = payload.get("hyperliquid_order_status")
    if raw_status:
        ccxt_filled = ccxt_454_status_fill(raw_status)
        if not math.isclose(ccxt_filled, reported):
            raise ValueError("normalized stop fill does not match the CCXT 4.5.4 replay")
        result["ccxt_4_5_4_filled"] = ccxt_filled

    accounting = payload.get("accounting")
    if accounting:
        open_rate = _finite_number(accounting["open_rate"], "open_rate")
        fee_open = _finite_number(accounting.get("fee_open", 0), "fee_open")
        fee_close = _finite_number(accounting.get("fee_close", 0), "fee_close")
        is_short = bool(accounting.get("is_short", False))
        prior_pnl = 0.0
        for index, item in enumerate(accounting.get("prior_exits", [])):
            prior_pnl += exit_pnl(
                _finite_number(item["amount"], f"prior_exits[{index}].amount"),
                _finite_number(item["price"], f"prior_exits[{index}].price"),
                open_rate,
                fee_open,
                fee_close,
                is_short=is_short,
                funding_fee=_finite_number(
                    item.get("funding_fee", 0), f"prior_exits[{index}].funding_fee"
                ),
            )
        result["reported_replay_profit_abs"] = prior_pnl + exit_pnl(
            reported, average, open_rate, fee_open, fee_close, is_short=is_short
        )
        result["exchange_replay_profit_abs"] = prior_pnl + exit_pnl(
            actual, average, open_rate, fee_open, fee_close, is_short=is_short
        )
        result["reported_minus_exchange_profit_abs"] = (
            result["reported_replay_profit_abs"] - result["exchange_replay_profit_abs"]
        )
        result["loss_overstatement_abs"] = max(
            0.0, -result["reported_minus_exchange_profit_abs"]
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="sanitized JSON replay input")
    args = parser.parse_args()
    result = audit(json.loads(args.input.read_text()))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["is_overbooked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
