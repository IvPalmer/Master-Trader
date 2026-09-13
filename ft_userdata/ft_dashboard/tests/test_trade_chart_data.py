import asyncio
import json
import subprocess
from pathlib import Path
import httpx
import app


def test_hyperliquid_candles_use_gateway_and_bound_window(monkeypatch):
    calls = []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            t = kwargs['json']['req']['endTime']
            return httpx.Response(200, request=httpx.Request('POST', url), json=[
                {'t': t, 'o': '1.2', 'c': '1.3', 'l': '1.1', 'h': '1.4', 'v': '10'}])
    monkeypatch.setattr(app.httpx, 'AsyncClient', Client)
    response = asyncio.run(app.api_trade_candles('killers-ft', 'GRAM/USDC:USDC', '4h', 10000, 1, 1789310000000))
    data = json.loads(response.body)
    assert data['source'] == 'Hyperliquid'
    assert data['candles'] == [[1789310000000, 1.2, 1.3, 1.1, 1.4, 10.0]]
    url, kwargs = calls[0]
    assert url == 'http://hl-gateway:8080/accounting/info'
    req = kwargs['json']['req']
    assert req['coin'] == 'GRAM'
    assert req['endTime'] - req['startTime'] <= 499 * 4 * 3600000


def test_trade_candles_reject_unknown_bot_and_invalid_pair():
    for key, pair, status in [('unknown', 'BTC/USDC:USDC', 404), ('killers-ft', 'BTC/USDT:USDT', 400)]:
        assert asyncio.run(app.api_trade_candles(key, pair)).status_code == status


def test_closed_line_reaches_mark_without_inventing_pnl_history():
    source = Path(app.__file__).parent / 'static/dashboard.js'
    script = source.read_text() + '''
const assert = require('node:assert/strict');
const epoch = 1787854748304, now = epoch + 100000;
const points = closedEquityThroughMark([[epoch, 98]], [[epoch, 98], [now, 103]]);
assert.deepEqual(points.map(([d,v])=>[Number(d),v]), [[epoch,98],[now,98]]);
const unchanged = closedEquityThroughMark([[epoch,98],[now,100]], [[epoch,98],[now,105]]);
assert.equal(unchanged.length,2);
assert.equal(unchanged[1][1],100);
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)


def test_killers_return_basis_is_verified_funding_not_available_margin():
    bot = app._bot_meta('killers-ft')
    basis = bot['performance_starting_capital']
    assert basis == 98.0
    pnl, _, _ = app._epoch_stats([], [{'profit_abs': 5.22}], basis)
    assert pnl['all_pct'] == 5.33
