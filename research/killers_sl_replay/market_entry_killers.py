"""Attack lane: does MARKET entry (be in every signal) beat the limit-in-zone entry
that cherry-picks a copier into the losers? Lane C said limit fills losers 99% /
winners 74% → market entry should remove that selection bias (at the cost of a worse
price). Also segment the edge (long/short, SL-distance bucket, BTC-regime) to find any
profitable subset for codex to design around. Risk-sized R (leverage-independent) +
5x margin view. Offline (cached klines)."""
import json, os
from collections import defaultdict
import replay_v2 as r

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON_D = 14
RESIDUAL = "close_full_only"


def sim(sig, entry_mode):
    p = r.prep(sig)
    if not p:
        return {"skip": "incomplete"}
    is_long, elo, ehi, sl0, edge, tps = p
    sym = r.fsym(sig["symbol"]); o_ms = r.ms(sig["open_date"])
    last = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=False)
    last = [c for c in last if c[0] <= o_ms + HORIZON_D * 86400_000]
    if len(last) < 5:
        return {"skip": "no_klines"}
    markc = r.fetch(sym, o_ms - r.TF_MS, o_ms + r.FETCH_D * 86400_000, mark=True)
    mark = {c[0]: (c[3], c[2]) for c in markc}

    if entry_mode == "market":
        cand = [c for c in last if c[0] >= o_ms]
        if not cand:
            return {"skip": "no_klines"}
        fi = last.index(cand[0]); fill = cand[0][1]            # signal-candle open
        if (fill >= tps[0]) if is_long else (fill <= tps[0]):
            return {"skip": "past_t1"}                          # already ran past T1 — stale
        if (fill <= sl0) if is_long else (fill >= sl0):
            return {"skip": "past_sl"}
    else:  # limit-in-zone (replay_v2 behaviour)
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
            return {"skip": "no_fill"}

    risk_frac = abs(fill - sl0) / fill
    if risk_frac <= 0:
        return {"skip": "bad_risk"}
    n = len(tps); w = 1.0 / n
    ch_close = r.ms(sig["channel_close_date"]) if sig.get("channel_close_date") else None

    def adv(px):
        return (px - fill) / fill if is_long else (fill - px) / fill

    def walk(mode):
        rem, nt, realized = 1.0, 0, 0.0
        for (ts, o, h, l, c) in last[fi:]:
            if rem <= 1e-9:
                break
            hit_sl = (l <= sl0) if is_long else (h >= sl0)
            if hit_sl:
                realized += rem * adv(sl0); rem = 0.0; break
            if mode == "t1":
                if (h >= tps[0]) if is_long else (l <= tps[0]):
                    realized += rem * adv(tps[0]); rem = 0.0; break
            else:
                while nt < n and ((h >= tps[nt]) if is_long else (l <= tps[nt])):
                    realized += w * adv(tps[nt]); rem -= w; nt += 1
            if ch_close and ts >= ch_close and rem > 1e-9:
                realized += rem * adv(c); rem = 0.0; break
        if rem > 1e-9:
            realized += rem * adv(last[-1][4])
        return realized / risk_frac - (2 * r.FEE) / risk_frac

    sl_dist = abs(fill - sl0) / fill
    return {"symbol": sig["symbol"], "dir": sig["direction"], "open": sig["open_date"],
            "t1_R": walk("t1"), "ladder_R": walk("ladder"), "sl_dist": sl_dist}


def summarize(tag, rows):
    if not rows:
        print(f"{tag}: (none)"); return
    n = len(rows)
    for key in ("t1", "ladder"):
        Rs = [x[f"{key}_R"] for x in rows]
        tot = sum(Rs); wins = sum(1 for v in Rs if v > 0)
        srt = sorted(rows, key=lambda x: abs(x[f"{key}_R"]), reverse=True)
        drop = tot - srt[0][f"{key}_R"]
        print(f"  {tag:<26}{key:<7} n={n:<4} totR={tot:>+7.1f}  meanR={tot/n:>+6.3f}  "
              f"win%={wins/n*100:>4.0f}  drop1={drop:>+7.1f}")


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    for mode in ("limit", "market"):
        rows, skips = [], defaultdict(int)
        for s in usable:
            x = sim(s, mode)
            if "skip" in x:
                skips[x["skip"]] += 1
            else:
                rows.append(x)
        print(f"\n########## ENTRY = {mode}  (filled {len(rows)}, skips {dict(skips)}) ##########")
        summarize("ALL", rows)
        summarize("LONG only", [x for x in rows if x["dir"] == "long"])
        summarize("SHORT only", [x for x in rows if x["dir"] == "short"])
        summarize("SL tight (<5%)", [x for x in rows if x["sl_dist"] < 0.05])
        summarize("SL mid (5-10%)", [x for x in rows if 0.05 <= x["sl_dist"] < 0.10])
        summarize("SL wide (>=10%)", [x for x in rows if x["sl_dist"] >= 0.10])


if __name__ == "__main__":
    main()
