"""Track A.3 — the FULL entry x exit matrix + realistic-member limit model.

Corrects an earlier methodology error: I tested only MARKET entry + his DISCRETIONARY closes
(-31%), ignoring (a) limit-in-zone entry and (b) his POSTED TP ladder (30/32 signals have TPs).
A real profitable member rests a limit in the zone and follows the posted TPs. This tests every
entry x exit combination and the realistic limit-member model. WEEX, 1-min, no lookahead.

Reuses the validated harness engine (reproduces RESULTS_MAY.md). Codex-reviewed.
"""
import json, os
import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PRICES_DIR", os.path.join(HERE, "prices_may"))
H.PRICES = __import__("pathlib").Path(os.environ["PRICES_DIR"]); H._cache.clear()
RISK_PCT = 5.0


def matrix(trades):
    print("=" * 78)
    print("FULL ENTRY x EXIT MATRIX (32 May trades, WEEX, no lookahead, GROSS R)")
    print("  exit=ladder -> his posted TP ladder (SL->BE after TP1); exit=manage -> his closes")
    print("=" * 78)
    print(f"  {'entry':9}{'exit':9}{'sized':7}{'WR':9}{'totalR':10}{'ex-top':9}{'acct@5%'}")
    for em in ("posted", "edge", "market"):
        for xm in ("ladder", "manage"):
            rows = []
            for t in trades:
                r = H.simulate(t, em, xm)
                if r.realized_R is not None:
                    rows.append(r.realized_R)
            if not rows:
                continue
            tot = sum(rows); top = max(rows)
            w = sum(1 for r in rows if r > 0)
            print(f"  {em:9}{xm:9}{len(rows):<7}{str(w)+'/'+str(len(rows)):9}"
                  f"{tot:+8.2f}  {tot-top:+7.2f}  {tot*RISK_PCT:+.1f}%")
    print("  ('edge'=best-touched price in zone = optimistic ceiling, NOT achievable;")
    print("   'posted'=zone-midpoint limit; 'market'=fill at signal-candle open.)")


def realistic_member(trades):
    """Rest a limit in the zone, fill ONLY if a causal candle touches it within 6h, posted-TP exit."""
    print("\n" + "=" * 78)
    print("REALISTIC MEMBER — limit rests in zone, fills only if touched, then posted TP ladder")
    print("=" * 78)
    print(f"  {'placement':11}{'filled':8}{'WR':8}{'gross':9}{'ex-top':9}{'ex-top2':9}{'~net':9}{'acct'}")
    for where in ("near", "mid", "far"):
        tot = 0; filled = 0; nofill = 0; wins = 0; rs = []
        for t in trades:
            sl = t.get("sl")
            if not isinstance(sl, (int, float)):
                continue
            cs, _ = H.candles(t["symbol"])
            a = H.ms(t["date"]); win = H.window(cs, a, a + 6 * 3600 * 1000)
            if not win:
                continue
            lo, hi = t.get("entry_lo"), t.get("entry_hi")
            if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
                continue
            lo, hi = min(lo, hi), max(lo, hi)
            is_long = t["direction"] == "LONG"
            px = (hi if is_long else lo) if where == "near" else \
                 (lo if is_long else hi) if where == "far" else (lo + hi) / 2
            ft = next((c["t"] for c in win if c["l"] <= px <= c["h"]), None)
            if ft is None:
                nofill += 1; continue
            realized, risk, kind, n = H._simulate_ladder(t, cs, px, is_long, sl, ft)
            R = realized / risk if risk else None
            if R is None:
                continue
            filled += 1; tot += R; rs.append(R)
            if R > 0: wins += 1
        rs.sort(reverse=True)
        extop = tot - (rs[0] if rs else 0)
        extop2 = tot - sum(rs[:2])
        net = tot - filled * 0.05  # ~maker-in/taker-out cost
        print(f"  {where:11}{str(filled)+'/'+str(filled+nofill):8}{str(wins)+'/'+str(filled):8}"
              f"{tot:+8.2f}{extop:+8.2f}{extop2:+8.2f}{net:+8.2f}  {net*RISK_PCT:+.0f}%")
    print("\n  Honest read (codex): positive in May, but placement-sensitive (near +6% .. mid +33%)")
    print("  and concentrated (mid survives ex-top, NOT ex-top-2). Promising, not proven. 1 month.")


if __name__ == "__main__":
    trades = json.load(open(os.path.join(HERE, "trades_may.json")))
    matrix(trades)
    realistic_member(trades)
