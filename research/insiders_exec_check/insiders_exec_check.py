"""Execution-verified replay of Insiders/Dennis trades.

proper_backtest.py assumes fill at the POSTED entry at signal time. This script
tests two realistic copier executions:
  (1) LIMIT gate: only enter if the posted entry price actually traded within
      WINDOW_H hours of the signal (a limit copier). Else the trade never opens.
  (2) MARKET entry: enter at the real market price at signal time (next-min
      open) regardless — this is what our bot does (market entries by design).

Reuses proper_backtest's event-walk so PnL accounting is identical; only the
entry fill changes.
"""
import sys, json, copy
sys.path.insert(0, "/Users/palmer/Work/Dev/master-trader/weex_probe")
import proper_backtest as pb

WINDOW_H = 6
SOURCE = "binance"

d = json.load(open(pb.TRADES_JSON))
trades = d["trades"]


def entry_traded_within(t, hours):
    """Did the posted entry price trade within `hours` of signal time?"""
    entry = t.get("entry"); sl = t.get("sl")
    if not isinstance(entry, (int, float)) or entry <= 0:
        return None
    a = pb.ms(t["date"]); b = a + hours * 3600 * 1000
    candles = pb.get_window(SOURCE, t["symbol"], a, b)
    if not candles:
        return None
    for c in candles:
        if c["t"] < a or c["t"] >= b:
            continue
        if c["l"] <= entry <= c["h"]:
            return True
    return False


def market_price_at_signal(t):
    return pb.price_at(SOURCE, t["symbol"], pb.ms(t["date"]))


# ---- baseline (posted-entry fill, as proper_backtest does) ----
base = [pb.simulate_trade(t, SOURCE) for t in trades]
base = [r for r in base if r is not None]
base_total = sum(r.realized_pnl_usd for r in base)

# ---- (1) LIMIT gate ----
filled, not_filled, nodata = [], [], 0
for t in trades:
    r = pb.simulate_trade(t, SOURCE)
    if r is None:
        continue
    tr = entry_traded_within(t, WINDOW_H)
    if tr is None:
        nodata += 1; continue
    (filled if tr else not_filled).append(r)

def stats(rs):
    tot = sum(r.realized_pnl_usd for r in rs)
    w = [r for r in rs if r.realized_pnl_usd > 0]
    l = [r for r in rs if r.realized_pnl_usd < 0]
    gw = sum(r.realized_pnl_usd for r in w); gl = -sum(r.realized_pnl_usd for r in l)
    pf = gw/gl if gl > 0 else float("inf")
    wr = len(w)/max(1,len(rs))*100
    return f"n={len(rs):3d}  PnL=${tot:8.2f} ({tot/pb.ACCOUNT*100:6.2f}%)  WR={wr:4.1f}%  PF={pf:.2f}"

# ---- (2) MARKET entry ----
mkt = []
for t in trades:
    mp = market_price_at_signal(t)
    if mp is None:
        continue
    t2 = copy.deepcopy(t)
    t2["entry"] = mp           # fill at real market, keep posted SL/TP/events
    r = pb.simulate_trade(t2, SOURCE)
    if r is not None:
        mkt.append(r)

print("="*70)
print(f"BASELINE (posted-entry fill, = proper_backtest): {stats(base)}")
print("-"*70)
print(f"(1) LIMIT gate, entry must trade within {WINDOW_H}h:")
print(f"    FILLED (would actually enter)     : {stats(filled)}")
print(f"    NOT FILLED (limit never triggers) : {stats(not_filled)}")
print(f"    [no-kline-data trades skipped: {nodata}]")
print("-"*70)
print(f"(2) MARKET entry at signal-time price (our bot's actual behavior):")
print(f"    {stats(mkt)}")
print("="*70)
