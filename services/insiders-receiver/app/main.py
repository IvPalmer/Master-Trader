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
from pydantic import BaseModel
# aiohttp is imported lazily inside the open-handler so this module can be
# imported in test environments without aiohttp installed.

from .classifier_dispatcher import ClaudeAgentClassifier, classify
from .claude_classifier import ClaudeCliClassifier
from .executor import (
    FreqtradeClient, FreqtradeConfig, SizingConfig, SKIP_COINS,
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
        # Claude classifier config
        self.claude_enabled = os.getenv("INSIDERS_CLAUDE_ENABLED", "true").lower() == "true"
        self.claude_timeout = float(os.getenv("INSIDERS_CLAUDE_TIMEOUT_SEC", "8.0"))
        self.claude_binary = os.getenv("INSIDERS_CLAUDE_BINARY", "claude")
        self.claude_model = os.getenv("INSIDERS_CLAUDE_MODEL") or None
        # Stale-signal mechanical gate (codex hardening — disabled by default
        # per user trust-the-signaler frame; toggle on if real-channel testing
        # reveals stale-signal misfires)
        self.stale_signal_max_sec = int(os.getenv("INSIDERS_STALE_SIGNAL_MAX_SEC", "0"))
        # 0 = disabled. Set to e.g. 18 to reject opens older than 18s.


# ── Lifespan: init state + background tasks ───────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config()
    graph = PositionGraph(cfg.db_path, cfg.instance_id)
    ft = FreqtradeClient(cfg.ft)
    # Use real Claude CLI classifier (Max subscription via subprocess).
    # Falls back to None on timeout / missing binary / parse error; the
    # dispatcher then degrades to the rule classifier.
    claude = ClaudeCliClassifier(
        timeout_sec=cfg.claude_timeout,
        binary=cfg.claude_binary,
        model=cfg.claude_model,
        enabled=cfg.claude_enabled,
    )
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

    # ATOMIC IDEMPOTENCY: claim the msg_id BEFORE classification + dispatch.
    # Two concurrent /event posts for the same msg_id can both pass a
    # plain msg_seen() check; only the INSERT (PRIMARY KEY) is atomic.
    # The loser sees rowcount=0 and bails — Freqtrade is never double-hit.
    claimed = graph.claim_msg(
        event.msg_id,
        raw_text=event.text,
        posted_at=event.posted_at,
        edited_at=event.edited_at,
        reply_to_msg_id=event.reply_to_msg_id,
    )
    if not claimed:
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

    # Fill in the classification on the previously-claimed row
    graph.complete_claim(
        msg_id=event.msg_id,
        classifier=result.classifier_used,
        classification=cls,
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
    # Defensive validation before ANY action. Catches garbage from the
    # cold-path Claude/rule output that the fast-path's is_strict_open
    # would have rejected — type errors here would otherwise crash
    # sizing/sanity or, worse, fire an order with a bogus value.
    valid, reason = validate_open_payload(cls)
    if not valid:
        logger.error("invalid open payload for msg %d: %s (cls=%s)",
                     event.msg_id, reason, cls)
        return {"status": "rejected", "reason": f"payload: {reason}"}

    symbol = cls.get("symbol")
    direction = cls.get("direction")
    entry = cls.get("entry")
    entry_range = cls.get("entry_range")
    sl = cls.get("sl")
    tp = cls.get("tp")

    # Skip-list check BEFORE any Binance call. Surfaces a clean operator
    # alert for coins that aren't on Binance Futures (e.g. MNT).
    if symbol.upper() in SKIP_COINS:
        logger.warning("skip-list reject msg %d: %s not on Binance Futures",
                       event.msg_id, symbol)
        return {"status": "rejected",
                "reason": f"skip-list: {symbol} not on Binance USDT-M Futures"}

    # Stale-signal mechanical gate (codex hardening — OFF by default per
    # user trust-the-signaler frame). Set INSIDERS_STALE_SIGNAL_MAX_SEC > 0
    # to enable. This is NOT a signal-quality veto; it's a clock-skew
    # safety net for cases where the listener was dead and we're now
    # replaying old messages.
    if cfg.stale_signal_max_sec > 0 and event.posted_at:
        try:
            posted = datetime.fromisoformat(event.posted_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - posted).total_seconds()
            if age_sec > cfg.stale_signal_max_sec:
                logger.warning(
                    "STALE signal: msg %d age %.1fs > threshold %ds — rejecting open",
                    event.msg_id, age_sec, cfg.stale_signal_max_sec,
                )
                return {"status": "rejected", "reason": f"stale: age {age_sec:.1f}s"}
        except (ValueError, TypeError) as e:
            logger.warning("could not parse posted_at %r: %s", event.posted_at, e)

    # Resolve entry + fetch mark price in a single session.
    import aiohttp
    async with aiohttp.ClientSession() as sess:
        mark = await get_mark_price(sess, symbol)
    if entry is None and entry_range:
        entry = (entry_range[0] + entry_range[1]) / 2
    if entry == "market" or entry is None:
        if mark is None:
            return {"status": "rejected", "reason": f"could not get mark for {symbol}"}
        entry = mark

    # Market sanity band
    ok, sanity_msg = sanity_check_entry(symbol, entry, mark)
    if not ok:
        logger.error("sanity reject msg %d: %s", event.msg_id, sanity_msg)
        return {"status": "rejected", "reason": f"sanity: {sanity_msg}"}

    # Wrong-side SL pre-reject. The strategy's custom_stoploss catches this
    # too and falls back to the static -10%, but that's a costly surprise —
    # we should never even open a position with a SL on the wrong side of
    # entry. Fail fast at the receiver.
    direction_lc = direction.lower()
    if direction_lc == "long" and sl >= entry:
        return {"status": "rejected",
                "reason": f"wrong-side SL: long entry={entry} sl={sl} (sl must be < entry)"}
    if direction_lc == "short" and sl <= entry:
        return {"status": "rejected",
                "reason": f"wrong-side SL: short entry={entry} sl={sl} (sl must be > entry)"}

    # Size it
    try:
        stake, leverage = size_position(entry, sl, cfg.sizing)
    except ValueError as e:
        return {"status": "rejected", "reason": f"sizing: {e}"}

    # Pre-create position in 'requested' state BEFORE /forceenter so a crash
    # between order placement and graph write leaves an attachable orphan
    # (reconciler matches by symbol+direction → links the ft_trade_id). The
    # row is finalized to status='open' only after a 2xx response from FT.
    pair = pair_for_symbol(symbol)
    side = "long" if direction_lc == "long" else "short"
    pos_id = graph.open_position(
        symbol=symbol, direction=direction,
        opened_by_msg_id=event.msg_id,
        open_entry=entry, open_sl=sl, open_tp=tp,
        stake_usdt=stake, leverage=leverage,
        freqtrade_trade_id=None,
        status="requested",
    )

    try:
        ft_resp = await ft.force_enter(pair, side, stake, leverage)
    except Exception as e:
        # UNCERTAIN: the exception may have fired AFTER FT received the
        # request (network drop, JSON parse error, timeout post-submit).
        # Leave the position in 'requested' so the reconciler can heal
        # it once FT's /status reflects the trade. Do NOT mark failed —
        # that would orphan real exchange exposure beyond reconciler
        # reach.
        logger.exception("forceenter raised for msg %d — keeping position "
                         "in 'requested' (uncertain)", event.msg_id)
        return {"status": "ft-uncertain",
                "reason": f"exception: {e}",
                "position_id": pos_id}

    kind = _ft_response_kind(ft_resp)

    if kind == "uncertain":
        # 5xx / status=0 / non-dict response. Same logic as exception path:
        # FT may or may not have accepted; let the reconciler decide.
        logger.error("forceenter UNCERTAIN for msg %d (kind=%s): %s — "
                     "keeping position in 'requested' for reconciler",
                     event.msg_id, kind, ft_resp)
        return {"status": "ft-uncertain", "reason": str(ft_resp),
                "position_id": pos_id}

    if kind == "rejected":
        # Definite NO from FT — 4xx or 2xx-with-error. No exposure created.
        # Safe to mark failed so the reconciler doesn't keep trying to heal.
        logger.error("forceenter REJECTED for msg %d: %s", event.msg_id, ft_resp)
        graph.mark_position_failed(
            pos_id, reason=f"ft-rejected: {ft_resp}"
        )
        return {"status": "ft-rejected", "reason": str(ft_resp),
                "position_id": pos_id}

    # kind == "accepted" — FT 2xx, no error key. Now look for trade_id.
    ft_trade_id = ft_resp.get("trade_id") or ft_resp.get("trade")
    if not isinstance(ft_trade_id, int) or isinstance(ft_trade_id, bool):
        # FT accepted but response shape didn't carry trade_id. Treat as
        # UNCERTAIN (NOT failed) — the order is live on FT but we don't
        # have the local handle yet. Reconciler will back-link via
        # (pair, side) on the next pass.
        logger.error("forceenter ACCEPTED but no usable trade_id for msg %d: "
                     "%s — keeping position in 'requested' for reconciler",
                     event.msg_id, ft_resp)
        return {"status": "ft-uncertain", "reason": "accepted-no-trade-id",
                "position_id": pos_id}

    graph.finalize_requested_position(pos_id, ft_trade_id=ft_trade_id)

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


def _ft_response_ok(resp: dict) -> bool:
    """A Freqtrade response counts as successful only when there's a 2xx
    status code AND no `error` key. Anything else means the order didn't
    execute — local graph state must NOT be mutated.

    Use _ft_response_kind() for the three-state version used by the open
    path (need to distinguish definite-reject from uncertain-submit).
    """
    return _ft_response_kind(resp) == "accepted"


def _ft_response_kind(resp: dict) -> str:
    """Classify an FT REST response into one of:

      'accepted' — 2xx, no error key. Order accepted by Freqtrade.
      'rejected' — 4xx OR 2xx with explicit `error` key. FT definitively
                   said NO; no exposure was created.
      'uncertain' — exception caught (network drop, JSON parse, timeout)
                   OR 5xx server error. FT may have accepted the order
                   server-side; we just don't know. Caller MUST leave the
                   position in 'requested' state so the reconciler can
                   heal it on the next pass.

    The exception case is signalled by the caller wrapping the response
    as {"_http_status": 0, "error": "...exception..."}. We treat
    status==0 as uncertain regardless of error presence.
    """
    if not isinstance(resp, dict):
        return "uncertain"
    status = resp.get("_http_status", 0)
    if status == 0:
        # Exception path — caller wrapped the exception as a dict.
        return "uncertain"
    if 200 <= status < 300:
        if "error" in resp:
            return "rejected"
        return "accepted"
    if 400 <= status < 500:
        return "rejected"
    # 3xx (shouldn't happen with FT) and 5xx fall through to uncertain.
    return "uncertain"


_OPEN_DIRECTIONS = {"long", "short", "LONG", "SHORT"}


def validate_open_payload(cls: dict) -> tuple[bool, str]:
    """Defensive validation for an open-kind classification BEFORE sizing
    or order placement.

    is_strict_open (in classifier_dispatcher) gates the fast-path so the
    Claude shadow can step in for messy shapes. This validator is the
    POST-classification gate that applies to ANY classification (fast or
    cold) before we touch real money. Catches:

    - non-string symbol (would crash .upper())
    - garbage direction (would crash .lower() / break side flag)
    - non-numeric sl/entry/entry_range (would crash sizing or sanity)
    - missing both entry and entry_range with no fallback to market
    - tp present but not numeric
    """
    symbol = cls.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        return False, f"invalid symbol: {symbol!r}"

    direction = cls.get("direction")
    if direction not in _OPEN_DIRECTIONS:
        return False, f"invalid direction: {direction!r}"

    sl = cls.get("sl")
    if not isinstance(sl, (int, float)) or isinstance(sl, bool) or sl <= 0:
        return False, f"invalid sl: {sl!r}"

    entry = cls.get("entry")
    entry_range = cls.get("entry_range")
    if entry is not None and entry != "market":
        if not isinstance(entry, (int, float)) or isinstance(entry, bool) or entry <= 0:
            return False, f"invalid entry: {entry!r}"
    elif entry_range is not None:
        if not isinstance(entry_range, (list, tuple)) or len(entry_range) != 2:
            return False, f"invalid entry_range: {entry_range!r}"
        for x in entry_range:
            if not isinstance(x, (int, float)) or isinstance(x, bool) or x <= 0:
                return False, f"invalid entry_range element: {x!r}"
    # entry == None / 'market' with no range → caller falls back to mark; OK

    tp = cls.get("tp")
    if tp is not None and (not isinstance(tp, (int, float))
                           or isinstance(tp, bool) or tp <= 0):
        return False, f"invalid tp: {tp!r}"

    return True, "ok"


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
            if not pos.freqtrade_trade_id:
                # No FT trade linked yet — refuse to mutate. Reconciler
                # will sort this out once the FT trade appears.
                results.append({"position_id": pos.position_id,
                                "status": "rejected",
                                "reason": "no ft_trade_id linked yet"})
                continue
            try:
                ft_resp = await ft.force_exit(pos.freqtrade_trade_id)
            except Exception as e:
                ft_resp = {"error": str(e)}
            if _ft_response_ok(ft_resp):
                graph.close_full(pos.position_id, event.msg_id)
                results.append({"position_id": pos.position_id,
                                "status": "closed", "ft_resp": ft_resp})
            else:
                logger.error("FT forceexit FAILED for pos %d: %s — graph NOT mutated",
                             pos.position_id, ft_resp)
                results.append({"position_id": pos.position_id,
                                "status": "ft-rejected",
                                "ft_resp": ft_resp,
                                "note": "graph not mutated; position remains open"})

        elif kind == "close_partial":
            if not pos.freqtrade_trade_id:
                results.append({"position_id": pos.position_id,
                                "status": "rejected",
                                "reason": "no ft_trade_id linked yet"})
                continue
            pct = cls.get("pct", 50)
            try:
                ft_resp = await ft.force_exit(pos.freqtrade_trade_id, amount_pct=pct)
            except Exception as e:
                ft_resp = {"error": str(e)}
            if _ft_response_ok(ft_resp):
                new_pct = graph.close_partial(pos.position_id, pct, event.msg_id)
                results.append({"position_id": pos.position_id,
                                "status": "partial-closed",
                                "remaining_pct": new_pct,
                                "ft_resp": ft_resp})
            else:
                logger.error("FT partial forceexit FAILED for pos %d: %s — graph NOT mutated",
                             pos.position_id, ft_resp)
                results.append({"position_id": pos.position_id,
                                "status": "ft-rejected",
                                "ft_resp": ft_resp,
                                "note": "graph not mutated; position remains at full size"})

        elif kind == "move_sl":
            new_sl = cls.get("sl")
            if new_sl == "breakeven":
                new_sl = pos.open_entry  # breakeven = open price
            if not isinstance(new_sl, (int, float)):
                results.append({"position_id": pos.position_id,
                                "status": "rejected",
                                "reason": f"invalid sl: {new_sl}"})
                continue
            # Freqtrade has no REST endpoint to change a per-trade SL.
            # InsidersScalpV1.custom_stoploss reads current_sl from the
            # graph on every candle, so mutating the graph IS the
            # application path. Side-validity is enforced again
            # client-side in the strategy.
            graph.move_sl(pos.position_id, float(new_sl), event.msg_id)
            results.append({"position_id": pos.position_id,
                            "status": "sl-moved-in-graph",
                            "new_sl": new_sl})

        elif kind == "increase":
            # Increases are NOT implemented on the live path. The offline
            # replay simulator records them (and replay PnL includes their
            # effect); the live receiver REJECTS them so we don't silently
            # diverge. To enable: implement /forceenter for the same pair
            # with additional stake + decide whether risk compounds per
            # increase or caps at the original budget.
            graph.record_increase(pos.position_id, event.msg_id, cls)
            logger.warning("increase event REJECTED on live path (pos %d) — "
                           "not implemented; replay PnL includes increases, "
                           "live will diverge", pos.position_id)
            results.append({"position_id": pos.position_id,
                            "status": "rejected",
                            "reason": "increase not implemented on live path",
                            "note": "logged in position graph for audit"})

    return {"status": "managed", "kind": kind, "results": results}


@app.post("/session-status")
async def session_status(s: SessionStatusIn):
    """Listener heartbeat / session-loss notifications.

    Codex: on session loss, pause new entries. Don't auto-close. Existing
    positions stay protected by exchange-side SL/TP.

    Reconnect does NOT auto-unpause — operator must explicitly call
    POST /system/unpause after verifying state. Prevents flapping
    listener from spamming entries during reconnect storms.
    """
    graph: PositionGraph = app.state.graph
    prev_connected = app.state.session_state.get("connected", True)
    app.state.session_state["connected"] = s.connected
    app.state.session_state["last_msg_at"] = s.last_msg_at

    if not s.connected:
        graph.set_entries_paused(True, reason=f"session-lost: {s.reason}")
        return {"status": "paused", "reason": s.reason}

    # Reconnected — record but stay paused if we were paused for session loss
    paused, reason = graph.is_entries_paused()
    if paused and reason.startswith("session-lost"):
        if not prev_connected:
            logger.warning(
                "session reconnected (was disconnected). Entries REMAIN PAUSED. "
                "Operator must POST /system/unpause to resume."
            )
        return {"status": "ok-but-paused-pending-manual-unpause",
                "pause_reason": reason}
    return {"status": "ok"}


@app.post("/system/unpause")
async def manual_unpause(reason: str = "operator-confirmed"):
    """Manually clear entries_paused. Required after session-loss event
    to resume new entries. Existing positions are managed regardless of
    pause state."""
    graph: PositionGraph = app.state.graph
    paused, prev_reason = graph.is_entries_paused()
    if not paused:
        return {"status": "already-unpaused"}
    graph.set_entries_paused(False, reason=f"manual: {reason}")
    logger.warning("entries UNPAUSED by operator. Previous pause reason: %s", prev_reason)
    return {"status": "unpaused", "prev_reason": prev_reason}


@app.post("/system/pause")
async def manual_pause(reason: str = "operator-requested"):
    """Manual pause endpoint — operator can stop new entries at any time."""
    graph: PositionGraph = app.state.graph
    graph.set_entries_paused(True, reason=f"manual: {reason}")
    return {"status": "paused", "reason": reason}


@app.post("/reconcile")
async def reconcile_endpoint():
    return await reconcile_once(app.state.graph, app.state.ft)


@app.get("/position/by_ft_id/{ft_trade_id}")
async def get_position_by_ft_id(ft_trade_id: int):
    """Strategy custom_stoploss endpoint. Returns live SL + state for a
    Freqtrade trade_id. Strategy calls this on every candle and uses
    `current_sl` as the active stop."""
    graph: PositionGraph = app.state.graph
    row = graph.conn.execute(
        "SELECT * FROM positions WHERE freqtrade_trade_id = ? AND status = 'open'",
        (ft_trade_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "position_id": row["position_id"],
        "symbol": row["symbol"],
        "direction": row["direction"],
        "open_entry": row["open_entry"],
        "current_sl": row["current_sl"],
        "current_tp": row["current_tp"],
        "pct_open": row["pct_open"],
        "status": row["status"],
    }


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


@app.get("/positions/requested")
async def list_requested():
    """Positions stuck in 'requested' — pre-created before /forceenter that
    never confirmed back (FT exception, timeout, 2xx-no-trade-id, 5xx).

    The reconciler tries to back-link these to unclaimed FT trades by
    (pair, side) automatically. Anything still here is operator-actionable:
    either the order was rejected silently and the row should be marked
    failed via POST /position/{id}/fail, or the operator can confirm an
    FT trade_id manually via POST /position/{id}/link.
    """
    graph: PositionGraph = app.state.graph
    orphans = graph.requested_orphans()
    now = datetime.now(timezone.utc)
    out = []
    for p in orphans:
        try:
            opened = datetime.fromisoformat(p.opened_at.replace("Z", "+00:00"))
            age_sec = (now - opened).total_seconds()
        except Exception:
            age_sec = None
        out.append({
            "position_id": p.position_id, "symbol": p.symbol,
            "direction": p.direction, "opened_at": p.opened_at,
            "age_sec": age_sec,
            "open_entry": p.open_entry, "open_sl": p.open_sl,
            "open_tp": p.open_tp, "stake_usdt": p.stake_usdt,
            "leverage": p.leverage,
            "opened_by_msg_id": p.opened_by_msg_id,
        })
    return out


@app.post("/position/{position_id}/fail")
async def manual_fail_requested(position_id: int, reason: str = "operator-fail"):
    """Operator action: mark a stale 'requested' position as failed.

    Use when you've verified Freqtrade has no matching exposure (e.g. the
    order was rejected silently or the signal was a false start). Does
    NOT touch FT — purely a graph state cleanup.

    Returns 409 if the position is not in 'requested' state.
    """
    graph: PositionGraph = app.state.graph
    row = graph.conn.execute(
        "SELECT status FROM positions WHERE position_id = ?", (position_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="position not found")
    if row["status"] != "requested":
        raise HTTPException(
            status_code=409,
            detail=f"position is {row['status']!r}, not 'requested' — refusing to fail",
        )
    graph.mark_position_failed(position_id, reason=f"manual: {reason}")
    logger.warning("position %d manually marked failed by operator: %s",
                   position_id, reason)
    return {"status": "failed", "position_id": position_id, "reason": reason}


@app.post("/position/{position_id}/link")
async def manual_link_requested(position_id: int, ft_trade_id: int):
    """Operator action: manually link a stale 'requested' position to a
    specific Freqtrade trade_id. Use when reconciler refused to auto-link
    (ambiguous bucket) but you've verified the correct attribution.

    Returns 409 if position is not 'requested', or if ft_trade_id is
    already claimed by another open position.
    """
    graph: PositionGraph = app.state.graph
    row = graph.conn.execute(
        "SELECT status FROM positions WHERE position_id = ?", (position_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="position not found")
    if row["status"] != "requested":
        raise HTTPException(
            status_code=409,
            detail=f"position is {row['status']!r}, not 'requested'",
        )
    # Reject double-claims of an ft_trade_id
    clash = graph.conn.execute(
        "SELECT position_id FROM positions WHERE freqtrade_trade_id = ? "
        "AND status = 'open'", (ft_trade_id,),
    ).fetchone()
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"ft_trade_id {ft_trade_id} already claimed by position {clash['position_id']}",
        )
    graph.finalize_requested_position(position_id, ft_trade_id=ft_trade_id)
    logger.warning("position %d manually linked to ft_trade_id=%d by operator",
                   position_id, ft_trade_id)
    return {"status": "linked", "position_id": position_id,
            "ft_trade_id": ft_trade_id}


@app.get("/system")
async def system_state():
    graph: PositionGraph = app.state.graph
    paused, reason = graph.is_entries_paused()
    stuck = find_stuck_positions(graph)
    requested = graph.requested_orphans()
    # Compute oldest requested age for alerting
    oldest_requested_age_sec = None
    if requested:
        now = datetime.now(timezone.utc)
        ages = []
        for p in requested:
            try:
                opened = datetime.fromisoformat(p.opened_at.replace("Z", "+00:00"))
                ages.append((now - opened).total_seconds())
            except Exception:
                continue
        if ages:
            oldest_requested_age_sec = max(ages)
    return {
        "instance": app.state.cfg.instance_id,
        "entries_paused": paused,
        "pause_reason": reason,
        "session_connected": app.state.session_state["connected"],
        "stuck_positions": stuck,
        "requested_orphans_count": len(requested),
        "oldest_requested_age_sec": oldest_requested_age_sec,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
