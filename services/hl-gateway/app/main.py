"""One bounded REST budget for the fleet's Hyperliquid clients.

Fixed upstream; no credentials, payloads or wallet addresses in telemetry.
Writes are forwarded exactly once and never cached/retried by this service.
"""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
import json
import math
import os
import time

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

UPSTREAM = 'https://api.hyperliquid.xyz'
CLIENTS = {'killers', 'insiders', 'short', 'accounting'}
LOW_COST = {'l2Book', 'allMids', 'clearinghouseState', 'orderStatus',
            'spotClearinghouseState', 'exchangeStatus'}
VARIABLE = {'recentTrades', 'historicalOrders', 'userFills', 'userFillsByTime',
            'fundingHistory', 'userFunding', 'nonUserFundingUpdates', 'twapHistory',
            'userTwapSliceFills', 'userTwapSliceFillsByTime', 'delegatorHistory',
            'delegatorRewards', 'validatorStats'}
# Only public market data is cached. Never conceal a new order/fill/account update.
CACHE_TTL = {'allMids': 1, 'l2Book': .5, 'meta': 300, 'spotMeta': 300,
             'metaAndAssetCtxs': 2, 'spotMetaAndAssetCtxs': 2, 'candleSnapshot': 2}


def cost(path, body):
    if path == 'exchange':
        action = body.get('action') or {}
        n = max([len(v) for v in action.values() if isinstance(v, list)] or [1])
        return 1 + n // 40
    kind = body.get('type')
    base = 2 if kind in LOW_COST else 60 if kind == 'userRole' else 20
    # Reserve the documented maximum response weight before sending. Refund
    # unused weight afterwards. This also bounds a startup history burst.
    return base + (100 if kind in VARIABLE else 84 if kind == 'candleSnapshot' else 0)


def actual_cost(path, body, result):
    reserved = cost(path, body)
    if path == 'exchange':
        return reserved
    kind = body.get('type')
    if isinstance(result, list) and (kind in VARIABLE or kind == 'candleSnapshot'):
        return 20 + math.ceil(len(result) / (60 if kind == 'candleSnapshot' else 20))
    return reserved


def priority(client, path, body):
    if path == 'exchange':
        return 0
    if client in {'killers', 'accounting'} and body.get('type') in LOW_COST | VARIABLE | {'openOrders', 'frontendOpenOrders'}:
        return 1
    return 2


class Budget:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.used = deque()
        self.waiting = [0, 0, 0]
        self.cooldown = 0.0

    def total(self):
        now = self.clock()
        while self.used and self.used[0][0] <= now - 60:
            self.used.popleft()
        return sum(row[1] for row in self.used)

    def reserve(self, weight, tier):
        # 250 weight reserved for managing live exposure; another 50 for
        # exchange actions. 300/min left for non-fleet users on the VPS IP.
        limit = (900, 850, 600)[tier]
        if (self.clock() < self.cooldown or any(self.waiting[:tier])
                or self.total() + weight > limit):
            return None
        row = [self.clock(), weight]
        self.used.append(row)
        return row

    async def acquire(self, weight, tier, timeout=12):
        deadline = self.clock() + timeout
        self.waiting[tier] += 1
        try:
            while self.clock() < deadline:
                row = self.reserve(weight, tier)
                if row is not None:
                    return row
                await asyncio.sleep(.05)
            return None
        finally:
            self.waiting[tier] -= 1


class Gateway:
    def __init__(self, session):
        self.session = session
        self.budget = Budget()
        self.cache = {}
        self.events = deque(maxlen=20000)

    def event(self, client, kind, result, elapsed=0):
        self.events.append((time.time(), client, kind, result, elapsed))

    def health(self):
        now = time.time()
        recent = [r for r in self.events if r[0] > now - 300]
        faults = [r for r in recent if r[3] in {'rate_limited', 'queue_timeout', 'upstream_error', 'transport_error'}]
        return {'ok': True, 'observed_at': now, 'status': 'warning' if faults else 'ok',
                'window_seconds': 300, 'faults': len(faults),
                'clients': {c: {k: sum(r[1] == c and r[3] == k for r in recent)
                               for k in ['ok', 'cached', 'rate_limited', 'queue_timeout', 'upstream_error', 'transport_error']}
                            for c in sorted(CLIENTS)},
                'max_latency_seconds': round(max([r[4] for r in recent] or [0]), 3),
                'weight_last_minute': self.budget.total(),
                'queued': sum(self.budget.waiting)}

    async def forward(self, client, path, body):
        started = time.monotonic()
        kind = body.get('type', 'exchange') if path == 'info' else 'exchange'
        ttl = CACHE_TTL.get(kind, 0) if path == 'info' else 0
        key = json.dumps(body, sort_keys=True, separators=(',', ':')) if ttl else None
        if key and key in self.cache and self.cache[key][0] > started:
            self.event(client, kind, 'cached')
            return self.cache[key][1]
        reservation = await self.budget.acquire(cost(path, body), priority(client, path, body))
        if reservation is None:
            self.event(client, kind, 'queue_timeout', time.monotonic() - started)
            return 429, b'{"error":"fleet request budget busy; request not forwarded"}'
        try:
            async with self.session.post(UPSTREAM + '/' + path, json=body) as response:
                data = await response.read()
                status = response.status
            try:
                decoded = json.loads(data)
                reservation[1] = actual_cost(path, body, decoded)
            except (ValueError, TypeError):
                pass
            result = (status, data)
            if status == 429:
                self.budget.cooldown = time.monotonic() + 10
            self.event(client, kind, 'rate_limited' if status == 429 else 'upstream_error' if status >= 400 else 'ok', time.monotonic() - started)
            if ttl and status == 200:
                if len(self.cache) >= 1024:
                    self.cache = {k: v for k, v in self.cache.items() if v[0] > time.monotonic()}
                    if len(self.cache) >= 1024:
                        self.cache.clear()
                self.cache[key] = (time.monotonic() + ttl, result)
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.event(client, kind, 'transport_error', time.monotonic() - started)
            # Bare 504 deliberately does NOT assert that a write was rejected.
            return 504, b'{"detail":"upstream outcome unavailable"}'


@asynccontextmanager
async def lifespan(app):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        app.state.gateway = Gateway(session)
        yield


app = FastAPI(lifespan=lifespan)


@app.get('/healthz')
async def health():
    return app.state.gateway.health()


@app.post('/{client}/{path}')
async def proxy(client: str, path: str, request: Request):
    if client not in CLIENTS or path not in {'info', 'exchange'}:
        raise HTTPException(404)
    if int(request.headers.get('content-length', '0')) > 1024 * 1024:
        raise HTTPException(413)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400)
    # Observation clients cannot submit signed actions via this gateway.
    if path == 'exchange' and client != 'killers':
        raise HTTPException(403, 'observation client cannot submit exchange actions')
    status, data = await app.state.gateway.forward(client, path, body)
    return Response(data, status_code=status, media_type='application/json')


@app.get('/account/killers')
async def account():
    wallet = os.environ.get('KILLERS_WALLET_ADDRESS')
    if not wallet:
        raise HTTPException(503, 'account not configured')
    status, data = await app.state.gateway.forward('accounting', 'info',
        {'type': 'clearinghouseState', 'user': wallet})
    if status != 200:
        raise HTTPException(503, 'account observation unavailable')
    result = json.loads(data)
    margin = result['marginSummary']
    return {'observed_at': time.time(), 'equity': float(margin['accountValue']),
            'free': float(result['withdrawable']), 'margin': float(margin['totalMarginUsed']),
            'notional': float(margin['totalNtlPos'])}
