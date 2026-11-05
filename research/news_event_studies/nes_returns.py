"""Part C Phase 2 returns, criteria and verdict (#229). Pure functions (O2-O4, O13-O15).

Series rows: candle open ms -> [open, high, low, close] as the CSV strings. The leak test
uses Decimal on those strings. Returns, announcement means, medians, the concentration share
and every verdict comparison are exact Fractions built from those strings and from the frozen
constants as written; only reports convert them to float. The MAE stays float (descriptive).
"""
import math
import random
import statistics
from decimal import Decimal
from fractions import Fraction

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
# A4 (operator directive, 2026-11-05): every study reports estimates; no gate voids one.
HYPOTHESES = 3                     # the three studies; Bonferroni-adjusted two-sided intervals
CI_LEVEL = 1 - Fraction(5, 100) / HYPOTHESES

_STRENGTH = {"unresolved": 3, "missing": 2, "halted": 1, "ok": 0}   # O4, strongest first


def _q(constant):
    """A frozen constant as the exact decimal it is written as: 4.5 -> 9/2, 0.6 -> 3/5."""
    return Fraction(str(constant))


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
    return 2 * (_q(FEE_BPS[venue]) + _q(slip_bps)) / 10_000


def _sign(direction):
    return {"long": 1, "short": -1}[direction]


def _ratio(later, earlier):
    return Fraction(later) / Fraction(earlier) - 1


def net(entry, exit, direction, venue, slip_bps):
    return _sign(direction) * _ratio(exit, entry) - _cost(venue, slip_bps)


def mae_short(rows, entry_ms, exit_candle_ms, entry):
    opens = range(_floor(entry_ms) + nu.MINUTE_MS, exit_candle_ms + 1, nu.MINUTE_MS)
    highs = []
    for k in opens:
        if k not in rows:
            return None
        highs.append(float(rows[k][1]))
    return max(0.0, max(highs) / float(entry) - 1) if highs else 0.0


def _horizons(rows, absent, btc_rows, start_ms, entry, direction, venue, with_paths):
    out = {}
    for h, dt in HORIZONS_MS.items():
        status, px, k = exit_at(rows, start_ms + dt, absent)
        item = {"exit_status": status, "gross": None, "net": None, "net_stress": None,
                "btc_adj_net": None, "mae": None}
        if px is not None and entry is not None:
            raw = _ratio(px, entry)
            item.update(gross=_sign(direction) * raw, net=net(entry, px, direction, venue, SLIP_BPS),
                        net_stress=net(entry, px, direction, venue, STRESS_SLIP_BPS))
            if with_paths:
                b0, b1 = price_at(btc_rows, start_ms), btc_rows.get(k, [None] * 4)[3]
                if b0 is not None and b1 is not None:
                    item["btc_adj_net"] = (_sign(direction) * (raw - _ratio(b1, b0))
                                           - _cost(venue, SLIP_BPS))
                if direction == "short":
                    item["mae"] = mae_short(rows, start_ms, k, entry)
        out[h] = item
    return out


def evaluate(event, series, btc_series, direction, venue):
    """One token-event. `venue` is the suffix of its `candidate:<venue>` status."""
    rows, absent = series["rows"], series["absent_dates"]
    t0 = event["t0_ms"]
    base = {k: event[k] for k in ("announcement_id", "t0_ms", "token", "kind", "supplement") if k in event}
    base.update(direction=direction, venue=venue)
    leak = leaked(rows, t0)
    start = t0 + ENTRY_OFFSET_MS
    entry = price_at(rows, start)
    # Exit statuses do not depend on the entry candle; with no entry they carry no returns.
    horizons = _horizons(rows, absent, btc_series["rows"], start, entry, direction, venue, True)
    statuses = [h["exit_status"] for h in horizons.values()]
    statuses += ["missing"] if leak is None or entry is None else []
    status = max(statuses, key=_STRENGTH.get)     # O4: a missing leak or entry candle never hides unresolved
    t60 = {}
    entry60 = price_at(rows, t0 + T60_OFFSET_MS)
    if entry is not None and entry60 is not None:
        t60 = {h: v["net"] for h, v in _horizons(rows, absent, btc_series["rows"], t0 + T60_OFFSET_MS,
                                                  entry60, direction, venue, False).items()}
    return {**base, "status": status, "leaked": leak, "horizons": horizons, "t60": t60}


def _usable(r):
    return r["status"] in ("ok", "halted")


