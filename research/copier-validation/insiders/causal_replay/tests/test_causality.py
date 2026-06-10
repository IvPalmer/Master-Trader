"""tests/test_causality.py — the 8 causality unit tests (SPEC §9).

Deterministic, no Claude (MockInterpreter only). Each maps to an invariant. Run under the
default `closed_minute` policy.

    python3 -m pytest causal_replay/tests/ -q
"""

from __future__ import annotations

import datetime
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from oracle import PointInTimeFeed, CausalityViolation, to_ms, MINUTE_MS  # noqa: E402
from ledger import PositionLedger, PositionState, Fill, ScalarPriceForbidden  # noqa: E402
from interpreter import Intent, Evidence, CandleRef, BoundedPrompt, MockInterpreter  # noqa: E402
from audit import audit_evidence, FutureReferenceRejected  # noqa: E402
from replay import replay  # noqa: E402

REPL = os.path.dirname(PKG)  # research/insiders_april_replication
MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices_may")


def ms(iso):
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)


# canonical timestamps from the verified data
T_1609 = "2026-05-21T21:56:44+00:00"
T_1611 = "2026-05-21T22:20:53+00:00"
T_2055 = ms("2026-05-21T21:55:00+00:00")  # candle open-time 21:55
T_2156 = ms("2026-05-21T21:56:00+00:00")  # candle open-time 21:56 (the fill candle)
T_2219 = ms("2026-05-21T22:19:00+00:00")  # last closed candle at 1611
T_2220 = ms("2026-05-21T22:20:00+00:00")  # in-progress candle at 1611 (closes 22:21:00)
T_0528 = ms("2026-05-28T12:00:00+00:00")  # far future (BTC@73000 region)


@pytest.fixture(scope="module")
def feed():
    return PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")


# --------------------------------------------------------------------------- #
# 1. test_oracle_raises_on_future (I1)                                        #
# --------------------------------------------------------------------------- #
def test_oracle_raises_on_future(feed):
    slc = feed.at(T_1611, decision_msg_id=1611)
    ora = slc.prices()

    # in-progress 22:20 candle (closes 22:21:00 > T) -> RAISE
    with pytest.raises(CausalityViolation):
        ora.candle_at("BTC", T_2220, venue="weex")
    # far-future 05-28 candle -> RAISE
    with pytest.raises(CausalityViolation):
        ora.candle_at("BTC", T_0528, venue="weex")
    # window upper bound in the future -> RAISE the whole call
    with pytest.raises(CausalityViolation):
        ora.window("BTC", T_2156, T_2220, venue="weex")
    # touched with since_ms in the future -> RAISE
    with pytest.raises(CausalityViolation):
        ora.touched("BTC", 78400, "above", since_ms=T_0528, venue="weex")

    # boundary: the 22:19 candle (closed at 22:20:00 <= T) returns correctly (no false positive)
    c = ora.candle_at("BTC", T_2219, venue="weex")
    assert c["c"] == 77592.2
    # and last_candle is exactly 22:19 (t_causal)
    assert ora.t_causal_ms == T_2219
    assert ora.last_candle("BTC", venue="weex")["t"] == T_2219


# --------------------------------------------------------------------------- #
# 2. test_messages_time_gated_and_tiebroken                                   #
# --------------------------------------------------------------------------- #
def test_messages_time_gated_and_tiebroken(feed):
    msgs = feed.at(T_1611, decision_msg_id=1611).messages()
    ids = [m["id"] for m in msgs]
    # INVARIANT 1: nothing after T
    assert 1612 not in ids
    assert 1613 not in ids
    # INVARIANT 3: decision message is exactly the last element
    assert ids[-1] == 1611
    # 1610 ("No", same minute, posted just before 1611) is present; the opener 1609 is present
    assert 1609 in ids
    assert 1610 in ids


