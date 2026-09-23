import json, sys, laya
Q = json.load(open(sys.argv[3]))
ag = laya.load("convaiinnovations/laya", subfolder="typed-decisions")
with open(sys.argv[2], "w") as out:
    for l in open(sys.argv[1]):
        r = json.loads(l)
        o = ag.predict(r["state"], Q)["answers"]["direction"]["probabilities"]
        b, s = o.get("buy", 0), o.get("sell", 0)
        out.write(json.dumps({"block": r["block"], "pBuy": b / (b + s) if b + s else 0.5}) + "\n")
