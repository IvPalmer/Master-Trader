"""The one hypothesis the forensic implies (PRE-REGISTERED, no tuning): the channel finds
multi-day MOVERS but scalps them to death. So treat each signal as a SWING entry — wide
catastrophic stop, let it run, trail off the peak — instead of tight-SL+near-T1. Does
capturing the fat tail of +50-150% moves beat the drawdowns on the losers?

PRE-REGISTERED single config (changing these post-hoc = data mining):
  entry  = market at signal-candle open, direction as signaled
  cat-stop = -20% underlying from entry (wide; alts swing 15-20%)
  trail  = arm at +10% favorable; then exit if price gives back 25% of (peak-entry) from peak
  horizon = 45d, else close at last
  return = UNLEVERED underlying % (×L for margin; wide stop => low L, 2-3x max)
  OOS: chronological 70/30. Report mean %/trade, win%, total, drop-top, median.
"""
import json, os
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON_D = 45
CAT = 0.20      # catastrophic stop
ARM = 0.10      # arm trail after +10%
GB = 0.25       # giveback fraction of (peak-entry)


def swing(sig):
    p = r.prep(sig)
    if not p:
        return None
    is_long, elo, ehi, sl0, edge, tps = p
    sym = r.fsym(sig["symbol"]); o_ms = r.ms(sig["open_date"])
    last = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=False)
    last = [c for c in last if c[0] <= o_ms + HORIZON_D * 86400_000]
    cand = [c for c in last if c[0] >= o_ms]
    if len(cand) < 5:
        return None
    fi = last.index(cand[0]); entry = cand[0][1]
    cat = entry * (1 - CAT) if is_long else entry * (1 + CAT)
    peak = entry
    def ret(px): return (px - entry) / entry if is_long else (entry - px) / entry
    exit_px = last[-1][4]; note = "horizon"
    for (ts, o, h, l, c) in last[fi:]:
        # catastrophic stop first (conservative)
        if (l <= cat) if is_long else (h >= cat):
            exit_px = cat; note = "cat"; break
        peak = max(peak, h) if is_long else min(peak, l)
        armed = ret(peak) >= ARM
        if armed:
            trail = peak - GB * (peak - entry) if is_long else peak + GB * (entry - peak)
            if (l <= trail) if is_long else (h >= trail):
                exit_px = trail; note = "trail"; break
    return {"sym": sig["symbol"], "dir": sig["direction"], "open": sig["open_date"],
            "ret": ret(exit_px), "note": note}


def stats(tag, rows):
    n = len(rows)
    if not n:
        print(f"  {tag}: n=0"); return
    rs = sorted(r_["ret"] for r_ in rows)
    tot = sum(rs); wins = sum(1 for x in rs if x > 0)
    med = rs[n // 2]
    drop1 = (tot - rs[-1])
    print(f"  {tag:<14} n={n:<4} mean={tot/n*100:>+6.1f}%  total={tot*100:>+7.0f}%  win={wins/n*100:>4.0f}%  "
          f"median={med*100:>+5.1f}%  drop-top total={drop1*100:>+6.0f}%")


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    rows = [x for x in (swing(s) for s in usable) if x]
    rows.sort(key=lambda x: x["open"])
    print(f"swing-overlay (cat -{CAT*100:.0f}%, trail {GB*100:.0f}% giveback armed +{ARM*100:.0f}%, {HORIZON_D}d), UNLEVERED:\n")
    stats("ALL", rows)
    stats("LONG", [x for x in rows if x["dir"] == "long"])
    stats("SHORT", [x for x in rows if x["dir"] == "short"])
    cut = int(len(rows) * 0.70)
    stats("TRAIN 70%", rows[:cut])
    stats("OOS 30%", rows[cut:])
    from collections import Counter
    print(f"\n  exit reasons: {dict(Counter(x['note'] for x in rows))}")
    # top contributors
    top = sorted(rows, key=lambda x: x["ret"], reverse=True)[:8]
    print("  top winners:", ", ".join(f"{x['sym']}{'+' if x['ret']>0 else ''}{x['ret']*100:.0f}%" for x in top))


if __name__ == "__main__":
    main()
