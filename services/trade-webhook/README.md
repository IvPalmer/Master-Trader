# trade-webhook

Tiny VPS-side service that closes the gap Anthropic Channels can't fill: real-time alerts when Mac is asleep / no Claude Code session is active.

## What it does

- `POST /freqtrade/event` — accepts freqtrade webhook JSON. Appends a JSONL event to `/srv/lake/raw/trades/<bot>.jsonl` (atomic). Forwards a one-line summary to Telegram via the `elder-brain-ops` bot.
- `POST /test/notify` — manual smoke test; sends an arbitrary Telegram message.
- `GET /healthz` — readiness probe.

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
```

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
