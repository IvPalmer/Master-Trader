"""SUPERSEDED 2026-08-30 — the P&L this script produces is WRONG. Do not cite it.

Kept only so the error is reproducible. An independent verification found four
ways it fails to reproduce the contract the bot actually runs:

  1. OI window misaligned by one hour. It scores each candle against OI over
     [T-45m, T]; the live strategy reads [T+15m, T+1h] at the decision point.
     Disjoint windows — this tests a different rule than the deployed one.
  2. max_open_trades=1 is not modelled; it runs eight concurrent pair slots,
     overstating trade count roughly 2.5x.
  3. custom_exit / ema50_break is not simulated at all, despite the original
     docstring claiming "the strategy's own exit rules".
  4. Prices come from fapi PERPETUAL klines for a SPOT strategy, with no fees
     or slippage, at 1h resolution on a ROI+stop+trailing exit stack — against
     the project's standing --timeframe-detail 1m rule.

Corrected, the same 30 days give PF 0.74 and -4.0%, not PF 2.46 and +16.3%,
and a placebo mask of equal pass rate scores median PF 0.69 — the gate lands
at the 57th percentile of its own null.

What survives, because it never depended on the simulation: the DISTRIBUTION.
45-minute OI growth over the window is p50 +0.01%, p90 +0.39%, p99 +1.46%,
against a deployed threshold of 2.00%. That threshold admitted nothing.

A valid redo must fix all four items above and include a placebo comparison.
See preregistration oi-gate-recalibration-2026-08-30.
"""
import json, time, urllib.request, datetime as dt
import numpy as np, pandas as pd

PAIRS = ["ETH","SOL","BNB","SUI","XRP","ADA","AVAX","LINK"]
DAYS = 30
NOW = int(time.time()*1000)

def get(url):
    for _ in range(4):
        try:
            return json.load(urllib.request.urlopen(url, timeout=25))
        except Exception:
            time.sleep(1.5)
    return []

def klines(sym, interval="1h", limit=1000):
    d = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}")
    if not d: return None
    df = pd.DataFrame(d, columns="ot o h l c v ct qv n tb tq ig".split())
    df["date"] = pd.to_datetime(df.ot, unit="ms", utc=True)
    for k in "ohlcv":
        col = {"o":"o","h":"h","l":"l","c":"c","v":"v"}[k]
        df[col] = df[col].astype(float)
    return df[["date","o","h","l","c","v"]].set_index("date")

def oi_hist(sym, period="15m"):
    step = 15*60*1000
    out, start = [], NOW - DAYS*24*3600*1000
    while start < NOW:
        d = get(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}"
                f"&period={period}&limit=500&startTime={start}&endTime={min(start+500*step, NOW)}")
        if not d: break
        out += d
        start = d[-1]["timestamp"] + step
        if len(d) < 2: break
    if not out: return None
    df = pd.DataFrame(out).drop_duplicates("timestamp")
    df["date"] = pd.to_datetime(df.timestamp, unit="ms", utc=True)
    df["oi"] = df.sumOpenInterest.astype(float)
    return df[["date","oi"]].set_index("date").sort_index()

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    rs=up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+rs)

btc = klines("BTCUSDT")
btc_trend = ((btc.c > ema(btc.c,200)) & (ema(btc.c,50) > ema(btc.c,200))).rename("btc_trend")

rows = []
for p in PAIRS:
    k = klines(p+"USDT"); oi = oi_hist(p+"USDT")
    if k is None or oi is None: print("skip", p); continue
    # 45-minute OI growth = 3 x 15m, then align to each hourly candle close
    oi["growth"] = oi.oi / oi.oi.shift(3) - 1.0
    g = oi.growth.reindex(k.index, method="ffill", tolerance=pd.Timedelta("20min"))
    df = k.copy()
    df["ema20"], df["ema50"], df["ema200"] = ema(df.c,20), ema(df.c,50), ema(df.c,200)
    df["rsi"] = rsi(df.c); df["vol_sma"] = df.v.rolling(20).mean()
    df["oi_growth"] = g
    df["btc_trend"] = btc_trend.reindex(df.index, method="ffill")
    df["pair"] = p
    rows.append(df)

