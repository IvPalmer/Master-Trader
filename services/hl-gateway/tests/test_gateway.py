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
        for client in ('killers', 'short', 'accounting'):
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
    for kind in ['meta', 'spotMeta', 'perpDexs', 'metaAndAssetCtxs', 'spotMetaAndAssetCtxs', 'l2Book']:
        assert g.priority('killers', 'info', {'type': kind}) == 1
    assert g.priority('killers', 'info', {'type': 'candleSnapshot'}) == 2


def test_live_usage_does_not_double_charge_background_allowance():
    budget = g.Budget(lambda: 100)
    assert budget.reserve(200, 1)
    assert budget.reserve(600, 2)
    assert budget.reserve(1, 2) is None
    assert budget.reserve(50, 1)
    assert budget.reserve(50, 0)
    assert budget.total() == 900


def test_expired_market_data_is_evicted_on_next_request():
    async def check():
        gateway = g.Gateway(Session())
        gateway.cache['expired'] = (0, (200, b'old'))
        await gateway.forward('killers', 'info', {'type':'allMids'})
        assert 'expired' not in gateway.cache
    asyncio.run(check())


def test_retired_insiders_client_has_no_route():
    """#216: the Insiders bot and receiver are retired; /insiders/* is a 404 and
    the client no longer appears in health telemetry."""
    async def check():
        for path in ('info', 'exchange'):
            try:
                await g.proxy('insiders', path, None)
            except g.HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError('insiders route still served')
    asyncio.run(check())
    assert 'insiders' not in g.Gateway(Session()).health()['clients']


class _Request:
    def __init__(self, body):
        self.headers = {'content-length': '2'}
        self._body = body

    async def json(self):
        return self._body


def test_upbit_pilot_client_routes_and_may_submit_exchange_actions():
    """#252: ft-upbit-fade-hl routes through /upbit with its own account and API
    wallet; it may forward signed actions once live, like killers. `short`
    stays observation only."""
    assert 'upbit' in g.CLIENTS and g.EXCHANGE_CLIENTS == {'killers', 'upbit'}
    assert g.priority('upbit', 'info', {'type': 'l2Book'}) == 2
    assert g.priority('upbit', 'info', {'type': 'candleSnapshot'}) == 2

    async def check():
        session = Session(b'{"status":"ok"}')
        g.app.state.gateway = g.Gateway(session)
        resp = await g.proxy('upbit', 'exchange', _Request({'action': {'type': 'order'}}))
        assert resp.status_code == 200 and session.calls == 1
        try:
            await g.proxy('short', 'exchange', _Request({'action': {'type': 'order'}}))
        except g.HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError('observation client forwarded an exchange action')
        assert session.calls == 1
        assert 'upbit' in g.Gateway(Session()).health()['clients']
    asyncio.run(check())


# --- #252 review: the pilot can never take Killers' protected capacity -------------------

KILLERS_PROTECTED = [('info', {'type': 'orderStatus'}), ('info', {'type': 'clearinghouseState'}),
                     ('info', {'type': 'l2Book'}), ('exchange', {'action': {'type': 'order'}})]


def test_upbit_reads_are_background_and_only_actions_and_order_status_use_its_slice():
    assert g.priority('upbit', 'exchange', {}) == 0
    assert g.priority('upbit', 'info', {'type': 'orderStatus'}) == 1
    for kind in ('l2Book', 'clearinghouseState', 'allMids', 'metaAndAssetCtxs', 'meta',
                 'frontendOpenOrders', 'openOrders', 'userFills', 'candleSnapshot'):
        assert g.priority('upbit', 'info', {'type': kind}) == 2, kind
    assert g.lane('upbit', 0) == g.lane('upbit', 1) == 'upbit' and g.lane('upbit', 2) is None
    assert g.lane('killers', 0) is None and g.SLICES == {'upbit': 40}


def test_maximum_upbit_load_never_rejects_killers_order_status_or_actions():
    """Codex's case: 600 background units plus 250 upbit units used to leave Killers'
    order-status read with nothing (the fleet's 850 tier-1 limit)."""
    budget = g.Budget(lambda: 100)
    assert budget.reserve(600, 2, 'short')
    upbit = [(path, {'type': kind}) for kind in ('l2Book', 'clearinghouseState', 'orderStatus',
                                                 'metaAndAssetCtxs') for path in ('info',)]
    upbit.append(('exchange', {'action': {'type': 'order'}}))
    for _ in range(250):
        for path, body in upbit:
            budget.reserve(g.cost(path, body), g.priority('upbit', path, body), 'upbit')
    assert budget.lane_total('upbit') <= 40
    for path, body in KILLERS_PROTECTED:
        assert budget.reserve(g.cost(path, body), g.priority('killers', path, body), 'killers'), body
    # Killers still has its whole 250 tier-1 and 50 action allowance.
    assert budget.reserve(250 - 2 - 2 - 2 - 1, 1, 'killers')
    assert budget.reserve(50, 0, 'killers')


