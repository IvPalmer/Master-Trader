"""Offline sampled-mark shadow diagnostics. Never treats modeled exits as fills.

The tape is immutable input. Analysis is rebuilt from it for restart determinism.
Partial entries/exits and observation gaps are retained as flagged cases, never
silently counted as successful full-position comparisons.
"""
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys


def positive(x):
    return isinstance(x,(float,int)) and math.isfinite(x) and x>0


def original_stop(t):
    tags = [t.get('enter_tag') or '']+[o.get('ft_order_tag') or '' for o in t.get('orders',[])]
    for tag in tags:
        match = re.search(r'(?:^|\|)sl:([0-9.]+)',tag)
        if match:
            return float(match.group(1))
    return None


def depth_price(levels, amount, short, limit):
    """Full remaining size at observed depth within a 2% stop-limit band."""
    side = levels[1 if short else 0]
    left, value = amount, 0.0
    for level in side:
        px, size = float(level['px']),float(level['sz'])
        if not positive(px) or not positive(size):
            return None
        if (px>limit if short else px<limit):
            continue
        used = min(left,size)
        value += used*px
        left -= used
        if left <= amount*1e-9:
            return value/amount
    return None


def evaluate(snapshots, protocol):
    episodes, previous = {}, None
    for snap in snapshots:
        now = snap['ts']
        if previous is not None and now<=previous:
            raise ValueError('Observation timestamps must strictly increase')
        if snap.get('collector_sha256') != protocol['collector_sha256']:
            raise ValueError('Mixed collector versions')
        previous = now
        for t in snap['trades']:
            key = str(t['trade_id'])
            if key not in episodes:
                if not t.get('is_open') or not positive(t.get('amount')):
                    continue
                filled = t.get('open_fill_timestamp') or t.get('open_timestamp')
                if filled is None:
                    continue
                stop = original_stop(t)
                entry = t.get('open_rate')
                short = bool(t.get('is_short'))
                direction = -1 if short else 1
                valid = positive(entry) and positive(stop) and direction*(entry-stop)>0
                ep = dict(flags=[],entry=entry,stop=stop,short=short,amount=t['amount'],
                          last=now,peak_r=0.0,armed=False,exit=None,baseline=None,
                          original_risk=direction*(entry-stop) if valid else None)
                episodes[key] = ep
                if filled/1000 < protocol['start']:
                    ep['flags'].append('pre_epoch_observational')
                if now-filled/1000 > protocol['max_gap_seconds']:
                    ep['flags'].append('late_first_observation')
                if not valid:
                    ep['flags'].append('missing_or_invalid_original_risk')
            ep = episodes[key]
            if ep['baseline'] is not None:
                continue
            if now-ep['last']>protocol['max_gap_seconds']:
                ep['flags'].append('observation_gap')
            ep['last'] = now
            if t.get('nr_of_successful_entries') != 1 or t.get('nr_of_successful_exits',0)>int(not t['is_open']):
                ep['flags'].append('partial_or_multiple_fills_need_event_replay')
            if not t['is_open']:
                ep['baseline'] = t.get('close_profit_abs')
                if ep['exit'] is None:
                    ep['flags'].append('baseline_exit_before_observed_shadow_exit')
                continue
            if abs(t['amount']-ep['amount'])>ep['amount']*1e-8:
                ep['flags'].append('position_size_changed')
            if ep['original_risk'] is None or ep['exit'] is not None or ep.get('triggered'):
                continue
            market = snap['market'].get(t['base_currency'],{})
            fresh = (positive(market.get('mark')) and
                     0<=now-market.get('book_time',0)<=10 and
                     0<=now-market.get('mark_requested',0)<=10 and
                     0<=market.get('mark_received',0)-market.get('mark_requested',0)<=5)
            if not fresh:
                ep['flags'].append('stale_or_missing_market')
                continue
            direction = -1 if ep['short'] else 1
            mark, risk = market['mark'],ep['original_risk']
            # Observe the previously armed stop first; revisions apply next sample.
            if ep['armed'] and direction*(mark-ep['stop'])<=0:
                limit = ep['stop']*(1.02 if ep['short'] else .98)
                px = depth_price(market['levels'],ep['amount'],ep['short'],limit)
                if px is None:
                    ep['flags'].append('triggered_stop_limit_unfillable')
                    # A triggered limit must persist, not be re-armed after rebound.
                    ep['triggered'] = True
                else:
                    ep['exit'] = {'ts':now,'price':px,'gross_r':direction*(px-ep['entry'])/risk,
                                  'funding_observed':t.get('funding_fees'),
                                  'entry_fee':t.get('fee_open_cost'),
                                  'exit_fee_rate':t.get('fee_close'),
                                  'kind':'modeled_depth_quote_not_execution'}
            if ep.get('triggered'):
                # Nonfill is unresolved and excluded; never invent a later fill.
                ep['flags'].append('unresolved_triggered_limit')
                continue
            if ep['exit'] is not None:
                continue
            ep['peak_r'] = max(ep['peak_r'],direction*(mark-ep['entry'])/risk)
            source = t.get('stop_loss_abs')
            if positive(source):
                ep['stop'] = min(ep['stop'],source) if ep['short'] else max(ep['stop'],source)
            if ep['peak_r']>=2:
                ep['armed'] = True
                candidate = ep['entry']+direction*(ep['peak_r']-1)*risk
                ep['stop'] = min(ep['stop'],candidate) if ep['short'] else max(ep['stop'],candidate)
    counts = Counter(flag for ep in episodes.values() for flag in set(ep['flags']))
    return {'episodes':len(episodes),'armed':sum(ep['armed'] for ep in episodes.values()),
            'modeled_exits':sum(ep['exit'] is not None for ep in episodes.values()),
            'baseline_closed':sum(ep['baseline'] is not None for ep in episodes.values()),
            'flagged_episodes':sum(bool(ep['flags']) for ep in episodes.values()),'flags':dict(counts),
            'promotion_ready':False,
            'limitations':['Sampled marks can miss intraminute triggers and peaks.',
                'Depth quotes are not executions; latency, competing liquidity and exchange updates remain unvalidated.',
                'Funding snapshots are unsettled/endpoint estimates, not matched funding cash flows; no net profitability score yet.',
                'Partial-fill/source-exit event replay and paired uncertainty reporting remain required.']}


def report(directory):
    protocol = json.loads((directory/'manifest.json').read_text())
    def snapshots():
        for path in sorted(directory.glob('observations-*.jsonl')):
            with path.open() as f:
                for line in f:
                    yield json.loads(line)  # corrupt tape fails loudly, never skips
    return evaluate(snapshots(),protocol)


if __name__ == '__main__':
    print(json.dumps(report(Path(sys.argv[1])),indent=2))
