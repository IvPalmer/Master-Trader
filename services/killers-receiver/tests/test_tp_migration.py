"""Network-free migration acceptance tests with a stateful executor double."""
import asyncio
import copy
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main as receiver
from app.tp_migration import Migration, install_routes
from .test_tp_reliability import trade


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv('KILLERS_DB', str(tmp_path/'receiver.sqlite'))
    monkeypatch.setenv('KILLERS_EXECUTION_VENUE', 'hyperliquid')
    monkeypatch.setenv('KILLERS_TP_MODE', 'nearest_source')
    monkeypatch.setenv('KILLERS_FT_PASSWORD', 'synthetic-operator-password')
    cfg = receiver.Config()
    conn = receiver.init_db(cfg.db_path)
    conn.execute("INSERT INTO positions (signal_id,symbol,pair,direction,state,open_msg_id,open_date,ft_trade_id,targets_remaining) VALUES (1,'TEST','TEST/USDC:USDC','long','open',1,'2026-01-01',42,'[1.1,1.2,2]')")
    conn.execute("INSERT INTO events (pos_id,msg_id,event_at,kind,payload) VALUES (1,1,'2026-01-01','open',?)", (json.dumps({'signal_targets': [1.1,1.2,2]}),))
    conn.execute("INSERT INTO target_orders (pos_id,idx,price,amount,state,ft_order_id) VALUES (1,2,2,40,'active','old-tp')")

    class Executor:
        def __init__(self):
            self.t = dict(trade(40), trade_id=42, pair='TEST/USDC:USDC',
                          current_rate=1, open_rate=1, open_timestamp=1700000000000,
                          stop_loss_abs=.84)
            self.t['orders'] = [dict(order_id='old-tp', ft_order_side='sell', order_type='limit',
                is_open=True, status='open', safe_price=2, amount=40, filled=0),
                dict(order_id='native-stop', ft_order_side='stoploss', order_type='stop_loss_limit',
                is_open=True, status='open', safe_price=.84, amount=40, filled=0)]
            self.cancels = self.posts = 0
            self.cancel_hook = self.post_hook = None

        async def get(self, *args, **kwargs):
            return copy.deepcopy(self.t)

        async def cancel(self, *args, **kwargs):
            self.cancels += 1
            self.t['orders'][0].update(is_open=False, status='canceled')
            if self.cancel_hook:
                self.cancel_hook(self.t)
            return {'status': 200}

        async def post(self, cfg, trade_id, amount, price, **kwargs):
            self.posts += 1
            if self.post_hook:
                self.post_hook(self.t)
            self.t['orders'].append(dict(order_id='new-'+str(self.posts), ft_order_side='sell',
                order_type='limit', is_open=True, status='open', safe_price=price, amount=amount, filled=0))
            return {'status': 200, 'body': '{}'}

    ex = Executor()
    monkeypatch.setattr(receiver, 'ft_get_trade', ex.get)
    monkeypatch.setattr(receiver, 'ft_force_exit_limit', ex.post)
    worker = Migration(cfg, conn, ex.get, ex.cancel, receiver._adopt_or_post_next_tp)
    yield worker, ex, conn
    conn.close()


def run(coro):
    return asyncio.run(coro)


def test_preview_has_no_exchange_writes_and_apply_is_idempotent(harness):
    w, ex, db = harness
    p = run(w.preview(42))
    assert p['targets'] == [dict(source_target=1, price=1.1, amount=20), dict(source_target=2, price=1.2, amount=20)]
    assert ex.posts == ex.cancels == 0
    stop = copy.deepcopy(ex.t['orders'][1])
    result = run(w.apply(p['request_id']))
    assert result['state'] == 'active'
    assert ex.cancels == ex.posts == 1
    assert ex.t['orders'][1] == stop
    assert run(w.apply(p['request_id'])) == result
    assert ex.cancels == ex.posts == 1
    archived = json.loads(db.execute('SELECT old_ledger FROM tp_migrations').fetchone()[0])
    assert archived[0]['ft_order_id'] == 'old-tp'
    assert json.loads(db.execute('SELECT tp_policy FROM positions').fetchone()[0])['migration_id'] == p['request_id']


def test_migrated_split_cascades_only_after_first_fill(harness):
    w, ex, db = harness
    run(w.apply(run(w.preview(42))['request_id']))
    ex.t['orders'][-1].update(is_open=False, status='closed', filled=20)
    ex.t['amount'] = 20
    ex.t['current_rate'] = 1.11
    summary = run(receiver._reconcile_target_orders_inner(w.cfg, db))
    assert summary['cascaded'] == 1
    assert ex.posts == 2
    assert ex.t['orders'][-1]['safe_price'] == 1.2
    assert ex.t['orders'][-1]['amount'] == 20
    assert [r[0] for r in db.execute('SELECT state FROM target_orders ORDER BY idx')] == ['filled','active']


