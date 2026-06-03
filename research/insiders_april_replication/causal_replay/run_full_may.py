"""Full-May streaming replay — the SCALE test. Streams every candidate decision message in the
May 10-29 window through TWO interpreters on the IDENTICAL causal harness:
  - the REAL LLM interpreter (routed to the VPS elder-brain-bot container; local token expired)
  - RegexBaselineInterpreter (the deliberately-dumb stateless comparator)

Same oracle, same fill/exit pricing, same R math, same audit — the ONLY difference is the
interpreter. Isolates "does LLM interpretation + state-tracking beat stateless regex" on the full
book, not hand-picked traps.

Causality: at each decision the interpreter sees ONLY the bounded prompt (msgs<=T, ledger snapshot,
prices<=T). Every cited ref is audited <=T; scalar prices + uncorroborated SLs are fail-closed.

RESUMABLE: each LLM raw stdout is cached to cache/<msg_id>.json. On restart cached calls load
instantly; the ledger is rebuilt by replaying in order. A quota/auth death mid-run just resumes.

Fidelity focus: grades INTERPRETATION (intent-type + state tracking + correct abstention) and
causal cleanliness, not PnL precision. Between-message hard-SL auto-triggering is NOT modeled
(message-driven closes only) — a known PnL caveat (Dennis's "got stopped" posts drive those via msg).
"""
import os, sys, json, datetime, re
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
REPL = os.path.dirname(HERE)
MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices_may")

from oracle import PointInTimeFeed
from ledger import PositionLedger
from interpreter import (ClaudeCliInterpreter, BoundedPrompt, intent_from_dict, Intent, Evidence)
from baseline import RegexBaselineInterpreter
from audit import audit_evidence

VPS_CMD = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "ubuntu@100.96.225.124",
           "docker exec -i elder-brain-bot claude -p --output-format json --model sonnet"]

WIN_LO = "2026-05-10T00:00:00+00:00"
WIN_HI = "2026-05-29T23:59:59+00:00"
OUT = os.path.join(HERE, "runs", "full_may")
CACHE = os.path.join(OUT, "cache")
os.makedirs(CACHE, exist_ok=True)

KW = re.compile(r"\b(long|short|close|closing|closed|sl|stop|stopped|breakeven|\bbe\b|add|adding|"
                r"loaded|target|entry|tp|take|trim|reduce|avg|average|fully|position)\b", re.I)

def ms(iso): return int(datetime.datetime.fromisoformat(iso.replace("Z","+00:00")).timestamp()*1000)

def candidate_msgs(feed):
    lo, hi = ms(WIN_LO), ms(WIN_HI)
    out = []
    for date_ms, idx, m in feed._messages:
        if lo <= date_ms <= hi and (m.get("text") or "").strip() and KW.search(m["text"]):
            out.append(m)
    return out

def price_loop(led, oracle, symbols, venue="weex"):
    for s in symbols:
        p = led.get(s)
        if p is not None and p.status == "watcher":
            try: led.confirm_fills(s, oracle, venue=venue)
            except Exception: pass

def cached_llm(interp, prompt, mid):
    cf = os.path.join(CACHE, f"{mid}.json")
    if os.path.exists(cf):
        raw = open(cf).read()
        try:
            return intent_from_dict(ClaudeCliInterpreter._extract_intent_json(raw)), None
        except Exception as e:
            return None, f"cache-parse:{e}"
    try:
        intent = interp.interpret(prompt)
        open(cf, "w").write(interp.last_raw_stdout or "")
        return intent, None
    except Exception as e:
        if interp.last_raw_stdout:
            open(cf + ".err", "w").write(interp.last_raw_stdout)
        return None, f"{type(e).__name__}:{e}"

