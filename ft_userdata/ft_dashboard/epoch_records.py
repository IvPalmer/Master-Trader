"""Immutable records of ended bot epochs (#277). Pure helpers: no app import.

A bot demoted, retired or deleted no longer serves its live trades: Freqtrade
opens another SQLite per mode. Each ended epoch is archived once, by
deploy/vps/archive_bot_epoch.py, as one JSON file in ``epoch-records/`` on the
``ft_user_data`` volume. The dashboard only reads them and never recomputes one.

A trade is identified by ``(pair, open_timestamp_ms, trade_id)``. A record owns
the closed trades of its half-open window ``[start_ms, end_ms)``; no trade may
belong to two records.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

SCHEMA = 1
CALC_VERSION = 1
# Never a running bot key: those contain no dot (killers-ft vs killers-ft.live-r5).
RECORD_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9.-]*")
_REQUIRED = {
    "record_id": str, "bot_key": str, "mode": str, "venue": str, "account_group": str,
    "start_ms": int, "end_ms": int, "starting_capital": (int, float), "reason": str,
    "issue": (int, str), "source_backup": str, "source_sha256": str, "totals": dict,
    "calc_version": int, "trades": list, "snapshot": dict,
}


class Records(NamedTuple):
    by_id: dict[str, dict]
    owned: frozenset
    errors: list[str]


_cache: dict[tuple, tuple[tuple, Records]] = {}


def trade_identity(trade: dict) -> tuple[str, int, int] | None:
    """(pair, open_timestamp_ms, trade_id), or None when the trade lacks one."""
    try:
        return (str(trade["pair"]), int(trade["open_timestamp"]), int(trade["trade_id"]))
    except (KeyError, TypeError, ValueError):
        return None


def sqlite_ts_ms(value: str | None) -> int | None:
    """A Freqtrade SQLite date (naive UTC) in ms, computed as Freqtrade does."""
    if not value:
        return None
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _finite(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid record JSON")


def validate_record(record: Any, record_id: str | None = None) -> list:
    """The record's trade identities; raises ValueError when it is malformed."""
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError(f"schema is not {SCHEMA}")
    for field, kind in _REQUIRED.items():
        if not isinstance(record.get(field), kind) or isinstance(record.get(field), bool):
            raise ValueError(f"{field} missing or invalid")
    rid = record["record_id"]
    if not RECORD_ID_RE.fullmatch(rid) or (record_id is not None and rid != record_id):
        raise ValueError("record_id does not match the file name or format")
    if record["mode"] not in {"live", "paper"} or record["start_ms"] >= record["end_ms"]:
        raise ValueError("invalid mode or window")
    snap = record["snapshot"]
    if (snap.get("key") != rid or snap.get("bot_key") != record["bot_key"]
            or snap.get("stopped") is not True or snap.get("open_trades")
            or snap.get("dry_run") is not (record["mode"] == "paper")):
        raise ValueError("snapshot does not describe this stopped epoch")
    identities = []
    for trade in record["trades"]:
        identity = trade_identity(trade) if isinstance(trade, dict) else None
        if identity is None or trade.get("is_open") is not False:
            raise ValueError("trade without identity or still open")
        close = trade.get("close_timestamp")
        if not isinstance(close, int) or not record["start_ms"] <= close < record["end_ms"]:
            raise ValueError(f"trade {identity[2]} closed outside the record window")
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate trade in record")
    _validate_measurements(record)
    return identities


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_measurements(record: dict) -> None:
    """The figures the dashboard shows must exist and agree with the ledger.

    Ownership removes these trades from the running bot, so a record whose
    measurements are missing or disagree would silently drop them.
    """
    snap, totals, trades = record["snapshot"], record["totals"], record["trades"]
    pnl, stats, events = snap.get("pnl"), snap.get("stats"), snap.get("realized_events")
    if not isinstance(pnl, dict) or not all(_number(pnl.get(k)) for k in ("closed", "closed_trades")):
        raise ValueError("snapshot P&L missing or invalid")
    counts = ("closed_trade_count", "winning_trades", "losing_trades")
    if (not isinstance(stats, dict) or not all(isinstance(stats.get(k), int) for k in counts)
            or not all(_number(stats.get(k)) for k in ("gross_profit", "gross_loss", "max_drawdown"))):
        raise ValueError("snapshot statistics missing or invalid")
    if not isinstance(events, list) or not all(
            isinstance(e, (list, tuple)) and len(e) == 2 and _number(e[1]) for e in events):
        raise ValueError("snapshot realized events missing or invalid")
    profits = [t.get("profit_abs") for t in trades]
    raws = [t.get("freqtrade_profit_abs", t.get("profit_abs")) for t in trades]
    if not all(_number(p) for p in profits + raws):
        raise ValueError("trade P&L missing or invalid")
    corrected, raw, tolerance = sum(profits), sum(raws), 1e-6 * max(1, len(trades))
    if not (stats["closed_trade_count"] == totals.get("closed_trades") == len(trades)
            and stats["winning_trades"] == sum(p > 0 for p in profits)
            and stats["losing_trades"] == sum(p < 0 for p in profits)):
        raise ValueError("trade counts disagree with the ledger")
    if not (_number(totals.get("raw_profit_abs")) and _number(totals.get("corrected_profit_abs"))
            and abs(totals["raw_profit_abs"] - raw) <= tolerance
            and abs(totals["corrected_profit_abs"] - corrected) <= tolerance
            and abs(pnl["closed_trades"] - corrected) <= 0.005 + tolerance  # rounded to cents
            and abs(pnl["closed"] - sum(e[1] for e in events)) <= 0.005 + tolerance):
        raise ValueError("P&L totals disagree with the ledger")
    gross_profit = sum(p for p in profits if p > 0)
    gross_loss = -sum(p for p in profits if p < 0)
    if (abs(stats["gross_profit"] - gross_profit) > 1e-4 + tolerance  # stored to 4 decimals
            or abs(stats["gross_loss"] - gross_loss) > 1e-4 + tolerance):
        raise ValueError("gross profit or loss disagrees with the ledger")
    # Realized events are the exit fills of these trades inside the window. A
    # trade opened before the window may have exits before it, which the epoch
    # does not count; otherwise the fills add up to the trades' P&L.
    if not all(_number(e[0]) and record["start_ms"] <= e[0] < record["end_ms"] for e in events):
        raise ValueError("realized event outside the record window")
    if (all(t["open_timestamp"] >= record["start_ms"] for t in trades)
            and abs(sum(e[1] for e in events) - corrected) > 0.005 + tolerance):
        raise ValueError("realized events disagree with the ledger")


