"""Track A.1 — does the EDGE survive? PnL of the validated LLM intent stream, net of costs.

The smart agent reads Dennis perfectly (87/87 intent fidelity). Necessary, not sufficient.
This asks the only question that gates productionization: when you ACT on those correct
intents, does the book make money net of realistic costs — or does perfect reading still lose
(as mechanical copying did, -31% to -41%)?

Input: the harness-computed realized R per closed position from the full-May LLM run
(causal_replay/runs/full_may/llm.json) — GROSS (no fees/slippage/funding). Each position's R =
realized_pnl / risk, risk = |entry - sl|.

Cost model (same as cost_ceiling.py): cost in R = roundtrip_cost_frac / sl_dist_pct, where
sl_dist_pct = |entry - sl| / entry. Tight stops amplify cost in R (real, not artifact).
  - taker 0.05%/side, slippage 0.05%/market fill; entry+exit both market for a copier.
  - roundtrip ~= 2*(taker+slip) = 0.20% notional. (maker/limit variants reported as sensitivity)
  - funding: flat small per-trade sensitivity.

sl_dist per position comes from the curated trade (trades_may.json, by opener src_id) — the
SAME entry/sl the LLM extracted and the ledger used.

Reports: gross vs net R, account-% at 5% risk/trade (the doc's convention), concentration
(strip the single biggest winner), and the kill-gate.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
LLM = os.path.join(HERE, "causal_replay/runs/full_may/llm.json")
TRUTH = os.path.join(HERE, "trades_may.json")

TAKER = 0.0005
SLIP = 0.0005
RISK_PCT = 5.0  # linear translation R -> account-% (same as RESULTS_MAY.md)

def sl_dist_pct_for(opener, truth_by_src):
    t = truth_by_src.get(opener)
    if not t:
        return None
    entry = t.get("entry")
    if entry is None:
        lo, hi = t.get("entry_lo"), t.get("entry_hi")
        if lo and hi:
            entry = (lo + hi) / 2.0
    sl = t.get("sl")
    if not (isinstance(entry, (int, float)) and isinstance(sl, (int, float)) and entry > 0):
        return None
    d = abs(entry - sl) / entry
    return d if d > 0 else None

def cost_R(sl_dist, roundtrip):
    return roundtrip / sl_dist if sl_dist and sl_dist > 0 else None

def main():
    led = json.load(open(LLM))["ledger"]
    truth = json.load(open(TRUTH))
    truth_by_src = {t["src_id"]: t for t in truth if t.get("src_id")}

    roundtrip_market = 2 * (TAKER + SLIP)      # 0.20%
    roundtrip_maker = 2 * 0.0002               # maker both sides, no slip (optimistic)

    rows = []
    gross = net_mkt = net_mkr = 0.0
    missing = []
    for p in led["closed"]:
        opener = p["opener"]
        sld = sl_dist_pct_for(opener, truth_by_src)
        if sld is None:
            missing.append(opener)
            # fall back to a conservative median sl_dist so the trade isn't free
            sld = 0.03
        cR_mkt = cost_R(sld, roundtrip_market)
        cR_mkr = cost_R(sld, roundtrip_maker)
        g = p["R"]
        nm = g - cR_mkt
        nk = g - cR_mkr
        gross += g; net_mkt += nm; net_mkr += nk
        rows.append({"sym": p["symbol"], "side": p["side"], "opener": opener,
                     "gross_R": round(g, 3), "sl_dist_%": round(sld * 100, 2),
                     "cost_R_mkt": round(cR_mkt, 3), "net_R_mkt": round(nm, 3)})

    n = len(rows)
    wins = [r for r in rows if r["net_R_mkt"] > 0]
    # concentration: strip single biggest NET winner
    top = max(rows, key=lambda r: r["net_R_mkt"])
    net_ex_top = net_mkt - top["net_R_mkt"]

    print("=" * 74)
    print("TRACK A.1 — PnL of the validated LLM intent stream, net of costs (full-May)")
    print("=" * 74)
    print(f"closed positions: {n}   (cost = roundtrip {roundtrip_market*100:.2f}% / sl_dist, in R)")
    if missing:
        print(f"  NOTE: {len(missing)} openers not in curated truth -> used 3% sl_dist fallback: {missing}")
    print()
    print(f"  GROSS total R:            {gross:+.2f}R   ({gross*RISK_PCT:+.1f}% @5%)")
    print(f"  NET R (market entry):     {net_mkt:+.2f}R   ({net_mkt*RISK_PCT:+.1f}% @5%)   WR {len(wins)}/{n}")
    print(f"  NET R (maker/limit opt.): {net_mkr:+.2f}R   ({net_mkr*RISK_PCT:+.1f}% @5%)")
    print(f"  total cost drag:          {gross-net_mkt:.2f}R")
    print()
    print(f"  CONCENTRATION: biggest net winner = {top['sym']} {top['side']} {top['net_R_mkt']:+.2f}R")
    print(f"  NET ex-top-winner:        {net_ex_top:+.2f}R   ({net_ex_top*RISK_PCT:+.1f}% @5%)")
    print()
    print("  per-position (sorted by net):")
    for r in sorted(rows, key=lambda r: -r["net_R_mkt"]):
        print(f"    {r['sym']:9}{r['side']:6} gross={r['gross_R']:+6.3f} "
              f"sl={r['sl_dist_%']:5.2f}% cost={r['cost_R_mkt']:+.3f} NET={r['net_R_mkt']:+6.3f}")
    print()
    print("=" * 74)
    print("KILL-GATE")
    print("=" * 74)
    kill = net_mkt <= 0 or net_ex_top <= 0
    print(f"  net (market) > 0 ?           {net_mkt > 0}   ({net_mkt:+.2f}R)")
    print(f"  survives stripping top win ? {net_ex_top > 0}   ({net_ex_top:+.2f}R)")
    print()
    if kill:
        print("  >>> VERDICT: does NOT clearly survive. Reading edge does not convert to a")
        print("      robust trading edge net of costs on this month. Document, do not build Track B")
        print("      on this evidence alone. (Compare: mechanical copier was -31% to -41%.)")
    else:
        print("  >>> VERDICT: SURVIVES — the smart-managed book is net-positive after costs AND")
        print("      not dependent on one winner. Materially better than mechanical (-31%/-41%).")
        print("      Justifies Track B, with the standing caveats (1 month, exit=posted-close,")
        print("      between-msg SL not modeled).")
    print()
    print("  CAVEATS: gross R uses the harness exit model (close at posted-message candle, market);")
    print("  between-message hard-SL NOT modeled (would add losers); 1 signaler / 1 month;")
    print("  fills are oracle-clamped to real candles (no fantasy edge). This is the LLM-managed")
    print("  book, not Dennis's actual fills.")

if __name__ == "__main__":
    main()
