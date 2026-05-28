"""Probe partial close + SL move endpoints.

Open small BTC LONG with attached SL, then try:
  A) partial close via /order SELL side (hedge opposing side)
  B) partial close via /closePositions with quantity
  C) move SL via modifyTpSlOrder
  D) move SL via cancel existing algo + place new with placeTpSlOrder
  E) cancel attached SL algo via cancel_order then place new attached SL
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


def load_env() -> WeexCredentials:
    creds: dict[str, str] = {}
    for line in (Path(__file__).parent / ".env.weex").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    return WeexCredentials(creds["WEEX_API_KEY"], creds["WEEX_API_SECRET"], creds["WEEX_PASSPHRASE"])


def main() -> int:
    c = WeexClient(load_env())

    # Open 0.0002 so we can split it into halves
    qty = "0.0002"
    coid = f"split-{int(time.time())}"
    mp = c.mark_price(SYMBOL)
    mark = float(mp[0]["markPrice"])
    sl_price = round(mark * 0.99, 1)
    tp_price = round(mark * 1.01, 1)

    print(f"=== open: 0.0002 BTC LONG @ ~{mark} SL={sl_price} TP={tp_price} ===")
    r = c._request("POST", "/capi/v3/order", body={
        "symbol": SYMBOL, "side": "BUY", "positionSide": "LONG", "type": "MARKET",
        "quantity": qty, "newClientOrderId": coid,
        "slTriggerPrice": str(sl_price), "SlWorkingType": "MARK_PRICE",
        "tpTriggerPrice": str(tp_price), "TpWorkingType": "MARK_PRICE",
    }, auth=True)
    print(r)
    time.sleep(2)

    positions = c.positions()
    pos = next((p for p in positions if p.get("symbol") == SYMBOL and p.get("side") == "LONG"), None)
    pos_id = pos["id"]
    print(f"position open size={pos['size']} id={pos_id}")

    # ===== A. partial close via SELL on hedge mode =====
    print("\n=== A. /order SELL 0.0001 to reduce position (hedge opposing) ===")
    try:
        r = c._request("POST", "/capi/v3/order", body={
            "symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "MARKET",
            "quantity": "0.0001", "newClientOrderId": f"partial-a-{uuid.uuid4().hex[:8]}",
        }, auth=True)
        print(f"   SUCCESS {r}")
    except WeexError as e:
        print(f"   FAIL {e.payload}")

    time.sleep(2)
    pos = next((p for p in c.positions() if p.get("symbol") == SYMBOL and p.get("side") == "LONG"), None)
    print(f"   position now: size={pos['size'] if pos else 'GONE'}")

    # ===== B. closePositions with quantity field (try the field even if undocumented) =====
    print("\n=== B. /closePositions with quantity field (probe) ===")
    try:
        r = c._request("POST", "/capi/v3/closePositions", body={
            "symbol": SYMBOL, "quantity": "0.00005",  # close half of remaining
        }, auth=True)
        print(f"   resp={r}")
    except WeexError as e:
        print(f"   FAIL {e.payload}")
    time.sleep(2)
    pos = next((p for p in c.positions() if p.get("symbol") == SYMBOL and p.get("side") == "LONG"), None)
    print(f"   position now: size={pos['size'] if pos else 'GONE'}")

    # If we still have a position, try SL move endpoints
    if pos:
        new_sl = round(mark * 0.995, 1)  # tighten SL

        # ===== C. modifyTpSlOrder =====
        print(f"\n=== C. /modifyTpSlOrder to move SL → {new_sl} ===")
        # need the current SL algo id
        try:
            algos = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
            print(f"   open algos: {[(a.get('algoId'), a.get('orderType'), a.get('triggerPrice')) for a in algos]}")
            sl_algo = next((a for a in algos if a.get("orderType") == "STOP_MARKET"), None)
            if sl_algo:
                try:
                    r = c._request("POST", "/capi/v3/modifyTpSlOrder", body={
                        "symbol": SYMBOL, "orderId": sl_algo["algoId"],
                        "triggerPrice": str(new_sl),
                    }, auth=True)
                    print(f"   SUCCESS {r}")
                except WeexError as e:
                    print(f"   FAIL {e.payload}")
            else:
                print(f"   no SL algo found to modify")
        except WeexError as e:
            print(f"   list algos FAIL {e.payload}")

        # ===== D. cancel existing SL + place new via placeTpSlOrder =====
        print(f"\n=== D. cancel SL algo + new placeTpSlOrder ===")
        try:
            algos = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
            sl_algo = next((a for a in algos if a.get("orderType") == "STOP_MARKET"), None)
            if sl_algo:
                cr = c._request("DELETE", "/capi/v3/algoOrder", body={"symbol": SYMBOL, "orderId": sl_algo["algoId"]}, auth=True)
                print(f"   cancel: {cr}")
                # now try placeTpSlOrder again now that no SL exists
                try:
                    r = c._request("POST", "/capi/v3/placeTpSlOrder", body={
                        "symbol": SYMBOL, "positionSide": "LONG", "planType": "STOP_LOSS",
                        "triggerPrice": str(new_sl - 100), "quantity": str(pos["size"]),
                        "clientAlgoId": f"d-{uuid.uuid4().hex[:8]}", "triggerPriceType": "MARK_PRICE",
                        "positionId": pos_id,
                    }, auth=True)
                    print(f"   placeTpSl SUCCESS {r}")
                except WeexError as e:
                    print(f"   placeTpSl FAIL {e.payload}")
        except WeexError as e:
            print(f"   {e.payload}")

    # cleanup
    print("\n=== cleanup ===")
    try:
        print(c.close_positions(SYMBOL))
    except WeexError as e:
        print(f"   {e.payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
