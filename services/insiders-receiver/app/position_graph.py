"""Position graph — codex's "actual core product."

Every Telegram message+classification creates events. Every event RECONCILES
against the current position graph before execution. The graph is
sqlite-backed, append-only audit-style, plus a derived "open positions" view.

Schemas:

    raw_events                   — every classified message we ingested
    positions                    — open positions (one row per active trade)
    position_actions             — every action applied to a position (open,
                                   close_partial, move_sl, increase)
    msg_to_position              — many-to-one: which msg(s) opened or affect
                                   which position

The graph answers questions like:
  - "which position does this 'close 30%' message apply to?"
  - "what's the current SL for our ETH SHORT?"
  - "has msg_id N already been processed?" (idempotency)
  - "what was the reply-chain ancestry of this management message?"

NO trading decisions are made here — just graph queries + state updates.
Execution lives in the freqtrade_executor.
"""
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Schema ─────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    msg_id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    posted_at TEXT,
    edited_at TEXT,
    reply_to_msg_id INTEGER,
    classifier TEXT NOT NULL,           -- 'rule' or 'claude' or 'hybrid'
    classification_json TEXT NOT NULL,  -- full structured classifier output
    raw_text TEXT,
    instance_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,            -- 'long' or 'short'
    opened_at TEXT NOT NULL,
    opened_by_msg_id INTEGER NOT NULL,
    open_entry REAL,                    -- as filled, or None for market
    open_sl REAL NOT NULL,              -- initial stop (every position MUST have)
    open_tp REAL,                       -- initial TP (may be None)
    current_sl REAL NOT NULL,           -- live SL (updated by move_sl events)
    current_tp REAL,                    -- live TP
    pct_open REAL NOT NULL DEFAULT 100, -- 100 = full, 50 = half closed, etc.
    status TEXT NOT NULL DEFAULT 'open', -- 'open', 'closed', 'rejected'
    closed_at TEXT,
    closed_by_msg_id INTEGER,
    freqtrade_trade_id INTEGER,         -- the FT trade_id once order fills
    stake_usdt REAL,
    leverage REAL,
    instance_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status, symbol);
CREATE INDEX IF NOT EXISTS idx_positions_opened_by ON positions(opened_by_msg_id);

CREATE TABLE IF NOT EXISTS position_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    msg_id INTEGER NOT NULL,
    applied_at TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- 'open','close_full','close_partial','move_sl','increase'
    detail_json TEXT NOT NULL,
    executor_result TEXT,               -- raw response from freqtrade / 'skipped' / 'failed:reason'
    FOREIGN KEY(position_id) REFERENCES positions(position_id),
    UNIQUE(msg_id, position_id, kind)   -- idempotency: same (msg, position, kind) only once
);
CREATE INDEX IF NOT EXISTS idx_actions_position ON position_actions(position_id);
CREATE INDEX IF NOT EXISTS idx_actions_msg ON position_actions(msg_id);

