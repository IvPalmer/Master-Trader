"""killers-receiver — Binance-Killers-VIP signal copy-trader executor.

Listens for classified-message events from the killers_bot observer,
translates them to Freqtrade Futures REST calls against the
ft-killers-scalp dry-run bot.

Pipeline:
  observer.py → POST /event → this receiver →
    open  → POST /forceenter  (BTC/USDT:USDT, market order, $20 stake, 5x lev)
    close → POST /forceexit   (look up trade by signal_id+symbol)
    move_sl / chat / increase → log only (Phase 2)

Position graph: SQLite table mapping (signal_id, symbol) → freqtrade
trade_id so close events can find the right position to exit.

Env vars:
  KILLERS_FT_BASE_URL       Freqtrade REST base (http://ft-killers-scalp:8080)
  KILLERS_FT_USERNAME       REST basic-auth
  KILLERS_FT_PASSWORD       REST basic-auth
  KILLERS_DB                SQLite path for position graph
  KILLERS_STAKE_USD         per-trade stake (default 20 — gives ~10 concurrent on $200)
  KILLERS_LEVERAGE          default leverage (default 5)
  KILLERS_MAX_OPEN          guardrail (default 10, matches max_open_trades)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# aiohttp imported lazily inside the methods that use it so the module can
# load in test environments without aiohttp installed (the pure-helper tests
# import this file). Functions that need it do `import aiohttp` locally.
try:
    import aiohttp  # noqa: F401 — kept for typing/runtime parity; lazy import inside fns
except ImportError:
    aiohttp = None  # type: ignore
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("killers-receiver")


# ── Config ─────────────────────────────────────────────────────────────────


class Config:
    def __init__(self):
        self.ft_base = os.environ.get(
            "KILLERS_FT_BASE_URL", "http://ft-killers-scalp:8080"
        )
        self.ft_user = os.environ.get("KILLERS_FT_USERNAME", "freqtrader")
        self.ft_pass = os.environ.get("KILLERS_FT_PASSWORD", "mastertrader")
        self.db_path = os.environ.get(
            "KILLERS_DB", "/var/lib/killers/receiver.sqlite"
        )
        self.stake_usd = float(os.environ.get("KILLERS_STAKE_USD", "20"))
        self.leverage = float(os.environ.get("KILLERS_LEVERAGE", "5"))
        self.max_open = int(os.environ.get("KILLERS_MAX_OPEN", "10"))
        # Where to ping for human-readable Telegram alerts. trade-webhook
        # already proxies to @elder_brain_bot; reusing its /test/notify keeps
        # one Telegram code path for the whole fleet. Empty string disables.
        self.notify_url = os.environ.get(
            "KILLERS_NOTIFY_URL", "http://trade-webhook:8088/test/notify"
        )
        # Max acceptable slippage from the signal's entry boundary, as
        # percent. LONG: skip if mark > entry_hi * (1 + pct/100).
        # SHORT: skip if mark < entry_lo * (1 - pct/100).
        # Set to 0 to disable. Default 3% — matches the HYPE #2144 case
        # study where we filled +6.78% above entry_hi and lost 7%.
        self.max_entry_slippage_pct = float(os.environ.get(
            "KILLERS_MAX_ENTRY_SLIPPAGE_PCT", "3.0",
        ))
        # Phase 2: place LIMIT exit orders at each TP at open-time instead
        # of waiting for the channel to announce target hits. Default ON
        # because the Killers signaler explicitly publishes the full TP
        # ladder at open and never closes at non-TP prices manually —
        # channel close_partial msgs are post-hoc announcements of fills
        # the exchange already captured.
        self.active_tp_limits = (os.environ.get(
            "KILLERS_ACTIVE_TP_LIMITS", "true",
        ).lower() in ("true", "1", "yes"))
        # Reconciler tick interval for target_orders state transitions.
        self.target_reconcile_sec = int(os.environ.get(
            "KILLERS_TARGET_RECONCILE_SEC", "20",
        ))


# ── Symbol mapping ─────────────────────────────────────────────────────────

# Channel uses bare symbols (BTC, ETH). Freqtrade futures uses BTC/USDT:USDT.
# Aliases are reserved for non-1:1 mappings only — leave plain SYM → SYM as
# identity (no entry). 1000-prefixed alts on Binance Futures are the actual
# perp pair, so we map small-denom names to them.
SYMBOL_ALIASES = {
    "PEPE":   "1000PEPE",
    "SHIB":   "1000SHIB",
    "FLOKI":  "1000FLOKI",
    "BONK":   "1000BONK",
    "GOLD":   "XAUT",        # channel typo correction
}


def to_freqtrade_pair(symbol: str) -> Optional[str]:
    """`BTC` → `BTC/USDT:USDT`. None for unmappable."""
    if not symbol:
        return None
    sym = SYMBOL_ALIASES.get(symbol.upper(), symbol.upper())
    return f"{sym}/USDT:USDT"


def to_binance_perp_symbol(symbol: str) -> Optional[str]:
    """`BTC` → `BTCUSDT` (Binance USDT-M perp futures symbol).

    Same aliasing as `to_freqtrade_pair` so 1000PEPE etc. map correctly.
    Returns None if symbol is missing or empty.
    """
    if not symbol:
        return None
    sym = SYMBOL_ALIASES.get(symbol.upper(), symbol.upper())
    return f"{sym}USDT"


# ── Target parser ──────────────────────────────────────────────────────────

# Killers signals carry an explicit target ladder in the raw text:
#   "TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300"
# The classifier only captures a single `tp` field. For the upfront
# already-past-targets guard we parse the full ladder directly from the
# raw text. Robust to: extra whitespace, mixed dash styles (- / – / —),
# scientific notation, lone "Targets:" lines with no values (returns []).
import re as _re

_TARGETS_LINE_RE = _re.compile(
    r"^[^\S\r\n]*TARGETS?[^\S\r\n]*:[^\S\r\n]*(.+)$",
    _re.IGNORECASE | _re.MULTILINE,
)
_NUMBER_RE = _re.compile(r"\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
# Note: unsigned. The channel uses `-` as a separator and sometimes drops
# the space ("68.00 -72.00"). Matching a signed number there would steal
# the dash and parse `-72.00`, which is then dropped by the positivity
# filter, silently losing that target. Targets in real signals are
# always positive, so we match unsigned and skip the ambiguity.


def extract_targets_from_text(text: Optional[str]) -> list[float]:
    """Pull the ordered target ladder from a Killers signal body.

    Returns a list of positive floats in the order they appear, or [] if
    no targets line is present. Channel format examples:
      "TARGETS: 59.50 - 62.00 - 65.00 - 68.00 - 72.00 - 77.00 - 83.00 - 90.00"
      "Targets: 0.0945 - 0.0990 - 0.1050"
    The function ignores any non-positive matches (defensive against the
    SL line or noisy parser output) and silently skips unparseable tokens.
    """
    if not text or not isinstance(text, str):
        return []
    m = _TARGETS_LINE_RE.search(text)
    if not m:
        return []
    tail = m.group(1)
    raw_nums = _NUMBER_RE.findall(tail)
    out: list[float] = []
    for r in raw_nums:
        try:
            v = float(r.replace(",", "."))
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out


def filter_remaining_targets(
    targets: list[float], current_price: float, direction: str,
) -> list[float]:
    """Return targets still 'ahead' of current price for the given direction.

    LONG  → keep targets > current_price (sorted ascending: nearest first).
    SHORT → keep targets < current_price (sorted descending: nearest first).

    Empty input or unknown direction → []. Caller MUST treat [] as 'all
    targets already crossed' (skip the open).
    """
    if not targets or not isinstance(current_price, (int, float)) or current_price <= 0:
        return []
    direction_lc = (direction or "").lower()
    if direction_lc == "long":
        remaining = sorted(t for t in targets if t > current_price)
    elif direction_lc == "short":
        remaining = sorted((t for t in targets if t < current_price), reverse=True)
    else:
        return []
    return remaining


async def get_binance_mark_price(symbol: str,
                                  session=None) -> Optional[float]:
    """Fetch Binance USDT-M futures mark price for a perp symbol.

    Returns None on any failure (HTTP error, non-2xx, parse error, network).
    Caller MUST treat None as 'cannot verify price' and fail closed (skip
    the open) to avoid entering after all targets are already crossed.

    If `session` is provided, reuses it (persistent connection pool, ~10-100ms
    saved on warm path). If None, creates a one-shot session.
    """
    binance_sym = to_binance_perp_symbol(symbol)
    if not binance_sym:
        return None
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    timeout = aiohttp.ClientTimeout(total=3)
    try:
        if session is not None:
            ctx = session.get(url, params={"symbol": binance_sym}, timeout=timeout)
            async with ctx as r:
                return await _parse_binance_mark(r, binance_sym)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url, params={"symbol": binance_sym}) as r:
                return await _parse_binance_mark(r, binance_sym)
    except Exception as e:
        logger.warning("binance mark price fetch error %s: %s", binance_sym, e)
        return None


async def _parse_binance_mark(r, binance_sym: str) -> Optional[float]:
    if r.status != 200:
        logger.warning("binance mark price HTTP %d for %s", r.status, binance_sym)
        return None
    data = await r.json()
    price = data.get("markPrice")
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    import math
    if not math.isfinite(p) or p <= 0:
        return None
    return p


# ── Position graph (SQLite) ─────────────────────────────────────────────────

POSITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    pos_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       INTEGER,
    symbol          TEXT NOT NULL,
    pair            TEXT NOT NULL,
    direction       TEXT NOT NULL,
    state           TEXT NOT NULL,           -- requested / open / closed / failed
    open_msg_id     INTEGER NOT NULL UNIQUE, -- idempotency: same channel msg = same trade attempt
    open_date       TEXT NOT NULL,
    stake_usd       REAL,
    leverage        REAL,
    sl_distance_pct REAL,
    ft_trade_id     INTEGER,
    close_msg_id    INTEGER,
    close_date      TEXT,
    close_reason    TEXT,
    last_event_at   TEXT,
    pct_open        REAL NOT NULL DEFAULT 100,  -- 100=full, 50=half closed, 0=fully closed
    targets_remaining TEXT                       -- JSON array of remaining TPs (ahead of entry price)
);
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pos_id      INTEGER REFERENCES positions(pos_id),
    msg_id      INTEGER NOT NULL,
    event_at    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT,
    response    TEXT,
    UNIQUE(pos_id, msg_id, kind)  -- idempotency: same (position, msg, kind) cannot re-fire
);
CREATE INDEX IF NOT EXISTS idx_pos_signal_symbol ON positions(signal_id, symbol);
CREATE INDEX IF NOT EXISTS idx_pos_state ON positions(state);

CREATE TABLE IF NOT EXISTS target_orders (
    -- Phase 2: active limit-order placement at each signal TP.
    -- Set-and-forget on open: parse TARGETS line → place LIMIT exit at
    -- each TP via /forceexit ordertype=limit → exchange fills the TPs
    -- as price walks. Channel "Target N hit" messages become dedupe
    -- audit only (the exchange already executed it).
    target_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    pos_id      INTEGER NOT NULL REFERENCES positions(pos_id),
    idx         INTEGER NOT NULL,           -- 0-based index in the signal's target ladder
    price       REAL NOT NULL,              -- TP price (limit price)
    amount      REAL NOT NULL,              -- base-currency slice assigned to this TP
    state       TEXT NOT NULL DEFAULT 'pending',
                                            -- pending: not yet posted to FT
                                            -- active: limit order open on FT
                                            -- filled: exchange filled the limit
                                            -- cancelled: explicitly cancelled
                                            -- rejected: FT rejected (precision, min-notional, etc)
                                            -- skipped: filtered out before placement
    ft_order_id TEXT,                       -- exchange order id (from FT trade.orders[])
    placed_at   TEXT,
    filled_at   TEXT,
    last_check_at TEXT,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_target_orders_pos ON target_orders(pos_id, state);
CREATE INDEX IF NOT EXISTS idx_target_orders_state ON target_orders(state);
"""

