"""Track A.2 — REPLICATE HIS FILLS: staged zone-ladder entry vs single-fill, net of costs.

Q (operator): if we read every message right, why can't we fill like him? Answer must be
MEASURED, not asserted. The full-May causal run used a single-fill entry (100% at the first
zone-touch midpoint). Dennis ladders across the zone, so his blended average differs. This
re-runs the SAME trades + SAME management (his posted closes) but with a STAGED entry model
that mirrors how he actually fills, and compares net of WEEX costs.

Reuses the validated harness.py engine (codex-reviewed, reproduces published numbers). The
only thing that changes is the ENTRY model. Exit = "manage" (his posted management events) —
i.e. we act on the intents the LLM read at 87/87. WEEX prices (his venue).

Staged ladder (honest model of his method, "20% market / 30% / 50% across the zone"):
  - Distribute the planned position across N legs spanning [entry_lo, entry_hi].
  - SHORT: ladder from low->high; each leg fills when a causal candle's HIGH reaches its
    price (you add to the short as price rises INTO your zone — selling higher is better).
  - LONG: ladder from high->low; each leg fills when a candle's LOW reaches its price.
  - Blended avg = size-weighted average of the legs that actually filled within the window.
    Legs the market never reaches DON'T fill (realistic partial — and a worse/incomplete
    position, not a free better price).
  - The first leg is a market leg at the signal candle (he often starts "by market").

This is a FAIR test of "can we fill like him": it gives the laddered average his method
produces, with no lookahead (legs fill only on causal candles, exit only on posted events).
"""
import json, os, sys
import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PRICES_DIR", os.path.join(HERE, "prices_may"))
H.PRICES = __import__("pathlib").Path(os.environ["PRICES_DIR"]); H._cache.clear()

TAKER = 0.0005
SLIP = 0.0005
RISK_PCT = 5.0
FILL_WINDOW_H = 6   # legs must fill within this window (same as harness limit window)

# leg distribution across the zone (fracs sum to 1.0): a market starter + laddered adds
LEG_FRACS = [0.20, 0.30, 0.50]   # his canonical 20/30/50


def staged_entry(t, cs):
    """Return (blended_avg, fill_ts, filled_frac, legs_detail) or (None, reason).

    Leg prices span the zone. Leg 0 = market at signal candle open. Remaining legs are limits
    laddered across the zone, filling when a causal candle reaches them.
    """
    a = H.ms(t["date"])
    win = H.window(cs, a, a + FILL_WINDOW_H * 3600 * 1000)
    if not win:
        return None, "no_data"
    is_long = t["direction"] == "LONG"
    lo = t.get("entry_lo"); hi = t.get("entry_hi")
    posted = t.get("entry")
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
        # no zone -> single market fill at signal open (degenerates to market model)
        return win[0]["o"], a, 1.0, [{"price": win[0]["o"], "frac": 1.0, "kind": "market"}]
    lo, hi = min(lo, hi), max(lo, hi)

    # leg target prices across the zone
    n = len(LEG_FRACS)
    # SHORT ladders low->high (sell into strength); LONG ladders high->low (buy into weakness)
    if is_long:
        targets = [hi - (hi - lo) * i / (n - 1) for i in range(n)]   # hi, mid, lo
    else:
        targets = [lo + (hi - lo) * i / (n - 1) for i in range(n)]   # lo, mid, hi

    legs = []
    # leg 0 = market at signal candle open (he starts by market)
    legs.append({"price": win[0]["o"], "frac": LEG_FRACS[0], "kind": "market", "filled": True,
                 "t": a})
    # remaining legs are limits that fill when a causal candle reaches them
    for i in range(1, n):
        tgt = targets[i]
        filled = False; ft = None
        for c in win:
            if (c["l"] <= tgt <= c["h"]):
                filled = True; ft = c["t"]; break
        legs.append({"price": tgt, "frac": LEG_FRACS[i], "kind": "limit",
                     "filled": filled, "t": ft})

    fill_legs = [l for l in legs if l["filled"]]
    den = sum(l["frac"] for l in fill_legs)
    if den <= 0:
        return None, "no_fill"
    blended = sum(l["price"] * l["frac"] for l in fill_legs) / den
    fill_ts = max(l["t"] for l in fill_legs if l["t"] is not None)
    return blended, fill_ts, den, legs