@pytest.mark.parametrize('mutation', ['quantity','stop','order','price'])
def test_stale_preview_never_cancels(harness, mutation):
    w, ex, db = harness
    p = run(w.preview(42))
    if mutation == 'quantity': ex.t['amount'] = 39
    if mutation == 'stop': ex.t['stop_loss_abs'] = .85
    if mutation == 'order': ex.t['orders'][0]['order_id'] = 'unknown-exit'
    if mutation == 'price': ex.t['current_rate'] = 1.15
    with pytest.raises(ValueError): run(w.apply(p['request_id']))
    assert ex.cancels == ex.posts == 0


@pytest.mark.parametrize('mutation', ['fill','stop','cross','still-open','closed'])
def test_changes_during_cancel_hold_without_replacement(harness, mutation):
    w, ex, db = harness
    def hook(t):
        if mutation == 'fill':
            t['amount'] = 39
            t['orders'][0]['filled'] = 1
        if mutation == 'stop': t['stop_loss_abs'] = .85
        if mutation == 'cross': t['current_rate'] = 1.15
        if mutation == 'missing-cancel': t['orders'].pop(0)
        if mutation == 'still-open': t['orders'][0].update(is_open=True, status='open')
        if mutation == 'closed': t['is_open'] = False
    ex.cancel_hook = hook
    p = run(w.preview(42))
    assert run(w.apply(p['request_id']))['state'] == 'needs_review'
    assert ex.cancels == 1 and ex.posts == 0
    assert db.execute('SELECT state FROM target_orders').fetchone()[0] == 'blocked'
    run(receiver._reconcile_target_orders_inner(w.cfg, db))
    run(w.apply(p['request_id']))
    assert ex.cancels == 1 and ex.posts == 0


def test_cancel_timeout_not_retried(harness):
    w, ex, db = harness
    w.cancel = AsyncMock(side_effect=TimeoutError())
    p = run(w.preview(42))
    assert run(w.apply(p['request_id']))['state'] == 'needs_review'
    run(w.apply(p['request_id']))
    assert w.cancel.await_count == 1 and ex.posts == 0


def test_submit_timeout_not_retried(harness, monkeypatch):
    w, ex, db = harness
    post = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(receiver, 'ft_force_exit_limit', post)
    p = run(w.preview(42))
    assert run(w.apply(p['request_id']))['state'] == 'needs_review'
    assert db.execute('SELECT state FROM target_orders ORDER BY idx').fetchone()[0] == 'unknown'
    run(w.apply(p['request_id']))
    run(receiver._reconcile_target_orders_inner(w.cfg, db))
    assert post.await_count == 1


def test_crash_after_hold_never_resubmits(harness):
    w, ex, db = harness
    class Crash(BaseException): pass
    w.cancel = AsyncMock(side_effect=Crash())
    p = run(w.preview(42))
    with pytest.raises(Crash): run(w.apply(p['request_id']))
    assert run(w.apply(p['request_id']))['state'] == 'cancelling'
    run(receiver._reconcile_target_orders_inner(w.cfg, db))
    assert w.cancel.await_count == 1 and ex.posts == 0


def test_crash_after_plan_commit_rechecks_crossed_price_on_restart(harness):
    w, ex, db = harness
    class Crash(BaseException): pass
    w.adopt = AsyncMock(side_effect=Crash())
    p = run(w.preview(42))
    with pytest.raises(Crash): run(w.apply(p['request_id']))
    ex.t['current_rate'] = 1.15
    run(receiver._reconcile_target_orders_inner(w.cfg, db))
    assert ex.posts == 0
    assert db.execute('SELECT state FROM target_orders ORDER BY idx').fetchone()[0] == 'blocked'


def test_small_inventory_full_exit_at_first_target(harness):
    w, ex, db = harness
    ex.t['amount'] = ex.t['orders'][0]['amount'] = 15
    db.execute('UPDATE target_orders SET amount=15')
    p = run(w.preview(42))
    assert p['targets'] == [dict(source_target=1,price=1.1,amount=15)]
    assert run(w.apply(p['request_id']))['state'] == 'active'


@pytest.mark.parametrize('mutation', ['entry','partial','dust','missing-source','unknown','expired'])
def test_invalid_inputs_fail_before_order_writes(harness, mutation):
    w, ex, db = harness
    p = run(w.preview(42))
    if mutation == 'entry': ex.t['orders'][0]['ft_order_side'] = 'buy'
    if mutation == 'partial': ex.t['orders'][0]['filled'] = 1
    if mutation == 'dust': ex.t['amount'] = 40.5
    if mutation == 'missing-source': db.execute('DELETE FROM events')
    if mutation == 'unknown': db.execute("UPDATE target_orders SET state='unknown'")
    if mutation == 'expired': db.execute('UPDATE tp_migrations SET created_at=0')
    with pytest.raises(ValueError): run(w.apply(p['request_id']))
    assert ex.cancels == ex.posts == 0


