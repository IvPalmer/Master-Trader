"""Exploratory hourly Chandelier diagnostic; no runtime or exchange integration."""
import argparse
from collections import deque
import json
from pathlib import Path

from research.profit_retention.historical import BAR_MS, DAY_MS, load_cases, walk
from research.profit_retention.take_profit import summarize

HOUR_MS = 3_600_000


def levels(bars, short):
    """Yield a causal completed-hour level, or None, for each 5-minute bar.

    Only complete UTC hours count. ATR starts with 22 true ranges, each with
    an observed previous close; subsequent values use Wilder smoothing.
    """
    hour, rows, previous_close, atr = None, [], None, None
    ranges, history = [], deque(maxlen=22)
    previous_ts = None
    for row in bars:
        if previous_ts is not None and row[0] - previous_ts != BAR_MS:
            hour, rows, previous_close, atr, ranges = None, [], None, None, []
            history.clear()
        previous_ts = row[0]
        bucket = row[0] // HOUR_MS
        if bucket != hour:
            hour, rows = bucket, []
        rows.append(row)
        level = None
        if row[0] % HOUR_MS == HOUR_MS - BAR_MS:
            complete = (len(rows) == 12 and rows[0][0] % HOUR_MS == 0
                        and all(b[0] - a[0] == BAR_MS for a, b in zip(rows, rows[1:])))
            if complete:
                high, low, close = max(r[2] for r in rows), min(r[3] for r in rows), rows[-1][4]
                history.append((high, low))
                if previous_close is not None:
                    tr = max(high-low, abs(high-previous_close), abs(low-previous_close))
                    if atr is None:
                        ranges.append(tr)
                        if len(ranges) == 22:
                            atr = sum(ranges)/22
                    else:
                        atr = (21*atr + tr)/22
                    if atr is not None:
                        level = (min(x[1] for x in history) + 3*atr if short
                                 else max(x[0] for x in history) - 3*atr)
                previous_close = close
            else:
                previous_close, atr, ranges = None, None, []
                history.clear()
        yield level


def replay(case, indicator_levels, cost_bps=10, funding_bps_day=0):
    entry, stop, short, target = (case[k] for k in ('entry', 'stop', 'short', 'target'))
    direction = -1 if short else 1
    risk, active, peak, armed = direction*(entry-stop), stop, 0.0, False
    bars = case['bars']
    if len(indicator_levels) != len(bars):
        raise ValueError('one causal indicator level required per bar')
    reason = 'horizon'
    for row, level in zip(bars, indicator_levels):
        ts, o, high, low, close, mark_high, mark_low = row
        adverse = mark_high if short else mark_low
        if direction*(adverse-active) <= 0:
            px = max(o, active) if short else min(o, active)
            reason = 'stop'
            break
        if (low <= target if short else high >= target):
            px, reason = target, 'target'
            break
        peak = max(peak, direction*((mark_low if short else mark_high)-entry)/risk)
        if peak >= 2 and level is not None and direction*(level-entry) > 0:
            armed = True
            active = min(active, level) if short else max(active, level)
        px = close
    days = (ts + BAR_MS - bars[0][0])/DAY_MS
    net = direction*(px-entry)/risk - cost_bps/10000*(entry+px)/risk
    net -= funding_bps_day/10000*entry*days/risk
    return dict(r=net, days=days, armed=armed, reason=reason)


def run(root):
    cases, excluded, total, fingerprint = load_cases(root)
    computed = [list(levels(c['bars'], c['short'])) for c in cases]
    result = dict(input_sha256=fingerprint, signal_count=total, eligible=len(cases),
                  excluded=excluded, scenarios={})
    for cost in (4.5, 10, 25):
        for carry in (-10, 0, 10):
            base = [walk(**c, trail=False, cost_bps=cost, funding_bps_day=carry) for c in cases]
            candidate = [replay(c, lv, cost, carry) for c, lv in zip(cases, computed)]
            report = summarize(base, candidate)
            report['armed'] = sum(x['armed'] for x in candidate)
            report['baseline_mean_r'] = summarize(base, base)['mean_r']
            result['scenarios'][f'cost_{cost}_carry_{carry}'] = report
    result['limitations'] = [
        'Already researched Binance corpus, not holdout or live Hyperliquid execution.',
        'Post-entry warmup: 23 full hours; early trades retain original stop.',
        'Final-target proxy only; posted partial exits and plan changes are not replayed here.',
        '14-day horizon; no source revisions, liquidation, replacement entries or portfolio capacity.',
        'Adverse-first mark stop and trade TP-touch fills; no queue, depth or nonfill model.',
        'Fixed fees and signed carry stresses, not actual settled funding.',
        'No statistical significance claim for dependent overlapping signals.',
    ]
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache_root', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.cache_root), indent=2))
