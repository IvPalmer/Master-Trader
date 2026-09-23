import pytest
from research.profit_retention.chandelier import levels, replay
from research.profit_retention.historical import BAR_MS


def flat(hours):
    return [[i*BAR_MS, 100, 101, 99, 100, 101, 99] for i in range(hours*12)]


@pytest.mark.parametrize('short,expected', [(False, 95), (True, 105)])
def test_atr_needs_22_true_ranges_and_previous_close(short, expected):
    out = list(levels(flat(24), short))
    assert all(x is None for x in out[:275])
    assert out[275] == expected
    assert out[287] == expected


def test_partial_entry_hour_and_gap_do_not_supply_warmup():
    assert all(x is None for x in levels(flat(23)[1:], False))
    bars = flat(24)
    del bars[200]
    assert all(x is None for x in levels(bars, False))


def test_prefix_is_unchanged_by_future_price():
    bars = flat(24)
    prefix = list(levels(bars[:276], False))
    bars[276][2] = 1000
    assert list(levels(bars, False))[:276] == prefix


@pytest.mark.parametrize('short,stop,target,rows,lv', [
    (False, 90, 150, [[0,100,125,99,120,125,99],
                    [BAR_MS,120,122,111,115,122,111],
                    [2*BAR_MS,115,116,109,110,116,109]], [110,105,None]),
    (True, 110, 50, [[0,100,101,75,80,101,75],
                    [BAR_MS,80,89,78,85,89,78],
                    [2*BAR_MS,85,91,84,90,91,84]], [90,95,None]),
])
def test_new_level_applies_next_bar_and_never_loosens(short, stop, target, rows, lv):
    case = dict(entry=100, stop=stop, short=short, target=target, bars=rows)
    r = replay(case, lv, cost_bps=0)
    assert r['r'] == 1
    assert r['days'] == 3*BAR_MS/86_400_000
    assert r['reason'] == 'stop'


def test_early_original_stop_remains_and_wins_same_bar_target():
    case = dict(entry=100, stop=90, target=120, short=False,
                bars=[[0,100,130,85,120,130,85]])
    r = replay(case, [110], cost_bps=0)
    assert r['r'] == -1
    assert not r['armed']


def test_wilder_smoothing_after_seed():
    bars = flat(24)
    bars[-1][2] = 123
    out = list(levels(bars, False))
    assert out[-1] == pytest.approx(123 - 3*((21*2+24)/22))
