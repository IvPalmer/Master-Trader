"""Track A.4 — multi-month out-of-sample test of the limit+TP copy model + directional autopsy.

Runs the IDENTICAL model (rest limit at near-edge of posted zone + posted TP ladder) across every
parseable month, reports per-month PnL + win rate + directional bias vs what BTC actually did.
Tests the hypothesis from the April autopsy: losses come from being positioned AGAINST the move
(short into a rally), not from chop. WEEX/Binance, 1m, no lookahead.
"""
import json, os, statistics as st
import harness as H
from pathlib import Path

HERE = Path(__file__).parent
RISK_PCT = 5.0

def candles(sym, prices_dir):
    """Consistent venue across ALL months = Binance (the only venue with full Feb->May history;
    WEEX cache only reaches back to 04-15). Binance majors track WEEX within ~0.1% (parity checked
    in RESULTS_MAY.md), so this is a fair cross-month comparison. May is ALSO run on Binance here
    for apples-to-apples — its WEEX number (+6%) is reported separately in the docs."""
    H.PRICES = Path(prices_dir)
    b = H.load(sym, "binance")
    if b: return b, "binance"
    w = H.load(sym, "weex")
    return (w, "weex") if w else (None, None)

def btc_move(prices_dir, lo_iso, hi_iso):
    """net % move of BTC over the month window."""
    H.PRICES = Path(prices_dir); H._cache.clear()
    c = H.load("BTC", "binance")
    a, b = H.ms(lo_iso), H.ms(hi_iso)
    seg = [x for x in c if a <= x["t"] < b]
    if not seg: return None
    return (seg[-1]["c"] - seg[0]["c"]) / seg[0]["c"] * 100

def run_month(signals_file, prices_dir):
    H.PRICES = Path(prices_dir); H._cache.clear()
    trades = json.load(open(signals_file))
    tot = 0.0; filled = 0; nofill = 0; nodata = 0; wins = 0; rs = []
    shorts = longs = 0
    short_R = 0.0; long_R = 0.0
    for t in trades:
        sym = t["symbol"]; is_long = t["direction"] == "LONG"; sl = t.get("sl")
        if not isinstance(sl, (int, float)): continue
        cs, _ = candles(sym, prices_dir)
        if not cs: nodata += 1; continue
        a = H.ms(t["date"]); win = H.window(cs, a, a + 6*3600*1000)
        if not win: nodata += 1; continue
        lo, hi = min(t["entry_lo"], t["entry_hi"]), max(t["entry_lo"], t["entry_hi"])
        px = hi if is_long else lo   # near-edge (the realistic 31/32-fill placement)
        ft = next((c["t"] for c in win if c["l"] <= px <= c["h"]), None)
        if ft is None: nofill += 1; continue
        realized, risk, kind, n = H._simulate_ladder(t, cs, px, is_long, sl, ft)
        R = realized/risk if risk else None
        if R is None: continue
        filled += 1; tot += R; rs.append(R)
        if R > 0: wins += 1
        if is_long: longs += 1; long_R += R
        else: shorts += 1; short_R += R
    net = tot - filled*0.05
    return dict(n=len(trades), filled=filled, nofill=nofill, nodata=nodata, wins=wins,
                gross=tot, net=net, shorts=shorts, longs=longs, short_R=short_R, long_R=long_R)

def main():
    months = [
        ("2026-02", HERE/"signals_parsed_2026_02.json", str(HERE/"prices"), "2026-02-01", "2026-03-01"),
        ("2026-03", HERE/"signals_parsed_2026_03.json", str(HERE/"prices"), "2026-03-01", "2026-04-01"),
        ("2026-04", HERE/"signals_parsed_2026_04.json", str(HERE/"prices"), "2026-04-01", "2026-04-30"),
        ("2026-05", HERE/"trades_may.json",             str(HERE/"prices_may"), "2026-05-10", "2026-05-30"),
    ]
    print("="*92)
    print("MULTI-MONTH OOS — near-edge limit + posted TP ladder. R gross/net, dir bias, BTC move")
    print("="*92)
    print(f"  {'month':8}{'filled':9}{'WR':8}{'gross':9}{'net':9}{'acct':8}{'shorts(R)':14}{'longs(R)':14}{'BTC move'}")
    pooled_net = 0; pooled_filled = 0; pooled_wins = 0
    for mo, sf, pd, lo, hi in months:
        if not os.path.exists(sf):
            print(f"  {mo:8} (no signals file)"); continue
        r = run_month(str(sf), pd)
        bm = btc_move(pd, lo, hi)
        pooled_net += r["net"]; pooled_filled += r["filled"]; pooled_wins += r["wins"]
        fillcol = f"{r['filled']}/{r['filled']+r['nofill']}"
        wrcol = f"{r['wins']}/{r['filled']}"
        shortcol = f"{r['shorts']}({r['short_R']:+.1f})"
        longcol = f"{r['longs']}({r['long_R']:+.1f})"
        bmcol = "" if bm is None else f"{bm:+.1f}%"
        print(f"  {mo:8}{fillcol:9}{wrcol:8}{r['gross']:+8.2f}{r['net']:+8.2f}"
              f"{r['net']*RISK_PCT:+6.0f}%  {shortcol:14}{longcol:14}{bmcol}")
    print("  " + "-"*88)
    print(f"  POOLED   filled={pooled_filled}  WR={pooled_wins}/{pooled_filled}  "
          f"net={pooled_net:+.2f}R ({pooled_net*RISK_PCT:+.0f}% @5%)")
    print()
    print("  Hypothesis: months where his net direction fought BTC (shorts in an up-month) lose;")
    print("  months aligned with the move win. If shorts(R) is the negative driver when BTC rose,")
    print("  the 'edge' is regime/direction timing, not the posted signals.")
    print("  CAVEAT: Feb/Mar are thin (few priceable signals). Pooled across months is the real read.")

if __name__ == "__main__":
    main()
