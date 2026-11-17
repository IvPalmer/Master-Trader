"""Summarise Freqtrade backtest zips: strategy, timerange, trade count, pairs."""
import json, sys, zipfile, collections

for path in sys.argv[1:]:
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        print("ERR", path, e); continue
    names = [n for n in z.namelist() if n.endswith(".json") and "_config" not in n and "market_change" not in n]
    for n in names:
        try:
            d = json.loads(z.read(n))
        except Exception as e:
            continue
        if not isinstance(d, dict) or "strategy" not in d:
            continue
        for strat, s in d["strategy"].items():
            tr = s.get("trades", [])
            pairs = collections.Counter(t["pair"] for t in tr)
            od = sorted(t["open_date"] for t in tr)
            tot = sum(t.get("profit_abs", 0) for t in tr)
            print(f"{path.split('/')[-3] if 'backtest_results' in path else path.split('/')[-1]} | {n} | {strat} | tf={s.get('timeframe')} detail={s.get('timeframe_detail')} | range={s.get('backtest_start')}..{s.get('backtest_end')} | n={len(tr)} | pairs={len(pairs)} | first={od[0] if od else None} last={od[-1] if od else None} | sum_abs={tot:.2f} | stake={s.get('stake_amount')} maxopen={s.get('max_open_trades')} | mode={s.get('trading_mode')}")
