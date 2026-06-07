"""Fetch Hyperliquid 1-min candles for Dennis's symbols, aligned to the EXISTING
WEEX/Binance cache windows, so the execution-matrix backtest can compare all three
venues apples-to-apples. Writes <SYM>.hyperliquid.jsonl ({t(ms),o,h,l,c}) into the
same prices/ (April) and prices_may/ (May) dirs.

HL API: POST https://api.hyperliquid.xyz/info {type:"candleSnapshot",
req:{coin, interval:"1m", startTime, endTime}}. Caps ~5000 candles/req → paginate.
"""
import json, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
HL_OK = ['BTC','EIGEN','ETC','ETH','FARTCOIN','HYPE','LTC','NEAR','PUMP','SKY','SOL','TON','VIRTUAL']  # 13/16 (no FF,FIDA,USELESS)
CHUNK_MS = 5000 * 60 * 1000  # 5000 one-minute candles per request

def post(body):
    req = urllib.request.Request('https://api.hyperliquid.xyz/info',
        data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=30))

def cache_bounds(pdir: Path, sym: str):
    """min/max open-time (ms) from the existing binance cache for this symbol+window."""
    f = pdir / f"{sym}.binance.jsonl"
    if not f.exists():
        return None
    ts = []
    for line in f.read_text().splitlines():
        line = line.strip()
        if line:
            ts.append(json.loads(line)['t'])
    if not ts:
        return None
    return min(ts), max(ts)

def fetch_hl(coin: str, start_ms: int, end_ms: int):
    out = {}
    s = start_ms
    while s <= end_ms:
        e = min(s + CHUNK_MS, end_ms)
        try:
            rows = post({'type':'candleSnapshot',
                         'req':{'coin':coin,'interval':'1m','startTime':s,'endTime':e}})
        except Exception as ex:
            print(f"    chunk {coin} {s}: {type(ex).__name__} {ex}")
            rows = []
        for c in rows or []:
            out[int(c['t'])] = {'t':int(c['t']),
                                'o':float(c['o']),'h':float(c['h']),
                                'l':float(c['l']),'c':float(c['c'])}
        s = e + 60000
        time.sleep(0.15)  # be polite
    return [out[k] for k in sorted(out)]

def run(pdir: Path, label: str):
    print(f"=== {label} ({pdir}) ===")
    for sym in HL_OK:
        b = cache_bounds(pdir, sym)
        if not b:
            print(f"  {sym}: no binance cache to align to — skip")
            continue
        lo, hi = b
        candles = fetch_hl(sym, lo, hi)
        outf = pdir / f"{sym}.hyperliquid.jsonl"
        outf.write_text('\n'.join(json.dumps(c) for c in candles))
        cov = f"{len(candles)} candles" if candles else "EMPTY (HL may lack history this far back)"
        print(f"  {sym}: {cov}  [{lo}..{hi}]")

if __name__ == '__main__':
    run(HERE / 'prices_may', 'MAY')
    run(HERE / 'prices', 'APRIL')
    print("done")
