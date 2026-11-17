"""Part C Phase 2 kline layer (#229): daily 1m files from data.binance.vision.

Only the [t0-1 d, t0+5 d] daily files of each needed series are downloaded; each zip is
deleted after its rows inside span(t0) are kept. Prices stay strings here.
"""
import json
import time
import zipfile
from pathlib import Path

import nes_util as nu
import na_fetch
import na_sources
from nes_venues import kline_url

MAX_ZIP_BYTES = 20_000_000
ATTEMPTS = 3
RETRY_S = 5.0
_US_THRESHOLD = 10 ** 14         # open times from 2025 on are in microseconds


class DiskGuard(Exception):
    pass


class KlineError(Exception):
    pass


def kline_fetch(req):
    return na_fetch.fetch(req, timeout_s=30, max_bytes=MAX_ZIP_BYTES,
                          deadline=time.monotonic() + 120)


def parse_kline_csv(text):
    rows = {}
    for i, line in enumerate(text.splitlines()):
        fields = line.strip().split(",")
        if not fields or not fields[0]:
            continue
        try:
            open_ms = int(fields[0])
        except ValueError:
            if i == 0:
                continue                  # header
            raise
        if open_ms >= _US_THRESHOLD:
            open_ms //= 1000
        rows[open_ms] = fields[1:5]
    return rows


def download_dates(t0_ms):
    return [nu.utc_date(t0_ms + k * nu.DAY_MS) for k in range(-1, 6)]


def span(t0_ms):
    return (t0_ms - 15 * nu.MINUTE_MS,
            t0_ms + 5 * nu.MINUTE_MS + nu.DAY_MS + 72 * nu.HOUR_MS + nu.MINUTE_MS)


def _get(url, fetcher, sleep):
    last = None
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(RETRY_S)
        try:
            resp = fetcher(nu.Req("GET", url, None, {"User-Agent": na_sources.UA}))
        except na_fetch.FetchError as e:
            last = e
            continue
        if resp.status in (200, 404):
            return resp
        last = "HTTP %d" % resp.status
    raise KlineError("%s: %s after %d attempts" % (url, last, ATTEMPTS))


def fetch_series(market, symbol, t0_ms, fetcher, work_dir, disk_ok, sleep=time.sleep):
    lo, hi = span(t0_ms)
    rows, absent = {}, []
    work_dir = Path(work_dir)
    for date in download_dates(t0_ms):
        if not disk_ok():
            raise DiskGuard("less than the free-disk floor before %s %s %s" % (market, symbol, date))
        url = kline_url(market, symbol, date)
        resp = _get(url, fetcher, sleep)
        if resp.status == 404:
            absent.append(date)
            continue
        path = work_dir / ("%s-%s-%s.zip" % (market, symbol, date))
        nu.write_atomic(path, resp.body)
        try:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.endswith(".csv")]
                if len(names) != 1:
                    raise KlineError("%s: expected one csv, found %s" % (url, names))
                text = z.read(names[0]).decode("utf-8")
            parsed = parse_kline_csv(text)
        except (zipfile.BadZipFile, UnicodeDecodeError, ValueError) as e:
            raise KlineError("%s: unreadable file: %s" % (url, e)) from e
        finally:
            path.unlink(missing_ok=True)
        rows.update({k: v for k, v in parsed.items() if lo <= k < hi})
    return {"rows": dict(sorted(rows.items())), "absent_dates": absent}


def store_series(path, series):
    nu.write_atomic(path, nu.canonical_bytes(
        {"rows": {str(k): v for k, v in series["rows"].items()},
         "absent_dates": list(series["absent_dates"])}))


def load_series(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"rows": {int(k): v for k, v in d["rows"].items()}, "absent_dates": d["absent_dates"]}
