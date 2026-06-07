"""build_blind_1609_prompt.py — build the BOUNDED CONTEXT a copier sees at the BTC-1609
breakeven decision (T = msg 1611 timestamp), with the ledger CARRIED by the harness.

Sequence (matches the HARDENED substrate's btc1609 scenario, but stops to emit the prompt
the copier would face at 1611 — no interpretation of 1611, no hint of the right answer):

  1. seed the prior BTC long (src_id 1561), status open, filled.
  2. apply msg 1608 ("Close long fully") -> long closes (priced at oracle last-closed candle).
  3. apply the 1609 opener (BTC Short, Entry 77300-77900, SL 78400, Target 73000) as a watcher,
     then let the price-loop's confirm_fills price it from the closed 21:56 candle.
  4. build the BoundedPrompt at T = 1611's timestamp via feed.at(T, decision_msg_id=1611).
  5. serialize + persist to runs/blind_1609/prompt.txt.
  6. machine-verify: ZERO messages dated > T, ZERO candles ts >= 22:20 in the serialized prompt.

The ledger snapshot embedded in the prompt is the harness-owned book AS IT STANDS just before
the 1611 decision — an open BTC short, plus the closed BTC long.
"""

from __future__ import annotations

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPL = os.path.dirname(HERE)  # research/insiders_april_replication

from oracle import PointInTimeFeed, MINUTE_MS, to_ms  # noqa: E402
from ledger import PositionLedger, PositionState, Fill  # noqa: E402
from interpreter import Intent, Evidence, CandleRef, BoundedPrompt  # noqa: E402

MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices_may")
RUN_DIR = os.path.join(HERE, "runs", "blind_1609")
PROMPT_PATH = os.path.join(RUN_DIR, "prompt.txt")

T_1609 = "2026-05-21T21:56:44+00:00"   # opener message time
T_1611 = "2026-05-21T22:20:53+00:00"   # the decision time T


def ms(iso):
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)


T_2156 = ms("2026-05-21T21:56:00+00:00")   # the 21:56 fill candle open-time
T_2219 = ms("2026-05-21T22:19:00+00:00")   # last fully-closed candle at T=1611
T_2220 = ms("2026-05-21T22:20:00+00:00")   # in-progress candle at T=1611 (closes 22:21:00)


def seeded_btc_long():
    """Prior BTC LONG from src_id 1561 (opener 05-18), status open, size 1.0 (HARDENED canonical)."""
    return PositionState(
        symbol="BTC", side="long", status="open", opener_msg_id=1561,
        entry_lo=76200.0, entry_hi=76950.0, planned_legs=[], avg=76575.0,
        filled_pct_of_planned=1.0, size_pct=1.0, remaining=1.0,
        original_sl=75250.0, current_sl=75250.0, tps=[79300.0],
        fills=[Fill(t_ms=ms("2026-05-18T00:26:00+00:00"), price=76575.0, frac_of_planned=1.0,
                    src_msg_id=1561, confirmed=True)],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=ms("2026-05-18T00:26:00+00:00"),
    )


def price_snapshot_from(oracle, symbols, venue="weex"):
    snap = {}
    for sym in symbols:
        try:
            lc = oracle.last_candle(sym, venue=venue)
        except (LookupError, KeyError):
            continue
        snap[sym] = {"last_t_ms": int(lc["t"]), "last_close": float(lc["c"]),
                     "high": float(lc["h"]), "low": float(lc["l"])}
    return snap


