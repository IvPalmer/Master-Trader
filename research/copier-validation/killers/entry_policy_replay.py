"""GROA-309 — Killers ENTRY-POLICY replay (research only; no live change).

Question: chase (marketable entry up to X% past the zone) vs wait for a pullback
limit at the zone top, vs wait-then-chase?  Preregistered in
ft_userdata/preregistrations.json  id=killers-entry-policy-replay-2026-10-13.

Everything but the entry is held fixed at the live production values
(ft_userdata/docker-compose.prod.yml, killers-receiver):
  posted stop, equal-slice posted-target ladder (first 8 targets), risk $12,
  margin $5..$40, integer leverage <=3, stop-limit ratio 0.98, venue min
  notional $11.3 for entry and $10 per ladder leg (slices that fall under it
  collapse into the next rung, as app/tp_plan.executable_targets does).

Data: 1m candles per signal, JSON [[ts_ms,o,h,l,c],...] in --cache DIR named
<SYMBOL>_<open_ms>.json (fetched from Binance USDT-M with --fetch if missing;
HL 1m can be dropped into the same files).  No network at import/test time.

Usage:  python entry_policy_replay.py --cache DIR [--fetch] [--out result.json]
"""
import argparse, json, math, os, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MIN = 60_000
HOUR = 3_600_000

# ── frozen parameters (see preregistration) ─────────────────────────────────
LATENCY_MS = 23_000            # lead-measured signal->fill latency (avg 23s)
HORIZON_D = 14
MAX_RUNGS = 8
RISK_USD, MIN_MARGIN, MAX_MARGIN, MAX_LEV = 12.0, 5.0, 40.0, 3
STOP_LIMIT_RATIO = 0.98
MIN_NOTIONAL_ENTRY, MIN_NOTIONAL_LEG = 11.3, 10.0
AMOUNT_RESERVE = 0.05
FEE_TAKER, FEE_MAKER = 0.00045, 0.00015      # Hyperliquid base tier
SLIPPAGES = (0.0, 0.005)
WAITS_H = (1, 4, 12, 24)
CHASE_CAPS = (0.05, 0.02, 0.01)
TRAIN_FRAC = 0.70


def policies():
    """name -> spec.  kind: chase | limit | wait_chase."""
    p = {f"chase<={int(c*100)}%": {"kind": "chase", "cap": c} for c in CHASE_CAPS}
    for w in WAITS_H:
        p[f"limit_{w}h"] = {"kind": "limit", "wait_h": w}
    for w in WAITS_H:
        p[f"wait_{w}h_then_chase<=2%"] = {"kind": "wait_chase", "wait_h": w, "cap": 0.02}
    return p


