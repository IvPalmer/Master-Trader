import pytest
from research.profit_retention.take_profit import capped_case, summarize
from research.profit_retention.historical import walk


@pytest.mark.parametrize('short,stop,target,expected', [
    (False, 90, 150, 120), (False, 90, 115, 115),
    (True, 110, 50, 80), (True, 110, 85, 85),
])
def test_cap_never_moves_source_target_farther(short, stop, target, expected):
    original = dict(entry=100, stop=stop, target=target, short=short)
    capped = capped_case(original)
    assert capped['target'] == expected
    assert original['target'] == target


@pytest.mark.parametrize('short,stop,target,high,low', [
    (False, 90, 150, 125, 85), (True, 110, 50, 115, 75),
])
def test_stop_wins_ambiguous_bar(short, stop, target, high, low):
    case = dict(entry=100, stop=stop, target=target, short=short,
                bars=[[0, 100, high, low, 100, high, low]])
    result = walk(**capped_case(case), trail=False, cost_bps=0)
    assert result['r'] == -1
    assert result['reason'] == 'stop'


def test_missed_winner_counts_sacrificed_return_not_only_losses():
    base = [dict(r=4, days=5), dict(r=-1, days=5)]
    candidate = [dict(r=2, days=1), dict(r=2, days=1)]
    report = summarize(base, candidate)
    assert report['missed_winners'] == 1
    assert report['winner_return_sacrificed_r'] == 2
    assert report['mean_delta_r'] == .5
