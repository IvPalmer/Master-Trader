"""ledger.py — PositionLedger (harness-owned book) (SPEC §3).

The independent ground truth of "what is open." Mutated ONLY by the harness via apply_intent,
which is a PURE function of (current state, intent, bounded oracle). It uses the oracle to
price-confirm fills/stops on candles <= T; it never reads the future.

Imports `oracle` (PriceOracle for fill/stop confirmation, and CausalityViolation type).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from oracle import PriceOracle, MINUTE_MS


class ScalarPriceForbidden(Exception):
    """Raised when an interpreter-supplied scalar fill/exit price reaches the ledger.

    The ledger derives every fill/exit price ONLY from the oracle (last closed candle <= T) or
    from an explicitly cited, audited CandleRef bound at T. A raw scalar from the interpreter is
    rejected fail-closed by audit.audit_evidence BEFORE apply_intent runs; this exception is the
    defense-in-depth backstop for any caller that bypassed the audit.
    """


# --------------------------------------------------------------------------- #
# Data shapes                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class Fill:
    t_ms: int                 # open-time of the CLOSED candle that confirmed the fill (causal)
    price: float              # fill price (limit price, or entry-zone edge for a market-style fill)
    frac_of_planned: float    # this fill's share of the original PLANNED signal size (legs sum <= 1.0)
    src_msg_id: int           # the message that declared the leg/entry
    confirmed: bool           # True iff price-confirmed by a closed candle; declared-only => False


@dataclass
class PositionState:
    symbol: str
    side: str                 # "long" | "short"
    status: str               # "watcher" | "open" | "closed"
    opener_msg_id: int
    entry_lo: float
    entry_hi: float
    planned_legs: list        # [{price, frac_of_planned, status: "filled"|"watcher_unfilled"}]
    avg: Optional[float]      # size-weighted avg of CONFIRMED fills; None while pure watcher
    filled_pct_of_planned: float   # sum of confirmed legs' frac_of_planned (0..1)
    size_pct: float           # current OPEN size as fraction of copier-held original (0..1)
    remaining: float          # alias of size_pct (harness/sim convention name)
    original_sl: float
    current_sl: Optional[float]
    tps: list
    fills: list               # list[Fill]
    realized_R: float         # cumulative realized PnL in R units of original risk
    closed_at_msg_id: Optional[int]
    last_event_t_ms: int
    declared_unconfirmed: bool = False  # flagged when a Dennis-declared fill lacks candle support

    def to_jsonable(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class LedgerDelta:
    """Describes exactly what changed in one apply_intent (for persistence + grading)."""

    symbol: Optional[str] = None
    kind: str = "none"        # "open"|"fill"|"close_partial"|"close_full"|"sl_move"|"none"
    detail: dict = field(default_factory=dict)

    def to_jsonable(self) -> dict:
        return {"symbol": self.symbol, "kind": self.kind, "detail": self.detail}


# --------------------------------------------------------------------------- #
# PositionLedger                                                              #
# --------------------------------------------------------------------------- #
class PositionLedger:
    """All positions keyed by symbol. One live position per symbol at a time.

    A re-open after a close starts a fresh PositionState; history retained in a closed-list.
    """

    def __init__(self):
        self._open = {}     # symbol -> PositionState (status watcher|open)
        self._closed = []   # list[PositionState] (status closed)

    # -- seeding / construction ------------------------------------------- #
    def seed(self, positions: list):
        for p in positions:
            self._open[p.symbol] = p

    # -- readers ----------------------------------------------------------- #
    def get(self, symbol: str) -> Optional[PositionState]:
        return self._open.get(symbol)

    def open_positions(self) -> list:
        return [p for p in self._open.values()]

    def closed_positions(self) -> list:
        return list(self._closed)

    def snapshot(self) -> dict:
        """Read-only JSON-serializable view of all positions, deterministic key order."""
        return {
            "open": {sym: self._open[sym].to_jsonable() for sym in sorted(self._open.keys())},
            "closed": [p.to_jsonable() for p in self._closed],
        }

    # -- pricing helpers --------------------------------------------------- #
    @staticmethod
    def _risk(p: PositionState) -> float:
        base = p.avg if p.avg is not None else (p.entry_lo + p.entry_hi) / 2.0
        return abs(base - p.original_sl)

    @staticmethod
    def _pnl_R(p: PositionState, exit_price: float, frac: float) -> float:
        risk = PositionLedger._risk(p)
        if risk == 0:
            return 0.0
        base = p.avg if p.avg is not None else (p.entry_lo + p.entry_hi) / 2.0
        if p.side == "short":
            move = base - exit_price
        else:
            move = exit_price - base
        return (move / risk) * frac

    # -- fill confirmation (used by replay price-loop + opener) ----------- #
    def confirm_fills(self, symbol: str, oracle: PriceOracle, venue: str = "weex") -> LedgerDelta:
        """Try to flip a watcher to open by price-confirming its legs on CLOSED candles.

        Market-style fill: the FIRST closed candle at/after the opener showing price inside the
        entry zone for the trade's side fills the position at the entry-zone edge.
        Limit legs: a leg flips to 'filled' when a causal candle's [l,h] crosses its limit.
        Returns a LedgerDelta describing any new fill.
        """
        p = self._open.get(symbol)
        if p is None or p.status not in ("watcher",):
            return LedgerDelta(symbol=symbol, kind="none")
        # find first closed candle at/after the opener whose range is inside the entry zone
        try:
            t_causal = oracle.t_causal_ms
        except LookupError:
            return LedgerDelta(symbol=symbol, kind="none")
        candles = oracle.window(symbol, p.last_event_t_ms, t_causal, venue=venue)
        for c in candles:
            lo = float(c["l"])
            hi = float(c["h"])
            # market-style fill: candle traded inside the entry zone
            if hi >= p.entry_lo and lo <= p.entry_hi:
                # fill at the entry-zone edge appropriate for the side
                if p.side == "short":
                    fill_price = min(p.entry_hi, max(p.entry_lo, hi))  # short fills as price rises into zone
                else:
                    fill_price = max(p.entry_lo, min(p.entry_hi, lo))
                # use the midpoint of the touched range clamped to the zone for stability
                clamped_hi = min(hi, p.entry_hi)
                clamped_lo = max(lo, p.entry_lo)
                fill_price = (clamped_lo + clamped_hi) / 2.0
                self._do_fill(p, fill_price, float(c["t"]), frac_of_planned=1.0, confirmed=True)
                return LedgerDelta(
                    symbol=symbol,
                    kind="fill",
                    detail={"price": fill_price, "t_ms": int(c["t"]), "confirmed": True},
                )
        return LedgerDelta(symbol=symbol, kind="none")

    def _do_fill(self, p: PositionState, price: float, t_ms: int, frac_of_planned: float, confirmed: bool):
        p.fills.append(Fill(t_ms=int(t_ms), price=float(price), frac_of_planned=float(frac_of_planned),
                            src_msg_id=p.opener_msg_id, confirmed=confirmed))
        # confirmed-fill VWAP
        conf = [f for f in p.fills if f.confirmed]
        if conf:
            num = sum(f.price * f.frac_of_planned for f in conf)
            den = sum(f.frac_of_planned for f in conf)
            p.avg = num / den if den else price
            p.filled_pct_of_planned = min(1.0, sum(f.frac_of_planned for f in conf))
        else:
            p.avg = price
            p.filled_pct_of_planned = frac_of_planned
        p.status = "open"
        p.size_pct = 1.0       # 100% of copier-held original
        p.remaining = 1.0
        p.last_event_t_ms = max(p.last_event_t_ms, int(t_ms))
        if not confirmed:
            p.declared_unconfirmed = True

    # -- the ONLY mutator -------------------------------------------------- #
    def apply_intent(self, intent, oracle: PriceOracle) -> LedgerDelta:
        it = intent.intent_type
        sym = intent.symbol

        if it in ("commentary", "abstain"):
            return LedgerDelta(symbol=sym, kind="none")

        if it in ("open", "open_partial"):
            return self._apply_open(intent, oracle)

        # the remaining intents operate on an existing position
        p = self._open.get(sym)
        if p is None:
            # nothing to act on; treat as no-op (attribution failure is a grading concern)
            return LedgerDelta(symbol=sym, kind="none")

        if it == "sl_to":
            return self._apply_sl(p, intent)
        if it == "close_partial":
            return self._apply_close_partial(p, intent, oracle)
        if it == "close_full":
            return self._apply_close_full(p, intent, oracle)
        return LedgerDelta(symbol=sym, kind="none")

    def _apply_open(self, intent, oracle: PriceOracle) -> LedgerDelta:
        sym = intent.symbol
        # build planned legs from structured fields if present, else a single market leg
        legs = []
        entry_lo = None
        entry_hi = None
        sl = None
        tps = []
        meta = getattr(intent, "open_meta", None)
        if meta:
            entry_lo = meta.get("entry_lo")
            entry_hi = meta.get("entry_hi")
            sl = meta.get("sl")
            tps = meta.get("tps", [])
            for leg in meta.get("legs", [{"price": (entry_lo + entry_hi) / 2.0, "frac_of_planned": 1.0}]):
                legs.append({"price": leg["price"], "frac_of_planned": leg["frac_of_planned"],
                             "status": "watcher_unfilled"})
        else:
            entry_lo = entry_hi = oracle.last_price(sym)
            sl = entry_lo
            legs = [{"price": entry_lo, "frac_of_planned": 1.0, "status": "watcher_unfilled"}]

        # decision time = oracle.T_ms; opener's own minute not yet closed -> last_event = opener msg minute
        opener_t = (oracle.T_ms // MINUTE_MS) * MINUTE_MS  # the opener's containing minute open-time
        p = PositionState(
            symbol=sym, side=intent.side, status="watcher", opener_msg_id=intent.evidence.msg_ids[-1]
            if intent.evidence.msg_ids else 0,
            entry_lo=entry_lo, entry_hi=entry_hi, planned_legs=legs, avg=None,
            filled_pct_of_planned=0.0, size_pct=0.0, remaining=0.0,
            original_sl=sl, current_sl=sl, tps=list(tps), fills=[], realized_R=0.0,
            closed_at_msg_id=None, last_event_t_ms=opener_t,
        )
        self._open[sym] = p
        return LedgerDelta(symbol=sym, kind="open",
                           detail={"side": intent.side, "entry_lo": entry_lo, "entry_hi": entry_hi, "sl": sl})

    def _apply_sl(self, p: PositionState, intent) -> LedgerDelta:
        target = intent.sl_to
        breakeven = p.avg if p.avg is not None else (p.entry_lo + p.entry_hi) / 2.0
        if target == "breakeven" or (target is None and intent.action_now == "sl_move"):
            p.current_sl = breakeven
        elif isinstance(target, (int, float)) and not isinstance(target, bool):
            p.current_sl = float(target)
        return LedgerDelta(symbol=p.symbol, kind="sl_move", detail={"current_sl": p.current_sl})

    def _apply_close_partial(self, p: PositionState, intent, oracle: PriceOracle) -> LedgerDelta:
        if p.status != "open":
            return LedgerDelta(symbol=p.symbol, kind="none")
        before = p.size_pct
        mode = intent.close_mode or "frac"
        frac = intent.close_frac if intent.close_frac is not None else 0.0
        if mode == "frac":
            closed = min(frac, p.size_pct)            # fraction of HELD-ORIGINAL
        elif mode == "frac_of_remaining":
            closed = frac * p.size_pct                # fraction of CURRENT remaining
        else:
            raise ValueError(f"unknown close_mode {mode!r}")
        exit_price = self._close_ref_price(p, intent, oracle)
        p.realized_R += self._pnl_R(p, exit_price, closed)
        p.size_pct -= closed
        p.remaining = p.size_pct
        return LedgerDelta(symbol=p.symbol, kind="close_partial",
                           detail={"mode": mode, "frac": frac, "closed_of_held": closed,
                                   "size_pct_before": before, "size_pct_after": p.size_pct,
                                   "exit_price": exit_price})

    def _apply_close_full(self, p: PositionState, intent, oracle: PriceOracle) -> LedgerDelta:
        if p.status not in ("open", "watcher"):
            return LedgerDelta(symbol=p.symbol, kind="none")
        exit_price = self._close_ref_price(p, intent, oracle)
        remaining = p.size_pct
        realized_now = self._pnl_R(p, exit_price, remaining) if p.status == "open" else 0.0
        p.realized_R += realized_now
        p.size_pct = 0.0
        p.remaining = 0.0
        p.status = "closed"
        p.closed_at_msg_id = intent.evidence.msg_ids[-1] if intent.evidence.msg_ids else None
        # move to closed-list
        self._closed.append(p)
        if self._open.get(p.symbol) is p:
            del self._open[p.symbol]
        return LedgerDelta(symbol=p.symbol, kind="close_full",
                           detail={"exit_price": exit_price, "closed_of_held": remaining,
                                   "realized_R_step": realized_now, "realized_R_total": p.realized_R,
                                   "closed_at_msg_id": p.closed_at_msg_id})

    def _close_ref_price(self, p: PositionState, intent, oracle: PriceOracle) -> float:
        """Close reference price — the close of the last FULLY-CLOSED candle at T (oracle.last_price,
        i.e. t_causal's close). Never the in-progress (T-containing) candle, and never a price the
        interpreter chose. This is the only objective "close at now" execution reference.

        Soundness: the interpreter may NOT influence the booked exit price (and thus PnL) at all.
          - A raw `intent.close_price` / `open_meta.close_price` scalar is a HARD audit reject
            (audit.audit_evidence, kind 'scalar_price') before apply_intent runs. If one bypasses
            the audit and reaches here we RAISE rather than book a fictional fill.
          - We do NOT let the model price-shop by citing a *favorable* historical causal candle:
            an exit is always priced at the last closed candle, so a CandleRef the model cites is
            evidence (audited for causality/existence) but never the exit price. A CandleRef that
            does coincide with t_causal yields the same value as oracle.last_price by construction.

        NOTE (residual, by design): opener entry_lo/entry_hi/sl from `open_meta` are the
        interpreter's *extraction of contemporaneous Dennis message facts* (e.g. "Entry 77300-77900
        / SL 78400"), not prices it invents — and they cannot book a fictional win because the FILL
        is oracle-confirmed (clamped to the real candle range) and the EXIT is oracle-only here.
        They shape the R *denominator* (|avg - sl|); if a future threat model needs those gated
        too, audit them against the cited opener message text. Out of scope for the close-price gap.
        """
        if getattr(intent, "close_price", None) is not None:
            raise ScalarPriceForbidden(
                f"interpreter-supplied close_price={intent.close_price!r} reached the ledger; "
                f"exit price must be the oracle's last closed candle (audit should have rejected "
                f"this fail-closed)."
            )
        meta = getattr(intent, "open_meta", None)
        if isinstance(meta, dict) and meta.get("close_price") is not None:
            raise ScalarPriceForbidden(
                f"interpreter-supplied open_meta.close_price={meta.get('close_price')!r} reached "
                f"the ledger; exit price must be the oracle's last closed candle (fail-closed)."
            )
        # oracle reference ONLY: close of the last fully-closed candle at T (no model price-shopping)
        return oracle.last_price(p.symbol)
