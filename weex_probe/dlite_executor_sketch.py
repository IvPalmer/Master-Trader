"""D-lite executor sketch — replaces Freqtrade for the Insiders bot.

Goal: take TradeIntents from the receiver's classification cascade and
turn each one into a validated WEEX REST payload (without actually
hitting the network for orders).

Critical WEEX quirks this sketch handles:
  - `quantityPrecision` can be NEGATIVE for thin-tail symbols (PUMP=-2),
    meaning order qty must be a multiple of 10**(-prec).
  - `contractVal` ≠ 1 for many alts. WEEX orders are in CONTRACTS, each
    representing `contractVal` units of the base asset (PUMP contract =
    100 PUMP tokens). qty * contractVal = base coins.
  - `minOrderSize` is in CONTRACTS (= contractVal for many thin pairs).
  - Symbol map: 1000-prefix variants for tiny coins (PEPE → 1000PEPEUSDT).
  - Hedge mode requires `positionId` for SL/TP plans (see probe_signed.py).

Mocked: order submission, fill confirmation, algo IDs. Replay drives
the executor; results land in journal + positions dicts.
"""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ── Symbol mapping helpers ───────────────────────────────────────────────


# Insiders symbols that need 1000-prefix on WEEX (small price -> scaled)
_SCALED_1000 = {"PEPE", "SHIB", "FLOKI", "BONK"}


def map_symbol(insiders_symbol: str, exchange_info: dict) -> Optional[str]:
    """Map an Insiders classifier symbol to a WEEX trading symbol.

    Returns None if the symbol isn't tradable on WEEX. Handles 1000-prefix
    for tiny memes and the already-prefixed case (1000PEPE).
    """
    s = insiders_symbol.upper().strip()
    all_syms = {row["symbol"] for row in exchange_info.get("symbols", [])}
    cands = [f"{s}USDT"]
    if s in _SCALED_1000:
        cands.append(f"1000{s}USDT")
    if s.startswith("1000"):
        cands.append(s + "USDT")
    for c in cands:
        if c in all_syms:
            return c
    return None


def get_symbol_meta(weex_symbol: str, exchange_info: dict) -> Optional[dict]:
    for row in exchange_info.get("symbols", []):
        if row["symbol"] == weex_symbol:
            return row
    return None


# ── Precision math ───────────────────────────────────────────────────────


def round_price(price: float, price_precision: int) -> float:
    """Round to WEEX's pricePrecision (always non-negative for prices)."""
    if price_precision < 0:
        # Defensive: never seen but spec-safe
        factor = 10 ** (-price_precision)
        return math.floor(price / factor) * factor
    q = 10 ** price_precision
    # Use floor-toward-zero for SL on long, ceil for SL on short would be ideal,
    # but the canonical Freqtrade-like behavior is plain round-half-to-even.
    return round(price * q) / q


def quantize_qty_to_contracts(
    base_coins: float,
    quantity_precision: int,
    min_order_size: float,
) -> tuple[float, int]:
    """Quantize an order from base-coins to WEEX contracts.

    WEEX's `quantity` field on the order endpoint is the number of
    contracts. For symbols with negative `quantityPrecision`, contracts
    must be multiples of 10**(-prec). e.g. PUMPUSDT qtyPrec=-2 means qty
    must be a multiple of 100 contracts.

    Returns (qty_in_contracts, n_decimal_digits_for_str).
    """
    if quantity_precision >= 0:
        step = 10 ** (-quantity_precision)
        # Floor toward zero so we never exceed budget after rounding.
        qty = math.floor(base_coins / step) * step
        # Snap up to minOrderSize if we floored below it.
        if qty < min_order_size:
            qty = min_order_size
        return round(qty, quantity_precision), quantity_precision
    # Negative precision: step = 10**(-prec) = 10**abs(prec)
    step = 10 ** (-quantity_precision)
    qty = math.floor(base_coins / step) * step
    if qty < min_order_size:
        qty = min_order_size
    return qty, 0


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass
class TradeIntent:
    intent_id: str
    symbol: str  # Insiders symbol (BTC, PUMP, etc — pre-mapping)
    direction: str  # LONG | SHORT
    kind: str  # open | close_full | close_partial | move_sl | increase
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    pct: Optional[float] = None  # 0-100 for partial close
    notional_usd: float = 25.0
    parent_trade_id: Optional[str] = None  # for events tied to an open trade
    mark_price: Optional[float] = None  # cached at intent creation


