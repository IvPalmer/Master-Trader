"""Operator-approved replacement of legacy TP ladders, serialized by the receiver.

Never invoked automatically. Journal and blocked rows survive process failure;
no cancel or submit with an uncertain outcome is blindly retried.
"""
import hashlib
import json
import secrets
import time
import uuid
from decimal import Decimal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .tp_policy import snapshot_nearby, nearby_allocations

SCHEMA = """
CREATE TABLE IF NOT EXISTS tp_migrations (
 request_id TEXT PRIMARY KEY,
 pos_id INTEGER NOT NULL,
 created_at REAL NOT NULL,
 state TEXT NOT NULL,
 proposal TEXT NOT NULL,
 old_ledger TEXT,
 result TEXT
);
"""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def signature(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def normal_open_orders(trade):
    # Native stoploss orders are deliberately excluded from the cancel path.
    return [o for o in trade.get('orders', [])
            if o.get('is_open') and o.get('ft_order_side') != 'stoploss']


def native_stops(trade):
    return [{k: o.get(k) for k in ('order_type', 'safe_price', 'price', 'amount')}
            for o in trade.get('orders', [])
            if o.get('is_open') and o.get('ft_order_side') == 'stoploss']


def order_basis(order):
    return {k: order.get(k) for k in (
        'order_id', 'ft_order_side', 'order_type', 'is_open', 'status',
        'safe_price', 'price', 'amount', 'filled')}


def inventory(trade):
    return {k: trade.get(k) for k in (
        'trade_id', 'pair', 'is_open', 'is_short', 'open_timestamp',
        'amount', 'open_rate', 'nr_of_successful_entries', 'stop_loss_abs',
        'stop_loss_ratio', 'amount_precision', 'precision_mode',
        'price_precision', 'precision_mode_price', 'contract_size')}


class Migration:
    def __init__(self, cfg, conn, get_trade, cancel, adopt, session=None):
        self.cfg, self.conn = cfg, conn
        self.get_trade, self.cancel, self.adopt = get_trade, cancel, adopt
        self.session = session

    async def proposal(self, trade_id):
        positions = self.conn.execute(
            "SELECT * FROM positions WHERE ft_trade_id=? AND state='open'", (trade_id,)
        ).fetchall()
        if len(positions) != 1:
            raise ValueError('expected exactly one open receiver position')
        pos = dict(positions[0])
        if pos['tp_policy']:
            raise ValueError('position already has a frozen policy; not a legacy migration')
        rows = [dict(r) for r in self.conn.execute(
            'SELECT * FROM target_orders WHERE pos_id=? ORDER BY idx,target_id', (pos['pos_id'],))]
        if not rows or any(r['state'] in ('placing', 'unknown', 'retry', 'rejected') for r in rows):
            raise ValueError('missing or uncertain ladder; reconcile it before migration')
        trade = await self.get_trade(self.cfg, trade_id, session=self.session)
        if not trade or trade.get('is_open') is not True:
            raise ValueError('fresh open trade unavailable')
        if (trade.get('pair') != pos['pair'] or trade.get('trade_id') != trade_id
                or bool(trade.get('is_short')) != (pos['direction'] == 'short')
                or not trade.get('open_timestamp')):
            raise ValueError('trade identity does not match receiver')
        # A stop-price snapshot is mandatory. We never submit a stop cancellation
        # or update, but a concurrent stop change invalidates the proposal.
        if Decimal(str(trade.get('stop_loss_abs') or 0)) <= 0:
            raise ValueError('missing stop metadata')
        if len(native_stops(trade)) != 1:
            raise ValueError('expected one active native stop in executor snapshot')
        opened = normal_open_orders(trade)
        exit_side = 'buy' if trade.get('is_short') else 'sell'
        if len(opened) > 1 or any(o.get('ft_order_side') != exit_side
                                  or o.get('order_type') != 'limit' for o in opened):
            raise ValueError('entry or unexpected open order; no cancellation allowed')
        if opened:
            o = opened[0]
            matched = [r for r in rows if r['ft_order_id']
                       and str(r['ft_order_id']) == str(o.get('order_id'))]
            if len(matched) != 1:
                raise ValueError('resting exit is not owned by the current ladder')
            if Decimal(str(o.get('filled') or 0)) != 0:
                raise ValueError('resting exit partially filled; reconcile before migration')
        elif any(r['state'] == 'active' for r in rows):
            raise ValueError('ledger claims an active order absent from executor')
        source = self.conn.execute(
            "SELECT payload FROM events WHERE pos_id=? AND kind='open' ORDER BY event_id LIMIT 1",
            (pos['pos_id'],)).fetchone()
        if not source:
            raise ValueError('original source targets unavailable')
        targets = json.loads(source['payload']).get('signal_targets')
        short = bool(trade.get('is_short'))
        mark, entry = Decimal(str(trade['current_rate'])), Decimal(str(trade['open_rate']))
        reference = min(mark, entry) if short else max(mark, entry)
        policy = snapshot_nearby(targets, reference, short)
        filled_indices = {r['idx'] for r in rows if r['state'] == 'filled'}
        if any(r['idx'] in filled_indices for r in policy['targets']):
            raise ValueError('candidate already filled; manual source review required')
        plan = nearby_allocations(trade, policy)
        if not plan or sum(Decimal(str(p[2])) for p in plan) != Decimal(str(trade['amount'])):
            raise ValueError('plan does not exhaust remaining inventory exactly')
        # Only operationally significant ledger fields enter the approval hash;
        # background last_check_at ticks must not invalidate an unchanged plan.
        ledger = [{k: r[k] for k in ('target_id', 'idx', 'price', 'amount', 'state', 'ft_order_id')}
                  for r in rows]
        basis = dict(pos_id=pos['pos_id'], inventory=inventory(trade), ledger=ledger,
                     orders=[order_basis(o) for o in opened], stops=native_stops(trade), policy=policy, plan=plan)
        return dict(basis=basis, fingerprint=signature(basis), market=trade['pair'],
                    current_rate=trade['current_rate'], trade_id=trade_id,
                    targets=[dict(source_target=i+1, price=p, amount=q) for i,p,q in plan]), trade, rows

    async def preview(self, trade_id):
        proposal, _, _ = await self.proposal(trade_id)
        request_id = str(uuid.uuid4())
        self.conn.execute('INSERT INTO tp_migrations VALUES (?,?,?,?,?,?,?)',
                          (request_id, proposal['basis']['pos_id'], time.time(), 'preview',
                           encoded(proposal), None, None))
        return dict(request_id=request_id, state='preview', expires_in_seconds=300,
                    market=proposal['market'], current_rate=proposal['current_rate'],
                    targets=proposal['targets'], changes_live_orders=False)

    def finish(self, request_id, state, detail):
        result = dict(request_id=request_id, state=state, detail=detail)
        self.conn.execute('UPDATE tp_migrations SET state=?,result=? WHERE request_id=?',
                          (state, encoded(result), request_id))
        return result

    async def apply(self, request_id):
        row = self.conn.execute('SELECT * FROM tp_migrations WHERE request_id=?', (request_id,)).fetchone()
        if not row:
            raise ValueError('unknown migration request')
        if row['state'] != 'preview':
            # Includes crash/timeout while cancelling. No implicit retry.
            return json.loads(row['result']) if row['result'] else dict(
                request_id=request_id, state=row['state'], detail='Inspect orders before creating another preview; no retry submitted')
        if time.time() - row['created_at'] > 300:
            raise ValueError('preview expired; create a new preview')
        approved = json.loads(row['proposal'])
        fresh, trade, old_rows = await self.proposal(approved['trade_id'])
        if fresh['fingerprint'] != approved['fingerprint']:
            raise ValueError('position, order or plan changed; create a new preview')
        pos_id = row['pos_id']
        # Commit the archived ledger and hold BEFORE network cancellation. On a
        # crash the receiver sees blocked rows, so cannot rearm the old ladder.
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            self.conn.execute("UPDATE tp_migrations SET state='cancelling',old_ledger=? WHERE request_id=?",
                              (encoded(old_rows), request_id))
            self.conn.execute("UPDATE target_orders SET state='blocked',notes=? WHERE pos_id=?",
                              ('operator migration hold '+request_id, pos_id))
            self.conn.execute('COMMIT')
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise
        opened = normal_open_orders(trade)
        if opened:
            try:
                response = await self.cancel(self.cfg, approved['trade_id'], session=self.session)
            except Exception:
                return self.finish(request_id, 'needs_review', 'Cancellation outcome uncertain; no replacement sent')
            if not 200 <= response['status'] < 300:
                return self.finish(request_id, 'needs_review', 'Cancellation not acknowledged; no replacement sent')
        after = await self.get_trade(self.cfg, approved['trade_id'], session=self.session)
        if (not after or normal_open_orders(after) or inventory(after) != inventory(trade)
                or native_stops(after) != native_stops(trade)):
            return self.finish(request_id, 'needs_review', 'Inventory, stop or open orders changed after cancellation; no replacement sent')
        if opened:
            matches = [o for o in after.get('orders', [])
                       if str(o.get('order_id')) == str(opened[0]['order_id'])]
            if (len(matches) != 1 or matches[0].get('is_open') is not False
                    or matches[0].get('status') not in ('canceled', 'cancelled', 'expired')
                    or Decimal(str(matches[0].get('filled') or 0)) != 0):
                return self.finish(request_id, 'needs_review', 'Old exit cancellation not proven unfilled; no replacement sent')
        policy = approved['basis']['policy']
        try:
            plan = nearby_allocations(after, policy)
            if encoded(plan) != encoded(approved['basis']['plan']):
                raise ValueError('plan changed')
        except (ValueError, TypeError, ArithmeticError):
            return self.finish(request_id, 'needs_review', 'Target crossed or plan invalid after cancellation; no replacement sent')
        pos = self.conn.execute('SELECT state FROM positions WHERE pos_id=?', (pos_id,)).fetchone()
        if not pos or pos['state'] != 'open':
            return self.finish(request_id, 'needs_review', 'Receiver position closed during migration; no replacement sent')
        policy['migration_id'] = request_id
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            self.conn.execute('DELETE FROM target_orders WHERE pos_id=?', (pos_id,))
            self.conn.execute('UPDATE positions SET tp_policy=? WHERE pos_id=?', (encoded(policy), pos_id))
            for idx, price, amount in plan:
                self.conn.execute('INSERT INTO target_orders (pos_id,idx,price,amount,state,notes) VALUES (?,?,?,?,?,?)',
                                  (pos_id, idx, price, amount, 'pending', 'operator migration '+request_id))
            self.conn.execute("UPDATE tp_migrations SET state='armed' WHERE request_id=?", (request_id,))
            self.conn.execute('COMMIT')
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise
        # Existing durable placing/unknown states prevent duplicate forceexit
        # after ambiguous responses. A committed pending plan may resume after
        # restart; the adopter rechecks its first price against a fresh mark.
        result = await self.adopt(self.cfg, self.conn, pos_id, approved['trade_id'], session=self.session)
        if not result or result.get('state') != 'active':
            return self.finish(request_id, 'needs_review', 'New plan persisted but first exit not confirmed active; inspect target_orders')
        verified = await self.get_trade(self.cfg, approved['trade_id'], session=self.session)
        orders = normal_open_orders(verified) if verified else []
        expected = plan[0]
        if (not verified or inventory(verified) != inventory(trade) or len(orders) != 1
                or native_stops(verified) != native_stops(trade)
                or orders[0].get('ft_order_side') != ('buy' if trade.get('is_short') else 'sell')
                or orders[0].get('order_type') != 'limit'
                or Decimal(str(orders[0].get('safe_price') or orders[0].get('price') or 0)) != Decimal(str(expected[1]))
                or Decimal(str(orders[0].get('amount') or 0)) != Decimal(str(expected[2]))):
            return self.finish(request_id, 'needs_review', 'Post-submit snapshot differs; reconcile without resubmitting')
        return self.finish(request_id, 'active', 'First replacement exit confirmed by executor; later targets remain sequential')


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trade_id: int = Field(gt=0)


def install_routes(app, get_trade, cancel, adopt):
    def service(request):
        cfg = request.app.state.cfg
        password = request.headers.get('x-operator-password', '')
        # Ingress bearer is also required by the app-wide dependency. Restrict
        # these operations to docker exec / localhost, not source-event clients.
        if (not request.client or request.client.host not in ('127.0.0.1', '::1')
                or not cfg.ft_pass or cfg.ft_pass == 'mastertrader'
                or not secrets.compare_digest(password.encode(), cfg.ft_pass.encode())):
            raise HTTPException(403, 'local operator authentication required')
        if cfg.tp_mode != 'nearest_source' or not cfg.active_tp_limits:
            raise HTTPException(409, 'nearest_source with active TP limits required')
        return Migration(cfg, request.app.state.conn, get_trade, cancel, adopt,
                         request.app.state.ft_session)

    @app.post('/operator/tp-migrations/preview')
    async def preview(body: PreviewRequest, request: Request):
        worker = service(request)
        async with request.app.state.phase2_lock:
            try:
                return await worker.preview(body.trade_id)
            except (ValueError, TypeError, ArithmeticError, KeyError) as exc:
                raise HTTPException(409, str(exc)) from None

    @app.post('/operator/tp-migrations/{request_id}/apply')
    async def apply(request_id: uuid.UUID, request: Request):
        worker = service(request)
        async with request.app.state.phase2_lock:
            try:
                return await worker.apply(str(request_id))
            except (ValueError, TypeError, ArithmeticError, KeyError) as exc:
                raise HTTPException(409, str(exc)) from None
