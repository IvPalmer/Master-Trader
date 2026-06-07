"""Fetch continuous 1h klines (with VOLUME) for all 172 channel coins + BTC over the signal
span (2024-03 -> 2026-06) for the Keltner-overlay test. Binance fapi. Cache keltner_1h/."""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "keltner_1h")
os.makedirs(OUT, exist_ok=True)
ALIAS = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK", "FLOKI": "1000FLOKI"}
START = int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)


def fsym(s): return ALIAS.get(s.upper(), s.upper()) + "USDT"


def fetch(sym):
    out, cur = [], START
    while cur < END:
        q = urllib.parse.urlencode({"symbol": sym, "interval": "1h", "startTime": cur, "endTime": END, "limit": 1500})
        try:
            req = urllib.request.Request("https://fapi.binance.com/fapi/v1/klines?" + q, headers={"User-Agent": "kelt/1.0"})
            rows = json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:
            if any(x in str(e) for x in ("400", "451", "404")):
                return None
            time.sleep(1.0); continue
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1500:
            break
        cur = rows[-1][0] + 3600_000
        time.sleep(0.03)
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in out]


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    coins = sorted(set(x["symbol"].upper() for x in sigs if x.get("symbol")))
    if "BTC" not in coins:
        coins.append("BTC")
    got = skip = 0
    for c in coins:
        fp = os.path.join(OUT, f"{c}.json")
        if os.path.exists(fp):
            got += 1; continue
        candles = fetch(fsym(c))
        if not candles or len(candles) < 200:
            skip += 1; print(f"  SKIP {c}", flush=True); continue
        json.dump(candles, open(fp, "w"))
        got += 1
        if got % 20 == 0:
            print(f"  {got} done ({c}: {len(candles)} candles)", flush=True)
    print(f"DONE got={got} skip={skip}")


if __name__ == "__main__":
    main()