# --------------------------------------------------------------------------- #
# 3. test_future_evidence_intent_rejected (I3)                                #
# --------------------------------------------------------------------------- #
def test_future_evidence_intent_rejected(feed):
    slc = feed.at(T_1611, decision_msg_id=1611)
    # cheater cites a 05-28 future candle AND msg 1612 (after T)
    cheater = Intent(
        "close_full", "BTC", "short", "close_full", "cheat", "price-confirmed", 0.9, "peeked",
        Evidence(msg_ids=[1609, 1612],
                 candles=[CandleRef("BTC", "weex", T_0528)]),
    )
    ea = audit_evidence(cheater, slc)
    assert ea.verdict == "reject"
    assert ea.ok is False
    kinds = {v["kind"] for v in ea.violations}
    assert "future_candle" in kinds
    assert "future_msg" in kinds

    # a cited candle that does not exist in the feed -> missing_candle (HARD reject)
    bogus = Intent(
        "close_full", "BTC", "short", "close_full", "cheat", "price-confirmed", 0.9, "fab",
        Evidence(msg_ids=[1609], candles=[CandleRef("BTC", "weex", T_2219 + 7)]),  # off-grid ts
    )
    ea2 = audit_evidence(bogus, slc)
    assert ea2.verdict == "reject"
    assert any(v["kind"] == "missing_candle" for v in ea2.violations)

    # in strict replay, the cheater hard-stops the run
    table = {1611: cheater}
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FutureReferenceRejected):
            replay("cheat_run", feed, MockInterpreter(table), mode="strict",
                   start_msg_id=1611, end_msg_id=1611, runs_root=td, relevant_symbols=["BTC"])


# --------------------------------------------------------------------------- #
# 4. test_clean_evidence_intent_accepted (I3 complement)                      #
# --------------------------------------------------------------------------- #
def test_clean_evidence_intent_accepted(feed):
    slc = feed.at(T_1611, decision_msg_id=1611)
    honest = Intent(
        "close_full", "BTC", "short", "close_full", "close at be", "declared-by-dennis", 0.9,
        "Closing around be => full exit at breakeven",
        Evidence(msg_ids=[1609, 1611],
                 candles=[CandleRef("BTC", "weex", T_2219), CandleRef("BTC", "weex", T_2156)]),
    )
    ea = audit_evidence(honest, slc)
    assert ea.verdict == "accept"
    assert ea.violations == []
    assert ea.ok is True


# --------------------------------------------------------------------------- #
# 5. test_ledger_compounding_math (I5)                                        #
# --------------------------------------------------------------------------- #
def test_ledger_compounding_math(feed):
    # a filled ETH short, size_pct starts at 1.0 (filled_pct_of_planned = 0.25, treated as 100% held)
    p = PositionState(
        symbol="ETH", side="short", status="open", opener_msg_id=1615,
        entry_lo=2128.0, entry_hi=2191.0, planned_legs=[], avg=2128.0,
        filled_pct_of_planned=0.25, size_pct=1.0, remaining=1.0,
        original_sl=2221.0, current_sl=2221.0, tps=[1930.0],
        fills=[Fill(t_ms=0, price=2128.0, frac_of_planned=0.25, src_msg_id=1615, confirmed=True)],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=0,
    )
    led = PositionLedger()
    led.seed([p])

    class _StubOracle:
        T_ms = 0

        def last_price(self, symbol, venue="weex"):
            return 2066.43  # in-profit price, irrelevant to the fraction math
    ora = _StubOracle()

    # 1627 "Close 30%" (bare -> of held) -> 0.70
    led.apply_intent(Intent("close_partial", "ETH", "short", "close_partial", "", "declared-by-dennis",
                            0.9, "", Evidence([1627], []), close_mode="frac", close_frac=0.30), ora)
    assert abs(led.get("ETH").size_pct - 0.70) < 1e-9
    # 1632 "Close 20% of remaining" -> 0.56
    led.apply_intent(Intent("close_partial", "ETH", "short", "close_partial", "", "declared-by-dennis",
                            0.9, "", Evidence([1632], []), close_mode="frac_of_remaining", close_frac=0.20), ora)
    assert abs(led.get("ETH").size_pct - 0.56) < 1e-9
    # 1635 "Close 30% of remaining" -> 0.392
    led.apply_intent(Intent("close_partial", "ETH", "short", "close_partial", "", "declared-by-dennis",
                            0.9, "", Evidence([1635], []), close_mode="frac_of_remaining", close_frac=0.30), ora)
    assert abs(led.get("ETH").size_pct - 0.392) < 1e-9

    # denominator split: filled_pct_of_planned stays 0.25 (planned), size_pct is the held-original
    assert abs(led.get("ETH").filled_pct_of_planned - 0.25) < 1e-9