def main():
    os.makedirs(RUN_DIR, exist_ok=True)
    feed = PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")

    ledger = PositionLedger()
    ledger.seed([seeded_btc_long()])

    # --- step 1: msg 1608 "Close long fully" closes the seeded BTC long ---
    # priced at the oracle's last-closed candle at 1608's time (harness-causal, no scalar).
    slc_1608 = feed.at(feed.msg(1608)["date"], decision_msg_id=1608)
    ora_1608 = slc_1608.prices()
    i1608 = Intent("close_full", "BTC", "long", "close_full",
                   "seeded BTC long open -> close fully", "declared-by-dennis", 0.9,
                   "msg 1608 'Close long fully' flattens the BTC long",
                   Evidence(msg_ids=[1608], candles=[]))
    d1608 = ledger.apply_intent(i1608, ora_1608)

    # --- step 2: msg 1609 opener (BTC Short, Entry 77300-77900, SL 78400, Target 73000) ---
    slc_1609 = feed.at(T_1609, decision_msg_id=1609)
    ora_1609 = slc_1609.prices()
    i1609 = Intent("open", "BTC", "short", "open",
                   "open BTC short", "price-confirmed", 0.85,
                   "msg 1609 opens BTC short 77300-77900 SL 78400 TP 73000",
                   Evidence(msg_ids=[1609], candles=[]))
    i1609.open_meta = {
        "entry_lo": 77300.0, "entry_hi": 77900.0, "sl": 78400.0, "tps": [73000.0],
        "legs": [{"price": 77600.0, "frac_of_planned": 1.0}],
    }
    d1609 = ledger.apply_intent(i1609, ora_1609)  # watcher

    # --- step 3: price-loop confirm_fills prices the watcher from the closed 21:56 candle ---
    # advance to the decision time T=1611, where 21:56 is long-closed; confirm fills causally.
    slc_T = feed.at(T_1611, decision_msg_id=1611)
    ora_T = slc_T.prices()
    d_fill = ledger.confirm_fills("BTC", ora_T, venue="weex")

    # --- step 4: build the BoundedPrompt at T = 1611, BEFORE any 1611 decision is interpreted ---
    symbols = ["BTC"]
    prompt = BoundedPrompt(
        T_iso=feed.msg(1611)["date"],
        messages=slc_T.messages(),
        ledger_snapshot=ledger.snapshot(),
        price_snapshot=price_snapshot_from(ora_T, symbols, "weex"),
        decision_msg_id=1611,
    )
    serialized = prompt.serialize()

    with open(PROMPT_PATH, "w") as f:
        f.write(serialized)

    # --- step 5: machine verification ---
    # (a) message-id scan: no id dated > T present in the slice.
    T_ms = to_ms(feed.msg(1611)["date"])
    msg_ids = [m["id"] for m in prompt.messages]
    offending_msgs = []
    for m in prompt.messages:
        if to_ms(m["date"]) > T_ms:
            offending_msgs.append(m["id"])
    # last message must be 1611; 1612/1613 must be absent.
    assert msg_ids[-1] == 1611, f"last msg is {msg_ids[-1]}, not 1611"
    assert 1612 not in msg_ids, "msg 1612 leaked into the bounded prompt"
    assert 1613 not in msg_ids, "msg 1613 leaked into the bounded prompt"

    # (b) candle scan over the serialized text: no candle ts >= 22:20 (in-progress / future).
    # The only candle ts surfaced in the prompt is the price snapshot's last_t_ms; the fill
    # candle 21:56 is recorded inside the ledger fills. Scan ALL integers that look like ms
    # epochs in the serialized prompt and confirm none is >= T_2220.
    import re
    future_candle_ts = []
    for tok in re.findall(r"\d{13}", serialized):
        v = int(tok)
        # only treat values in the candle-epoch band as candle timestamps
        if 1_700_000_000_000 <= v <= 1_900_000_000_000 and v >= T_2220:
            future_candle_ts.append(v)
    # also explicitly check the structured snapshot value
    snap_last_t = prompt.price_snapshot["BTC"]["last_t_ms"]
    assert snap_last_t == T_2219, f"price snapshot last_t_ms={snap_last_t}, expected 22:19={T_2219}"

    verified = (len(offending_msgs) == 0 and len(future_candle_ts) == 0)

    # --- emit a compact report to stdout for the wrapper ---
    report = {
        "prompt_path": PROMPT_PATH,
        "T_iso": feed.msg(1611)["date"],
        "T_ms": T_ms,
        "msg_ids_in_prompt": msg_ids,
        "offending_future_msg_ids": offending_msgs,
        "future_candle_ts_in_prompt": future_candle_ts,
        "T_2219_ms": T_2219,
        "T_2220_ms": T_2220,
        "price_snapshot_last_t_ms": snap_last_t,
        "machine_bounded_confirmed": verified,
        "ledger_deltas": {
            "1608_close_long": d1608.to_jsonable(),
            "1609_open_short": d1609.to_jsonable(),
            "fill_short": d_fill.to_jsonable(),
        },
        "ledger_snapshot": ledger.snapshot(),
        "serialized_prompt": serialized,
    }
    print(json.dumps(report, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
