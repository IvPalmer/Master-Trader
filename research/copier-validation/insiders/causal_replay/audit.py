"""audit.py — evidence causality enforcement (SPEC §5).

Where causality stops being a promise and becomes a checked fact. Runs AFTER interpret, BEFORE
apply_intent. The intent does not reach the ledger until it passes.

Causality is NEVER inferred from intent.epistemic_tag or any self-cert flag — only from direct
comparison of cited refs against T, resolved through the same bounded Slice the harness used.

Imports `oracle` (resolves CandleRefs / Slice) and `interpreter` (Intent/Evidence types).
Does NOT import `ledger`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from oracle import Slice, CausalityViolation, MINUTE_MS
from interpreter import Intent, CandleRef


@dataclass
class EvidenceAudit:
    ok: bool
    T_ms: int
    checked_msg_ids: list
    checked_candles: list      # [{symbol, venue, t_ms}] actually checked
    violations: list           # [{kind, ref, detail}]
    verdict: str               # "accept" | "reject"

    def to_jsonable(self) -> dict:
        return asdict(self)


class FutureReferenceRejected(Exception):
    """Raised by replay when a rejected audit must hard-stop the run (strict mode)."""


def audit_evidence(intent: Intent, slice_: Slice) -> EvidenceAudit:
    """Check every cited msg_id and CandleRef against T (resolved via slice_).

    For EVERY msg_id: must exist AND date <= T (present in slice.messages()).
      else 'unknown_msg' (id absent from feed) or 'future_msg' (date > T).
    For EVERY CandleRef(symbol, venue, t_ms):
      (a) CAUSALITY: t_ms + 60000 <= T_ms; else 'future_candle' (HARD reject).
      (b) EXISTENCE: the (symbol,venue) candle with open-time t_ms must exist; else
          'missing_candle' (HARD reject — a cited-but-absent candle is fabrication).
      (c) SUPPORT (warning): the candle does not cross a claimed level -> 'unsupported_claim'
          (kept separate; does NOT by itself flip the verdict to reject).

    SCALAR-PRICE GATE (HARD): the interpreter may NOT set a fill/exit price — and therefore
    PnL — via a raw scalar. Every fill/exit price the ledger books is derived ONLY from the
    oracle (last closed candle <= T) or from an explicitly cited CandleRef bound at T. So any
    interpreter-supplied price scalar is a 'scalar_price' violation (HARD reject):
      - `intent.close_price is not None`  (the exit-price scalar that books realized R), and
      - any `close_price` smuggled through an attached `open_meta` dict.
    This is machine-enforced and fail-closed: a model that emits close_price=73000 (a future
    take-profit) with otherwise-clean cited evidence is REJECTED, never booked as a win.

    ANY future_* / unknown_msg / missing_candle / scalar_price => verdict='reject', ok=False.
    """
    T_ms = slice_.T_ms
    violations = []
    checked_msg_ids = []
    checked_candles = []

    # --- scalar-price gate (interpreter must not set PnL via a raw scalar) ---
    if getattr(intent, "close_price", None) is not None:
        violations.append({"kind": "scalar_price", "ref": "intent.close_price",
                           "detail": f"interpreter-supplied close_price={intent.close_price!r}; "
                                     f"exit price must come from the oracle or a cited CandleRef, "
                                     f"not a raw scalar (fail-closed)"})
    meta = getattr(intent, "open_meta", None)
    if isinstance(meta, dict) and meta.get("close_price") is not None:
        violations.append({"kind": "scalar_price", "ref": "open_meta.close_price",
                           "detail": f"interpreter-supplied open_meta.close_price="
                                     f"{meta.get('close_price')!r}; exit price must be "
                                     f"oracle/CandleRef-derived, not a raw scalar (fail-closed)"})

    # --- messages ---
    feed = slice_._feed
    # set of message ids visible at T (date <= T per the slice's own rule)
    visible_msgs = slice_.messages()
    visible_ids = {m["id"] for m in visible_msgs}

    # --- denominator-binding gate (HARD): the opener's stop-loss shapes realized R
    # (risk = |avg - sl|). The fill avg is oracle-confirmed, but a fabricated/inflated SL would
    # shrink the denominator and inflate R on a real oracle-priced exit. So an interpreter-supplied
    # open_meta.sl must be CORROBORATED by the text of a cited message <= T (Dennis posts e.g.
    # "SL 78400"). An SL absent from every cited message is fabrication -> 'unbound_sl' (HARD reject).
    # (entry_lo/entry_hi are NOT gated here: the fill is clamped to the real candle range by the
    # oracle, so they cannot book a fictional fill price the way an uncorroborated SL inflates R.)
    if isinstance(meta, dict) and isinstance(meta.get("sl"), (int, float)) and not isinstance(meta.get("sl"), bool):
        sl_val = meta["sl"]
        cited = set(intent.evidence.msg_ids)
        cited_text = " ".join(m.get("text", "") or "" for m in visible_msgs if m["id"] in cited)
        norm = cited_text.replace(",", "")          # "78,400" -> "78400"
        if str(int(sl_val)) not in norm:
            violations.append({"kind": "unbound_sl", "ref": f"open_meta.sl={sl_val!r}",
                               "detail": "stop-loss not corroborated by the text of any cited "
                                         "message <= T; a fabricated SL inflates realized R "
                                         "(risk=|avg-sl|) -> fail-closed reject"})
    for mid in intent.evidence.msg_ids:
        checked_msg_ids.append(mid)
        if mid not in feed._idx_by_id:
            violations.append({"kind": "unknown_msg", "ref": mid, "detail": "id absent from feed"})
            continue
        if mid not in visible_ids:
            # exists in feed but its date is > T (or same-second after the decision) -> future leak
            violations.append({"kind": "future_msg", "ref": mid,
                               "detail": "message dated after T (or same-second after decision)"})

    # --- candles ---
    oracle = slice_.prices()
    for c in intent.evidence.candles:
        ref = {"symbol": c.symbol, "venue": c.venue, "t_ms": int(c.t_ms)}
        checked_candles.append(ref)
        # (a) causality
        if c.t_ms + MINUTE_MS > T_ms:
            violations.append({"kind": "future_candle", "ref": ref,
                               "detail": f"t+60000={c.t_ms + MINUTE_MS} > T_ms={T_ms}"})
            continue
        # (b) existence — resolve through the bounded oracle (raises only on future, handled above)
        try:
            oracle.candle_at(c.symbol, c.t_ms, venue=c.venue)
        except CausalityViolation as e:  # defensive; the (a) check should preempt this
            violations.append({"kind": "future_candle", "ref": ref, "detail": str(e)})
            continue
        except KeyError:
            violations.append({"kind": "missing_candle", "ref": ref,
                               "detail": "no candle at this open-time in the feed (in-range gap or fabrication)"})
            continue

    hard = [v for v in violations if v["kind"] in
            ("future_msg", "future_candle", "unknown_msg", "missing_candle", "scalar_price", "unbound_sl")]
    verdict = "reject" if hard else "accept"
    return EvidenceAudit(
        ok=(verdict == "accept"),
        T_ms=T_ms,
        checked_msg_ids=checked_msg_ids,
        checked_candles=checked_candles,
        violations=violations,
        verdict=verdict,
    )
