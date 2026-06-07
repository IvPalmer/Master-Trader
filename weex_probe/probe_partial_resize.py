"""Critical unverified gap: after partial close, do the auto-spawned
SL/TP algos resize to the new position size, or keep the original
qty (and over-close on trigger)?

Procedure:
  1. Switch BTCUSDT to one-way mode (COMBINED)
  2. Open 0.0002 BTC LONG with attached SL + TP (qty=0.0002)
  3. Read openAlgoOrders — record SL qty, TP qty (should both be 0.0002)
  4. Partial-close 0.0001 (50%) via opposing-side /order SELL
  5. Read openAlgoOrders again — did SL qty and TP qty drop to 0.0001?
     If yes → atomic, safe.
     If no → SL/TP still 0.0002, trigger would oversell (0.0002 vs
       0.0001 remaining position) → architecture needs cancel+resize.
  6. Read positions to confirm current position size
  7. closePositions cleanup
  8. Restore SEPARATED for cleanliness
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


def algos(c, symbol):
    try:
        return c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": symbol}, auth=True)
    except WeexError as e:
        return {"err": e.payload}


def pos_size(c, symbol):
    positions = c.positions()
    p = next((p for p in positions if p.get("symbol") == symbol and float(p.get("size", 0) or 0) > 0), None)
    return float(p["size"]) if p else 0.0


def main() -> int:
    c = WeexClient(load_env())

    # Need to transfer from Spot back to Futures since we left only 1 USDT in Futures
    # Actually we have 23.29 in Futures still, good
    print(f"balance: {c.balance()}")

    # Step 1: switch to one-way mode
    print("\n=== STEP 1: switch BTCUSDT to one-way (COMBINED) ===")
    try:
        c.set_margin_type(SYMBOL, "ISOLATED", "COMBINED")
        c.set_leverage(SYMBOL, "ISOLATED", isolated_long_leverage=5, isolated_short_leverage=5)
        print("  ok")
    except WeexError as e:
        print(f"  info: {e.payload}")

    # Step 2: open with attached SL+TP
    mp = c.mark_price(SYMBOL)
    mark = float(mp[0]["markPrice"])
    sl_price = round(mark * 0.99, 1)
    tp_price = round(mark * 1.01, 1)
    qty = "0.0002"
    coid = f"resize-{int(time.time())}"
    print(f"\n=== STEP 2: open {qty} BTC LONG  mark={mark} SL={sl_price} TP={tp_price} ===")
    try:
        r = c._request("POST", "/capi/v3/order", body={
            "symbol": SYMBOL, "side": "BUY", "positionSide": "LONG", "type": "MARKET",
            "quantity": qty, "newClientOrderId": coid,
            "slTriggerPrice": str(sl_price), "SlWorkingType": "MARK_PRICE",
            "tpTriggerPrice": str(tp_price), "TpWorkingType": "MARK_PRICE",
        }, auth=True)
        print(f"  order: {r}")
    except WeexError as e:
        print(f"  FAIL {e.payload}")
        return 1
    time.sleep(2)

    # Step 3: read initial algos
    print("\n=== STEP 3: initial algos (expect both qty=0.0002) ===")
    initial = algos(c, SYMBOL)
    print(json.dumps(initial, indent=2, default=str))
    initial_sl = next((a for a in initial if a.get("orderType") == "STOP_MARKET"), {})
    initial_tp = next((a for a in initial if a.get("orderType") == "TAKE_PROFIT_MARKET"), {})
    print(f"  SL qty: {initial_sl.get('quantity')}")
    print(f"  TP qty: {initial_tp.get('quantity')}")

    # Step 4: partial close 50%
    print("\n=== STEP 4: partial close 0.0001 via /order SELL ===")
    try:
        r = c._request("POST", "/capi/v3/order", body={
            "symbol": SYMBOL, "side": "SELL", "positionSide": "LONG", "type": "MARKET",
            "quantity": "0.0001", "newClientOrderId": f"partial-{uuid.uuid4().hex[:8]}",
        }, auth=True)
        print(f"  partial: {r}")
    except WeexError as e:
        print(f"  FAIL {e.payload}")
    time.sleep(3)

    # Step 5: read algos again
    print("\n=== STEP 5: post-partial position + algos ===")
    sz = pos_size(c, SYMBOL)
    print(f"  position size now: {sz}")
    post = algos(c, SYMBOL)
    print(json.dumps(post, indent=2, default=str))
    post_sl = next((a for a in (post if isinstance(post, list) else []) if a.get("orderType") == "STOP_MARKET"), {})
    post_tp = next((a for a in (post if isinstance(post, list) else []) if a.get("orderType") == "TAKE_PROFIT_MARKET"), {})
    print(f"  SL qty after: {post_sl.get('quantity')}")
    print(f"  TP qty after: {post_tp.get('quantity')}")

    # Verdict
    print("\n=== VERDICT ===")
    initial_sl_qty = float(initial_sl.get("quantity", 0) or 0)
    post_sl_qty = float(post_sl.get("quantity", 0) or 0)
    initial_tp_qty = float(initial_tp.get("quantity", 0) or 0)
    post_tp_qty = float(post_tp.get("quantity", 0) or 0)
    if post_sl_qty == sz and post_tp_qty == sz:
        print("  AUTO-RESIZE: ✅  SL+TP shrunk to match remaining position")
    elif post_sl_qty == initial_sl_qty and post_tp_qty == initial_tp_qty:
        print(f"  AUTO-RESIZE: ❌  algos still original size ({initial_sl_qty}/{initial_tp_qty})")
        print(f"               position is {sz} — trigger would oversell!")
        print("               Architecture impact: partial-close needs cancel+replace")
    else:
        print(f"  AUTO-RESIZE: PARTIAL")
        print(f"               initial SL={initial_sl_qty} TP={initial_tp_qty}")
        print(f"               post SL={post_sl_qty} TP={post_tp_qty}")
        print(f"               position={sz}")

    # Cleanup
    print("\n=== cleanup ===")
    try:
        print(c.close_positions(SYMBOL))
    except WeexError as e:
        print(f"  {e.payload}")
    try:
        c.set_margin_type(SYMBOL, "ISOLATED", "SEPARATED")
        print("  restored SEPARATED")
    except WeexError as e:
        print(f"  info: {e.payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
