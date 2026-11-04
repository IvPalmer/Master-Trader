"""Part C Phase 2 returns, criteria and verdict (#229). Pure functions (O2-O4, O13-O15).

Series rows: candle open ms -> [open, high, low, close] as the CSV strings. The leak test
uses Decimal on those strings; returns use float.
"""
import math
import random
import statistics
from decimal import Decimal

import nes_util as nu

ENTRY_OFFSET_MS = 300_000
T60_OFFSET_MS = 60_000
HORIZONS_MS = {"30m": 1_800_000, "4h": 14_400_000, "24h": 86_400_000}
PRIMARY = "4h"
FEE_BPS = {"hyperliquid": 4.5, "binance_spot": 7.5}
SLIP_BPS = 10
STRESS_SLIP_BPS = 25
LEAK_GT = Decimal("0.02")
LEAK_FROM_MS = -600_000
LEAK_TO_MS = -120_000
HALT_WINDOW_MS = 259_200_000
MIN_ANN = 20
TOP_DECILE_LT = 0.6
COVERAGE_GT = 0.2
BOOT_N = 10_000
BOOT_SEED = 229

_STRENGTH = {"unresolved": 3, "missing": 2, "halted": 1, "ok": 0}   # O4, strongest first


def _floor(ms):
    return ms - ms % nu.MINUTE_MS


def price_at(rows, instant_ms):
    candle = rows.get(_floor(instant_ms))
    return candle[3] if candle else None


def leaked(rows, t0_ms):
    early, late = price_at(rows, t0_ms + LEAK_FROM_MS), price_at(rows, t0_ms + LEAK_TO_MS)
    if early is None or late is None:
        return None
    return abs(Decimal(late) / Decimal(early) - 1) > LEAK_GT


def exit_at(rows, scheduled_ms, absent_dates=()):
    """O4: the scheduled candle, else the first candle opening in (scheduled, +72 h] (halted).

    A resumption candle with the scheduled candle's UTC-day file absent is an archive hole
    (missing); no resumption candle is unresolved."""
    first = _floor(scheduled_ms)
    if first in rows:
        return "ok", rows[first][3], first
    later = [k for k in rows if first < k <= first + HALT_WINDOW_MS]
    if not later:
        return "unresolved", None, None
    if nu.utc_date(first) in absent_dates:
        return "missing", None, None
    k = min(later)
    return "halted", rows[k][3], k


def _cost(venue, slip_bps):
    return 2 * (FEE_BPS[venue] + slip_bps) / 10_000


def _sign(direction):
    return {"long": 1, "short": -1}[direction]


def net(entry, exit, direction, venue, slip_bps):
    return _sign(direction) * (float(exit) / float(entry) - 1) - _cost(venue, slip_bps)


def mae_short(rows, entry_ms, exit_candle_ms, entry):
    opens = range(_floor(entry_ms) + nu.MINUTE_MS, exit_candle_ms + 1, nu.MINUTE_MS)
    highs = []
    for k in opens:
        if k not in rows:
            return None
        highs.append(float(rows[k][1]))
    return max(highs) / float(entry) - 1 if highs else 0.0


def _horizons(rows, absent, btc_rows, start_ms, entry, direction, venue, with_paths):
    out = {}
    for h, dt in HORIZONS_MS.items():
        status, px, k = exit_at(rows, start_ms + dt, absent)
        item = {"exit_status": status, "gross": None, "net": None, "net_stress": None,
                "btc_adj_net": None, "mae": None}
        if px is not None:
            raw = float(px) / float(entry) - 1
            item.update(gross=_sign(direction) * raw, net=net(entry, px, direction, venue, SLIP_BPS),
                        net_stress=net(entry, px, direction, venue, STRESS_SLIP_BPS))
            if with_paths:
                b0, b1 = price_at(btc_rows, start_ms), btc_rows.get(k, [None] * 4)[3]
                if b0 is not None and b1 is not None:
                    item["btc_adj_net"] = (_sign(direction) * (raw - (float(b1) / float(b0) - 1))
                                           - _cost(venue, SLIP_BPS))
                if direction == "short":
                    item["mae"] = mae_short(rows, start_ms, k, entry)
        out[h] = item
    return out


