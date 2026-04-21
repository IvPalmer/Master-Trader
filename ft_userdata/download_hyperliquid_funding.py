#!/usr/bin/env python3
"""
Download historical funding rate data from Hyperliquid perpetual exchange.

Hyperliquid is a decentralized perpetual exchange. Funding settles HOURLY on
Hyperliquid vs 8-HOURLY on Binance — an important cadence mismatch for any
cross-venue spread analysis. The downstream script
`analysis/cross_venue_funding_spread.py` resamples both to a common cadence.

API docs: POST https://api.hyperliquid.xyz/info with body
  { "type": "fundingHistory", "coin": "<symbol>", "startTime": <ms>, "endTime": <ms> }
Response: list of { coin, fundingRate, premium, time }. Each call returns up to
500 records, so we paginate by updating startTime.

Output: feather files at user_data/data/hyperliquid/funding/{PAIR}-funding.feather
with columns [date, funding_rate] matching the Binance schema.

Usage:
    python3 download_hyperliquid_funding.py
    python3 download_hyperliquid_funding.py --pairs BTC/USDT,ETH/USDT
"""
import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

USER_DATA = Path(__file__).parent / "user_data"
BINANCE_FUNDING_DIR = USER_DATA / "data" / "binance" / "funding"
HL_FUNDING_DIR = USER_DATA / "data" / "hyperliquid" / "funding"
HL_FUNDING_DIR.mkdir(parents=True, exist_ok=True)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

# Conservative rate limit: Hyperliquid publicly rate-limits to ~1200 weight/min
# per IP, fundingHistory weight unknown — be cautious.
REQ_SLEEP = 1.0  # seconds between requests

# Hyperliquid uses short coin symbols (e.g. "BTC" not "BTCUSDT").
# Some pairs on Binance don't exist on HL (meme coins, low-cap alts).
# Build the HL symbol from the pair base.


def log(msg):
    print(f"[hl-funding] {msg}", flush=True)


def pair_to_hl_symbol(pair: str) -> str:
    """BTC/USDT -> BTC for Hyperliquid."""
    return pair.split("/")[0]


def discover_binance_pairs() -> list:
    """Return the list of pairs we already have Binance funding data for."""
    pairs = []
    for f in sorted(BINANCE_FUNDING_DIR.glob("*-funding.feather")):
        pair_file = f.stem.replace("-funding", "")
        pairs.append(pair_file.replace("_", "/"))
    return pairs


def fetch_hl_meta() -> set:
    """Return the set of perpetual coin symbols listed on Hyperliquid."""
    r = requests.post(HL_INFO_URL, json={"type": "meta"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    names = {asset["name"] for asset in data.get("universe", [])}
    return names


def fetch_funding_history(coin: str, start_ms: int, end_ms: int) -> list:
    """
    Page through Hyperliquid fundingHistory. Each call returns up to 500
    records. Paginate forward by setting startTime to last_record_time + 1.
    """
    all_records = []
    cursor = start_ms
    last_len = -1

    while cursor < end_ms:
        body = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": cursor,
            "endTime": end_ms,
        }
        r = requests.post(HL_INFO_URL, json=body, timeout=30)
        if r.status_code == 429:
            log(f"    rate limited, sleeping 10s")
            time.sleep(10)
            continue
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        all_records.extend(batch)
        last_ts = batch[-1]["time"]
        if last_ts <= cursor or len(batch) == last_len == 0:
            break
        cursor = last_ts + 1
        last_len = len(batch)
        time.sleep(REQ_SLEEP)

    # Dedup by time (pagination overlap guard)
    seen = set()
    uniq = []
    for rec in all_records:
        if rec["time"] in seen:
            continue
        seen.add(rec["time"])
        uniq.append(rec)
    return uniq


def save_pair(pair: str, records: list) -> int:
    if not records:
        return 0
    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.rename(columns={"time": "date", "fundingRate": "funding_rate"})
    df = df[["date", "funding_rate"]].sort_values("date").drop_duplicates("date")

    pair_file = pair.replace("/", "_")
    out = HL_FUNDING_DIR / f"{pair_file}-funding.feather"
    df.reset_index(drop=True).to_feather(out)
    return len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pairs", default=None,
        help="Comma-separated pairs. Default: all pairs with Binance funding data.",
    )
    parser.add_argument("--start", default="20230101", help="YYYYMMDD")
    parser.add_argument(
        "--end", default=datetime.utcnow().strftime("%Y%m%d"), help="YYYYMMDD",
    )
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start, "%Y%m%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(args.end, "%Y%m%d").replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    if args.pairs:
        pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    else:
        pairs = discover_binance_pairs()

    log(f"Fetching Hyperliquid meta...")
    hl_universe = fetch_hl_meta()
    log(f"  {len(hl_universe)} perps listed on Hyperliquid")

    matched, skipped = [], []
    for p in pairs:
        if pair_to_hl_symbol(p) in hl_universe:
            matched.append(p)
        else:
            skipped.append(p)
    log(f"  matched {len(matched)} / {len(pairs)} Binance pairs on HL")
    if skipped:
        log(f"  skipped (not on HL): {', '.join(skipped[:10])}"
            f"{'...' if len(skipped) > 10 else ''}")

    log(f"Downloading {args.start} → {args.end} to {HL_FUNDING_DIR}")

    total_records = 0
    for i, pair in enumerate(matched, 1):
        symbol = pair_to_hl_symbol(pair)
        log(f"  [{i}/{len(matched)}] {pair} ({symbol})...")
        try:
            records = fetch_funding_history(symbol, start_ms, end_ms)
            n = save_pair(pair, records)
            total_records += n
            first = records[0]["time"] if records else None
            last = records[-1]["time"] if records else None
            if first and last:
                first_dt = datetime.fromtimestamp(first / 1000, tz=timezone.utc)
                last_dt = datetime.fromtimestamp(last / 1000, tz=timezone.utc)
                log(f"    {n} records, {first_dt.date()} → {last_dt.date()}")
            else:
                log(f"    0 records")
        except Exception as e:
            log(f"    ERROR: {e}")

    log(f"Done. Total: {total_records} HL funding records, "
        f"{len(matched)} pairs, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
