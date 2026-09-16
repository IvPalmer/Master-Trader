"""Cache-only historical stress test, not a live-executor backtest or holdout."""
import argparse
from collections import Counter
from datetime import datetime
import json
import hashlib
from pathlib import Path
import statistics

BAR_MS = 300_000
DAY_MS = 86_400_000


def timestamp(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()*1000)


def walk(bars, entry, stop, target, short, trail, cost_bps=10, funding_bps_day=0):
    direction = -1 if short else 1
    risk = direction*(entry-stop)
    active, peak, armed = stop, 0.0, False
    start = bars[0][0]
    reason = 'horizon'
    for ts, o, h, l, close, mh, ml in bars:
        adverse = ml if not short else mh
        if direction*(adverse-active) <= 0:
            # Mark trigger, adverse trade open/stop assumption. Depth/nonfill unknown.
            px = min(o, active) if not short else max(o, active)
            reason = 'stop'
            break
        if (h >= target if not short else l <= target):
            px, reason = target, 'target'
            break
        peak = max(peak, direction*((mh if not short else ml)-entry)/risk)
        if trail and peak >= 2:
            armed = True
            candidate = entry + direction*(peak-1)*risk
            active = max(active, candidate) if not short else min(active, candidate)
        px = close
    days = (ts + BAR_MS - start)/DAY_MS
    gross = direction*(px-entry)/risk
    # Entry/exit transaction cost applied to respective notionals. Signed carry
    # stress is proportional to entry notional, NOT reconstructed actual funding.
    cost = cost_bps/10000*(entry+px)/risk
    carry = funding_bps_day/10000*entry*days/risk
    return dict(r=gross-cost-carry, days=days, armed=armed, reason=reason)


def load_cases(root):
    signals = json.loads((root/'killers_signals.json').read_text())
    skips, cases = Counter(), []
    digest = hashlib.sha256((root/'killers_signals.json').read_bytes())
    aliases = {'PEPE':'1000PEPE','SHIB':'1000SHIB','FLOKI':'1000FLOKI','BONK':'1000BONK','GOLD':'XAUT'}
    for s in signals:
        if not s.get('sl_initial') or not s.get('tp_ladder') or s.get('direction') not in ('long','short'):
            skips['incomplete_signal'] += 1
            continue
        start = timestamp(s['open_date'])
        symbol = aliases.get(s['symbol'].upper(),s['symbol'].upper())+'USDT'
        paths = [root/'klines_cache_v2'/f'{kind}_{symbol}_{start-BAR_MS}_{start+45*DAY_MS}.json' for kind in ('l','m')]
        if not all(p.exists() for p in paths):
            skips['uncached'] += 1
            continue
        for path in paths:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        last, mark = [json.loads(p.read_text()) for p in paths]
        mark = {c[0]:c for c in mark}
        rows = [c for c in last if start <= c[0] < start+14*DAY_MS]
        if not rows or rows[0][0]-start > BAR_MS or start+14*DAY_MS-(rows[-1][0]+BAR_MS)>BAR_MS:
            skips['incomplete_horizon'] += 1
            continue
        if any(b[0]-a[0] != BAR_MS for a,b in zip(rows,rows[1:])) or any(c[0] not in mark for c in rows):
            skips['price_or_mark_gap'] += 1
            continue
        entry, stop, short = rows[0][1], float(s['sl_initial']), s['direction']=='short'
        direction = -1 if short else 1
        targets = sorted([float(t) for t in s['tp_ladder']],reverse=short)
        if direction*(entry-stop)<=0 or direction*(targets[0]-entry)<=0:
            skips['entry_past_stop_or_first_target'] += 1
            continue
        bars = [[*c,mark[c[0]][2],mark[c[0]][3]] for c in rows]
        cases.append(dict(bars=bars,entry=entry,stop=stop,target=targets[-1],short=short))
    return sorted(cases,key=lambda c:c['bars'][0][0]), dict(skips), len(signals), digest.hexdigest()


def run(root):
    cases, skips, total, fingerprint = load_cases(root)
    out = dict(input_sha256=fingerprint,signal_count=total, eligible=len(cases), excluded=skips, scenarios={})
    for cost in (4.5,10,25):
        for funding in (-10,0,10):
            pairs = [(walk(**c,trail=False,cost_bps=cost,funding_bps_day=funding),
                      walk(**c,trail=True,cost_bps=cost,funding_bps_day=funding)) for c in cases]
            delta = [b['r']-a['r'] for a,b in pairs]
            cut = int(.7*len(pairs))
            mean = lambda xs: statistics.mean(xs) if xs else None
            out['scenarios'][f'cost_{cost}_bps_each_side_carry_{funding}_bps_day'] = dict(
                baseline_mean_r=mean([a['r'] for a,b in pairs]), candidate_mean_r=mean([b['r'] for a,b in pairs]),
                mean_delta_r=mean(delta), improved=sum(d>1e-9 for d in delta), worse=sum(d < -1e-9 for d in delta),
                armed=sum(b['armed'] for a,b in pairs), early70_delta_r=mean(delta[:cut]), late30_delta_r=mean(delta[cut:]),
                delta_without_best=mean(sorted(delta)[:-1]))
    out['limitations'] = ['Previously researched Binance corpus, not holdout or current Hyperliquid execution.',
        'Next full bar market entry; not bounded copier admission. Full exit at final posted target, not actual TP grouping.',
        '14-day endpoint; ignores source revisions, liquidation and portfolio capacity.',
        'Mark triggers and adverse-first bar ordering; no order-book nonfill model. Signed funding stress, not actual funding.',
        'Cost/funding scenarios are sensitivity checks, not nine independently selected policies.']
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('cache_root',type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.cache_root),indent=2))
