import importlib.util
from pathlib import Path
import pytest
s=importlib.util.spec_from_file_location('retention',Path(__file__).parents[1]/'research/profit_retention/replay.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def trade(bars,short=False):
 return dict(entry=100,stop=110 if short else 90,start=10,end=40,end_price=100,bars=bars,short=short)
def bar(start,end,o,h,l):
 return dict(start=start,end=end,open=o,high=h,low=l)
def test_trail_is_not_applied_retroactively():
 t=trade([bar(10,20,100,130,95)])
 assert m.replay(t,'trail_1r_after_2r') == 0
 t['bars'].append(bar(20,30,125,128,119))
 assert m.replay(t,'trail_1r_after_2r') == 2

def test_gap_fills_at_open_not_better_stop():
 t=trade([bar(10,20,100,111,95),bar(20,30,97,99,93)])
 assert m.replay(t,'breakeven_after_1r') == -.3

def test_short_and_entry_bar_causality():
 t=trade([bar(0,20,100,120,50),bar(20,30,100,105,79),bar(30,40,85,91,82)],True)
 assert m.replay(t,'trail_1r_after_2r') == pytest.approx(1.1)
