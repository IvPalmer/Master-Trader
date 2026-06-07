"""Switch BTCUSDT to one-way (COMBINED) mode, retry partial close + SL move."""
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

    # Try switching to COMBINED (one-way)
    print("=== switching BTCUSDT to ISOLATED + COMBINED (one-way) ===")
    try:
        r = c.set_margin_type(SYMBOL, "ISOLATED", "COMBINED")
        print(f"   {r}")
    except WeexError as e:
        print(f"   FAIL {e.payload}")
        return 1

    # Verify
    cfg = c.account_config()
    print(f"   account dualSidePosition: {cfg.get('dualSidePosition')}")

    # Open 0.0002 with attached SL+TP — in one-way mode, positionSide may not be needed
    qty = "0.0002"
    coid = f"oneway-{int(time.time())}"
    mp = c.mark_price(SYMBOL)
    mark = float(mp[0]["markPrice"])
    sl_price = round(mark * 0.99, 1)
    tp_price = round(mark * 1.01, 1)
    print(f"\n=== open 0.0002 BTC LONG @ ~{mark} SL={sl_price} TP={tp_price} (one-way) ===")
    try:
        r = c._request("POST", "/capi/v3/order", body={
            "symbol": SYMBOL, "side": "BUY", "positionSide": "LONG", "type": "MARKET",
            "quantity": qty, "newClientOrderId": coid,
            "slTriggerPrice": str(sl_price), "SlWorkingType": "MARK_PRICE",
            "tpTriggerPrice": str(tp_price), "TpWorkingType": "MARK_PRICE",
        }, auth=True)
        print(r)
    except WeexError as e:
        print(f"   FAIL {e.payload}")
        return 1
    time.sleep(2)

    positions = c.positions()
    pos = next((p for p in positions if p.get("symbol") == SYMBOL and float(p.get("size",0) or 0) > 0), None)
    if not pos:
        print("no position!")
        return 1
    print(f"   position id={pos['id']} side={pos.get('side')} size={pos['size']}")
    pos_id = pos["id"]

    # === A: partial close via SELL ===
    print("\n=== A. /order SELL 0.0001 partial (one-way) ===")
    try:
        r = c._request("POST", "/capi/v3/order", body={
            "symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "MARKET",
            "quantity": "0.0001", "newClientOrderId": f"pa-{uuid.uuid4().hex[:8]}",
        }, auth=True)
        print(f"   SUCCESS {r}")
    except WeexError as e:
        print(f"   FAIL {e.payload}")
    time.sleep(2)
    pos = next((p for p in c.positions() if p.get("symbol") == SYMBOL and float(p.get("size",0) or 0) > 0), None)
    print(f"   position now: size={pos['size'] if pos else 'GONE'}")

    # === C. modifyTpSlOrder to move SL ===
    if pos:
        new_sl = round(mark * 0.995, 1)
        print(f"\n=== C. /modifyTpSlOrder move SL → {new_sl} ===")
        try:
            algos = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
            print(f"   current algos: {[(a.get('algoId'), a.get('orderType'), a.get('triggerPrice')) for a in algos]}")
            sl_algo = next((a for a in algos if a.get("orderType") == "STOP_MARKET"), None)
            if sl_algo:
                try:
                    r = c._request("POST", "/capi/v3/modifyTpSlOrder", body={
                        "symbol": SYMBOL, "orderId": sl_algo["algoId"],
                        "triggerPrice": str(new_sl),
                    }, auth=True)
                    print(f"   modify SUCCESS {r}")
                    algos2 = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
                    print(f"   after move: {[(a.get('algoId'), a.get('triggerPrice')) for a in algos2]}")
                except WeexError as e:
                    print(f"   modify FAIL {e.payload}")
            else:
                print(f"   no STOP_MARKET algo to modify")
        except WeexError as e:
            print(f"   list algos FAIL {e.payload}")

        # === D. cancel SL + new placeTpSlOrder in one-way ===
        print(f"\n=== D. cancel SL + placeTpSlOrder in one-way ===")
        try:
            algos = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
            sl_algo = next((a for a in algos if a.get("orderType") == "STOP_MARKET"), None)
            if sl_algo:
                cr = c._request("DELETE", "/capi/v3/algoOrder", body={"symbol": SYMBOL, "orderId": sl_algo["algoId"]}, auth=True)
                print(f"   cancelled: {cr}")
                try:
                    r = c._request("POST", "/capi/v3/placeTpSlOrder", body={
                        "symbol": SYMBOL, "positionSide": "LONG", "planType": "STOP_LOSS",
                        "triggerPrice": str(new_sl - 200), "quantity": str(pos["size"]),
                        "clientAlgoId": f"od-{uuid.uuid4().hex[:8]}", "triggerPriceType": "MARK_PRICE",
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

    # Switch back to SEPARATED for safety (we may want hedge later)
    print("\n=== restore SEPARATED (hedge) ===")
    try:
        r = c.set_margin_type(SYMBOL, "ISOLATED", "SEPARATED")
        print(f"   {r}")
    except WeexError as e:
        print(f"   info: {e.payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