def sim_staged(t):
    """Simulate one trade with staged entry + his posted management (manage exit). Returns R."""
    sym = t["symbol"]; is_long = t["direction"] == "LONG"
    cs, venue = H.candles(sym)   # weex primary
    if not cs:
        return None, "no_data", None
    sl = t.get("sl")
    if not isinstance(sl, (int, float)):
        return None, "no_sl", None
    res = staged_entry(t, cs)
    if res[0] is None:
        return None, res[1], None
    blended, fill_ts, filled_frac, legs = res
    # run his posted management from the blended entry (reuse harness manage walker)
    realized, risk, exit_kind, n_part = H._simulate_manage(t, cs, blended, is_long, sl, fill_ts)
    R = (realized / risk) if (risk and risk > 0) else None
    # scale R by the fraction actually filled (incomplete ladder = smaller position)
    if R is not None:
        R *= filled_frac
    return R, exit_kind, {"blended": round(blended, 6), "filled_frac": round(filled_frac, 2),
                          "sl_dist_pct": round(abs(blended - sl) / blended * 100, 2),
                          "venue": venue}


def sim_single(t):
    """Single midpoint fill (what the full-May causal run did) + his management — for contrast."""
    sym = t["symbol"]; is_long = t["direction"] == "LONG"
    cs, venue = H.candles(sym)
    if not cs:
        return None, "no_data", None
    sl = t.get("sl")
    if not isinstance(sl, (int, float)):
        return None, "no_sl", None
    a = H.ms(t["date"])
    win = H.window(cs, a, a + FILL_WINDOW_H * 3600 * 1000)
    if not win:
        return None, "no_fill", None
    lo = t.get("entry_lo"); hi = t.get("entry_hi")
    # single fill: midpoint of the zone (or market open if no zone) at first zone touch
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        ep = (lo + hi) / 2.0
        ft = H._first_touch_ts(win, ep, a)
    else:
        ep = win[0]["o"]; ft = a
    realized, risk, exit_kind, n_part = H._simulate_manage(t, cs, ep, is_long, sl, ft)
    R = (realized / risk) if (risk and risk > 0) else None
    return R, exit_kind, {"fill": round(ep, 6), "sl_dist_pct": round(abs(ep - sl) / ep * 100, 2)}


def cost_R(sl_dist_pct, roundtrip):
    d = sl_dist_pct / 100.0
    return roundtrip / d if d > 0 else 0.0


def main():
    trades = json.load(open(os.path.join(HERE, "trades_may.json")))
    roundtrip = 2 * (TAKER + SLIP)   # 0.20% market both sides

    print("=" * 78)
    print("TRACK A.2 — REPLICATE HIS FILLS: staged zone-ladder vs single-fill, his mgmt, WEEX")
    print("=" * 78)
    g_st = n_st = g_si = n_si = 0.0
    net_st = net_si = 0.0
    rows = []
    for t in trades:
        rS, kS, dS = sim_staged(t)
        rI, kI, dI = sim_single(t)
        if rS is None or rI is None:
            continue
        cS = cost_R(dS["sl_dist_pct"], roundtrip) * dS["filled_frac"]   # cost scales w/ filled size
        cI = cost_R(dI["sl_dist_pct"], roundtrip)
        g_st += rS; g_si += rI
        net_st += rS - cS; net_si += rI - cI
        rows.append((t["symbol"], t["direction"], round(rS, 3), round(rI, 3),
                     dS["filled_frac"], dS["sl_dist_pct"]))
    n = len(rows)
    print(f"trades: {n}   cost roundtrip {roundtrip*100:.2f}% (market)   risk {RISK_PCT}%/trade\n")
    print(f"  SINGLE-FILL (what the causal run did):  gross {g_si:+.2f}R   NET {net_si:+.2f}R "
          f"({net_si*RISK_PCT:+.1f}% @5%)")
    print(f"  STAGED LADDER (his method, 20/30/50):   gross {g_st:+.2f}R   NET {net_st:+.2f}R "
          f"({net_st*RISK_PCT:+.1f}% @5%)")
    print(f"  delta (staged - single), net:           {net_st-net_si:+.2f}R\n")
    # concentration on staged
    nets = sorted(((sym, d, rS) for (sym, d, rS, rI, ff, sld) in rows), key=lambda x: -x[2])
    print(f"  staged biggest winner: {nets[0][0]} {nets[0][1]} {nets[0][2]:+.2f}R")
    print(f"  staged net ex-top-winner: {net_st - nets[0][2]:+.2f}R (gross basis)\n")
    print("  per-trade  (staged_R | single_R | filled% | sl_dist%):")
    for sym, d, rS, rI, ff, sld in sorted(rows, key=lambda x: -x[2]):
        print(f"    {sym:9}{d:6} staged={rS:+6.3f}  single={rI:+6.3f}  filled={ff*100:3.0f}%  sl={sld:5.2f}%")
    print()
    print("  NOTE: staged R is scaled by filled fraction (incomplete ladders = smaller position).")
    print("  Both use his posted management (the 87/87 intents). WEEX. No lookahead. Between-msg")
    print("  hard-SL still not modeled (would hurt both equally).")

if __name__ == "__main__":
    main()
