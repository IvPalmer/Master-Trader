"""Read-only Hyperliquid stop-fill reconciliation for reporting.

Freqtrade/CCXT can report a reduce-only stop as filled for its original size
after partial take profits, even though Hyperliquid caps the execution at the
remaining position.  This module corrects copies of reporting records from
order-specific ``userFills`` rows.  It never mutates a database or submits an
exchange action, and it fails closed to the Freqtrade value when evidence is
missing or ambiguous.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Iterable


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _order_id(row: dict[str, Any]) -> str:
    value = row.get("oid", row.get("order_id", row.get("order", "")))
    return str(value) if value is not None else ""


def fills_by_order(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Index valid Hyperliquid/CCXT fill rows by exchange order id."""
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = _order_id(row)
        amount = _positive(row.get("sz", row.get("amount")))
        price = _positive(row.get("px", row.get("price")))
        if oid and amount is not None and price is not None:
            indexed.setdefault(oid, []).append(row)
    return indexed


def actual_order_fill(rows: Iterable[dict[str, Any]]) -> tuple[float, float]:
    """Return actual quantity and volume-weighted price for one order."""
    amounts: list[tuple[float, float]] = []
    for row in rows:
        amount = _positive(row.get("sz", row.get("amount")))
        price = _positive(row.get("px", row.get("price")))
        if amount is not None and price is not None:
            amounts.append((amount, price))
    if not amounts:
        raise ValueError("no valid order-specific fills")
    total = sum(amount for amount, _ in amounts)
    return total, sum(amount * price for amount, price in amounts) / total


def exit_pnl(
    amount: float,
    exit_price: float,
    open_rate: float,
    fee_open: float,
    fee_close: float,
    *,
    is_short: bool = False,
) -> float:
    """Mirror Freqtrade's per-exit valuation (funding stays in the raw total)."""
    open_value = amount * open_rate * (1 - fee_open if is_short else 1 + fee_open)
    close_value = amount * exit_price * (1 + fee_close if is_short else 1 - fee_close)
    return open_value - close_value if is_short else close_value - open_value


def reconcile_trade(
    trade: dict[str, Any], exchange_fills: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Return a reporting copy corrected for proven overbooked stop fills.

    The raw Freqtrade values remain under ``freqtrade_*`` fields.  No correction
    is made unless a terminal stop order has matching exchange executions and
    their summed quantity is smaller than Freqtrade's reported fill.
    """
    result = deepcopy(trade)
    try:
        raw_profit = float(trade["profit_abs"])
        open_rate = float(trade["open_rate"])
        fee_open = float(trade.get("fee_open") or 0)
        fee_close = float(trade.get("fee_close") or 0)
    except (KeyError, TypeError, ValueError):
        return result
    if not all(math.isfinite(v) for v in (raw_profit, open_rate, fee_open, fee_close)):
        return result

    indexed = fills_by_order(exchange_fills)
    corrections: list[dict[str, Any]] = []
    delta = 0.0
    for order in trade.get("orders") or []:
        if str(order.get("ft_order_side") or "").lower() != "stoploss":
            continue
        if order.get("is_open") is True:
            continue
        reported = _positive(order.get("filled"))
        oid = str(order.get("order_id", order.get("id", "")))
        if reported is None or not oid or oid not in indexed:
            continue
        actual, average = actual_order_fill(indexed[oid])
        tolerance = max(1e-10, reported * 1e-9)
        if actual >= reported - tolerance:
            continue
        reported_pnl = exit_pnl(
            reported, average, open_rate, fee_open, fee_close,
            is_short=bool(trade.get("is_short")),
        )
        actual_pnl = exit_pnl(
            actual, average, open_rate, fee_open, fee_close,
            is_short=bool(trade.get("is_short")),
        )
        delta += actual_pnl - reported_pnl
        corrections.append({
            "order_id": oid,
            "freqtrade_filled": reported,
            "exchange_filled": actual,
            "overbooked_quantity": reported - actual,
            "exchange_average": average,
            "freqtrade_stop_pnl": reported_pnl,
            "exchange_stop_pnl": actual_pnl,
        })

    if not corrections:
        return result
    result["freqtrade_profit_abs"] = raw_profit
    result["profit_abs"] = raw_profit + delta
    stake = _positive(trade.get("stake_amount"))
    if stake is not None:
        if trade.get("profit_ratio") is not None:
            try:
                raw_ratio = float(trade["profit_ratio"])
                result["freqtrade_profit_ratio"] = raw_ratio
                result["profit_ratio"] = raw_ratio + delta / stake
            except (TypeError, ValueError):
                pass
        if trade.get("profit_pct") is not None:
            try:
                raw_pct = float(trade["profit_pct"])
                result["freqtrade_profit_pct"] = raw_pct
                result["profit_pct"] = raw_pct + delta / stake * 100
            except (TypeError, ValueError):
                pass
    result["stop_fill_overbooked"] = True
    result["hyperliquid_stop_reconciliation"] = {
        "status": "corrected_from_user_fills",
        "freqtrade_profit_abs": raw_profit,
        "corrected_profit_abs": result["profit_abs"],
        "profit_adjustment": delta,
        "orders": corrections,
    }
    return result


def reconcile_trades(
    trades: Iterable[dict[str, Any]], exchange_fills: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    fills = list(exchange_fills)
    return [reconcile_trade(trade, fills) for trade in trades]
