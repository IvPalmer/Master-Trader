"""Lane A: T1-exit-100% policy test (Luc's style) for Dennis/Insiders signals.

Neither baseline exit model (ladder = equal-fraction scale-out; manage = follow
Dennis's posted events) closes the WHOLE position at the first take-profit. Luc, a
copier who appears profitable, exits ~100% at T1. This was never tested. Test it.

Reuses harness.py primitives (offline; local price cache only). Same conventions as
_simulate_ladder: walk from the actual fill_ts, SL checked FIRST within a candle
(conservative), tail-cap at MAX_TAIL_HOURS, risk = |entry - sl|, R = realized/risk.

Usage (run per ledger so the PRICES cache matches):
  python3 t1_exit_test.py <abs path trades.json>          # April  (PRICES_DIR unset)
  PRICES_DIR=<abs .../prices_may> python3 t1_exit_test.py <abs trades_may.json>  # May
"""
from __future__ import annotations
import json, sys
import harness as h


def simulate_t1(t: dict, entry_model: str):
    sym = t["symbol"]; is_long = t["direction"] == "LONG"
    if not t.get("date"):
        return {"symbol": sym, "direction": t["direction"], "realized_R": None, "exit_kind": "unplaceable", "fill": None, "venue": "none"}
    cs, venue = h.candles(sym)
    if not cs:
        return {"symbol": sym, "direction": t["direction"], "realized_R": None, "exit_kind": "no_data", "fill": None, "venue": "none"}
    sl = t.get("sl"); has_sl = isinstance(sl, (int, float))
    ep, info = h._entry_fill(t, cs, entry_model)
    if ep is None:
        return {"symbol": sym, "direction": t["direction"], "realized_R": None, "exit_kind": info, "fill": None, "venue": venue}
    a = info
    # tps[0] is T1 (nearest TP in trade direction): ladder sorts reverse=not is_long
    tps = sorted([x for x in (t.get("tps") or []) if isinstance(x, (int, float))], reverse=not is_long)
    t1 = tps[0] if tps else None
    walk = [c for c in cs if c["t"] >= a]
    end = a + h.MAX_TAIL_HOURS * 3600 * 1000
    realized = 0.0; exit_kind = "open"
    for c in walk:
        if c["t"] >= end:
            break
        if has_sl:
            hit_sl = (c["l"] <= sl) if is_long else (c["h"] >= sl)
            if hit_sl:
                realized = h._pnl_units(is_long, 1.0, ep, sl); exit_kind = "sl"; break
        if t1 is not None:
            hit_t1 = (c["h"] >= t1) if is_long else (c["l"] <= t1)
            if hit_t1:
                realized = h._pnl_units(is_long, 1.0, ep, t1); exit_kind = "t1"; break
    if exit_kind == "open":
        capped = [c for c in walk if c["t"] < end]
        if capped:
            realized = h._pnl_units(is_long, 1.0, ep, capped[-1]["c"]); exit_kind = "tail"
    risk = abs(ep - sl) if has_sl else None
    realized_R = (realized / risk) if (risk and risk > 0) else None
    return {"symbol": sym, "direction": t["direction"], "entry_model": entry_model,
            "venue": venue, "fill": round(ep, 8),
            "realized_R": round(realized_R, 3) if realized_R is not None else None,
            "exit_kind": exit_kind, "has_sl": has_sl}


def agg_t1(trades, entry_model):
    rows = [simulate_t1(t, entry_model) for t in trades]
    sized = [r for r in rows if r["realized_R"] is not None]
    totR = sum(r["realized_R"] for r in sized)
    wins = [r for r in sized if r["realized_R"] > 0]
    return rows, sized, totR, wins


def main():
    tf = sys.argv[1]
    trades = json.load(open(tf))
    label = tf.split("/")[-1]
    print(f"\n========== LEDGER {label}  ({len(trades)} trades) ==========")
    print(f"{'entry':8}{'exit':9}{'sized':>7}{'totalR':>9}{'acct@5%':>9}{'WR':>9}")
    for entry_model in ("posted", "edge", "market"):
        # baselines
        for exit_model in ("ladder", "manage"):
            _, sized, totR, wins = h.run(trades, entry_model, exit_model)
            print(f"{entry_model:8}{exit_model:9}{len(sized):>7}{totR:>+9.2f}{totR*h.RISK_PCT:>+8.1f}%{len(wins):>5}/{len(sized):<3}")
        # T1-exit
        rows, sized, totR, wins = agg_t1(trades, entry_model)
        print(f"{entry_model:8}{'t1_exit':9}{len(sized):>7}{totR:>+9.2f}{totR*h.RISK_PCT:>+8.1f}%{len(wins):>5}/{len(sized):<3}")
        # robustness: drop the single largest-|R| t1 trade
        if sized:
            srt = sorted(sized, key=lambda r: abs(r["realized_R"]), reverse=True)
            drop = srt[0]
            totR_drop = totR - drop["realized_R"]
            print(f"{'':8}{'  ^drop':9}{len(sized)-1:>7}{totR_drop:>+9.2f}{totR_drop*h.RISK_PCT:>+8.1f}%   (dropped {drop['symbol']} {drop['realized_R']:+.2f}R)")
        # per-trade detail for t1_exit
        det = "  ".join(f"{r['symbol']}:{(format(r['realized_R'],'+.2f')+'R') if r['realized_R'] is not None else r['exit_kind']}" for r in rows)
        print(f"         t1 detail: {det}\n")


if __name__ == "__main__":
    main()
