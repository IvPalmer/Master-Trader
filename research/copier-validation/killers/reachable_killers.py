"""Final attack (codex round 2): REACHABLE-ENTRY subset.

+62R came from filling at the posted entry; market entry (chase) = −24R. Unresolved:
is there a subset where the posted price is genuinely REACHABLE at signal time (price is
already in/at the posted zone when the signal fires) — no chase, no adverse-selection
wait — and does THAT subset keep positive expectancy? If yes → a narrow real execution
edge. If no → copier thesis is dead.

Rule: at the signal candle, require the candle range to contain a fill price inside the
posted zone (clamp signal-open into [elo,ehi]); skip if price already past T1 or past SL.
Fill at that reachable posted price; 100% exit at T1/SL; risk=|fill-SL|; fees in R.
Chronological 70/30. Hurdle (codex): OOS mean >= +0.10R/trade, decent N, not one-window/side.
"""
import json, os
from collections import Counter
import replay_v2 as r
from momentum_killers import stats

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON_D = 14
FEE = r.FEE


def sim(sig):
    p = r.prep(sig)
    if not p:
        return ("skip", "incomplete", None)
    is_long, elo, ehi, sl0, edge, tps = p
    sym = r.fsym(sig["symbol"]); o_ms = r.ms(sig["open_date"])
    last = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=False)
    last = [c for c in last if c[0] <= o_ms + HORIZON_D * 86400_000]
    cand = [c for c in last if c[0] >= o_ms]
    if len(cand) < 5:
        return ("skip", "no_klines", None)
    fi = last.index(cand[0]); ts, o, h, l, c0 = cand[0]
    t1 = tps[0]
    # reachable posted price at signal candle
    fill = min(max(o, elo), ehi) if True else o   # clamp open into zone
    if not (l <= fill <= h):
        return ("skip", "zone_not_touched_at_signal", None)   # posted price NOT reachable now
    if (fill >= t1) if is_long else (fill <= t1):
        return ("skip", "past_t1", None)
    if (fill <= sl0) if is_long else (fill >= sl0):
        return ("skip", "past_sl", None)
    risk = abs(fill - sl0)
    if risk <= 0:
        return ("skip", "bad_risk", None)
    for (ts2, o2, h2, l2, c2) in last[fi:]:
        if (l2 <= sl0) if is_long else (h2 >= sl0):
            return ("trade", sig["direction"], (-1.0 - 2 * FEE, o_ms))
        if (h2 >= t1) if is_long else (l2 <= t1):
            R = (((t1 - fill) if is_long else (fill - t1)) / risk) - 2 * FEE
            return ("trade", sig["direction"], (R, o_ms))
    R = (((last[-1][4] - fill) if is_long else (fill - last[-1][4])) / risk) - 2 * FEE
    return ("trade", sig["direction"], (R, o_ms))


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    rows, reasons = [], Counter()
    for s in usable:
        tag, info, payload = sim(s)
        if tag == "trade":
            rows.append((payload[1], payload[0], info))  # (o_ms, R, dir)
            reasons["trade"] += 1
        else:
            reasons[info] += 1
    rows.sort(key=lambda x: x[0])
    Rs = [x[1] for x in rows]
    print(f"reachable trades = {len(rows)} / {len(usable)} usable")
    print(f"disposition: {dict(reasons)}\n")
    print(f"  ALL reachable:   {stats(Rs)}")
    print(f"  LONG:  {stats([x[1] for x in rows if x[2]=='long'])}")
    print(f"  SHORT: {stats([x[1] for x in rows if x[2]=='short'])}")
    cut = int(len(rows) * 0.70)
    tr, oos = [x[1] for x in rows[:cut]], [x[1] for x in rows[cut:]]
    print(f"\n  TRAIN (first 70%): {stats(tr)}")
    print(f"  OOS   (last 30%):  {stats(oos)}")
    if oos:
        om = sum(oos) / len(oos); srt = sorted(oos)
        print(f"\n  HURDLE: mean>=+0.10 [{om:+.3f}->{om>=0.10}]  total>0 [{sum(oos):+.1f}]  "
              f"drop-top>0 [{(sum(oos)-srt[-1])>0}]  N={len(oos)}")


if __name__ == "__main__":
    main()