def announcements(results, horizon, include_leaked=False, key="net", allow_halted=True):
    """Eligibility is per horizon (A4): an unresolved 24 h exit no longer drops a valid 4 h return.
    The primary set needs the leak test to have run and passed; `include_leaked` takes every event."""
    ok = ("ok", "halted") if allow_halted else ("ok",)
    groups = {}
    for r in results:
        if not include_leaked and r["leaked"] is not False:
            continue
        hz = r["horizons"].get(horizon, {})
        v = hz.get(key)
        if hz.get("exit_status") not in ok or v is None:
            continue
        groups.setdefault((r["t0_ms"], r["announcement_id"]), []).append(Fraction(v))  # str when stored
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
    top = sum(sorted(values, reverse=True)[:math.ceil(n / 10)]) if n else 0
    share = top / total if total > 0 else None
    med = _median(values)
    return {"n": n, "median": med, "half_medians": halves, "sum": total, "top_decile_share": share,
            "passes": {"n": n >= MIN_ANN, "median": med is not None and med > 0,
                       "halves": all(m is not None and m > 0 for m in halves),
                       "concentration": share is not None and share < _q(TOP_DECILE_LT)}}


def coverage(counts, results):
    """O13: (unknown + missing + unresolved + shortfall) / (not rule-excluded + shortfall)."""
    phase2 = sum(r["status"] in ("missing", "unresolved") for r in results)
    shortfall = counts["harvest_shortfall"]
    num = counts["unknown"] + counts["missing"] + phase2 + shortfall
    den = counts["candidates"] + counts["unknown"] + counts["missing"] + shortfall
    return Fraction(num, den) if den else Fraction(1)


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
    if cov > _q(COVERAGE_GT):
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


# --- A4 estimates (operator directive, 2026-11-05) ------------------------------------

def _month(t0_ms):
    return nu.utc_date(t0_ms)[:7]


def block_bootstrap_mean_ci(anns, level=CI_LEVEL, n=BOOT_N, seed=BOOT_SEED):
    """Percentile interval of the announcement-level mean, resampling whole UTC calendar months
    (announcements in one month share a market regime). None with fewer than two months."""
    blocks = {}
    for t0, _aid, v in anns:
        blocks.setdefault(_month(t0), []).append(float(v))
    bl = [blocks[k] for k in sorted(blocks)]
    if len(bl) < 2:
        return None, None
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        pick = [x for b in rng.choices(bl, k=len(bl)) for x in b]
        means.append(sum(pick) / len(pick))
    means.sort()
    tail = float((1 - Fraction(level)) / 2)
    return means[max(0, math.ceil(tail * n) - 1)], means[min(n - 1, math.ceil((1 - tail) * n) - 1)]


def estimate(anns):
    values = [float(a[2]) for a in anns]
    lo, hi = block_bootstrap_mean_ci(anns)
    return {"n": len(values), "months": len({_month(a[0]) for a in anns}),
            "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "win_rate": sum(v > 0 for v in values) / len(values) if values else None,
            "ci": [lo, hi]}


def missing_announcements(results, horizon=PRIMARY):
    """Announcements in the primary population with no usable value at `horizon`: at least one
    token-event passed the leak test or could not be tested, and none yields a return."""
    have = {(a[0], a[1]) for a in announcements(results, horizon)}
    seen = {}
    for r in results:
        if r["leaked"] is not True:
            seen[(r["t0_ms"], r["announcement_id"])] = True
    return sorted(k for k in seen if k not in have)


def classify(results, horizon=PRIMARY):
    """A4 decision on the announcement-level mean net return at the primary horizon.

    EDGE (proxy): the adjusted interval of the stress-cost mean lies above zero.
    NO EDGE: the adjusted interval of the base-cost mean lies at or below zero.
    Otherwise NOT DETERMINABLE. A conclusion that flips when every missing announcement takes
    the worst observed value for it (min for EDGE, max for NO EDGE) is NOT DETERMINABLE too."""
    base, stress = announcements(results, horizon), announcements(results, horizon, key="net_stress")
    lo, _ = block_bootstrap_mean_ci(stress)
    _, hi = block_bootstrap_mean_ci(base)
    if lo is None or hi is None:
        return "NOT DETERMINABLE", ["fewer than two calendar months with a %s return" % horizon]
    missing = missing_announcements(results, horizon)
    if lo > 0:
        cls, check, key, pick = "EDGE (proxy)", lambda b: b[0] > 0, "net_stress", min
        anns = stress
    elif hi <= 0:
        cls, check, key, pick = "NO EDGE", lambda b: b[1] <= 0, "net", max
        anns = base
    else:
        return "NOT DETERMINABLE", ["%s mean interval spans zero (stress low %+.4f, base high %+.4f)"
                                    % (horizon, lo, hi)]
    reasons = ["%s mean interval: stress low %+.4f, base high %+.4f" % (horizon, lo, hi)]
    if missing:
        worst = pick(a[2] for a in anns)
        bound = block_bootstrap_mean_ci(anns + [(t0, aid, worst) for t0, aid in missing])
        if not check(bound):
            return "NOT DETERMINABLE", reasons + ["%d missing announcement(s) at the worst observed"
                                                  " value would reverse %s" % (len(missing), cls)]
        reasons.append("holds with %d missing announcement(s) at the worst observed value"
                       % len(missing))
    return cls, reasons
