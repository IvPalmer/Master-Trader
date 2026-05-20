"""FastAPI receiver — Telegram event ingestion → classification →
position-graph reconciliation → Freqtrade execution.

Endpoints:
  POST /event           — listener pushes raw Telegram message + reply context
  POST /session-status  — listener heartbeat / session-lost notifications
  POST /reconcile       — manual reconcile trigger (mostly for ops)
  GET  /health          — liveness
  GET  /positions       — current open positions
  GET  /system          — system state (paused, last reconcile)
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
import aiohttp
from pydantic import BaseModel

from .classifier_dispatcher import ClaudeAgentClassifier, classify
from .executor import (
    FreqtradeClient, FreqtradeConfig, SizingConfig,
    get_mark_price, sanity_check_entry, size_position, pair_for_symbol,
)
from .position_graph import PositionGraph
from .reconciler import reconcile_loop, reconcile_once, find_stuck_positions

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────


class Config:
    def __init__(self):
        self.db_path = os.getenv("INSIDERS_DB", "/var/lib/insiders/receiver.sqlite")
        self.instance_id = os.getenv("INSIDERS_INSTANCE_ID", "unknown")
        self.reconcile_interval = int(os.getenv("INSIDERS_RECONCILE_SEC", "30"))
        self.sizing = SizingConfig(
            risk_usd=float(os.getenv("INSIDERS_RISK_USD", "2.0")),
            margin_usd=float(os.getenv("INSIDERS_MARGIN_USD", "10.0")),
            max_leverage=float(os.getenv("INSIDERS_MAX_LEVERAGE", "30")),
        )
        self.ft = FreqtradeConfig.from_env()


# ── Lifespan: init state + background tasks ───────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config()
    graph = PositionGraph(cfg.db_path, cfg.instance_id)
    ft = FreqtradeClient(cfg.ft)
    claude = ClaudeAgentClassifier()
    app.state.cfg = cfg
    app.state.graph = graph
    app.state.ft = ft
    app.state.claude = claude
    app.state.session_state = {"connected": True, "last_msg_at": None}
    logger.info("receiver up. instance=%s db=%s ft=%s",
                cfg.instance_id, cfg.db_path, cfg.ft.base_url)
    task = asyncio.create_task(reconcile_loop(graph, ft, cfg.reconcile_interval))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        graph.close()


app = FastAPI(title="insiders-receiver", lifespan=lifespan)


# ── Schemas ───────────────────────────────────────────────────────────────


class EventIn(BaseModel):
    msg_id: int
    text: str
    posted_at: Optional[str] = None
    edited_at: Optional[str] = None
    reply_to_msg_id: Optional[int] = None
    reply_chain_msg_ids: list[int] = []
    reply_chain_msgs: dict[int, dict] = {}  # {msg_id: {"text":..., ...}} for parent context


class SessionStatusIn(BaseModel):
    connected: bool
    reason: str = ""
    last_msg_at: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {
        "ok": True,
        "instance": app.state.cfg.instance_id,
        "session_connected": app.state.session_state["connected"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/event")
async def post_event(event: EventIn):
    """Main path — process a Telegram message."""
    graph: PositionGraph = app.state.graph
    cfg: Config = app.state.cfg
    claude: ClaudeAgentClassifier = app.state.claude
    ft: FreqtradeClient = app.state.ft

    # Idempotency
    if graph.msg_seen(event.msg_id):
        return {"status": "duplicate", "msg_id": event.msg_id}

    # Classify
    msg_dict = {
        "id": event.msg_id,
        "text": event.text,
        "reply_to_msg_id": event.reply_to_msg_id,
        "date": event.posted_at,
    }
    by_id = {mid: m for mid, m in event.reply_chain_msgs.items()}
    by_id[event.msg_id] = msg_dict

    # Provide open positions to classifier (Claude needs this context)
    position_context = [
        {"position_id": p.position_id, "symbol": p.symbol,
         "direction": p.direction, "opened_by_msg_id": p.opened_by_msg_id,
         "current_sl": p.current_sl, "pct_open": p.pct_open}
        for p in graph.open_positions()
    ]

    result = await classify(msg_dict, by_id, position_context, claude)
    cls = result.classification

    # Record raw event (audit spine)
    graph.record_raw_event(
        msg_id=event.msg_id,
        classifier=result.classifier_used,
        classification=cls,
        raw_text=event.text,
        posted_at=event.posted_at,
        edited_at=event.edited_at,
        reply_to_msg_id=event.reply_to_msg_id,
    )

    # Dispatch on kind
    kind = cls.get("kind", "chat")
    if kind == "chat":
        return {"status": "chat", "classifier": result.classifier_used,
                "elapsed_ms": result.elapsed_ms}

    # Pause-check for opens
    if kind == "open":
        paused, reason = graph.is_entries_paused()
        if paused:
            logger.warning("entries paused (%s) — ignoring open msg %d", reason, event.msg_id)
            return {"status": "paused", "reason": reason}

        return await _handle_open(graph, ft, cfg, event, cls, result.classifier_used)

    # Management events
    if kind in {"close_full", "close_partial", "move_sl", "increase"}:
        return await _handle_management(graph, ft, event, cls, kind)

    return {"status": "unhandled-kind", "kind": kind}


async def _handle_open(graph, ft, cfg, event, cls, classifier_used):
    """Process an open classification."""
    symbol = cls.get("symbol")
    direction = cls.get("direction")
    entry = cls.get("entry")
    entry_range = cls.get("entry_range")
    sl = cls.get("sl")
    tp = cls.get("tp")

    if symbol is None or direction is None or sl is None:
        return {"status": "rejected", "reason": "missing symbol/direction/sl"}

    # Resolve entry: explicit number, midpoint of range, or "market"
    if entry is None and entry_range:
        entry = (entry_range[0] + entry_range[1]) / 2
    if entry == "market" or entry is None:
        # We need the market price as the effective entry for sizing
        async with aiohttp.ClientSession() as sess:
            mark = await get_mark_price(sess, symbol)
        if mark is None:
            return {"status": "rejected", "reason": f"could not get mark for {symbol}"}
        entry = mark

    # Market sanity band
    async with aiohttp.ClientSession() as sess:
        mark = await get_mark_price(sess, symbol)
    ok, sanity_msg = sanity_check_entry(symbol, entry, mark)
    if not ok:
        logger.error("sanity reject msg %d: %s", event.msg_id, sanity_msg)
        return {"status": "rejected", "reason": f"sanity: {sanity_msg}"}

    # Size it
    try:
        stake, leverage = size_position(entry, sl, cfg.sizing)
    except ValueError as e:
        return {"status": "rejected", "reason": f"sizing: {e}"}

    # Order
    pair = pair_for_symbol(symbol)
    side = "long" if direction.lower() == "long" else "short"

    try:
        ft_resp = await ft.force_enter(pair, side, entry, stake, leverage)
    except Exception as e:
        logger.exception("forceenter failed for msg %d", event.msg_id)
        return {"status": "ft-error", "reason": str(e)}

    ft_trade_id = ft_resp.get("trade_id") or ft_resp.get("trade")
    if ft_resp.get("_http_status", 0) >= 400:
        logger.error("forceenter HTTP %d: %s", ft_resp.get("_http_status"), ft_resp)
        return {"status": "ft-rejected", "reason": str(ft_resp)}

    pos_id = graph.open_position(
        symbol=symbol, direction=direction,
        opened_by_msg_id=event.msg_id,
        open_entry=entry, open_sl=sl, open_tp=tp,
        stake_usdt=stake, leverage=leverage,
        freqtrade_trade_id=ft_trade_id,
    )

    return {
        "status": "opened",
        "position_id": pos_id,
        "symbol": symbol, "direction": direction,
        "entry": entry, "sl": sl, "tp": tp,
        "stake_usdt": stake, "leverage": leverage,
        "ft_trade_id": ft_trade_id,
        "classifier": classifier_used,
        "sanity": sanity_msg,
    }


async def _handle_management(graph, ft, event, cls, kind):
    """Process management classifications: close_full, close_partial, move_sl, increase."""
    targets = graph.resolve_target_positions(cls, event.reply_chain_msg_ids)
    if not targets:
        return {"status": "no-target",
                "reason": "no open position matches this classification",
                "kind": kind}

    results = []
    for pos in targets:
        # Idempotency at action level
        if graph.action_seen(event.msg_id, pos.position_id, kind):
            results.append({"position_id": pos.position_id, "status": "duplicate-action"})
            continue

        if kind == "close_full":
            try:
                ft_resp = await ft.force_exit(pos.freqtrade_trade_id) if pos.freqtrade_trade_id else {"status": "no-ft-id"}
            except Exception as e:
                ft_resp = {"error": str(e)}
            graph.close_full(pos.position_id, event.msg_id)
            results.append({"position_id": pos.position_id, "status": "closed", "ft_resp": ft_resp})

        elif kind == "close_partial":
            pct = cls.get("pct", 50)
            try:
                ft_resp = await ft.force_exit(pos.freqtrade_trade_id, amount_pct=pct) if pos.freqtrade_trade_id else {"status": "no-ft-id"}
            except Exception as e:
                ft_resp = {"error": str(e)}
            new_pct = graph.close_partial(pos.position_id, pct, event.msg_id)
            results.append({"position_id": pos.position_id,
                            "status": "partial-closed",
                            "remaining_pct": new_pct,
                            "ft_resp": ft_resp})

        elif kind == "move_sl":
            new_sl = cls.get("sl")
            if new_sl == "breakeven":
                new_sl = pos.open_entry  # breakeven = open price
            if not isinstance(new_sl, (int, float)):
                results.append({"position_id": pos.position_id,
                                "status": "rejected",
                                "reason": f"invalid sl: {new_sl}"})
                continue
            # TODO: Freqtrade's REST doesn't directly support per-trade SL
            # change. Either patch via custom_stoploss or live with
            # manual trail. For now, record in graph; receiver will need
            # a strategy-side hook (InsidersScalpV1 reads from graph).
            graph.move_sl(pos.position_id, float(new_sl), event.msg_id)
            results.append({"position_id": pos.position_id,
                            "status": "sl-moved-in-graph",
                            "new_sl": new_sl,
                            "note": "Freqtrade-side application TODO"})

        elif kind == "increase":
            # Add to position. Per-signal logic: signal specifies a new
            # limit order at a price. TODO: forceenter for the same pair
            # again with additional stake. For now: log only.
            graph.record_increase(pos.position_id, event.msg_id, cls)
            results.append({"position_id": pos.position_id,
                            "status": "increase-logged",
                            "note": "increase execution TODO"})

    return {"status": "managed", "kind": kind, "results": results}


@app.post("/session-status")
async def session_status(s: SessionStatusIn):
    """Listener heartbeat / session-loss notifications.

    Codex: on session loss, pause new entries. Don't auto-close. Existing
    positions stay protected by exchange-side SL/TP.
    """
    graph: PositionGraph = app.state.graph
    app.state.session_state["connected"] = s.connected
    app.state.session_state["last_msg_at"] = s.last_msg_at

    if not s.connected:
        graph.set_entries_paused(True, reason=f"session-lost: {s.reason}")
        return {"status": "paused", "reason": s.reason}

    # Reconnected — unpause if we were paused due to session loss
    paused, reason = graph.is_entries_paused()
    if paused and reason.startswith("session-lost"):
        graph.set_entries_paused(False, reason="session-restored")
    return {"status": "ok"}


@app.post("/reconcile")
async def reconcile_endpoint():
    return await reconcile_once(app.state.graph, app.state.ft)


@app.get("/positions")
async def list_positions():
    pos = app.state.graph.open_positions()
    return [
        {
            "position_id": p.position_id, "symbol": p.symbol,
            "direction": p.direction, "opened_at": p.opened_at,
            "open_entry": p.open_entry, "current_sl": p.current_sl,
            "current_tp": p.current_tp, "pct_open": p.pct_open,
            "freqtrade_trade_id": p.freqtrade_trade_id,
            "stake_usdt": p.stake_usdt, "leverage": p.leverage,
        }
        for p in pos
    ]


@app.get("/system")
async def system_state():
    graph: PositionGraph = app.state.graph
    paused, reason = graph.is_entries_paused()
    stuck = find_stuck_positions(graph)
    return {
        "instance": app.state.cfg.instance_id,
        "entries_paused": paused,
        "pause_reason": reason,
        "session_connected": app.state.session_state["connected"],
        "stuck_positions": stuck,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
