"""Virtual position state machine for Binance Killers VIP signals.

Mirrors Eduardo's risk-budget sizing rule for cross-channel consistency:
  position_notional = $10 / sl_distance_pct  (1% risk on $1k account)
  leverage          = position_notional / $50 margin per trade

No real fills; we treat the entry-range midpoint as fill at signal-post
time. SL/TP tracking happens via the channel's own published updates
(target hits + Profit% lines + bare CLOSE / stop-loss-hit messages).

When the channel publishes "🔥X% Profit (Yx)🔥", we extract X as the
cumulative realized % on the trade and update the paper position.
"""
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

ACCOUNT = 1000.0
RISK_USD = 10.0
MARGIN_USD = 50.0

PCT_RE = re.compile(r"([+\-]?\d+(?:\.\d+)?)\s*%")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_published_pct(notes: str) -> Optional[float]:
    """Largest-magnitude % in notes (Killers publishes cumulative profit there)."""
    if not notes:
        return None
    pcts = [float(m.group(1)) for m in PCT_RE.finditer(notes)]
    return max(pcts, key=abs) if pcts else None


def find_active_position(conn: sqlite3.Connection, signal_id: int, symbol: str) -> Optional[dict]:
    """Most-recent OPEN or PENDING position for this (signal_id, symbol)."""
    row = conn.execute(
        "SELECT * FROM paper_positions "
        "WHERE signal_id = ? AND symbol = ? AND state IN ('pending', 'open') "
        "ORDER BY open_date DESC LIMIT 1",
        (signal_id, symbol),
    ).fetchone()
    return dict(row) if row else None


def open_paper_position(conn: sqlite3.Connection, msg: dict, classification: dict) -> Optional[dict]:
    """Materialize a paper position from an 'open' classification."""
    sym = classification.get("symbol")
    direction = classification.get("direction")
    if not sym or not direction:
        return None

    entry_range = classification.get("entry_range")
    entry = classification.get("entry")
    if entry_range and isinstance(entry_range, list) and len(entry_range) == 2:
        try:
            lo, hi = float(entry_range[0]), float(entry_range[1])
        except (TypeError, ValueError):
            lo = hi = None
    elif isinstance(entry, (int, float)):
        lo = hi = float(entry)
    else:
        lo = hi = None

    entry_mid = (lo + hi) / 2 if (lo is not None and hi is not None) else None

    sl_val = classification.get("sl")
    sl_num = float(sl_val) if isinstance(sl_val, (int, float)) else None
    sl_str = sl_val if isinstance(sl_val, str) else None

    sl_dist_pct = None
    pos_notional = None
    leverage = None
    if entry_mid and sl_num:
        sl_dist_pct = abs(entry_mid - sl_num) / entry_mid
        if sl_dist_pct > 0:
            pos_notional = RISK_USD / sl_dist_pct
            leverage = pos_notional / MARGIN_USD

    cur = conn.execute(
        "INSERT INTO paper_positions "
        "(signal_id, symbol, direction, state, open_msg_id, open_date, "
        " entry_lo, entry_hi, entry_mid, sl, sl_distance_pct, "
        " position_notional, leverage, last_event_at) "
        "VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            classification.get("signal_id"),
            sym, direction,
            msg["id"], str(msg["date"]),
            lo, hi, entry_mid,
            sl_num, sl_dist_pct,
            pos_notional, leverage,
            now_iso(),
        ),
    )
    conn.commit()
    pos_id = cur.lastrowid

    logger.info(
        "[OPEN] pos_id=%d signal=#%s %s %s entry=%s sl=%s lev=%.1fx notional=$%.0f",
        pos_id, classification.get("signal_id"), sym, direction.upper(),
        f"{entry_mid:.4g}" if entry_mid else "?",
        f"{sl_num:.4g}" if sl_num else (sl_str or "?"),
        leverage or 0, pos_notional or 0,
    )
    return {"pos_id": pos_id, "entry_mid": entry_mid, "sl": sl_num,
            "leverage": leverage, "position_notional": pos_notional}