def ms(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def usable(sigs):
    return [s for s in sigs if s.get("entry_lo") and s.get("sl_initial")
            and s.get("tp_ladder") and s.get("direction") in ("long", "short")]


def prep(sig):
    """-> (is_long, bound, sl, targets) or None.  bound = zone top (long) / bottom (short)."""
    is_long = sig["direction"] == "long"
    bound = sig["entry_hi"] if is_long else sig["entry_lo"]
    sl = sig["sl_initial"]
    if bound is None or (is_long and not sl < bound) or (not is_long and not sl > bound):
        return None
    tps = sorted([t for t in sig["tp_ladder"] if isinstance(t, (int, float)) and t > 0
                  and (t > bound) == is_long], reverse=not is_long)[:MAX_RUNGS]
    if not tps:
        return None
    return is_long, bound, sl, tps


# ── sizing (mirror of services/killers-receiver compute_stake, hyperliquid) ──
def size(is_long, entry, sl):
    """-> (notional, leverage, sl_dist) or None when live would skip."""
    stop_fill = sl * (STOP_LIMIT_RATIO if is_long else 2 - STOP_LIMIT_RATIO)
    d = abs(entry - stop_fill) / entry
    if d <= 0:
        return None
    raw = RISK_USD / (MAX_MARGIN * d)
    if raw < 1.0:
        lev, stake = 1.0, RISK_USD / d
    else:
        lev = min(raw, MAX_LEV); stake = RISK_USD / (d * lev)
    notional = stake * lev
    lev = max(1, min(math.ceil(lev), MAX_LEV))
    stake = min(MAX_MARGIN, notional / lev)
    stake = math.floor(stake * 100) / 100
    if stake < MIN_MARGIN or stake * lev < MIN_NOTIONAL_ENTRY:
        return None
    return stake * lev, lev, d


def ladder_plan(notional, fill, targets, sl_dist_ratio):
    """Equal slices by target; a slice below the $10 leg minimum (or leaving a
    remainder below minimum*reserve) accumulates into the next rung.
    -> [(target_price, fraction)] summing to 1.  Mirrors tp_plan.executable_targets
    without lot-size rounding."""
    n = len(targets)
    reserve = min(1.5, max(1.0, (1 + AMOUNT_RESERVE) / (1 - min(sl_dist_ratio, 0.99))))
    qty = notional / fill
    out, allocated = [], 0.0
    for i, px in enumerate(targets):
        cum = (i + 1) / n
        amt = cum - allocated
        rem = 1.0 - cum
        if amt * qty * px < MIN_NOTIONAL_LEG:
            continue
        if rem > 1e-12 and rem * qty * px < MIN_NOTIONAL_LEG * reserve:
            continue
        out.append((px, amt)); allocated = cum
    if not out:
        return [(targets[-1], 1.0)]
    if allocated < 1.0 - 1e-9:                 # leftover goes to the last planned rung
        px, a = out[-1]; out[-1] = (px, a + 1.0 - allocated)
    return out


# ── entry policies ──────────────────────────────────────────────────────────
def _past(is_long, price, level):             # price beyond level on the adverse side
    return price > level if is_long else price < level


def find_entry(spec, is_long, bound, sl, tps, candles, t0):
    """-> dict(i, px, taker) or {"skip": reason}.  i = index of the fill candle."""
    first = next((i for i, c in enumerate(candles) if c[0] >= t0 + LATENCY_MS), None)
    if first is None:
        return {"skip": "no_data"}

    def chase(i, cap):
        px = candles[i][1]
        dev = (px - bound) / bound if is_long else (bound - px) / bound
        if cap is not None and dev > cap + 1e-12:
            return {"skip": "beyond_cap"}
        if (px <= sl) if is_long else (px >= sl):
            return {"skip": "past_stop"}
        if (px >= tps[-1]) if is_long else (px <= tps[-1]):
            return {"skip": "past_all_targets"}
        return {"i": i, "px": px, "taker": True, "dev": dev}

    kind = spec["kind"]
    if kind == "chase":
        return chase(first, spec.get("cap"))
    deadline = t0 + int(spec["wait_h"] * HOUR)
    for i in range(first, len(candles)):
        ts, o, h, l, c = candles[i]
        if ts >= deadline:
            break
        if (l <= bound) if is_long else (h >= bound):
            px = min(o, bound) if is_long else max(o, bound)   # gap-through fills at open
            if (px <= sl) if is_long else (px >= sl):
                return {"skip": "past_stop"}
            return {"i": i, "px": px, "taker": False, "dev": 0.0}
        if (l <= sl) if is_long else (h >= sl):                # stop level traded before fill
            return {"skip": "stop_before_fill"}
    if kind == "limit":
        return {"skip": "no_fill"}
    j = next((i for i in range(first, len(candles)) if candles[i][0] >= deadline), None)
    return {"skip": "no_data"} if j is None else chase(j, spec["cap"])


# ── trade walk ──────────────────────────────────────────────────────────────
def walk(is_long, fill, sl, plan, candles, i0, notional, taker_entry, slip, close_ms):
    """Adverse-first within a candle. Returns net $ pnl and exit reason."""
    pnl, reason, _ = walk_ex(is_long, fill, sl, plan, candles, i0, notional, taker_entry, slip, close_ms)
    return pnl, reason


def walk_ex(is_long, fill, sl, plan, candles, i0, notional, taker_entry, slip, close_ms):
    """walk() plus `first`: which of stop / tp1 was touched first (None if neither)."""
    first = None
    sgn = 1.0 if is_long else -1.0
    qty = notional / fill
    rem, pnl = 1.0, 0.0
    fees = (FEE_TAKER if taker_entry else FEE_MAKER) * notional
    k, reason = 0, "horizon"
    for ts, o, h, l, c in candles[i0:]:
        stopped = (l <= sl) if is_long else (h >= sl)
        if stopped:
            px = min(sl, o) if is_long else max(sl, o)
            px *= (1 - sgn * slip)                              # stop exits slip adversely
            pnl += rem * qty * sgn * (px - fill); fees += FEE_TAKER * rem * qty * px
            rem, reason = 0.0, "stop"; first = first or "stop"; break
        while k < len(plan) and ((h >= plan[k][0]) if is_long else (l <= plan[k][0])):
            f = plan[k][1]
            pnl += f * qty * sgn * (plan[k][0] - fill); fees += FEE_MAKER * f * qty * plan[k][0]
            rem -= f; k += 1; first = first or "tp1"
        if rem <= 1e-9:
            reason = "all_tp"; break
        if close_ms and ts >= close_ms:
            pnl += rem * qty * sgn * (c - fill); fees += FEE_TAKER * rem * qty * c
            rem, reason = 0.0, "channel_close"; break
    if rem > 1e-9:
        c = candles[-1][4]
        pnl += rem * qty * sgn * (c - fill); fees += FEE_TAKER * rem * qty * c
    return pnl - fees, reason, first


def run_signal(sig, candles, spec, slip):
    p = prep(sig)
    if not p:
        return {"skip": "incomplete"}
    is_long, bound, sl, tps = p
    t0 = ms(sig["open_date"])
    candles = [c for c in candles if c[0] >= t0 and c[0] <= t0 + HORIZON_D * 24 * HOUR]
    if len(candles) < 5:
        return {"skip": "no_data"}
    e = find_entry(spec, is_long, bound, sl, tps, candles, t0)
    if "skip" in e:
        return e
    sgn = 1.0 if is_long else -1.0
    fill = e["px"]
    if e["taker"]:
        fill *= 1 + sgn * slip                                  # marketable entries slip adversely
    live_tps = [t for t in tps if (t > fill) == is_long]
    if not live_tps:
        return {"skip": "past_all_targets"}
    sz = size(is_long, fill, sl)
    if not sz:
        return {"skip": "below_min_notional"}
    notional, lev, d = sz
    plan = ladder_plan(notional, fill, live_tps, abs(fill - sl) / fill * lev)
    close_ms = ms(sig["channel_close_date"]) if sig.get("channel_close_date") else None
    pnl, reason = walk(is_long, fill, sl, plan, candles, e["i"], notional, e["taker"], slip, close_ms)
    risk = notional * abs(fill - sl) / fill          # 1R = loss at the posted stop trigger
    return {"pnl": pnl, "R": pnl / risk, "risk": risk, "reason": reason, "dev": e["dev"],
            "t_fill_h": (candles[e["i"]][0] - t0) / HOUR, "open": sig["open_date"]}


# ── exit arm (GROA-309 amendment 1): signal = entry trigger only ───────────
ATR_N, BAR_MS, PRE_D, SWING_K, STRUCT_BUF = 14, 4 * HOUR, 8, 2, 0.001
R_MULTS = (1, 2, 3)
EXIT_ENTRY = {"kind": "chase", "cap": 0.05}          # live entry policy, so arms share fills
BASELINE = "live_posted"


def exit_variants():
    return {BASELINE: {"stop": "posted", "targets": "ladder"},
            "x1_atr1.5": {"stop": "atr", "k": 1.5, "targets": "R"},
            "x1_atr2.5": {"stop": "atr", "k": 2.5, "targets": "R"},
            "x2_struct": {"stop": "struct", "targets": "R"},
            "x3_posted_R": {"stop": "posted", "targets": "R"}}


def bars_4h(pre, t0):
    """Aggregate 1m candles into completed UTC-aligned 4h bars ending <= t0 -> [(ts,o,h,l,c)]."""
    b = {}
    for ts, o, h, l, c in pre:
        if ts >= t0:
            continue
        k = ts - ts % BAR_MS
        if k + BAR_MS > t0:
            continue
        if k not in b:
            b[k] = [k, o, h, l, c]
        else:
            x = b[k]; x[2] = max(x[2], h); x[3] = min(x[3], l); x[4] = c
    return [b[k] for k in sorted(b)]


def atr(bars, n=ATR_N):
    """Wilder ATR over the given bars; None if fewer than n+1 bars."""
    if len(bars) < n + 1:
        return None
    tr = [max(bars[i][2] - bars[i][3], abs(bars[i][2] - bars[i - 1][4]), abs(bars[i][3] - bars[i - 1][4]))
          for i in range(1, len(bars))]
    a = statistics.fmean(tr[:n])
    for t in tr[n:]:
        a = (a * (n - 1) + t) / n
    return a


def swing_stop(bars, is_long, fill):
    """Most recent confirmed 4h fractal (K bars each side) low (long) / high (short) beyond
    `fill`, pushed out by STRUCT_BUF.  None if there is none."""
    k = SWING_K
    for i in range(len(bars) - k - 1, k - 1, -1):
        w = bars[i - k:i + k + 1]
        if is_long:
            lv = bars[i][3]
            if lv == min(x[3] for x in w) and lv < fill:
                return lv * (1 - STRUCT_BUF)
        else:
            hv = bars[i][2]
            if hv == max(x[2] for x in w) and hv > fill:
                return hv * (1 + STRUCT_BUF)
    return None


def run_exit_signal(sig, candles, pre, xspec, slip):
    p = prep(sig)
    if not p:
        return {"skip": "incomplete"}
    is_long, bound, psl, tps = p
    t0 = ms(sig["open_date"])
    candles = [c for c in candles if t0 <= c[0] <= t0 + HORIZON_D * 24 * HOUR]
    if len(candles) < 5:
        return {"skip": "no_data"}
    e = find_entry(EXIT_ENTRY, is_long, bound, psl, tps, candles, t0)
    if "skip" in e:
        return e
    sgn = 1.0 if is_long else -1.0
    fill = e["px"] * (1 + sgn * slip)
    live_tps = [t for t in tps if (t > fill) == is_long]
    if not live_tps:
        return {"skip": "past_all_targets"}
    if xspec["stop"] == "posted":
        sl = psl
    else:
        bars = bars_4h(pre, t0)
        if xspec["stop"] == "atr":
            a = atr(bars)
            if a is None:
                return {"skip": "no_pre"}
            sl = fill - sgn * xspec["k"] * a
        else:
            sl = swing_stop(bars, is_long, fill)
            if sl is None:
                return {"skip": "no_structure"}
    if (sl >= fill) if is_long else (sl <= fill):
        return {"skip": "bad_stop"}
    sz = size(is_long, fill, sl)
    if not sz:
        return {"skip": "below_min_notional"}
    notional, lev, d = sz
    if xspec["targets"] == "ladder":
        targets = live_tps
    else:
        dist = abs(fill - sl)
        targets = [fill + sgn * m * dist for m in R_MULTS]
    plan = ladder_plan(notional, fill, targets, abs(fill - sl) / fill * lev)
    close_ms = ms(sig["channel_close_date"]) if sig.get("channel_close_date") else None
    pnl, reason, first = walk_ex(is_long, fill, sl, plan, candles, e["i"], notional, True, slip, close_ms)
    risk = notional * abs(fill - sl) / fill
    return {"pnl": pnl, "R": pnl / risk, "risk": risk, "reason": reason, "first": first,
            "stop_pct": abs(fill - sl) / fill, "open": sig["open_date"]}


def evaluate_exits(sigs, load, load_pre, n_trials):
    """Exit arm. n_trials = entry-arm trials + exit variants (preregistered, conservative)."""
    sigs = sorted(sigs, key=lambda s: s["open_date"])
    cut = int(len(sigs) * TRAIN_FRAC)
    split_of = {s["signal_id"]: ("early70" if i < cut else "late30") for i, s in enumerate(sigs)}
    cache = {s["signal_id"]: (load(s), load_pre(s)) for s in sigs}
    out = {"n_signals": len(sigs), "variants": {}, "n_trials": n_trials}
    for slip in SLIPPAGES:
        key = f"slip{slip}"
        for name, xs in exit_variants().items():
            res = {s["signal_id"]: run_exit_signal(s, *cache[s["signal_id"]], xs, slip) for s in sigs}
            elig = [i for i in res if res[i].get("skip") not in ("incomplete", "no_data")]
            fl = [res[i] for i in elig if "pnl" in res[i]]
            tp1 = sum(r["first"] == "tp1" for r in fl); st = sum(r["first"] == "stop" for r in fl)
            rec = {"eligible": len(elig), "fill_rate": len(fl) / len(elig) if elig else None,
                   "skip_reasons": _count(res[i]["skip"] for i in elig if "skip" in res[i]),
                   "all": metrics(fl),
                   "early70": metrics([res[i] for i in elig if "pnl" in res[i] and split_of[i] == "early70"]),
                   "late30": metrics([res[i] for i in elig if "pnl" in res[i] and split_of[i] == "late30"]),
                   "tp1_first": tp1, "stop_first": st,
                   "tp1_vs_stop_rate": tp1 / (tp1 + st) if tp1 + st else None,
                   "median_stop_pct": statistics.median([r["stop_pct"] for r in fl]) if fl else None,
                   "_Rs": [r["R"] for r in fl]}
            out["variants"].setdefault(name, {})[key] = rec
        stt = {n: sharpe_stats(v[key]["_Rs"]) for n, v in out["variants"].items()}
        var = statistics.pvariance([x["sr"] for x in stt.values() if x]) if sum(bool(x) for x in stt.values()) > 1 else 0.0
        for n, v in out["variants"].items():
            x = stt[n]; v[key]["dsr"] = None
            if x:
                prob, sr0 = deflated_sharpe(x["sr"], x["n"], x["skew"], x["kurt"], n_trials, var)
                v[key]["dsr"] = {"sr_per_trade": x["sr"], "dsr_prob": prob, "sr_benchmark": sr0, "n_trials": n_trials}
    for v in out["variants"].values():
        for r in v.values():
            r.pop("_Rs")
    return out


def report_exits(res):
    lines = ["\nEXIT ARM  (prior: 2026-05-28 found no edge; exits only changed loss size; any positive arm needs forward confirmation)"]
    for key in (f"slip{s}" for s in SLIPPAGES):
        lines.append(f"\n=== exits {key}  (N signals={res['n_signals']}) ===")
        lines.append(f"{'variant':<14}{'fill%':>6}{'n':>5}{'stop%':>7}{'tp1>stop':>9}{'expR':>8}{'exp$':>8}{'tot$':>9}"
                     f"{'PF':>6}{'maxDD$':>9}{'e70':>8}{'l30':>8}{'DSR':>6}")
        for n, v in res["variants"].items():
            r = v[key]; a = r["all"]
            if not a.get("n"):
                lines.append(f"{n:<14}  no fills"); continue
            f = lambda m: f"{m['exp_R']:+.3f}" if m.get("n") else "n/a"
            hr = "%.0f%%" % (r["tp1_vs_stop_rate"] * 100) if r["tp1_vs_stop_rate"] is not None else "n/a"
            dsr = "%.2f" % r["dsr"]["dsr_prob"] if r.get("dsr") else "n/a"
            lines.append(f"{n:<14}{r['fill_rate']*100:>6.0f}{a['n']:>5}{r['median_stop_pct']*100:>7.1f}{hr:>9}"
                         f"{a['exp_R']:>+8.3f}{a['exp_usd']:>+8.2f}{a['total_usd']:>+9.1f}{(a['pf'] or 0):>6.2f}"
                         f"{a['maxdd_usd']:>9.1f}{f(r['early70']):>8}{f(r['late30']):>8}{dsr:>6}")
    return "\n".join(lines)


# ── statistics ──────────────────────────────────────────────────────────────
def _norm_cdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def _norm_ppf(p):                                  # Acklam-free bisection; tiny and dependable
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _norm_cdf(mid) < p else (lo, mid)
    return (lo + hi) / 2


def sharpe_stats(rs):
    n = len(rs)
    if n < 3:
        return None
    m = statistics.fmean(rs); sd = statistics.pstdev(rs)
    if sd == 0:
        return None
    z = [(x - m) / sd for x in rs]
    return {"n": n, "sr": m / sd, "skew": sum(v ** 3 for v in z) / n,
            "kurt": sum(v ** 4 for v in z) / n}


def deflated_sharpe(sr, n, skew, kurt, n_trials, sr_var):
    """Bailey & Lopez de Prado DSR: P(true SR>0 | best of n_trials), per-trade SR units."""
    g = 0.5772156649
    sr0 = math.sqrt(max(sr_var, 1e-12)) * ((1 - g) * _norm_ppf(1 - 1 / n_trials)
          + g * _norm_ppf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return _norm_cdf((sr - sr0) * math.sqrt(n - 1) / den), sr0


def metrics(rows):
    if not rows:
        return {"n": 0}
    rows = sorted(rows, key=lambda r: r["open"])
    pn = [r["pnl"] for r in rows]; Rs = [r["R"] for r in rows]
    gw = sum(x for x in pn if x > 0); gl = -sum(x for x in pn if x < 0)
    eq = peak = dd = 0.0
    for x in pn:
        eq += x; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {"n": len(rows), "win": sum(x > 0 for x in pn) / len(pn), "exp_R": statistics.fmean(Rs),
            "exp_usd": statistics.fmean(pn), "total_usd": sum(pn),
            "pf": (gw / gl) if gl > 0 else None, "maxdd_usd": dd}


# ── driver ──────────────────────────────────────────────────────────────────
def evaluate(sigs, load, ref_name="uncapped_ref"):
    """sigs: usable signals; load(sig)->candles.  Returns full result dict."""
    sigs = sorted(sigs, key=lambda s: s["open_date"])
    cut = int(len(sigs) * TRAIN_FRAC)
    split_of = {s["signal_id"]: ("early70" if i < cut else "late30") for i, s in enumerate(sigs)}
    pol = policies()
    cache = {s["signal_id"]: load(s) for s in sigs}
    out = {"n_signals": len(sigs), "policies": {}}
    ref_spec = {"kind": "chase", "cap": None}
    for slip in SLIPPAGES:
        ref = {s["signal_id"]: run_signal(s, cache[s["signal_id"]], ref_spec, slip) for s in sigs}
        for name, spec in pol.items():
            res = {s["signal_id"]: run_signal(s, cache[s["signal_id"]], spec, slip) for s in sigs}
            elig = [sid for sid in res if res[sid].get("skip") not in ("incomplete", "no_data")]
            filled = [res[sid] for sid in elig if "pnl" in res[sid]]
            missed = [ref[sid] for sid in elig if "skip" in res[sid] and "pnl" in ref[sid]]
            rec = {"eligible": len(elig), "fill_rate": len(filled) / len(elig) if elig else None,
                   "skip_reasons": _count(res[sid]["skip"] for sid in elig if "skip" in res[sid]),
                   "all": metrics(filled),
                   "early70": metrics([res[s] for s in elig if "pnl" in res[s] and split_of[s] == "early70"]),
                   "late30": metrics([res[s] for s in elig if "pnl" in res[s] and split_of[s] == "late30"]),
                   "missed_n": len([sid for sid in elig if "skip" in res[sid]]),
                   "missed_if_uncapped": metrics(missed),
                   "_Rs": [r["R"] for r in filled]}
            out["policies"].setdefault(name, {})[f"slip{slip}"] = rec
    # DSR across all policies x slippage trials, per slippage level
    for slip in SLIPPAGES:
        key = f"slip{slip}"
        st = {n: sharpe_stats(p[key]["_Rs"]) for n, p in out["policies"].items()}
        srs = [v["sr"] for v in st.values() if v]
        var = statistics.pvariance(srs) if len(srs) > 1 else 0.0
        for n, p in out["policies"].items():
            v = st[n]
            p[key]["dsr"] = None
            if v:
                prob, sr0 = deflated_sharpe(v["sr"], v["n"], v["skew"], v["kurt"], len(pol), var)
                p[key]["dsr"] = {"sr_per_trade": v["sr"], "dsr_prob": prob, "sr_benchmark": sr0,
                                 "n_trials": len(pol)}
    for p in out["policies"].values():
        for r in p.values():
            r.pop("_Rs")
    return out


def _count(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


def fetch_1m(symbol, start_ms, end_ms):                         # VPS only; sandbox has no route
    import urllib.request, urllib.parse, time
    alias = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI", "BONK": "1000BONK", "GOLD": "XAUT"}
    sym = alias.get(symbol.upper(), symbol.upper()) + "USDT"
    out, cur = [], start_ms
    while cur < end_ms:
        q = urllib.parse.urlencode({"symbol": sym, "interval": "1m", "startTime": cur,
                                    "endTime": end_ms, "limit": 1500})
        rows = json.load(urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/klines?{q}", timeout=25))
        if not rows:
            break
        out += rows
        if len(rows) < 1500:
            break
        cur = rows[-1][0] + MIN; time.sleep(0.05)
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in out]


def make_loader(cache_dir, fetch=False):
    os.makedirs(cache_dir, exist_ok=True)
    def load(sig):
        t0 = ms(sig["open_date"])
        path = os.path.join(cache_dir, f"{sig['symbol']}_{t0}.json")
        if os.path.exists(path):
            return json.load(open(path))
        if not fetch:
            return []
        c = fetch_1m(sig["symbol"], t0 - MIN, t0 + HORIZON_D * 24 * HOUR)
        json.dump(c, open(path, "w"))
        return c
    return load


def make_pre_loader(cache_dir, fetch=False):
    """8 days of 1m before the signal, for ATR / swing structure (<SYMBOL>_<open_ms>_pre.json)."""
    os.makedirs(cache_dir, exist_ok=True)
    def load(sig):
        t0 = ms(sig["open_date"])
        path = os.path.join(cache_dir, f"{sig['symbol']}_{t0}_pre.json")
        if os.path.exists(path):
            return json.load(open(path))
        if not fetch:
            return []
        c = fetch_1m(sig["symbol"], t0 - PRE_D * 24 * HOUR, t0)
        json.dump(c, open(path, "w"))
        return c
    return load


def report(res):
    lines = []
    for key in (f"slip{s}" for s in SLIPPAGES):
        lines.append(f"\n=== {key}  (N signals={res['n_signals']}) ===")
        lines.append(f"{'policy':<24}{'fill%':>6}{'n':>5}{'expR':>8}{'exp$':>8}{'tot$':>9}{'PF':>6}{'maxDD$':>9}"
                     f"{'expR e70':>9}{'expR l30':>9}{'missed':>7}{'missWinR':>9}{'DSR':>6}")
        for n, p in res["policies"].items():
            r = p[key]; a = r["all"]
            if not a.get("n"):
                lines.append(f"{n:<24}  no fills"); continue
            f = lambda m: f"{m['exp_R']:+.3f}" if m.get("n") else "   n/a"
            mi = r["missed_if_uncapped"]
            miss_r = "%+.3f" % mi["exp_R"] if mi.get("n") else "n/a"
            dsr = "%.2f" % r["dsr"]["dsr_prob"] if r.get("dsr") else "n/a"
            lines.append(f"{n:<24}{r['fill_rate']*100:>6.0f}{a['n']:>5}{a['exp_R']:>+8.3f}{a['exp_usd']:>+8.2f}"
                         f"{a['total_usd']:>+9.1f}{(a['pf'] or 0):>6.2f}{a['maxdd_usd']:>9.1f}"
                         f"{f(r['early70']):>9}{f(r['late30']):>9}{r['missed_n']:>7}"
                         f"{miss_r:>9}{dsr:>6}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", default=os.path.join(HERE, "killers_signals.json"))
    ap.add_argument("--cache", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sigs = usable(json.load(open(a.signals)))
    load = make_loader(a.cache, a.fetch)
    res = evaluate(sigs, load)
    xres = evaluate_exits(sigs, load, make_pre_loader(a.cache, a.fetch),
                          n_trials=len(policies()) + len(exit_variants()) - 1)
    if a.out:
        json.dump({"entry_arm": res, "exit_arm": xres}, open(a.out, "w"), indent=1)
    print(report(res))
    print(report_exits(xres))


if __name__ == "__main__":
    main()
