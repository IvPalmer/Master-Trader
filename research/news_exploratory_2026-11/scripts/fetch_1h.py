import sys, os, pickle
sys.path.insert(0, os.path.dirname(__file__))
from klines_fetch import monthly
out = {}
for sym in ('BTCUSDT', 'ETHUSDT'):
    rows = []
    for y in range(2017, 2023):
        for m in range(1, 13):
            if (y, m) < (2017, 8): continue
            r = monthly(sym, '1h', f'{y}-{m:02d}')
            if r: rows += r
    for m in (1, 2):
        r = monthly(sym, '1h', f'2023-{m:02d}')   # only for forward windows of late-2022 signals
        if r: rows += r
    out[sym] = rows; print(sym, len(rows))
pickle.dump(out, open('data/majors_1h.pkl', 'wb'))