# --------------------------------------------------------------------------- #
# helpers for the acceptance / watcher tests                                  #
# --------------------------------------------------------------------------- #
def _seeded_btc_long():
    """The prior BTC LONG from src_id 1561 (opener 05-18), status open, size 1.0."""
    return PositionState(
        symbol="BTC", side="long", status="open", opener_msg_id=1561,
        entry_lo=76200.0, entry_hi=76950.0, planned_legs=[], avg=76575.0,
        filled_pct_of_planned=1.0, size_pct=1.0, remaining=1.0,
        original_sl=75250.0, current_sl=75250.0, tps=[79300.0],
        fills=[Fill(t_ms=ms("2026-05-18T00:26:00+00:00"), price=76575.0, frac_of_planned=1.0,
                    src_msg_id=1561, confirmed=True)],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=ms("2026-05-18T00:26:00+00:00"),
    )


def _btc1609_mock_table():
    """MockInterpreter table for the §8 window: 1608 close-long, 1609 open-short, 1611 close-full."""
    # 1608 "Close long fully" -> close the seeded BTC long fully (Dennis close price unknown ->
    # ledger uses the last-closed-candle ref price; R math irrelevant to the PASS check on 1609)
    i1608 = Intent("close_full", "BTC", "long", "close_full",
                   "seeded BTC long open -> close fully", "declared-by-dennis", 0.9,
                   "msg 1608 'Close long fully' flattens the BTC long",
                   Evidence(msg_ids=[1608], candles=[]))
    # 1609 opener: BTC short, entry 77300-77900, SL 78400, TP 73000
    i1609 = Intent("open", "BTC", "short", "open",
                   "open BTC short", "price-confirmed", 0.85,
                   "msg 1609 opens BTC short 77300-77900 SL 78400 TP 73000",
                   Evidence(msg_ids=[1609], candles=[]))
    # attach opener metadata the ledger reads via getattr(intent, "open_meta", None)
    i1609.open_meta = {
        "entry_lo": 77300.0, "entry_hi": 77900.0, "sl": 78400.0, "tps": [73000.0],
        "legs": [{"price": 77600.0, "frac_of_planned": 1.0}],
    }
    # 1611 "Closing around be" -> close_full at the last-closed-candle ref (22:19 close 77592.2)
    i1611 = Intent("close_full", "BTC", "short", "close_full",
                   "BTC short live, close at breakeven", "declared-by-dennis", 0.9,
                   "msg 1611 'Closing around be' => full exit; SL/TP never touched",
                   Evidence(msg_ids=[1609, 1611],
                            candles=[CandleRef("BTC", "weex", T_2219)]))
    return {1608: i1608, 1609: i1609, 1611: i1611}


