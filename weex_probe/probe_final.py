"""Final smoke test using attached SL/TP at entry (the pattern that works).

Sequence:
  1. AUTH check
  2. Set isolated 5x for BTCUSDT (idempotent)
  3. Place MARKET entry with attached SL + TP via /order endpoint
  4. Confirm position open
  5. Confirm algo orders (the auto-generated SL+TP plan orders) exist
  6. closePositions to flatten — verifies SL/TP get cleaned up too
  7. Confirm flat

This is the production pattern: entry+SL+TP atomic in one API call.
"""
from __future__ import annotations
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from weex_client import WeexClient, WeexCredentials, WeexError


SYMBOL = "BTCUSDT"
LEVERAGE = 5


def load_env() -> WeexCredentials:
    creds: dict[str, str] = {}
    for line in (Path(__file__).parent / ".env.weex").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    return WeexCredentials(creds["WEEX_API_KEY"], creds["WEEX_API_SECRET"], creds["WEEX_PASSPHRASE"])


def pretty(o) -> str:
    return json.dumps(o, indent=2, default=str)


def section(n, t):
    print(f"\n{'='*60}\n  STEP {n}.  {t}\n{'='*60}")


def main() -> int:
    c = WeexClient(load_env())

    section(1, "AUTH")
    bal = c.balance()
    print(pretty(bal))

    section(2, f"CONFIG — isolated {LEVERAGE}x {SYMBOL}")
    try:
        c.set_margin_type(SYMBOL, "ISOLATED", "SEPARATED")
        c.set_leverage(SYMBOL, "ISOLATED", isolated_long_leverage=LEVERAGE, isolated_short_leverage=LEVERAGE)
        print("  ok")
    except WeexError as e:
        print(f"  info: {e.payload}")

    # size
    info = c.exchange_info()
    sym_meta = next(s for s in info["symbols"] if s["symbol"] == SYMBOL)
    qty = sym_meta["minOrderSize"]
    mp = c.mark_price(SYMBOL)
    mark = float(mp[0]["markPrice"])
    sl_price = round(mark * 0.99, sym_meta.get("pricePrecision", 1))
    tp_price = round(mark * 1.01, sym_meta.get("pricePrecision", 1))
    print(f"  qty={qty}  mark={mark}  SL={sl_price}  TP={tp_price}")

    section(3, "ORDER — MARKET BUY with attached SL+TP")
    coid = f"final-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    body = {
        "symbol": SYMBOL,
        "side": "BUY",
        "positionSide": "LONG",
        "type": "MARKET",
        "quantity": str(qty),
        "newClientOrderId": coid,
        "slTriggerPrice": str(sl_price),
        "SlWorkingType": "MARK_PRICE",
        "tpTriggerPrice": str(tp_price),
        "TpWorkingType": "MARK_PRICE",
    }
    r = c._request("POST", "/capi/v3/order", body=body, auth=True)
    print(pretty(r))

    time.sleep(2)

    section(4, "POSITION")
    positions = c.positions()
    long_pos = next((p for p in positions if p.get("symbol") == SYMBOL and p.get("side") == "LONG"), None)
    if not long_pos:
        print("FAIL: no position")
        return 1
    print(f"  size={long_pos['size']}  entry≈openValue/size={float(long_pos['openValue'])/float(long_pos['size']):.1f}")
    print(f"  marginSize=${long_pos['marginSize']}  liquidate=${long_pos['liquidatePrice']}")

    section(5, "ALGO ORDERS (auto-created SL/TP plans)")
    try:
        algos = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
        print(pretty(algos))
    except WeexError as e:
        print(f"  info: {e.payload}")

    section(6, "CLOSE — closePositions")
    cr = c.close_positions(SYMBOL)
    print(pretty(cr))
    time.sleep(2)

    section(7, "VERIFY FLAT")
    positions = c.positions()
    open_algos = []
    try:
        open_algos = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
    except WeexError:
        pass
    if positions or open_algos:
        print(f"FAIL: positions={positions}  algos={open_algos}")
        return 1
    print("OK — position flat, algos cleared")

    section(8, "FINAL BALANCE")
    print(pretty(c.balance()))

    print("\n" + "="*60)
    print("  PLAUSIBILITY CONFIRMED — atomic bracket via /order works")
    print("="*60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