def load_records(directory: Path, reserved: frozenset | set = frozenset()) -> Records:
    """Valid records in ``directory``; never raises, never counts a record partially.

    A malformed record, one whose id is a running bot's key, or one claiming a
    trade an earlier record (by record_id) owns is rejected and reported.
    Cached by file name and mtime.
    """
    directory = Path(directory)
    try:
        paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
        signature = tuple((p.name, p.stat().st_mtime_ns) for p in paths)
    except OSError as exc:
        return Records({}, frozenset(), [f"Epoch records unreadable: {exc}"])
    key = (str(directory), frozenset(reserved))
    cached = _cache.get(key)
    if cached and cached[0] == signature:
        return cached[1]
    by_id: dict[str, dict] = {}
    owned: set = set()
    errors: list[str] = []
    for path in paths:  # sorted by name, which is the record_id: the first owner wins
        try:
            record = json.loads(path.read_text(), parse_float=_finite,
                                parse_constant=_reject_constant)
            identities = validate_record(record, path.stem)
            if path.stem in reserved:
                raise ValueError("record id is a running bot's key")
            if owned.intersection(identities):
                raise ValueError("a trade is already owned by another record")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            errors.append(f"Epoch record {path.name} rejected: {exc}")
            continue
        by_id[path.stem] = record
        owned.update(identities)
    result = Records(by_id, frozenset(owned), errors)
    _cache[key] = (signature, result)
    return result


def coverage(directory: Path, owned: set | frozenset, closed_before_ms: int | None = None) -> dict:
    """Closed trades in each live DB that no record and no running epoch owns.

    A DB that cannot be read is reported unverified, never as covered. Trades
    closed at or after ``closed_before_ms`` are not classified yet: the running
    ledgers they would belong to were read before them.
    """
    uncovered: list[dict] = []
    unverified: list[dict] = []
    for path in sorted(Path(directory).glob("tradesv3.live.*.sqlite")):
        try:
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)
            try:
                rows = conn.execute(
                    "SELECT id, pair, open_date, close_date FROM trades WHERE is_open = 0"
                ).fetchall()
            finally:
                conn.close()
            missing = []
            for trade_id, pair, open_date, close_date in rows:
                close_ms = sqlite_ts_ms(close_date)
                if closed_before_ms is not None and (close_ms or 0) >= closed_before_ms:
                    continue
                if (str(pair), sqlite_ts_ms(open_date), int(trade_id)) not in owned:
                    missing.append(int(trade_id))
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            unverified.append({"db": path.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if missing:
            uncovered.append({"db": path.name, "count": len(missing), "trade_ids": sorted(missing)[:20]})
    return {"uncovered": uncovered, "unverified": unverified}
