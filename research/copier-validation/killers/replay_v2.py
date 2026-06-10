"""Tightened SL replay v2 — accurate liquidation + strategy/leverage sweep.

Improvements over v1 (codex-flagged):
  - liquidation detected on Binance MARK-price klines (not trade-candle wicks).
  - 5m granularity (was 15m) → tighter TP/SL touch ordering.
  - channel_only residual closes at the channel's LAST logged event (208/278
    trades have one) instead of riding a 45d horizon — far more realistic.
  - sweeps a MATRIX of SL strategies x leverage, not just on/off.

Shared by all strategies: limit-in-zone entry (near edge, 72h) + posted TP ladder
(equal-weight partial exits). Strategies differ only in the residual STOP rule.
Liquidation (isolated, ~1/LEV adverse on MARK price) always applies. Returns in
margin units (1.0 = +100% of one position's margin). Taker fee 0.04%/side.
"""
import json, os, time, urllib.request, urllib.parse
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "klines_cache_v2")
os.makedirs(CACHE, exist_ok=True)

ENTRY_WINDOW_H = 72
FETCH_D = 45
HORIZON_D = int(os.environ.get("HORIZON_D", "45"))
FEE = 0.0004
TF = "5m"
TF_MS = 5 * 60 * 1000
ALIAS = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI", "BONK": "1000BONK", "GOLD": "XAUT"}

def fsym(s): return ALIAS.get(s.upper(), s.upper()) + "USDT"
def dt(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def ms(s): return int(dt(s).timestamp() * 1000)

def fetch(symbol, start_ms, end_ms, mark=False):
    ep = "markPriceKlines" if mark else "klines"
    cp = os.path.join(CACHE, f"{'m' if mark else 'l'}_{symbol}_{start_ms}_{end_ms}.json")
    if os.path.exists(cp):
        return json.load(open(cp))
    out, cur = [], start_ms
    while cur < end_ms:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": TF, "startTime": cur, "endTime": end_ms, "limit": 1500})
        try:
            req = urllib.request.Request(f"https://fapi.binance.com/fapi/v1/{ep}?" + q, headers={"User-Agent": "replay2/1.0"})
            rows = json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            if "451" in str(e) or "400" in str(e):
                break
            time.sleep(1.0); continue
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1500:
            break
        cur = rows[-1][0] + TF_MS
        time.sleep(0.05)
    candles = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in out]  # ts,o,h,l,c
    json.dump(candles, open(cp, "w"))
    return candles

# ── strategy: returns the active stop price for the residual, or None ──
# state: fill_px, sl0, is_long, n_tp (rungs filled so far), tps (ladder), elapsed_d
def stop_none(s): return None
def stop_posted(s): return s["sl0"]
def stop_posted_buf(s):                    # 2% beyond posted SL (avoid wick stop-outs)
    return s["sl0"] * (1 - 0.02) if s["is_long"] else s["sl0"] * (1 + 0.02)
def stop_breakeven(s):                     # posted SL until TP1, then breakeven
    if s["n_tp"] >= 1:
        return s["fill_px"]
    return s["sl0"]
def stop_trailing(s):                      # posted SL until TP1, then trail under last filled rung
    if s["n_tp"] >= 2:
        return s["tps"][s["n_tp"] - 2]     # previous filled rung
    if s["n_tp"] == 1:
        return s["fill_px"]                # breakeven after first
    return s["sl0"]
def stop_fixed8(s):                        # mechanical -8% underlying, ignore posted SL
    return s["fill_px"] * (1 - 0.08) if s["is_long"] else s["fill_px"] * (1 + 0.08)

STRATEGIES = {
    "channel_only": stop_none,
    "posted_sl": stop_posted,
    "posted_sl_buf2%": stop_posted_buf,
    "breakeven_after_tp1": stop_breakeven,
    "trailing_after_tp": stop_trailing,
    "fixed_8pct": stop_fixed8,
    # time_stop handled via flag below (posted SL + exit-if-underwater at N days)
    "posted_sl+time7d": stop_posted,
}
TIME_STOP_D = {"posted_sl+time7d": 7}

def prep(sig):
    is_long = sig["direction"] == "long"
    elo, ehi, sl0 = sig["entry_lo"], sig["entry_hi"], sig["sl_initial"]
    tps = [t for t in sig["tp_ladder"] if isinstance(t, (int, float)) and t > 0]
    if not tps or sl0 is None or elo is None:
        return None
    edge = ehi if is_long else elo
    if (is_long and not sl0 < edge) or ((not is_long) and not sl0 > edge):
        return None
    tps = sorted([t for t in tps if (t > edge) == is_long], reverse=not is_long)
    if not tps:
        return None
    return is_long, elo, ehi, sl0, edge, tps

