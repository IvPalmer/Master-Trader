"""Read-only Hyperliquid exit-fill reconciliation for reporting.

Freqtrade/CCXT can report terminal reduce-only stop and take-profit orders with
the wrong filled size.  This module corrects copies of reporting records from
the sum of order-specific ``userFills`` rows.  It never mutates a database or
submits an exchange action.  A successful, possibly empty, ``userFills`` result
is authoritative; malformed matching rows are ignored instead of producing a
guessed zero fill or P&L correction.
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


def _nonnegative(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _order_id(row: dict[str, Any]) -> str:
    value = row.get("oid", row.get("order_id", row.get("order", "")))
    return str(value) if value is not None else ""


def fills_by_order(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Index Hyperliquid/CCXT fill rows by exchange order id."""
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = _order_id(row)
        if oid:
            indexed.setdefault(oid, []).append(row)
    return indexed


def actual_order_fill(rows: Iterable[dict[str, Any]]) -> tuple[float, float | None]:
    """Return actual quantity and volume-weighted price for one order.

    No rows means a proven zero fill when the caller successfully fetched the
    wallet's ``userFills``.  Rows for the order with unusable values are
    ambiguous and raise instead of being silently treated as zero.
    """
    amounts: list[tuple[float, float]] = []
    saw_row = False
    for row in rows:
        saw_row = True
        amount = _positive(row.get("sz", row.get("amount")))
        price = _positive(row.get("px", row.get("price")))
        if amount is None or price is None:
            raise ValueError("invalid order-specific fill")
        amounts.append((amount, price))
    if not amounts:
        if saw_row:
            raise ValueError("no valid order-specific fills")
        return 0.0, None
    total = sum(amount for amount, _ in amounts)
    return total, sum(amount * price for amount, price in amounts) / total


def _terminal_exit_kind(order: dict[str, Any], *, is_short: bool) -> str | None:
    """Classify a terminal Freqtrade order as a stop or ordinary exit."""
    if order.get("is_open") is True:
        return None
    status = str(order.get("status") or "").lower()
    if order.get("is_open") is not False and status not in {
        "closed", "canceled", "cancelled", "rejected", "expired",
    }:
        return None
    side = str(order.get("ft_order_side") or "").lower()
    if side == "stoploss":
        return "stoploss"
    if side == ("buy" if is_short else "sell"):
        return "take_profit"
    return None


def _reported_exit_price(order: dict[str, Any]) -> float | None:
    """Return Freqtrade's best available price for a zero-fill mismatch."""
    for field in ("safe_price", "average", "price", "stop_price"):
        price = _positive(order.get(field))
        if price is not None:
            return price
    return None


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
    """Return a reporting copy reconciled to terminal exit ``userFills``.

    The raw Freqtrade values remain under ``freqtrade_*`` fields.  Stop and
    take-profit orders are compared in both directions, including a canceled
    order whose reported fill is non-zero but whose ``userFills`` sum is zero.
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
    correction_complete = True
    is_short = bool(trade.get("is_short"))
    for order in trade.get("orders") or []:
        kind = _terminal_exit_kind(order, is_short=is_short)
        if kind is None:
            continue
        reported = _nonnegative(order.get("filled"))
        oid = str(order.get("order_id", order.get("id", "")))
        if reported is None or not oid:
            continue
        try:
            actual, exchange_average = actual_order_fill(indexed.get(oid, []))
        except ValueError:
            continue
        tolerance = max(1e-10, max(reported, actual) * 1e-9)
        if math.isclose(actual, reported, rel_tol=0.0, abs_tol=tolerance):
            continue
        price = exchange_average or _reported_exit_price(order)
        record = {
            "order_id": oid,
            "order_kind": kind,
            "order_status": order.get("status"),
            "fill_mismatch": True,
            "freqtrade_filled": reported,
            "exchange_filled": actual,
            "quantity_difference": actual - reported,
            "overbooked_quantity": max(0.0, reported - actual),
            "exchange_average": exchange_average,
        }
        if price is None:
            correction_complete = False
            record["pnl_correction_status"] = "unavailable_missing_price"
        else:
            reported_pnl = exit_pnl(
                reported, price, open_rate, fee_open, fee_close,
                is_short=is_short,
            )
            actual_pnl = exit_pnl(
                actual, price, open_rate, fee_open, fee_close,
                is_short=is_short,
            )
            delta += actual_pnl - reported_pnl
            record.update({
                "reconciliation_price": price,
                "freqtrade_exit_pnl": reported_pnl,
                "exchange_exit_pnl": actual_pnl,
                # Kept for existing audit clients of the original stop-only API.
                "freqtrade_stop_pnl": reported_pnl,
                "exchange_stop_pnl": actual_pnl,
                "pnl_correction_status": "corrected",
            })
        corrections.append(record)

    if not corrections:
        return result
    result["freqtrade_profit_abs"] = raw_profit
    if correction_complete:
        result["profit_abs"] = raw_profit + delta
    stake = _positive(trade.get("stake_amount"))
    if correction_complete and stake is not None:
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
    result["hyperliquid_fill_mismatch"] = True
    result["stop_fill_overbooked"] = any(
        row["order_kind"] == "stoploss" and row["freqtrade_filled"] > row["exchange_filled"]
        for row in corrections
    )
    reconciliation = {
        "status": (
            "corrected_from_user_fills" if correction_complete
            else "fill_mismatch_unpriced"
        ),
        "profit_correction_complete": correction_complete,
        "freqtrade_profit_abs": raw_profit,
        "corrected_profit_abs": result["profit_abs"],
        "profit_adjustment": delta if correction_complete else None,
        "orders": corrections,
    }
    result["hyperliquid_fill_reconciliation"] = reconciliation
    # Backward-compatible alias for clients deployed with the stop-only version.
    result["hyperliquid_stop_reconciliation"] = reconciliation
    return result


def reconcile_trades(
    trades: Iterable[dict[str, Any]], exchange_fills: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    fills = list(exchange_fills)
    return [reconcile_trade(trade, fills) for trade in trades]
