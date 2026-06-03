"""Parse structured Entry/SL/TP signals from the paid export into the trade schema, for ANY
month — so we can run the limit+TP copy model out-of-sample (Feb/Mar/Apr) against May.

Only emits signals on symbols we have a price cache for (crypto). Metals/FX (XAUT/XAG) are
dropped — no candles to simulate. Two posted formats are handled:
  A) terse:      "$ETHUSDT  long  entry - 2427.09; stop - 2350.75  take - 2488.51"
  B) structured: "SOL/SHORT ...  Entry point: 88-91  TP: 84 / fix 75% ... SL = 93"
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAID = os.path.join(HERE, "paid_export", "paid_messages.json")

NUM = r"[-+]?\d[\d,]*\.?\d*"

def to_f(s):
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None

def priceable_symbols(prices_dir):
    syms = set()
    for f in os.listdir(prices_dir):
        if f.endswith(".weex.jsonl") or f.endswith(".binance.jsonl"):
            syms.add(f.split(".")[0].upper())
    return syms

def norm_sym(raw):
    s = raw.upper().lstrip("$")
    s = re.sub(r"USDT$|/USDT$|/USD$|PERP$", "", s)
    s = s.strip("/ ")
    return s

def parse_one(text):
    t = text or ""
    # symbol + direction
    sym = None; side = None
    m = re.search(r"\$?([A-Z]{2,12})(?:USDT)?\s*[\n/]+\s*(LONG|SHORT)", t, re.I)
    if not m:
        m = re.search(r"\$?([A-Z]{2,12})(?:USDT)?\b.*?\b(LONG|SHORT)\b", t, re.I | re.S)
    if m:
        sym = norm_sym(m.group(1)); side = m.group(2).upper()
    if not sym or side not in ("LONG", "SHORT"):
        return None
    # entry — three shapes, checked in order:
    elo = ehi = entry = None
    legs = []
    # (1) STAGED LADDER: "Entry  20% - 74100  30% - 74700  50% - 75300"
    ladder = re.findall(r"(\d{1,3})\s*%\s*[-–:]\s*(" + NUM + r")", t)
    if ladder:
        for pct, px in ladder:
            v = to_f(px)
            if v:
                legs.append({"frac": float(pct) / 100.0, "price": v})
        if legs:
            prices = [l["price"] for l in legs]
            elo, ehi = min(prices), max(prices)
            # planned blended avg = frac-weighted (his stated ladder average)
            den = sum(l["frac"] for l in legs) or 1.0
            entry = sum(l["price"] * l["frac"] for l in legs) / den
    # (2) ZONE: "Entry point: 74100-75300"  (avoid matching after a % sign)
    if entry is None:
        mz = re.search(r"entry(?:\s*point)?\s*[:\-]?\s*(" + NUM + r")\s*[–\-]\s*(" + NUM + r")", t, re.I)
        if mz and "%" not in t[max(0, mz.start()-4):mz.start()]:
            a, b = to_f(mz.group(1)), to_f(mz.group(2))
            if a and b:
                elo, ehi = min(a, b), max(a, b); entry = (elo + ehi) / 2
    # (3) SINGLE
    if entry is None:
        ms_ = re.search(r"entry\s*[:\-]?\s*(" + NUM + r")", t, re.I)
        if ms_:
            entry = to_f(ms_.group(1)); elo = ehi = entry
    # sl
    sl = None
    msl = re.search(r"(?:sl|stop)\s*(?:loss)?\s*[=:\-]?\s*(" + NUM + r")", t, re.I)
    if msl:
        sl = to_f(msl.group(1))
    # tps (take / tp / target)
    tps = []
    for mt in re.finditer(r"(?:tp|take|target)\s*[:=\-]?\s*(" + NUM + r")", t, re.I):
        v = to_f(mt.group(1))
        if v:
            tps.append(v)
    # also bare "X / fix 75%" lines under a TP: header
    for mt in re.finditer(r"(" + NUM + r")\s*/\s*(?:we\s+)?fix\s+\d", t, re.I):
        v = to_f(mt.group(1))
        if v and v not in tps:
            tps.append(v)
    if entry is None or sl is None:
        return None
    # sanity: entry within an order of magnitude of sl (catches leverage/junk mis-parses)
    if sl and entry and not (0.1 < entry / sl < 10):
        return None
    return {"symbol": sym, "direction": side, "entry": entry, "entry_lo": elo,
            "entry_hi": ehi, "sl": sl, "tps": tps, "legs": legs, "events": []}

def main():
    month_filter = sys.argv[1] if len(sys.argv) > 1 else None  # e.g. "2026-04"
    prices_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "prices")
    syms = priceable_symbols(prices_dir)
    paid = json.load(open(PAID))
    out = []
    dropped_sym = {}
    for m in paid:
        d = (m.get("date") or "")[:7]
        if month_filter and d != month_filter:
            continue
        txt = m.get("text", "")
        if not (re.search(r"\bentry\b", txt, re.I) and re.search(r"\bsl\b|stop", txt, re.I)
                and re.search(r"\btp\b|target|take", txt, re.I)):
            continue
        p = parse_one(txt)
        if not p:
            continue
        p["date"] = m["date"]; p["src_id"] = m["id"]
        if p["symbol"] not in syms:
            dropped_sym[p["symbol"]] = dropped_sym.get(p["symbol"], 0) + 1
            continue
        out.append(p)
    print(f"parsed {len(out)} priceable signals" + (f" for {month_filter}" if month_filter else ""))
    print(f"  dropped (no price cache): {dict(sorted(dropped_sym.items(), key=lambda x:-x[1]))}")
    tag = month_filter.replace("-", "_") if month_filter else "all"
    outf = os.path.join(HERE, f"signals_parsed_{tag}.json")
    json.dump(out, open(outf, "w"), indent=1)
    print(f"  -> {outf}")
    if out:
        print("  sample:")
        for p in out[:6]:
            print(f"    {p['symbol']:8}{p['direction']:6} {p['entry_lo']}-{p['entry_hi']} sl={p['sl']} tp={p['tps']}")

if __name__ == "__main__":
    main()
