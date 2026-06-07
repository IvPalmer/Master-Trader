"""Token/scale integrity check for the May ledger.
For each trade: compare cached WEEX (and Binance) price at the signal minute to the
posted entry range. Flag >~5% mismatch as a candidate wrong-token/scale failure.
Offline; reads prices_may/ only."""
import json, os
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
PRICES = HERE / "prices_may"

def ms(s):
    return int(datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()*1000)

def load(sym, venue):
    p = PRICES / f"{sym.upper()}.{venue}.jsonl"
    rows=[]
    if p.exists():
        for ln in p.read_text().splitlines():
            ln=ln.strip()
            if ln: rows.append(json.loads(ln))
    rows.sort(key=lambda c:c["t"])
    return rows

def price_at(cs, t):
    # candle covering t (first at/after t)
    for c in cs:
        if c["t"] >= t:
            return c
    return None

def span(cs):
    if not cs: return "EMPTY"
    a=datetime.fromtimestamp(cs[0]["t"]/1000,tz=timezone.utc).strftime("%m-%dT%H:%M")
    b=datetime.fromtimestamp(cs[-1]["t"]/1000,tz=timezone.utc).strftime("%m-%dT%H:%M")
    return f"{a}..{b} ({len(cs)})"

trades=json.load(open(HERE/"trades_may.json"))
print(f"{'SYM':9}{'DIR':6}{'DATE':17}{'POSTED_ENTRY':>13}{'WEEX@sig':>12}{'BIN@sig':>12}{'W_dev%':>9}{'WvsB%':>9}  FLAG")
for t in trades:
    sym=t["symbol"]; d=t["date"]; pe=t.get("entry"); sl=t.get("sl")
    a=ms(d)
    w=load(sym,"weex"); b=load(sym,"binance")
    wc=price_at(w,a); bc=price_at(b,a)
    wpx = wc["c"] if wc else None
    bpx = bc["c"] if bc else None
    # deviation of cached price from posted entry midpoint
    def dev(px):
        if px is None or not isinstance(pe,(int,float)): return None
        return (px-pe)/pe*100.0
    wdev=dev(wpx); bdev=dev(bpx)
    wvb = ((wpx-bpx)/bpx*100.0) if (wpx and bpx) else None
    flags=[]
    if wdev is not None and abs(wdev)>8: flags.append(f"WEEX_DEV_{wdev:+.0f}%")
    if wvb is not None and abs(wvb)>2: flags.append(f"WvsB_{wvb:+.1f}%")
    # 10x scale detection
    if wpx and isinstance(pe,(int,float)):
        ratio = wpx/pe
        for k in (10,100,1000,0.1,0.01,0.001):
            if abs(ratio-k)/k < 0.15:
                flags.append(f"SCALE_x{k}")
    ws = f"{wpx:.6g}" if wpx is not None else "NA"
    bs = f"{bpx:.6g}" if bpx is not None else "NA"
    wd = f"{wdev:+.1f}" if wdev is not None else "NA"
    wbs= f"{wvb:+.1f}" if wvb is not None else "NA"
    print(f"{sym:9}{t['direction']:6}{d[5:16]:17}{str(pe):>13}{ws:>12}{bs:>12}{wd:>9}{wbs:>9}  {' '.join(flags)}")

print("\n--- per-symbol cache spans (WEEX / Binance) ---")
seen=set()
for t in trades:
    s=t["symbol"]
    if s in seen: continue
    seen.add(s)
    print(f"{s:9} W:{span(load(s,'weex'))}   B:{span(load(s,'binance'))}")
