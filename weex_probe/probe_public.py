"""Probe WEEX public endpoints (no auth) to verify research spec.

Confirms:
  - base URL + path prefix are correct
  - exchangeInfo response shape, symbol naming
  - Dennis's signal universe is enumerated
  - mark price (premiumIndex) shape
  - klines intervals that work
  - depth quirk (no `limit` param)

Run:  python3 weex_probe/probe_public.py
"""
from __future__ import annotations

import json
import sys

from weex_client import WeexClient, WeexError


# Dennis's signal universe (top symbols by frequency from
# trades_llm_2026-05-26.json replay — 147 trades / 83 days)
DENNIS_TOP_SYMBOLS = [
    "BTC", "ETH", "PUMP", "ASTER", "FF", "XAUT", "ZEC", "HYPE",
    "XTIU", "XAG", "SOL", "LTC", "XRP", "HBAR", "BNB",
    "XMR", "UAI", "ETC", "ATOM", "AAVE",
    "FARTCOIN", "SIREN", "RENDER", "ARB", "APT",
    "PEPE",  # may be listed as 1000PEPE
    "TRUMP", "PLTR", "EGLD",
]

# Build candidate WEEX symbol names — try both raw and 1000-prefix
def candidates(sym: str) -> list[str]:
    s = sym.upper()
    cands = [f"{s}USDT"]
    if s in ("PEPE", "SHIB", "FLOKI", "BONK"):
        cands.append(f"1000{s}USDT")
    return cands


def main() -> int:
    c = WeexClient()
    fails = 0

    # 1. Server time
    print("=" * 60)
    print("1. SERVER TIME")
    try:
        st = c.server_time()
        print(json.dumps(st, indent=2))
    except Exception as e:
        print(f"FAIL: {e}")
        fails += 1

    # 2. Exchange info
    print("=" * 60)
    print("2. EXCHANGE INFO")
    try:
        info = c.exchange_info()
        symbols_field = info.get("symbols", [])
        print(f"keys at top: {sorted(info.keys())}")
        print(f"total symbols: {len(symbols_field)}")
        if symbols_field:
            print(f"first symbol entry: {json.dumps(symbols_field[0], indent=2)}")
        symbols_set = {s.get("symbol") for s in symbols_field}
    except Exception as e:
        print(f"FAIL: {e}")
        fails += 1
        symbols_set = set()

    # 3. Dennis pair coverage
    print("=" * 60)
    print("3. DENNIS SIGNAL UNIVERSE COVERAGE")
    found = []
    missing = []
    for sym in DENNIS_TOP_SYMBOLS:
        match = None
        for cand in candidates(sym):
            if cand in symbols_set:
                match = cand
                break
        if match:
            found.append((sym, match))
        else:
            missing.append(sym)
    print(f"FOUND ({len(found)}/{len(DENNIS_TOP_SYMBOLS)}):")
    for raw, mapped in found:
        marker = " (1000-prefix!)" if mapped != f"{raw}USDT" else ""
        print(f"  {raw:10s} -> {mapped}{marker}")
    print(f"MISSING ({len(missing)}/{len(DENNIS_TOP_SYMBOLS)}):")
    for sym in missing:
        print(f"  {sym}")

    # 4. Mark price for confirmed symbols
    print("=" * 60)
    print("4. MARK PRICE (premiumIndex)")
    for raw, mapped in found[:5]:
        try:
            mp = c.mark_price(mapped)
            print(f"  {mapped}: {mp if isinstance(mp, dict) else mp[0] if mp else 'empty'}")
        except Exception as e:
            print(f"  {mapped}: FAIL {e}")
            fails += 1

    # 5. Klines — verify which intervals work
    print("=" * 60)
    print("5. KLINES INTERVAL PROBE")
    intervals = ["1m", "5m", "15m", "1h", "4h", "1d"]
    for interval in intervals:
        try:
            k = c.klines("BTCUSDT", interval=interval, limit=2)
            ok = isinstance(k, list) and len(k) >= 1
            print(f"  {interval:5s}: {'OK' if ok else 'EMPTY'}  sample={k[:1] if ok else k}")
        except WeexError as e:
            print(f"  {interval:5s}: FAIL {e.payload}")
        except Exception as e:
            print(f"  {interval:5s}: FAIL {e}")

    # 6. Depth (no limit)
    print("=" * 60)
    print("6. DEPTH (no limit param)")
    try:
        d = c.depth("BTCUSDT")
        if isinstance(d, dict):
            print(f"  keys: {sorted(d.keys())}")
            for k in ("bids", "asks"):
                v = d.get(k)
                if v is not None:
                    print(f"  {k}: {len(v)} levels, top={v[0] if v else None}")
        else:
            print(f"  unexpected shape: {type(d).__name__} {str(d)[:200]}")
    except Exception as e:
        print(f"  FAIL: {e}")
        fails += 1

    # 7. Ticker 24hr — for liquidity sanity
    print("=" * 60)
    print("7. TICKER 24hr (all symbols)")
    try:
        t = c.ticker_24hr()
        if isinstance(t, list):
            print(f"  total: {len(t)}")
            if t:
                print(f"  sample fields: {sorted(t[0].keys())}")
                # Pull BTC + a thin one for comparison
                for x in t:
                    s = x.get("symbol") or x.get("Symbol")
                    if s in ("BTCUSDT", "PUMPUSDT", "ASTERUSDT", "FFUSDT"):
                        print(f"  {s}: {x}")
        else:
            print(f"  unexpected shape: {type(t).__name__} {str(t)[:200]}")
    except Exception as e:
        print(f"  FAIL: {e}")
        fails += 1

    # Summary
    print("=" * 60)
    print(f"PUBLIC PROBE COMPLETE  failures={fails}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
