"""Download Binance USDT-M futures 15m klines for the Killers coin universe.

Per-symbol window = [first signal, last signal + 30d] capped at now. Throttled
to ~4 req/s (fapi weight budget). Writes ohlcv/{BSYM}.json and coverage.json.
"""
import json, time, urllib.request, urllib.error, os
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

DIR = "/home/ubuntu/killers_backtest"
OHLCV = f"{DIR}/ohlcv"
os.makedirs(OHLCV, exist_ok=True)

ALIASES = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI",
           "BONK": "1000BONK", "GOLD": "XAUT"}
INTERVAL = "15m"
HORIZON_DAYS = 30
NOW_MS = int(datetime.now(timezone.utc).timestamp() * 1000)


def bsym(sym):
    return ALIASES.get(sym.upper(), sym.upper()) + "USDT"


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# windows per symbol
trades = [json.loads(l) for l in open(f"{DIR}/trades.jsonl") if l.strip()]
win = {}
for t in trades:
    s = t["symbol"]
    if not s:
        continue
    ot = parse_dt(t["open_ts"])
    lo, hi = win.get(s, (ot, ot))
    win[s] = (min(lo, ot), max(hi, ot))

symbols = sorted(win)
print(f"symbols: {len(symbols)}", flush=True)


def fetch(sym):
    bs = bsym(sym)
    start_dt, last_dt = win[sym]
    start = int(start_dt.timestamp() * 1000)
    end = min(int((last_dt + timedelta(days=HORIZON_DAYS)).timestamp() * 1000), NOW_MS)
    rows = []
    cur = start
    pages = 0
    while cur < end:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={bs}"
               f"&interval={INTERVAL}&startTime={cur}&endTime={end}&limit=1500")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    return sym, bs, "invalid_symbol", []
                if e.code in (429, 418):
                    time.sleep(10)
                    continue
                if attempt == 3:
                    return sym, bs, f"http_{e.code}", rows
                time.sleep(2)
            except Exception:
                if attempt == 3:
                    return sym, bs, "neterr", rows
                time.sleep(2)
        else:
            return sym, bs, "retries_exhausted", rows
        if not data:
            break
        for k in data:
            # [open_time, o, h, l, c, v, ...]
            rows.append([k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4])])
        pages += 1
        last_open = data[-1][0]
        if last_open <= cur:
            break
        cur = last_open + 1
        time.sleep(0.25)  # ~4 req/s per worker; 3 workers -> stay under budget
    status = "ok" if rows else "empty"
    if rows:
        json.dump(rows, open(f"{OHLCV}/{bs}.json", "w"))
    return sym, bs, status, rows


cov = {}
done = 0
with ThreadPoolExecutor(max_workers=3) as ex:
    for sym, bs, status, rows in ex.map(fetch, symbols):
        cov[sym] = {"bsym": bs, "status": status, "rows": len(rows)}
        done += 1
        if done % 20 == 0 or status not in ("ok",):
            print(f"[{done}/{len(symbols)}] {sym}->{bs} {status} rows={len(rows)}", flush=True)

json.dump(cov, open(f"{DIR}/coverage.json", "w"), indent=2)
ok = sum(1 for v in cov.values() if v["status"] == "ok")
missing = [s for s, v in cov.items() if v["status"] != "ok"]
print(f"DONE. covered {ok}/{len(symbols)} symbols", flush=True)
print(f"missing: {missing}", flush=True)