# --------------------------------------------------------------------------- #
# 6. test_mock_1609_books_breakeven (acceptance, deterministic)               #
# --------------------------------------------------------------------------- #
def test_mock_1609_books_breakeven(feed):
    table = _btc1609_mock_table()
    decision_ids = set(table.keys())  # {1608, 1609, 1611}; 1610 "No" advances clock, no decision
    with tempfile.TemporaryDirectory() as td:
        res = replay("btc1609_mock", feed, MockInterpreter(table), mode="strict",
                     start_msg_id=1608, end_msg_id=1611,
                     seed_ledger=[_seeded_btc_long()], runs_root=td, relevant_symbols=["BTC"],
                     decision_filter=lambda m: m["id"] in decision_ids)
        # all audits clean (strict didn't raise)
        assert res.audits_rejected == 0
        # final BTC short realized within +/-0.15R of 0 (breakeven)
        btc_R = res.final_R.get("BTC")
        assert btc_R is not None
        assert abs(btc_R) <= 0.15, f"BTC realized_R={btc_R} not breakeven"

        # criterion 1: the seeded BTC long was closed at 1608 (non-vacuous attribution)
        import json
        steps = [json.loads(l) for l in open(os.path.join(td, "btc1609_mock", "steps.jsonl"))]
        step_1608 = next(s for s in steps if s["decision_msg_id"] == 1608)
        closed_after_1608 = {p["symbol"]: p for p in step_1608["ledger_snapshot"]["closed"]}
        assert "BTC" in closed_after_1608
        assert closed_after_1608["BTC"]["side"] == "long"
        assert closed_after_1608["BTC"]["closed_at_msg_id"] == 1608

        # criterion 2: the 1609 BTC short closed at 1611
        step_1611 = next(s for s in steps if s["decision_msg_id"] == 1611)
        # after 1611, BTC short is in closed list
        closed_after_1611 = [p for p in step_1611["ledger_snapshot"]["closed"]
                             if p["symbol"] == "BTC" and p["side"] == "short"]
        assert closed_after_1611, "BTC short not closed after 1611"
        short = closed_after_1611[-1]
        assert short["status"] == "closed"
        assert short["closed_at_msg_id"] == 1611
        # the short DID fill (avg near ~77650 inside the entry zone)
        assert short["avg"] is not None
        assert 77300.0 <= short["avg"] <= 77900.0

        # criterion 3+4: 1611 evidence causal-clean, no future ref
        ea = step_1611["evidence_audit"]
        assert ea["verdict"] == "accept"
        assert ea["violations"] == []
        for c in ea["checked_candles"]:
            assert c["t_ms"] <= T_2219, f"future candle cited: {c}"


# --------------------------------------------------------------------------- #
# 7. test_watcher_fill_requires_confirmation                                  #
# --------------------------------------------------------------------------- #
def test_watcher_fill_requires_confirmation(feed):
    # An opener whose entry zone the closed candles NEVER reach stays watcher, size 0.
    # Use a BTC short with an absurd entry zone far above the 77.5-77.7k band.
    led = PositionLedger()
    slc = feed.at(T_1611, decision_msg_id=1611)
    ora = slc.prices()
    unreachable = Intent("open", "BTC", "short", "open", "", "price-confirmed", 0.5, "",
                         Evidence([1609], []))
    unreachable.open_meta = {"entry_lo": 90000.0, "entry_hi": 91000.0, "sl": 92000.0,
                             "tps": [80000.0], "legs": [{"price": 90500.0, "frac_of_planned": 1.0}]}
    led.apply_intent(unreachable, ora)
    led.confirm_fills("BTC", ora, venue="weex")
    p = led.get("BTC")
    assert p.status == "watcher"
    assert p.size_pct == 0.0
    # a close on an unfilled watcher is a no-op
    delta = led.apply_intent(
        Intent("close_full", "BTC", "short", "close_full", "", "declared-by-dennis", 0.9, "",
               Evidence([1611], [])), ora)
    # close_full of a watcher books 0 R (no realized PnL since never filled)
    assert led.closed_positions()[-1].realized_R == 0.0 if led.closed_positions() else True

    # a reachable entry zone DOES fill on a closed candle
    led2 = PositionLedger()
    reachable = Intent("open", "BTC", "short", "open", "", "price-confirmed", 0.85, "",
                       Evidence([1609], []))
    reachable.open_meta = {"entry_lo": 77300.0, "entry_hi": 77900.0, "sl": 78400.0,
                           "tps": [73000.0], "legs": [{"price": 77600.0, "frac_of_planned": 1.0}]}
    # apply the opener at its own message time (21:56:44), as replay does, so its minute is 21:56
    slc_open = feed.at(T_1609, decision_msg_id=1609)
    led2.apply_intent(reachable, slc_open.prices())
    # then the price-loop advances: confirm fills on a later slice (21:58:30) where 21:56/21:57 closed
    slc2 = feed.at("2026-05-21T21:58:30+00:00", decision_msg_id=1609)
    ora2 = slc2.prices()
    led2.confirm_fills("BTC", ora2, venue="weex")
    p2 = led2.get("BTC")
    assert p2.status == "open"
    assert p2.size_pct == 1.0
    assert p2.avg is not None and 77300.0 <= p2.avg <= 77900.0

    # a Dennis-declared fill with NO supporting candle flips to open but flagged declared_unconfirmed
    led3 = PositionLedger()
    far = PositionState(symbol="BTC", side="short", status="watcher", opener_msg_id=1609,
                        entry_lo=90000.0, entry_hi=91000.0, planned_legs=[], avg=None,
                        filled_pct_of_planned=0.0, size_pct=0.0, remaining=0.0,
                        original_sl=92000.0, current_sl=92000.0, tps=[80000.0], fills=[],
                        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=T_2156)
    led3.seed([far])
    led3._do_fill(far, price=90500.0, t_ms=T_2156, frac_of_planned=1.0, confirmed=False)
    assert far.status == "open"
    assert far.declared_unconfirmed is True
    assert far.fills[-1].confirmed is False


