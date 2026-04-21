#!/usr/bin/env python3
"""
Pre-flight check for FundingFadeV1 live whitelist.

For each pair in the static whitelist, verify:
  - Symbol is actively trading on Binance spot
  - minNotional × 1.5 ≤ stake_amount (50% headroom for rounding + price drift)
  - A $15 order at current price passes LOT_SIZE stepSize + PRICE_FILTER tickSize

Exits non-zero if any pair fails. Does NOT touch the API key — uses public endpoints only.
"""
from __future__ import annotations

import json
import sys
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import requests

LIVE_CONFIG = Path(__file__).parent.parent / "user_data/configs/FundingFadeV1.live.json"
BINANCE_SPOT = "https://api.binance.com"


def load_whitelist_and_stake() -> tuple[list[str], float]:
    cfg = json.loads(LIVE_CONFIG.read_text())
    wl = cfg["exchange"]["pair_whitelist"]
    stake = float(cfg["stake_amount"])
    return wl, stake


def fetch_exchange_info() -> dict:
    r = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_price(symbol: str) -> Decimal:
    r = requests.get(
        f"{BINANCE_SPOT}/api/v3/ticker/price",
        params={"symbol": symbol},
        timeout=10,
    )
    r.raise_for_status()
    return Decimal(r.json()["price"])


def decimal_floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def check_pair(pair: str, stake: float, info_by_symbol: dict) -> list[str]:
    """Return list of failure reasons, empty list = OK."""
    symbol = pair.replace("/", "")
    fails: list[str] = []
    info = info_by_symbol.get(symbol)
    if not info:
        return [f"symbol {symbol} NOT in Binance exchangeInfo"]

    if info["status"] != "TRADING":
        fails.append(f"symbol status={info['status']} (need TRADING)")

    # Binance's live schema now uses isSpotTradingAllowed + permissionSets (list of
    # lists). Older responses used a flat `permissions` array.
    spot_allowed = info.get("isSpotTradingAllowed")
    if spot_allowed is None:
        perm_sets = info.get("permissionSets") or []
        flat = info.get("permissions") or []
        spot_allowed = any("SPOT" in p for p in perm_sets) or "SPOT" in flat
    if not spot_allowed:
        fails.append("symbol does not allow SPOT trading")

    filters = {f["filterType"]: f for f in info["filters"]}

    min_notional = None
    if "NOTIONAL" in filters:
        min_notional = Decimal(filters["NOTIONAL"]["minNotional"])
    elif "MIN_NOTIONAL" in filters:
        min_notional = Decimal(filters["MIN_NOTIONAL"]["minNotional"])
    if min_notional is not None:
        headroom_needed = min_notional * Decimal("1.5")
        if headroom_needed > Decimal(str(stake)):
            fails.append(
                f"minNotional {min_notional} × 1.5 = {headroom_needed} > stake {stake}"
            )

    lot = filters.get("LOT_SIZE")
    price_filter = filters.get("PRICE_FILTER")
    if lot and price_filter:
        step_size = Decimal(lot["stepSize"])
        min_qty = Decimal(lot["minQty"])
        try:
            price = fetch_price(symbol)
        except Exception as e:
            fails.append(f"price fetch failed: {e}")
            return fails
        if price <= 0:
            fails.append(f"price {price} invalid")
            return fails
        qty = Decimal(str(stake)) / price
        qty_floored = decimal_floor_step(qty, step_size)
        notional = qty_floored * price
        if qty_floored < min_qty:
            fails.append(
                f"${stake} @ {price} → qty {qty_floored} < minQty {min_qty}"
            )
        if min_notional is not None and notional < min_notional:
            fails.append(
                f"${stake} @ {price} after step-floor → notional {notional} < minNotional {min_notional}"
            )
    return fails


def main() -> int:
    whitelist, stake = load_whitelist_and_stake()
    print(f"[preflight] live config: {LIVE_CONFIG.name}")
    print(f"[preflight] stake: ${stake}, {len(whitelist)} pairs")
    info = fetch_exchange_info()
    info_by_symbol = {s["symbol"]: s for s in info["symbols"]}

    failed = 0
    for pair in whitelist:
        fails = check_pair(pair, stake, info_by_symbol)
        if not fails:
            print(f"  OK   {pair}")
        else:
            failed += 1
            print(f"  FAIL {pair}")
            for f in fails:
                print(f"       - {f}")

    print()
    if failed:
        print(f"[preflight] {failed}/{len(whitelist)} pairs FAILED. Do NOT flip live.")
        return 1
    print(f"[preflight] All {len(whitelist)} pairs pass. Whitelist is flight-ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
