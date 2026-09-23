import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('trade_controls', Path(__file__).parents[1] / 'trade_controls.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_ACTION_DB', str(tmp_path / 'actions.sqlite'))
    app = FastAPI()
    m.install(app, [{'key':'test','url':'http://executor'}], lambda _: ('operator','synthetic-secret'))
    client = TestClient(app, base_url='https://dashboard.test')
    headers = {'Origin':'https://dashboard.test', 'X-Trade-Action':'close', 'Authorization':'Basic '+base64.b64encode(b'operator:synthetic-secret').decode()}
    body = {'request_id':str(uuid4()),'pair':'TEST/USDC:USDC','amount':20.,'open_timestamp':12345678.,'is_short':False}
    trade = {'trade_id':4, **{k:v for k,v in body.items() if k!='request_id'}}
    upstream = AsyncMock()
    upstream.__aenter__.return_value = upstream
    upstream.get.return_value = httpx.Response(200, json=[trade], request=httpx.Request('GET','http://executor'))
    upstream.post.return_value = httpx.Response(200, json={'result':'created'}, request=httpx.Request('POST','http://executor'))
    monkeypatch.setattr(m.httpx, 'AsyncClient', lambda **_:upstream)
    return client, headers, body, trade, upstream


def test_confirmed_close_and_replay_submit_once(setup):
    client,h,b,t,up = setup
    r=client.post('/api/trades/test/4/close',headers=h,json=b)
    assert r.json()['state']=='accepted'
    assert client.post('/api/trades/test/4/close',headers=h,json=b).json()['replayed']
    up.post.assert_awaited_once_with('http://executor/api/v1/forceexit',json={'tradeid':'4','ordertype':'market'})
    b['request_id']=str(uuid4())
    assert client.post('/api/trades/test/4/close',headers=h,json=b).status_code==409
    assert up.post.await_count==1


@pytest.mark.parametrize('header,value,status',[('Origin','https://hostile.test',403),('X-Trade-Action','',403),('Authorization','Basic wrong',401),('Sec-Fetch-Site','cross-site',403)])
def test_auth_and_origin_fail_before_upstream(setup,header,value,status):
    client,h,b,t,up=setup; h[header]=value
    assert client.post('/api/trades/test/4/close',headers=h,json=b).status_code==status
    up.get.assert_not_awaited(); up.post.assert_not_awaited()


@pytest.mark.parametrize('field,value',[('amount',19),('pair','OTHER/USDC:USDC'),('open_timestamp',23456789),('is_short',True)])
def test_stale_confirmation_cannot_close_changed_position(setup,field,value):
    client,h,b,t,up=setup; b[field]=value
    assert client.post('/api/trades/test/4/close',headers=h,json=b).status_code==409
    up.post.assert_not_awaited()


def test_unknown_submission_is_not_retried(setup):
    client,h,b,t,up=setup
    up.post.side_effect=httpx.ReadTimeout('ambiguous')
    assert client.post('/api/trades/test/4/close',headers=h,json=b).json()['state']=='unknown'
    assert client.post('/api/trades/test/4/close',headers=h,json=b).json()['state']=='unknown'
    assert up.post.await_count==1


def test_closed_position_does_not_submit(setup):
    client,h,b,t,up=setup
    up.get.return_value=httpx.Response(200,json=[],request=httpx.Request('GET','http://executor'))
    assert client.post('/api/trades/test/4/close',headers=h,json=b).json()['state']=='already_closed'
    up.post.assert_not_awaited()


def test_read_failure_does_not_submit(setup):
    client,h,b,t,up=setup; up.get.side_effect=httpx.ReadTimeout('offline')
    assert client.post('/api/trades/test/4/close',headers=h,json=b).status_code==503
    up.post.assert_not_awaited()


def test_open_entry_blocks_close(setup):
    client,h,b,t,up=setup
    t['orders']=[{'is_open':True,'ft_order_side':'buy'}]
    up.get.return_value=httpx.Response(200,json=[t],request=httpx.Request('GET','http://executor'))
    assert client.post('/api/trades/test/4/close',headers=h,json=b).status_code==409
    up.post.assert_not_awaited()


def test_upstream_error_does_not_enable_blind_retry(setup):
    client,h,b,t,up=setup
    up.post.return_value=httpx.Response(502,json={'error':'upstream'},request=httpx.Request('POST','http://executor'))
    assert client.post('/api/trades/test/4/close',headers=h,json=b).json()['state']=='unknown'
    b['request_id']=str(uuid4())
    assert client.post('/api/trades/test/4/close',headers=h,json=b).status_code==409
    assert up.post.await_count==1
