"""Reconciliation loop — pull Freqtrade state every N seconds, compare to
the position graph, repair mismatches by alerting + logging.

Codex: *"The worst failure is not 'missed trade'; it is believing you are
flat when Binance has exposure."*

We do NOT auto-close mismatches. We ALERT them, the user/operator decides.
A divergence means our model of state is wrong — closing without
understanding why could compound the damage.
"""
import asyncio
import logging
from datetime import datetime, timezone

from .executor import FreqtradeClient, pair_for_symbol
from .position_graph import PositionGraph

logger = logging.getLogger(__name__)


# Orphans younger than this are NOT auto-linked — they could still be
# in-flight inside _handle_open between /forceenter return and the
# graph.finalize_requested_position call. We want the orphan to survive
# at least one round-trip + a margin before the reconciler claims it.
ORPHAN_LINK_MIN_AGE_SEC = 5


async def reconcile_once(graph: PositionGraph, ft: FreqtradeClient) -> dict:
    """Single reconciliation pass. Returns a summary dict for monitoring."""
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "graph_open": 0,
        "ft_open": 0,
        "matched": 0,
        "graph_only": [],   # graph thinks open, FT doesn't
        "ft_only": [],      # FT has it, graph doesn't
        "orphans_linked": 0,  # 'requested' positions back-linked to FT trades
    }

    try:
        ft_trades = await ft.get_open_trades()
    except Exception as e:
        logger.error("reconcile: freqtrade fetch failed: %s", e)
        summary["error"] = str(e)
        return summary

    summary["ft_open"] = len(ft_trades)
    ft_by_id = {t["trade_id"]: t for t in ft_trades}

    # (0) Heal 'requested' orphans — positions pre-created before /forceenter
    # whose ack we never recorded (crash, timeout, slow response). Match by
    # (pair, is_short) against currently-open FT trades that no graph row
    # claims.
    #
    # Safety rules to prevent mis-linking:
    #   - Only orphans older than ORPHAN_LINK_MIN_AGE_SEC are eligible —
    #     younger ones might still be in-flight in _handle_open.
    #   - If one orphan ↔ multiple unclaimed FT trades for the same
    #     (pair, side) OR multiple orphans ↔ one FT trade, REFUSE TO LINK
    #     and surface the ambiguity. We'd rather page the operator than
    #     attach the wrong position to the wrong exchange exposure.
    #   - Otherwise: deterministic 1-to-1 pairing by open time, oldest
    #     orphan ↔ oldest FT trade.
    claimed_ftids = {p.freqtrade_trade_id for p in graph.open_positions()
                     if p.freqtrade_trade_id is not None}
    ft_unclaimed_by_pair: dict[tuple[str, bool], list[dict]] = {}
    for t in ft_trades:
        if t["trade_id"] in claimed_ftids:
            continue
        key = (t.get("pair"), bool(t.get("is_short")))
        ft_unclaimed_by_pair.setdefault(key, []).append(t)
    # Sort each bucket by open_date ascending (oldest first) for
    # deterministic pairing with the (also ASC-ordered) orphan list.
    for bucket in ft_unclaimed_by_pair.values():
        bucket.sort(key=lambda t: t.get("open_date") or t.get("open_timestamp") or "")

    # Group orphans by (pair, is_short) so we can detect ambiguity.
    orphans_by_pair: dict[tuple[str, bool], list] = {}
    for orphan in graph.requested_orphans(older_than_seconds=ORPHAN_LINK_MIN_AGE_SEC):
        key = (pair_for_symbol(orphan.symbol), orphan.direction == "short")
        orphans_by_pair.setdefault(key, []).append(orphan)

    summary["orphans_ambiguous"] = []
    for key, orphan_list in orphans_by_pair.items():
        bucket = ft_unclaimed_by_pair.get(key, [])
        if not bucket:
            continue
        if len(orphan_list) > 1 and len(bucket) > 1:
            # Both sides plural → can't be sure which goes with which.
            # Refuse to link and surface the ambiguity for operator review.
            logger.error(
                "RECONCILE: AMBIGUOUS orphan pairing for %s side=%s "
                "(%d orphans vs %d unclaimed FT trades) — NOT linking",
                key[0], "short" if key[1] else "long",
                len(orphan_list), len(bucket),
            )
            summary["orphans_ambiguous"].append({
                "pair": key[0], "is_short": key[1],
                "orphan_count": len(orphan_list),
                "ft_unclaimed_count": len(bucket),
                "orphan_position_ids": [o.position_id for o in orphan_list],
                "ft_trade_ids": [t["trade_id"] for t in bucket],
            })
            continue
        if len(orphan_list) > 1 and len(bucket) == 1:
            # Many orphans, one FT trade — can't attribute the FT trade
            # to a specific orphan. Refuse.
            logger.error(
                "RECONCILE: %d orphans for %s side=%s but only 1 unclaimed "
                "FT trade — NOT linking (ambiguous attribution)",
                len(orphan_list), key[0], "short" if key[1] else "long",
            )
            summary["orphans_ambiguous"].append({
                "pair": key[0], "is_short": key[1],
                "orphan_count": len(orphan_list),
                "ft_unclaimed_count": 1,
                "orphan_position_ids": [o.position_id for o in orphan_list],
                "ft_trade_ids": [bucket[0]["trade_id"]],
            })
            continue
        if len(orphan_list) == 1 and len(bucket) > 1:
            # ONE orphan but MULTIPLE unclaimed FT trades on same
            # (pair, side). Could be a manual trade, a stale unclosed
            # position, or another bot's trade — picking "oldest" risks
            # back-linking to the wrong exposure. Refuse and surface
            # so the operator can investigate.
            logger.error(
                "RECONCILE: 1 orphan for %s side=%s but %d unclaimed FT "
                "trades — NOT linking (cannot disambiguate without "
                "stake/amount correlation)",
                key[0], "short" if key[1] else "long", len(bucket),
            )
            summary["orphans_ambiguous"].append({
                "pair": key[0], "is_short": key[1],
                "orphan_count": 1,
                "ft_unclaimed_count": len(bucket),
                "orphan_position_ids": [orphan_list[0].position_id],
                "ft_trade_ids": [t["trade_id"] for t in bucket],
            })
            continue
        # Only unambiguous case: exactly 1 orphan AND exactly 1 unclaimed
        # FT trade for this (pair, side). Auto-link.
        ft_trade = bucket[0]
        orphan = orphan_list[0]
        try:
            graph.finalize_requested_position(
                orphan.position_id, ft_trade_id=ft_trade["trade_id"]
            )
        except ValueError as e:
            # Last-write race: another path (manual link, parallel
            # reconcile) claimed the ft_trade_id between our claimed_ftids
            # snapshot and the finalize. Don't crash the whole pass —
            # surface and continue with the next bucket.
            logger.error(
                "RECONCILE: finalize race for position_id=%d → ft_trade_id=%d: %s",
                orphan.position_id, ft_trade["trade_id"], e,
            )
            summary["orphans_ambiguous"].append({
                "pair": key[0], "is_short": key[1],
                "orphan_count": 1, "ft_unclaimed_count": 1,
                "orphan_position_ids": [orphan.position_id],
                "ft_trade_ids": [ft_trade["trade_id"]],
                "race_error": str(e),
            })
            continue
        summary["orphans_linked"] += 1
        logger.warning(
            "RECONCILE: orphan position_id=%d %s %s back-linked to ft_trade_id=%d",
            orphan.position_id, orphan.symbol, orphan.direction,
            ft_trade["trade_id"],
        )

    # Refresh open positions AFTER orphan linking
    graph_positions = graph.open_positions()
    summary["graph_open"] = len(graph_positions)

    graph_by_ftid = {p.freqtrade_trade_id: p for p in graph_positions
                     if p.freqtrade_trade_id is not None}

    for ftid, ft_trade in ft_by_id.items():
        if ftid in graph_by_ftid:
            summary["matched"] += 1
        else:
            summary["ft_only"].append({
                "ft_trade_id": ftid,
                "pair": ft_trade.get("pair"),
                "amount": ft_trade.get("amount"),
                "open_rate": ft_trade.get("open_rate"),
            })

    for p in graph_positions:
        if p.freqtrade_trade_id is None:
            # No FT id yet — order maybe still being placed. Skip.
            continue
        if p.freqtrade_trade_id not in ft_by_id:
            summary["graph_only"].append({
                "position_id": p.position_id,
                "symbol": p.symbol,
                "direction": p.direction,
                "ft_trade_id": p.freqtrade_trade_id,
            })

    if summary["graph_only"] or summary["ft_only"]:
        logger.error(
            "RECONCILE MISMATCH: graph_only=%d ft_only=%d. Details: %s",
            len(summary["graph_only"]), len(summary["ft_only"]), summary,
        )
    else:
        logger.info("reconcile clean: %d positions matched (%d orphans linked)",
                    summary["matched"], summary["orphans_linked"])

    return summary


async def reconcile_loop(graph: PositionGraph, ft: FreqtradeClient,
                         interval_sec: int = 30):
    """Background task — runs reconcile_once every interval_sec."""
    logger.info("reconcile loop starting, interval=%ds", interval_sec)
    while True:
        try:
            await reconcile_once(graph, ft)
        except Exception as e:
            logger.exception("reconcile loop iteration crashed: %s", e)
        await asyncio.sleep(interval_sec)


# ── Stuck-position alerting ──────────────────────────────────────────────


def find_stuck_positions(graph: PositionGraph, stuck_after_hours: int = 72) -> list:
    """Positions open with NO management action for `stuck_after_hours`."""
    cutoff = datetime.now(timezone.utc).timestamp() - stuck_after_hours * 3600
    rows = graph.conn.execute(
        """
        SELECT p.position_id, p.symbol, p.direction, p.opened_at,
               (SELECT MAX(applied_at) FROM position_actions
                WHERE position_id = p.position_id) AS last_action
        FROM positions p
        WHERE status = 'open'
        """
    ).fetchall()
    stuck = []
    for r in rows:
        last = r["last_action"] or r["opened_at"]
        try:
            last_ts = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if last_ts < cutoff:
            stuck.append(dict(r))
    return stuck
