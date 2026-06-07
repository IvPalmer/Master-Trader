"""Back-fill Binance 1m caches to 2026-02-01 for the symbols in Feb-Apr structured signals,
so we can run the limit+TP copy model across ALL parseable months (not just May/April).
Binance fapi USDT-M perp, paginated. Prepends + dedups into prices/<SYM>.binance.jsonl.
"""
import json, os, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "prices"
SYMS = ["BTC", "ETH", "ASTER", "BNB", "ATOM", "ETC", "SOL", "SEI", "AAVE"]
START = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 4, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)  # joins the 04-01 backfill

def fetch(sym, start, end):
    out = {}; s = start
    while s < end:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
               f"&interval=1m&startTime={s}&endTime={end}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            rows = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as e:
            print(f"    {sym} {s}: {type(e).__name__} {e}"); break
        if not rows: break
        for r in rows:
            t = int(r[0]); out[t] = {"t": t, "o": float(r[1]), "h": float(r[2]),
                                     "l": float(r[3]), "c": float(r[4])}
        s = int(rows[-1][0]) + 60000; time.sleep(0.1)
        if len(rows) < 1000: break
    return out

for sym in SYMS:
    f = OUT / f"{sym}.binance.jsonl"
    existing = {}
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                c = json.loads(line); existing[int(c["t"])] = c
    before = len(existing)
    existing.update(fetch(sym, START, END))
    merged = [existing[k] for k in sorted(existing)]
    if merged:
        f.write_text("\n".join(json.dumps(c) for c in merged))
        lo = datetime.fromtimestamp(merged[0]["t"]/1000, timezone.utc).strftime("%m-%d")
        print(f"  {sym}: {before} -> {len(merged)} (+{len(merged)-before}); starts {lo}")
    else:
        print(f"  {sym}: no data")
