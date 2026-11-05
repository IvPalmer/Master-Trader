import pickle, sys, os, json
import numpy as np
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))
from study import Series, usd, multiples, aggregate, H
D = pickle.load(open('data/delist2022.pkl', 'rb'))
btc = {e['id']: Series(e['btc']) for e in D['events']}
PEGGED = {'RENBTC', 'SUSD'}
items = []
for r in D['tokens']:
    if not r['k'] or r['token'] in PEGGED: continue
    b = btc[r['id']]
    s = usd(Series(r['k']), r['quote'], b)
    d = datetime.fromtimestamp(r['t0'] / 1000, timezone.utc)
    items.append({'s': s, 'btc': b, 't0': r['t0'], 'aid': r['id'], 'label': f"{r['token']} · {d:%d/%m/%y}"})
print('tokens', len(items), 'announcements', len({i['aid'] for i in items}))
hz = {'+1h': H, '+4h': 4 * H, '+24h': 24 * H, '+72h': 72 * H}
multiples(items, 't0', 'Binance anuncia deslistagem (2022): preço de cada token em volta do anúncio', 'out/delist_multiples.png')
T = aggregate(items, 't0', f'Binance deslistagem 2022: {len(items)} tokens, {len({i["aid"] for i in items})} anúncios', 'out/delist_aggregate.png', hz, -1)
for nm in hz:
    v = np.array([t[nm][1] for t in T if t[nm][1] is not None]); u = np.array([t[nm][0] for t in T if t[nm][0] is not None])
    # per-announcement medians (announcement = unit of analysis)
    per = {}
    for it, t in zip(items, T):
        if t[nm][1] is not None: per.setdefault(it['aid'], []).append(t[nm][1])
    pa = np.array([np.mean(x) for x in per.values()])
    print(f"{nm}: n={len(v)} hedged median {np.median(v)*100:+.2f}% win {(v>0).mean()*100:.0f}% | unhedged median {np.median(u)*100:+.2f}% | per-announcement mean of {len(pa)}: {np.round(pa*100,1).tolist()}")
for it, t in zip(items, T):
    print(it['label'], {k: (round(v[1]*100,1) if v[1] is not None else None) for k, v in t.items()})
