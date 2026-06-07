"""Shadow SL replay: channel-driven exits vs hard-stop-at-posted-SL.

Compares two exit policies over the 2yr Killers signal corpus, on REAL Binance
USDⓈ-M futures prices, to answer: should the copy-trader exit at the signal's
posted SL instead of riding until the channel posts a close?

Both policies share: limit-in-zone entry + the posted TP ladder (equal-weight
partial exits). They differ ONLY on the residual position:
  channel_only : no stop; closes at the channel's close_full (if any) else at
                 horizon end; models 5x ISOLATED liquidation (the real downside).
  posted_plan  : residual exits at the posted SL on touch.

Assumptions (explicit, see codex review):
  ENTRY_WINDOW_H  entry limit rests this long; fills on first touch into zone.
  HORIZON_D       max hold for an un-closed trade, then mark-to-last.
  LEV             leverage (matches the live bot's 5x).
  FEE             taker fee per side.
  Liquidation     adverse underlying move of ~1/LEV (isolated) wipes the residual.
  Same-candle TP+SL in one 15m bar → conservatively assume SL hit first.
No look-ahead: only the SL/TPs known at entry are used (corpus has 0 move_sl).
"""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "klines_cache")
os.makedirs(CACHE, exist_ok=True)

ENTRY_WINDOW_H = 72
FETCH_D = 45                                  # klines window (fixed → cache stable)
HORIZON_D = int(os.environ.get("HORIZON_D", "45"))  # sim residual-hold cap (sensitivity)
LEV = 5.0
FEE = 0.0004
TF = "15m"
TF_MS = 15 * 60 * 1000
LIQ_FRAC = 1.0 / LEV - 0.005   # isolated liq ~ adverse 1/lev move (minus maint.)

ALIAS = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI",
         "BONK": "1000BONK", "GOLD": "XAUT"}

def fsym(sym):
    return ALIAS.get(sym.upper(), sym.upper()) + "USDT"

def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def fetch_klines(symbol, start_ms, end_ms):
    """Binance USDⓈ-M 15m klines, paginated, disk-cached per symbol+window."""
    key = f"{symbol}_{start_ms}_{end_ms}.json"
    cp = os.path.join(CACHE, key)
    if os.path.exists(cp):
        return json.load(open(cp))
    out, cur = [], start_ms
    while cur < end_ms:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": TF,
                                    "startTime": cur, "endTime": end_ms, "limit": 1500})
        url = "https://fapi.binance.com/fapi/v1/klines?" + q
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "replay/1.0"})
            rows = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as e:
            if "451" in str(e) or "400" in str(e):  # delisted / unavailable
                break
            time.sleep(1.0); continue
        if not rows:
            break
        out.extend(rows)
        last = rows[-1][0]
        if last <= cur or len(rows) < 1500:
            cur = last + TF_MS
            if len(rows) < 1500:
                break
        else:
            cur = last + TF_MS
        time.sleep(0.06)
    candles = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in out]  # ts,o,h,l,c
    json.dump(candles, open(cp, "w"))
    return candles