def simulate(sig, lev):
    p = prep(sig)
    if not p:
        return {"skip": "incomplete"}
    is_long, elo, ehi, sl0, edge, tps = p
    sym = fsym(sig["symbol"])
    o_ms = ms(sig["open_date"])
    last = fetch(sym, o_ms - TF_MS, o_ms + FETCH_D * 86400_000, mark=False)
    cut = o_ms + HORIZON_D * 86400_000
    last = [c for c in last if c[0] <= cut]
    if len(last) < 5:
        return {"skip": "no_klines"}
    markc = fetch(sym, o_ms - TF_MS, o_ms + FETCH_D * 86400_000, mark=True)
    mark = {c[0]: (c[3], c[2]) for c in markc}   # ts -> (low, high)

    # entry: limit-in-zone, fill on first touch into zone within window
    deadline = o_ms + ENTRY_WINDOW_H * 3600_000
    fi, fill_px = None, None
    for i, (ts, o, h, l, c) in enumerate(last):
        if ts < o_ms:
            continue
        if ts > deadline:
            break
        if (l <= ehi) if is_long else (h >= elo):
            fi, fill_px = i, edge; break
    if fi is None:
        return {"skip": "no_fill"}

    n = len(tps); w = 1.0 / n
    liq_frac = 1.0 / lev - 0.005
    liq_px = fill_px * (1 - liq_frac) if is_long else fill_px * (1 + liq_frac)
    # Residual-close model (codex: last_event biases channel_only HIGH because
    # the last event is usually a TP-hit announcement at a favorable price).
    #   last_event       — close residual at the channel's last logged event (optimistic)
    #   close_full_only   — only a real close_full counts; else ride to horizon (de-biased)
    #   none              — never use channel events; ride to horizon (neutral)
    RESIDUAL = os.environ.get("RESIDUAL", "last_event")
    if RESIDUAL == "close_full_only":
        ch_close = ms(sig["channel_close_date"]) if sig.get("channel_close_date") else None
    elif RESIDUAL == "none":
        ch_close = None
    else:
        ch_close = ms(sig["last_event_date"]) if sig.get("last_event_date") else None

    def adverse_ret(px):
        return (px - fill_px) / fill_px if is_long else (fill_px - px) / fill_px

    def run(stop_fn, time_stop_d):
        rem, next_tp, realized = 1.0, 0, 0.0
        liquidated = stopped = False
        note = "horizon"
        for (ts, o, h, l, c) in last[fi:]:
            if rem <= 1e-9:
                note = "all_tp"; break
            # Stop level reflects TPs filled in PRIOR candles, so a raised
            # (breakeven/trailing) stop only activates the candle AFTER its TP
            # fills — not the same wide candle (codex fix; was punishing
            # dynamic stops).
            st = stop_fn({"fill_px": fill_px, "sl0": sl0, "is_long": is_long, "n_tp": next_tp, "tps": tps})
            mlo, mhi = mark.get(ts, (l, h))
            hit_stop = st is not None and ((l <= st) if is_long else (h >= st))
            hit_liq = (mlo <= liq_px) if is_long else (mhi >= liq_px)
            # adverse-first; stop (closer to entry) fires before liq
            if hit_stop:
                realized += rem * adverse_ret(st); rem = 0.0; stopped = True; note = "stop"; break
            if hit_liq:
                realized += rem * adverse_ret(liq_px); rem = 0.0; liquidated = True; note = "liq"; break
            # take this candle's TPs (raises the stop for the NEXT candle)
            while next_tp < n and ((h >= tps[next_tp]) if is_long else (l <= tps[next_tp])):
                realized += w * adverse_ret(tps[next_tp]); rem -= w; next_tp += 1
            if time_stop_d and (ts - o_ms) >= time_stop_d * 86400_000 and rem > 1e-9:
                r = adverse_ret(c)
                if r < 0:                       # only exit if underwater at the time stop
                    realized += rem * r; rem = 0.0; note = "time"; break
            if ch_close and ts >= ch_close and rem > 1e-9:
                realized += rem * adverse_ret(c); rem = 0.0; note = "channel_close"; break
        if rem > 1e-9:
            realized += rem * adverse_ret(last[-1][4]); rem = 0.0
        net = realized * lev - 2 * FEE * lev
        return net, liquidated, stopped, note

    res = {"symbol": sig["symbol"], "dir": sig["direction"], "open": sig["open_date"]}
    for name, fn in STRATEGIES.items():
        net, liq, st, note = run(fn, TIME_STOP_D.get(name))
        res[name] = {"ret": net, "liq": liq, "stopped": st, "note": note}
    return res

def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    for lev in (5.0, 2.0):
        print(f"\n#### LEVERAGE {lev}x  residual={os.environ.get('RESIDUAL','last_event')}  horizon={HORIZON_D}d  5m  mark-liq ####")
        results, skips = [], Counter()
        for i, s in enumerate(usable):
            r = simulate(s, lev)
            if "skip" in r:
                skips[r["skip"]] += 1
            else:
                results.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(usable)} filled={len(results)}", flush=True)
        json.dump(results, open(os.path.join(HERE, f"v2_results_{int(lev)}x_{HORIZON_D}d.json"), "w"))
        report(results, skips)

def report(results, skips):
    n = len(results)
    ordered = sorted(results, key=lambda r: r["open"])
    print(f"filled={n}  skips={dict(skips)}")
    print(f"{'strategy':<22}{'total':>9}{'mean':>9}{'win%':>7}{'liq':>5}{'maxDD':>9}")
    rows = []
    for name in STRATEGIES:
        rets = [r[name]["ret"] for r in results]
        total = sum(rets); wins = sum(1 for x in rets if x > 0)
        liqs = sum(1 for r in results if r[name]["liq"])
        eq = peak = mdd = 0.0
        for r in ordered:
            eq += r[name]["ret"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        rows.append((name, total, total / n, wins / n * 100, liqs, mdd))
        print(f"{name:<22}{total:>9.2f}{total/n:>9.3f}{wins/n*100:>7.1f}{liqs:>5}{mdd:>9.2f}")
    best = max(rows, key=lambda x: x[1])
    print(f"  best total: {best[0]} ({best[1]:+.2f})")

if __name__ == "__main__":
    main()
