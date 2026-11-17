"""Exploratory veto test 2018-2022: does a crypto 'crash news' storm (GDELT) predict worse next days?
Signal known at end of UTC day d; outcomes measured from 00:00 UTC of d+1. 2023+ held out."""
import json, glob, pickle, sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from study import plt, SURF, INK, INK2, GRID, BLUE, ORANGE, RED, LIGHT
g = []
for f in sorted(glob.glob('data/gdelt_crash_20*.json')):
    for p in json.load(open(f))['timeline'][0]['data']:
        g.append((pd.Timestamp(p['date'][:8]), p['value'], p['norm']))
G = pd.DataFrame(g, columns=['d', 'n', 'norm']).drop_duplicates('d').set_index('d').sort_index()
G['share'] = G.n / G.norm
G['ratio'] = G.share / G.share.shift(1).rolling(30, min_periods=20).median()
K = pickle.load(open('data/majors_1h.pkl', 'rb'))
def hourly(sym):
    df = pd.DataFrame(K[sym], columns=['t', 'o', 'h', 'l', 'c', 'v']); df.index = pd.to_datetime(df.t, unit='ms'); return df
res = {}
for sym in ('BTCUSDT', 'ETHUSDT'):
    h = hourly(sym); c = h.c
    day = c.resample('1D').last()                        # close at end of day d
    lr = np.log(c).diff()
    rows = []
    for d in G.index:
        if d < pd.Timestamp('2018-01-01') or d > pd.Timestamp('2022-12-31') or d not in day.index: continue
        c0 = day.get(d); prev = day.get(d - pd.Timedelta(days=1))
        win = c[(c.index >= d + pd.Timedelta(days=1)) & (c.index < d + pd.Timedelta(days=4))]
        def fwd(k):
            x = day.get(d + pd.Timedelta(days=k)); return x / c0 - 1 if x is not None and c0 else np.nan
        lw = lr[(lr.index >= d + pd.Timedelta(days=1)) & (lr.index < d + pd.Timedelta(days=4))]
        rows.append({'d': d, 'ret_d': c0 / prev - 1 if prev else np.nan, 'r1': fwd(1), 'r3': fwd(3), 'r7': fwd(7),
                     'vol3': lw.std() * np.sqrt(24 * 365) if len(lw) > 48 else np.nan,
                     'mdd3': win.min() / c0 - 1 if len(win) else np.nan})
    R = pd.DataFrame(rows).set_index('d').join(G[['share', 'ratio']])
    R['news'] = R.ratio >= 2.0
    R['price'] = R.ret_d <= -0.05
    res[sym] = R
    def row(mask, name):
        x = R[mask]
        return f"{name:28s} n={len(x):4d}  r1 med {x.r1.median()*100:+.2f}% mean {x.r1.mean()*100:+.2f}%  r3 med {x.r3.median()*100:+.2f}%  r7 med {x.r7.median()*100:+.2f}%  vol3 {x.vol3.median()*100:.0f}%  mdd3 med {x.mdd3.median()*100:.1f}%"
    print('==', sym)
    for m, nm in ((R.index == R.index, 'todos os dias'), (R.news, 'tempestade de notícias'), (R.price, 'queda de preço >=5%'),
                  (R.news & ~R.price, 'notícias sem queda de preço'), (R.price & ~R.news, 'queda de preço sem notícias')):
        print(row(m, nm))
pickle.dump({'G': G, 'res': res}, open('data/veto.pkl', 'wb'))