# Default partial-close pct when the signal doesn't specify ("TP1 hit", "took
# profit on half", etc). 50% mirrors the most common Killers channel pattern
# (close half on first TP, runner stays). Tune via env if it doesn't match.
DEFAULT_PARTIAL_PCT = 50.0

# Residual threshold below which a partial close is treated as a full close.
# Avoids leaving 0.1% dust positions open after rounding.
FULL_CLOSE_RESIDUAL_PCT = 0.5


def init_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(POSITION_SCHEMA)
    # Migration: ALTER TABLE adds `pct_open` column to legacy databases that
    # predate the partial-close tracking. DEFAULT 100 means existing rows are
    # treated as fully open, which matches their pre-migration semantics.
    try:
        conn.execute("ALTER TABLE positions ADD COLUMN pct_open REAL NOT NULL DEFAULT 100")
    except sqlite3.OperationalError:
        pass  # column already exists — schema already up to date
    # Migration: add targets_remaining column. NULL on legacy rows is fine —
    # the target-guard only consults it on new opens.
    try:
        conn.execute("ALTER TABLE positions ADD COLUMN targets_remaining TEXT")
    except sqlite3.OperationalError:
        pass
    # Migration: add UNIQUE(pos_id, msg_id, kind) on events for partial-close
    # idempotency. SQLite can't ALTER TABLE ADD CONSTRAINT, so the index is
    # created instead — same effect for our INSERT OR IGNORE pattern.
    #
    # If legacy data already contains (pos_id, msg_id, kind) duplicates from
    # the pre-fix era (when close_partial collapsed to close_full and re-fired
    # on redelivery), CREATE UNIQUE INDEX raises IntegrityError. Auto-dedupe:
    # keep the oldest event_id per group, delete the rest. Log loudly so any
    # historical loss of audit rows is operator-visible.
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_pos_msg_kind "
            "ON events(pos_id, msg_id, kind)"
        )
    except sqlite3.IntegrityError:
        dupe_count = conn.execute(
            "SELECT COUNT(*) FROM events e WHERE EXISTS ("
            "  SELECT 1 FROM events e2 "
            "  WHERE e2.pos_id = e.pos_id AND e2.msg_id = e.msg_id "
            "  AND e2.kind = e.kind AND e2.event_id < e.event_id)"
        ).fetchone()[0]
        logger.error(
            "[MIGRATION] %d duplicate event rows detected before applying "
            "UNIQUE(pos_id, msg_id, kind) index. Auto-deduping (keeping oldest "
            "event_id per group). Audit rows lost — symptom of pre-fix "
            "redelivery double-firing.", dupe_count,
        )
        conn.execute(
            "DELETE FROM events WHERE event_id NOT IN ("
            "  SELECT MIN(event_id) FROM events GROUP BY pos_id, msg_id, kind"
            ")"
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_events_pos_msg_kind "
            "ON events(pos_id, msg_id, kind)"
        )
    except sqlite3.OperationalError:
        pass  # index already exists
    return conn


def find_active_position(
    conn: sqlite3.Connection, signal_id: Optional[int], symbol: str
) -> tuple[Optional[dict], str]:
    """Look up the active position for this (signal_id, symbol).

    Returns (position_dict_or_None, reason). `reason` is one of:
      'matched_by_signal_id' — exact signal_id + symbol match
      'matched_by_symbol_unique' — fallback succeeded because only one
                                   active position for this symbol exists
      'no_match' — no active position for this symbol at all
      'ambiguous' — multiple active positions for this symbol; refuse
                    to close blindly (closing the wrong trade is worse
                    than missing the close).
    """
    if signal_id is not None:
        row = conn.execute(
            "SELECT * FROM positions "
            "WHERE signal_id = ? AND symbol = ? AND state IN ('open', 'requested') "
            "ORDER BY open_date DESC LIMIT 1",
            (signal_id, symbol),
        ).fetchone()
        if row:
            return dict(row), "matched_by_signal_id"

    # Fallback by symbol — ONLY if exactly one active position exists.
    # Otherwise we'd risk closing the wrong trade (codex review finding #3).
    rows = conn.execute(
        "SELECT * FROM positions "
        "WHERE symbol = ? AND state IN ('open', 'requested') "
        "ORDER BY open_date DESC",
        (symbol,),
    ).fetchall()
    if len(rows) == 1:
        return dict(rows[0]), "matched_by_symbol_unique"
    if len(rows) > 1:
        return None, "ambiguous"
    return None, "no_match"


# ── Sizing ─────────────────────────────────────────────────────────────────


def compute_stake(
    classification: dict, cfg: Config
) -> tuple[float, float, Optional[float]]:
    """Return (stake_usd, leverage, sl_distance_pct).

    Sizing model (matches the other dry-run bots' risk-budget rule):
      sl_distance_pct = |entry_mid - sl| / entry_mid
      stake_usd is constant per trade (default $20 → max 10 concurrent on $200);
      leverage is constant default 5x.
    Future: tighten sizing to per-trade-risk ($1 risk / sl_distance), like
    insiders-receiver. For MVP just use fixed stake + fixed leverage.
    """
    sl = classification.get("sl")
    entry_range = classification.get("entry_range") or []
    entry = classification.get("entry")

    # Compute entry midpoint
    if entry_range and isinstance(entry_range, list) and len(entry_range) == 2:
        try:
            lo, hi = float(entry_range[0]), float(entry_range[1])
            entry_mid = (lo + hi) / 2
        except (TypeError, ValueError):
            entry_mid = None
    elif isinstance(entry, (int, float)):
        entry_mid = float(entry)
    else:
        entry_mid = None

    sl_dist = None
    if entry_mid and isinstance(sl, (int, float)):
        sl_dist = abs(entry_mid - float(sl)) / entry_mid if entry_mid else None

    return cfg.stake_usd, cfg.leverage, sl_dist


