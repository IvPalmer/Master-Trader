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
import json
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


# Sanity bound on a single funding rate. It is NOT the exchange cap: Binance
# sets the cap per symbol and changes it over time. /fapi/v1/fundingInfo on
# 2026-10-02 listed 804 symbols with caps from ±0.30% (BTC, ETH) to ±3%, and
# ZEC, HBAR, NEAR, ARB, ENA and TAO in DEFAULT_PAIRS are capped at ±2%. Real
# settlements beyond the old ±0.75% bound exist in our own feathers (ZEC
# -1.64% on 2025-04-07, SOL -0.93% on 2023-01-04).
#
# A rate beyond ±3% exceeds every cap Binance lists, so it is treated as
# malformed data (decimal shift, bad payload) and quarantined for that ROW only.
# The old bound rejected the whole batch, and because --incremental rewinds 24h
# the rejected row sat in every later window: one value froze the pair's file
# for good and FundingFadeV1's staleness guard then blocked its entries (#113).
FUNDING_RATE_SANITY_BOUND = 0.03
# Rows listed per QUARANTINE log line; the count always covers all of them.
_QUARANTINE_LOG_ROWS = 5


def _event_label(date) -> str:
    return date.strftime("%Y-%m-%dT%H:%MZ") if pd.notna(date) else "?"


def _quarantine_bad_rates(pair: str, df_new: pd.DataFrame, raw_rates: pd.Series,
                          quarantined: list | None = None) -> pd.DataFrame:
    """Drop rows whose rate is missing, non-numeric, non-finite or beyond the
    sanity bound, logging each as QUARANTINE. The remaining rows are returned
    so the rest of the batch still merges and the file keeps advancing.
    Dropped rows are appended to `quarantined` as (pair, event, raw value)."""
    ok = df_new["funding_rate"].abs() <= FUNDING_RATE_SANITY_BOUND  # NaN/inf -> False
    if ok.all():
        return df_new
    bad = df_new.loc[~ok]
    if quarantined is not None:
        quarantined.extend(
            (pair, _event_label(d), repr(raw_rates.loc[i])) for i, d in bad["date"].items()
        )
    shown = ", ".join(
        f"{_event_label(d)}={raw_rates.loc[i]!r}"
        for i, d in bad["date"].head(_QUARANTINE_LOG_ROWS).items()
    )
    more = f" (+{len(bad) - _QUARANTINE_LOG_ROWS} more)" if len(bad) > _QUARANTINE_LOG_ROWS else ""
    log(
        f"    QUARANTINE {pair}: dropped {len(bad)} of {len(df_new)} row(s) with funding_rate "
        f"missing, non-numeric or beyond ±{FUNDING_RATE_SANITY_BOUND}: {shown}{more}"
    )
    return df_new.loc[ok]


def save_pair(pair: str, records: list, quarantined: list | None = None):
    """Merge new records with any existing feather, then atomically replace.

    - Validates each funding rate; a bad row is quarantined (dropped, logged and
      appended to `quarantined` for the run's alert) and the rest of the batch
      is still saved, so one value never freezes the file.
    - Merges with existing file so a partial API page doesn't truncate history.
    - On corrupt-feather read, ABORTS the save (does NOT fall back to new-only)
      because that path silently truncates the historical series.
    - Writes to a temp file in the same directory, then os.replace() for atomic swap.
    """
    if not records:
        return 0
    df_new = pd.DataFrame(records)
    df_new["fundingTime"] = pd.to_datetime(df_new["fundingTime"], unit="ms", utc=True)
    raw_rates = df_new["fundingRate"]
    # coerce: a malformed value becomes NaN and is quarantined with its row,
    # instead of raising and dropping the whole batch.
    df_new["fundingRate"] = pd.to_numeric(raw_rates, errors="coerce").astype(float)
    df_new = df_new.rename(columns={"fundingTime": "date", "fundingRate": "funding_rate"})
    df_new = df_new[["date", "funding_rate"]]

    df_new = _quarantine_bad_rates(pair, df_new, raw_rates, quarantined)
    if df_new.empty:
        return 0

    pair_file = pair.replace("/", "_")
    out = FUNDING_DIR / f"{pair_file}-funding.feather"

    if out.exists():
        try:
            df_old = pd.read_feather(out)[["date", "funding_rate"]]
        except Exception as e:
            log(f"    ABORT {pair}: existing feather unreadable ({e}); refusing to truncate history")
            sentinel = out.with_suffix(out.suffix + ".CORRUPT")
            try:
                os.replace(out, sentinel)
                log(f"    moved corrupt feather to {sentinel.name}; manual recovery required")
            except Exception as move_err:
                log(f"    sentinel rename also failed: {move_err}")
            return 0
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new

    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    tmp = out.with_suffix(out.suffix + f".tmp.{os.getpid()}")
    df.to_feather(tmp)
    os.replace(tmp, out)
    return len(df)