def run_stream(feed, cands, interp, is_llm):
    led = PositionLedger()
    steps = []
    syms_seen = set()
    for m in cands:
        T = m["date"]; mid = m["id"]
        slc = feed.at(T, decision_msg_id=mid)
        oracle = slc.prices()
        price_loop(led, oracle, list(syms_seen))
        # WINDOWED prompt: show the model only the recent context (last 40 msgs / 48h) — the
        # harness-owned ledger snapshot already carries older position state, so re-sending the
        # full Jan->T history (~70k tokens/call) is pure waste. Windowing is post-causal-gate
        # (can only shrink the <=T set), so it cannot leak future data. audit.py still resolves
        # cited ids against the FULL feed, so a cite outside the window is verified, not rejected.
        prompt = BoundedPrompt(T_iso=T, messages=slc.messages(last_n=40, within_ms=48*3600*1000),
                               ledger_snapshot=led.snapshot(), price_snapshot={},
                               decision_msg_id=mid)
        if is_llm:
            intent, err = cached_llm(interp, prompt, mid)
            if intent is None:
                return steps, led, err   # checkpoint + bail (resumable)
        else:
            intent = interp.interpret(prompt)
        if intent.symbol: syms_seen.add(intent.symbol.upper())
        ea = audit_evidence(intent, slc)
        applied = False; apperr = None
        if ea.verdict == "accept":
            try: led.apply_intent(intent, oracle); applied = True
            except Exception as e: apperr = f"{type(e).__name__}:{e}"
        steps.append({"msg_id": mid, "T": T, "text": (m.get("text") or "")[:140],
                      "intent_type": intent.intent_type, "symbol": intent.symbol,
                      "side": intent.side, "action": intent.action_now,
                      "epistemic": intent.epistemic_tag, "audit": ea.verdict,
                      "violations": [v["kind"] for v in ea.violations],
                      "applied": applied, "apperr": apperr})
    return steps, led, None

def summarize(led):
    closed = [{"symbol": p.symbol, "side": p.side, "opener": p.opener_msg_id,
               "closed_at": p.closed_at_msg_id, "R": round(p.realized_R, 4)}
              for p in led.closed_positions()]
    total = sum(p.realized_R for p in led.closed_positions())
    return {"closed": closed, "n_closed": len(closed), "total_realized_R": round(total, 4)}

def tally(steps):
    t = {}
    for s in steps: t[s["intent_type"]] = t.get(s["intent_type"], 0) + 1
    return t

def main():
    feed = PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")
    cands = candidate_msgs(feed)
    meta = {"window": [WIN_LO, WIN_HI], "n_candidates": len(cands),
            "first_id": cands[0]["id"] if cands else None,
            "last_id": cands[-1]["id"] if cands else None}
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=2)

    # baseline (fast, deterministic)
    b_steps, b_led, _ = run_stream(feed, cands, RegexBaselineInterpreter(), is_llm=False)
    json.dump({"steps": b_steps, "ledger": summarize(b_led)},
              open(os.path.join(OUT, "baseline.json"), "w"), indent=2, default=str)

    # LLM via VPS (resumable)
    interp = ClaudeCliInterpreter(model="sonnet", cmd_override=VPS_CMD, timeout_s=180)
    l_steps, l_led, err = run_stream(feed, cands, interp, is_llm=True)
    done = len(l_steps)
    json.dump({"steps": l_steps, "ledger": summarize(l_led),
               "stopped_early": err, "n_done": done, "n_total": len(cands)},
              open(os.path.join(OUT, "llm.json"), "w"), indent=2, default=str)

    summary = {"meta": meta, "n_candidates": len(cands),
               "baseline_intent_types": tally(b_steps), "baseline_ledger": summarize(b_led),
               "llm_done": done, "llm_stopped_early": err,
               "llm_intent_types": tally(l_steps),
               "llm_audit_rejects": sum(1 for s in l_steps if s["audit"] == "reject"),
               "llm_ledger": summarize(l_led)}
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))
    if err:
        print(f"\n[stopped early: {err} — {done}/{len(cands)} done; re-run to resume from cache]")
    else:
        print(f"\n[COMPLETE: {done}/{len(cands)} LLM decisions]")

if __name__ == "__main__":
    main()
