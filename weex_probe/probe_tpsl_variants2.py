"""Round 2: try positionId in query string + algoOrder field names."""
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

    qty = "0.0001"
    try:
        c.place_order(SYMBOL, "BUY", "LONG", "MARKET", qty, f"v2-{int(time.time())}")
    except WeexError as e:
        print(f"open FAIL: {e.payload}")
        return 1
    time.sleep(2)

    positions = c.positions()
    pos = next((p for p in positions if p.get("symbol") == SYMBOL and p.get("side") == "LONG"), None)
    if not pos:
        print("no position!")
        return 1
    pos_id = pos["id"]
    print(f"positionId: {pos_id}")

    mp = c.mark_price(SYMBOL)
    mark = float(mp[0]["markPrice"])
    sl_price = round(mark * 0.99, 1)
    tp_price = round(mark * 1.01, 1)
    print(f"mark={mark}  sl={sl_price}  tp={tp_price}\n")

    base_tpsl = {
        "symbol": SYMBOL, "positionSide": "LONG", "planType": "STOP_LOSS",
        "triggerPrice": str(sl_price), "quantity": qty, "triggerPriceType": "MARK_PRICE",
    }

    variants = [
        # placeTpSlOrder with positionId in QUERY string
        ("placeTpSl: positionId in query (int)", "POST", "/capi/v3/placeTpSlOrder",
         {"positionId": pos_id}, {**base_tpsl, "clientAlgoId": f"q1-{uuid.uuid4().hex[:8]}"}),
        ("placeTpSl: positionId in query (str)", "POST", "/capi/v3/placeTpSlOrder",
         {"positionId": str(pos_id)}, {**base_tpsl, "clientAlgoId": f"q2-{uuid.uuid4().hex[:8]}"}),
        # placeTpSlOrder body with int positionId AND symbol-uppercase Y/N
        ("placeTpSl: positionId int body, no triggerType",
         "POST", "/capi/v3/placeTpSlOrder", None,
         {"symbol": SYMBOL, "positionSide": "LONG", "planType": "STOP_LOSS",
          "triggerPrice": str(sl_price), "quantity": qty, "positionId": pos_id,
          "clientAlgoId": f"q3-{uuid.uuid4().hex[:8]}"}),
        # algoOrder — try clientOrderId without "new" prefix
        ("algoOrder: clientOrderId field", "POST", "/capi/v3/algoOrder", None,
         {"symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "STOP_MARKET",
          "quantity": qty, "stopPrice": str(sl_price), "workingType": "MARK_PRICE",
          "clientOrderId": f"a1-{uuid.uuid4().hex[:8]}"}),
        ("algoOrder: newClientAlgoId field", "POST", "/capi/v3/algoOrder", None,
         {"symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "STOP_MARKET",
          "quantity": qty, "stopPrice": str(sl_price), "workingType": "MARK_PRICE",
          "newClientAlgoId": f"a2-{uuid.uuid4().hex[:8]}"}),
        ("algoOrder: newClientOrderId + positionId", "POST", "/capi/v3/algoOrder", None,
         {"symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "STOP_MARKET",
          "quantity": qty, "stopPrice": str(sl_price), "workingType": "MARK_PRICE",
          "newClientOrderId": f"a3-{uuid.uuid4().hex[:8]}", "positionId": pos_id}),
        # Try modifyTpSlOrder semantics — maybe placeTpSlOrder actually requires a pre-existing
        # algo plan id?
        ("placeTpSl: with attached SL/TP on entry order — try order endpoint instead", "POST", "/capi/v3/order", None,
         {"symbol": SYMBOL, "side": "BUY", "positionSide": "LONG", "type": "MARKET",
          "quantity": "0.0001", "newClientOrderId": f"a4-{uuid.uuid4().hex[:8]}",
          "slTriggerPrice": str(sl_price), "SlWorkingType": "MARK_PRICE"}),
    ]

    for name, method, path, query, body in variants:
        print(f"=== {name} ===")
        try:
            r = c._request(method, path, query=query, body=body, auth=True)
            print(f"   SUCCESS  resp={json.dumps(r)[:400]}")
            algo_id = (r.get("orderId") if isinstance(r, dict) else None) or (r.get("data", {}).get("orderId") if isinstance(r, dict) else None)
            if algo_id:
                try:
                    cr = c._request("DELETE", "/capi/v3/algoOrder", body={"symbol": SYMBOL, "orderId": algo_id}, auth=True)
                    print(f"   cancelled: {cr}")
                except Exception as ce:
                    print(f"   cancel: {ce}")
        except WeexError as e:
            print(f"   FAIL  {e.payload}")
        except Exception as e:
            print(f"   ERR   {e}")

    print("\nflattening...")
    print(c.close_positions(SYMBOL))
    return 0


if __name__ == "__main__":
    sys.exit(main())
