import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock
import aiohttp

spec = importlib.util.spec_from_file_location('gateway', Path(__file__).parents[1] / 'app/main.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def test_shared_budget_reserves_capacity_for_live_management_and_actions():
    now = [100.0]
    budget = g.Budget(lambda: now[0])
    assert budget.reserve(600, 2)
    assert budget.reserve(1, 2) is None
    assert budget.reserve(250, 1)
    assert budget.reserve(1, 1) is None
    assert budget.reserve(50, 0)
    assert budget.reserve(1, 0) is None
    now[0] += 61
    assert budget.reserve(600, 2)


def test_high_priority_waiters_win_and_cooldown_applies_to_every_client():
    budget = g.Budget(lambda: 100)
    budget.waiting[0] = 1
    assert budget.reserve(20, 2) is None
    assert budget.reserve(1, 0)
    budget.cooldown = 101
    assert budget.reserve(1, 0) is None


def test_response_weight_and_exchange_batch_weight_are_reserved():
    assert g.cost('info', {'type': 'orderStatus'}) == 2
    assert g.cost('info', {'type': 'userRole'}) == 60
    assert g.cost('info', {'type': 'userFills'}) == 120
    assert g.actual_cost('info', {'type': 'userFills'}, [{}] * 21) == 22
    assert g.cost('exchange', {'action': {'orders': [{}] * 79}}) == 2
    assert g.cost('info', {'type': 'candleSnapshot'}) == 104


class Session:
    def __init__(self, data=b'{}', status=200, error=None):
        self.calls = 0
        self.data = data
        self.status = status
        self.error = error
    def post(self, *args, **kwargs):
        self.calls += 1
        return self
    async def __aenter__(self):
        if self.error:
            raise self.error
        return self
    async def __aexit__(self, *args):
        pass
    async def read(self):
        return self.data


def test_timed_out_write_is_sent_once_and_reports_unknown_outcome():
    async def check():
        session = Session(error=asyncio.TimeoutError())
        gateway = g.Gateway(session)
        status, body = await gateway.forward('killers', 'exchange', {'action': {'type': 'order'}})
        assert status == 504
        assert b'error' not in body
        assert session.calls == 1
        assert gateway.health()['status'] == 'warning'
    asyncio.run(check())


def test_account_and_order_observations_are_never_cached():
    async def check():
        session = Session()
        gateway = g.Gateway(session)
        for kind in ('orderStatus', 'clearinghouseState', 'userFills', 'openOrders'):
            for _ in range(2):
                assert (await gateway.forward('killers', 'info', {'type': kind}))[0] == 200
        assert session.calls == 8
    asyncio.run(check())


def test_market_cache_is_shared_without_exposing_payloads():
    async def check():
        session = Session(b'{"BTC":"100"}')
        gateway = g.Gateway(session)
        for client in ('killers', 'insiders', 'short'):
            assert (await gateway.forward(client, 'info', {'type': 'allMids'}))[0] == 200
        assert session.calls == 1
        assert 'BTC' not in str(gateway.health())
    asyncio.run(check())


def test_queue_timeout_never_sends_request_and_is_visible():
    async def check():
        session = Session()
        gateway = g.Gateway(session)
        gateway.budget.acquire = AsyncMock(return_value=None)
        assert (await gateway.forward('killers', 'exchange', {}))[0] == 429
        assert session.calls == 0
        assert gateway.health()['clients']['killers']['queue_timeout'] == 1
    asyncio.run(check())


def test_candle_reservation_bounds_requested_window_and_keeps_fallback():
    body = {'type': 'candleSnapshot', 'req': {'interval': '5m', 'startTime': 0, 'endTime': 3000000}}
    assert g.cost('info', body) == 21
    body['req']['endTime'] = 5000 * 300000
    assert g.cost('info', body) == 104
    body['req']['interval'] = 'invalid'
    assert g.cost('info', body) == 104


def test_only_background_reads_wait_across_a_budget_window():
    async def check():
        gateway = g.Gateway(Session())
        gateway.budget.acquire = AsyncMock(return_value=None)
        await gateway.forward('killers', 'exchange', {})
        assert gateway.budget.acquire.call_args.kwargs['timeout'] == 12
        await gateway.forward('killers', 'info', {'type': 'orderStatus'})
        assert gateway.budget.acquire.call_args.kwargs['timeout'] == 12
        await gateway.forward('short', 'info', {'type': 'candleSnapshot'})
        assert gateway.budget.acquire.call_args.kwargs['timeout'] == 70
    asyncio.run(check())


def test_live_ticker_contexts_have_exit_priority():
    for kind in ['metaAndAssetCtxs', 'spotMetaAndAssetCtxs', 'l2Book']:
        assert g.priority('killers', 'info', {'type': kind}) == 1
    assert g.priority('killers', 'info', {'type': 'candleSnapshot'}) == 2