# ── Freqtrade REST calls ───────────────────────────────────────────────────


async def ft_force_enter(
    cfg: Config, pair: str, direction: str, stake: float, leverage: float,
    session=None,
) -> dict:
    """POST /forceenter to the killers Freqtrade bot. Returns response dict.

    Per Freqtrade docs: side is 'long' or 'short'; stakeamount in quote currency;
    leverage as float; ordertype 'market' for immediate fills (matches config).

    If `session` is provided (a pre-authed aiohttp.ClientSession), reuses it.
    Falls back to a one-shot session if None — keeps the function usable
    outside the FastAPI lifespan (tests, ad-hoc scripts).
    """
    url = f"{cfg.ft_base}/api/v1/forceenter"
    body = {
        "pair": pair,
        "side": direction,
        "stakeamount": round(stake, 2),
        "leverage": leverage,
        "ordertype": "market",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    if session is not None:
        async with session.post(url, json=body, timeout=timeout) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=body, auth=auth, timeout=timeout) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}


async def ft_force_exit(cfg: Config, trade_id: int,
                        pct: Optional[float] = None,
                        session=None) -> dict:
    """POST /forceexit. `pct` (0–100) is the fraction of the CURRENT remaining
    position to close — NOT the fraction of original size. The receiver
    converts original-percentage-point signals into remaining-fraction before
    calling this (see _process_event close branch).

    Freqtrade's `amount` field is base-currency size, NOT a percentage. For a
    real partial close we must look up the trade's current amount and send
    `current_amount * pct/100`. Without the lookup, Freqtrade treats any
    `amount` we pass as base coins and either over-closes or rejects.

    Passing `pct=None` or `pct>=100` omits `amount` so Freqtrade closes the
    whole trade. If the trade lookup fails for a partial we fail closed —
    don't fall through to a full close, that would amplify the signaler's
    intent. Returns a synthetic `{status: 0, body: "<error>"}` so the
    caller's status gate treats it as not-accepted.
    """
    url = f"{cfg.ft_base}/api/v1/forceexit"
    body: dict[str, Any] = {"tradeid": str(trade_id), "ordertype": "market"}
    if pct is not None and pct < 100:
        trade = await ft_get_trade(cfg, trade_id, session=session)
        if trade is None:
            logger.error("ft_force_exit partial: cannot fetch trade %d", trade_id)
            return {"status": 0, "body": f"cannot fetch trade {trade_id} for partial exit"}
        raw_amount = trade.get("amount")
        # Freqtrade may return amount as int, float, or string (Decimal-typed
        # JSON). Coerce defensively. Reject NaN/inf/negative/zero.
        try:
            current_amount = float(raw_amount) if raw_amount is not None else None
        except (TypeError, ValueError):
            logger.error("ft_force_exit partial: trade %d amount unparseable: %r",
                         trade_id, raw_amount)
            return {"status": 0,
                    "body": f"trade {trade_id} amount unparseable: {raw_amount!r}"}
        import math
        if (current_amount is None
                or not math.isfinite(current_amount)
                or current_amount <= 0):
            logger.error("ft_force_exit partial: trade %d has bad amount %r",
                         trade_id, raw_amount)
            return {"status": 0,
                    "body": f"trade {trade_id} amount unusable: {raw_amount!r}"}
        body["amount"] = round(current_amount * pct / 100.0, 8)
    timeout = aiohttp.ClientTimeout(total=10)
    if session is not None:
        async with session.post(url, json=body, timeout=timeout) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=body, auth=auth, timeout=timeout) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}


async def ft_get_trade(cfg: Config, trade_id: int,
                       session=None) -> Optional[dict]:
    url = f"{cfg.ft_base}/api/v1/trade/{trade_id}"
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        if session is not None:
            async with session.get(url, timeout=timeout) as r:
                if r.status == 200:
                    return await r.json()
                return None
        auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, auth=auth, timeout=timeout) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        logger.warning("ft_get_trade failed: %s", e)
    return None


async def ft_force_exit_limit(cfg: Config, trade_id: int, amount: float,
                              price: float, session=None) -> dict:
    """POST /forceexit with ordertype=limit at a specific price + amount.

    Used by Phase 2 active-TP placement. Each TP gets its own resting
    LIMIT exit order at the exchange — fills automatically when price
    crosses the TP, no need for the receiver to react to channel
    "Target N hit" announcements.

    Caller MUST have already computed `amount` in base currency (slice
    of the position) and verified `price` is on the favorable side
    relative to current mark. Returns `{status, body}` like the market
    helpers.
    """
    url = f"{cfg.ft_base}/api/v1/forceexit"
    body: dict[str, Any] = {
        "tradeid": str(trade_id),
        "ordertype": "limit",
        "amount": round(float(amount), 8),
        "price": float(price),
    }
    timeout = aiohttp.ClientTimeout(total=10)
    if session is not None:
        async with session.post(url, json=body, timeout=timeout) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=body, auth=auth, timeout=timeout) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}


async def ft_open_trades(cfg: Config, session=None) -> list[dict]:
    url = f"{cfg.ft_base}/api/v1/status"
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        if session is not None:
            async with session.get(url, timeout=timeout) as r:
                if r.status == 200:
                    return await r.json()
                return []
        auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, auth=auth, timeout=timeout) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        logger.warning("ft_open_trades failed: %s", e)
    return []


# ── HTTP API ───────────────────────────────────────────────────────────────


class EventPayload(BaseModel):
    msg: dict
    classification: dict


# ── Phase 2: active TP-limit-order placement ─────────────────────────────


async def _place_target_limits(
    cfg: Config, conn: sqlite3.Connection,
    pos_id: int, ft_trade_id: int,
    targets: list[float], slice_amount: float,
    session=None,
) -> list[dict]:
    """Post a LIMIT exit order at each TP, persist a target_orders row per
    target. Returns a list of `{idx, price, ft_order_id, state}` dicts for
    audit + the open response.

    Best-effort per target: if one TP's /forceexit rejects (precision,
    min-notional, etc.) we still attempt the rest. Failures are logged
    and the target_orders row is marked `rejected` with the FT body for
    operator review.
    """
    if session is None:
        session = getattr(app.state, "ft_session", None)
    placed: list[dict] = []
    for idx, tp_price in enumerate(targets):
        # Persist row in 'pending' state before posting so a crash mid-call
        # leaves an audit trail. UNIQUE constraint via composite, but we
        # don't enforce it — each (pos_id, idx) is unique by construction.
        cur = conn.execute(
            "INSERT INTO target_orders (pos_id, idx, price, amount, state) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (pos_id, idx, float(tp_price), round(float(slice_amount), 8)),
        )
        target_id = cur.lastrowid
        try:
            resp = await ft_force_exit_limit(
                cfg, ft_trade_id, slice_amount, tp_price, session=session,
            )
        except Exception as e:
            logger.exception("[PHASE2] /forceexit limit raised for pos=%d idx=%d", pos_id, idx)
            conn.execute(
                "UPDATE target_orders SET state='rejected', notes=?, "
                "last_check_at=? WHERE target_id=?",
                (f"exception: {e}", datetime.now(timezone.utc).isoformat(), target_id),
            )
            placed.append({"idx": idx, "price": tp_price, "state": "rejected",
                           "reason": str(e)})
            continue

        ok = 200 <= resp["status"] < 300
        if not ok:
            logger.error(
                "[PHASE2] target idx=%d price=%g REJECTED pos=%d ft_trade=%d "
                "status=%d body=%s",
                idx, tp_price, pos_id, ft_trade_id, resp["status"],
                (resp.get("body") or "")[:200],
            )
            conn.execute(
                "UPDATE target_orders SET state='rejected', notes=?, "
                "last_check_at=? WHERE target_id=?",
                (f"ft_status={resp['status']} body={resp.get('body','')[:300]}",
                 datetime.now(timezone.utc).isoformat(), target_id),
            )
            placed.append({"idx": idx, "price": tp_price,
                           "state": "rejected",
                           "ft_status": resp["status"]})
            continue

        # FT accepted. Try to pull the new order_id from the response body
        # (FT returns the freshly created trade snapshot whose `orders[]`
        # array includes the new exit order). Pick the most recent
        # ft_order_side=sell/buy-close order with status=open. If we can't
        # find it now, the reconciler will back-link by pos+price+amount.
        new_order_id = None
        try:
            body = json.loads(resp.get("body") or "{}")
            new_order_id = _extract_new_exit_order_id(body, tp_price, slice_amount)
        except Exception:
            pass

        conn.execute(
            "UPDATE target_orders SET state='active', ft_order_id=?, placed_at=?, "
            "last_check_at=? WHERE target_id=?",
            (new_order_id, datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat(), target_id),
        )
        placed.append({
            "target_id": target_id, "idx": idx, "price": tp_price,
            "ft_order_id": new_order_id, "state": "active",
        })
        logger.info(
            "[PHASE2] pos=%d idx=%d limit posted at price=%g amount=%.6f ft_order_id=%s",
            pos_id, idx, tp_price, slice_amount, new_order_id,
        )
    return placed


