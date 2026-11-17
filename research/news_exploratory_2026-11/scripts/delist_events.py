"""2022 Binance spot delisting announcements -> per-token 5m paths (exploratory; 2023+ held out for Part C)."""
import json, re, sys, os, pickle
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from klines_fetch import daily
A = json.load(open('data/binance_161_all.json'))
ev = []
for a in A:
    t0 = a['releaseDate']
    if datetime.fromtimestamp(t0/1000, timezone.utc).year != 2022: continue
    m = re.match(r'Binance Will Delist (.+?) on (\d{4}-\d{2}-\d{2})$', a['title'])
    if not m: continue
    toks = [x.strip() for x in re.split(r',| and ', m.group(1)) if x.strip()]
    ev.append({'id': a['id'], 't0': t0, 'title': a['title'], 'tokens': toks, 'delist_date': m.group(2)})
print(len(ev), sum(len(e['tokens']) for e in ev))
cache = {}
def series(sym, start, days):
    out = []
    for d in range(days):
        ymd = (start + timedelta(days=d)).strftime('%Y-%m-%d')
        k = (sym, ymd)
        if k not in cache: cache[k] = daily(sym, '5m', ymd)
        if cache[k] is None:
            if d == 0: return None
            continue
        out += cache[k]
    return out
res = []
for e in ev:
    t0d = datetime.fromtimestamp(e['t0']/1000, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    btc = series('BTCUSDT', t0d, 8)
    for tok in e['tokens']:
        got = None
        for q in ('USDT', 'BUSD', 'BTC'):
            s = series(tok + q, t0d, 8)
            if s: got = (q, s); break
        print(e['delist_date'], tok, got[0] if got else None, len(got[1]) if got else 0, flush=True)
        res.append({**{k: e[k] for k in ('id', 't0', 'title', 'delist_date')}, 'token': tok,
                    'quote': got[0] if got else None, 'k': got[1] if got else None})
    e['btc'] = btc
pickle.dump({'events': ev, 'tokens': res}, open('data/delist2022.pkl', 'wb'))