def test_an_upbit_waiter_on_its_spent_slice_never_holds_killers_back():
    async def check():
        budget = g.Budget()
        assert budget.reserve(40, 0, 'upbit')
        waiter = asyncio.ensure_future(budget.acquire(1, 0, timeout=1, client='upbit'))
        await asyncio.sleep(.1)
        assert budget.waiting == [0, 0, 0]
        assert await budget.acquire(2, 1, timeout=.2, client='killers')
        assert await budget.acquire(20, 2, timeout=.2, client='killers')
        assert await waiter is None
    asyncio.run(check())


def test_killers_budget_is_unchanged_when_upbit_is_idle():
    """The pre-#252 allowance sequence, client given or not."""
    for client in (None, 'killers', 'short', 'accounting'):
        now = [100.0]
        budget = g.Budget(lambda: now[0])
        assert budget.reserve(600, 2, client)
        assert budget.reserve(1, 2, client) is None
        assert budget.reserve(250, 1, client)
        assert budget.reserve(1, 1, client) is None
        assert budget.reserve(50, 0, client)
        assert budget.reserve(1, 0, client) is None
        now[0] += 61
        assert budget.reserve(600, 2, client)
    for kind in ('orderStatus', 'l2Book', 'metaAndAssetCtxs', 'candleSnapshot'):
        assert g.priority('killers', 'info', {'type': kind}) == (2 if kind == 'candleSnapshot' else 1)
    assert g.priority('killers', 'exchange', {}) == 0


# --- #252 review round 3: no budget persistence, no synthetic start ---------------------

def test_the_gateway_keeps_no_budget_state_and_starts_empty(tmp_path, monkeypatch):
    """Round 3: the persisted history and the synthetic cold start are both gone. A started
    gateway has an empty window and writes nothing; restarts are made safe by the
    deploy procedure (Killers flat, trailing-minute usage under 300), not by state."""
    import inspect
    import yaml
    assert list(inspect.signature(g.Budget).parameters) == ['clock']
    assert not hasattr(g.Budget, 'persist') and not hasattr(g.Budget, 'restore')
    monkeypatch.setenv('BUDGET_STATE_PATH', str(tmp_path / 'budget.json'))
    monkeypatch.chdir(tmp_path)

    async def check():
        async with g.lifespan(g.app):
            gw = g.app.state.gateway
            assert gw.budget.total() == 0 and gw.budget.reserve(120, 1, 'killers')
            health = gw.health()
            assert health['weight_last_minute'] == 120 and 'budget_history' not in health
    asyncio.run(check())
    assert list(tmp_path.iterdir()) == []
    root = Path(__file__).parents[3]
    svc = yaml.safe_load((root / 'ft_userdata/docker-compose.prod.yml').read_text())
    assert 'volumes' not in svc['services']['hl-gateway']
    assert 'BUDGET_STATE_PATH' not in svc['services']['hl-gateway']['environment']
    assert 'hl_gateway_state' not in svc['volumes']
    assert '/state' not in (Path(__file__).parents[1] / 'Dockerfile').read_text()


def test_the_deployed_short_client_serves_a_dry_run_bot():
    """Round 3: in dry-run the pilot uses `short`, unchanged from the deployed gateway:
    every info read is forwarded at the background tier and exchange actions are refused
    (a dry-run Freqtrade never posts one: create_order, cancel_order, set_leverage and
    set_margin_mode all return early in dry-run)."""
    for kind in ('meta', 'metaAndAssetCtxs', 'spotMeta', 'perpDexs', 'allMids', 'l2Book',
                 'candleSnapshot', 'fundingHistory', 'orderStatus', 'clearinghouseState'):
        assert g.priority('short', 'info', {'type': kind}) == 2, kind
        assert g.lane('short', 2) is None

    async def check():
        session = Session(b'[]')
        g.app.state.gateway = g.Gateway(session)
        for kind in ('meta', 'metaAndAssetCtxs', 'candleSnapshot', 'fundingHistory', 'l2Book'):
            resp = await g.proxy('short', 'info', _Request({'type': kind}))
            assert resp.status_code == 200, kind
        try:
            await g.proxy('short', 'exchange', _Request({'action': {'type': 'order'}}))
        except g.HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError('short forwarded an exchange action')
    asyncio.run(check())
