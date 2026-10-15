"""Track A.2 (v2, codex-corrected) — can we fill like Dennis if we read every message right?

Three entry models on the SAME 32 May trades + SAME posted management (the 87/87 intents),
WEEX, no lookahead, net of 0.20% market roundtrip cost. Fixes from codex review:

  1. single-fill comparator no longer uses fantasy midpoint fills — it fills market at the
     signal-candle open (a price that definitely traded), not an untouched zone midpoint.
  2. STARTER-ONLY: the honest copyable entry when he posts a zone but NO explicit adds — a
     market starter at full intended risk. This is what a mechanical copier actually gets in
     the validated May window (where curated truth has ~1 add event in 32 trades).
  3. EVENT-DRIVEN ladder: starter + adds ONLY where he explicitly posts them (curated `add`
     events / the LLM's open_partial intents). No assumed generic ladder.
  4. GENERIC 20/30/50 reported as a SENSITIVITY bound, not the answer.

Reports gross + net for each, with the exit-basis labelled:
  exit = his posted management events (curated `events[]`) = "if we interpret all posted
  management correctly" (entry-fidelity diagnostic), NOT the live-bot end-to-end number.
"""
import json, os
import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PRICES_DIR", os.path.join(HERE, "prices_may"))
H.PRICES = __import__("pathlib").Path(os.environ["PRICES_DIR"]); H._cache.clear()

TAKER = 0.0005; SLIP = 0.0005; RISK_PCT = 5.0; FILL_WINDOW_H = 6
GENERIC_LEGS = [0.20, 0.30, 0.50]


def _win(t, cs):
    a = H.ms(t["date"])
    return a, H.window(cs, a, a + FILL_WINDOW_H * 3600 * 1000)


def starter_only(t, cs):
    """Market starter at full risk: fill 100% at the signal-candle open (a real traded price)."""
    a, win = _win(t, cs)
    if not win:
        return None
    return win[0]["o"], a, 1.0


def event_driven(t, cs):
    """Starter at signal open, then add legs ONLY where he posts an add (curated add events).
    Each posted add fills at the market price at the add's timestamp. Blended avg over what
    actually filled. Frac per leg: split planned size across (1 starter + n posted adds)."""
    a, win = _win(t, cs)
    if not win:
        return None
    add_events = [e for e in (t.get("events") or [])
                  if e.get("action") in ("add", "increase")
                  or "add" in (e.get("note", "") or "").lower() and e.get("action") not in ("close", "close_full")]
    n_legs = 1 + len(add_events)
    frac = 1.0 / n_legs
    legs = [{"price": win[0]["o"], "frac": frac}]
    for e in add_events:
        pe = H.price_at(cs, H.ms(e["t"]))
        if pe is not None:
            legs.append({"price": pe, "frac": frac})
    den = sum(l["frac"] for l in legs)
    blended = sum(l["price"] * l["frac"] for l in legs) / den
    filled = den  # starter always fills; posted adds fill at their posted time
    fill_ts = a
    return blended, fill_ts, filled


def generic_ladder(t, cs):
    """The ASSUMED 20/30/50 zone ladder (sensitivity bound, not the answer)."""
    a, win = _win(t, cs)
    if not win:
        return None
    is_long = t["direction"] == "LONG"
    lo, hi = t.get("entry_lo"), t.get("entry_hi")
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
        return win[0]["o"], a, 1.0
    lo, hi = min(lo, hi), max(lo, hi)
    n = len(GENERIC_LEGS)
    targets = ([hi - (hi - lo) * i / (n - 1) for i in range(n)] if is_long
               else [lo + (hi - lo) * i / (n - 1) for i in range(n)])
    legs = [{"price": win[0]["o"], "frac": GENERIC_LEGS[0], "filled": True, "t": a}]
    for i in range(1, n):
        tgt = targets[i]; filled = False; ft = None
        for c in win:
            if c["l"] <= tgt <= c["h"]:
                filled = True; ft = c["t"]; break
        legs.append({"price": tgt, "frac": GENERIC_LEGS[i], "filled": filled, "t": ft})
    fl = [l for l in legs if l["filled"]]
    den = sum(l["frac"] for l in fl)
    if den <= 0:
        return None
    blended = sum(l["price"] * l["frac"] for l in fl) / den
    fill_ts = max(l["t"] for l in fl if l["t"] is not None)
    return blended, fill_ts, den


def run_model(trades, entry_fn, scale_by_fill):
    roundtrip = 2 * (TAKER + SLIP)
    gross = net = 0.0; rows = []
    for t in trades:
        sl = t.get("sl")
        if not isinstance(sl, (int, float)):
            continue
        cs, venue = H.candles(t["symbol"])
        if not cs:
            continue
        res = entry_fn(t, cs)
        if res is None:
            continue
        ep, fill_ts, filled = res
        is_long = t["direction"] == "LONG"
        realized, risk, kind, npart = H._simulate_manage(t, cs, ep, is_long, sl, fill_ts)
        R = (realized / risk) if (risk and risk > 0) else None
        if R is None:
            continue
        if scale_by_fill:
            R *= filled
        sld = abs(ep - sl) / ep * 100
        c = (roundtrip / (sld / 100.0)) * (filled if scale_by_fill else 1.0)
        gross += R; net += R - c
        rows.append((t["symbol"], t["direction"], round(R, 3), round(filled, 2), round(sld, 2)))
    return gross, net, rows


def main():
    trades = json.load(open(os.path.join(HERE, "trades_may.json")))
    print("=" * 80)
    print("TRACK A.2 v2 (codex-corrected) — can we fill like Dennis? 32 May trades, WEEX,")
    print("his posted management as exit, net of 0.20% market cost, 5%/trade, no lookahead")
    print("=" * 80)
    models = [
        ("STARTER-ONLY (market, full risk) — the honest copyable entry", starter_only, False),
        ("EVENT-DRIVEN (starter + ONLY posted adds)", event_driven, True),
        ("GENERIC 20/30/50 ladder (ASSUMED — sensitivity bound)", generic_ladder, True),
    ]
    for name, fn, scale in models:
        g, net, rows = run_model(trades, fn, scale)
        n = len(rows); wins = sum(1 for r in rows if r[2] > 0)
        top = max(rows, key=lambda r: r[2])[2] if rows else 0
        print(f"\n  {name}")
        print(f"    trades={n}  gross={g:+.2f}R  NET={net:+.2f}R ({net*RISK_PCT:+.1f}% @5%)  "
              f"WR={wins}/{n}  net_ex_top={net-top:+.2f}R(gross)")
    print()
    print("  Reading: STARTER-ONLY is what a copier that reads everything actually gets in May")
    print("  (he posts zones + manages exits; he rarely posts copyable ADDS in this window —")
    print("  ~1 add event in 32 curated trades). EVENT-DRIVEN ~ STARTER because there are almost")
    print("  no posted adds to act on. GENERIC ladder is what his METHOD would do IF he laddered")
    print("  every zone — it underfills winners (adds only complete when price goes against you).")
    print()
    print("  EXIT BASIS = curated posted-management ('if we interpret all his management right').")
    print("  NOT the live-bot end-to-end number. Between-msg hard-SL not modeled (hurts all equally).")

if __name__ == "__main__":
    main()
