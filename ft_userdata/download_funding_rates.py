#!/usr/bin/env python3
"""
Download historical funding rate data from Binance futures API.

Funding rate is a perpetual futures mechanism: every 8 hours, longs pay shorts
(or vice versa) based on futures-vs-spot premium. Extreme funding values indicate
crowded positioning and often precede reversals.

Data stored as feather files in user_data/data/binance/funding/{PAIR}-funding.feather
with columns: [date, funding_rate].

Usage:
    python3 download_funding_rates.py
    python3 download_funding_rates.py --pairs BTC/USDT,ETH/USDT --start 20230101
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

USER_DATA = Path(__file__).parent / "user_data"
FUNDING_DIR = USER_DATA / "data" / "binance" / "funding"
FUNDING_DIR.mkdir(parents=True, exist_ok=True)

# Top pairs that have 1m data (from strategy_lab) — same universe
DEFAULT_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "TRX/USDT",
    "LTC/USDT", "NEAR/USDT", "SUI/USDT", "UNI/USDT", "BCH/USDT",
    "ARB/USDT", "HBAR/USDT", "ENA/USDT", "TAO/USDT", "ZEC/USDT",
]

BINANCE_FUTURES = "https://fapi.binance.com"


def log(msg):
    print(f"[funding] {msg}", flush=True)


def pair_to_symbol(pair: str) -> str:
    """BTC/USDT -> BTCUSDT for Binance API."""
    return pair.replace("/", "")


def fetch_funding_history(symbol: str, start_ms: int, end_ms: int) -> list:
    """
    Fetch funding rate history from Binance.

    API: /fapi/v1/fundingRate
    Rate-limited: 500 requests/5min, each returns up to 1000 records.
    Returns list of {symbol, fundingTime, fundingRate}.
    """
    url = f"{BINANCE_FUTURES}/fapi/v1/fundingRate"
    all_records = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        all_records.extend(batch)
        last_ts = batch[-1]["fundingTime"]
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        # Rate limit: 500req/5min = ~1.67 req/sec; be conservative
        time.sleep(0.2)

    return all_records


def save_pair(pair: str, records: list):
    """Merge new records with any existing feather, then atomically replace.

    - Merges with existing file so a partial API page doesn't truncate history.
    - Writes to a temp file in the same directory, then os.replace() for atomic swap.
      A live bot reading the feather mid-refresh sees either the old file or the new
      file, never a half-written blob.
    """
    if not records:
        return 0
    df_new = pd.DataFrame(records)
    df_new["fundingTime"] = pd.to_datetime(df_new["fundingTime"], unit="ms", utc=True)
    df_new["fundingRate"] = df_new["fundingRate"].astype(float)
    df_new = df_new.rename(columns={"fundingTime": "date", "fundingRate": "funding_rate"})
    df_new = df_new[["date", "funding_rate"]]

    pair_file = pair.replace("/", "_")
    out = FUNDING_DIR / f"{pair_file}-funding.feather"

    if out.exists():
        try:
            df_old = pd.read_feather(out)[["date", "funding_rate"]]
            df = pd.concat([df_old, df_new], ignore_index=True)
        except Exception as e:
            log(f"    merge read failed on {pair} ({e}); keeping new records only")
            df = df_new
    else:
        df = df_new

    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    tmp = out.with_suffix(out.suffix + f".tmp.{os.getpid()}")
    df.to_feather(tmp)
    os.replace(tmp, out)
    return len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS),
                        help="Comma-separated list of pairs")
    parser.add_argument("--start", default="20230101", help="YYYYMMDD")
    parser.add_argument("--end", default=None,
                        help="YYYYMMDD. Default: now (UTC), including current-day fundings")
    parser.add_argument("--incremental", action="store_true",
                        help="Only fetch from (most recent existing ts - 1d) forward per pair")
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start, "%Y%m%d").replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    if args.end:
        end_dt = datetime.strptime(args.end, "%Y%m%d").replace(tzinfo=timezone.utc)
        end_ms = int(end_dt.timestamp() * 1000)
    else:
        # Include current-day fundings (Binance publishes every 8h at 00/08/16 UTC)
        end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    log(f"Downloading {len(pairs)} pairs: start_ms={start_ms} end_ms={end_ms}")
    log(f"Output: {FUNDING_DIR}")

    total_records = 0
    for i, pair in enumerate(pairs, 1):
        symbol = pair_to_symbol(pair)
        pair_file = pair.replace("/", "_")
        existing = FUNDING_DIR / f"{pair_file}-funding.feather"

        pair_start_ms = start_ms
        if args.incremental and existing.exists():
            try:
                df_old = pd.read_feather(existing)
                if len(df_old):
                    # Rewind 24h to tolerate duplicates; save_pair dedupes.
                    last_ts = int(df_old["date"].iloc[-1].timestamp() * 1000)
                    pair_start_ms = max(start_ms, last_ts - 24 * 3600 * 1000)
            except Exception as e:
                log(f"    incremental read failed on {pair} ({e}); full fetch")

        log(f"  [{i}/{len(pairs)}] {pair} ({symbol}) start_ms={pair_start_ms}...")
        try:
            records = fetch_funding_history(symbol, pair_start_ms, end_ms)
            n = save_pair(pair, records)
            total_records += n
            log(f"    {n} funding periods total after merge")
        except Exception as e:
            log(f"    ERROR: {e}")

    log(f"Done. Total: {total_records} funding records across {len(pairs)} pairs.")


if __name__ == "__main__":
    main()
