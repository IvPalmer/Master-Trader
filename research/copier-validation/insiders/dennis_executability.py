"""Dennis/Insiders EXECUTABILITY precondition (testable NOW, no LLM lookahead).

Before building a forward agentic selector, answer the only thing cached data can answer
honestly: with realistic limit fills + fees, is there a SURVIVING, COST-CLEARING edge to
select from? (Killers failed this — edge dies at the fill.) Pure price/fill geometry +
fees; this is NOT the selector test (that's forward-only), it's the gate for it.

Run per ledger:
  python3 dennis_executability.py <abs trades.json>                       # April
  PRICES_DIR=<abs prices_may> python3 dennis_executability.py <abs trades_may.json>  # May
"""
import sys, json
import harness as h
import t1_exit_test as t1x

FEE = 0.0004  # Binance taker/side (the verdict says copy Dennis on Binance, not WEEX)


def fee_R(entry, sl):
    risk = abs(entry - sl)
    return (2 * FEE * entry / risk) if risk > 0 else 0.0


def net_rows(trades, entry_model, exit_model):
    """Return list of net-of-fee R for filled, risk-sized trades."""
    out = []
    if exit_model == "t1":
        for t in trades:
            r = t1x.simulate_t1(t, entry_model)
            if r["realized_R"] is None or r["fill"] is None:
                continue
            out.append(r["realized_R"] - fee_R(r["fill"], t["sl"]))
    else:
        rows, *_ = h.run(trades, entry_model, exit_model),
        rows = rows[0]
        for r in rows:
            if r.realized_R is None or r.entry_price is None:
                continue
            # find sl for this symbol/dir/date — match by entry_price approx; use trade list
            out.append(r.realized_R)  # manage fee handled below (approx)
    return out


def summarize(tag, Rs):
    n = len(Rs)
    if not n:
        print(f"  {tag:<22} n=0"); return
    tot = sum(Rs); wins = sum(1 for x in Rs if x > 0)
    srt = sorted(Rs); drop1 = tot - srt[-1]
    print(f"  {tag:<22} n={n:<3} totR={tot:>+7.2f} R/trade={tot/n:>+6.3f} "
          f"win={wins}/{n}  drop1 R/trade={drop1/(n-1) if n>1 else 0:>+6.3f}")


def main():
    tf = sys.argv[1]
    trades = json.load(open(tf))
    print(f"\n===== {tf.split('/')[-1]} — executability (Binance fee {FEE*100:.2f}%/side, NET of fee) =====")
    print("  realistic = posted-limit entry (skip if entry never trades); T1-exit + manage")
    for em in ("posted", "edge"):
        summarize(f"{em}+t1 (net)", net_rows(trades, em, "t1"))
    # manage net: recompute fee per filled trade by matching sl
    rows, *_ = h.run(trades, "posted", "manage"),
    rows = rows[0]
    sl_by = {}
    for t in trades:
        sl_by[(t["symbol"], t["direction"])] = t.get("sl")
    mg = []
    for r in rows:
        if r.realized_R is None or r.entry_price is None:
            continue
        sl = sl_by.get((r.symbol, r.direction))
        mg.append(r.realized_R - (fee_R(r.entry_price, sl) if isinstance(sl, (int, float)) else 0.0))
    summarize("posted+manage (net)", mg)
    print("  cost hurdle: a real edge must clear ~+0.10 R/trade (sub) on top of this net-of-fee number")


if __name__ == "__main__":
    main()