# --------------------------------------------------------------------------- #
# 8. test_no_global_state (I2)                                                #
# --------------------------------------------------------------------------- #
def test_no_global_state(feed):
    # Two Slices at different T answer independently.
    s_early = feed.at("2026-05-21T22:00:30+00:00", decision_msg_id=1609)  # only ~21:59 closed
    s_late = feed.at(T_1611, decision_msg_id=1611)
    assert s_early.prices().t_causal_ms < s_late.prices().t_causal_ms
    assert s_early.prices().last_candle("BTC")["t"] != s_late.prices().last_candle("BTC")["t"]

    # Mutating one ledger does not affect another.
    a = PositionLedger()
    b = PositionLedger()
    a.seed([_seeded_btc_long()])
    assert a.get("BTC") is not None
    assert b.get("BTC") is None

    # BoundedPrompt carries no path/oracle/clock — only bounded data.
    bp = BoundedPrompt(T_iso=T_1611, messages=s_late.messages(), ledger_snapshot=a.snapshot(),
                       price_snapshot={"BTC": {"last_t_ms": T_2219, "last_close": 77592.2}},
                       decision_msg_id=1611)
    fields = set(bp.__dict__.keys())
    assert fields == {"T_iso", "messages", "ledger_snapshot", "price_snapshot", "decision_msg_id"}
    # no attribute is a feed/oracle/slice handle
    for v in bp.__dict__.values():
        assert not isinstance(v, (PointInTimeFeed,))
    # serialization is a pure string
    assert isinstance(bp.serialize(), str)


