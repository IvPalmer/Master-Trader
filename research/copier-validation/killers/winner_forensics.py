"""Forensics (descriptive, not predictive mining): what drove the BIGGEST moves in the
Killers signal set, and were they CAPTURABLE or fantasy? For each signal measure the max
favorable excursion (MFE) from the signal-candle open in R (risk=|open-SL|), whether a
reachable entry existed at signal time, whether T1 hit pre-entry, time-to-peak, and what a
market+T1 copier actually realized. Rank by MFE. Answers 'what made winners win' with
evidence + 'how much was left on the table' (MFE vs realized)."""
import json, os
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON_D = 14


def forensic(sig):
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
    fi = last.index(cand[0]); ref = cand[0][1]; t1 = tps[0]
    risk = abs(ref - sl0)
    if risk <= 0 or (ref >= t1 if is_long else ref <= t1) or (ref <= sl0 if is_long else ref >= sl0):
        return None
    # MFE / MAE in R, time-to-peak; pre-entry-T1 & reachable-at-signal
    mfe = mae = 0.0; t_peak = 0
    for c in last[fi:]:
        ts, o, h, l, cl = c
        fav = ((h - ref) if is_long else (ref - l)) / risk
        adv = ((ref - l) if is_long else (h - ref)) / risk
        if fav > mfe:
            mfe = fav; t_peak = (ts - o_ms) / 3600_000
        mae = max(mae, adv)
    sc = cand[0]
    reachable = (sc[3] <= ehi) if is_long else (sc[2] >= elo)  # zone touched in signal candle
    # market+T1 realized R (SL-first)
    realized = None
    for c in last[fi:]:
        ts, o, h, l, cl = c
        if (l <= sl0) if is_long else (h >= sl0):
            realized = -1.0; break
        if (h >= t1) if is_long else (l <= t1):
            realized = ((t1 - ref) if is_long else (ref - t1)) / risk; break
    if realized is None:
        realized = ((last[-1][4] - ref) if is_long else (ref - last[-1][4])) / risk
    rr_t1 = (abs(t1 - ref) / risk)   # reward-to-risk to T1
    return dict(sym=sig["symbol"], dir=sig["direction"], mfe=mfe, mae=mae, t_peak_h=t_peak,
                reachable=reachable, realized=realized, rr_t1=rr_t1)


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    rows = [x for x in (forensic(s) for s in usable) if x]
    rows.sort(key=lambda x: x["mfe"], reverse=True)
    print(f"analyzed {len(rows)} signals\n")
    print("TOP 20 by max-favorable-excursion (MFE in R):")
    print(f"  {'sym':<10}{'dir':<6}{'MFE_R':>7}{'MAE_R':>7}{'t_peak_h':>9}{'reach':>6}{'realized_R':>11}{'RR→T1':>7}")
    for x in rows[:20]:
        print(f"  {x['sym']:<10}{x['dir']:<6}{x['mfe']:>7.1f}{x['mae']:>7.1f}{x['t_peak_h']:>9.1f}"
              f"{'Y' if x['reachable'] else 'n':>6}{x['realized']:>11.2f}{x['rr_t1']:>7.2f}")
    # concentration + capturability
    mfes = sorted((x["mfe"] for x in rows), reverse=True)
    tot_mfe = sum(mfes)
    top10 = sum(mfes[:10]) / tot_mfe * 100
    big = [x for x in rows if x["mfe"] >= 5]      # "huge winner" = >=5R favorable excursion
    big_real = sum(1 for x in big if x["realized"] > 0)
    print(f"\nMFE concentration: top-10 signals = {top10:.0f}% of all favorable excursion")
    print(f"'huge' movers (MFE>=5R): {len(big)} signals; of those, market+T1 actually PROFITED on {big_real}/{len(big)}")
    print(f"  their mean realized R = {sum(x['realized'] for x in big)/len(big):+.2f} (vs mean MFE {sum(x['mfe'] for x in big)/len(big):.1f}R left on table)")
    print(f"  reachable-at-signal among huge movers: {sum(1 for x in big if x['reachable'])}/{len(big)}")
    # MFE for reachable vs not
    rch = [x['mfe'] for x in rows if x['reachable']]; nrch = [x['mfe'] for x in rows if not x['reachable']]
    print(f"\nmean MFE reachable={sum(rch)/len(rch):.2f}R (n{len(rch)}) vs NOT-reachable={sum(nrch)/len(nrch):.2f}R (n{len(nrch)})")
    print(f"  (if winners cluster in NOT-reachable, the big moves are the ones you can't fill)")
    # avg MFE vs avg realized overall
    print(f"\noverall: mean MFE={sum(x['mfe'] for x in rows)/len(rows):.2f}R  mean MAE={sum(x['mae'] for x in rows)/len(rows):.2f}R  "
          f"mean realized(market+T1)={sum(x['realized'] for x in rows)/len(rows):+.3f}R")


if __name__ == "__main__":
    main()
