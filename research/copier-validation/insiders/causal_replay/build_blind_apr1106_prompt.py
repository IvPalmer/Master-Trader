"""build_blind_apr1106_prompt.py — build the BOUNDED CONTEXT a copier sees at the APRIL
attribution decision (T = msg 1106 timestamp), with the ledger CARRIED by the harness.

The April window breaks the May author-contamination. The decision point is msg 1106
(2026-04-20T09:24:31+00:00):

    "The position tapped the limit at 74,000 yesterday. My average is 75,340.
     I decided to close the part I added to keep the risk under control"

The harness presents ONLY the bounded substrate at T and stops — it interprets nothing at
1106 and reveals no answer. The BTC Long carried by the harness-owned ledger at T is built
causally from the prior April messages:

  1. msg 1078 (2026-04-18T08:19:20) opens "BTC Long (Hedge position)" — initial leg, filled
     at the oracle's last-closed candle at the opener time.
  2. msg 1103 (2026-04-19T14:15:03) "On BTC Long / Set the stop at 73,000. / Place a limit
     order at 74,000 and add +50% to the position" — moves SL to 73,000 and arms a +50% add
     leg at the 74,000 limit.
  3. the 74,000 limit leg fills "yesterday" at the first causal candle AFTER the 1103 arming
     time whose low crosses 74,000 — confirmed BEFORE T.
  4. msg 1105 (2026-04-20T09:22:36) "Update / BTC Long / Close 30% here" is an explicit,
     unambiguous prior instruction posted BEFORE the 1106 decision; the harness applies it
     causally (close_partial 30%, priced by the oracle's last closed candle at 1105's time)
     so the book is state-correct AS IT STANDS just before 1106. The 1106 trap itself is left
     entirely UNINTERPRETED — no decision is taken on it here.

The harness-owned ledger therefore carries an OPEN BTC long (size reduced to 70% by the 1105
close) whose mechanical VWAP is computed from the copier's OWN confirmed fills (oracle-priced),
independent of any figure quoted in the message stream. The bounded prompt embeds that book.

Sequence:
  1. seed the BTC long from 1078 (initial fill) + 1103 (SL move + 74000 add fill).
  2. apply msg 1105's "Close 30% here" causally via ledger.apply_intent (oracle-priced).
  3. build the BoundedPrompt at T = 1106's timestamp via feed.at(T, decision_msg_id=1106)
     over the APRIL paid_messages.json + APRIL prices/ cache.
  4. serialize + persist to runs/blind_apr1106/prompt.txt.
  5. machine-verify (and ASSERT): ZERO messages dated > T, ZERO candles ts >= the in-progress
     minute (09:24) in the serialized prompt; price snapshot last_t_ms == last closed minute
     (09:23); every ledger fill t_ms strictly before the in-progress minute.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPL = os.path.dirname(HERE)  # research/insiders_april_replication

from oracle import PointInTimeFeed, MINUTE_MS, to_ms  # noqa: E402
from ledger import PositionLedger, PositionState, Fill  # noqa: E402
from interpreter import Intent, Evidence, BoundedPrompt  # noqa: E402

MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices")          # APRIL cache (NOT prices_may)
RUN_DIR = os.path.join(HERE, "runs", "blind_apr1106")
PROMPT_PATH = os.path.join(RUN_DIR, "prompt.txt")

# --- April decision-point anchors (verified against paid_messages.json) ---
DEC_MSG_ID = 1106
T_1106 = "2026-04-20T09:24:31+00:00"   # the decision time T (msg 1106 date)
T_1078 = "2026-04-18T08:19:20+00:00"   # BTC Long hedge opener
T_1103 = "2026-04-19T14:15:03+00:00"   # SL->73000 + arms the 74,000 add leg
T_1105 = "2026-04-20T09:22:36+00:00"   # "Close 30% here" (prior, before the 1106 decision)


def ms(iso):
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)


# last fully-closed minute at T=09:24:31 is 09:23:00 (closes 09:24:00 <= T);
# the 09:24:00 minute is in-progress (closes 09:25:00 > T) and must never surface.
T_0923 = ms("2026-04-20T09:23:00+00:00")   # last fully-closed candle open-time at T
T_0924 = ms("2026-04-20T09:24:00+00:00")   # in-progress candle open-time at T (closes 09:25:00)


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


def build_btc_long(feed):
    """Construct the harness-owned BTC long as it stands at T, priced ONLY from causal candles.

    Two confirmed fills, both before T:
      - initial hedge leg (src 1078), priced at the last-closed candle at the 1078 opener time.
      - +50% add leg (armed by 1103 at the 74,000 limit), priced at the FIRST causal candle on
        2026-04-19 whose low crosses 74,000 (the 'tapped the limit at 74,000 yesterday' event).
    Mechanical confirmed-fill VWAP is computed by the ledger from these fills — it is the
    copier's OWN average, derived independently of any figure quoted in the message stream.
    """
    venue = "weex"
    # --- initial hedge fill (1078) ---
    slc_open = feed.at(T_1078, decision_msg_id=1078)
    ora_open = slc_open.prices()
    open_candle = ora_open.last_candle("BTC", venue=venue)
    init_t = int(open_candle["t"])
    init_price = float(open_candle["c"])
    init_frac = 1.0

    # --- +50% add fill at the 74,000 limit, after the 1103 arming time ---
    # the limit was placed by msg 1103 (14:15:03); search candles from the arming MINUTE forward.
    # locate the first causal candle whose low <= 74,000 using the oracle window at T.
    slc_T = feed.at(T_1106, decision_msg_id=DEC_MSG_ID)
    ora_T = slc_T.prices()
    arm_lo = (ms(T_1103) // MINUTE_MS) * MINUTE_MS    # 1103's containing minute open-time
    add_t = None
    for c in ora_T.window("BTC", arm_lo, ora_T.t_causal_ms, venue=venue):
        if float(c["l"]) <= 74000.0:
            add_t = int(c["t"])
            break
    if add_t is None:
        raise AssertionError("74,000 limit tap not found in causal window after 1103 arming")
    add_price = 74000.0     # leg fills at its limit price (low crossed it)
    add_frac = 0.5          # '+50% to the position'

    # confirmed-fill VWAP (the copier's own average, oracle-derived)
    num = init_price * init_frac + add_price * add_frac
    den = init_frac + add_frac
    avg = num / den
    filled = min(1.0, init_frac + add_frac)

    p = PositionState(
        symbol="BTC", side="long", status="open", opener_msg_id=1078,
        entry_lo=init_price, entry_hi=init_price,
        planned_legs=[
            {"price": init_price, "frac_of_planned": init_frac, "status": "filled"},
            {"price": add_price, "frac_of_planned": add_frac, "status": "filled"},
        ],
        avg=avg, filled_pct_of_planned=filled, size_pct=1.0, remaining=1.0,
        original_sl=73000.0, current_sl=73000.0,   # SL set to 73,000 by msg 1103
        tps=[],
        fills=[
            Fill(t_ms=init_t, price=init_price, frac_of_planned=init_frac,
                 src_msg_id=1078, confirmed=True),
            Fill(t_ms=add_t, price=add_price, frac_of_planned=add_frac,
                 src_msg_id=1103, confirmed=True),
        ],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=add_t,
    )
    return p


def main():
    os.makedirs(RUN_DIR, exist_ok=True)
    feed = PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")

    ledger = PositionLedger()
    ledger.seed([build_btc_long(feed)])

    # --- apply msg 1105 "Close 30% here" causally (prior decision, BEFORE 1106) ---
    # Priced by the harness's own mutator at the oracle's last closed candle at 1105's time.
    # This is an explicit, unambiguous instruction; applying it makes the book state-correct at
    # T. The 1106 trap is NOT interpreted here.
    slc_1105 = feed.at(T_1105, decision_msg_id=1105)
    ora_1105 = slc_1105.prices()
    i1105 = Intent(
        "close_partial", "BTC", "long", "close_partial",
        "BTC long open -> reduce 30% on the 1105 'Close 30% here' instruction",
        "declared-by-dennis", 0.9,
        "msg 1105 'Update / BTC Long / Close 30% here' closes 30% of the held BTC long",
        Evidence(msg_ids=[1105], candles=[]),
    )
    i1105.close_mode = "frac"
    i1105.close_frac = 0.30
    d1105 = ledger.apply_intent(i1105, ora_1105)

    # --- build the BoundedPrompt at T = 1106, BEFORE any 1106 decision is interpreted ---
    slc_T = feed.at(T_1106, decision_msg_id=DEC_MSG_ID)
    ora_T = slc_T.prices()
    symbols = ["BTC"]
    prompt = BoundedPrompt(
        T_iso=feed.msg(DEC_MSG_ID)["date"],
        messages=slc_T.messages(),
        ledger_snapshot=ledger.snapshot(),
        price_snapshot=price_snapshot_from(ora_T, symbols, "weex"),
        decision_msg_id=DEC_MSG_ID,
    )
    serialized = prompt.serialize()

    with open(PROMPT_PATH, "w") as f:
        f.write(serialized)

    # --- machine verification (ALL conditions asserted; the run fails loudly on any leak) ---
    T_ms = to_ms(feed.msg(DEC_MSG_ID)["date"])
    msg_ids = [m["id"] for m in prompt.messages]

    # (a) message-id scan: NO message dated > T anywhere in the slice; last msg is the decision.
    offending_msgs = [m["id"] for m in prompt.messages if to_ms(m["date"]) > T_ms]
    assert msg_ids[-1] == DEC_MSG_ID, f"last msg is {msg_ids[-1]}, not {DEC_MSG_ID}"
    assert 1107 not in msg_ids, "msg 1107 leaked into the bounded prompt"
    assert 1108 not in msg_ids, "msg 1108 leaked into the bounded prompt"

    # (b) candle scan over the serialized text: no candle ts >= the in-progress minute (09:24).
    future_candle_ts = []
    for tok in re.findall(r"\d{13}", serialized):
        v = int(tok)
        if 1_700_000_000_000 <= v <= 1_900_000_000_000 and v >= T_0924:
            future_candle_ts.append(v)
    snap_last_t = prompt.price_snapshot["BTC"]["last_t_ms"]
    assert snap_last_t == T_0923, f"price snapshot last_t_ms={snap_last_t}, expected 09:23={T_0923}"

    # (c) every price-snapshot last_t_ms strictly before the in-progress minute.
    snap_future = [s["last_t_ms"] for s in prompt.price_snapshot.values() if int(s["last_t_ms"]) >= T_0924]

    # (d) ledger fills must all be on candles strictly before the in-progress minute.
    fill_ts_future = []
    for pos in ledger.snapshot()["open"].values():
        for fll in pos["fills"]:
            if int(fll["t_ms"]) >= T_0924:
                fill_ts_future.append(int(fll["t_ms"]))

    verified = (len(offending_msgs) == 0
                and len(future_candle_ts) == 0
                and len(snap_future) == 0
                and len(fill_ts_future) == 0)

    # hard fail-closed: the run is VOID unless every bound holds.
    assert verified, (
        "machine-bounding FAILED: "
        f"offending_msgs={offending_msgs} future_candle_ts={future_candle_ts} "
        f"snap_future={snap_future} fill_ts_future={fill_ts_future}"
    )

    report = {
        "prompt_path": PROMPT_PATH,
        "T_iso": feed.msg(DEC_MSG_ID)["date"],
        "T_ms": T_ms,
        "decision_msg_id": DEC_MSG_ID,
        "n_messages_in_prompt": len(msg_ids),
        "first_msg_id": msg_ids[0],
        "last_msg_id": msg_ids[-1],
        "offending_future_msg_ids": offending_msgs,
        "future_candle_ts_in_prompt": future_candle_ts,
        "fill_ts_at_or_after_inprogress": fill_ts_future,
        "T_0923_ms": T_0923,
        "T_0924_ms": T_0924,
        "price_snapshot_last_t_ms": snap_last_t,
        "machine_bounded_confirmed": verified,
        "ledger_snapshot": ledger.snapshot(),
        "serialized_prompt": serialized,
    }
    print(json.dumps(report, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
