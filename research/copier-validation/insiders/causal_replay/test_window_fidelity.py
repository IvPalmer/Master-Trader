"""Does the WINDOWED prompt (last40/48h) keep fidelity on the hardest cases vs the full-history
prompt? Re-decide a few discriminating msgs with the window, compare to cached full-prompt sonnet.
Cache to window_test/ (resumable, no re-burn). ~6 calls.
"""
import os, sys, json, glob
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
REPL=os.path.dirname(HERE)
from oracle import PointInTimeFeed
from ledger import PositionLedger
from interpreter import ClaudeCliInterpreter, BoundedPrompt, intent_from_dict
import run_full_may as R

FULL=os.path.join(HERE,"runs","full_may","cache")
WT=os.path.join(HERE,"runs","full_may","window_test"); os.makedirs(WT,exist_ok=True)
VPS=["ssh","-o","BatchMode=yes","-o","ConnectTimeout=15","ubuntu@100.96.225.124",
     "docker exec -i elder-brain-bot claude -p --output-format json --model sonnet"]

# the discriminating set: the 1609 trap (1611), two-part SL-only openers, a recap, a stopped-close
HARD=[1611, 1499, 1552, 1561, 1473, 1493]

def full_intent(mid):
    f=os.path.join(FULL,f"{mid}.json")
    if not os.path.exists(f): return None
    return intent_from_dict(ClaudeCliInterpreter._extract_intent_json(open(f).read())).intent_type

def main():
    feed=PointInTimeFeed(R.MSGS,R.PRICES,as_of_policy="closed_minute")
    cands=R.candidate_msgs(feed)
    msgs={m["id"]:m for m in json.load(open(R.MSGS))}
    interp=ClaudeCliInterpreter(model="sonnet",cmd_override=VPS,timeout_s=180)
    # advance ledger with cached full-prompt sonnet up to each hard msg (realistic state)
    sonnet={}
    for f in glob.glob(os.path.join(FULL,"*.json")):
        mid=int(os.path.basename(f)[:-5])
        try: sonnet[mid]=intent_from_dict(ClaudeCliInterpreter._extract_intent_json(open(f).read()))
        except: pass
    led=PositionLedger(); syms=set(); rows=[]
    for m in cands:
        mid=m["id"]
        if mid not in sonnet: continue
        slc=feed.at(m["date"],decision_msg_id=mid); oracle=slc.prices()
        R.price_loop(led,oracle,list(syms))
        if mid in HARD:
            cf=os.path.join(WT,f"{mid}.json")
            if os.path.exists(cf):
                wi=intent_from_dict(ClaudeCliInterpreter._extract_intent_json(open(cf).read()))
            else:
                bp=BoundedPrompt(T_iso=m["date"],messages=slc.messages(last_n=40,within_ms=48*3600*1000),
                                 ledger_snapshot=led.snapshot(),price_snapshot={},decision_msg_id=mid)
                try: wi=interp.interpret(bp)
                except Exception as e: rows.append({"id":mid,"err":str(e)}); break
                open(cf,"w").write(interp.last_raw_stdout or "")
            fi=full_intent(mid)
            rows.append({"id":mid,"text":(msgs[mid]["text"] or "")[:55].replace("\n"," "),
                         "windowed":wi.intent_type,"full_sonnet":fi,"match":wi.intent_type==fi})
        adv=sonnet[mid]
        if adv.symbol: syms.add(adv.symbol.upper())
        from audit import audit_evidence
        if audit_evidence(adv,slc).verdict=="accept":
            try: led.apply_intent(adv,oracle)
            except: pass
    graded=[r for r in rows if "windowed" in r]
    match=sum(1 for r in graded if r["match"])
    out={"n":len(graded),"match":f"{match}/{len(graded)}","rows":graded}
    json.dump(out,open("/tmp/window_fidelity.json","w"),indent=1,default=str)
    print(json.dumps(out,indent=1,default=str))

if __name__=="__main__": main()
