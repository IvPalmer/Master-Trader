"""Pre-cache 1m OHLCV for the May 11-29 SCALP_CH ledger symbols (the +2702% claim).
Same offline-cache approach as fetch_prices.py. WEEX primary (cmt_), Binance parity.
Window May 9 -> Jun 11 (covers entries + the 12-day MAX_TAIL walk for late-May trades)."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "weex_probe"))
import proper_backtest as pb
import replay_on_weex as rw

HERE = Path(__file__).parent
OUT = HERE / "prices_may"        # separate cache so it never clobbers the April prices/
OUT.mkdir(exist_ok=True)

# every symbol appearing in the May 11-29 ledger / export signals
SYMBOLS = ["BTC","ETH","SOL","NEAR","FIDA","PUMP","HYPE","SKY","FARTCOIN","ETC",
           "FF","VIRTUAL","EIGEN","LTC","USELESS","TON"]
START = int(datetime(2026,5,9,tzinfo=timezone.utc).timestamp()*1000)
END   = int(datetime(2026,5,30,20,0,tzinfo=timezone.utc).timestamp()*1000)  # data end (WEEX rejects future endTime); late-May trades close via management within window

def save(sym, venue, candles):
    p = OUT / f"{sym}.{venue}.jsonl"
    with p.open("w") as f:
        for c in candles:
            f.write(json.dumps(c) + "\n")
    return len(candles)

summary = {}
for sym in SYMBOLS:
    row = {}
    try:
        wc = rw.fetch_weex_candles(sym, START, END)
        row["weex"] = save(sym, "weex", wc)
        if wc:
            row["span"] = (datetime.fromtimestamp(wc[0]["t"]/1000,timezone.utc).isoformat()[:16] + ".." +
                           datetime.fromtimestamp(wc[-1]["t"]/1000,timezone.utc).isoformat()[:16])
    except Exception as e:
        row["weex"] = f"ERR {str(e)[:50]}"
    try:
        bc = pb.fetch_binance(pb.binance_pair(sym), START, END)
        row["binance"] = save(sym, "binance", bc)
    except Exception as e:
        row["binance"] = f"ERR {str(e)[:50]}"
    summary[sym] = row
    print(f"{sym:10} weex={row.get('weex')!s:>8} binance={row.get('binance')!s:>8} {row.get('span','-')}", flush=True)

(HERE / "price_cache_may_summary.json").write_text(json.dumps(summary, indent=2))
print("\nDONE -> price_cache_may_summary.json")
