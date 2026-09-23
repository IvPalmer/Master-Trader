"""Fixed whole-position TP diagnostic; cache-only, never called by live bots."""
import argparse
import json
from pathlib import Path
import statistics

from research.profit_retention.historical import load_cases, walk


def capped_case(case):
    direction = -1 if case['short'] else 1
    risk = direction * (case['entry'] - case['stop'])
    cap = case['entry'] + direction * 2 * risk
    target = max(case['target'], cap) if case['short'] else min(case['target'], cap)
    return dict(case, target=target)


def summarize(base, candidate):
    delta = [b['r'] - a['r'] for a, b in zip(base, candidate)]
    cut = int(.7 * len(delta))
    mean = lambda values: statistics.mean(values) if values else None
    return dict(
        mean_r=mean([b['r'] for b in candidate]),
        mean_delta_r=mean(delta),
        early70_delta_r=mean(delta[:cut]), late30_delta_r=mean(delta[cut:]),
        delta_without_best=mean(sorted(delta)[:-1]),
        win_fraction=mean([b['r'] > 0 for b in candidate]),
        mean_holding_days=mean([b['days'] for b in candidate]),
        improved=sum(d > 1e-9 for d in delta), worse=sum(d < -1e-9 for d in delta),
        missed_winners=sum(a['r'] > 0 and b['r'] < a['r'] - 1e-9
                           for a, b in zip(base, candidate)),
        winner_return_sacrificed_r=sum(max(0, a['r'] - b['r'])
                                      for a, b in zip(base, candidate) if a['r'] > 0),
    )


def run(root):
    cases, skips, total, fingerprint = load_cases(root)
    result = dict(input_sha256=fingerprint, signal_count=total, eligible=len(cases),
                  excluded=skips, scenarios={})
    for cost in (4.5, 10, 25):
        for carry in (-10, 0, 10):
            def replay(cs, trail=False):
                return [walk(**c, trail=trail, cost_bps=cost, funding_bps_day=carry) for c in cs]
            baseline = replay(cases)
            result['scenarios'][f'cost_{cost}_carry_{carry}'] = {
                'final_source_target': summarize(baseline, baseline),
                'nearer_source_or_2r': summarize(baseline, replay([capped_case(c) for c in cases])),
                'existing_2r_1r_trail': summarize(baseline, replay(cases, trail=True)),
            }
    result['limitations'] = [
        'Previously studied Binance corpus; temporal blocks are diagnostics, not holdout.',
        'Whole-position final source target baseline is a proxy, not actual executable grouping.',
        'Next full bar entry, 14-day horizon; no source updates, liquidation or capital capacity.',
        'Adverse-first mark stop, trade-bar TP touch assumes fill; no queue/depth/nonfill model.',
        'Fixed transaction costs and signed carry stresses, not settled fees/funding.',
        'No independent-trade significance claim; overlapping signals are dependent.',
        'Missed winners means reduced positive baseline return, not necessarily a losing candidate.',
    ]
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache_root', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.cache_root), indent=2))
