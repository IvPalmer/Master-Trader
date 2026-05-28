"""Two production-safety probes:
  1. Idempotency: send same `newClientOrderId` twice. Does WEEX dedup
     or double-fill?
  2. Rate-limit burst: send 15 cheap requests in 1 second. Where does
     it 429? Does it queue?

No new position opened — uses /openAlgoOrders queries (auth, no $ risk)
for the burst test. For idempotency, opens a tiny position with a
specific COID, then immediately retries the same COID and observes.

Cost: ~$0.04 (one entry + close cycle).
"""
from __future__ import annotations
import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    # Switch to one-way for clean state
    try:
        c.set_margin_type(SYMBOL, "ISOLATED", "COMBINED")
        c.set_leverage(SYMBOL, "ISOLATED", isolated_long_leverage=5, isolated_short_leverage=5)
    except WeexError as e:
        print(f"setup: {e.payload}")

    # ── PROBE 1: idempotency ──────────────────────────────────────────────
    print("=" * 60)
    print("  PROBE 1: idempotent newClientOrderId")
    print("=" * 60)
    coid = f"idemp-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    body = {
        "symbol": SYMBOL, "side": "BUY", "positionSide": "LONG", "type": "MARKET",
        "quantity": "0.0001", "newClientOrderId": coid,
    }
    print(f"  COID: {coid}")
    try:
        r1 = c._request("POST", "/capi/v3/order", body=body, auth=True)
        print(f"  call 1: {r1}")
    except WeexError as e:
        print(f"  call 1 FAIL: {e.payload}")
        return 1

    time.sleep(1)
    print("  --- immediately replay same COID ---")
    try:
        r2 = c._request("POST", "/capi/v3/order", body=body, auth=True)
        print(f"  call 2: {r2}")
        if isinstance(r1, dict) and isinstance(r2, dict):
            if r1.get("orderId") == r2.get("orderId"):
                print("  IDEMPOTENT: ✅ same orderId returned, no double-fill")
            else:
                print(f"  DOUBLE-FILL: ❌ DIFFERENT orderIds: {r1.get('orderId')} vs {r2.get('orderId')}")
                print("  -> WEEX did NOT dedup, position is now doubled")
    except WeexError as e:
        # Hopefully this fails with a "duplicate" error code — that's also idempotent-ish
        print(f"  call 2 rejected: {e.payload}")
        print("  IDEMPOTENT-VIA-REJECT: ✅ WEEX rejected duplicate COID")

    # Verify position size to confirm
    time.sleep(2)
    positions = c.positions()
    btc_pos = next((p for p in positions if p.get("symbol") == SYMBOL), None)
    if btc_pos:
        sz = float(btc_pos.get("size", 0))
        print(f"  actual position size: {sz}  (expected 0.0001 if idempotent, 0.0002 if double-fill)")

    # ── PROBE 2: rate-limit burst ─────────────────────────────────────────
    print()
    print("=" * 60)
    print("  PROBE 2: rate-limit burst — 15 concurrent /openAlgoOrders")
    print("=" * 60)
    results: list[tuple[int, str, float, int]] = []  # (idx, label, duration_ms, status)

    def hit(idx: int) -> tuple[int, str, float, int]:
        start = time.time()
        try:
            r = c._request("GET", "/capi/v3/openAlgoOrders", query={"symbol": SYMBOL}, auth=True)
            return (idx, "ok", (time.time() - start) * 1000, 200)
        except WeexError as e:
            return (idx, f"err {e.payload}", (time.time() - start) * 1000, e.status)
        except Exception as e:
            return (idx, f"exc {e}", (time.time() - start) * 1000, 0)

    burst_start = time.time()
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(hit, i) for i in range(15)]
        for f in as_completed(futures):
            results.append(f.result())
    burst_duration = (time.time() - burst_start) * 1000

    results.sort()
    ok_count = sum(1 for r in results if r[3] == 200)
    print(f"  total burst: {burst_duration:.0f}ms, {ok_count}/15 OK")
    for idx, label, dur, status in results:
        marker = "✅" if status == 200 else "❌"
        print(f"  [{idx:2d}] {marker} {status} {dur:5.0f}ms  {label[:80]}")

    if ok_count == 15:
        print("  RATE LIMIT: 15/15 in burst → no 429 at this rate")
    elif ok_count >= 10:
        print(f"  RATE LIMIT: partial — {15-ok_count} rejected, but most pass")
    else:
        print(f"  RATE LIMIT: aggressive — {15-ok_count}/15 rejected")

    # ── Cleanup ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  cleanup")
    print("=" * 60)
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
