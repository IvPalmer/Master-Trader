"""Human-confirmed full-position exits. No automatic retries or background exits."""
import base64
import hmac
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class ClosePosition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    pair: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, allow_inf_nan=False)
    open_timestamp: float = Field(gt=0, allow_inf_nan=False)
    is_short: bool


def connect():
    path = Path(os.environ.get('DASHBOARD_ACTION_DB', '/var/lib/dashboard-actions/actions.sqlite'))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=5)
    path.chmod(0o600)
    db.execute('CREATE TABLE IF NOT EXISTS actions (request_id TEXT PRIMARY KEY, bot TEXT, trade INTEGER, payload TEXT, opened REAL, state TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')
    db.commit()
    return db


def install(app, bots, auth):
    @app.post('/api/trades/{bot_key}/{trade_id}/close')
    async def close_position(bot_key: str, trade_id: int, payload: ClosePosition, request: Request):
        bot = next((b for b in bots if b['key'] == bot_key), None)
        if bot is None or trade_id <= 0:
            raise HTTPException(404, 'Unknown bot or position')
        origin = urlsplit(request.headers.get('origin', ''))
        if (origin.scheme != 'https' or origin.netloc != request.headers.get('host')
                or request.headers.get('x-trade-action') != 'close'
                or request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'):
            raise HTTPException(403, 'Use the dashboard on its HTTPS address')
        expected_user, expected_password = auth(bot['url'])
        if not expected_password or expected_password == 'mastertrader':
            raise HTTPException(503, 'Trading controls require configured bot credentials')
        try:
            kind, encoded = request.headers.get('authorization', '').split(' ', 1)
            user, password = base64.b64decode(encoded, validate=True).decode().split(':', 1)
            authenticated = (kind.lower() == 'basic'
                             and hmac.compare_digest(user.encode(), expected_user.encode())
                             and hmac.compare_digest(password.encode(), expected_password.encode()))
        except (ValueError, UnicodeError):
            authenticated = False
        if not authenticated:
            raise HTTPException(401, 'Bot API username or password is incorrect')
        body = payload.model_dump_json()
        key = str(payload.request_id)
        with connect() as db:
            previous = db.execute('SELECT bot,trade,payload,state FROM actions WHERE request_id=?', (key,)).fetchone()
        if previous:
            if previous[:3] != (bot_key, trade_id, body):
                raise HTTPException(409, 'Request identity was already used for another action')
            return {'state': previous[3], 'replayed': True}
        async with httpx.AsyncClient(timeout=45, auth=(expected_user, expected_password)) as client:
            try:
                response = await client.get(bot['url'].rstrip('/') + '/api/v1/status')
                response.raise_for_status()
                trades = response.json()
                if not isinstance(trades, list):
                    raise ValueError('Invalid snapshot')
            except (httpx.HTTPError, ValueError):
                raise HTTPException(503, 'Cannot refresh position; no exit submitted') from None
            trade = next((t for t in trades if t.get('trade_id') == trade_id), None)
            if not trade:
                return {'state': 'already_closed'}
            if (trade.get('pair') != payload.pair or bool(trade.get('is_short')) != payload.is_short
                    or trade.get('amount') != payload.amount
                    or trade.get('open_timestamp') != payload.open_timestamp):
                raise HTTPException(409, 'Position changed. Refresh and review it again; no exit submitted')
            entry_side = 'sell' if trade.get('is_short') else 'buy'
            if any(o.get('is_open') and o.get('ft_order_side') == entry_side for o in trade.get('orders', [])):
                raise HTTPException(409, 'An entry order is still open. Resolve it before closing this position')
            # Durable reservation before POST. A timeout or process death never permits a blind retry.
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT state FROM actions WHERE bot=? AND trade=? AND opened=? AND state IN (\'submitting\',\'accepted\',\'unknown\')', (bot_key, trade_id, payload.open_timestamp)).fetchone()
                if old:
                    raise HTTPException(409, 'An exit request already exists. Check current orders before another action')
                try:
                    db.execute('INSERT INTO actions(request_id,bot,trade,payload,opened,state) VALUES(?,?,?,?,?,?)', (key, bot_key, trade_id, body, payload.open_timestamp, 'submitting'))
                except sqlite3.IntegrityError:
                    raise HTTPException(409, 'Request already submitted') from None
            try:
                result = await client.post(bot['url'].rstrip('/') + '/api/v1/forceexit', json={'tradeid': str(trade_id), 'ordertype': 'market'})
                # Non-2xx may follow a side effect: treat as uncertain, not safely retryable.
                state = 'accepted' if result.is_success else 'unknown'
            except httpx.HTTPError:
                state = 'unknown'
            with connect() as db:
                db.execute('UPDATE actions SET state=? WHERE request_id=?', (state, key))
            return {'state': state, 'replayed': False}
