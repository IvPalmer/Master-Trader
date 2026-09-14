#!/usr/bin/env python3
"""Offline replay of archived quotes at recorded hourly decision times; no network."""
import argparse
import gzip
import json
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import tracker


def replay(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Replay output must be new; original records are never overwritten')
    (output / 'data').mkdir(parents=True)
    funding = tracker.load_funding(str(source))
    tracker.load_funding = lambda _: funding
    cached = {}
    def load_quotes(_, now, lookback_s=3700):
        dates = [(now - timedelta(days=d)).strftime('%Y%m%d') for d in (0, 1)]
        for old in list(cached):
            if old not in dates:
                del cached[old]
        for date in dates:
            if date in cached:
                continue
            fp = source / 'data' / f'bbo_{date}.jsonl'
            if not fp.exists():
                fp = fp.with_suffix('.jsonl.gz')
            rows = defaultdict(list)
            if fp.exists():
                with (gzip.open(fp, 'rt') if str(fp).endswith('.gz') else open(fp)) as f:
                    for line in f:
                        r = json.loads(line)
                        rows[r['coin']].append(r)
            cached[date] = {c: (sorted(rs, key=lambda r:r['ts'])) for c, rs in rows.items()}
        latest, past = {}, defaultdict(list)
        for date in reversed(dates):
            for coin, rows in cached[date].items():
                times = [r['ts'] for r in rows]
                a = bisect_right(times, now.timestamp() - lookback_s)
                b = bisect_right(times, now.timestamp())
                past[coin].extend(rows[a:b])
                if b and 0 <= now.timestamp() - rows[b-1]['ts'] <= 120:
                    latest[coin] = rows[b-1]
        return latest, past
    tracker.load_bbo_snaps = load_quotes
    decisions = []
    for line in (source / 'monitor.log').read_text().splitlines():
        if ' tracker:' in line:
            decisions.append(datetime.fromisoformat(line.split()[0]))
    decisions = sorted(set(decisions))
    if not decisions:
        raise ValueError('No recorded hourly decisions')
    for i, now in enumerate(decisions):
        tracker.run_hourly(str(output), now)
        if i % 168 == 0:
            print(f'{i}/{len(decisions)} {now.isoformat()}', flush=True)
    events_path = output / 'data' / 'episodes.jsonl'
    events = [json.loads(l) for l in events_path.read_text().splitlines()] if events_path.exists() else []
    exits = [e for e in events if e['event'] == 'exit']
    state = tracker.load_state(str(output))
    hours = sum(e['duration_h'] for e in exits)
    net = sum(e['net'] for e in exits)
    days = (decisions[-1] - decisions[0]).total_seconds() / 86400
    # Whole-life completed-episode exposure is a matched denominator. Never
    # call this a portfolio return when positions remain open.
    summary = {
        'accounting_version': 2, 'start': decisions[0].isoformat(), 'end': decisions[-1].isoformat(),
        'decision_count': len(decisions), 'closed_episodes': len(exits),
        'open_episodes': len(state['open_episodes']), 'net_model_usd': net,
        'funding_model_usd': sum(e['funding_received'] for e in exits),
        'basis_model_usd': sum(e['basis_pnl'] for e in exits),
        'fees_model_usd': sum(e['total_fees'] for e in exits),
        'completed_position_hours': hours,
        'completed_episode_yield_annual_pct': net / (hours * 1500) * 8760 * 100 if hours else None,
        'provisioned_return_pct': net / tracker.PROVISIONED_PEAK * 100 if not state['open_episodes'] else None,
        'provisioned_yield_annual_pct': net / tracker.PROVISIONED_PEAK * 365 / days * 100 if days and not state['open_episodes'] else None,
        'cost_stress_extra_5bps_each_of_four_fills_net_usd': net - len(exits) * tracker.NOTIONAL * 4 * 5 / 10000,
        'cost_stress_extra_10bps_each_of_four_fills_net_usd': net - len(exits) * tracker.NOTIONAL * 4 * 10 / 10000,
        'fills_before_signal': sum(e['fill_ts'] <= e['signal_ts'] for e in exits),
        'decision': 'RESEARCH_ONLY: execution depth, quote timing, actual fees and funding notional remain unvalidated',
        'limitations': ['Archived timestamps mark snapshot start; cross-venue quotes are not atomic.',
            'Funding archive has settlement timestamps but no ingestion timestamps.',
            'Model uses fixed $1000 funding notional and frozen fee assumptions.',
            'Trade-through is a paper fill proxy; depth and hedge latency are not simulated.',
            'Capital model is $1500 per episode, not verified production margin requirements.'],
    }
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source'); parser.add_argument('output')
    args = parser.parse_args()
    replay(args.source, args.output)
