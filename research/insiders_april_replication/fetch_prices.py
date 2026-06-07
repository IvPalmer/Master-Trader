"""Pre-cache 1m OHLCV for every symbol in Dennis's April 17-May 6 ledger.

WEEX (cmt_<sym>usdt via /capi/v2/market/historyCandles) is the primary source —
it serves the obscure alts (TRADOOR, LYN, PIPPIN, NAORIS, LAB) that Binance does
not list. Binance fapi is fetched too where available (parity check + majors).

Run once; writes prices/<SYM>.weex.jsonl and prices/<SYM>.binance.jsonl.
Offline after that, so the backtest harness + review subagents never touch the
network (deterministic, no rate-limit flakiness).
"""
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/Users/palmer/Work/Dev/master-trader/weex_probe")
import proper_backtest as pb          # fetch_binance, binance_pair
import replay_on_weex as rw           # fetch_weex_candles (V2 historyCandles, cmt_ fmt)

HERE = Path(__file__).parent
OUT = HERE / "prices"
OUT.mkdir(exist_ok=True)

# Every symbol that appears in the April 17-May 6 STATS ledger
SYMBOLS = ["BTC","ETH","ASTER","SOL","AAVE","SEI","LYN","TRADOOR","TAO","PENDLE",
           "FARTCOIN","PIPPIN","BIO","APT","B","RIVER","NAORIS","LAB","ZEC"]

START = int(datetime(2026,4,16,tzinfo=timezone.utc).timestamp()*1000)
END   = int(datetime(2026,5,18,tzinfo=timezone.utc).timestamp()*1000)

def save(sym, venue, candles):
    p = OUT / f"{sym}.{venue}.jsonl"
    with p.open("w") as f:
        for c in candles:
            f.write(json.dumps(c) + "\n")
    return len(candles)

summary = {}
for sym in SYMBOLS:
    row = {}
    # WEEX (primary — has the alts)
    try:
        wc = rw.fetch_weex_candles(sym, START, END)
        row["weex"] = save(sym, "weex", wc)
        if wc:
            row["weex_first"] = datetime.fromtimestamp(wc[0]["t"]/1000, timezone.utc).isoformat()[:16]
            row["weex_last"]  = datetime.fromtimestamp(wc[-1]["t"]/1000, timezone.utc).isoformat()[:16]
    except Exception as e:
        row["weex"] = f"ERR {str(e)[:60]}"
    # Binance (majors + parity)
    try:
        bc = pb.fetch_binance(pb.binance_pair(sym), START, END)
        row["binance"] = save(sym, "binance", bc)
    except Exception as e:
        row["binance"] = f"ERR {str(e)[:60]}"
    summary[sym] = row
    print(f"{sym:10} weex={row.get('weex')!s:>7}  binance={row.get('binance')!s:>7}  "
          f"weex_span={row.get('weex_first','-')}..{row.get('weex_last','-')}", flush=True)

(HERE / "price_cache_summary.json").write_text(json.dumps(summary, indent=2))
print("\nDONE. summary -> price_cache_summary.json")