def _extract_new_exit_order_id(body: dict, target_price: float,
                                expected_amount: float) -> Optional[str]:
    """Pick the newly-created limit exit order from a /forceexit response.

    FT's snapshot may contain legacy orders from earlier requests. Sort
    candidates by `order_timestamp` descending so we prefer the most
    recent matching limit, which is the one we just placed.
    """
    orders = body.get("orders") or []
    candidates: list[tuple[int, dict]] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        if not o.get("is_open"):
            continue
        if o.get("order_type") != "limit":
            continue
        price = o.get("safe_price") or o.get("price")
        amount = o.get("amount")
        try:
            if (price is not None and abs(float(price) - float(target_price)) / float(target_price) < 0.001
                    and amount is not None and abs(float(amount) - float(expected_amount)) / float(expected_amount) < 0.01):
                ts = o.get("order_timestamp") or 0
                try:
                    ts_int = int(ts)
                except (TypeError, ValueError):
                    ts_int = 0
                candidates.append((ts_int, o))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1].get("order_id")


async def _reconcile_target_orders(
    cfg: Config, conn: sqlite3.Connection, session=None,
) -> dict:
    """Scan active target_orders and transition states based on FT's view.

    For each row state='active': query /trade/{ft_trade_id}, find the
    matching order by ft_order_id (or by price+amount as fallback), and
    transition:
      order.status=='closed' + filled > 0 → state='filled'
      order.status in ('canceled','cancelled','expired') → state='cancelled'
      no matching order found → leave active (might be partial-fill that
                                FT consolidated; safer than guessing)
    """
    summary = {"checked": 0, "filled": 0, "cancelled": 0, "still_active": 0}
    rows = conn.execute(
        "SELECT t.target_id, t.pos_id, t.idx, t.price, t.amount, t.ft_order_id, "
        "       p.ft_trade_id, p.state AS pos_state "
        "FROM target_orders t JOIN positions p ON p.pos_id = t.pos_id "
        "WHERE t.state = 'active' AND p.state = 'open'"
    ).fetchall()
    if not rows:
        return summary

    # Group by ft_trade_id so we query FT once per trade.
    trades_by_id: dict[int, dict] = {}
    for r in rows:
        ft_tid = r["ft_trade_id"]
        if ft_tid is None:
            continue
        if ft_tid not in trades_by_id:
            trade = await ft_get_trade(cfg, ft_tid, session=session)
            if trade is None:
                continue
            trades_by_id[ft_tid] = trade
        trade = trades_by_id.get(ft_tid)
        if trade is None:
            continue
        summary["checked"] += 1
        order = _find_matching_order(trade.get("orders") or [],
                                     r["ft_order_id"], r["price"], r["amount"])
        if order is None:
            summary["still_active"] += 1
            continue
        status = (order.get("status") or "").lower()
        filled = float(order.get("filled") or 0)
        if status == "closed" and filled > 0:
            conn.execute(
                "UPDATE target_orders SET state='filled', filled_at=?, "
                "last_check_at=? WHERE target_id=?",
                (datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat(), r["target_id"]),
            )
            summary["filled"] += 1
            logger.info(
                "[PHASE2 RECONCILE] FILLED pos=%d idx=%d price=%g order_id=%s",
                r["pos_id"], r["idx"], r["price"], r["ft_order_id"],
            )
        elif status in ("canceled", "cancelled", "expired", "rejected"):
            conn.execute(
                "UPDATE target_orders SET state='cancelled', notes=?, "
                "last_check_at=? WHERE target_id=?",
                (f"ft_order_status={status}",
                 datetime.now(timezone.utc).isoformat(), r["target_id"]),
            )
            summary["cancelled"] += 1
            logger.warning(
                "[PHASE2 RECONCILE] CANCELLED pos=%d idx=%d order_id=%s status=%s",
                r["pos_id"], r["idx"], r["ft_order_id"], status,
            )
        else:
            summary["still_active"] += 1
            conn.execute(
                "UPDATE target_orders SET last_check_at=? WHERE target_id=?",
                (datetime.now(timezone.utc).isoformat(), r["target_id"]),
            )
    return summary


def _find_matching_order(orders: list[dict], ft_order_id: Optional[str],
                         target_price: float, expected_amount: float) -> Optional[dict]:
    """Locate a target's matching order in FT's trade.orders[] array.

    Prefers exact ft_order_id match. Falls back to price+amount match for
    limit-type orders only — never matches market orders (those are entries
    or full force-exits, not TPs). When multiple limits match in fallback
    mode, pick the newest by order_timestamp.
    """
    if ft_order_id:
        for o in orders:
            if isinstance(o, dict) and o.get("order_id") == ft_order_id:
                return o
    # Fallback: match by limit + price + amount.
    candidates: list[tuple[int, dict]] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        if o.get("order_type") != "limit":
            continue
        try:
            price = float(o.get("safe_price") or o.get("price") or 0)
            amount = float(o.get("amount") or 0)
            if (price > 0 and abs(price - float(target_price)) / float(target_price) < 0.001
                    and amount > 0 and abs(amount - float(expected_amount)) / float(expected_amount) < 0.01):
                ts = o.get("order_timestamp") or 0
                try:
                    ts_int = int(ts)
                except (TypeError, ValueError):
                    ts_int = 0
                candidates.append((ts_int, o))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


async def target_orders_reconcile_loop(cfg: Config, conn: sqlite3.Connection,
                                       ft_session=None) -> None:
    """Background loop that ticks _reconcile_target_orders every
    cfg.target_reconcile_sec. Separate from the position-level reconcile
    so cadences can differ."""
    import asyncio
    while True:
        try:
            await _reconcile_target_orders(cfg, conn, session=ft_session)
        except Exception as e:
            logger.warning("target_orders reconcile error: %s", e)
        await asyncio.sleep(cfg.target_reconcile_sec)


async def reconcile_loop(cfg: Config, conn: sqlite3.Connection,
                         ft_session=None) -> None:
    """Repair orphans: positions stuck in 'requested' with no ft_trade_id,
    and positions whose Freqtrade trade has closed without our seeing it.

    Two failure modes addressed:
      1. Receiver crashed between /forceenter and writing trade_id back.
         → Look up open trades on Freqtrade by pair+direction+open_date
         and back-fill ft_trade_id.
      2. Freqtrade closed a trade (e.g. liquidation, manual close) without
         our /forceexit. → Mark position closed locally.
    """
    import asyncio
    while True:
        try:
            ft_open = await ft_open_trades(cfg, session=ft_session)
            ft_by_pair: dict[tuple, dict] = {}
            for t in ft_open:
                key = (t.get("pair"), bool(t.get("is_short")))
                ft_by_pair[key] = t

            # (1) link orphans
            orphans = conn.execute(
                "SELECT * FROM positions WHERE state = 'requested' AND ft_trade_id IS NULL "
                "ORDER BY open_date DESC LIMIT 50"
            ).fetchall()
            for pos in orphans:
                key = (pos["pair"], pos["direction"] == "short")
                ft = ft_by_pair.get(key)
                if ft and ft.get("trade_id"):
                    conn.execute(
                        "UPDATE positions SET state = 'open', ft_trade_id = ?, last_event_at = ? "
                        "WHERE pos_id = ?",
                        (ft["trade_id"], datetime.now(timezone.utc).isoformat(), pos["pos_id"]),
                    )
                    logger.info("[RECONCILE] orphan pos_id=%d linked to ft_trade_id=%d",
                                pos["pos_id"], ft["trade_id"])

            # (2) detect closes we missed
            our_open_ids = {row["ft_trade_id"] for row in conn.execute(
                "SELECT ft_trade_id FROM positions WHERE state = 'open' AND ft_trade_id IS NOT NULL"
            )}
            ft_open_ids = {t["trade_id"] for t in ft_open}
            missed = our_open_ids - ft_open_ids
            for tid in missed:
                conn.execute(
                    "UPDATE positions SET state = 'closed', close_reason = 'reconciled_missing', "
                    "close_date = ?, last_event_at = ? WHERE ft_trade_id = ? AND state = 'open'",
                    (datetime.now(timezone.utc).isoformat(),
                     datetime.now(timezone.utc).isoformat(), tid),
                )
                logger.info("[RECONCILE] ft_trade_id=%d no longer open in freqtrade; marked closed",
                            tid)
        except Exception as e:
            logger.warning("reconcile loop error: %s", e)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    cfg = Config()
    conn = init_db(cfg.db_path)
    app.state.cfg = cfg
    app.state.conn = conn
    # Persistent aiohttp sessions: reusing the underlying TCP connections
    # saves ~10-100ms per call on the hot path (FT + Binance + Telegram).
    # `ft_session` carries BasicAuth so every call to FT REST reuses it
    # without rebuilding the credential. `public_session` is for unauthed
    # endpoints (Binance public API, trade-webhook notify).
    import aiohttp
    ft_auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    app.state.ft_session = aiohttp.ClientSession(auth=ft_auth)
    app.state.public_session = aiohttp.ClientSession()
    # Track background notify tasks so we can drain on shutdown.
    app.state.notify_tasks = set()
    logger.info(
        "receiver up ft=%s db=%s stake=$%.0f lev=%.1fx max_open=%d "
        "max_slippage=%.1f%% active_tp=%s reconcile_sec=%d",
        cfg.ft_base, cfg.db_path, cfg.stake_usd, cfg.leverage, cfg.max_open,
        cfg.max_entry_slippage_pct, cfg.active_tp_limits,
        cfg.target_reconcile_sec,
    )
    recon = asyncio.create_task(
        reconcile_loop(cfg, conn, ft_session=app.state.ft_session)
    )
    target_recon = None
    if cfg.active_tp_limits:
        target_recon = asyncio.create_task(
            target_orders_reconcile_loop(cfg, conn,
                                          ft_session=app.state.ft_session)
        )
    try:
        yield
    finally:
        recon.cancel()
        if target_recon is not None:
            target_recon.cancel()
        # Drain in-flight notify tasks with a short timeout so we don't
        # leak Telegram POSTs on container restart.
        if app.state.notify_tasks:
            try:
                await asyncio.wait(app.state.notify_tasks, timeout=3)
            except Exception:
                pass
        await app.state.ft_session.close()
        await app.state.public_session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/positions")
