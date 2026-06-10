"""Gather complete per-trade data for the May +2702% ledger dashboard.
Chart window is extended to the ACTUAL exit so SL/TP hits are visible (no off-screen
contradictions). Outcome fields computed consistently with the market+manage sim."""
import sys, os, json
sys.path.insert(0, ".")
os.environ["PRICES_DIR"] = "prices_may"
import harness

mtr = json.load(open("trades_may.json"))
PM = {m["id"]: m for m in json.load(open("paid_export/paid_messages.json"))}  # raw telegram msgs
HOUR = 3600 * 1000
MAXSPAN = 6 * 24 * HOUR   # cap chart width at 6 days for readability

def msf(s): return harness.ms(s)

def walk_exit(t, cs):
    """Mirror market+manage: return (exit_ts, exit_reason, sl_hit, tp_hit) over the FULL
    sim window — used for the chart window + the plain-English note."""
    a = msf(t["date"]); is_long = t["direction"] == "LONG"
    fill = harness.price_at(cs, a)
    sl = t.get("sl"); cur_sl = sl if isinstance(sl, (int, float)) else None
    tps = t.get("tps") or []
    evs = sorted([e for e in (t.get("events") or []) if msf(e["t"]) >= a], key=lambda e: msf(e["t"]))
    remaining = 1.0; ei = 0
    end_cap = a + harness.MAX_TAIL_HOURS * HOUR
    sl_hit = tp_hit = False
    for c in cs:
        if c["t"] < a: continue
        if c["t"] >= end_cap: return end_cap, "tail (12d cap)", sl_hit, tp_hit
        # track SL/TP touches for the note (original posted SL + tps)
        if sl is not None and ((c["l"] <= sl) if is_long else (c["h"] >= sl)): sl_hit = True
        for tp in tps:
            if (c["h"] >= tp) if is_long else (c["l"] <= tp): tp_hit = True
        # SL-first exit on the CURRENT (maybe BE) stop
        if cur_sl is not None and ((c["l"] <= cur_sl) if is_long else (c["h"] >= cur_sl)):
            return c["t"], ("stop" if cur_sl == sl else "breakeven stop"), sl_hit, tp_hit
        while ei < len(evs) and msf(evs[ei]["t"]) <= c["t"]:
            e = evs[ei]; ei += 1; act = e.get("action")
            if act == "close_full":
                return c["t"], "Dennis posted full close", sl_hit, tp_hit
            if act == "close":
                f = e.get("frac_of_remaining", 0) * remaining if "frac_of_remaining" in e else min(e.get("frac", 0), remaining)
                remaining -= f
            if e.get("sl_to") == "breakeven": cur_sl = fill
            elif isinstance(e.get("sl_to"), (int, float)): cur_sl = e["sl_to"]
            if remaining <= 1e-9:
                return c["t"], "Dennis's partial closes flattened it", sl_hit, tp_hit
    return (cs[-1]["t"] if cs else end_cap), "data end (unresolved)", sl_hit, tp_hit

out = {"trades": []}
for t in mtr:
    sym = t["symbol"]; cs, ven = harness.candles(sym)
    a = msf(t["date"])
    ex_ts, ex_reason, sl_hit, tp_hit = walk_exit(t, cs)
    end = min(a + MAXSPAN, ex_ts + max(2 * HOUR, int((ex_ts - a) * 0.12)))
    start = a - 1 * HOUR
    win = [c for c in cs if start <= c["t"] <= end]
    # aggregate 1m -> ~130 OHLC candles for a readable candlestick chart
    span_min = max(1, (end - start) / 60000)
    bucket_ms = max(1, round(span_min / 130)) * 60000
    buckets = {}
    for c in win:
        k = (c["t"] // bucket_ms) * bucket_ms
        b = buckets.get(k)
        if b is None:
            buckets[k] = [k, c["o"], c["h"], c["l"], c["c"]]   # [t, o, h, l, c]
        else:
            b[2] = max(b[2], c["h"]); b[3] = min(b[3], c["l"]); b[4] = c["c"]
    path = [buckets[k] for k in sorted(buckets)]
    fills = {}
    for em in ("posted", "edge", "market"):
        r = harness.simulate(t, em, "manage")
        fills[em] = {"fill": r.entry_price, "R": r.realized_R, "exit": r.exit_kind, "parts": r.n_partials}
    ev_mk = []
    for e in sorted(t.get("events") or [], key=lambda e: msf(e["t"])):
        et = msf(e["t"]); pe = harness.price_at(cs, et); act = e.get("action")
        if act == "close":
            f = e.get("frac_of_remaining") or e.get("frac")
            lab = f"close {int((f or 0)*100)}%" + ("→BE" if e.get("sl_to") == "breakeven" else "")
        elif act == "close_full": lab = "full close"
        elif act == "sl_to": lab = f"SL→{e.get('sl_to')}"
        else: lab = act or ""
        raw = (PM.get(e.get("src_id")) or {}).get("text")
        ev_mk.append({"t": et, "price": pe, "label": lab, "src": e.get("src_id"), "raw": raw})
    out["trades"].append({
        "sym": sym, "dir": t["direction"], "date": t["date"], "src_id": t.get("src_id"),
        "entry": t.get("entry"), "entry_lo": t.get("entry_lo"), "entry_hi": t.get("entry_hi"),
        "sl": t.get("sl"), "tps": t.get("tps") or [], "claim_usd": t.get("claim_usd"),
        "claim_pct": t.get("claim_pct"), "fills": fills, "events": ev_mk, "path": path,
        "venue": ven, "exit_ts": ex_ts, "exit_reason": ex_reason, "sl_hit": sl_hit, "tp_hit": tp_hit,
        "posted_filled": fills["posted"]["fill"] is not None,
        "signal_text": (PM.get(t.get("src_id")) or {}).get("text"),
        "signal_msg_date": (PM.get(t.get("src_id")) or {}).get("date"),
    })

def tot(trades, em, xm):
    _, s, R, w = harness.run(trades, em, xm); return [round(R, 2), len(w), len(s)]
out["totals"] = {
    "market_manage": tot(mtr, "market", "manage"), "market_ladder": tot(mtr, "market", "ladder"),
    "posted_manage": tot(mtr, "posted", "manage"), "edge_manage": tot(mtr, "edge", "manage"),
    "del1609": tot([t for t in mtr if t.get("src_id") != 1609], "market", "manage"),
    "thru24": tot([t for t in mtr if t["date"][:10] <= "2026-05-24"], "market", "manage"),
    "exHYPE": tot([t for t in mtr if t["symbol"] != "HYPE"], "market", "manage"),
}
out["claim_sum"] = sum(t.get("claim_usd") or 0 for t in mtr)
json.dump(out, open("dashboard_full_data.json", "w"))
print(f"gathered {len(out['trades'])} trades; market+manage {out['totals']['market_manage']}")
# sanity: flag any trade where note(sl exit) but chart path never reaches SL
for t in out["trades"]:
    if "stop" in t["exit_reason"] and t["sl"]:
        lo = min(c[3] for c in t["path"]); hi = max(c[2] for c in t["path"])
        reached = (lo <= t["sl"]) if t["dir"] == "LONG" else (hi >= t["sl"])
        if not reached and t["exit_reason"] == "stop":
            print(f"  WARN {t['sym']} {t['src_id']}: stop exit but path doesn't reach SL {t['sl']} (lo{lo} hi{hi})")
