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
CACHE_TTL = {'allMids': 1, 'l2Book': .5, 'meta': 300, 'spotMeta': 300, 'perpDexs': 300,
             'metaAndAssetCtxs': 10, 'spotMetaAndAssetCtxs': 10, 'candleSnapshot': 2}


def cost(path, body):
    if path == 'exchange':
        action = body.get('action') or {}
        n = max([len(v) for v in action.values() if isinstance(v, list)] or [1])
        return 1 + n // 40
    kind = body.get('type')
    base = 2 if kind in LOW_COST else 60 if kind == 'userRole' else 20
    # Reserve the documented maximum response weight before sending. Refund
    # unused weight afterwards. This also bounds a startup history burst.
    candle_rows = 5000
    if kind == 'candleSnapshot':
        req = body.get('req') or {}
        interval = req.get('interval', '')
        try:
            interval_ms = int(interval[:-1]) * {'m': 60000, 'h': 3600000, 'd': 86400000}[interval[-1]]
            # Include both boundary candles. An absent/invalid window keeps
            # the conservative exchange maximum reservation.
            span = int(req['endTime']) - int(req['startTime'])
            if interval_ms > 0 and span >= 0:
                candle_rows = min(5000, span // interval_ms + 2)
        except (ValueError, TypeError, KeyError, IndexError):
            pass
    return base + (100 if kind in VARIABLE else math.ceil(candle_rows / 60) if kind == 'candleSnapshot' else 0)


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
    # CCXT fetch_ticker(s) uses asset contexts, not just allMids/l2Book.
    # Price reads used by live status and exits must not wait behind candles.
    if client in {'killers', 'accounting'} and body.get('type') in LOW_COST | VARIABLE | {'openOrders', 'frontendOpenOrders', 'meta', 'spotMeta', 'perpDexs', 'metaAndAssetCtxs', 'spotMetaAndAssetCtxs'}:
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
        total = self.total()
        # Background has its own 600-unit allowance. Charging live traffic
        # against that allowance as well double-reserved capacity and starved
        # candles while hundreds of units remained unused.
        background = sum(row[1] for row in self.used if row[2] == 2)
        limit = 900 if tier == 0 else 850
        if (self.clock() < self.cooldown or any(self.waiting[:tier])
                or total + weight > limit
                or (tier == 2 and background + weight > 600)):
            return None
        row = [self.clock(), weight, tier]
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
                'background_weight_last_minute': sum(r[1] for r in self.budget.used if r[2] == 2),
                'requests_by_type': {kind: sum(r[2] == kind for r in recent)
                                     for kind in sorted({r[2] for r in recent})},
                'queued': sum(self.budget.waiting)}

    async def forward(self, client, path, body):
        started = time.monotonic()
        kind = body.get('type', 'exchange') if path == 'info' else 'exchange'
        ttl = CACHE_TTL.get(kind, 0) if path == 'info' else 0
        self.cache = {k: v for k, v in self.cache.items() if v[0] > started}
        key = json.dumps(body, sort_keys=True, separators=(',', ':')) if ttl else None
        if key and key in self.cache and self.cache[key][0] > started:
            self.event(client, kind, 'cached')
            return self.cache[key][1]
        tier = priority(client, path, body)
        # Public startup history can wait across a budget window; exit/order
        # reads and actions retain the short deadline and reserved capacity.
        reservation = await self.budget.acquire(cost(path, body), tier, timeout=70 if tier == 2 else 12)
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
                # Bound resident response bytes as well as entry count.
                if len(data) <= 4 * 1024 * 1024:
                    while self.cache and (len(self.cache) >= 128 or
                            sum(len(v[1][1]) for v in self.cache.values()) + len(data) > 8 * 1024 * 1024):
                        self.cache.pop(next(iter(self.cache)))
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
