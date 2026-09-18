"""Paired exit accounting from private observations and exchange cash-flow events.

Actual baseline fills, fees and settled funding are shared until a modeled exit.
No fitted parameters, order submission, portfolio-return or execution guarantee.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import heapq
import math
from pathlib import Path
import random
import statistics
import sys

from shadow import original_stop, positive

SCENARIOS = (
    ('quoted',0,1.0,0),
    ('one_sample_half_depth',1,.5,10),
    ('two_samples_quarter_depth',2,.25,25),
)


def number(x):
    value=float(x)
    if not math.isfinite(value):
        raise ValueError('Non-finite cash flow')
    return value


def merge_ledger(batches):
    fills, funding, coverage = {}, {}, []
    for b in batches:
        coverage.append((b['start_ms'],b['end_ms']))
        for kind,target,identity in [('fills',fills,lambda r:(r['coin'],r['tid'])),
                ('funding',funding,lambda r:(r['time'],r['delta']['coin'],r['hash']))]:
            for r in b[kind]:
                key=identity(r)
                if key in target and target[key] != r:
                    raise ValueError('Conflicting duplicate ledger event')
                target[key]=r
    merged=[]
    for lo,hi in sorted(coverage):
        if merged and lo<=merged[-1][1]+1:
            merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:
            merged.append((lo,hi))
    return list(fills.values()),list(funding.values()),merged


def trade_events(trade,fills,funding):
    """Exact order-id join, each partial exchange fill appears once."""
    orders={str(o['order_id']):o for o in trade['orders']}
    events=[]
    totals=defaultdict(float)
    for f in fills:
        key=str(f['oid'])
        if key not in orders or f['coin'] != trade['base_currency']:
            continue
        o=orders[key]
        if f.get('feeToken') != 'USDC':
            raise ValueError('Unsupported fee currency')
        qty,price,fee=number(f['sz']),number(f['px']),number(f['fee'])
        if qty<=0 or price<=0:
            raise ValueError('Invalid fill')
        totals[key]+=qty
        entry_side='sell' if trade['is_short'] else 'buy'
        entry=o['ft_order_side']==entry_side
        expected='A' if (trade['is_short'] if entry else not trade['is_short']) else 'B'
        if f['side'] != expected:
            raise ValueError('Fill side mismatch')
        events.append(dict(ts=f['time'],kind='entry' if entry else 'exit',qty=qty,price=price,
            fee=fee,stop=o['ft_order_side']=='stoploss',id=str(f['tid'])))
    for key,o in orders.items():
        expected=number(o.get('filled') or 0)
        if not math.isclose(totals[key],expected,rel_tol=1e-7,abs_tol=1e-8):
            raise ValueError('Exchange fill quantity does not reconcile with executor order')
    starts=[e['ts'] for e in events if e['kind']=='entry']
    if not starts:
        raise ValueError('No matched entry fills')
    end=trade.get('close_timestamp') if not trade['is_open'] else None
    for f in funding:
        d=f['delta']
        if d['coin']==trade['base_currency'] and min(starts)<=f['time'] and (end is None or f['time']<=end):
            events.append(dict(ts=f['time'],kind='funding',cash=number(d['usdc']),position=number(d['szi'])))
    return sorted(events,key=lambda e:(e['ts'],0 if e['kind']=='funding' else 1,e.get('id','')))


def baseline(events,short):
    direction=-1 if short else 1
    qty,cash=0.0,0.0
    for e in events:
        if e['kind']=='funding':
            if not math.isclose(direction*qty,e['position'],rel_tol=1e-6,abs_tol=1e-7):
                raise ValueError('Funding position does not match this trade at settlement')
            cash+=e['cash']
        else:
            sign=1 if e['kind']=='entry' else -1
            qty+=sign*e['qty']
            cash-=direction*sign*e['qty']*e['price']+e['fee']
            if qty < -1e-7:
                raise ValueError('Exit exceeds matched entry quantity')
    return cash,qty


def book_fill(market,qty,short,limit,haircut,slip):
    """Full size, adverse slippage, limit respected; insufficient depth is a nonfill."""
    levels=market['levels'][1 if short else 0]
    left,value=qty,0.0
    for row in levels:
        px=number(row['px'])*(1+slip/10000 if short else 1-slip/10000)
        size=number(row['sz'])*haircut
        if px<=0 or size<0:
            raise ValueError('Invalid book')
        if px>limit if short else px<limit:
            continue
        used=min(left,size)
        value+=used*px
        left-=used
        if left<=max(1e-9,qty*1e-9):
            return value/qty
    return None


def replay(events,observations,trade,delay=0,haircut=1,slip=0,max_gap=120):
    short=trade['is_short']; direction=-1 if short else 1
    entries=[e for e in events if e['kind']=='entry']
    size=sum(e['qty'] for e in entries)
    entry=sum(e['qty']*e['price'] for e in entries)/size
    stop=original_stop(trade)
    if not positive(stop) or direction*(entry-stop)<=0:
        raise ValueError('Missing or invalid original risk')
    risk=direction*(entry-stop); risk_usd=risk*size
    last_entry=max(e['ts'] for e in entries)
    if any(e['kind']=='exit' and e['ts']<last_entry for e in events):
        raise ValueError('Position increases after exits need a distinct protocol')
    qty,cash,peak=0.0,0.0,0.0
    armed=False; trigger=None; shadow_exit=None; previous=None; bad=set(); nonfills=0
    # Accounting events win ties. Ambiguous stop/funding ties are flagged below.
    timeline=heapq.merge(((e['ts'],0,e) for e in events),
        ((int(s['ts']*1000),1,s) for s in observations),key=lambda x:(x[0],x[1]))
    for ts,kind,row in timeline:
        if kind==0:
            if row['kind']=='entry':
                if shadow_exit is not None:
                    bad.add('entry_after_shadow_exit')
                    continue
                qty+=row['qty']; cash-=direction*row['qty']*row['price']+row['fee']
            elif row['kind']=='funding':
                if shadow_exit is None:
                    if not math.isclose(direction*qty,row['position'],rel_tol=1e-6,abs_tol=1e-7):
                        bad.add('funding_position_mismatch')
                    cash+=row['cash']
            elif shadow_exit is None:
                # Once replaced by a tighter modeled stop, do not borrow a fill
                # from the original stop if the modeled stop failed to execute.
                if row['stop'] and armed:
                    bad.add('baseline_stop_filled_before_modeled_exit')
                    continue
                if qty+1e-7<row['qty']:
                    bad.add('source_exit_quantity_mismatch')
                    continue
                qty-=row['qty']; cash+=direction*row['qty']*row['price']-row['fee']
            continue
        if ts<last_entry or shadow_exit is not None or qty<=1e-7:
            continue
        if previous is not None and ts-previous>max_gap*1000:
            bad.add('observation_gap')
        previous=ts
        m=row['market'].get(trade['base_currency'],{})
        fresh=(positive(m.get('mark')) and 0<=row['ts']-m.get('book_time',0)<=10
            and 0<=row['ts']-m.get('mark_requested',0)<=10
            and 0<=m.get('mark_received',0)-m.get('mark_requested',0)<=5)
        if not fresh:
            bad.add('stale_market'); continue
        if armed and trigger is None and direction*(m['mark']-stop)<=0:
            trigger={'ts':ts,'remaining_samples':delay,'limit':stop*(1.02 if short else .98)}
        if trigger is not None:
            if trigger['remaining_samples']>0:
                trigger['remaining_samples']-=1
                continue
            price=book_fill(m,qty,short,trigger['limit'],haircut,slip)
            if price is None:
                nonfills+=1; continue
            available=[f for f in trade.get('_fee_observations',[]) if 0<=ts-f['ts']<=7200000]
            if not available:
                bad.add('missing_causal_taker_fee'); continue
            fee_rate=number(max(available,key=lambda f:f['ts'])['taker_rate'])
            if fee_rate<0:
                raise ValueError('Negative modeled taker fee')
            cash+=direction*qty*price-qty*price*fee_rate
            qty=0.0; shadow_exit=ts
            if any(e['kind']=='funding' and e['ts']==ts for e in events):
                bad.add('funding_exit_timestamp_tie')
            continue
        peak=max(peak,direction*(m['mark']-entry)/risk)
        observed=next((t for t in row['trades'] if t['trade_id']==trade['trade_id']),None)
        if observed and positive(observed.get('stop_loss_abs')):
            source=observed['stop_loss_abs']
            stop=min(stop,source) if short else max(stop,source)
        if peak>=2:
            armed=True
            candidate=entry+direction*(peak-1)*risk
            stop=min(stop,candidate) if short else max(stop,candidate)
    if qty>1e-7:
        bad.add('challenger_unresolved')
    return dict(net_usd=cash if qty<=1e-7 else None,risk_usd=risk_usd,armed=armed,
                modeled_exit_ms=shadow_exit,flags=sorted(bad),nonfill_observations=nonfills)


def paired_summary(rows):
    if not rows:
        return {'completed_pairs':0,'mean_delta_r':None,'date_cluster_ci95':None}
    groups=defaultdict(list)
    for r in rows:
        groups[r['date']].append(r['delta_r'])
    values=[r['delta_r'] for r in rows]
    clusters=list(groups.values()); rng=random.Random(20260916)
    draws=[]
    if len(clusters)>=2:
        for _ in range(2000):
            sample=[x for group in rng.choices(clusters,k=len(clusters)) for x in group]
            draws.append(statistics.mean(sample))
    draws.sort()
    def drawdown(key):
        total=peak=worst=0.0
        for r in sorted(rows,key=lambda r:r['closed_ms']):
            total+=r[key]; peak=max(peak,total); worst=max(worst,peak-total)
        return worst
    return {'completed_pairs':len(rows),'date_clusters':len(groups),
        'baseline_mean_r':statistics.mean(r['baseline_r'] for r in rows),
        'candidate_mean_r':statistics.mean(r['candidate_r'] for r in rows),
        'armed_pairs':sum(r.get('armed',False) for r in rows),
        'mean_delta_r':statistics.mean(values),'date_cluster_ci95':[draws[50],draws[1949]] if draws else None,
        'worse_pairs':sum(v<0 for v in values),'missed_baseline_winners':sum(r['baseline_r']>0 and r['delta_r']<0 for r in rows),
        'baseline_closed_sequence_drawdown_r':drawdown('baseline_r'),
        'candidate_closed_sequence_drawdown_r':drawdown('candidate_r'),
        'drawdown_basis':'equal-risk completed pairs ordered by baseline close; not portfolio mark-to-market'}


def analyze(snapshots,protocol,batches):
    raw_source=snapshots if callable(snapshots) else lambda: iter(snapshots)
    ledger_source=batches if callable(batches) else lambda: iter(batches)
    fills,funding,coverage=merge_ledger(ledger_source())
    ledger_end=max((hi for _,hi in coverage),default=None)
    def source():
        for frame in raw_source():
            if ledger_end is not None and frame['ts']*1000<=ledger_end:
                yield frame
    latest={}; first={}
    fee_observations=[b['fee_observation'] for b in ledger_source() if 'fee_observation' in b]
    previous=None
    for s in source():
        if previous is not None and s['ts']<=previous:
            raise ValueError('Nonchronological observations')
        if s.get('collector_sha256')!=protocol['collector_sha256']:
            raise ValueError('Mixed observation epochs')
        previous=s['ts']
        for t in s['trades']:
            latest[str(t['trade_id'])]=t
            first.setdefault(str(t['trade_id']),s['ts'])
    # Freeze repeated scans at the same snapshot boundary, even if the live
    # collector appends more observations while this report is being built.
    cutoff_ms=previous*1000 if previous is not None else None
    def source():
        for frame in raw_source():
            if cutoff_ms is not None and frame['ts']*1000<=cutoff_ms:
                yield frame
    fills=[f for f in fills if cutoff_ms is not None and f['time']<=cutoff_ms]
    funding=[f for f in funding if cutoff_ms is not None and f['time']<=cutoff_ms]
    rows={name:[] for name,*_ in SCENARIOS}; exclusions=Counter(); reconciled=0; funding_discrepancies=0
    scenario_flags={name:Counter() for name,*_ in SCENARIOS}; nonfills=Counter()
    for key,t in latest.items():
        try:
            events=trade_events(t,fills,funding)
            cash,qty=baseline(events,t['is_short'])
            if not t['is_open'] and qty>1e-7:
                raise ValueError('Closed trade has unmatched residual')
            # Exchange arithmetic is authoritative; executor is a cross-check.
            if not t['is_open']:
                expected=t.get('close_profit_abs')
                settled_funding=sum(e['cash'] for e in events if e['kind']=='funding')
                reported_funding=number(t.get('funding_fees') or 0)
                if abs(settled_funding-reported_funding)>1e-5:
                    funding_discrepancies+=1
                comparable=cash-settled_funding+reported_funding
                if expected is None or abs(comparable-number(expected))>max(1e-5,abs(comparable)*1e-6):
                    raise ValueError('Executor net PnL disagrees with settled exchange cash flows')
                reconciled+=1
            entry_ms=min(e['ts'] for e in events if e['kind']=='entry')
            end=t.get('close_timestamp') if not t['is_open'] else int(previous*1000)
            if not any(lo<=entry_ms and hi>=end for lo,hi in coverage):
                raise ValueError('Ledger coverage incomplete')
        except (ValueError,TypeError,KeyError) as exc:
            exclusions[str(exc) if isinstance(exc,ValueError) else 'missing_accounting_field']+=1
            continue
        if entry_ms < protocol['start']*1000:
            exclusions['pre_epoch_observational']+=1; continue
        if first[key]*1000-entry_ms>protocol['max_gap_seconds']*1000:
            exclusions['late_first_observation']+=1; continue
        if t['is_open']:
            exclusions['baseline_still_open']+=1; continue
        def observations():
            return (s for s in source() if entry_ms<=s['ts']*1000<=end)
        last_observed=None
        for frame in observations():
            last_observed=frame['ts']*1000
        if last_observed is None or end-last_observed>protocol['max_gap_seconds']*1000:
            exclusions['observation_coverage_incomplete']+=1; continue
        for name,delay,haircut,slip in SCENARIOS:
            try:
                result=replay(events,observations(),dict(t,_fee_observations=fee_observations),delay,haircut,slip,protocol['max_gap_seconds'])
            except (ValueError,TypeError,KeyError):
                scenario_flags[name]['invalid_replay_input']+=1; continue
            nonfills[name]+=result['nonfill_observations']
            if result['flags']:
                scenario_flags[name].update(result['flags']); continue
            risk=result['risk_usd']
            rows[name].append({'baseline_r':cash/risk,'candidate_r':result['net_usd']/risk,
                'delta_r':(result['net_usd']-cash)/risk,'closed_ms':end,'armed':result['armed'],
                'date':datetime.fromtimestamp(entry_ms/1000,timezone.utc).date().isoformat()})
    return {'ledger_end_ms':ledger_end,'observation_cutoff_ms':cutoff_ms,
        'input_status':'aligned' if cutoff_ms is not None else 'waiting_for_common_coverage',
        'executor_funding_discrepancies':funding_discrepancies,'exchange_reconciled_closed_trades':reconciled,'observed_trade_count':len(latest),
        'exclusions':dict(exclusions),'scenarios':{name:dict(paired_summary(rows[name]),
            flagged=dict(scenario_flags[name]),nonfill_observations=nonfills[name]) for name,*_ in SCENARIOS},
        'promotion_ready':False,'interpretation':'Executable research accounting, not proof of profitable live execution. Fresh sample and deployment validation still required.'}


def report(directory):
    protocol=json.loads((directory/'manifest.json').read_text())
    def snapshots():
        for p in sorted(directory.glob('observations-*.jsonl')):
            with p.open() as f:
                for line in f:
                    yield json.loads(line)
    def batches():
        for p in sorted((directory/'ledger').glob('*.json')):
            yield json.loads(p.read_text())
    return analyze(snapshots,protocol,batches)


if __name__=='__main__':
    directory=Path(sys.argv[1])
    result=report(directory)
    if '--write' in sys.argv:
        temporary=directory/'accounting-report.tmp'
        temporary.write_text(json.dumps(result,indent=2))
        temporary.chmod(0o600)
        temporary.replace(directory/'accounting-report.json')
    print(json.dumps(result,indent=2))