@dataclass
class JournalEntry:
    intent_id: str
    kind: str
    phase: str  # validated | submitted | filled | failed | suppressed
    detail: str
    payload: Optional[dict] = None
    error_type: Optional[str] = None


@dataclass
class PositionState:
    trade_id: str
    weex_symbol: str
    position_side: str  # LONG | SHORT
    contracts: float
    contract_val: float
    entry_price: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    position_id: Optional[str] = None  # WEEX's internal id, mocked
    sl_algo_id: Optional[str] = None
    tp_algo_id: Optional[str] = None
    closed: bool = False


# ── Mock WEEX responses ──────────────────────────────────────────────────


def _mock_order_response(client_order_id: str) -> dict:
    return {
        "success": True,
        "code": "00000",
        "data": {
            "orderId": str(int(time.time() * 1000)) + uuid.uuid4().hex[:6],
            "clientOrderId": client_order_id,
        },
    }


def _mock_algo_response(client_algo_id: str) -> dict:
    return {
        "success": True,
        "code": "00000",
        "data": {
            "algoId": str(int(time.time() * 1000)) + uuid.uuid4().hex[:6],
            "clientAlgoId": client_algo_id,
        },
    }


def _mock_position_id() -> str:
    return uuid.uuid4().hex[:16]


# ── Executor ─────────────────────────────────────────────────────────────


class ValidationError(Exception):
    def __init__(self, error_type: str, detail: str):
        super().__init__(f"{error_type}: {detail}")
        self.error_type = error_type
        self.detail = detail


