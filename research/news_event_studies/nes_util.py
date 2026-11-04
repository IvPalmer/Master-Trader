"""Shared constants and helpers for the Part C event studies (#229).

Importing this module puts `research/news_archive` on sys.path, so `na_fetch`,
`na_sources` and `na_store` (Part A) are importable by every nes_ module.
"""
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
ARCHIVE_DIR = HERE.parent / "news_archive"
ARCHIVE_LIMITER_STATE = ARCHIVE_DIR / "data" / "binance_cms_state.json"

if str(ARCHIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_DIR))

import na_store  # noqa: E402

WINDOW_START_MS = 1672531200000   # 2023-01-01T00:00Z, inclusive
WINDOW_END_MS = 1793491200000     # 2026-11-01T00:00Z, exclusive
MINUTE_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
MIN_FREE_BYTES = 15 * 1024 ** 3

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Req:
    """A request spec accepted by na_fetch.fetch."""
    method: str
    url: str
    body: "bytes | None" = None
    headers: dict = field(default_factory=dict)


def canonical_bytes(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            .encode("utf-8") + b"\n")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dt(ms):
    return _EPOCH + timedelta(milliseconds=int(ms))


def iso_ms(ms):
    return na_store.iso(_dt(ms))


def ms_from_iso(s):
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("timestamp without a zone: %r" % s)
    return (dt - _EPOCH) // timedelta(milliseconds=1)


def utc_date(ms):
    return _dt(ms).strftime("%Y-%m-%d")


def disk_ok(path):
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free >= MIN_FREE_BYTES


def write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
    tmp.replace(path)
