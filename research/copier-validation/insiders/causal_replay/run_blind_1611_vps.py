"""Focused, LOGGED blind proof of the BTC-1609 breakeven TRAP via the REAL LLM (VPS container).

Local `claude -p` token is expired; route to the VPS elder-brain-bot container (live Max auth).
Scope: the load-bearing DECISION is at msg 1611 ("Closing around be"). We seed the carried BTC
short (opened 1609, avg ~77650, SL 78400, TP 73000) into the harness-owned ledger, build the
bounded prompt at T=1611 (msgs<=T, ledger snapshot, prices<=22:19), and let the REAL model decide
with NO future data. Persist raw model stdout + intent + audit (closes the chain-of-custody gap).

Trap: a blind model that reads "Closing around be" should CLOSE at breakeven; one that ignores it
rides to a phantom +5.75R TP (BTC only hit 73000 on 05-28, 7 days later). The model cannot see
that future — the oracle makes it unreachable.
"""
import os, sys, json, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
REPL = os.path.dirname(HERE)
MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices_may")

from oracle import PointInTimeFeed
from ledger import PositionLedger, PositionState, Fill
from interpreter import ClaudeCliInterpreter, BoundedPrompt
from audit import audit_evidence

def ms(iso): return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)
T_1611 = "2026-05-21T22:20:53+00:00"
T_2156 = ms("2026-05-21T21:56:00+00:00")

VPS_CMD = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "ubuntu@100.96.225.124",
           "docker exec -i elder-brain-bot claude -p --output-format json --model sonnet"]

OUT = os.path.join(HERE, "runs", "blind_1611_vps"); os.makedirs(OUT, exist_ok=True)

def carried_btc_short():
    return PositionState(
        symbol="BTC", side="short", status="open", opener_msg_id=1609,
        entry_lo=77300.0, entry_hi=77900.0, planned_legs=[], avg=77650.0,
        filled_pct_of_planned=1.0, size_pct=1.0, remaining=1.0,
        original_sl=78400.0, current_sl=78400.0, tps=[73000.0],
        fills=[Fill(t_ms=T_2156, price=77650.0, frac_of_planned=1.0, src_msg_id=1609, confirmed=True)],
        realized_R=0.0, closed_at_msg_id=None, last_event_t_ms=T_2156,
    )

def main():
    rec = {"ok": False}
    feed = PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")
    led = PositionLedger(); led.seed([carried_btc_short()])
    slc = feed.at(T_1611, decision_msg_id=1611)
    oracle = slc.prices()
    msgs = slc.messages()
    # machine-confirm bounded: no msg/candle after T
    T_ms = oracle.T_ms
    future_msgs = [m["id"] for m in msgs if ms(m["date"]) > T_ms]
    prompt = BoundedPrompt(T_iso=T_1611, messages=msgs, ledger_snapshot=led.snapshot(),
                           price_snapshot={"BTC": {"last_t_ms": oracle.last_candle("BTC")["t"],
                                                   "last_close": oracle.last_candle("BTC")["c"]}},
                           decision_msg_id=1611)
    open(os.path.join(OUT, "prompt.txt"), "w").write(prompt.serialize())
    rec["bounded_ok"] = (len(future_msgs) == 0)
    rec["last_msg_id"] = msgs[-1]["id"]
    rec["future_msgs_in_prompt"] = future_msgs
    rec["last_candle_close_le_2219"] = oracle.last_candle("BTC")["c"]

    interp = ClaudeCliInterpreter(model="sonnet", cmd_override=VPS_CMD, timeout_s=180)
    try:
        intent = interp.interpret(prompt)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["raw_stdout"] = (interp.last_raw_stdout or "")[:2000]
        json.dump(rec, open(os.path.join(OUT, "result.json"), "w"), indent=2, default=str)
        print(json.dumps(rec, indent=2, default=str)[:1500]); return
    # persist raw + intent
    open(os.path.join(OUT, "raw_stdout.json"), "w").write(interp.last_raw_stdout or "")
    ea = audit_evidence(intent, slc)
    # apply
    delta = led.apply_intent(intent, oracle)
    p = None
    for cp in led.closed_positions():
        if cp.symbol == "BTC" and cp.side == "short": p = cp
    rec.update({
        "ok": True,
        "intent_type": intent.intent_type, "action_now": intent.action_now, "side": intent.side,
        "epistemic_tag": intent.epistemic_tag, "confidence": intent.confidence,
        "evidence_msg_ids": intent.evidence.msg_ids,
        "close_price_scalar": intent.close_price,
        "audit_verdict": ea.verdict, "audit_violations": [v["kind"] for v in ea.violations],
        "reasoning": intent.reasoning[:600],
        "btc_short_closed": (p is not None and p.status == "closed"),
        "realized_R": (p.realized_R if p else None),
        "caught_breakeven": (p is not None and p.realized_R is not None and abs(p.realized_R) <= 0.15),
    })
    json.dump({**rec, "intent": intent.to_jsonable(), "audit": ea.to_jsonable()},
              open(os.path.join(OUT, "result.json"), "w"), indent=2, default=str)
    print(json.dumps(rec, indent=2, default=str))

if __name__ == "__main__":
    main()