class DLiteExecutor:
    """Thin REST-direct executor for WEEX USDT-M perp.

    No persistent state in this sketch — positions/journal live in
    in-memory dicts. Real impl would back them with sqlite.
    """

    def __init__(self, client: Any, exchange_info: dict, mark_price_cache: Optional[dict] = None):
        self.client = client  # WeexClient or None for mock-only
        self.exchange_info = exchange_info
        self.mark_price_cache = mark_price_cache or {}
        self.journal: list[JournalEntry] = []
        self.positions: dict[str, PositionState] = {}  # trade_id -> state

    # ── helpers ──

    def _resolve_mark(self, insiders_symbol: str, intent_mark: Optional[float]) -> Optional[float]:
        if intent_mark and intent_mark > 0:
            return intent_mark
        rec = self.mark_price_cache.get(insiders_symbol)
        if rec and rec.get("mark_price"):
            return float(rec["mark_price"])
        return None

    def _log(self, entry: JournalEntry) -> None:
        self.journal.append(entry)

    def _validate_open_intent(self, intent: TradeIntent) -> tuple[str, dict, float, float]:
        """Return (weex_symbol, sym_meta, contracts, qty_step_for_str)."""
        weex_symbol = map_symbol(intent.symbol, self.exchange_info)
        if not weex_symbol:
            raise ValidationError("missing_symbol", f"{intent.symbol} not on WEEX")
        meta = get_symbol_meta(weex_symbol, self.exchange_info)
        if not meta:
            raise ValidationError("missing_symbol", f"{weex_symbol} meta lookup failed")

        mark = self._resolve_mark(intent.symbol, intent.mark_price)
        if mark is None or mark <= 0:
            raise ValidationError("no_mark_price", f"no mark for {weex_symbol}")

        # Sanity band on entry vs mark — copy from current executor.py
        if intent.entry is not None and intent.entry > 0:
            dev = abs(intent.entry - mark) / mark
            if dev > 0.30:
                # NOTE: stricter than 20% only used as a guard, not a hard reject
                # in the sketch — we tag in payload validation instead.
                pass

        # Compute size: notional / mark = base coins; then divide by contractVal.
        contract_val = float(meta.get("contractVal", 1.0))
        base_coins = intent.notional_usd / mark
        # contracts (not base coins) is what WEEX wants on order qty
        target_contracts_raw = base_coins / contract_val

        qty_prec = int(meta.get("quantityPrecision", 0))
        min_size = float(meta.get("minOrderSize", 0))

        qty, dec_digits = quantize_qty_to_contracts(target_contracts_raw, qty_prec, min_size)

        # After rounding, verify we meet minOrderSize
        if qty < min_size:
            raise ValidationError(
                "min_size_floor",
                f"{weex_symbol} qty={qty} < minOrderSize={min_size} at ${intent.notional_usd:.2f} notional (mark={mark})",
            )

        # Verify the resulting notional isn't drastically inflated by quantization
        # (e.g. min-size floor pushes a $25 intent to $60 notional)
        resulting_notional = qty * contract_val * mark
        if resulting_notional > intent.notional_usd * 2.5:
            raise ValidationError(
                "min_size_inflation",
                f"{weex_symbol} quantization floor forces notional ${resulting_notional:.2f} vs target ${intent.notional_usd:.2f}",
            )

        # SL/TP rounding (if present)
        price_prec = int(meta.get("pricePrecision", 2))
        if intent.sl is not None:
            sl_rounded = round_price(intent.sl, price_prec)
            if sl_rounded <= 0:
                raise ValidationError("price_underflow", f"SL rounded to {sl_rounded}")
            # Verify rounding didn't make SL cross the entry direction
            if intent.entry is not None:
                if intent.direction == "LONG" and sl_rounded >= intent.entry:
                    raise ValidationError("sl_rounding_inversion",
                                         f"LONG SL {intent.sl}→{sl_rounded} ≥ entry {intent.entry}")
                if intent.direction == "SHORT" and sl_rounded <= intent.entry:
                    raise ValidationError("sl_rounding_inversion",
                                         f"SHORT SL {intent.sl}→{sl_rounded} ≤ entry {intent.entry}")

        if intent.tp is not None:
            tp_rounded = round_price(intent.tp, price_prec)
            if tp_rounded <= 0:
                raise ValidationError("price_underflow", f"TP rounded to {tp_rounded}")

        return weex_symbol, meta, qty, dec_digits

    # ── primary methods ──

    def open_with_bracket(self, intent: TradeIntent) -> dict:
        try:
            weex_symbol, meta, qty, dec_digits = self._validate_open_intent(intent)
        except ValidationError as e:
            self._log(JournalEntry(intent.intent_id, intent.kind, "failed", str(e),
                                   error_type=e.error_type))
            return {"ok": False, "error_type": e.error_type, "detail": e.detail}

        price_prec = int(meta.get("pricePrecision", 2))
        contract_val = float(meta.get("contractVal", 1.0))
        side = "BUY" if intent.direction == "LONG" else "SELL"
        position_side = intent.direction  # one-way: LONG|SHORT

        client_order_id = f"insiders-{intent.intent_id}"
        qty_str = f"{qty:.{max(dec_digits, 0)}f}"

        sl_str = (str(round_price(intent.sl, price_prec))
                  if intent.sl is not None else None)
        tp_str = (str(round_price(intent.tp, price_prec))
                  if intent.tp is not None else None)

        payload = {
            "symbol": weex_symbol,
            "side": side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": qty_str,
            "newClientOrderId": client_order_id,
        }
        if sl_str is not None:
            payload["slTriggerPrice"] = sl_str
            payload["SlWorkingType"] = "MARK_PRICE"
        if tp_str is not None:
            payload["tpTriggerPrice"] = tp_str
            payload["TpWorkingType"] = "MARK_PRICE"

        self._log(JournalEntry(intent.intent_id, intent.kind, "validated",
                               f"payload for {weex_symbol} {position_side} qty={qty_str}",
                               payload=payload))

        # MOCKED: submit + capture order id + spawn position
        order_resp = _mock_order_response(client_order_id)
        order_id = order_resp["data"]["orderId"]
        position_id = _mock_position_id()
        mark = self._resolve_mark(intent.symbol, intent.mark_price) or intent.entry or 0
        state = PositionState(
            trade_id=intent.intent_id,
            weex_symbol=weex_symbol,
            position_side=position_side,
            contracts=qty,
            contract_val=contract_val,
            entry_price=mark,
            sl=float(sl_str) if sl_str else None,
            tp=float(tp_str) if tp_str else None,
            position_id=position_id,
        )
        # Spawn SL/TP algos (mocked)
        if state.sl is not None:
            algo = _mock_algo_response(f"sl-{intent.intent_id}")
            state.sl_algo_id = algo["data"]["algoId"]
        if state.tp is not None:
            algo = _mock_algo_response(f"tp-{intent.intent_id}")
            state.tp_algo_id = algo["data"]["algoId"]

        self.positions[intent.intent_id] = state
        self._log(JournalEntry(intent.intent_id, intent.kind, "submitted",
                               f"order_id={order_id} position_id={position_id}",
                               payload={"order_resp": order_resp}))
        return {"ok": True, "order_id": order_id, "position_id": position_id, "payload": payload}

    def full_close(self, intent: TradeIntent) -> dict:
        state = self.positions.get(intent.parent_trade_id or intent.intent_id)
        if state is None or state.closed:
            self._log(JournalEntry(intent.intent_id, intent.kind, "failed",
                                   f"no open position for parent={intent.parent_trade_id}",
                                   error_type="no_parent_position"))
            return {"ok": False, "error_type": "no_parent_position"}
        # /closePositions takes only symbol
        payload = {"symbol": state.weex_symbol}
        self._log(JournalEntry(intent.intent_id, intent.kind, "validated",
                               f"closePositions {state.weex_symbol}",
                               payload=payload))
        state.closed = True
        self._log(JournalEntry(intent.intent_id, intent.kind, "submitted",
                               "mocked closePositions ok",
                               payload={"close_resp": {"success": True}}))
        return {"ok": True, "payload": payload}

    def partial_close(self, intent: TradeIntent) -> dict:
        state = self.positions.get(intent.parent_trade_id or intent.intent_id)
        if state is None or state.closed:
            self._log(JournalEntry(intent.intent_id, intent.kind, "failed",
                                   f"no open position for parent={intent.parent_trade_id}",
                                   error_type="no_parent_position"))
            return {"ok": False, "error_type": "no_parent_position"}

        pct = intent.pct or 0
        if pct <= 0 or pct >= 100:
            # >=100 falls through to full close semantics
            return self.full_close(intent)

        meta = get_symbol_meta(state.weex_symbol, self.exchange_info) or {}
        qty_prec = int(meta.get("quantityPrecision", 0))
        min_size = float(meta.get("minOrderSize", 0))

        target_close = state.contracts * (pct / 100.0)
        close_qty, dec_digits = quantize_qty_to_contracts(target_close, qty_prec, min_size)
        # Ensure we don't close more than we hold
        if close_qty > state.contracts:
            close_qty = state.contracts

        remainder = state.contracts - close_qty
        # CRITICAL: WEEX rejects orders below minOrderSize. If the remainder
        # would fall below minOrderSize, the position has to be fully closed
        # OR the partial close size has to be tweaked so the remainder is exactly 0.
        if 0 < remainder < min_size:
            # Promote to full close (safer than leaving a phantom dust position).
            self._log(JournalEntry(intent.intent_id, intent.kind, "validated",
                                   f"partial→full (remainder {remainder} < min {min_size})",
                                   error_type="partial_promoted_to_full"))
            return self.full_close(intent)

        if close_qty < min_size:
            self._log(JournalEntry(intent.intent_id, intent.kind, "failed",
                                   f"partial qty {close_qty} < min {min_size}",
                                   error_type="partial_below_min"))
            return {"ok": False, "error_type": "partial_below_min"}

        # Build a reduce-only MARKET order
        opposite = "SELL" if state.position_side == "LONG" else "BUY"
        qty_str = f"{close_qty:.{max(dec_digits, 0)}f}"
        payload = {
            "symbol": state.weex_symbol,
            "side": opposite,
            "positionSide": state.position_side,
            "type": "MARKET",
            "quantity": qty_str,
            "newClientOrderId": f"insiders-{intent.intent_id}",
            "reduceOnly": True,
        }
        self._log(JournalEntry(intent.intent_id, intent.kind, "validated",
                               f"partial close {pct}% = {qty_str} contracts (remainder {remainder})",
                               payload=payload))
        state.contracts = remainder
        self._log(JournalEntry(intent.intent_id, intent.kind, "submitted",
                               "mocked partial close ok",
                               payload={"close_resp": _mock_order_response(payload["newClientOrderId"])}))
        return {"ok": True, "payload": payload, "remainder": remainder}

    def move_sl(self, intent: TradeIntent) -> dict:
        state = self.positions.get(intent.parent_trade_id or intent.intent_id)
        if state is None or state.closed:
            self._log(JournalEntry(intent.intent_id, intent.kind, "failed",
                                   f"no open position for parent={intent.parent_trade_id}",
                                   error_type="no_parent_position"))
            return {"ok": False, "error_type": "no_parent_position"}

        meta = get_symbol_meta(state.weex_symbol, self.exchange_info) or {}
        price_prec = int(meta.get("pricePrecision", 2))

        # Resolve "breakeven" semantics
        if intent.sl is None:
            new_sl = state.entry_price
        else:
            new_sl = float(intent.sl)
        new_sl_rounded = round_price(new_sl, price_prec)

        # Validate direction (LONG: SL must be < current mark; SHORT: SL > mark)
        # Skip strict mark check in sketch; just verify SL isn't trivially zero.
        if new_sl_rounded <= 0:
            self._log(JournalEntry(intent.intent_id, intent.kind, "failed",
                                   f"SL rounded to {new_sl_rounded}",
                                   error_type="price_underflow"))
            return {"ok": False, "error_type": "price_underflow"}

        # Real flow: cancel old SL algo, place new STOP_LOSS algo
        cancel_payload = {"symbol": state.weex_symbol, "orderId": state.sl_algo_id}
        new_algo_payload = {
            "symbol": state.weex_symbol,
            "positionSide": state.position_side,
            "planType": "STOP_LOSS",
            "triggerPrice": str(new_sl_rounded),
            "quantity": f"{state.contracts}",
            "clientAlgoId": f"sl-mv-{intent.intent_id}",
            "triggerPriceType": "MARK_PRICE",
            "positionId": state.position_id,
        }
        self._log(JournalEntry(intent.intent_id, intent.kind, "validated",
                               f"move SL → {new_sl_rounded} (was {state.sl})",
                               payload={"cancel": cancel_payload, "new": new_algo_payload}))
        state.sl = new_sl_rounded
        new_algo = _mock_algo_response(new_algo_payload["clientAlgoId"])
        state.sl_algo_id = new_algo["data"]["algoId"]
        self._log(JournalEntry(intent.intent_id, intent.kind, "submitted",
                               f"sl algo replaced id={state.sl_algo_id}"))
        return {"ok": True, "new_sl": new_sl_rounded}

    def alert_on_increase(self, intent: TradeIntent) -> dict:
        """Increase events are ALERT-ONLY per Eduardo's behavior contract.

        We don't add to a position on a re-buy notification; just journal it
        for the operator dashboard.
        """
        self._log(JournalEntry(intent.intent_id, intent.kind, "suppressed",
                               f"increase suppressed (alert-only) parent={intent.parent_trade_id}",
                               error_type="alert_only"))
        return {"ok": True, "suppressed": True}

    # ── dispatch ──

    def dispatch(self, intent: TradeIntent) -> dict:
        if intent.kind == "open":
            return self.open_with_bracket(intent)
        if intent.kind == "close_full":
            return self.full_close(intent)
        if intent.kind == "close_partial":
            return self.partial_close(intent)
        if intent.kind == "move_sl":
            return self.move_sl(intent)
        if intent.kind == "increase":
            return self.alert_on_increase(intent)
        if intent.kind == "detail":
            # Pure FYI from signaler — no action.
            self._log(JournalEntry(intent.intent_id, intent.kind, "suppressed",
                                   "detail event — informational only",
                                   error_type="detail_noop"))
            return {"ok": True, "suppressed": True}
        self._log(JournalEntry(intent.intent_id, intent.kind, "failed",
                               f"unknown kind {intent.kind}",
                               error_type="unknown_kind"))
        return {"ok": False, "error_type": "unknown_kind"}


