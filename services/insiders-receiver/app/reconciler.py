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

from .executor import FreqtradeClient
from .position_graph import PositionGraph

logger = logging.getLogger(__name__)


async def reconcile_once(graph: PositionGraph, ft: FreqtradeClient) -> dict:
    """Single reconciliation pass. Returns a summary dict for monitoring."""
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "graph_open": 0,
        "ft_open": 0,
        "matched": 0,
        "graph_only": [],   # graph thinks open, FT doesn't
        "ft_only": [],      # FT has it, graph doesn't
    }

    graph_positions = graph.open_positions()
    summary["graph_open"] = len(graph_positions)

    try:
        ft_trades = await ft.get_open_trades()
    except Exception as e:
        logger.error("reconcile: freqtrade fetch failed: %s", e)
        summary["error"] = str(e)
        return summary

    summary["ft_open"] = len(ft_trades)

    # Match by freqtrade_trade_id where available
    ft_by_id = {t["trade_id"]: t for t in ft_trades}
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
        logger.info("reconcile clean: %d positions matched", summary["matched"])

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