CREATE TABLE IF NOT EXISTS msg_to_position (
    -- many-to-one helper: when a single management message hits multiple
    -- positions (multi-coin fan-out), record all linkages here.
    msg_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    relation TEXT NOT NULL,             -- 'opens', 'manages', 'closes'
    PRIMARY KEY (msg_id, position_id, relation)
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- Common keys: 'entries_paused' ('1'/'0'), 'last_reconcile_at', 'instance_id'
"""


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class Position:
    position_id: int
    symbol: str
    direction: str  # 'long' / 'short'
    opened_at: str
    opened_by_msg_id: int
    open_entry: Optional[float]
    open_sl: float
    open_tp: Optional[float]
    current_sl: float
    current_tp: Optional[float]
    pct_open: float
    status: str
    closed_at: Optional[str]
    closed_by_msg_id: Optional[int]
    freqtrade_trade_id: Optional[int]
    stake_usdt: Optional[float]
    leverage: Optional[float]
    instance_id: str


# ── Connection helper ──────────────────────────────────────────────────────


class PositionGraph:
    def __init__(self, db_path: str, instance_id: str):
        self.db_path = db_path
        self.instance_id = instance_id
        self.conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self):
        """SQLite implicit transactions via BEGIN/COMMIT for atomic updates."""
        try:
            self.conn.execute("BEGIN")
            yield
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ── Idempotency ──────────────────────────────────────────────────────

    def msg_seen(self, msg_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM raw_events WHERE msg_id = ?", (msg_id,)
        ).fetchone()
        return row is not None

    def action_seen(self, msg_id: int, position_id: int, kind: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM position_actions WHERE msg_id=? AND position_id=? AND kind=?",
            (msg_id, position_id, kind),
        ).fetchone()
        return row is not None

    # ── Event ingestion ──────────────────────────────────────────────────

    def record_raw_event(
        self, msg_id: int, classifier: str, classification: dict,
        raw_text: str = "", posted_at: str = None, edited_at: str = None,
        reply_to_msg_id: int = None,
    ) -> None:
        import json
        self.conn.execute(
            "INSERT OR IGNORE INTO raw_events "
            "(msg_id, received_at, posted_at, edited_at, reply_to_msg_id, "
            " classifier, classification_json, raw_text, instance_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                msg_id,
                datetime.now(timezone.utc).isoformat(),
                posted_at,
                edited_at,
                reply_to_msg_id,
                classifier,
                json.dumps(classification),
                raw_text,
                self.instance_id,
            ),
        )

    # ── Position lifecycle ───────────────────────────────────────────────

    def open_position(
        self, *, symbol: str, direction: str, opened_by_msg_id: int,
        open_entry: Optional[float], open_sl: float, open_tp: Optional[float],
        stake_usdt: Optional[float] = None, leverage: Optional[float] = None,
        freqtrade_trade_id: Optional[int] = None,
    ) -> int:
        """Create a new open position. Returns position_id.

        Caller must have already verified this isn't a duplicate via
        action_seen(opened_by_msg_id, ?, 'open').
        """
        direction = direction.lower()
        if direction not in ("long", "short"):
            raise ValueError(f"bad direction: {direction!r}")
        with self._tx():
            cur = self.conn.execute(
                "INSERT INTO positions "
                "(symbol, direction, opened_at, opened_by_msg_id, open_entry, "
                " open_sl, open_tp, current_sl, current_tp, pct_open, status, "
                " freqtrade_trade_id, stake_usdt, leverage, instance_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,100,'open',?,?,?,?)",
                (
                    symbol.upper(), direction,
                    datetime.now(timezone.utc).isoformat(),
                    opened_by_msg_id, open_entry, open_sl, open_tp,
                    open_sl, open_tp,
                    freqtrade_trade_id, stake_usdt, leverage, self.instance_id,
                ),
            )
            position_id = cur.lastrowid
            self.conn.execute(
                "INSERT OR IGNORE INTO msg_to_position (msg_id, position_id, relation) "
                "VALUES (?, ?, 'opens')",
                (opened_by_msg_id, position_id),
            )
            logger.info(
                "opened position %d: %s %s entry=%s sl=%s tp=%s by msg %s",
                position_id, symbol, direction, open_entry, open_sl, open_tp,
                opened_by_msg_id,
            )
        return position_id

    def update_position_freqtrade_id(self, position_id: int, ft_trade_id: int) -> None:
        self.conn.execute(
            "UPDATE positions SET freqtrade_trade_id = ? WHERE position_id = ?",
            (ft_trade_id, position_id),
        )

    def move_sl(self, position_id: int, new_sl: float, msg_id: int) -> None:
        with self._tx():
            self.conn.execute(
                "UPDATE positions SET current_sl = ? WHERE position_id = ?",
                (new_sl, position_id),
            )
            self._record_action(position_id, msg_id, "move_sl",
                                {"new_sl": new_sl})

    def close_partial(self, position_id: int, pct: float, msg_id: int) -> float:
        """Reduce pct_open by `pct` percentage-points (0–100). Returns new pct_open."""
        row = self.conn.execute(
            "SELECT pct_open FROM positions WHERE position_id = ? AND status = 'open'",
            (position_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"position {position_id} not found or not open")
        new_pct = max(0, row["pct_open"] - pct)
        with self._tx():
            if new_pct <= 0.5:  # treat <0.5% as full close
                self.conn.execute(
                    "UPDATE positions SET pct_open=0, status='closed', closed_at=?, closed_by_msg_id=? "
                    "WHERE position_id = ?",
                    (datetime.now(timezone.utc).isoformat(), msg_id, position_id),
                )
            else:
                self.conn.execute(
                    "UPDATE positions SET pct_open = ? WHERE position_id = ?",
                    (new_pct, position_id),
                )
            self._record_action(position_id, msg_id, "close_partial",
                                {"pct_closed": pct, "remaining_pct": new_pct})
        return new_pct

    def close_full(self, position_id: int, msg_id: int) -> None:
        with self._tx():
            self.conn.execute(
                "UPDATE positions SET pct_open=0, status='closed', closed_at=?, closed_by_msg_id=? "
                "WHERE position_id = ?",
                (datetime.now(timezone.utc).isoformat(), msg_id, position_id),
            )
            self._record_action(position_id, msg_id, "close_full", {})

    def record_increase(self, position_id: int, msg_id: int, detail: dict) -> None:
        with self._tx():
            self._record_action(position_id, msg_id, "increase", detail)

    def _record_action(self, position_id: int, msg_id: int, kind: str, detail: dict) -> None:
        import json
        self.conn.execute(
            "INSERT OR IGNORE INTO position_actions "
            "(position_id, msg_id, applied_at, kind, detail_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (position_id, msg_id,
             datetime.now(timezone.utc).isoformat(),
             kind, json.dumps(detail)),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO msg_to_position (msg_id, position_id, relation) "
            "VALUES (?, ?, 'manages')",
            (msg_id, position_id),
        )

    # ── Queries ──────────────────────────────────────────────────────────

    def open_positions(self, symbol: str = None, direction: str = None) -> list[Position]:
        sql = "SELECT * FROM positions WHERE status = 'open'"
        params = []
        if symbol:
            sql += " AND symbol = ?"; params.append(symbol.upper())
        if direction:
            sql += " AND direction = ?"; params.append(direction.lower())
        sql += " ORDER BY opened_at DESC"
        return [Position(**dict(r)) for r in self.conn.execute(sql, params).fetchall()]

    def latest_open_position(self, symbol: str, direction: str = None) -> Optional[Position]:
        """Most recently opened position for (symbol, direction)."""
        rows = self.open_positions(symbol=symbol, direction=direction)
        return rows[0] if rows else None

    def resolve_target_positions(
        self, classification: dict, reply_chain_msg_ids: list[int] = None
    ) -> list[Position]:
        """Given a management classification, return the position(s) it
        applies to.

        Resolution order (deterministic):
          1. If classification has `applies_to`: each coin → latest open
             position for that coin.
          2. If classification has `symbol`: that symbol's latest open
             position (any direction).
          3. If reply_chain_msg_ids: walk back to find the nearest
             ancestor message that's recorded as opening a position.
          4. Otherwise: empty list (caller logs & skips).
        """
        if applies_to := classification.get("applies_to"):
            out = []
            for coin in applies_to:
                p = self.latest_open_position(coin)
                if p: out.append(p)
            return out
        if symbol := classification.get("symbol"):
            p = self.latest_open_position(symbol)
            return [p] if p else []
        if reply_chain_msg_ids:
            # Walk back through reply chain looking for a message that
            # opened a position
            placeholders = ",".join("?" * len(reply_chain_msg_ids))
            rows = self.conn.execute(
                f"SELECT position_id FROM msg_to_position "
                f"WHERE msg_id IN ({placeholders}) AND relation = 'opens'",
                reply_chain_msg_ids,
            ).fetchall()
            return [self._position_by_id(r["position_id"]) for r in rows if r]
        return []

    def _position_by_id(self, position_id: int) -> Optional[Position]:
        row = self.conn.execute(
            "SELECT * FROM positions WHERE position_id = ?", (position_id,)
        ).fetchone()
        return Position(**dict(row)) if row else None

    # ── System state ─────────────────────────────────────────────────────

    def set_entries_paused(self, paused: bool, reason: str = "") -> None:
        import json
        self.conn.execute(
            "INSERT OR REPLACE INTO system_state (key, value, updated_at) "
            "VALUES ('entries_paused', ?, ?)",
            (json.dumps({"paused": bool(paused), "reason": reason}),
             datetime.now(timezone.utc).isoformat()),
        )
        logger.warning("entries_paused = %s (reason: %s)", paused, reason)

    def is_entries_paused(self) -> tuple[bool, str]:
        row = self.conn.execute(
            "SELECT value FROM system_state WHERE key = 'entries_paused'"
        ).fetchone()
        if not row:
            return False, ""
        import json
        v = json.loads(row["value"])
        return bool(v.get("paused")), v.get("reason", "")
