"""Descriptive exit-overlay replay. No network or order submission.

Input stays private: actual entry/stop/end prices and closed OHLC bars. Not an
out-of-sample strategy test: the sample is selected after observed giveback.
"""
import json
import sys

POLICIES = ('breakeven_after_1r', 'lock_half_r_after_2r', 'trail_1r_after_2r')


def replay(trade, policy):
    if policy not in POLICIES:
        raise ValueError('Unknown exit policy')
    entry, initial = trade['entry'], trade['stop']
    direction = -1 if trade.get('short') else 1
    risk = direction * (entry - initial)
    if risk <= 0:
        raise ValueError('Initial stop must be on the loss side of entry')
    stop = initial
    peak_r = 0.0
    for bar in trade['bars']:
        # Only complete bars wholly after entry and before the observed endpoint.
        if bar['start'] < trade['start'] or bar['end'] > trade['end']:
            continue
        o, h, l = bar['open'], bar['high'], bar['low']
        adverse = l if direction == 1 else h
        if direction * (adverse - stop) <= 0:
            # A gap cannot fill at the better stop price. Extra execution costs
            # are deliberately reported separately by the study.
            px = min(o, stop) if direction == 1 else max(o, stop)
            return direction * (px-entry)/risk
        favorable = h if direction == 1 else l
        peak_r = max(peak_r, direction * (favorable-entry)/risk)
        # New stops become effective NEXT bar, never retroactively within a bar.
        candidate_r = -1.0
        if policy == 'breakeven_after_1r' and peak_r >= 1:
            candidate_r = 0.0
        elif policy == 'lock_half_r_after_2r' and peak_r >= 2:
            candidate_r = .5
        elif policy == 'trail_1r_after_2r' and peak_r >= 2:
            candidate_r = peak_r - 1
        candidate = entry + direction*candidate_r*risk
        stop = max(stop, candidate) if direction == 1 else min(stop, candidate)
    return direction*(trade['end_price']-entry)/risk


def summarize(trades):
    if not trades:
        raise ValueError('At least one trade is required')
    baseline = [(-1 if t.get('short') else 1)*(t['end_price']-t['entry'])/abs(t['entry']-t['stop']) for t in trades]
    out = {'sample_size':len(trades), 'observed_mean_gross_r':sum(baseline)/len(trades), 'policies':{}}
    for p in POLICIES:
        r = [replay(t,p) for t in trades]
        differences = [a-b for a,b in zip(r,baseline)]
        out['policies'][p] = {'mean_gross_r':sum(r)/len(r), 'mean_delta_r':sum(differences)/len(r),
            'improved':sum(d>1e-9 for d in differences),'worse':sum(d < -1e-9 for d in differences),
            'unchanged':sum(abs(d)<=1e-9 for d in differences)}
    out['limitations'] = ['Selected current cohort; no holdout or significance claim.',
        'Trade OHLC is not mark-price history; live stops trigger on marks.',
        '15m bars hide intrabar paths, latency, order-book depth and stop-limit nonfills.',
        'Gross R excludes fees/funding; alternative exits change funding exposure.',
        'No re-entry, replacement signals or portfolio-capacity effects modeled.',
        'Observed endpoints censor future returns of still-open positions.']
    out['limitations'].extend([
        'Partial entry/endpoint bars are excluded and may hide a trigger.',
        'No TP ladder or source-stop revisions are simulated; this is an overlay diagnostic.'])
    return out

if __name__ == '__main__':
    print(json.dumps(summarize(json.load(open(sys.argv[1]))),indent=2))