all_df = pd.concat(rows)
ta_ok = (
    (all_df.ema50 > all_df.ema200) & (all_df.c > all_df.ema200) & (all_df.c > all_df.ema20)
    & (all_df.c.groupby(all_df.pair).shift(1) <= all_df.ema20.groupby(all_df.pair).shift(1))
    & (all_df.c <= all_df.ema20*1.02) & (all_df.rsi.between(45,68))
    & (all_df.v > all_df.vol_sma*1.10) & (all_df.btc_trend) & (all_df.v > 0)
)
print(f"window: {all_df.index.min():%Y-%m-%d} .. {all_df.index.max():%Y-%m-%d}  "
      f"pairs={len(rows)}  candles={len(all_df)}")
print(f"TA conjunction alone (no OI gate): {int(ta_ok.sum())} setups")
oig = all_df.oi_growth
print(f"OI 45m growth distribution: p50={oig.quantile(.5)*100:+.2f}%  p90={oig.quantile(.9)*100:+.2f}%  "
      f"p99={oig.quantile(.99)*100:+.2f}%  max={oig.max()*100:+.2f}%  NaN={int(oig.isna().sum())}")

# --- simulate the deployed exit rules on 1h bars ---
ROI = [(0,0.06),(360,0.04),(720,0.025),(1440,0.01)]  # minutes -> target
STOP, TRAIL_OFF, TRAIL = -0.05, 0.04, 0.025
def simulate_per_pair(frames, thr):
    """Walk each pair independently; one open position at a time, like the bot."""
    out = []
    for d in frames:
        d = d.reset_index()
        ta = (
            (d.ema50 > d.ema200) & (d.c > d.ema200) & (d.c > d.ema20)
            & (d.c.shift(1) <= d.ema20.shift(1)) & (d.c <= d.ema20*1.02)
            & (d.rsi.between(45,68)) & (d.v > d.vol_sma*1.10)
            & (d.btc_trend.fillna(False)) & (d.v > 0)
        )
        sig = ta & (d.oi_growth >= thr)
        i, n = 0, len(d)
        while i < n-1:
            if not bool(sig.iloc[i]): i += 1; continue
            entry = d.o.iloc[i+1]; peak = 0.0; res = None; j = i+1
            while j < min(i+1+240, n):
                mins = (j-i)*60
                hi = d.h.iloc[j]/entry-1; lo = d.l.iloc[j]/entry-1
                peak = max(peak, hi)
                roi = next(v for m,v in reversed(ROI) if mins >= m)
                if lo <= STOP: res = STOP; break
                if peak >= TRAIL_OFF and lo <= peak-TRAIL: res = max(peak-TRAIL, STOP); break
                if hi >= roi: res = roi; break
                j += 1
            if res is None: res = d.c.iloc[min(j, n-1)]/entry-1
            out.append(res)
            i = j + 1          # position occupied until exit
    return out

print("\nthreshold |  signals | trades/mo |   PF  |  net%  |  win%")
print("----------|----------|-----------|-------|--------|------")
for thr in [0.02, 0.015, 0.01, 0.0075, 0.005, 0.0025, 0.0, -0.005]:
    r = simulate_per_pair(rows, thr)
    if not r:
        print(f"  {thr*100:+5.2f}%  |     0    |     -     |   -   |    -   |   -")
        continue
    r = np.array(r); w = r[r>0].sum(); l = -r[r<0].sum()
    print(f"  {thr*100:+5.2f}%  |   {len(r):4d}   |   {len(r)/(DAYS/30):5.1f}   | "
          f"{(w/l if l else float('inf')):5.2f} | {r.sum()*100:+6.1f} | {(r>0).mean()*100:4.0f}%")