def simulate(sig):
    """Return dict with per-policy result + classification, or {'skip': reason}."""
    sym = fsym(sig["symbol"])
    is_long = sig["direction"] == "long"
    elo, ehi, sl0 = sig["entry_lo"], sig["entry_hi"], sig["sl_initial"]
    tps = [t for t in sig["tp_ladder"] if isinstance(t, (int, float)) and t > 0]
    if not tps or sl0 is None or elo is None:
        return {"skip": "incomplete"}
    # sanity: SL must be on the correct side of entry
    entry_edge = ehi if is_long else elo                 # limit-in-zone near edge
    if is_long and not (sl0 < entry_edge):
        return {"skip": "bad_sl_side"}
    if (not is_long) and not (sl0 > entry_edge):
        return {"skip": "bad_sl_side"}
    # keep TPs on the profit side, in order
    tps = [t for t in tps if (t > entry_edge) == is_long]
    if not tps:
        return {"skip": "no_valid_tp"}
    tps = sorted(tps, reverse=not is_long)

    open_ms = int(dt(sig["open_date"]).timestamp() * 1000)
    candles = fetch_klines(sym, open_ms - TF_MS, open_ms + FETCH_D * 86400_000)
    # sim-horizon cap (sensitivity) applied on the cached fetch window
    horizon_cut = open_ms + HORIZON_D * 86400_000
    candles = [c for c in candles if c[0] <= horizon_cut]
    if len(candles) < 5:
        return {"skip": "no_klines"}

    # ---- entry: limit-in-zone, fill on first touch into [elo,ehi] within window
    entry_deadline = open_ms + ENTRY_WINDOW_H * 3600_000
    fill_i, fill_px = None, None
    for i, (ts, o, h, l, c) in enumerate(candles):
        if ts < open_ms:
            continue
        if ts > entry_deadline:
            break
        touched = (l <= ehi) if is_long else (h >= elo)   # price reaches the zone
        if touched:
            fill_i, fill_px = i, entry_edge                # fill at near edge
            break
    if fill_i is None:
        return {"skip": "no_fill"}

    nrungs = len(tps)
    w = 1.0 / nrungs                                       # equal weight per rung
    liq_px = fill_px * (1 - LIQ_FRAC) if is_long else fill_px * (1 + LIQ_FRAC)

    # channel close (for channel_only residual)
    ch_close_ms = int(dt(sig["channel_close_date"]).timestamp() * 1000) if sig.get("channel_close_date") else None

    def run(policy):
        rem = 1.0          # remaining fraction of position
        next_tp = 0
        realized = 0.0     # sum of (weight * underlying_return) over closed legs
        sl_touched_ts = None
        liquidated = False
        exit_note = "horizon"
        for (ts, o, h, l, c) in candles[fill_i:]:
            if rem <= 1e-9:
                exit_note = "all_tp"; break
            hit_tp = []
            while next_tp < nrungs and ((h >= tps[next_tp]) if is_long else (l <= tps[next_tp])):
                hit_tp.append(tps[next_tp]); next_tp += 1
            hit_sl = (l <= sl0) if is_long else (h >= sl0)
            hit_liq = (l <= liq_px) if is_long else (h >= liq_px)
            # conservative same-candle handling: adverse event first
            if policy == "posted_plan" and hit_sl:
                ret = (sl0 - fill_px) / fill_px if is_long else (fill_px - sl0) / fill_px
                realized += rem * ret; rem = 0.0; sl_touched_ts = ts; exit_note = "sl"; break
            if policy == "channel_only" and hit_liq:
                ret = (liq_px - fill_px) / fill_px if is_long else (fill_px - liq_px) / fill_px
                realized += rem * ret; rem = 0.0; liquidated = True; exit_note = "liquidation"; break
            for tp in hit_tp:                              # take TP partials
                ret = (tp - fill_px) / fill_px if is_long else (fill_px - tp) / fill_px
                realized += w * ret; rem -= w
            if policy == "channel_only" and ch_close_ms and ts >= ch_close_ms and rem > 1e-9:
                ret = (c - fill_px) / fill_px if is_long else (fill_px - c) / fill_px
                realized += rem * ret; rem = 0.0; exit_note = "channel_close"; break
        if rem > 1e-9:                                     # mark-to-last at horizon
            c = candles[-1][4]
            ret = (c - fill_px) / fill_px if is_long else (fill_px - c) / fill_px
            realized += rem * ret; rem = 0.0
        # net margin return: underlying * lev, minus round-trip fees * lev
        net = realized * LEV - 2 * FEE * LEV
        return {"underlying_ret": realized, "margin_ret": net, "exit": exit_note,
                "liquidated": liquidated, "sl_touched": sl_touched_ts is not None}

    co = run("channel_only")
    pp = run("posted_plan")
    # SL-breach 4-case classification (does posted_plan diverge or save us?)
    sl_breached = pp["sl_touched"]
    case = "no_sl_breach"
    if sl_breached:
        if co["liquidated"]:
            case = "co_liquidated"           # hard SL saved us from liquidation
        elif co["margin_ret"] >= pp["margin_ret"]:
            case = "co_recovered"            # channel rode it back better → SL hurt
        else:
            case = "co_worse"                # SL exited better than riding
    return {"symbol": sig["symbol"], "dir": sig["direction"], "open": sig["open_date"],
            "channel_only": co, "posted_plan": pp, "sl_breached": sl_breached, "case": case}


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"]
              and s["direction"] in ("long", "short")]
    print(f"simulating {len(usable)} signals @ {LEV}x, {TF}, horizon {HORIZON_D}d ...")
    results, skips = [], {}
    for i, s in enumerate(usable):
        r = simulate(s)
        if "skip" in r:
            skips[r["skip"]] = skips.get(r["skip"], 0) + 1
        else:
            results.append(r)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(usable)}  filled={len(results)}")
    json.dump({"results": results, "skips": skips}, open(os.path.join(HERE, "replay_results.json"), "w"))
    print("skips:", skips)
    report(results)

def report(results):
    import statistics as st
    n = len(results)
    def agg(pol):
        rets = [r[pol]["margin_ret"] for r in results]
        wins = sum(1 for x in rets if x > 0)
        total = sum(rets)
        # equity curve in open-date order for max drawdown (per-trade margin, $1 risk units)
        ordered = sorted(results, key=lambda r: r["open"])
        eq, peak, mdd = 0.0, 0.0, 0.0
        for r in ordered:
            eq += r[pol]["margin_ret"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        liqs = sum(1 for r in results if r[pol]["liquidated"])
        return {"trades": n, "total_margin_ret": round(total, 3),
                "mean_per_trade": round(total / n, 4), "win_rate": round(wins / n, 3),
                "max_dd_units": round(mdd, 3), "liquidations": liqs}
    print("\n===== RESULTS (margin return units, 1 = +100% of one position's margin) =====")
    print(f"filled trades: {n}")
    print("channel_only:", agg("channel_only"))
    print("posted_plan :", agg("posted_plan"))
    from collections import Counter
    cases = Counter(r["case"] for r in results)
    breached = sum(1 for r in results if r["sl_breached"])
    print(f"\nSL breached in {breached}/{n} trades. Case matrix:")
    for k, v in cases.most_common():
        print(f"  {k}: {v}")
    # delta
    d = agg("posted_plan")["total_margin_ret"] - agg("channel_only")["total_margin_ret"]
    print(f"\nposted_plan − channel_only total: {d:+.3f} margin units "
          f"({'SL helps' if d > 0 else 'SL hurts'})")

if __name__ == "__main__":
    main()