# --------------------------------------------------------------------------- #
# 9. test_scalar_price_cheat_rejected (scalar-price audit gap closed)         #
# --------------------------------------------------------------------------- #
def test_scalar_price_cheat_rejected(feed):
    """An intent that closes the 1609 BTC short at close_price=73000 (the TP, never touched in
    the window — BTC only hit 73000 on 05-28, 7 days later) with OTHERWISE-CLEAN cited evidence
    must be REJECTED fail-closed: the auditor flags a 'scalar_price' violation, the ledger refuses
    to book it, and a strict replay voids the whole run. It must never book the fictional ~8R win.
    """
    slc = feed.at(T_1611, decision_msg_id=1611)

    # --- layer 1: the auditor rejects the scalar exit price even with clean cited evidence ---
    cheater = Intent(
        "close_full", "BTC", "short", "close_full",
        "BTC short live, close at the target", "declared-by-dennis", 0.95,
        "msg 1611 — book the short at TP 73000",  # plausible prose; the lie is the scalar price
        Evidence(msg_ids=[1609, 1611],
                 candles=[CandleRef("BTC", "weex", T_2219)]),  # the cited candle is real + causal
        close_price=73000.0,  # <-- the cheat: a raw take-profit scalar that would book a fat win
    )
    ea = audit_evidence(cheater, slc)
    assert ea.verdict == "reject"
    assert ea.ok is False
    kinds = {v["kind"] for v in ea.violations}
    assert "scalar_price" in kinds, f"scalar close_price not caught: {ea.violations}"
    # the cited msg/candle evidence itself is clean — the ONLY reason for rejection is the scalar
    assert "future_candle" not in kinds
    assert "future_msg" not in kinds
    assert "missing_candle" not in kinds
    assert "unknown_msg" not in kinds

    # --- layer 2: the ledger is a fail-closed backstop (raises if the scalar reaches it) ---
    led = PositionLedger()
    short = PositionState(
        symbol="BTC", side="short", status="open", opener_msg_id=1609,
        entry_lo=77300.0, entry_hi=77900.0, planned_legs=[], avg=77650.0,
        filled_pct_of_planned=1.0, size_pct=1.0, remaining=1.0,
        original_sl=78400.0, current_sl=78400.0, tps=[73000.0],
        fills=[Fill(t_ms=T_2156, price=77650.0, frac_of_planned=1.0, src_msg_id=1609, confirmed=True)],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=T_2156,
    )
    led.seed([short])
    with pytest.raises(ScalarPriceForbidden):
        led.apply_intent(cheater, slc.prices())
    # the position was NOT closed and NO PnL was booked off the scalar
    p = led.get("BTC")
    assert p is not None and p.status == "open"
    assert p.realized_R == 0.0

    # --- layer 3: end-to-end strict replay VOIDS the run (no fictional win booked) ---
    table = _btc1609_mock_table()
    table[1611] = cheater  # swap the honest close for the scalar cheat
    decision_ids = {1608, 1609, 1611}
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FutureReferenceRejected):
            replay("scalar_cheat_run", feed, MockInterpreter(table), mode="strict",
                   start_msg_id=1608, end_msg_id=1611,
                   seed_ledger=[_seeded_btc_long()], runs_root=td, relevant_symbols=["BTC"],
                   decision_filter=lambda m: m["id"] in decision_ids)
        # the offending step was persisted then the run voided; the BTC short was NEVER booked
        # as a closed multi-R win.
        import json
        steps = [json.loads(l) for l in open(os.path.join(td, "scalar_cheat_run", "steps.jsonl"))]
        step_1611 = next(s for s in steps if s["decision_msg_id"] == 1611)
        assert step_1611["evidence_audit"]["verdict"] == "reject"
        assert any(v["kind"] == "scalar_price" for v in step_1611["evidence_audit"]["violations"])
        # no ledger delta was applied for the rejected scalar-cheat step
        assert step_1611["ledger_delta"] is None
        closed_btc_short = [p for p in step_1611["ledger_snapshot"]["closed"]
                            if p["symbol"] == "BTC" and p["side"] == "short"]
        assert not closed_btc_short, "scalar-cheat short must NOT be booked as a closed win"

    # --- contrast: the honest 1611 (no scalar) still books breakeven cleanly ---
    honest = _btc1609_mock_table()[1611]
    assert honest.close_price is None
    ea_ok = audit_evidence(honest, slc)
    assert ea_ok.verdict == "accept"
    assert ea_ok.violations == []


