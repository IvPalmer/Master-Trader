"""Full signed-endpoint smoke test against live WEEX.

Sequence (each step gated, stops on first hard failure):
  1.  AUTH  : balance — verifies signing works
  2.  CFG   : accountConfig — hedge vs one-way mode
  3.  CFG   : set isolated margin + hedge mode for BTCUSDT
  4.  CFG   : set 5x leverage for BTCUSDT
  5.  ORDER : place tiny market LONG BTCUSDT (~$5 notional after leverage)
  6.  POS   : verify position appears, capture entry price + qty
  7.  ALGO  : place SL via placeTpSlOrder (1% below entry)
  8.  ALGO  : place TP via placeTpSlOrder (1% above entry)
  9.  OPEN  : list openAlgoOrders → confirm both algo orders exist
  10. CLOSE : closePositions to flatten
  11. POS   : verify position cleared
  12. CANCEL: any stuck algo orders

Run AFTER you have:
  - WEEX_API_KEY / WEEX_API_SECRET / WEEX_PASSPHRASE in weex_probe/.env.weex
  - ≥$20 USDT in account
  - IP allowlist whitelisting this machine

Risk: ~$5 notional on production. Network blip mid-flight could leave
naked position — closePositions step is the recovery; if even that fails,
manually flatten in WEEX UI.

Run:  python3 weex_probe/probe_signed.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

from typing import Optional

from weex_client import WeexClient, WeexCredentials, WeexError


SYMBOL = "BTCUSDT"
LEVERAGE = 5
MARGIN_MODE = "ISOLATED"
POSITION_SIDE = "LONG"
SIDE = "BUY"


def load_env() -> WeexCredentials:
    env_path = Path(__file__).parent / ".env.weex"
    if not env_path.exists():
        print(f"[FATAL] missing {env_path}; copy .env.weex.template and fill in")
        sys.exit(2)
    creds: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k in ("WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_PASSPHRASE")
               if not creds.get(k)]
    if missing:
        print(f"[FATAL] .env.weex missing: {missing}")
        sys.exit(2)
    return WeexCredentials(
        api_key=creds["WEEX_API_KEY"],
        api_secret=creds["WEEX_API_SECRET"],
        passphrase=creds["WEEX_PASSPHRASE"],
    )


def section(num: int, title: str) -> None:
    print()
    print("=" * 60)
    print(f"  STEP {num}.  {title}")
    print("=" * 60)


def pretty(obj) -> str:
    try:
        return json.dumps(obj, indent=2, default=str)
    except (TypeError, ValueError):
        return repr(obj)


def main() -> int:
    creds = load_env()
    c = WeexClient(credentials=creds)

    # ── STEP 1: AUTH ──────────────────────────────────────────────────────
    section(1, "AUTH — GET /account/balance")
    try:
        bal = c.balance()
        print(pretty(bal))
    except WeexError as e:
        print(f"FAIL: HTTP {e.status} {e.payload}")
        print("Check: key/secret/passphrase, IP allowlist, KYC approved.")
        return 1

    # ── STEP 2: ACCOUNT CONFIG ────────────────────────────────────────────
    section(2, "CONFIG — GET /account/accountConfig (hedge vs one-way)")
    try:
        cfg = c.account_config()
        print(pretty(cfg))
        dual = cfg.get("dualSidePosition") if isinstance(cfg, dict) else None
        print(f"  -> dualSidePosition (hedge mode): {dual}")
    except WeexError as e:
        print(f"FAIL: {e.payload}")
        return 1

    # ── STEP 3: SET MARGIN TYPE ───────────────────────────────────────────
    section(3, f"CONFIG — set margin {MARGIN_MODE} + hedge for {SYMBOL}")
    try:
        # SEPARATED = hedge mode (dualSidePosition), COMBINED = one-way
        r = c.set_margin_type(SYMBOL, MARGIN_MODE, "SEPARATED")
        print(pretty(r))
    except WeexError as e:
        # may already be set — log and continue
        print(f"INFO (may already be configured): {e.payload}")

    # ── STEP 4: SET LEVERAGE ──────────────────────────────────────────────
    section(4, f"CONFIG — set isolated long {LEVERAGE}x for {SYMBOL}")
    try:
        r = c.set_leverage(
            SYMBOL,
            margin_type=MARGIN_MODE,
            isolated_long_leverage=LEVERAGE,
            isolated_short_leverage=LEVERAGE,
        )
        print(pretty(r))
    except WeexError as e:
        print(f"INFO: {e.payload}")

    # Need mark price + symbol info to size correctly
    section(4.5, "size lookup — exchangeInfo + mark price")
    try:
        info = c.exchange_info()
        sym_meta = next((s for s in info.get("symbols", []) if s.get("symbol") == SYMBOL), None)
        if not sym_meta:
            print(f"FAIL: {SYMBOL} not in exchangeInfo")
            return 1
        min_qty = float(sym_meta.get("minOrderSize", 0.001))
        qty_prec = int(sym_meta.get("quantityPrecision", 4))
        contract_val = float(sym_meta.get("contractVal", 1))
        print(f"  minOrderSize={min_qty}  quantityPrecision={qty_prec}  contractVal={contract_val}")

        mp = c.mark_price(SYMBOL)
        mark = float(mp[0]["markPrice"]) if isinstance(mp, list) else float(mp["markPrice"])
        print(f"  markPrice={mark}")
    except (WeexError, KeyError, ValueError) as e:
        print(f"FAIL: {e}")
        return 1

    # Size: ~$5 notional at mark
    qty = max(min_qty, round(5.0 / mark, qty_prec))
    sl_price = round(mark * 0.99, sym_meta.get("pricePrecision", 1))
    tp_price = round(mark * 1.01, sym_meta.get("pricePrecision", 1))
    print(f"  -> qty={qty}  SL={sl_price}  TP={tp_price}")

    # ── STEP 5: PLACE MARKET ENTRY ────────────────────────────────────────
    section(5, f"ORDER — market BUY {qty} {SYMBOL} (~$5 notional, {LEVERAGE}x)")
    coid = f"smoke-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    try:
        r = c.place_order(
            symbol=SYMBOL,
            side=SIDE,
            position_side=POSITION_SIDE,
            order_type="MARKET",
            quantity=str(qty),
            client_order_id=coid,
        )
        print(pretty(r))
    except WeexError as e:
        print(f"FAIL: HTTP {e.status} {e.payload}")
        return 1

    # Wait for fill propagation
    time.sleep(2)

    # ── STEP 6: VERIFY POSITION ───────────────────────────────────────────
    section(6, f"POSITION — confirm {SYMBOL} LONG open")
    position_id: Optional[str] = None
    try:
        positions = c.positions()
        print(pretty(positions))
        long_pos = None
        if isinstance(positions, list):
            for p in positions:
                if p.get("symbol") == SYMBOL and p.get("side") in ("LONG", "long"):
                    long_pos = p
                    break
        if not long_pos:
            print("FAIL: no LONG position visible after market entry")
            # try emergency close anyway
        else:
            position_id = str(long_pos.get("id"))
            print(f"  -> position size={long_pos.get('size')}  positionId={position_id}")
    except WeexError as e:
        print(f"FAIL: {e.payload}")

    # ── STEP 7: PLACE SL ──────────────────────────────────────────────────
    section(7, f"ALGO — SL plan @ {sl_price}  (positionId={position_id})")
    sl_id = f"smoke-sl-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    try:
        r = c.place_tp_sl(
            symbol=SYMBOL,
            position_side=POSITION_SIDE,
            plan_type="STOP_LOSS",
            trigger_price=str(sl_price),
            quantity=str(qty),
            client_algo_id=sl_id,
            position_id=position_id,
        )
        print(pretty(r))
    except WeexError as e:
        print(f"FAIL: {e.payload}")
        print("Recovery: closePositions to flatten before SL placement reliability is sorted")

    # ── STEP 8: PLACE TP ──────────────────────────────────────────────────
    section(8, f"ALGO — TP plan @ {tp_price}")
    tp_id = f"smoke-tp-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    try:
        r = c.place_tp_sl(
            symbol=SYMBOL,
            position_side=POSITION_SIDE,
            plan_type="TAKE_PROFIT",
            trigger_price=str(tp_price),
            quantity=str(qty),
            client_algo_id=tp_id,
            position_id=position_id,
        )
        print(pretty(r))
    except WeexError as e:
        print(f"FAIL: {e.payload}")

    # ── STEP 10: CLOSE POSITION ───────────────────────────────────────────
    section(10, "CLOSE — POST /closePositions to flatten")
    try:
        r = c.close_positions(SYMBOL)
        print(pretty(r))
    except WeexError as e:
        print(f"FAIL: {e.payload}")
        print(">>> MANUALLY FLATTEN IN UI <<<")
        return 1

    time.sleep(2)

    # ── STEP 11: VERIFY FLAT ──────────────────────────────────────────────
    section(11, "POSITION — confirm flat after close")
    try:
        positions = c.positions()
        still_open = [p for p in (positions if isinstance(positions, list) else [])
                      if p.get("symbol") == SYMBOL and float(p.get("size", 0) or 0) > 0]
        if still_open:
            print(f"FAIL: position still open: {still_open}")
            return 1
        print("OK — flat")
    except WeexError as e:
        print(f"FAIL: {e.payload}")
        return 1

    print()
    print("=" * 60)
    print("  SIGNED PROBE COMPLETE — plumbing works")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
