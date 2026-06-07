"""Empirical probe: find correct positionId field for placeTpSlOrder in hedge mode.

Opens one tiny BTCUSDT long, captures position id, tries multiple field-name
+ type + endpoint variants for SL placement, then closes.
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

    # Open position
    qty = "0.0001"
    coid = f"varprobe-{int(time.time())}"
    try:
        c.place_order(SYMBOL, "BUY", "LONG", "MARKET", qty, coid)
    except WeexError as e:
        print(f"open FAIL: {e.payload}")
        return 1
    print(f"opened, sleeping 2s for propagation...")
    time.sleep(2)

    positions = c.positions()
    pos = next((p for p in positions if p.get("symbol") == SYMBOL and p.get("side") == "LONG"), None)
    if not pos:
        print("no position!")
        return 1
    pos_id_int = int(pos["id"])
    pos_id_str = str(pos_id_int)
    print(f"positionId (int): {pos_id_int}")
    print(f"positionId (str): {pos_id_str}")

    # Mark for SL price (~1% below)
    mp = c.mark_price(SYMBOL)
    mark = float(mp[0]["markPrice"])
    sl_price = round(mark * 0.99, 1)
    print(f"mark={mark}, sl_price={sl_price}\n")

    base_body = {
        "symbol": SYMBOL,
        "positionSide": "LONG",
        "planType": "STOP_LOSS",
        "triggerPrice": str(sl_price),
        "quantity": qty,
        "triggerPriceType": "MARK_PRICE",
    }

    variants = [
        ("positionId as int",        "/capi/v3/placeTpSlOrder", {**base_body, "clientAlgoId": f"v1-{uuid.uuid4().hex[:8]}", "positionId": pos_id_int}),
        ("positionId as str",        "/capi/v3/placeTpSlOrder", {**base_body, "clientAlgoId": f"v2-{uuid.uuid4().hex[:8]}", "positionId": pos_id_str}),
        ("posId as int",             "/capi/v3/placeTpSlOrder", {**base_body, "clientAlgoId": f"v3-{uuid.uuid4().hex[:8]}", "posId": pos_id_int}),
        ("holdSide+positionId int",  "/capi/v3/placeTpSlOrder", {**base_body, "clientAlgoId": f"v4-{uuid.uuid4().hex[:8]}", "positionId": pos_id_int, "holdSide": "LONG"}),
        ("algoOrder endpoint",       "/capi/v3/algoOrder",      {"symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "STOP_MARKET", "quantity": qty, "stopPrice": str(sl_price), "newClientOrderId": f"v5-{uuid.uuid4().hex[:8]}", "workingType": "MARK_PRICE"}),
    ]

    for name, path, body in variants:
        print(f"=== {name} ===  path={path}")
        try:
            r = c._request("POST", path, body=body, auth=True)
            print(f"   SUCCESS  resp={json.dumps(r)[:300]}")
            # Cancel immediately so it doesn't trigger
            algo_id = r.get("orderId") if isinstance(r, dict) else None
            if algo_id:
                try:
                    if "algoOrder" in path:
                        c._request("DELETE", "/capi/v3/algoOrder", body={"symbol": SYMBOL, "orderId": algo_id}, auth=True)
                    else:
                        c._request("DELETE", "/capi/v3/algoOrder", body={"symbol": SYMBOL, "orderId": algo_id}, auth=True)
                    print(f"   cancelled {algo_id}")
                except Exception as ce:
                    print(f"   cancel issue: {ce}")
        except WeexError as e:
            print(f"   FAIL  {e.payload}")
        except Exception as e:
            print(f"   ERR   {e}")

    print("\nflattening...")
    print(c.close_positions(SYMBOL))
    return 0


if __name__ == "__main__":
    sys.exit(main())