# --------------------------------------------------------------------------- #
# 10. test_unbound_sl_rejected (denominator-binding gate closed)              #
# --------------------------------------------------------------------------- #
def test_unbound_sl_rejected(feed):
    """The R denominator is |avg - sl|. The fill avg is oracle-confirmed, but the opener's SL is
    interpreter-supplied — a fabricated/inflated SL shrinks risk and inflates realized R on a real
    oracle-priced exit. So open_meta.sl MUST be corroborated by the text of a cited message <= T.
    Dennis's real 1609 post says "SL 78400" (in msg 1609); a cheater citing 1609 but supplying a
    fabricated sl=70000 (absent from the message) is REJECTED 'unbound_sl', fail-closed.
    """
    slc_open = feed.at(T_1609, decision_msg_id=1609)

    # honest opener: sl 78400 IS in msg 1609's text, cited -> corroborated, no unbound_sl
    honest_open = _btc1609_mock_table()[1609]
    assert honest_open.open_meta["sl"] == 78400.0
    ea_ok = audit_evidence(honest_open, slc_open)
    assert not any(v["kind"] == "unbound_sl" for v in ea_ok.violations), ea_ok.violations

    # cheater opener: same cited evidence (msg 1609) but a fabricated tighter SL that inflates R
    cheat_open = Intent(
        "open", "BTC", "short", "open", "open BTC short", "price-confirmed", 0.85,
        "msg 1609 opens BTC short — but I'll claim a tighter SL to shrink risk",
        Evidence(msg_ids=[1609], candles=[]),
    )
    cheat_open.open_meta = {"entry_lo": 77300.0, "entry_hi": 77900.0, "sl": 70000.0,
                            "tps": [73000.0], "legs": [{"price": 77600.0, "frac_of_planned": 1.0}]}
    ea = audit_evidence(cheat_open, slc_open)
    assert ea.verdict == "reject"
    assert ea.ok is False
    kinds = {v["kind"] for v in ea.violations}
    assert "unbound_sl" in kinds, f"fabricated SL not caught: {ea.violations}"


# --------------------------------------------------------------------------- #
# 11. test_model_derived_open_meta_flows (open leg from JSON, not seeded)     #
# --------------------------------------------------------------------------- #
def test_model_derived_open_meta_flows(feed):
    """The interpreter (not the harness) derives the opener: open_meta arrives via intent_from_dict
    from model JSON, the audit corroborates the SL against cited text, and the ledger opens a
    watcher that fills on a real candle. This closes WF#4 caveat #2 (open leg was seeded)."""
    from interpreter import intent_from_dict
    slc_open = feed.at(T_1609, decision_msg_id=1609)

    # a model JSON dict (as if parsed from the CLI) opening the BTC short with SL 78400 (real, in 1609)
    d = {
        "intent_type": "open", "symbol": "BTC", "side": "short", "action_now": "open",
        "inferred_state": "open BTC short per msg 1609", "epistemic_tag": "declared-by-dennis",
        "confidence": 0.85, "reasoning": "msg 1609 opens BTC short 77300-77900 SL 78400 TP 73000",
        "evidence": {"msg_ids": [1609], "candles": []},
        "open_meta": {"entry_lo": 77300.0, "entry_hi": 77900.0, "sl": 78400.0,
                      "tps": [73000.0], "legs": [{"price": 77600.0, "frac_of_planned": 1.0}]},
    }
    intent = intent_from_dict(d)
    assert intent.open_meta is not None and intent.open_meta["sl"] == 78400.0
    # audit: SL 78400 IS in cited msg 1609 -> no unbound_sl
    ea = audit_evidence(intent, slc_open)
    assert not any(v["kind"] == "unbound_sl" for v in ea.violations), ea.violations
    assert ea.verdict == "accept", ea.violations

    # ledger opens the position from the model-derived meta (watcher), then fills on a closed candle
    led = PositionLedger()
    led.apply_intent(intent, slc_open.prices())
    p = led.get("BTC")
    assert p is not None and p.side == "short"
    assert p.original_sl == 78400.0
    slc2 = feed.at("2026-05-21T21:58:30+00:00", decision_msg_id=1609)
    led.confirm_fills("BTC", slc2.prices(), venue="weex")
    p = led.get("BTC")
    assert p.status == "open" and p.size_pct == 1.0
    assert p.avg is not None and 77300.0 <= p.avg <= 77900.0