# Telegram alert for quarantined rows, through trade-webhook's /test/notify
# (the path killers-receiver uses). FUNDING_NOTIFY_URL unset = no alert.
# TRADE_WEBHOOK_NOTIFY_TOKEN is sent as X-Notify-Token only when set (#59).
#
# --incremental rewinds 24h, so a quarantined row is re-fetched by every run for
# a day. Rows already alerted are remembered in this file (pruned after a week)
# so each bad row alerts once, not hourly; a failed delivery is not recorded, so
# the next run retries it.
_ALERTED_FILE = ".quarantine-alerted.json"
_ALERTED_KEEP_S = 7 * 24 * 3600
_ALERT_MAX_ROWS = 20


def notify_quarantine(quarantined: list) -> None:
    """Send one best-effort alert for this run's newly quarantined rows. Never raises."""
    url = os.environ.get("FUNDING_NOTIFY_URL", "").strip()
    if not quarantined or not url:
        return
    state_path = FUNDING_DIR / _ALERTED_FILE
    try:
        alerted = json.loads(state_path.read_text())
        if not isinstance(alerted, dict):
            alerted = {}
    except FileNotFoundError:
        alerted = {}
    except Exception as e:
        log(f"    quarantine alert state unreadable ({e}); alerting every row")
        alerted = {}

    new = [row for row in quarantined if "|".join(row) not in alerted]
    if not new:
        return
    lines = [f"  {pair} {event} = {raw}" for pair, event, raw in new[:_ALERT_MAX_ROWS]]
    if len(new) > _ALERT_MAX_ROWS:
        lines.append(f"  (+{len(new) - _ALERT_MAX_ROWS} more, see ft-funding-refresh logs)")
    text = "\n".join([
        f"⚠ FUNDING QUARANTINE [ft-funding-refresh] {len(new)} row(s)",
        f"funding_rate missing, non-numeric or beyond ±{FUNDING_RATE_SANITY_BOUND}; "
        "dropped, the rest of each file kept updating:",
        *lines,
        "  → FundingFadeV1 sees a missing funding event for these pairs",
    ])
    token = os.environ.get("TRADE_WEBHOOK_NOTIFY_TOKEN", "").strip()
    headers = {"X-Notify-Token": token} if token else None
    try:
        resp = requests.post(url, json={"text": text}, headers=headers, timeout=10)
    except Exception as e:
        log(f"    quarantine alert not sent ({type(e).__name__}); will retry next run")
        return
    if not 200 <= resp.status_code < 300:
        hint = (": TRADE_WEBHOOK_NOTIFY_TOKEN missing or different from trade-webhook's"
                if resp.status_code == 401 else "")
        log(f"    quarantine alert rejected (HTTP {resp.status_code}){hint}; will retry next run")
        return
    log(f"    quarantine alert sent for {len(new)} row(s)")

    now = time.time()
    alerted = {k: t for k, t in alerted.items()
               if isinstance(t, (int, float)) and now - t < _ALERTED_KEEP_S}
    alerted.update({"|".join(row): now for row in new})
    tmp = state_path.with_name(f"{state_path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(alerted))
        os.replace(tmp, state_path)
    except Exception as e:
        log(f"    quarantine alert state not saved ({e}); these rows may alert again")


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
    quarantined = []
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
            n = save_pair(pair, records, quarantined)
            total_records += n
            log(f"    {n} funding periods total after merge")
        except Exception as e:
            log(f"    ERROR: {e}")

    try:
        notify_quarantine(quarantined)
    except Exception as e:  # the alert must never fail the refresh
        log(f"    quarantine alert failed: {e}")

    log(f"Done. Total: {total_records} funding records across {len(pairs)} pairs.")


if __name__ == "__main__":
    main()