async def list_positions():
    conn: sqlite3.Connection = app.state.conn
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM positions ORDER BY pos_id DESC LIMIT 100"
    )]
    return {"count": len(rows), "positions": rows}


@app.get("/target_orders")
async def list_target_orders(pos_id: Optional[int] = None,
                              state: Optional[str] = None,
                              limit: int = 100):
    """Inspect phase-2 target_orders state. Useful for verifying limit
    placements + reconciler progression. Filter by pos_id and/or state."""
    conn: sqlite3.Connection = app.state.conn
    sql = "SELECT * FROM target_orders WHERE 1=1"
    params: list = []
    if pos_id is not None:
        sql += " AND pos_id = ?"
        params.append(pos_id)
    if state is not None:
        sql += " AND state = ?"
        params.append(state)
    sql += " ORDER BY target_id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params)]
    return {"count": len(rows), "target_orders": rows}


@app.post("/target_orders/reconcile")
async def force_reconcile_target_orders():
    """Manually tick the target_orders reconciler. Returns the summary."""
    cfg: Config = app.state.cfg
    conn: sqlite3.Connection = app.state.conn
    session = getattr(app.state, "ft_session", None)
    summary = await _reconcile_target_orders(cfg, conn, session=session)
    return summary


# Pending events older than this are surfaced as "stuck" — the receiver
# successfully claimed the (pos_id, msg_id, kind) but never patched the
# response, almost certainly because it crashed between the claim insert
# and the UPDATE that records the FT result. Operator action required:
# inspect, decide whether FT actually applied the partial, then manually
# patch via /events/pending/{event_id}/resolve.
PENDING_STUCK_AFTER_SEC = 300  # 5 min


def _pending_events_count(conn: sqlite3.Connection,
                          older_than_sec: int = PENDING_STUCK_AFTER_SEC) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE json_extract("
        "  CASE WHEN json_valid(response) THEN response ELSE '{}' END, "
        "  '$.status') = 'pending' "
        "AND event_at < ?",
        (cutoff,),
    ).fetchone()
    return row[0] if row else 0


@app.get("/system")
async def system_state():
    """Operator dashboard summary. `pending_events_count` non-zero means
    one or more partial-closes crashed mid-flight; check /events/pending."""
    conn: sqlite3.Connection = app.state.conn
    open_count = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE state IN ('open', 'requested')"
    ).fetchone()[0]
    pending = _pending_events_count(conn)
    # Oldest pending age, if any
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=PENDING_STUCK_AFTER_SEC)).isoformat()
    oldest_row = conn.execute(
        "SELECT MIN(event_at) FROM events "
        "WHERE json_extract("
        "  CASE WHEN json_valid(response) THEN response ELSE '{}' END, "
        "  '$.status') = 'pending' "
        "AND event_at < ?",
        (cutoff,),
    ).fetchone()
    oldest_age_sec = None
    if oldest_row and oldest_row[0]:
        try:
            opened = datetime.fromisoformat(oldest_row[0].replace("Z", "+00:00"))
            oldest_age_sec = (datetime.now(timezone.utc) - opened).total_seconds()
        except Exception:
            pass
    return {
        "instance": "killers",
        "active_positions_count": open_count,
        "pending_events_count": pending,
        "oldest_pending_age_sec": oldest_age_sec,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/events/pending")
async def list_pending_events(older_than_sec: int = PENDING_STUCK_AFTER_SEC):
    """Events that claimed a (pos_id, msg_id, kind) slot but never recorded
    a real FT response. Crash-mid-partial signature."""
    conn: sqlite3.Connection = app.state.conn
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)).isoformat()
    rows = conn.execute(
        "SELECT event_id, pos_id, msg_id, kind, event_at, payload "
        "FROM events "
        "WHERE json_extract("
        "  CASE WHEN json_valid(response) THEN response ELSE '{}' END, "
        "  '$.status') = 'pending' "
        "AND event_at < ? "
        "ORDER BY event_at ASC LIMIT 100",
        (cutoff,),
    ).fetchall()
    out = []
    now = datetime.now(timezone.utc)
    for r in rows:
        try:
            evt = datetime.fromisoformat(r["event_at"].replace("Z", "+00:00"))
            age_sec = (now - evt).total_seconds()
        except Exception:
            age_sec = None
        out.append({
            "event_id": r["event_id"],
            "pos_id": r["pos_id"],
            "msg_id": r["msg_id"],
            "kind": r["kind"],
            "event_at": r["event_at"],
            "age_sec": age_sec,
            "payload": json.loads(r["payload"]) if r["payload"] else {},
        })
    return out


@app.post("/events/pending/{event_id}/resolve")
async def resolve_pending_event(event_id: int,
                                action: str = "drop",
                                ft_status: int = 200):
    """Operator action on a stuck-pending event.

    action='drop'   — declare the partial as having been applied successfully
                      (or accept the divergence). Updates the event row's
                      response to reflect operator intent; if action='drop'
                      and ft_status is 2xx, also reduces pct_open per the
                      original close intent (close_pp_of_original).
    action='cancel' — declare the partial as NOT applied. Event row marked
                      cancelled, pct_open untouched, position state untouched.

    Operator MUST inspect Freqtrade state before calling. This is a manual
    audit trail patch, not an auto-heal. Wrapped in BEGIN IMMEDIATE so the
    pending-check, position mutation, and event UPDATE are atomic — no
    chance of partial application on crash or concurrent retry.
    """
    if action not in ("drop", "cancel"):
        raise HTTPException(status_code=400, detail="action must be 'drop' or 'cancel'")
    conn: sqlite3.Connection = app.state.conn
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,),
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            raise HTTPException(status_code=404, detail="event not found")
        try:
            payload = json.loads(row["payload"])
            response = json.loads(row["response"])
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(status_code=500, detail=f"event row malformed: {e}")
        if response.get("status") != "pending":
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=409,
                detail=f"event response is {response!r}, not pending — refusing to resolve",
            )

        if action == "cancel":
            conn.execute(
                "UPDATE events SET response = ? WHERE event_id = ?",
                (json.dumps({"status": "cancelled", "by": "operator"}), event_id),
            )
            conn.execute("COMMIT")
            logger.warning("[OPERATOR] event_id=%d cancelled (not applied)", event_id)
            return {"status": "cancelled", "event_id": event_id}

        # drop path
        ok = 200 <= ft_status < 300
        if ok:
            pos = conn.execute(
                "SELECT pct_open, state FROM positions WHERE pos_id = ?",
                (row["pos_id"],),
            ).fetchone()
            if not pos:
                conn.execute("ROLLBACK")
                raise HTTPException(status_code=404, detail="position vanished")
            close_pp_raw = payload.get("close_pp_of_original")
            try:
                close_pp = float(close_pp_raw)
            except (TypeError, ValueError):
                close_pp = -1.0
            pct_open_before = float(pos["pct_open"])
            if not (0 < close_pp <= pct_open_before):
                conn.execute("ROLLBACK")
                raise HTTPException(
                    status_code=422,
                    detail=(f"invalid close_pp_of_original={close_pp_raw!r} "
                            f"vs pct_open={pct_open_before}; expected 0 < close_pp <= pct_open"),
                )
            new_pct_open = max(0.0, round(pct_open_before - close_pp, 4))
            new_state = "closed" if new_pct_open <= FULL_CLOSE_RESIDUAL_PCT else pos["state"]
            if new_state == "closed":
                conn.execute(
                    "UPDATE positions SET state = 'closed', pct_open = 0, "
                    "close_msg_id = ?, close_date = ?, close_reason = ?, "
                    "last_event_at = ? WHERE pos_id = ?",
                    (row["msg_id"], row["event_at"], row["kind"],
                     datetime.now(timezone.utc).isoformat(), row["pos_id"]),
                )
            else:
                conn.execute(
                    "UPDATE positions SET pct_open = ?, last_event_at = ? "
                    "WHERE pos_id = ?",
                    (new_pct_open, datetime.now(timezone.utc).isoformat(),
                     row["pos_id"]),
                )
            conn.execute(
                "UPDATE events SET response = ? WHERE event_id = ?",
                (json.dumps({"status": ft_status, "by": "operator-drop",
                             "synthetic": True}), event_id),
            )
            conn.execute("COMMIT")
            logger.warning(
                "[OPERATOR] event_id=%d dropped as applied: pos_id=%d "
                "pct_open %.1f → %.1f state=%s",
                event_id, row["pos_id"], pct_open_before, new_pct_open, new_state,
            )
            return {"status": "applied", "event_id": event_id,
                    "pos_id": row["pos_id"], "new_pct_open": new_pct_open,
                    "new_state": new_state}

        # drop with non-2xx ft_status: audit-only, no state change
        conn.execute(
            "UPDATE events SET response = ? WHERE event_id = ?",
            (json.dumps({"status": ft_status, "by": "operator-drop",
                         "synthetic": True}), event_id),
        )
        conn.execute("COMMIT")
        logger.warning(
            "[OPERATOR] event_id=%d marked as non-2xx (status=%d), pct_open unchanged",
            event_id, ft_status,
        )
        return {"status": "marked_failed", "event_id": event_id}
    except HTTPException:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


