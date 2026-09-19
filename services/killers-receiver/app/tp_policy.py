"""Explicit source-price exit allocations. Never move an allocation to a later TP."""
from decimal import Decimal, ROUND_FLOOR

from .tp_plan import _positive, _step, _partial_exit_reserve


def parse_policy(value):
    """One-based source index:percentage, e.g. 1:50,2:30,3:20.

    Empty preserves the existing epoch. A configured policy has no fallback.
    """
    if not value.strip():
        return None
    try:
        entries = [part.split(":") for part in value.split(",")]
        policy = [(int(index), _positive(weight)) for index, weight in entries]
        indices = [i for i, _ in policy]
        if (not indices or indices[0] < 1 or indices != sorted(set(indices))
                or sum(w for _, w in policy) != 100):
            raise ValueError()
    except (ValueError, ArithmeticError, TypeError):
        raise ValueError("TP allocation must use increasing source indices and positive percentages totaling 100") from None
    return [(i, str(w)) for i, w in policy]


def snapshot_policy(policy, source_targets, entry, short):
    """Freeze original indices and prices before entry; crossed targets are not renumbered."""
    entry = _positive(entry)
    rows = []
    for index, weight in policy:
        if index > len(source_targets):
            raise ValueError("selected source target is missing")
        price = _positive(source_targets[index - 1])
        if (price >= entry if short else price <= entry):
            raise ValueError("selected source target is already crossed")
        rows.append({"idx": index - 1, "price": str(price), "weight": weight})
    prices = [Decimal(r["price"]) for r in rows]
    if any((b >= a if short else b <= a) for a, b in zip(prices, prices[1:])):
        raise ValueError("selected source targets must be strictly ordered")
    return {"version": 1, "mode": "source_allocations", "targets": rows}


def allocate(policy, amount, minimum, reserve, quantum=None):
    """Validate each order and remainder at its order price, including final short exits."""
    if policy.get("version") != 1 or policy.get("mode") != "source_allocations":
        raise ValueError("unsupported TP policy snapshot")
    total = _positive(amount)
    if quantum is not None:
        total = (total / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
    cumulative_weight = Decimal(0)
    allocated = Decimal(0)
    plan = []
    for row in policy["targets"]:
        cumulative_weight += _positive(row["weight"])
        cumulative = total * cumulative_weight / 100
        if quantum is not None:
            cumulative = (cumulative / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
        quantity = cumulative - allocated
        price = _positive(row["price"])
        remainder = total - cumulative
        if quantity <= 0 or quantity * price < minimum:
            raise ValueError("selected TP allocation is below venue minimum")
        if remainder and remainder * price < minimum * reserve:
            raise ValueError("selected TP leaves a remainder below Freqtrade minimum")
        plan.append((row["idx"], float(price), float(quantity)))
        allocated = cumulative
    if not plan or cumulative_weight != 100 or allocated != total:
        raise ValueError("TP allocations must exhaust filled inventory")
    return plan


def preflight(policy, notional, entry):
    # No venue precision before the fill: necessary notional check only.
    # The conservative maximum FT reserve prevents knowingly unfundable entries.
    return allocate(policy, _positive(notional) / _positive(entry), Decimal(10), Decimal("1.5"))


def executable_source_targets(trade, policy):
    side = "sell" if trade.get("is_short") else "buy"
    if (trade.get("is_open") is False or int(trade.get("nr_of_successful_entries") or 0) < 1
            or any(o.get("is_open") and o.get("ft_order_side") == side for o in trade.get("orders", []))):
        return []
    quantum = _step(trade.get("amount_precision"), trade.get("precision_mode"), trade.get("contract_size") or 1)
    price_step = _step(trade.get("price_precision"), trade.get("precision_mode_price") or trade.get("precision_mode"))
    # Exact posted prices only: no hidden price rounding in this policy.
    for row in policy["targets"]:
        if _positive(row["price"]) % price_step:
            raise ValueError("posted TP price does not fit venue precision")
    return allocate(policy, trade.get("amount"), Decimal(10), _partial_exit_reserve(trade, .05), quantum)


def snapshot_nearby(source_targets, entry, short):
    """Freeze the nearest still-ahead source candidates; never choose a later price to fit size."""
    reference = _positive(entry)
    prices = [_positive(p) for p in source_targets]
    if any((b >= a if short else b <= a) for a, b in zip(prices, prices[1:])):
        raise ValueError('source targets must be strictly ordered')
    rows = [{'idx':i, 'price':str(p)} for i, p in enumerate(prices)
            if (p < reference if short else p > reference)][:2]
    if not rows:
        raise ValueError('no eligible source targets')
    return {'version':1, 'mode':'nearest_source', 'targets':rows}


def nearby_allocations(trade, policy):
    """Closest pair with a roughly half split, or full exit at the FIRST candidate."""
    from decimal import ROUND_CEILING
    if policy.get('version') != 1 or policy.get('mode') != 'nearest_source':
        raise ValueError('unsupported nearby policy')
    side = 'sell' if trade.get('is_short') else 'buy'
    if (trade.get('is_open') is False or int(trade.get('nr_of_successful_entries') or 0) < 1
            or any(o.get('is_open') and o.get('ft_order_side') == side for o in trade.get('orders', []))):
        return []
    q = _step(trade.get('amount_precision'), trade.get('precision_mode'), trade.get('contract_size') or 1)
    tick = _step(trade.get('price_precision'), trade.get('precision_mode_price') or trade.get('precision_mode'))
    total = (_positive(trade.get('amount')) / q).to_integral_value(rounding=ROUND_FLOOR) * q
    rows = policy['targets']
    if not 1 <= len(rows) <= 2:
        raise ValueError('expected one or two nearby candidates')
    first = _positive(rows[0]['price'])
    mark = _positive(trade.get('current_rate'))
    if (first >= mark if trade.get('is_short') else first <= mark):
        raise ValueError('first selected target already crossed; review required')
    if any(_positive(row['price']) % tick for row in rows):
        raise ValueError('posted TP price does not fit venue precision')
    minimum = Decimal(10)
    if total * first < minimum:
        raise ValueError('whole position below minimum at first target')
    full = [(rows[0]['idx'], float(first), float(total))]
    if len(rows) == 1:
        return full
    second = _positive(rows[1]['price'])
    if (second >= first if trade.get('is_short') else second <= first):
        raise ValueError('nearby candidates out of order')
    ceil = lambda v: (v / q).to_integral_value(rounding=ROUND_CEILING) * q
    smallest_exit = ceil(minimum / first)
    smallest_remainder = max(ceil(minimum * _partial_exit_reserve(trade, .05) / first), ceil(minimum / second))
    largest_exit = total - smallest_remainder
    if smallest_exit > largest_exit:
        return full
    half = (total / 2 / q).to_integral_value(rounding=ROUND_FLOOR) * q
    quantity = min(largest_exit, max(smallest_exit, half))
    return [(rows[0]['idx'], float(first), float(quantity)),
            (rows[1]['idx'], float(second), float(total - quantity))]