def update_paper_position(
    conn: sqlite3.Connection, msg: dict, classification: dict,
) -> Optional[dict]:
    """Apply a close_partial / close_full / move_sl event to an active position."""
    sid = classification.get("signal_id")
    sym = classification.get("symbol")
    if not sid or not sym:
        return None
    pos = find_active_position(conn, sid, sym)
    if not pos:
        logger.info(
            "[ORPHAN] msg=%d kind=%s signal=#%s %s — no matching active position",
            msg["id"], classification.get("kind"), sid, sym,
        )
        return None

    kind = classification.get("kind")
    notes = classification.get("notes", "")
    pct = extract_published_pct(notes)

    # Record event
    conn.execute(
        "INSERT INTO position_events (pos_id, msg_id, event_at, kind, pct, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pos["pos_id"], msg["id"], str(msg["date"]), kind, pct, notes[:500]),
    )

    if kind == "close_partial":
        # Update max realized %
        new_max = max(abs(pos.get("realized_pct") or 0), abs(pct or 0))
        new_max_signed = pct if pct and abs(pct) > abs(pos.get("realized_pct") or 0) else pos.get("realized_pct")
        if pos.get("position_notional"):
            realized_pnl = MARGIN_USD * (new_max_signed or 0) / 100
            conn.execute(
                "UPDATE paper_positions SET realized_pct = ?, realized_pnl = ?, "
                "last_event_at = ? WHERE pos_id = ?",
                (new_max_signed, round(realized_pnl, 2), now_iso(), pos["pos_id"]),
            )
        logger.info(
            "[PARTIAL] pos_id=%d signal=#%s %s realized=%s%%",
            pos["pos_id"], sid, sym,
            f"{new_max_signed:+.2f}" if new_max_signed is not None else "?",
        )

    elif kind == "close_full":
        is_sl = (pct is not None and pct < 0) or "sl" in notes.lower() or "stop" in notes.lower()
        final_pct = pct if pct is not None else pos.get("realized_pct")
        realized_pnl = MARGIN_USD * (final_pct or 0) / 100 if pos.get("position_notional") else None
        conn.execute(
            "UPDATE paper_positions SET state = 'closed', close_msg_id = ?, "
            "close_date = ?, close_reason = ?, realized_pct = ?, realized_pnl = ?, "
            "last_event_at = ? WHERE pos_id = ?",
            (
                msg["id"], str(msg["date"]),
                "sl_hit" if is_sl else "tp_or_manual",
                final_pct, round(realized_pnl, 2) if realized_pnl is not None else None,
                now_iso(), pos["pos_id"],
            ),
        )
        logger.info(
            "[CLOSED] pos_id=%d signal=#%s %s reason=%s final=%s%%",
            pos["pos_id"], sid, sym,
            "SL" if is_sl else "TP/manual",
            f"{final_pct:+.2f}" if final_pct is not None else "?",
        )

    elif kind == "move_sl":
        new_sl = classification.get("sl")
        sl_num = float(new_sl) if isinstance(new_sl, (int, float)) else None
        if sl_num:
            conn.execute(
                "UPDATE paper_positions SET sl = ?, last_event_at = ? WHERE pos_id = ?",
                (sl_num, now_iso(), pos["pos_id"]),
            )
            logger.info("[MOVE-SL] pos_id=%d signal=#%s %s new_sl=%g",
                        pos["pos_id"], sid, sym, sl_num)
        elif new_sl == "breakeven" and pos.get("entry_mid"):
            conn.execute(
                "UPDATE paper_positions SET sl = ?, last_event_at = ? WHERE pos_id = ?",
                (pos["entry_mid"], now_iso(), pos["pos_id"]),
            )
            logger.info("[MOVE-SL] pos_id=%d signal=#%s %s new_sl=BE(%g)",
                        pos["pos_id"], sid, sym, pos["entry_mid"])

    conn.commit()
    return {"pos_id": pos["pos_id"]}
