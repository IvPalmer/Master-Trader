"""Fetch Binance fapi 1m caches for Feb+Mar Dennis signal coins (OOS test).
Writes harness-format jsonl ({t,o,h,l,c}) into prices_feb/ and prices_mar/.
Offline-after-cache. Binance only (verdict: copy Dennis on Binance; WEEX parity <0.1%)."""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ALIAS = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK", "FLOKI": "1000FLOKI"}

PLAN = {
    "prices_feb": (["BTC", "ETH", "HBAR", "BNB", "ATOM", "EGLD", "ETC", "PUMP", "ASTER"],
                   datetime(2026, 2, 1, tzinfo=timezone.utc), datetime(2026, 3, 13, tzinfo=timezone.utc)),
    "prices_mar": (["BTC", "PUMP", "XAUT"],  # XAUT will 4xx (no fapi) -> skipped
                   datetime(2026, 3, 1, tzinfo=timezone.utc), datetime(2026, 4, 13, tzinfo=timezone.utc)),
}


def fsym(s):
    return ALIAS.get(s.upper(), s.upper()) + "USDT"


def fetch(sym, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        q = urllib.parse.urlencode({"symbol": sym, "interval": "1m", "startTime": cur, "endTime": end_ms, "limit": 1500})
        try:
            req = urllib.request.Request("https://fapi.binance.com/fapi/v1/klines?" + q, headers={"User-Agent": "oos/1.0"})
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
        cur = rows[-1][0] + 60000
        time.sleep(0.04)
    return [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])} for r in out]


def main():
    for outdir, (coins, start, end) in PLAN.items():
        od = os.path.join(HERE, outdir)
        os.makedirs(od, exist_ok=True)
        sms, ems = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        for c in coins:
            candles = fetch(fsym(c), sms, ems)
            if not candles:
                print(f"  {outdir}/{c}: SKIP (no data)"); continue
            with open(os.path.join(od, f"{c.upper()}.binance.jsonl"), "w") as f:
                for cd in candles:
                    f.write(json.dumps(cd) + "\n")
            span = datetime.fromtimestamp(candles[0]["t"]/1000, timezone.utc).isoformat()[:10] + ".." + datetime.fromtimestamp(candles[-1]["t"]/1000, timezone.utc).isoformat()[:10]
            print(f"  {outdir}/{c}: {len(candles)} candles {span}", flush=True)


if __name__ == "__main__":
    main()
