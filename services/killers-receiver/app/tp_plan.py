"""Plan executable exits without increasing the filled position.

Small adjacent allocations accumulate at the last target in their group.
No allocation exits earlier than its original target. This deliberately
trades fewer targets when venue minimums make an equal-slice ladder invalid.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def _positive(value):
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError("expected a finite positive value")
    return number


def _step(precision, mode, contract_size=1):
    if mode == 4:  # CCXT TICK_SIZE
        step = _positive(precision)
    elif mode == 2:  # CCXT DECIMAL_PLACES
        digits = Decimal(str(precision))
        if not digits.is_finite() or digits != int(digits):
            raise ValueError("invalid decimal precision")
        step = Decimal(10) ** -int(digits)
    else:
        raise ValueError("unsupported or missing precision mode")
    return step * _positive(contract_size)


def executable_targets(trade, targets, min_notional):
    """Return (original target index, rounded price, base amount) groups.

    Metadata comes from the executor's trade snapshot, not inferred from
    displayed decimals. Missing metadata fails closed. Only completed entry
    fills may be allocated; a pending entry is not available inventory.
    """
    if not targets or int(trade.get("nr_of_successful_entries") or 0) < 1:
        return []
    if trade.get("is_open") is False:
        return []
    short = bool(trade.get("is_short"))
    entry_side = "sell" if short else "buy"
    if any(o.get("is_open") and o.get("ft_order_side") == entry_side
           for o in trade.get("orders", [])):
        return []
    quantum = _step(trade.get("amount_precision"), trade.get("precision_mode"),
                    trade.get("contract_size") or 1)
    price_step = _step(trade.get("price_precision"),
                       trade.get("precision_mode_price") or trade.get("precision_mode"))
    total = (_positive(trade.get("amount")) / quantum).to_integral_value(
        rounding=ROUND_FLOOR) * quantum
    minimum = _positive(min_notional)
    rounding = ROUND_FLOOR if short else ROUND_CEILING
    prices = [(_positive(p) / price_step).to_integral_value(rounding=rounding)
              * price_step for p in targets]
    if any(p <= 0 for p in prices):
        raise ValueError("target rounded to zero")
    if any((b > a if short else b < a) for a, b in zip(prices, prices[1:])):
        raise ValueError("targets must follow the position's profit direction")
    allocated = Decimal(0)
    plan = []
    for index, price in enumerate(prices):
        cumulative = (total * (index + 1) / len(prices) / quantum).to_integral_value(
            rounding=ROUND_FLOOR) * quantum
        amount = cumulative - allocated
        remainder = total - cumulative
        # Do not strand a final sub-minimum allocation. Keep accumulating
        # through the last target instead of selling its allocation early.
        if amount <= 0 or amount * price < minimum:
            continue
        if remainder and remainder * prices[-1] < minimum:
            continue
        plan.append((index, float(price), float(amount)))
        allocated = cumulative
    if allocated != total or not plan:
        raise ValueError("position cannot support executable target allocations")
    return plan
