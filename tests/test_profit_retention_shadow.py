import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]/'research/profit_retention'

def module(name):
    spec = importlib.util.spec_from_file_location(name,ROOT/f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

s = module('shadow')
h = module('historical')
PROTOCOL = dict(start=100,collector_sha256='frozen',max_gap_seconds=120)


def snap(ts, mark=100, short=False, book=None):
    return dict(ts=ts,collector_sha256='frozen',trades=[dict(trade_id=1,is_open=True,
        amount=2,open_fill_timestamp=110000,open_rate=100,enter_tag='x|sl:110' if short else 'x|sl:90',
        is_short=short,nr_of_successful_entries=1,nr_of_successful_exits=0,
        base_currency='X',stop_loss_abs=110 if short else 90)],market={'X':dict(
        mark=mark,book_time=ts,mark_requested=ts-1,mark_received=ts,
        levels=book or [[dict(px=str(mark-.1),sz='100')],[dict(px=str(mark+.1),sz='100')]])})


def test_shadow_does_not_retroactively_use_the_arming_sample():
    report = s.evaluate([snap(120),snap(180,130)],PROTOCOL)
    assert report['armed'] == 1
    assert report['modeled_exits'] == 0
    report = s.evaluate([snap(120),snap(180,130),snap(240,119)],PROTOCOL)
    assert report['modeled_exits'] == 1
    assert report['promotion_ready'] is False


def test_stale_gap_and_preexisting_positions_are_visible():
    a,b = snap(120),snap(360,130)
    a['trades'][0]['open_fill_timestamp'] = 90000
    b['market']['X']['book_time'] = 100
    report = s.evaluate([a,b],PROTOCOL)
    assert report['flags']['pre_epoch_observational'] == 1
    assert report['flags']['observation_gap'] == 1
    assert report['flags']['stale_or_missing_market'] == 1
    assert report['armed'] == 0


def test_depth_requires_whole_size_inside_limit():
    levels = [[dict(px='120',sz='1'),dict(px='117',sz='10')],[]]
    assert s.depth_price(levels,2,False,118) is None
    assert s.depth_price(levels,2,False,116) == 118.5


def test_short_trigger_and_nonfill_are_not_credited():
    report = s.evaluate([snap(120,100,True),snap(180,70,True),snap(240,85,True)],PROTOCOL)
    assert report['armed'] == 1
    assert report['modeled_exits'] == 0
    assert report['flags']['triggered_stop_limit_unfillable'] == 1


def test_tape_must_be_chronological_and_version_consistent():
    with pytest.raises(ValueError):
        s.evaluate([snap(120),snap(120)],PROTOCOL)
    row = snap(120)
    row['collector_sha256'] = 'changed'
    with pytest.raises(ValueError):
        s.evaluate([row],PROTOCOL)


def test_partial_exits_remain_flagged():
    a,b = snap(120),snap(180)
    b['trades'][0].update(amount=1,nr_of_successful_exits=1)
    report = s.evaluate([a,b],PROTOCOL)
    assert report['flags']['position_size_changed'] == 1
    assert report['flags']['partial_or_multiple_fills_need_event_replay'] == 1


def test_historical_mark_trigger_precedes_target_and_accounts_for_costs():
    bars = [[0,100,150,95,110,150,89]]
    r = h.walk(bars,100,90,140,False,True,cost_bps=10)
    assert r['reason'] == 'stop'
    assert r['r'] == pytest.approx(-1.019)


def test_historical_trail_only_effective_on_next_bar():
    bars = [[0,100,131,95,125,130,95],[300000,119,125,117,120,125,117]]
    r = h.walk(bars,100,90,140,False,True,cost_bps=0)
    assert r['r'] == 1.9
    assert r['armed']


def test_unfillable_trigger_is_not_later_credited():
    rows=[snap(120),snap(180,130),snap(240,100),snap(300,119)]
    result=s.evaluate(rows,PROTOCOL)
    assert result['modeled_exits']==0
    assert result['flags']['triggered_stop_limit_unfillable']==1


def test_collector_freezes_hash_and_writes_private_tape(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    c=module('collector')
    root=tmp_path/'private'
    monkeypatch.setattr(c.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0,
        stdout=json.dumps(dict(ts=120,trades=[],market={})).encode()))
    assert c.collect(root)['ok']
    assert not (root.stat().st_mode & 0o077)
    tape=next(root.glob('observations-*.jsonl'))
    assert not (tape.stat().st_mode & 0o077)
    manifest=json.loads((root/'manifest.json').read_text())
    manifest['collector_sha256']='tampered'
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='Collector changed'):
        c.collect(root)


def test_collector_does_not_publish_failure_body(tmp_path,monkeypatch):
    from types import SimpleNamespace
    c=module('collector')
    monkeypatch.setattr(c.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1,
        stdout=b'',stderr=b'private credential context'))
    with pytest.raises(RuntimeError,match='no observation credited') as failure:
        c.collect(tmp_path/'private')
    assert 'credential' not in str(failure.value)
    assert not list((tmp_path/'private').glob('observations-*'))
