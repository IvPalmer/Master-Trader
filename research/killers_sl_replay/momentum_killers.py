"""Attack lane (codex-designed, pre-registered): MOMENTUM-CONFIRMATION entry.

Hypothesis: pullback limits adverse-select losers (they come back & fill); winners run
to T1 without you. So DON'T wait for a pullback — enter only AFTER price confirms toward
T1 by a fraction k, joining the runaways. R-preservation gates prevent "buying the top".

PRE-REGISTERED (no post-hoc tweaking):
  entry_ref = signal-candle open (honest reachable price, NOT the unreachable posted entry)
  trigger_px = entry_ref + k*(T1-entry_ref)  [long];  entry_ref - k*(entry_ref-T1) [short]
  k in {0.15, 0.25, 0.35}  (pick ONE on train, report OOS)
  trigger must occur within 3 candles (15m @5m)
  CANCEL: SL touched before trigger | fill already >70% to T1 | remaining reward <0.25R(orig)
          | effective SL >1.4R(orig) | trigger&SL same candle -> no-trade (conservative)
  EXIT: 100% at T1 or posted SL. Fees 0.04%/side in R. SL-first within candle.
  Report R on ACTUAL fill risk (|fill-SL|) so a stop = -1R (disciplined "size from SL").
  Chronological split: train = first 70%, OOS = last 30%. Pick k on train ONLY.
  HURDLE (OOS): >=50 trades, mean>=+0.15R, total>=+8R, survives drop-top, beats
                market-entry-T1 baseline by >=+0.20R/trade.
"""
import json, os
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON_D = 14
FEE = r.FEE


def fetch_sig(sig):
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
    fi = last.index(cand[0])
    return dict(is_long=is_long, sl0=sl0, t1=tps[0], last=last, fi=fi,
                entry_ref=cand[0][1], o_ms=o_ms, sym=sig["symbol"], dir=sig["direction"])


def momentum_R(s, k):
    """Return ('trade', R) | ('skip', reason)."""
    is_long, sl0, t1, last, fi, eref = s["is_long"], s["sl0"], s["t1"], s["last"], s["fi"], s["entry_ref"]
    reward0 = (t1 - eref) if is_long else (eref - t1)
    risk0 = (eref - sl0) if is_long else (sl0 - eref)
    if reward0 <= 0 or risk0 <= 0:
        return ("skip", "bad_geom")
    trig = eref + k * reward0 if is_long else eref - k * reward0
    # find trigger within 3 candles; SL-before-trigger cancels
    fill_px = None
    for c in last[fi:fi + 3]:
        ts, o, h, l, cl = c
        hit_sl = (l <= sl0) if is_long else (h >= sl0)
        hit_trig = (h >= trig) if is_long else (l <= trig)
        if hit_sl and hit_trig:
            return ("skip", "trig_and_sl_same_candle")   # conservative no-trade
        if hit_sl:
            return ("skip", "sl_before_trigger")
        if hit_trig:
            fill_px = max(trig, o) if is_long else min(trig, o)  # gap-fill at worse of trig/open
            trig_i = last.index(c)
            break
    if fill_px is None:
        return ("skip", "no_trigger_3c")
    # R-preservation gates (relative to ORIGINAL posted risk)
    progressed = ((fill_px - eref) if is_long else (eref - fill_px)) / reward0
    if progressed > 0.70:
        return ("skip", "fill_past_70pct")
    remaining_R = (((t1 - fill_px) if is_long else (fill_px - t1)) / risk0)
    if remaining_R < 0.25:
        return ("skip", "reward_lt_0.25R")
    effsl_R = (((fill_px - sl0) if is_long else (sl0 - fill_px)) / risk0)
    if effsl_R > 1.4:
        return ("skip", "effSL_gt_1.4R")
    # walk from trigger candle: 100% exit at T1 or SL (SL-first), risk = actual fill->SL
    risk = abs(fill_px - sl0)
    for c in last[trig_i:]:
        ts, o, h, l, cl = c
        hit_sl = (l <= sl0) if is_long else (h >= sl0)
        if hit_sl:
            return ("trade", (((sl0 - fill_px) if is_long else (fill_px - sl0)) / risk) - 2 * FEE)
        hit_t1 = (h >= t1) if is_long else (l <= t1)
        if hit_t1:
            return ("trade", (((t1 - fill_px) if is_long else (fill_px - t1)) / risk) - 2 * FEE)
    # horizon
    last_px = last[-1][4]
    return ("trade", (((last_px - fill_px) if is_long else (fill_px - last_px)) / risk) - 2 * FEE)


