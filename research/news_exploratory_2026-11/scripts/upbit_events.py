"""Upbit KRW-market listing notices up to 2022-12-31 -> Binance spot 5m paths (exploratory; 2023+ held out)."""
import json, re, sys, os, glob, pickle
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from klines_fetch import daily
N = {}
for f in glob.glob('data/upbit_p*.json'):
    try: j = json.load(open(f))
    except Exception: print('BAD', f); continue
    for x in j['data']['notices']: N[x['id']] = x
A = sorted(N.values(), key=lambda x: x['first_listed_at'])
print('notices', len(A), A[0]['first_listed_at'], A[-1]['first_listed_at'])
ev = []; seen = set()
MARKET = {'KRW', 'BTC', 'ETH', 'USDT'}
for x in A:
    t = x['title']; y = x['first_listed_at'][:4]
    if not ('2018' <= y <= '2022'): continue
    if not re.search(r'원화|KRW', t): continue
    if not re.search(r'신규 상장|자산 추가|신규 거래 ?지원|원화 ?마켓 (오픈|상장)|상장 예고', t): continue
    if re.search(r'제거|종료|유의|변경|중단|연기|재개', t): continue
    t0 = int(datetime.fromisoformat(x['first_listed_at']).timestamp() * 1000)
    toks = [k for k in re.findall(r'(?<![A-Za-z])([A-Z][A-Z0-9]{1,9})(?![A-Za-z])', t) if k not in MARKET and k not in seen]
    seen.update(toks)
    if toks: ev.append({'id': x['id'], 't0': t0, 'title': t, 'tokens': toks})
print('KRW listing notices <=2022:', len(ev), 'tokens', sum(len(e['tokens']) for e in ev))
cache = {}
def series(sym, start, days):
    out = []
    for d in range(days):
        ymd = (start + timedelta(days=d)).strftime('%Y-%m-%d'); k = (sym, ymd)
        if k not in cache: cache[k] = daily(sym, '5m', ymd)
        if cache[k] is None:
            if d == 0: return None
            continue
        out += cache[k]
    return out
res = []
for e in ev:
    t0d = datetime.fromtimestamp(e['t0'] / 1000, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    e['btc'] = series('BTCUSDT', t0d, 8)
    for tok in e['tokens']:
        got = None
        for q in ('USDT', 'BUSD', 'BTC'):
            s = series(tok + q, t0d, 8)
            if s and s[0][0] < e['t0'] - 3_600_000: got = (q, s); break   # must already trade on Binance before t0
        print(datetime.fromtimestamp(e['t0']/1000, timezone.utc).date(), tok, got[0] if got else '-', flush=True)
        res.append({'id': e['id'], 't0': e['t0'], 'title': e['title'], 'token': tok, 'quote': got[0] if got else None, 'k': got[1] if got else None})
pickle.dump({'events': ev, 'tokens': res}, open('data/upbit2022.pkl', 'wb'))
