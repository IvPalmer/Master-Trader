"""Codex check: does same-candle TP-first (vs conservative SL-first) rescue Killers
T1-exit? Quantify ambiguous same-candle trades + the totR delta. Risk-sized R
(leverage-independent), de-biased residual (horizon ride; channel close ignored to
isolate the entry/SL/T1 mechanics). Offline (cached klines)."""
import json, os
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON_D = 14


def outcome(sig, tp_first):
    p = r.prep(sig)
    if not p:
        return None
    is_long, elo, ehi, sl0, edge, tps = p
    sym = r.fsym(sig["symbol"]); o_ms = r.ms(sig["open_date"])
    last = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=False)
    last = [c for c in last if c[0] <= o_ms + HORIZON_D * 86400_000]
    if len(last) < 5:
        return None
    deadline = o_ms + r.ENTRY_WINDOW_H * 3600_000
    fi = fill = None
    for i, (ts, o, h, l, c) in enumerate(last):
        if ts < o_ms:
            continue
        if ts > deadline:
            break
        if (l <= ehi) if is_long else (h >= elo):
            fi, fill = i, edge; break
    if fi is None:
        return None
    risk_frac = abs(fill - sl0) / fill
    t1 = tps[0]
    ambiguous = False

    def adv(px):
        return (px - fill) / fill if is_long else (fill - px) / fill

    for (ts, o, h, l, c) in last[fi:]:
        hit_sl = (l <= sl0) if is_long else (h >= sl0)
        hit_t1 = (h >= t1) if is_long else (l <= t1)
        if hit_sl and hit_t1:
            ambiguous = True
            px = t1 if tp_first else sl0
            return (adv(px) - 2 * r.FEE) / risk_frac, ambiguous
        if tp_first:
            if hit_t1:
                return (adv(t1) - 2 * r.FEE) / risk_frac, ambiguous
            if hit_sl:
                return (adv(sl0) - 2 * r.FEE) / risk_frac, ambiguous
        else:
            if hit_sl:
                return (adv(sl0) - 2 * r.FEE) / risk_frac, ambiguous
            if hit_t1:
                return (adv(t1) - 2 * r.FEE) / risk_frac, ambiguous
    return (adv(last[-1][4]) - 2 * r.FEE) / risk_frac, ambiguous


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    slf = tpf = 0.0; n = amb = 0
    for s in usable:
        a = outcome(s, tp_first=False)
        b = outcome(s, tp_first=True)
        if a is None or b is None:
            continue
        n += 1
        slf += a[0]; tpf += b[0]
        if a[1]:
            amb += 1
    print(f"filled={n}  same-candle-ambiguous(SL&T1 in one candle)={amb} ({amb/n*100:.0f}%)")
    print(f"T1-exit totR  SL-first={slf:+.2f}R   TP-first={tpf:+.2f}R   delta={tpf-slf:+.2f}R")
    print(f"  -> TP-first {'STILL negative' if tpf < 0 else 'turns POSITIVE'} (recovers {tpf-slf:+.1f}R of the {slf:+.1f}R)")


if __name__ == "__main__":
    main()
