"""grade_blind_1609.py — apply + grade the BLIND 1609 (May) decision on the HARDENED substrate.

Drives the real replay() exactly as the acceptance test does (seed BTC long from 1561, mock
the 1608 close-long and the 1609 open-short to CARRY the ledger), but at the decision message
1611 it hands the harness the BLIND interpreter's *actual* returned intent (the JSON produced
by the interpreter fed only the bounded prompt — no clean-up, no oracle-supplied candle ref).

That blind intent therefore passes through the SAME machine gates a real run would:
  - audit_evidence: msg/candle refs <= T  AND  the new scalar-price gate (no raw close_price)
  - apply_intent:   close priced ONLY from the oracle's last closed candle (22:19 close 77592.2)

Then grade.py scores runs/blind_1609/ against trades_may.json (src_id 1609) with fail-closed
grading. Persists steps.jsonl / final_ledger.json / meta.json / grade.json into runs/blind_1609/.
"""

from __future__ import annotations

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPL = os.path.dirname(HERE)

from oracle import PointInTimeFeed  # noqa: E402
from ledger import PositionState, Fill  # noqa: E402
from interpreter import Intent, Evidence, MockInterpreter  # noqa: E402
from replay import replay  # noqa: E402
from grade import grade  # noqa: E402

MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices_may")
RUNS_ROOT = os.path.join(HERE, "runs")


def ms(iso):
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)


def seeded_btc_long():
    return PositionState(
        symbol="BTC", side="long", status="open", opener_msg_id=1561,
        entry_lo=76200.0, entry_hi=76950.0, planned_legs=[], avg=76575.0,
        filled_pct_of_planned=1.0, size_pct=1.0, remaining=1.0,
        original_sl=75250.0, current_sl=75250.0, tps=[79300.0],
        fills=[Fill(t_ms=ms("2026-05-18T00:26:00+00:00"), price=76575.0, frac_of_planned=1.0,
                    src_msg_id=1561, confirmed=True)],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=ms("2026-05-18T00:26:00+00:00"),
    )


# ---- the BLIND interpreter's ACTUAL returned intent (verbatim from the task) ---------------
BLIND_1611 = {
    "intent_type": "close_full",
    "action_now": "Close the open BTC short fully now, around breakeven (near entry avg "
                  "77665.65; last close 77592.2).",
    "symbol": "BTC",
    "side": "short",
    "inferred_state": "Open BTC short from msg 1609 (avg 77665.65, SL 78400, TP 73000, full "
                      "size, remaining 1.0). The signaler immediately walked it back: msg 1610 "
                      "\"No\" then msg 1611 \"Closing around be\" (breakeven). Latest message is "
                      "an explicit close-at-breakeven instruction for this just-opened short.",
    "epistemic_tag": "explicit_instruction",
    "evidence_msg_ids": [1609, 1610, 1611],
    "confidence": 0.86,
    "reasoning": "Msg 1610 'No' + msg 1611 'Closing around be' = explicit close-at-breakeven "
                 "of the only open position (BTC short from 1609). close_full, no scalar price.",
}


def blind_intent_1611() -> Intent:
    """Faithfully reconstruct the Intent dataclass from the blind interpreter's JSON.

    KEY FIDELITY POINTS (do NOT 'fix' to the mock's clean version):
      - evidence.msg_ids = [1609, 1610, 1611] exactly as the model cited; NO candle refs were
        emitted, so evidence.candles = [] (the close will be oracle-priced).
      - close_price is ABSENT in the model's JSON -> None -> scalar-price gate must pass.
      - action_now is the model's verbose prose; the ledger keys off intent_type=close_full.
    """
    return Intent(
        intent_type=BLIND_1611["intent_type"],
        symbol=BLIND_1611["symbol"],
        side=BLIND_1611["side"],
        action_now="close_full",  # canonical action token; model's prose preserved in reasoning
        inferred_state=BLIND_1611["inferred_state"],
        epistemic_tag=BLIND_1611["epistemic_tag"],
        confidence=float(BLIND_1611["confidence"]),
        reasoning=BLIND_1611["reasoning"] + " [model action_now verbatim: "
                  + BLIND_1611["action_now"] + "]",
        evidence=Evidence(msg_ids=list(BLIND_1611["evidence_msg_ids"]), candles=[]),
        # close_price intentionally omitted (None) — the model supplied no scalar exit price.
    )


def carry_ledger_table():
    """1608 close-long + 1609 open-short carry the ledger (deterministic), 1611 = BLIND intent."""
    i1608 = Intent("close_full", "BTC", "long", "close_full",
                   "seeded BTC long open -> close fully", "declared-by-dennis", 0.9,
                   "msg 1608 'Close long fully' flattens the BTC long",
                   Evidence(msg_ids=[1608], candles=[]))
    i1609 = Intent("open", "BTC", "short", "open",
                   "open BTC short", "price-confirmed", 0.85,
                   "msg 1609 opens BTC short 77300-77900 SL 78400 TP 73000",
                   Evidence(msg_ids=[1609], candles=[]))
    i1609.open_meta = {
        "entry_lo": 77300.0, "entry_hi": 77900.0, "sl": 78400.0, "tps": [73000.0],
        "legs": [{"price": 77600.0, "frac_of_planned": 1.0}],
    }
    return {1608: i1608, 1609: i1609, 1611: blind_intent_1611()}


def main():
    feed = PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")
    table = carry_ledger_table()
    decision_ids = set(table.keys())  # 1610 "No" advances clock, is not a decision

    res = replay(
        "blind_1609", feed, MockInterpreter(table), mode="strict",
        start_msg_id=1608, end_msg_id=1611,
        seed_ledger=[seeded_btc_long()], runs_root=RUNS_ROOT, relevant_symbols=["BTC"],
        decision_filter=lambda m: m["id"] in decision_ids,
    )

    run_dir = os.path.join(RUNS_ROOT, "blind_1609")
    rep = grade(run_dir)

    out = {
        "replay_result": res.to_jsonable(),
        "grade": rep.to_jsonable(),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
