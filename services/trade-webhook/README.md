# trade-webhook

Tiny VPS-side service that closes the gap Anthropic Channels can't fill: real-time alerts when Mac is asleep / no Claude Code session is active.

## What it does

- `POST /freqtrade/event` — accepts freqtrade webhook JSON. Appends a JSONL event to `/srv/lake/raw/trades/<bot>.jsonl` (atomic). Forwards a one-line summary to Telegram via the `elder-brain-ops` bot.
- `POST /test/notify` — relays `{"text": ...}` to Telegram. Used by killers-receiver / insiders-receiver alerts and as a manual smoke test. Requires the `X-Notify-Token` header when `TRADE_WEBHOOK_NOTIFY_TOKEN` is set (see below).
- `GET /healthz` — readiness probe.

`/freqtrade/event` and `/healthz` remain unauthenticated (Freqtrade's webhook config is not updated yet).

## Deployment

Plain `docker compose` from `/home/ubuntu/master-trader/services/trade-webhook/` on the VPS. Lives in the master-trader repo because the webhook only exists to receive events from this repo's freqtrade strategies — ownership obvious, atomic changes. Lifecycle independent of master-trader's Dokploy compose stack (rebuilding freqtrade strategies doesn't bounce the webhook).

Bring up after `git pull`:

```
cd /home/ubuntu/master-trader/services/trade-webhook
docker compose up -d --build
```

Secrets live in `/etc/lake/ops-bot.env`:

```
OPS_BOT_TOKEN=<elder_brain_bot token from @BotFather>
OPS_BOT_CHAT_ID=<your Telegram user id>
TRADE_WEBHOOK_NOTIFY_TOKEN=<openssl rand -hex 24>
```

### `/test/notify` token rollout (#59)

The service shares `dokploy-network` with ~25 unrelated apps, so `/test/notify` would otherwise let any of them post to the ops chat.

1. Generate one value (`openssl rand -hex 24`, at least 24 chars; shorter values log a WARNING).
2. Set `TRADE_WEBHOOK_NOTIFY_TOKEN` to that value in the Dokploy env of the master-trader compose (read by both `killers-receiver` and `insiders-receiver`) and redeploy them. They send it as `X-Notify-Token`; trade-webhook ignores the header while it has no token.
3. Add it to `/etc/lake/ops-bot.env` and `docker compose up -d` here. From then on a missing or wrong header gets 401 and nothing is sent. Receivers log `telegram notify rejected (401)` on a mismatch.
4. Next step (not yet done): make the token mandatory — refuse to start without it, like killers-receiver's `KILLERS_INGRESS_TOKEN`.

While unset, the route stays open and startup logs a WARNING saying so.

Manual smoke test once the token is set:

```bash
curl -X POST -H 'content-type: application/json' -H "X-Notify-Token: $TRADE_WEBHOOK_NOTIFY_TOKEN" \
  -d '{"text":"hello"}' http://127.0.0.1:8088/test/notify
```

Tests: `cd services/trade-webhook && python -m pytest tests/ -q` (network-free; Telegram is stubbed).

The service joins `dokploy-network` so master-trader's freqtrade containers reach it via Docker DNS at `http://trade-webhook:8088/freqtrade/event`.

## Master-trader webhook config

Set in `FundingFadeV1.live.json` (or whichever active strategy):

```json
"webhook": {
  "enabled": true,
  "url": "http://trade-webhook:8088/freqtrade/event",
  "format": "json"
}
```

## Local sanity check

From inside the dokploy-network (any sibling container) — or from VPS host hitting the published port if needed:

```bash
curl -X POST -H 'content-type: application/json' \
  -d '{"type":"status","bot_name":"smoke","message":"hello from synthetic test"}' \
  http://trade-webhook:8088/freqtrade/event
```

Expected: HTTP 200, JSONL line in `/srv/lake/raw/trades/smoke.jsonl`, Telegram message on your phone.
