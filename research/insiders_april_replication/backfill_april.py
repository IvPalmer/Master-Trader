"""Back-fill the April price cache to early April so pre-04-16 signals are testable.

The existing prices/ cache starts 2026-04-16; April signals run 04-02..04-29, so signals
before 04-16 silently drop ("no candles at signal time"). This fetches 04-01..04-16 from
Binance fapi for the April signal symbols and PREPENDS to the existing <SYM>.binance.jsonl
(dedup + sort), so the OOS test has complete coverage.

Binance USDT-M perp 1m klines, public endpoint, paginated (1000/req).
"""
import json, os, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "prices"

# symbols that appear in parsed April signals + majors (Binance-listed)
SYMS = ["BTC", "ETH", "ASTER", "SOL", "SEI", "AAVE"]
START = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 4, 16, 1, tzinfo=timezone.utc).timestamp() * 1000)

def fetch_binance(sym, start, end):
    out = {}
    s = start
    while s < end:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
               f"&interval=1m&startTime={s}&endTime={end}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            rows = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as e:
            print(f"    {sym} chunk {s}: {type(e).__name__} {e}")
            break
        if not rows:
            break
        for r in rows:
            t = int(r[0])
            out[t] = {"t": t, "o": float(r[1]), "h": float(r[2]),
                      "l": float(r[3]), "c": float(r[4])}
        s = int(rows[-1][0]) + 60000
        time.sleep(0.12)
        if len(rows) < 1000:
            break
    return out

def main():
    for sym in SYMS:
        f = OUT / f"{sym}.binance.jsonl"
        existing = {}
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.strip()
                if line:
                    c = json.loads(line); existing[int(c["t"])] = c
        before = len(existing)
        new = fetch_binance(sym, START, END)
        existing.update(new)
        merged = [existing[k] for k in sorted(existing)]
        f.write_text("\n".join(json.dumps(c) for c in merged))
        lo = datetime.fromtimestamp(merged[0]["t"] / 1000, timezone.utc).strftime("%m-%d %H:%M") if merged else "?"
        print(f"  {sym}: {before} -> {len(merged)} candles (+{len(merged)-before}); now starts {lo}")

if __name__ == "__main__":
    main()
