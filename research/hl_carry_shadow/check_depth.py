#!/usr/bin/env python3
"""Read-only check of recorded top-of-book size for the replay's modeled fills."""
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def check(source, replay):
    source, replay = Path(source), Path(replay)
    events = [json.loads(l) for l in (replay/'data/episodes.jsonl').read_text().splitlines()]
    needed = {}
    for e in events:
        if e['event'] in {'fill', 'exit'}:
            ts = e['fill_ts'] if e['event'] == 'fill' else e['exit_ts']
            needed[(e['coin'], ts)] = e
    quotes = {}
    days = sorted({datetime.fromtimestamp(ts, timezone.utc).strftime('%Y%m%d') for _, ts in needed})
    for day in days:
        fp = source/'data'/f'bbo_{day}.jsonl'
        if not fp.exists():
            fp = fp.with_suffix('.jsonl.gz')
        with (gzip.open(fp,'rt') if str(fp).endswith('.gz') else open(fp)) as f:
            for line in f:
                r = json.loads(line)
                if (r['coin'],r['ts']) in needed:
                    quotes[(r['coin'],r['ts'])] = r
    issues = []
    for key, e in needed.items():
        r = quotes.get(key,{})
        qty = 1000 / e['perp_entry']
        fields = ('hl_bid_sz','bn_ask_sz') if e['event']=='fill' else ('hl_ask_sz','bn_bid_sz')
        for field in fields:
            size = r.get(field)
            if size is None or size < qty:
                issues.append({'episode':e['ep_id'],'coin':e['coin'],'event':e['event'],
                               'field':field,'required_base_qty':qty,'recorded_base_qty':size})
    return {'modeled_fill_events':len(needed),'checked_legs':len(needed)*2,
            'missing_or_insufficient_top_of_book_legs':len(issues),'issues':issues,
            'interpretation':'Screen only. Sufficient recorded size does not prove atomic quotes, queue fill or hedge latency.'}

if __name__ == '__main__':
    print(json.dumps(check(*sys.argv[1:]),indent=2))
