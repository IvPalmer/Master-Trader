"""Lane B: T1-exit-100% + risk-based sizing test (Luc's recipe) for Binance Killers.

replay_v2 sweeps STOP strategies on an equal-weight TP ladder, returns in margin
units (leverage-scaled). Luc instead (a) exits ~100% at the first TP, and (b) sizes
from the SL distance ("margin based on given SL"). Test both, offline, reusing v2's
cached klines + mark-price liquidation. Honest yes/no on whether it flips positive.

  python3 t1_exit_killers.py            # runs 5x & 2x, 14d & 45d, residual de-biased+pessimistic
"""
import json, os
from collections import Counter
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))


def simulate(sig, lev, horizon_d, residual):
    p = r.prep(sig)
    if not p:
        return {"skip": "incomplete"}
    is_long, elo, ehi, sl0, edge, tps = p
    sym = r.fsym(sig["symbol"])
    o_ms = r.ms(sig["open_date"])
    last = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=False)
    cut = o_ms + horizon_d * 86400_000
    last = [c for c in last if c[0] <= cut]
    if len(last) < 5:
        return {"skip": "no_klines"}
    markc = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=True)
    mark = {c[0]: (c[3], c[2]) for c in markc}

    deadline = o_ms + r.ENTRY_WINDOW_H * 3600_000
    fi, fill_px = None, None
    for i, (ts, o, h, l, c) in enumerate(last):
        if ts < o_ms:
            continue
        if ts > deadline:
            break
        if (l <= ehi) if is_long else (h >= elo):
            fi, fill_px = i, edge; break
    if fi is None:
        return {"skip": "no_fill"}

    n = len(tps); w = 1.0 / n
    liq_frac = 1.0 / lev - 0.005
    liq_px = fill_px * (1 - liq_frac) if is_long else fill_px * (1 + liq_frac)
    risk_frac = abs(fill_px - sl0) / fill_px            # SL distance as a fraction (>0)

    if residual == "close_full_only":
        ch_close = r.ms(sig["channel_close_date"]) if sig.get("channel_close_date") else None
    elif residual == "none":
        ch_close = None
    else:
        ch_close = r.ms(sig["last_event_date"]) if sig.get("last_event_date") else None

    def adverse_ret(px):
        return (px - fill_px) / fill_px if is_long else (fill_px - px) / fill_px

    def walk(mode):
        """mode='ladder' (equal-weight rungs, posted SL) or 't1' (100% at first TP)."""
        rem, next_tp, realized = 1.0, 0, 0.0
        liquidated = stopped = False
        for (ts, o, h, l, c) in last[fi:]:
            if rem <= 1e-9:
                break
            st = sl0                                   # posted SL throughout (Luc sizes from it)
            mlo, mhi = mark.get(ts, (l, h))
            hit_stop = (l <= st) if is_long else (h >= st)
            hit_liq = (mlo <= liq_px) if is_long else (mhi >= liq_px)
            if hit_stop:
                realized += rem * adverse_ret(st); rem = 0.0; stopped = True; break
            if hit_liq:
                realized += rem * adverse_ret(liq_px); rem = 0.0; liquidated = True; break
            if mode == "t1":
                if (h >= tps[0]) if is_long else (l <= tps[0]):
                    realized += rem * adverse_ret(tps[0]); rem = 0.0; break
            else:
                while next_tp < n and ((h >= tps[next_tp]) if is_long else (l <= tps[next_tp])):
                    realized += w * adverse_ret(tps[next_tp]); rem -= w; next_tp += 1
            if ch_close and ts >= ch_close and rem > 1e-9:
                realized += rem * adverse_ret(c); rem = 0.0; break
        if rem > 1e-9:
            realized += rem * adverse_ret(last[-1][4]); rem = 0.0
        net_margin = realized * lev - 2 * r.FEE * lev          # margin units (leverage view)
        net_R = realized / risk_frac - (2 * r.FEE) / risk_frac  # risk-sized view (R), fee in R
        return net_margin, net_R, liquidated, stopped

    lm, lR, lliq, _ = walk("ladder")
    tm, tR, tliq, _ = walk("t1")
    return {"symbol": sig["symbol"], "open": sig["open_date"],
            "ladder_margin": lm, "ladder_R": lR, "ladder_liq": lliq,
            "t1_margin": tm, "t1_R": tR, "t1_liq": tliq}


def report(results, lev, horizon_d, residual):
    n = len(results)
    ordered = sorted(results, key=lambda x: x["open"])
    print(f"\n#### {lev:g}x  {horizon_d}d  residual={residual}  filled={n} ####")
    print(f"{'model':<16}{'tot_margin':>11}{'mean':>8}{'win%':>7}{'liq':>5}{'maxDD':>9}   {'tot_R':>8}{'meanR':>8}{'winR%':>7}")
    for key in ("ladder", "t1"):
        m = [x[f"{key}_margin"] for x in results]
        Rs = [x[f"{key}_R"] for x in results]
        liqs = sum(1 for x in results if x[f"{key}_liq"])
        eq = peak = mdd = 0.0
        for x in ordered:
            eq += x[f"{key}_margin"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        winm = sum(1 for v in m if v > 0) / n * 100
        winR = sum(1 for v in Rs if v > 0) / n * 100
        print(f"{key:<16}{sum(m):>+11.2f}{sum(m)/n:>+8.3f}{winm:>7.1f}{liqs:>5}{mdd:>9.2f}   "
              f"{sum(Rs):>+8.2f}{sum(Rs)/n:>+8.3f}{winR:>7.1f}")
    # drop-largest robustness (risk-sized R)
    for key in ("ladder", "t1"):
        Rs = sorted(results, key=lambda x: abs(x[f"{key}_R"]), reverse=True)
        tot = sum(x[f"{key}_R"] for x in results)
        drop = Rs[0]
        print(f"   {key} drop-largest: totR {tot:+.2f} -> {tot - drop[f'{key}_R']:+.2f}  (dropped {drop['symbol']} {drop[f'{key}_R']:+.2f}R)")


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    print(f"usable signals: {len(usable)}")
    for residual in ("close_full_only", "none"):
        for lev in (5.0, 2.0):
            for horizon_d in (14, 45):
                results, skips = [], Counter()
                for s in usable:
                    r_ = simulate(s, lev, horizon_d, residual)
                    if "skip" in r_:
                        skips[r_["skip"]] += 1
                    else:
                        results.append(r_)
                report(results, lev, horizon_d, residual)
                print(f"   skips={dict(skips)}")


if __name__ == "__main__":
    main()
