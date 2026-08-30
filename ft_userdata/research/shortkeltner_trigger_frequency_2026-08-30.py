"""ShortKeltnerV2HL redesign: does a BREAKDOWN trigger clear the frequency bar
the current REJECTION trigger fails?

Deliberately measures SIGNAL FREQUENCY ONLY. No P&L, no exit modelling, no
threshold sweep — frequency is robust to the exit/fill/fee mistakes that
invalidated today's OI calibration, and frequency is the specific thing that
kills the current design (4 signals in 20 months).

Proxy caveat, same as the 2026-08-29 research note: Binance USDT klines stand
in for Hyperliquid USDC candles. Volume distributions are NOT comparable and
volume is a binding filter, so counts on HL will differ.
"""
import json, time, urllib.request
import numpy as np, pandas as pd

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
MONTHS = 20

def get(u):
    for _ in range(4):
        try: return json.load(urllib.request.urlopen(u, timeout=25))
        except Exception: time.sleep(1.5)
    return []

def klines(sym, interval, months):
    step = {"1h": 3600_000, "1d": 86400_000}[interval]
    end = int(time.time()*1000); start = end - months*30*86400_000
    out = []
    while start < end:
        d = get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}"
                f"&limit=1000&startTime={start}&endTime={end}")
        if not d: break
        out += d; start = d[-1][0] + step
        if len(d) < 1000: break
    df = pd.DataFrame(out, columns="ot o h l c v ct qv n tb tq ig".split()).drop_duplicates("ot")
    df["date"] = pd.to_datetime(df.ot, unit="ms", utc=True)
    for k in ["o","h","l","c","v"]: df[k] = df[k].astype(float)
    return df.set_index("date")[["o","h","l","c","v"]].sort_index()

def atr(d, n):
    tr = pd.concat([d.h-d.l, (d.h-d.c.shift(1)).abs(), (d.l-d.c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()
def rsi(s, n=14):
    x=s.diff(); up=x.clip(lower=0); dn=-x.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean())

btc1h = klines("BTCUSDT","1h",MONTHS); btc1d = klines("BTCUSDT","1d",MONTHS+8)
btc1h["sma50"]=btc1h.c.rolling(50).mean(); btc1h["sma200"]=btc1h.c.rolling(200).mean()
btc1h["slope"]=btc1h.sma50-btc1h.sma50.shift(24)
btc1d["sma200d"]=btc1d.c.rolling(200).mean()
# 1d informative is lagged one full day, as freqtrade's merge does
d200 = btc1d.sma200d.shift(1).reindex(btc1h.index, method="ffill")
GATE = ((btc1h.c<btc1h.sma50)&(btc1h.c<btc1h.sma200)&(btc1h.slope<0)&(btc1h.c<d200))
print(f"janela: {btc1h.index.min():%Y-%m-%d} .. {btc1h.index.max():%Y-%m-%d}  "
      f"({len(btc1h)} barras 1h)   gate bear aberto: {GATE.mean()*100:.1f}% das horas")

KP, KM, VM, VP, RSI_OB = 25, 2.5, 1.75, 20, 60
rows=[]
for sym in PAIRS:
    d = klines(sym,"1h",MONTHS)
    sma = d.c.rolling(KP).mean(); a = atr(d,KP)
    up, lo = sma + KM*a, sma - KM*a
    vs = d.v.rolling(VP).mean(); r = rsi(d.c)
    g = GATE.reindex(d.index, method="ffill").fillna(False)
    vol = d.v > VM*vs

    # A) DEPLOYED — fade: close drops back inside the upper band after RSI was overbought
    rej = (d.c<up)&(d.c.shift(1)>=up.shift(1))&vol&((r.shift(1)>RSI_OB)|(r.shift(2)>RSI_OB))&g
    # B) PROPOSED — breakdown: close breaks DOWN through the lower band on volume
    brk = (d.c<lo)&(d.c.shift(1)>=lo.shift(1))&vol&g
    # B') breakdown without the volume filter, to see what volume costs
    brk_nv = (d.c<lo)&(d.c.shift(1)>=lo.shift(1))&g
    rows.append((sym,int(rej.sum()),int(brk.sum()),int(brk_nv.sum())))

mo = len(btc1h)/24/30.4
print(f"\n{'par':<9}{'A) rejeicao (atual)':>21}{'B) rompimento':>16}{'B sem filtro vol':>19}")
for s,a_,b_,c_ in rows:
    print(f"{s:<9}{a_:>12} ({a_/mo:.2f}/mes){b_:>8} ({b_/mo:.2f}/mes){c_:>10} ({c_/mo:.2f}/mes)")
ta,tb,tc = (sum(x[i] for x in rows) for i in (1,2,3))
print(f"{'TOTAL':<9}{ta:>12} ({ta/mo:.2f}/mes){tb:>8} ({tb/mo:.2f}/mes){tc:>10} ({tc/mo:.2f}/mes)")
print(f"\nN=30 exigiria: A {30/max(ta/mo,1e-9)/12:.1f} anos   |   B {30/max(tb/mo,1e-9)/12:.1f} anos")