async def _notify_telegram(cfg: Config, text: str, session=None) -> None:
    """Best-effort POST to trade-webhook /test/notify → @elder_brain_bot.
    Silent on failure; observability shouldn't block the signal pipeline.

    Uses `async with` even for the persistent-session path so the response
    is released back to the connection pool. Without this, the connector
    slot stays held until GC and accumulates across alerts — would
    eventually starve the shared `public_session` of free connections.
    """
    if not cfg.notify_url:
        return
    timeout = aiohttp.ClientTimeout(total=5)
    payload = {"text": text}
    try:
        if session is not None:
            async with session.post(cfg.notify_url, json=payload,
                                    timeout=timeout) as r:
                # Read body to release connection cleanly. Don't care about content.
                await r.read()
            return
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(cfg.notify_url, json=payload) as r:
                await r.read()
    except Exception as e:
        logger.warning("telegram notify failed: %s", e)


def _format_event_summary(payload: EventPayload, result: dict) -> Optional[str]:
    """Compose a single-line Telegram-friendly summary, or None to skip.

    Keep it tight — feed reader will see this in @elder_brain_bot.
    """
    cls    = payload.classification
    kind   = cls.get("kind", "?")
    sym    = cls.get("symbol") or "?"
    direc  = (cls.get("direction") or "").upper()
    sig    = cls.get("signal_id") or "?"
    action = result.get("action", "?")
    reason = result.get("reason", "")

    # Chat is 60% of the corpus — filter to keep Telegram readable.
    if kind == "chat" or action == "ignored":
        return None
    # Duplicate observer redelivery: already alerted on the first pass.
    if action == "deduped":
        return None

    head = "[killers-scalp]"
    if action == "force_enter":
        pos = result.get("pos_id", "?")
        ft  = (result.get("ft") or {}).get("status", "?")
        remaining = result.get("remaining_targets") or []
        sig_targets = result.get("signal_targets") or []
        tgt_tail = ""
        if sig_targets:
            crossed = len(sig_targets) - len(remaining)
            if crossed > 0 and remaining:
                tgt_tail = f" · {crossed}/{len(sig_targets)} TPs crossed, next={remaining[0]:g}"
            elif remaining:
                tgt_tail = f" · {len(remaining)} TPs ahead, next={remaining[0]:g}"
        return f"📈 {head} OPEN  · #{sig} {sym} {direc}  · pos={pos} ft_status={ft}{tgt_tail}"
    if action == "skipped" and reason == "all_targets_crossed":
        mark = result.get("mark", "?")
        return f"🚫 {head} SKIPPED · #{sig} {sym} {direc}  · all TPs already crossed (mark={mark})"
    if action == "skipped" and reason == "entry_slippage_exceeded":
        slip = result.get("slippage_pct", "?")
        cap = result.get("max_slippage_pct", "?")
        mark = result.get("mark", "?")
        entry_lo = result.get("entry_lo", "?")
        entry_hi = result.get("entry_hi", "?")
        return (f"🚫 {head} SKIPPED · #{sig} {sym} {direc}  · "
                f"slippage {slip}% > {cap}% (entry {entry_lo}-{entry_hi}, mark {mark})")
    if action == "skipped" and reason == "entry_bounds_missing":
        cap = result.get("max_slippage_pct", "?")
        return (f"🚫 {head} SKIPPED · #{sig} {sym} {direc}  · "
                f"entry bounds missing, slippage cap {cap}% enabled — fail-closed")
    if action == "force_exit":
        pos = result.get("pos_id", "?")
        ft  = (result.get("ft") or {}).get("status", "?")
        verb = "CLOSE_PARTIAL" if kind == "close_partial" else "CLOSE_FULL"
        # Surface partial-close arithmetic in ORIGINAL percentage points:
        # how much of original we closed, what's still open after.
        pct_closed = result.get("pct_closed_of_original")
        pct_after = result.get("pct_open_after")
        tail = ""
        if pct_closed is not None and pct_after is not None:
            tail = f" · closed {pct_closed:.0f}pp of original → {pct_after:.0f}% still open"
        # Anything outside 2xx (including synthetic status=0 from FT lookup
        # failure inside ft_force_exit) is a failure.
        ft_ok = isinstance(ft, int) and 200 <= ft < 300
        emoji = "📉" if ft_ok else "❌"
        return f"{emoji} {head} {verb} · #{sig} {sym}  · pos={pos} ft_status={ft}{tail}"
    if action == "skipped":
        return f"⏭ {head} OBSERVED · #{sig} {kind} {sym} {direc}  · skipped: {reason}"
    if action == "logged":
        return f"📝 {head} OBSERVED · #{sig} {kind} {sym} {direc}  · {reason}"
    return f"🔔 {head} {kind} {sym} · action={action} reason={reason}"


@app.post("/event")
async def handle_event(payload: EventPayload):
    result = await _process_event(payload)
    cfg: Config = app.state.cfg
    text = _format_event_summary(payload, result)
    if text:
        # TRUE fire-and-forget: spawn the notify as a background task so
        # the observer's POST gets a response immediately rather than
        # blocking on the trade-webhook round-trip. Codex flagged the
        # previous `await` as misleading vs the comment. Task is registered
        # on app.state.notify_tasks so we can drain on shutdown.
        task = asyncio.create_task(
            _notify_telegram(cfg, text,
                             session=getattr(app.state, "public_session", None))
        )
        notify_tasks = getattr(app.state, "notify_tasks", None)
        if notify_tasks is not None:
            notify_tasks.add(task)
            task.add_done_callback(notify_tasks.discard)
    return result