# ── Self-test ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    info_path = os.path.join(os.path.dirname(__file__), "exchange_info_cache.json")
    marks_path = os.path.join(os.path.dirname(__file__), "mark_price_cache.json")
    info = json.load(open(info_path))
    marks = json.load(open(marks_path))

    ex = DLiteExecutor(client=None, exchange_info=info, mark_price_cache=marks)

    # Smoke test with PUMP (thin tail, negative qtyPrecision, contractVal=100)
    open_intent = TradeIntent(
        intent_id="t1-open",
        symbol="PUMP",
        direction="LONG",
        kind="open",
        entry=0.00171,
        sl=0.00160,
        tp=0.00200,
        notional_usd=25.0,
    )
    print("PUMP open:", ex.dispatch(open_intent))

    partial = TradeIntent(
        intent_id="t1-p1",
        symbol="PUMP",
        direction="LONG",
        kind="close_partial",
        pct=50.0,
        parent_trade_id="t1-open",
    )
    print("PUMP partial 50:", ex.dispatch(partial))

    move = TradeIntent(
        intent_id="t1-mv",
        symbol="PUMP",
        direction="LONG",
        kind="move_sl",
        sl=None,  # breakeven
        parent_trade_id="t1-open",
    )
    print("PUMP move_sl BE:", ex.dispatch(move))

    print(f"\njournal entries: {len(ex.journal)}")
    for e in ex.journal:
        print(f"  {e.phase:11s}  {e.kind:14s}  {e.detail}")