def evaluate(event, series, btc_series, direction, venue):
    """One token-event. `venue` is the suffix of its `candidate:<venue>` status."""
    rows, absent = series["rows"], series["absent_dates"]
    t0 = event["t0_ms"]
    base = {k: event[k] for k in ("announcement_id", "t0_ms", "token", "kind") if k in event}
    base.update(direction=direction, venue=venue)
    leak = leaked(rows, t0)
    start = t0 + ENTRY_OFFSET_MS
    entry = price_at(rows, start)
    if entry is None:
        return {**base, "status": "missing", "leaked": leak, "horizons": {}, "t60": {}}
    horizons = _horizons(rows, absent, btc_series["rows"], start, entry, direction, venue, True)
    statuses = [h["exit_status"] for h in horizons.values()] + (["missing"] if leak is None else [])
    status = max(statuses, key=_STRENGTH.get)     # a missing leak candle never hides unresolved
    t60 = {}
    entry60 = price_at(rows, t0 + T60_OFFSET_MS)
    if entry60 is not None:
        t60 = {h: v["net"] for h, v in _horizons(rows, absent, btc_series["rows"], t0 + T60_OFFSET_MS,
                                                  entry60, direction, venue, False).items()}
    return {**base, "status": status, "leaked": leak, "horizons": horizons, "t60": t60}


def _usable(r):
    return r["status"] in ("ok", "halted")


def announcements(results, horizon, include_leaked=False, key="net"):
    groups = {}
    for r in results:
        if not _usable(r) or (r["leaked"] and not include_leaked):
            continue
        v = r["horizons"].get(horizon, {}).get(key)
        if v is None:
            continue
        groups.setdefault((r["t0_ms"], r["announcement_id"]), []).append(v)
    return [(t0, aid, sum(vs) / len(vs)) for (t0, aid), vs in sorted(groups.items())]


def _median(values):
    return statistics.median(values) if values else None


def criteria(anns):
    anns = sorted(anns, key=lambda a: (a[0], a[1]))
    values = [a[2] for a in anns]
    n = len(values)
    half = n // 2
    halves = [_median(values[:half]), _median(values[half:])]
    total = sum(values)
    top = sum(sorted(values, reverse=True)[:math.ceil(n / 10)]) if n else 0.0
    share = top / total if total > 0 else None
    med = _median(values)
    return {"n": n, "median": med, "half_medians": halves, "sum": total, "top_decile_share": share,
            "passes": {"n": n >= MIN_ANN, "median": med is not None and med > 0,
                       "halves": all(m is not None and m > 0 for m in halves),
                       "concentration": share is not None and share < TOP_DECILE_LT}}


def coverage(counts, results):
    """O13: (unknown + missing + unresolved + shortfall) / (not rule-excluded + shortfall)."""
    phase2 = sum(r["status"] in ("missing", "unresolved") for r in results)
    shortfall = counts["harvest_shortfall"]
    num = counts["unknown"] + counts["missing"] + phase2 + shortfall
    den = counts["candidates"] + counts["unknown"] + counts["missing"] + shortfall
    return num / den if den else 1.0


def verdict(counts, results):
    reasons, verdicts = [], []
    if not counts["harvest_complete"]:
        reasons.append("harvest incomplete")
        verdicts.append("INCONCLUSIVE-by-data")
    unresolved = sum(r["status"] == "unresolved" for r in results)
    if unresolved:
        reasons.append("%d unresolved post-entry event(s)" % unresolved)
        verdicts.append("INCONCLUSIVE")
    cov = coverage(counts, results)
    if cov > COVERAGE_GT:
        reasons.append("coverage %.4f > %s" % (cov, COVERAGE_GT))
        verdicts.append("INCONCLUSIVE-by-data")
    c = criteria(announcements(results, PRIMARY))
    if c["n"] < MIN_ANN:
        reasons.append("n %d < %d announcements" % (c["n"], MIN_ANN))
        verdicts.append("INCONCLUSIVE-by-data")
    failed = [k for k in ("median", "halves", "concentration") if not c["passes"][k]]
    reasons += ["criterion failed: %s" % k for k in failed]
    if verdicts:
        return verdicts[0], reasons
    if failed:
        return "FAIL", reasons
    return "PASS", reasons or ["all four criteria pass"]


def bootstrap_median_ci(values, n=BOOT_N, seed=BOOT_SEED):
    if not values:
        return None, None
    rng = random.Random(seed)
    meds = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(n))
    return meds[math.ceil(0.025 * n) - 1], meds[math.ceil(0.975 * n) - 1]