async def _process_event(payload: EventPayload):
    cfg: Config = app.state.cfg
    conn: sqlite3.Connection = app.state.conn
    msg = payload.msg
    cls = payload.classification
    kind = cls.get("kind")
    symbol = cls.get("symbol")
    signal_id = cls.get("signal_id")
    msg_id = msg.get("id")

    if kind == "chat":
        return {"action": "ignored", "reason": "chat"}

    if kind == "open":
        if not symbol or not cls.get("direction"):
            return {"action": "skipped", "reason": "missing symbol or direction"}
        pair = to_freqtrade_pair(symbol)
        if not pair:
            return {"action": "skipped", "reason": "symbol_unmappable"}

        # Guardrail: cap concurrent opens
        active = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE state IN ('open','requested')"
        ).fetchone()[0]
        if active >= cfg.max_open:
            return {"action": "skipped", "reason": f"max_open ({cfg.max_open})"}

        stake, leverage, sl_dist = compute_stake(cls, cfg)
        direction = cls["direction"].lower()
        if direction not in ("long", "short"):
            return {"action": "skipped", "reason": "bad_direction"}

        # Target-aware guard: parse the TARGETS ladder from the raw signal
        # text, fetch the live Binance mark price, and refuse to open if all
        # targets are already behind us. If some targets remain, persist the
        # filtered list so downstream close handling can match TP-hit
        # messages to specific levels.
        #
        # Direction semantics:
        #   LONG  → keep targets > mark; "all crossed" means mark >= max(targets)
        #   SHORT → keep targets < mark; "all crossed" means mark <= min(targets)
        #
        # Failure modes:
        #   - Targets line absent (channel/classifier drift) → skip guard,
        #     open without remaining-targets persistence (logged WARN).
        #   - Mark fetch fails when targets ARE present → fail closed (skip).
        #     We don't open into a position we can't verify is still viable.
        raw_text = msg.get("text") if isinstance(msg, dict) else None
        signal_targets = extract_targets_from_text(raw_text)
        remaining_targets: list[float] = []
        # Fetch mark once up front. We use it for both the entry-slippage
        # gate and the target-remaining filter, so a single Binance round-trip
        # serves both checks.
        mark: Optional[float] = None
        needs_mark = (
            (signal_targets and len(signal_targets) > 0)
            or cfg.max_entry_slippage_pct > 0
        )
        if needs_mark:
            mark = await get_binance_mark_price(
                symbol, session=getattr(app.state, "public_session", None),
            )
            if mark is None:
                logger.error(
                    "[GUARD] mark fetch failed for %s — refusing to open "
                    "(fail-closed: %d targets, slippage_pct=%.1f)",
                    symbol, len(signal_targets), cfg.max_entry_slippage_pct,
                )
                return {"action": "skipped",
                        "reason": "mark_fetch_failed (guard fail-closed)",
                        "signal_targets": signal_targets}

        # ── Entry slippage gate ───────────────────────────────────────────
        # If we'd fill too far past the signaler's entry boundary, skip.
        # This is what would have caught HYPE #2144: signal entry 56.80-57.00,
        # mark $60.86 at fill time = +6.78% slippage = past 3% gate → SKIP.
        #
        # When the cap is enabled but entry bounds are unparseable, FAIL
        # CLOSED rather than silently opening — the operator turned the
        # gate ON specifically to limit slippage, so missing data means
        # we cannot honor that contract.
        if cfg.max_entry_slippage_pct > 0 and mark is not None:
            entry_lo = cls.get("entry_lo")
            entry_hi = cls.get("entry_hi")
            # Some classifications carry a single `entry` instead of range
            # (rule-fast-path emits {entry, entry_range:None} or
            # {entry:None, entry_range:[lo,hi]}); handle both shapes.
            if entry_lo is None and entry_hi is None:
                entry_single = cls.get("entry")
                entry_range = cls.get("entry_range")
                if isinstance(entry_range, (list, tuple)) and len(entry_range) == 2:
                    entry_lo, entry_hi = entry_range[0], entry_range[1]
                elif isinstance(entry_single, (int, float)):
                    entry_lo = entry_hi = entry_single
            usable_bounds = (
                isinstance(entry_lo, (int, float))
                and isinstance(entry_hi, (int, float))
                and entry_lo > 0 and entry_hi > 0
            )
            if not usable_bounds:
                logger.error(
                    "[SLIPPAGE GUARD] %s %s entry bounds unparseable "
                    "(entry_lo=%r entry_hi=%r) but cap=%.1f%% enabled — fail-closed",
                    symbol, direction.upper(), entry_lo, entry_hi,
                    cfg.max_entry_slippage_pct,
                )
                return {"action": "skipped",
                        "reason": "entry_bounds_missing",
                        "mark": mark,
                        "entry_lo": entry_lo,
                        "entry_hi": entry_hi,
                        "max_slippage_pct": cfg.max_entry_slippage_pct}
            if direction == "long":
                bound = entry_hi
                slip_pct = (mark - bound) / bound * 100.0
            else:  # short
                bound = entry_lo
                slip_pct = (bound - mark) / bound * 100.0
            if slip_pct > cfg.max_entry_slippage_pct:
                logger.warning(
                    "[SLIPPAGE GUARD] %s %s entry=%.6g-%.6g mark=%.6g "
                    "slippage=%.2f%% > %.1f%% — skipping open",
                    symbol, direction.upper(), entry_lo, entry_hi, mark,
                    slip_pct, cfg.max_entry_slippage_pct,
                )
                return {"action": "skipped",
                        "reason": "entry_slippage_exceeded",
                        "mark": mark,
                        "entry_lo": entry_lo,
                        "entry_hi": entry_hi,
                        "slippage_pct": round(slip_pct, 2),
                        "max_slippage_pct": cfg.max_entry_slippage_pct}

        # ── Target remaining filter ───────────────────────────────────────
        if signal_targets:
            remaining_targets = filter_remaining_targets(
                signal_targets, mark, direction,
            )
            if not remaining_targets:
                logger.warning(
                    "[TARGET GUARD] all targets crossed for %s %s: mark=%s, targets=%s — skipping open",
                    symbol, direction.upper(), mark, signal_targets,
                )
                return {"action": "skipped",
                        "reason": "all_targets_crossed",
                        "mark": mark,
                        "signal_targets": signal_targets}
            crossed = len(signal_targets) - len(remaining_targets)
            if crossed > 0:
                logger.info(
                    "[TARGET GUARD] %s %s mark=%s: %d/%d targets already crossed, "
                    "%d remaining=%s",
                    symbol, direction.upper(), mark, crossed, len(signal_targets),
                    len(remaining_targets), remaining_targets,
                )
        else:
            logger.warning(
                "[TARGET GUARD] no TARGETS line parsed from signal text for %s "
                "msg_id=%d — opening without target guard",
                symbol, msg_id,
            )

        # Insert tentative position record BEFORE the REST call so we have audit
        # spine even if the call fails. UNIQUE constraint on open_msg_id makes
        # this idempotent — duplicate event delivery returns the existing row.
        targets_json = json.dumps(remaining_targets) if remaining_targets else None
        try:
            cur = conn.execute(
                "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
                " open_msg_id, open_date, stake_usd, leverage, sl_distance_pct, "
                " last_event_at, targets_remaining) "
                "VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?)",
                (signal_id, symbol, pair, direction, msg_id, str(msg.get("date")),
                 stake, leverage, sl_dist, datetime.now(timezone.utc).isoformat(),
                 targets_json),
            )
            pos_id = cur.lastrowid
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT pos_id, state, ft_trade_id FROM positions WHERE open_msg_id = ?",
                (msg_id,),
            ).fetchone()
            logger.info("[OPEN DUPE] msg_id=%d already processed pos_id=%d state=%s ft_trade_id=%s",
                        msg_id, existing["pos_id"], existing["state"], existing["ft_trade_id"])
            return {"action": "deduped", "pos_id": existing["pos_id"],
                    "state": existing["state"], "ft_trade_id": existing["ft_trade_id"]}

        # Fire the order
        resp = await ft_force_enter(
            cfg, pair, direction, stake, leverage,
            session=getattr(app.state, "ft_session", None),
        )
        conn.execute(
            "INSERT INTO events (pos_id, msg_id, event_at, kind, payload, response) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (pos_id, msg_id, datetime.now(timezone.utc).isoformat(),
             json.dumps({"pair": pair, "side": direction, "stake": stake,
                         "leverage": leverage,
                         "signal_targets": signal_targets,
                         "remaining_targets": remaining_targets}),
             json.dumps(resp)),
        )

        # Try to extract Freqtrade trade_id + filled amount from the response body
        ft_trade_id = None
        ft_amount = None
        try:
            body = json.loads(resp["body"])
            ft_trade_id = body.get("trade_id") or body.get("tradeid")
            ft_amount = body.get("amount")
        except Exception:
            pass

        new_state = "open" if (200 <= resp["status"] < 300) else "failed"
        conn.execute(
            "UPDATE positions SET state = ?, ft_trade_id = ?, last_event_at = ? "
            "WHERE pos_id = ?",
            (new_state, ft_trade_id, datetime.now(timezone.utc).isoformat(), pos_id),
        )

        # ── Phase 2: active TP-limit-order placement ──────────────────────
        # The Killers signaler publishes the FULL TP ladder at open time
        # and never mid-trade-closes at non-TP prices. Wiring those TPs
        # directly to the exchange as limit exits captures fills at
        # exchange-latency speed without round-tripping through the
        # channel's "Target N hit" announcement (which is post-hoc).
        placed_tps: list[dict] = []
        if (new_state == "open" and cfg.active_tp_limits
                and ft_trade_id and ft_amount and remaining_targets):
            try:
                amount_total = float(ft_amount)
            except (TypeError, ValueError):
                amount_total = 0.0
            n = len(remaining_targets)
            if amount_total > 0 and n > 0:
                slice_amt = amount_total / n
                placed_tps = await _place_target_limits(
                    cfg, conn, pos_id, ft_trade_id, remaining_targets, slice_amt,
                )

        logger.info(
            "[OPEN] pos_id=%d signal=#%s %s %s pair=%s stake=$%.0f lev=%.1fx "
            "remaining_targets=%s tp_orders_placed=%d → ft_status=%d ft_trade_id=%s",
            pos_id, signal_id, symbol, direction.upper(), pair, stake, leverage,
            remaining_targets, len(placed_tps), resp["status"], ft_trade_id,
        )
        return {"action": "force_enter", "pos_id": pos_id, "ft": resp,
                "remaining_targets": remaining_targets,
                "signal_targets": signal_targets,
                "tp_orders_placed": placed_tps}

    if kind in ("close_full", "close_partial"):
        if not symbol:
            return {"action": "skipped", "reason": "missing symbol on close"}
        pos, match_reason = find_active_position(conn, signal_id, symbol)
        if match_reason == "ambiguous":
            logger.warning("[CLOSE AMBIG] msg_id=%d signal=#%s sym=%s — refusing to close",
                           msg_id, signal_id, symbol)
            return {"action": "skipped", "reason": "ambiguous_close"}
        if not pos or not pos.get("ft_trade_id"):
            return {"action": "skipped", "reason": f"no_active_position ({match_reason})"}

        # Atomic claim BEFORE any await: SQLite's UNIQUE(pos_id, msg_id, kind)
        # is the only race-safe gate. A plain SELECT-then-await would let
        # concurrent requests both pass the check and both hit Freqtrade. Insert
        # a `pending` event row first; if rowcount==0 we're a duplicate and bail
        # without touching FT. After the FT call we UPDATE the same row with
        # the real response. Mirrors the Insiders msg-claim pattern.
        pct_open_raw = pos.get("pct_open")
        pct_remaining_before = 100.0 if pct_open_raw is None else float(pct_open_raw)
        if pct_remaining_before <= 0:
            return {"action": "skipped", "reason": "pct_open already zero"}

        # Compute close intent in ORIGINAL percentage points (matches Insiders
        # simulator semantics: pct_open = 100 - sum(close_partial.pct_of_original)).
        # close_full → close all remaining.
        # close_partial → classifier's pct is "X% of the original position"
        #                 (Killers channel convention: "TP1 hit, take 50%" means
        #                 close 50pp of the original size).
        if kind == "close_full":
            close_pp_of_original = pct_remaining_before  # close everything left
        else:
            raw_pct = cls.get("pct")
            if isinstance(raw_pct, (int, float)) and 0 < raw_pct <= 100:
                close_pp_of_original = float(raw_pct)
            else:
                close_pp_of_original = DEFAULT_PARTIAL_PCT
        # Cap at remaining: signaler saying "close 50%" when only 30 is left
        # collapses to closing the rest.
        close_pp_of_original = min(close_pp_of_original, pct_remaining_before)
        # Convert original-pp to remainder-fraction (what FT amount actually needs)
        close_pct_of_remaining = (close_pp_of_original / pct_remaining_before) * 100.0

        claim_payload = json.dumps({
            "ft_trade_id": pos["ft_trade_id"],
            "close_pp_of_original": close_pp_of_original,
            "pct_remaining_before": pct_remaining_before,
            "pending": True,
        })
        claim = conn.execute(
            "INSERT OR IGNORE INTO events "
            "(pos_id, msg_id, event_at, kind, payload, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pos["pos_id"], msg_id, datetime.now(timezone.utc).isoformat(),
             kind, claim_payload, json.dumps({"status": "pending"})),
        )
        if claim.rowcount == 0:
            # Concurrent or prior delivery already claimed this (pos_id, msg_id,
            # kind). Don't double-fire FT.
            logger.info("[%s DUPE] msg_id=%d pos_id=%d kind=%s — already claimed",
                        kind.upper(), msg_id, pos["pos_id"], kind)
            return {"action": "deduped", "pos_id": pos["pos_id"], "kind": kind}

        # ── Phase 2 audit-only path ───────────────────────────────────────
        # When active TP limits are placed at open time, channel
        # close_partial messages are post-hoc announcements of fills the
        # exchange should have already captured. Calling ft_force_exit
        # market here would double-exit (limit filled or about-to-fill +
        # market reduce). Force a reconcile FIRST (in case the limit just
        # filled and we haven't ticked), then audit-only if any Phase 2
        # rows exist for this position (pending/active/filled). close_full
        # still goes through the market path so explicit "close all" /
        # SL-hit messages from the channel are honored.
        phase2_audit_only = False
        if kind == "close_partial" and cfg.active_tp_limits:
            try:
                await _reconcile_target_orders(
                    cfg, conn,
                    session=getattr(app.state, "ft_session", None),
                )
            except Exception as e:
                logger.warning("inline reconcile before close_partial failed: %s", e)
            phase2_rows = conn.execute(
                "SELECT COUNT(*) FROM target_orders WHERE pos_id=? "
                "AND state IN ('pending','active','filled')",
                (pos["pos_id"],),
            ).fetchone()[0]
            if phase2_rows > 0:
                phase2_audit_only = True
                logger.info(
                    "[%s AUDIT-ONLY] msg_id=%d pos_id=%d — %d Phase 2 target_orders "
                    "exist; channel target-hit is post-hoc, NOT calling ft_force_exit",
                    kind.upper(), msg_id, pos["pos_id"], phase2_rows,
                )
                conn.execute(
                    "UPDATE events SET response = ? "
                    "WHERE pos_id = ? AND msg_id = ? AND kind = ?",
                    (json.dumps({"status": "audit_only",
                                 "reason": "active_tp_limits"}),
                     pos["pos_id"], msg_id, kind),
                )
                return {"action": "audit_only",
                        "pos_id": pos["pos_id"], "kind": kind,
                        "reason": "active_tp_limits",
                        "phase2_rows": phase2_rows}

        resp = await ft_force_exit(
            cfg, pos["ft_trade_id"], pct=close_pct_of_remaining,
            session=getattr(app.state, "ft_session", None),
        )
        # Patch the claim row with the real FT response.
        conn.execute(
            "UPDATE events SET response = ? "
            "WHERE pos_id = ? AND msg_id = ? AND kind = ?",
            (json.dumps(resp), pos["pos_id"], msg_id, kind),
        )

        ft_ok = 200 <= resp["status"] < 300
        new_pct_open = pct_remaining_before
        if ft_ok:
            new_pct_open = max(0.0, round(pct_remaining_before - close_pp_of_original, 4))

        if ft_ok and new_pct_open <= FULL_CLOSE_RESIDUAL_PCT:
            new_state = "closed"
            conn.execute(
                "UPDATE positions SET state = ?, pct_open = 0, "
                "close_msg_id = ?, close_date = ?, close_reason = ?, "
                "last_event_at = ? WHERE pos_id = ?",
                (new_state, msg_id, str(msg.get("date")),
                 kind, datetime.now(timezone.utc).isoformat(), pos["pos_id"]),
            )
            # Phase 2: market exit on close_full implicitly closes the
            # position on FT's side, which the exchange interprets as
            # cancellation of any pending LIMIT exit orders attached to
            # this trade. Mark our local target_orders rows accordingly
            # so the reconciler doesn't keep polling cancelled orders.
            conn.execute(
                "UPDATE target_orders SET state='cancelled', "
                "notes=COALESCE(notes,'') || ' | position-closed', "
                "last_check_at=? WHERE pos_id=? AND state IN ('pending','active')",
                (datetime.now(timezone.utc).isoformat(), pos["pos_id"]),
            )
        elif ft_ok:
            # Partial succeeded; position stays open with reduced size.
            new_state = pos["state"]  # 'open' stays 'open'
            conn.execute(
                "UPDATE positions SET pct_open = ?, last_event_at = ? "
                "WHERE pos_id = ?",
                (new_pct_open, datetime.now(timezone.utc).isoformat(),
                 pos["pos_id"]),
            )
        else:
            # FT rejected/failed: do NOT mutate state or pct_open. Reconciler
            # or operator handles divergence.
            new_state = pos["state"]
            logger.error(
                "[%s FAILED] pos_id=%d signal=#%s %s ft_trade_id=%d "
                "→ ft_status=%d body=%s — state/pct_open NOT mutated",
                kind.upper(), pos["pos_id"], signal_id, symbol,
                pos["ft_trade_id"], resp["status"], resp.get("body", "")[:200],
            )

        if ft_ok:
            logger.info(
                "[%s] pos_id=%d signal=#%s %s ft_trade_id=%d "
                "close=%.1fpp of original (=%.1f%% of remainder %.1f%%) "
                "→ new pct_open=%.1f%% state=%s",
                kind.upper(), pos["pos_id"], signal_id, symbol,
                pos["ft_trade_id"], close_pp_of_original,
                close_pct_of_remaining, pct_remaining_before,
                new_pct_open, new_state,
            )
        return {"action": "force_exit",
                "pos_id": pos["pos_id"],
                "ft": resp,
                "pct_closed_of_original": close_pp_of_original,
                "pct_open_after": new_pct_open,
                "kind": kind}

    if kind == "move_sl":
        # MVP: log only. Freqtrade lacks a clean REST hook for mid-trade SL
        # adjustment; would need a strategy custom_stoploss + side-channel
        # signal table. Defer to Phase 2.
        return {"action": "logged", "reason": "move_sl not executed in MVP"}

    if kind == "increase":
        return {"action": "logged", "reason": "increase not executed in MVP"}

    return {"action": "ignored", "reason": f"unknown_kind:{kind}"}
