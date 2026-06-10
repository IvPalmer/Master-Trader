"""Lane C: adverse-selection / uncapturable-edge audit across BOTH channels.

The RENDER #2147 case: channel posts an entry RANGE, price tags T1 minutes later
(BEFORE a limit at the posted entry would fill), then days later dips to fill and
rolls back to breakeven. The channel claims the T1 win; a mechanical limit-copier
either misses the clean pre-entry T1, or only fills the trades that come BACK — which
skew toward losers (adverse selection). Question: how much of each channel's apparent
edge is structurally UNCAPTURABLE by any mechanical copier, regardless of exit policy?

Self-contained (own jsonl loader for Insiders; reuses killers replay_v2.fetch cache
for Killers). Offline. Read-only on price data.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
KILL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "killers")
sys.path.insert(0, KILL)
import replay_v2 as kr  # noqa: E402

MAX_TAIL_H = 24 * 12
# ENTRY_MODE: "mid" (range midpoint, default) or "nearedge" (the edge price hit FIRST as
# price enters the zone = ehi for long, elo for short — most permissive, fills earliest).
ENTRY_MODE = os.environ.get("ENTRY_MODE", "mid")


def ms(s): return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def load_insiders(sym, prices_dir):
    """Return list of (ts,o,h,l,c) from <prices_dir>/<SYM>.<venue>.jsonl, weex>binance."""
    for venue in ("weex", "binance"):
        p = os.path.join(prices_dir, f"{sym.upper()}.{venue}.jsonl")
        if os.path.exists(p):
            rows = []
            for line in open(p):
                line = line.strip()
                if line:
                    d = json.loads(line)
                    rows.append((d["t"], d["o"], d["h"], d["l"], d["c"]))
            if rows:
                rows.sort(key=lambda c: c[0])
                return rows
    return []


def classify(cands, signal_ts, entry, sl, t1, is_long, fill_window_h):
    """Return dict with fill/pre_entry_T1 flags + always-fill & real-fill outcomes (R)."""
    win_end = signal_ts + fill_window_h * 3600_000
    in_win = [c for c in cands if signal_ts <= c[0] < win_end]
    risk = abs(entry - sl)
    if risk <= 0 or not in_win:
        return None

    # first candle the posted-entry limit would actually trade in
    fill_idx = None
    for i, (ts, o, h, l, c) in enumerate(in_win):
        if l <= entry <= h:
            fill_idx = i; break
    # first candle T1 is touched within the fill window
    t1_win_idx = None
    for i, (ts, o, h, l, c) in enumerate(in_win):
        if (h >= t1) if is_long else (l <= t1):
            t1_win_idx = i; break
    pre_entry_T1 = (t1_win_idx is not None) and (fill_idx is None or t1_win_idx < fill_idx)
    filled = fill_idx is not None

    def outcome_from(start_ts):
        """SL-first vs T1 from start_ts; cap at MAX_TAIL_H. Returns (R, kind)."""
        end = start_ts + MAX_TAIL_H * 3600_000
        walk = [c for c in cands if start_ts <= c[0] < end]
        for (ts, o, h, l, c) in walk:
            hit_sl = (l <= sl) if is_long else (h >= sl)
            if hit_sl:
                return -1.0, "loss"
            hit_t1 = (h >= t1) if is_long else (l <= t1)
            if hit_t1:
                pnl = (t1 - entry) if is_long else (entry - t1)
                return pnl / risk, "win"
        if walk:
            last = walk[-1][4]
            pnl = (last - entry) if is_long else (entry - last)
            return pnl / risk, "tail"
        return 0.0, "nodata"

    # always-fill: pretend you got the posted entry at signal time
    af_R, af_kind = outcome_from(signal_ts)
    # real-fill: only if the limit actually traded; walk from the real fill candle
    if filled:
        rf_R, rf_kind = outcome_from(in_win[fill_idx][0])
    else:
        rf_R, rf_kind = 0.0, "no_fill"
    return {"filled": filled, "pre_entry_T1": pre_entry_T1,
            "af_R": af_R, "af_kind": af_kind, "rf_R": rf_R, "rf_kind": rf_kind}


def audit(name, items):
    """items: list of dicts with keys cands, signal_ts, entry, sl, t1, is_long, fill_window_h"""
    rows = []
    for it in items:
        c = classify(it["cands"], it["signal_ts"], it["entry"], it["sl"], it["t1"],
                     it["is_long"], it["fill_window_h"])
        if c:
            rows.append(c)
    n = len(rows)
    if not n:
        print(f"\n=== {name}: no usable signals ==="); return
    pre = sum(1 for r in rows if r["pre_entry_T1"])
    filled = sum(1 for r in rows if r["filled"])
    winners = [r for r in rows if r["af_kind"] == "win"]
    losers = [r for r in rows if r["af_kind"] == "loss"]
    wf = sum(1 for r in winners if r["filled"]) / len(winners) * 100 if winners else float("nan")
    lf = sum(1 for r in losers if r["filled"]) / len(losers) * 100 if losers else float("nan")
    af_tot = sum(r["af_R"] for r in rows)
    rf_tot = sum(r["rf_R"] for r in rows)
    print(f"\n=== {name}  (usable={n}) ===")
    print(f"  pre-entry T1 (clean win copier can't get): {pre}/{n} = {pre/n*100:.0f}%")
    print(f"  never-filled in window:                    {n-filled}/{n} = {(n-filled)/n*100:.0f}%")
    print(f"  always-fill outcome buckets: win={len(winners)} loss={len(losers)} other={n-len(winners)-len(losers)}")
    print(f"  WINNER fill-rate: {wf:.0f}%   LOSER fill-rate: {lf:.0f}%   (loser>winner = adverse selection)")
    print(f"  total R  always-fill = {af_tot:+.1f}R   |   real-fill = {rf_tot:+.1f}R   "
          f"(edge surviving real fills: {rf_tot/af_tot*100:.0f}% of headline)" if af_tot else "")


def insiders_items(trades_file, prices_dir):
    trades = json.load(open(trades_file))
    out = []
    for t in trades:
        if not t.get("date"):
            continue
        sl = t.get("sl")
        tps = [x for x in (t.get("tps") or []) if isinstance(x, (int, float))]
        if not isinstance(sl, (int, float)) or not tps:
            continue
        is_long = t["direction"] == "LONG"
        lo, hi = t.get("entry_lo"), t.get("entry_hi")
        if ENTRY_MODE == "nearedge" and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            entry = hi if is_long else lo
        else:
            entry = t.get("entry")
            if not isinstance(entry, (int, float)):
                if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                    entry = (lo + hi) / 2
                else:
                    continue
        cands = load_insiders(t["symbol"], prices_dir)
        if not cands:
            continue
        t1 = sorted(tps, reverse=not is_long)[0]
        out.append({"cands": cands, "signal_ts": ms(t["date"]), "entry": entry,
                    "sl": sl, "t1": t1, "is_long": is_long, "fill_window_h": 6})
    return out


def killers_items():
    sigs = json.load(open(os.path.join(KILL, "killers_signals.json")))
    out = []
    for s in sigs:
        p = kr.prep(s)
        if not p:
            continue
        is_long, elo, ehi, sl0, edge, tps = p
        sym = kr.fsym(s["symbol"])
        o_ms = kr.ms(s["open_date"])
        cands = kr.fetch(sym, o_ms - kr.TF_MS, o_ms + kr.FETCH_D * 86400_000, mark=False)
        if not cands or len(cands) < 5:
            continue
        entry = (ehi if is_long else elo) if ENTRY_MODE == "nearedge" else (elo + ehi) / 2
        out.append({"cands": cands, "signal_ts": o_ms, "entry": entry, "sl": sl0,
                    "t1": tps[0], "is_long": is_long, "fill_window_h": 72})
    return out


if __name__ == "__main__":
    audit("INSIDERS April", insiders_items(os.path.join(HERE, "trades.json"), os.path.join(HERE, "prices")))
    audit("INSIDERS May",   insiders_items(os.path.join(HERE, "trades_may.json"), os.path.join(HERE, "prices_may")))
    audit("BINANCE KILLERS", killers_items())
