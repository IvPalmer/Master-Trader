import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('carry_tracker', Path(__file__).parents[1] / 'research/hl_carry_shadow/tracker.py')
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def setup(tmp_path, monkeypatch, pending=True):
    (tmp_path / 'data').mkdir()
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    sec = now.timestamp()
    state = t.default_state()
    state['open_episodes']['BTC'] = dict(ep_id='ep1', status='pending_fill' if pending else 'open',
        signal_ts=sec-3600, post_ts=sec-3600, posted_ask=100, n_reposts=0,
        fill_ts=sec-3500, perp_entry=100, spot_entry=100, entry_fee_hl=.15,
        entry_fee_bn=.75, entry_exec_basis=0, accrual_start_ts=(sec-3500)*1000,
        trail24_at_signal=.45)
    t.save_state(str(tmp_path), state)
    monkeypatch.setattr(t, 'load_funding', lambda _: {'BTC': [(int((sec-i*3600)*1000), 0) for i in range(30)]})
    return now, sec


def test_fill_requires_quote_after_post_and_before_expiry(tmp_path, monkeypatch):
    now, sec = setup(tmp_path, monkeypatch)
    quotes = [dict(ts=sec-3610, hl_bid=101, bn_ask=100), dict(ts=sec-3500, hl_bid=99, bn_ask=100)]
    monkeypatch.setattr(t, 'load_bbo_snaps', lambda *_: ({}, {'BTC':quotes}))
    t.run_hourly(str(tmp_path), now)
    assert t.load_state(str(tmp_path))['open_episodes']['BTC']['status'] == 'pending_fill'
    state = t.load_state(str(tmp_path)); state['open_episodes']['BTC']['post_ts'] = sec-7*3600
    t.save_state(str(tmp_path), state)
    quotes[:] = [dict(ts=sec-10, hl_bid=101, bn_ask=100)]
    t.run_hourly(str(tmp_path), now)
    assert t.load_state(str(tmp_path))['open_episodes']['BTC']['status'] == 'pending_fill'


def test_short_exit_buys_at_ask(tmp_path, monkeypatch):
    now, sec = setup(tmp_path, monkeypatch, pending=False)
    monkeypatch.setattr(t, 'load_bbo_snaps', lambda *_: ({'BTC':dict(ts=sec, hl_bid=99, hl_ask=101, bn_bid=100)}, {}))
    t.run_hourly(str(tmp_path), now)
    e=json.loads((tmp_path/'data/episodes.jsonl').read_text())
    assert e['perp_exit'] == 101
    assert e['net'] == -12.1


def test_quotes_ignore_future_stale_and_read_gzip(tmp_path):
    import gzip
    (tmp_path/'data').mkdir()
    now=datetime(2026,9,14,0,0,30,tzinfo=timezone.utc); sec=now.timestamp()
    rows=[dict(coin='BTC',ts=sec-60),dict(coin='STALE',ts=sec-300),dict(coin='BTC',ts=sec+1)]
    with gzip.open(tmp_path/'data/bbo_20260913.jsonl.gz','wt') as f:
        f.write('\n'.join(json.dumps(r) for r in rows))
    latest,past=t.load_bbo_snaps(str(tmp_path),now)
    assert latest == {'BTC':rows[0]}
    assert len(past['BTC']) == 1


def test_weekly_hours_include_open_and_clip_closed(tmp_path):
    (tmp_path/'data').mkdir()
    now=datetime(2026,9,14,tzinfo=timezone.utc); sec=now.timestamp()
    rows=[dict(event='fill',ep_id='a',ts=(sec-10*86400)*1000,fill_ts=sec-10*86400),
          dict(event='exit',ep_id='a',ts=(sec-86400)*1000,exit_ts=sec-86400,net=10),
          dict(event='fill',ep_id='b',ts=(sec-2*86400)*1000,fill_ts=sec-2*86400,n_reposts=0,fill_delay_h=1)]
    (tmp_path/'data/episodes.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    report=t.weekly_summary(str(tmp_path),now)
    assert report['active_position_hours'] == 192
    assert report['yield_on_avg_deployed_annual_pct'] is None
    assert report['yield_on_provisioned_peak_annual_pct'] is None


def test_future_funding_cannot_trigger_entry(tmp_path, monkeypatch):
    now, sec=setup(tmp_path, monkeypatch)
    t.save_state(str(tmp_path),t.default_state())
    monkeypatch.setattr(t,'load_funding',lambda _: {'BTC':[(int((sec+i*3600)*1000),.1) for i in range(1,31)]})
    monkeypatch.setattr(t,'load_bbo_snaps',lambda *_: ({'BTC':dict(ts=sec,hl_ask=100)},{}))
    t.run_hourly(str(tmp_path),now)
    assert not t.load_state(str(tmp_path))['open_episodes']
