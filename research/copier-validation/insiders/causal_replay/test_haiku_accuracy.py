"""Test whether HAIKU is accurate enough vs the cached SONNET reference on the discriminating
cases. Same harness, same bounded prompts, same ledger state (advanced via the cached sonnet
intents for non-sampled msgs). Calls haiku ONLY on a sample of the hardest messages. Caches to a
separate haiku/ dir so it's resumable and never re-burns.
"""
import os, sys, json, glob, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
REPL = os.path.dirname(HERE)
MSGS = os.path.join(REPL, "paid_export", "paid_messages.json")
PRICES = os.path.join(REPL, "prices_may")

from oracle import PointInTimeFeed
from ledger import PositionLedger
from interpreter import ClaudeCliInterpreter, BoundedPrompt, intent_from_dict
from audit import audit_evidence
import run_full_may as R   # reuse candidate_msgs / price_loop

SONNET_CACHE = os.path.join(HERE, "runs", "full_may", "cache")
HAIKU_CACHE = os.path.join(HERE, "runs", "full_may", "haiku")
os.makedirs(HAIKU_CACHE, exist_ok=True)

VPS_HAIKU = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "ubuntu@100.96.225.124",
             "docker exec -i elder-brain-bot claude -p --output-format json --model haiku"]

def load_sonnet():
    out = {}
    for f in glob.glob(os.path.join(SONNET_CACHE, "*.json")):
        mid = int(os.path.basename(f)[:-5])
        try:
            out[mid] = intent_from_dict(ClaudeCliInterpreter._extract_intent_json(open(f).read()))
        except Exception:
            pass
    return out

def haiku_call(interp, prompt, mid):
    cf = os.path.join(HAIKU_CACHE, f"{mid}.json")
    if os.path.exists(cf):
        return intent_from_dict(ClaudeCliInterpreter._extract_intent_json(open(cf).read()))
    intent = interp.interpret(prompt)
    open(cf, "w").write(interp.last_raw_stdout or "")
    return intent

def main():
    feed = PointInTimeFeed(MSGS, PRICES, as_of_policy="closed_minute")
    cands = R.candidate_msgs(feed)
    msgs = {m["id"]: m for m in json.load(open(MSGS))}
    truth = json.load(open(os.path.join(REPL, "trades_may.json")))
    openers = {t["src_id"] for t in truth if t.get("src_id")}
    sonnet = load_sonnet()
    done_ids = set(sonnet)

    # SAMPLE = the discriminating hard cases within the done window:
    #   all curated openers + recaps/commentary + the 1609 trap (1611) + a few closes
    lo, hi = min(done_ids), max(done_ids)
    sample = set(o for o in openers if lo <= o <= hi)         # openers (incl. two-part SL-only replies)
    for mid in (1473, 1493, 1517, 1518, 1545, 1555, 1611, 1494, 1511, 1515):
        if mid in done_ids:
            sample.add(mid)
    sample = sorted(sample)

    interp = ClaudeCliInterpreter(model="haiku", cmd_override=VPS_HAIKU, timeout_s=180)
    led = PositionLedger()
    syms = set()
    rows = []
    for m in cands:
        mid = m["id"]
        if mid not in done_ids:
            continue   # only within the window we have sonnet for
        slc = feed.at(m["date"], decision_msg_id=mid)
        oracle = slc.prices()
        R.price_loop(led, oracle, list(syms))
        prompt = BoundedPrompt(T_iso=m["date"], messages=slc.messages(),
                               ledger_snapshot=led.snapshot(), price_snapshot={}, decision_msg_id=mid)
        if mid in sample:
            try:
                h = haiku_call(interp, prompt, mid)
            except Exception as e:
                rows.append({"id": mid, "err": f"{type(e).__name__}:{e}"}); break
            s = sonnet[mid]
            ea = audit_evidence(h, slc)
            rows.append({"id": mid, "text": (msgs[mid]["text"] or "")[:60].replace("\n", " "),
                         "haiku": h.intent_type, "sonnet": s.intent_type,
                         "match": h.intent_type == s.intent_type,
                         "is_opener": mid in openers,
                         "haiku_open_ok": (mid in openers and h.intent_type in ("open", "open_partial")),
                         "haiku_audit": ea.verdict})
            adv = h   # advance ledger with haiku's call on sampled msgs
        else:
            adv = sonnet[mid]   # advance with cached sonnet on the rest (keeps state realistic)
        if adv.symbol: syms.add(adv.symbol.upper())
        ea2 = audit_evidence(adv, slc)
        if ea2.verdict == "accept":
            try: led.apply_intent(adv, oracle)
            except Exception: pass

    graded = [r for r in rows if "haiku" in r]
    n = len(graded)
    match = sum(1 for r in graded if r["match"])
    openers_in_sample = [r for r in graded if r["is_opener"]]
    opener_ok = sum(1 for r in openers_in_sample if r["haiku_open_ok"])
    audit_clean = sum(1 for r in graded if r["haiku_audit"] == "accept")
    summary = {
        "sample_size": n,
        "haiku_vs_sonnet_match": f"{match}/{n}" + (f" = {100*match//n}%" if n else ""),
        "haiku_opener_catch": f"{opener_ok}/{len(openers_in_sample)}",
        "haiku_audit_clean": f"{audit_clean}/{n}",
        "mismatches": [r for r in graded if not r["match"]],
        "all_rows": graded,
    }
    json.dump(summary, open("/tmp/haiku_test.json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in summary.items() if k != "all_rows"}, indent=1, default=str))

if __name__ == "__main__":
    main()
