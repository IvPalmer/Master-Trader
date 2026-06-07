"""Final forensic check (codex-endorsed, not a bot): the swing trail truncated winners — so
does NO-trail pure HOLD monetize the 'channel flags medium-term movers' drift? Market entry,
hold to fixed horizon (14/30/45d), with and without a -20% catastrophic stop. UNLEVERED %.
One pass, no tuning. If negative, the lane is definitively closed."""
import json, os
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))


def hold(sig, horizon_d, cat):
    p = r.prep(sig)
    if not p:
        return None
    is_long, elo, ehi, sl0, edge, tps = p
    sym = r.fsym(sig["symbol"]); o_ms = r.ms(sig["open_date"])
    last = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=False)
    last = [c for c in last if c[0] <= o_ms + horizon_d * 86400_000]
    cand = [c for c in last if c[0] >= o_ms]
    if len(cand) < 5:
        return None
    fi = last.index(cand[0]); entry = cand[0][1]
    def ret(px): return (px - entry) / entry if is_long else (entry - px) / entry
    if cat:
        cp = entry * (1 - cat) if is_long else entry * (1 + cat)
        for (ts, o, h, l, c) in last[fi:]:
            if (l <= cp) if is_long else (h >= cp):
                return {"open": sig["open_date"], "ret": ret(cp), "dir": sig["direction"]}
    return {"open": sig["open_date"], "ret": ret(last[-1][4]), "dir": sig["direction"]}


def stats(tag, rows):
    n = len(rows)
    if not n:
        print(f"  {tag}: n=0"); return
    rs = sorted(x["ret"] for x in rows); tot = sum(rs); wins = sum(1 for x in rs if x > 0)
    cut = int(n * 0.7); oos = [x["ret"] for x in rows[cut:]]
    oosm = (sum(oos) / len(oos) * 100) if oos else 0
    print(f"  {tag:<22} n={n:<4} mean={tot/n*100:>+6.1f}%  total={tot*100:>+6.0f}%  win={wins/n*100:>4.0f}%  "
          f"median={rs[n//2]*100:>+5.1f}%  OOS mean={oosm:>+5.1f}%  drop-top={ (tot-rs[-1])*100:>+6.0f}%")


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    for cat in (0.20, None):
        print(f"\n--- catastrophic stop = {'-20%' if cat else 'NONE (pure hold)'} ---")
        for H in (14, 30, 45):
            rows = [x for x in (hold(s, H, cat) for s in usable) if x]
            rows.sort(key=lambda x: x["open"])
            stats(f"hold {H}d", rows)
            longs = [x for x in rows if x["dir"] == "long"]
            stats(f"  hold {H}d LONG", longs)


if __name__ == "__main__":
    main()