def market_t1_R(s):
    """Baseline: market entry at signal-candle open, 100% exit at T1/SL."""
    is_long, sl0, t1, last, fi, eref = s["is_long"], s["sl0"], s["t1"], s["last"], s["fi"], s["entry_ref"]
    if (eref >= t1) if is_long else (eref <= t1):
        return None
    if (eref <= sl0) if is_long else (eref >= sl0):
        return None
    risk = abs(eref - sl0)
    for c in last[fi:]:
        ts, o, h, l, cl = c
        if (l <= sl0) if is_long else (h >= sl0):
            return -1.0 - 2 * FEE
        if (h >= t1) if is_long else (l <= t1):
            return (((t1 - eref) if is_long else (eref - t1)) / risk) - 2 * FEE
    return (((last[-1][4] - eref) if is_long else (eref - last[-1][4])) / risk) - 2 * FEE


def stats(Rs):
    n = len(Rs)
    if not n:
        return "n=0"
    tot = sum(Rs); wins = sum(1 for x in Rs if x > 0)
    srt = sorted(Rs)
    drop1 = tot - srt[-1]
    drop2 = tot - srt[-1] - srt[-2] if n >= 2 else drop1
    return f"n={n:<4} totR={tot:>+7.1f} meanR={tot/n:>+6.3f} win%={wins/n*100:>4.0f} drop1={drop1:>+6.1f} drop2={drop2:>+6.1f}"


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    states = [fetch_sig(s) for s in sigs if s in usable]
    states = [s for s in states if s]
    states.sort(key=lambda s: s["o_ms"])
    cut = int(len(states) * 0.70)
    train, oos = states[:cut], states[cut:]
    print(f"usable states={len(states)}  train={len(train)} oos={len(oos)} (chronological 70/30)\n")

    print("== TRAIN (pick ONE k) ==")
    best_k, best_mean = None, -9
    for k in (0.15, 0.25, 0.35):
        Rs = [r_ for st in train for tag, r_ in [momentum_R(st, k)] if tag == "trade"]
        m = (sum(Rs) / len(Rs)) if Rs else -9
        print(f"  k={k}: {stats(Rs)}")
        if m > best_mean and len(Rs) >= 20:
            best_mean, best_k = m, k
    print(f"  -> chosen k (best train mean, n>=20) = {best_k}\n")

    print("== OOS (locked k, untouched) ==")
    if best_k is None:
        print("  no k qualified on train"); return
    oos_R = [r_ for st in oos for tag, r_ in [momentum_R(st, best_k)] if tag == "trade"]
    base = [x for st in oos for x in [market_t1_R(st)] if x is not None]
    print(f"  momentum k={best_k}:   {stats(oos_R)}")
    print(f"  market-T1 baseline: {stats(base)}")
    mm = (sum(oos_R) / len(oos_R)) if oos_R else 0
    bm = (sum(base) / len(base)) if base else 0
    print(f"\n  HURDLE CHECK (need all): n>=50 [{len(oos_R)>=50}]  mean>=+0.15 [{mm:+.3f}->{mm>=0.15}]  "
          f"total>=+8 [{sum(oos_R):+.1f}->{sum(oos_R)>=8}]  beats-base-by>=0.20 [{mm-bm:+.3f}->{mm-bm>=0.20}]")
    srt = sorted(oos_R)
    print(f"  drop-top>0 [{(sum(oos_R)-srt[-1])>0 if oos_R else False}]")
    # skip-reason histogram on OOS
    from collections import Counter
    reasons = Counter(tag if tag == "trade" else r_ for st in oos for tag, r_ in [momentum_R(st, best_k)])
    print(f"\n  OOS disposition: {dict(reasons)}")


if __name__ == "__main__":
    main()