def test_operator_route_requires_loopback_and_password(harness):
    w, ex, db = harness
    app = FastAPI()
    app.state.cfg = w.cfg
    app.state.conn = db
    app.state.ft_session = None
    app.state.phase2_lock = asyncio.Lock()
    install_routes(app, ex.get, ex.cancel, receiver._adopt_or_post_next_tp)
    # Default testclient peer is not loopback. Source bearer alone must not
    # permit a source-event client to operate migration endpoints.
    client = TestClient(app)
    r = client.post('/operator/tp-migrations/preview', json={'trade_id':42},
                    headers={'X-Operator-Password':w.cfg.ft_pass})
    assert r.status_code == 403
    assert ex.posts == ex.cancels == 0


def test_native_stop_disappears_after_cancel_no_replacement(harness):
    w, ex, db = harness
    ex.cancel_hook = lambda t: t['orders'].pop(1)
    assert run(w.apply(run(w.preview(42))['request_id']))['state'] == 'needs_review'
    assert ex.posts == 0


def test_new_preview_can_recover_cancelled_hold_with_fresh_approval(harness):
    w, ex, db = harness
    ex.cancel_hook = lambda t: t.update(current_rate=1.15)
    old = run(w.preview(42))
    assert run(w.apply(old['request_id']))['state'] == 'needs_review'
    ex.cancel_hook = None
    new = run(w.preview(42))
    assert new['targets'][0]['source_target'] == 2
    assert run(w.apply(new['request_id']))['state'] == 'active'
    assert ex.cancels == 1 and ex.posts == 1


def test_short_migration_preserves_original_source_indices(harness):
    w, ex, db = harness
    ex.t.update(is_short=True, current_rate=.95, stop_loss_abs=1.16)
    ex.t['orders'][0].update(ft_order_side='buy', safe_price=.5)
    db.execute("UPDATE positions SET direction='short'")
    db.execute('UPDATE target_orders SET price=.5')
    db.execute('UPDATE events SET payload=?', (json.dumps({'signal_targets':[.98,.9,.8,.5]}),))
    p = run(w.preview(42))
    assert [t['source_target'] for t in p['targets']] == [2,3]
    assert [t['amount'] for t in p['targets']] == [20,20]


def test_authenticated_routes_serialize_duplicate_apply(harness):
    import httpx
    from fastapi import Depends
    w, ex, db = harness
    app = FastAPI(dependencies=[Depends(receiver._require_ingress_token)])
    app.state.cfg, app.state.conn, app.state.ft_session = w.cfg, db, None
    app.state.phase2_lock = asyncio.Lock()
    install_routes(app, ex.get, ex.cancel, receiver._adopt_or_post_next_tp)
    async def exercise():
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1',1234))
        async with httpx.AsyncClient(transport=transport, base_url='http://local') as client:
            path='/operator/tp-migrations/preview'
            assert (await client.post(path,json={'trade_id':42})).status_code == 401
            headers={'Authorization':'Bearer '+w.cfg.ingress_token}
            assert (await client.post(path,json={'trade_id':42},headers=headers)).status_code == 403
            headers['X-Operator-Password']=w.cfg.ft_pass
            p=await client.post(path,json={'trade_id':42},headers=headers)
            assert p.status_code == 200
            path='/operator/tp-migrations/'+p.json()['request_id']+'/apply'
            results=await asyncio.gather(client.post(path,headers=headers),client.post(path,headers=headers))
            assert all(r.status_code == 200 and r.json()['state']=='active' for r in results)
    run(exercise())
    assert ex.posts == ex.cancels == 1


def test_cancelled_zero_fill_order_omitted_by_freqtrade_serializer(harness):
    w, ex, db = harness
    ex.cancel_hook = lambda t: t['orders'].pop(0)
    assert run(w.apply(run(w.preview(42))['request_id']))['state'] == 'active'
    assert ex.posts == ex.cancels == 1


def test_hidden_fill_accounting_change_blocks_even_if_quantity_is_stale(harness):
    w, ex, db = harness
    ex.t.update(nr_of_successful_exits=0,realized_profit=0)
    def hook(t):
        t['orders'].pop(0)
        t.update(nr_of_successful_exits=1,realized_profit=.1)
    ex.cancel_hook=hook
    assert run(w.apply(run(w.preview(42))['request_id']))['state'] == 'needs_review'
    assert ex.posts == 0


@pytest.mark.parametrize('answer,expected_applies', [('APPLY',1),('',0),('yes',0)])
def test_interactive_review_requires_exact_operator_confirmation(harness,monkeypatch,answer,expected_applies):
    from app import tp_migrate
    calls=[]
    def call(cfg,path,body=None):
        calls.append(path)
        if path=='/positions': return {'positions':[{'state':'open','ft_trade_id':42,'tp_policy':None}]}
        if path.endswith('/preview'): return {'state':'preview','request_id':'synthetic','targets':[]}
        return {'state':'active'}
    monkeypatch.setattr(tp_migrate,'call',call)
    monkeypatch.setattr('builtins.input',lambda _:answer)
    monkeypatch.setattr('sys.argv',['tp_migrate','review'])
    tp_migrate.main()
    assert sum(p.endswith('/apply') for p in calls)==expected_applies
