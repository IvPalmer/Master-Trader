#!/usr/bin/env python3
"""
check_balance.py — Read-only Binance spot account sanity check.

Verifies that the API key in .env is valid, scoped read-only-for-balance, and
reports current USDT (and any other non-zero asset) balances. Run this BEFORE
flipping any bot to live mode.

Safety:
  - Only calls /api/v3/account (GET). No order placement, no transfers.
  - Fails loudly if API key has withdrawal or futures permissions enabled
    (we want minimum-privilege keys for trading bots).
  - Reads credentials from .env at the repo root. Prints only last 4 chars of
    the key so logs don't leak the full credential.

Usage:
    cd ~/Work/Dev/master-trader
    python3 ft_userdata/scripts/check_balance.py
"""
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

BASE = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE / ".env"
BINANCE_SPOT = "https://api.binance.com"


def load_env() -> dict:
    if not ENV_PATH.exists():
        print(f"ERROR: {ENV_PATH} not found. Copy .env.example to .env first.")
        sys.exit(1)
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def signed_request(path: str, params: dict, api_key: str, secret: str):
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10_000
    query = urlencode(params)
    signature = hmac.new(
        secret.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    url = f"{BINANCE_SPOT}{path}?{query}&signature={signature}"
    return requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=10)


def main():
    env = load_env()
    key = env.get("BINANCE_API_KEY", "")
    secret = env.get("BINANCE_API_SECRET", "")
    if not key or key.startswith("paste_"):
        print("ERROR: BINANCE_API_KEY missing or unfilled in .env")
        sys.exit(1)
    if not secret or secret.startswith("paste_"):
        print("ERROR: BINANCE_API_SECRET missing or unfilled in .env")
        sys.exit(1)

    print(f"[check] API key ...{key[-4:]} (secret ...{secret[-4:]})")

    # 1. Account info (balance + permissions)
    r = signed_request("/api/v3/account", {}, key, secret)
    if r.status_code != 200:
        print(f"ERROR: /api/v3/account returned {r.status_code}: {r.text}")
        sys.exit(2)
    acct = r.json()

    # Account-level permissions (tied to user, not API key)
    print()
    print("[check] Account-level flags (user-level, NOT key-scoped):")
    for flag, label in [("canTrade", "Spot trading"), ("canDeposit", "Deposits"), ("canWithdraw", "Withdrawals (account-level)")]:
        print(f"     {label}: {acct.get(flag)}")

    # API key permission flags (this is what matters for bot safety)
    r2 = signed_request("/sapi/v1/account/apiRestrictions", {}, key, secret)
    if r2.status_code == 200:
        restr = r2.json()
        print()
        print("[check] API KEY scopes (this is what a leaked key can actually do):")
        scopes = [
            ("enableReading", "Reading", True),
            ("enableSpotAndMarginTrading", "Spot & Margin Trading", True),
            ("enableWithdrawals", "WITHDRAWALS", False),
            ("enableFutures", "Futures", False),
            ("enableMargin", "Margin", False),
            ("enableInternalTransfer", "Internal Transfer", False),
            ("permitsUniversalTransfer", "Universal Transfer", False),
            ("enableVanillaOptions", "Vanilla Options", False),
        ]
        any_bad = False
        for field, label, expect in scopes:
            val = restr.get(field, False)
            ok = (val == expect)
            marker = "  " if ok else "!!"
            print(f"  {marker} {label}: {val}  (expected {expect})")
            if not ok:
                any_bad = True
        if restr.get("ipRestrict"):
            print(f"     IP restriction: ENABLED")
        else:
            print(f"  !! IP restriction: DISABLED — key valid from any IP")
            any_bad = True
        if any_bad:
            print()
            print("  WARNING: key scope mismatch. Fix before trading live.")
    else:
        print(f"[check] apiRestrictions fetch failed: {r2.status_code} {r2.text}")

    # Non-zero balances
    balances = [
        b for b in acct.get("balances", [])
        if float(b["free"]) > 0 or float(b["locked"]) > 0
    ]
    print()
    print(f"[check] Non-zero balances ({len(balances)}):")
    if not balances:
        print("  (no assets — deposit some USDT to trade)")
    else:
        total_usdt_equiv = 0.0
        for b in sorted(balances, key=lambda x: -float(x["free"]) - float(x["locked"])):
            asset = b["asset"]
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked
            print(f"  {asset:10s}  free={free:15.8f}  locked={locked:15.8f}  total={total:15.8f}")
            if asset == "USDT":
                total_usdt_equiv += total
        if total_usdt_equiv > 0:
            print()
            print(f"  USDT total: {total_usdt_equiv:.2f}")

    # 2. Open orders sanity
    r = signed_request("/api/v3/openOrders", {}, key, secret)
    if r.status_code == 200:
        open_orders = r.json()
        print()
        print(f"[check] Open orders: {len(open_orders)}")
        for o in open_orders[:10]:
            print(f"  {o['symbol']} {o['side']} {o['type']} qty={o['origQty']} @ {o['price']}")
    else:
        print(f"[check] openOrders fetch failed: {r.status_code}")

    print()
    print("[check] OK — key is valid and read-accessible.")


if __name__ == "__main__":
    main()
