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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
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
    last_event_at   TEXT
);
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pos_id      INTEGER REFERENCES positions(pos_id),
    msg_id      INTEGER NOT NULL,
    event_at    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT,
    response    TEXT
);
CREATE INDEX IF NOT EXISTS idx_pos_signal_symbol ON positions(signal_id, symbol);
CREATE INDEX IF NOT EXISTS idx_pos_state ON positions(state);
"""


def init_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(POSITION_SCHEMA)
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
    cfg: Config, pair: str, direction: str, stake: float, leverage: float
) -> dict:
    """POST /forceenter to the killers Freqtrade bot. Returns response dict.

    Per Freqtrade docs: side is 'long' or 'short'; stakeamount in quote currency;
    leverage as float; ordertype 'market' for immediate fills (matches config).
    """
    url = f"{cfg.ft_base}/api/v1/forceenter"
    body = {
        "pair": pair,
        "side": direction,
        "stakeamount": round(stake, 2),
        "leverage": leverage,
        "ordertype": "market",
    }
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, json=body, auth=auth,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}


async def ft_force_exit(cfg: Config, trade_id: int, pct: Optional[float] = None) -> dict:
    """POST /forceexit. Pct truncates the exit amount for partial closes."""
    url = f"{cfg.ft_base}/api/v1/forceexit"
    body: dict[str, Any] = {"tradeid": str(trade_id), "ordertype": "market"}
    if pct is not None:
        # Freqtrade accepts "amount" as base-currency size; without it, exits
        # the whole position. For pct partials we'd need to query the trade's
        # current amount, multiply by pct/100, and pass amount. Skipping in MVP.
        pass
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, json=body, auth=auth,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            txt = await r.text()
            return {"status": r.status, "body": txt}


async def ft_get_trade(cfg: Config, trade_id: int) -> Optional[dict]:
    url = f"{cfg.ft_base}/api/v1/trade/{trade_id}"
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, auth=auth, timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        logger.warning("ft_get_trade failed: %s", e)
    return None


async def ft_open_trades(cfg: Config) -> list[dict]:
    url = f"{cfg.ft_base}/api/v1/status"
    auth = aiohttp.BasicAuth(cfg.ft_user, cfg.ft_pass)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, auth=auth, timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        logger.warning("ft_open_trades failed: %s", e)
    return []


# ── HTTP API ───────────────────────────────────────────────────────────────


class EventPayload(BaseModel):
    msg: dict
    classification: dict


async def reconcile_loop(cfg: Config, conn: sqlite3.Connection) -> None:
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
            ft_open = await ft_open_trades(cfg)
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
    logger.info(
        "receiver up ft=%s db=%s stake=$%.0f lev=%.1fx max_open=%d",
        cfg.ft_base, cfg.db_path, cfg.stake_usd, cfg.leverage, cfg.max_open,
    )
    recon = asyncio.create_task(reconcile_loop(cfg, conn))
    try:
        yield
    finally:
        recon.cancel()


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


async def _notify_telegram(cfg: Config, text: str) -> None:
    """Best-effort POST to trade-webhook /test/notify → @elder_brain_bot.
    Silent on failure; observability shouldn't block the signal pipeline."""
    if not cfg.notify_url:
        return
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            await session.post(cfg.notify_url, json={"text": text})
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
        return f"📈 {head} OPEN  · #{sig} {sym} {direc}  · pos={pos} ft_status={ft}"
    if action == "force_exit":
        pos = result.get("pos_id", "?")
        ft  = (result.get("ft") or {}).get("status", "?")
        verb = "CLOSE_PARTIAL" if kind == "close_partial" else "CLOSE_FULL"
        return f"📉 {head} {verb} · #{sig} {sym}  · pos={pos} ft_status={ft}"
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
        # Fire-and-forget Telegram alert; never block the response on it.
        await _notify_telegram(cfg, text)
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

        # Insert tentative position record BEFORE the REST call so we have audit
        # spine even if the call fails. UNIQUE constraint on open_msg_id makes
        # this idempotent — duplicate event delivery returns the existing row.
        try:
            cur = conn.execute(
                "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
                " open_msg_id, open_date, stake_usd, leverage, sl_distance_pct, last_event_at) "
                "VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?)",
                (signal_id, symbol, pair, direction, msg_id, str(msg.get("date")),
                 stake, leverage, sl_dist, datetime.now(timezone.utc).isoformat()),
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
        resp = await ft_force_enter(cfg, pair, direction, stake, leverage)
        conn.execute(
            "INSERT INTO events (pos_id, msg_id, event_at, kind, payload, response) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (pos_id, msg_id, datetime.now(timezone.utc).isoformat(),
             json.dumps({"pair": pair, "side": direction, "stake": stake, "leverage": leverage}),
             json.dumps(resp)),
        )

        # Try to extract Freqtrade trade_id from the response body
        ft_trade_id = None
        try:
            body = json.loads(resp["body"])
            ft_trade_id = body.get("trade_id") or body.get("tradeid")
        except Exception:
            pass

        new_state = "open" if (200 <= resp["status"] < 300) else "failed"
        conn.execute(
            "UPDATE positions SET state = ?, ft_trade_id = ?, last_event_at = ? "
            "WHERE pos_id = ?",
            (new_state, ft_trade_id, datetime.now(timezone.utc).isoformat(), pos_id),
        )
        logger.info(
            "[OPEN] pos_id=%d signal=#%s %s %s pair=%s stake=$%.0f lev=%.1fx → ft_status=%d ft_trade_id=%s",
            pos_id, signal_id, symbol, direction.upper(), pair, stake, leverage,
            resp["status"], ft_trade_id,
        )
        return {"action": "force_enter", "pos_id": pos_id, "ft": resp}

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

        resp = await ft_force_exit(cfg, pos["ft_trade_id"])
        conn.execute(
            "INSERT INTO events (pos_id, msg_id, event_at, kind, payload, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pos["pos_id"], msg_id, datetime.now(timezone.utc).isoformat(),
             kind, json.dumps({"ft_trade_id": pos["ft_trade_id"]}),
             json.dumps(resp)),
        )
        new_state = "closed" if (200 <= resp["status"] < 300) else pos["state"]
        conn.execute(
            "UPDATE positions SET state = ?, close_msg_id = ?, close_date = ?, "
            "close_reason = ?, last_event_at = ? WHERE pos_id = ?",
            (new_state, msg_id, str(msg.get("date")), kind,
             datetime.now(timezone.utc).isoformat(), pos["pos_id"]),
        )
        logger.info(
            "[%s] pos_id=%d signal=#%s %s ft_trade_id=%d → ft_status=%d",
            kind.upper(), pos["pos_id"], signal_id, symbol,
            pos["ft_trade_id"], resp["status"],
        )
        return {"action": "force_exit", "pos_id": pos["pos_id"], "ft": resp}

    if kind == "move_sl":
        # MVP: log only. Freqtrade lacks a clean REST hook for mid-trade SL
        # adjustment; would need a strategy custom_stoploss + side-channel
        # signal table. Defer to Phase 2.
        return {"action": "logged", "reason": "move_sl not executed in MVP"}

    if kind == "increase":
        return {"action": "logged", "reason": "increase not executed in MVP"}

    return {"action": "ignored", "reason": f"unknown_kind:{kind}"}
