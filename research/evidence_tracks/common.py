"""Shared pieces for the GH #28 evidence tracks. Research only: nothing here
touches a deployed strategy, config, allocation or order path."""
import random
from datetime import datetime, timezone


def parse_ts(value) -> datetime:
    """ISO-8601 / 'YYYY-MM-DD HH:MM:SS' -> aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def assign_epoch(ts, epochs):
    """Epoch whose start is the latest one <= ts; None before the first epoch.

    ``epochs`` is [(name, start_iso), ...]. Boundaries are frozen in the
    preregistration; a trade is never re-labelled because of its outcome.
    """
    t = parse_ts(ts)
    label = None
    for name, start in sorted(epochs, key=lambda e: parse_ts(e[1])):
        if parse_ts(start) <= t:
            label = name
    return label


def metrics(pnls):
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    return {"trades": len(pnls), "net": round(sum(pnls), 6),
            "profit_factor": (round(wins / losses, 3) if losses else (None if not wins else "inf")),
            "win_rate": round(sum(p > 0 for p in pnls) / len(pnls), 3) if pnls else None}


def block_bootstrap_p_better(daily_a, daily_b, block=7, n=5000, seed=28):
    """P(sum A > sum B) resampling contiguous day blocks of the paired series.

    daily_a / daily_b: {date_str: pnl}. Missing days count as 0 so the two arms
    share one calendar. Returns None when there are no days.
    """
    days = sorted(set(daily_a) | set(daily_b))
    if not days:
        return None
    diff = [daily_a.get(d, 0.0) - daily_b.get(d, 0.0) for d in days]
    rng = random.Random(seed)
    starts = range(len(diff))
    k = max(1, -(-len(diff) // block))
    better = 0
    for _ in range(n):
        total = 0.0
        for _ in range(k):
            s = rng.choice(starts)
            total += sum(diff[s:s + block])
        better += total > 0
    return better / n


def _pct(sorted_values, q):
    return sorted_values[int(q * (len(sorted_values) - 1))]


def control_reading_rule(summary, gate, control, placebo_prefix, parts=("half1", "half2")):
    """Gate shows discriminative power only if it beats the price-only control AND
    the 90th percentile of the placebo distribution on profit factor and net, in
    every part. Anything else is "not demonstrated". "inf" PF compares as infinite.
    """
    def num(x):
        return float("inf") if x == "inf" else x

    placebos = [v for k, v in summary.items() if k.startswith(placebo_prefix)]
    verdict = {}
    for part in parts:
        row = {}
        for m in ("profit_factor", "net"):
            g, c = summary[gate][part][m], summary[control][part][m]
            pv = sorted(num(p[part][m]) for p in placebos if p[part][m] is not None)
            p90 = _pct(pv, 0.9) if pv else None
            ok = (g is not None and c is not None and p90 is not None
                  and num(g) > num(c) and num(g) > p90)
            row[m] = {"gate": g, "price_only": c, "placebo_p90": p90, "beats_control_and_p90": ok}
        verdict[part] = row
    shown = all(verdict[p][m]["beats_control_and_p90"] for p in parts for m in ("profit_factor", "net"))
    return {"by_part": verdict, "discriminative_power": "demonstrated" if shown else "not demonstrated"}
