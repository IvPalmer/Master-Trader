# trade-webhook

Tiny VPS-side service that closes the gap Anthropic Channels can't fill: real-time alerts when Mac is asleep / no Claude Code session is active.

## What it does

- `POST /freqtrade/event` — accepts freqtrade webhook JSON. Appends a JSONL event to `/srv/lake/raw/trades/<bot>.jsonl` (atomic). Forwards a one-line summary to Telegram via the `elder-brain-ops` bot. Checks the shared token per `TRADE_WEBHOOK_EVENT_AUTH` (see below). The record's `ts` and `received_from` are always the server's; a payload cannot set them.
- `POST /test/notify` — relays `{"text": ...}` to Telegram. Used by killers-receiver alerts (and the Killers risk warden, which runs inside killers-receiver) and as a manual smoke test. Requires the `X-Notify-Token` header when `TRADE_WEBHOOK_NOTIFY_TOKEN` is set.
- `GET /healthz` — readiness probe, unauthenticated.

## Network

The service is on master-trader's compose network only (`compose-bypass-mobile-port-fbk1m6_default`, attached as `master-trader-net`), plus `127.0.0.1:8088` on the host for cron jobs. It is not on `dokploy-network` (#97). That Swarm overlay is shared with ~25 unrelated apps. Its access log from 2026-05-20 to 2026-10-02 shows every `/freqtrade/event` coming from the compose network and every `/test/notify` from the two receivers, which are on both networks. Callers reach it as `http://trade-webhook:8088/...`.

## Deployment

Plain `docker compose` from `/home/ubuntu/master-trader/services/trade-webhook/` on the VPS. Lives in the master-trader repo because the webhook only exists to receive events from this repo's freqtrade strategies — ownership obvious, atomic changes. Lifecycle independent of master-trader's Dokploy compose stack (rebuilding freqtrade strategies doesn't bounce the webhook).

Bring up after `git pull` of `/home/ubuntu/master-trader` (the host checkout of `vps-deploy`, separate from the Dokploy one):

```
cd /home/ubuntu/master-trader/services/trade-webhook
docker compose up -d --build
```

Secrets live in `/etc/lake/ops-bot.env`:

```
OPS_BOT_TOKEN=<elder_brain_bot token from @BotFather>
OPS_BOT_CHAT_ID=<your Telegram user id>
TRADE_WEBHOOK_NOTIFY_TOKEN=<openssl rand -hex 24>
TRADE_WEBHOOK_EVENT_AUTH=<monitor|enforce, default monitor>
```

## The shared token (#59, #97)

One value, `TRADE_WEBHOOK_NOTIFY_TOKEN`, generated with `openssl rand -hex 24` (at least 24 characters; shorter values log a WARNING). Keep it hex. Freqtrade runs `str.format` on its template strings, so a `{` or `}` in the value breaks every webhook call. An all-digit value would be typed as a number and rejected. Who sends it, and how:

| Caller | Route | Carries the token as | Configured in |
|---|---|---|---|
| killers-receiver, Killers risk warden | `/test/notify` | `X-Notify-Token` header | Dokploy env of the master-trader compose |
| metrics-exporter circuit breaker | `/freqtrade/event` | `X-Notify-Token` header | Dokploy env |
| the six Freqtrade bots | `/freqtrade/event` | `webhook_token` field in the JSON body | Dokploy env, via `FREQTRADE__WEBHOOK__*` (below) |
| health report and other `ft_userdata` report scripts | `/freqtrade/event` | `X-Notify-Token` header (`ft_userdata/webhook_notify.py`, #101) | `run-health-report.sh` reads it from `/etc/lake/ops-bot.env` |

Freqtrade's webhook cannot send headers (2026.7 reads only `url`, `format`, `retries`, `retry_delay`, `timeout`), and a token in the URL would land in every bot's log on the first failed call. So `ft_userdata/docker-compose.prod.yml` sets `FREQTRADE__WEBHOOK__<TEMPLATE>__WEBHOOK_TOKEN` for each body template the bot's config defines, and Freqtrade merges that field into every event it posts. trade-webhook removes `webhook_token` from every payload before it stores, summarizes or logs anything.

`/test/notify`: token unset keeps the route open (startup WARNING). Token set means a missing or wrong header gets a 401 and nothing is sent. Receivers log `telegram notify rejected (401)` on a mismatch. Next step, not yet done: refuse to start without it, like killers-receiver's `KILLERS_INGRESS_TOKEN`.

`/freqtrade/event`, by `TRADE_WEBHOOK_EVENT_AUTH`:

- `monitor` (default): every event is accepted. With a token configured, each event that does not carry it logs `unauthenticated POST /freqtrade/event bot=<bot> from=<ip>: missing|invalid token`.
- `enforce`: a missing or wrong token is a 401. Nothing is written to the lake and nothing goes to Telegram. The service refuses to start in this mode without a token, or with any other value.

### Rollout order

1. **trade-webhook first, with no token yet.** Merge and release this change and #101 (PR #139), `git pull` the host checkout and `docker compose up -d --build` here. This drops `dokploy-network` and starts stripping `webhook_token`. An older trade-webhook would write a bot's token straight into the lake JSONL, so this step must come before any bot carries the token. Check: the next receiver notify and the next bot event still return 200 (`docker logs trade-webhook`).
2. **Callers.** Set `TRADE_WEBHOOK_NOTIFY_TOKEN` in the Dokploy env of the master-trader compose. Recreate `killers-receiver`, `metrics-exporter` and the bot containers with `--no-deps`. Recreating a bot restarts it, so schedule it under the runbook's rules (`docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md`). A bot that has not been recreated yet keeps posting without the token, which `monitor` accepts. Copy `deploy/vps/run-health-report.sh` over `/home/ubuntu/master-trader/run-health-report.sh`. The installed copy predates the per-bot credential export and the token read.
3. **Token on trade-webhook.** Add `TRADE_WEBHOOK_NOTIFY_TOKEN` (same value) to `/etc/lake/ops-bot.env` and `docker compose up -d`. `/test/notify` is now enforced and `/freqtrade/event` monitored.
4. **Check.** Each bot posts a startup status on (re)start, so step 2 already produced one event per bot. `docker logs trade-webhook 2>&1 | grep 'unauthenticated POST'` must show nothing newer than step 3, across at least one 23:00 health report.
5. **Enforce.** Add `TRADE_WEBHOOK_EVENT_AUTH=enforce` to `/etc/lake/ops-bot.env` and `docker compose up -d`.

Rollback: remove `TRADE_WEBHOOK_EVENT_AUTH` (back to `monitor`) and `docker compose up -d`. The network change is reverted by restoring the `dokploy-network` entries in `docker-compose.yml`.

Manual smoke tests once the token is set:

```bash
curl -X POST -H 'content-type: application/json' -H "X-Notify-Token: $TRADE_WEBHOOK_NOTIFY_TOKEN" \
  -d '{"text":"hello"}' http://127.0.0.1:8088/test/notify
curl -X POST -H 'content-type: application/json' -H "X-Notify-Token: $TRADE_WEBHOOK_NOTIFY_TOKEN" \
  -d '{"type":"status","bot_name":"smoke","status":"hello from synthetic test"}' \
  http://127.0.0.1:8088/freqtrade/event
```

Expected: HTTP 200, a JSONL line in `/srv/lake/raw/trades/smoke.jsonl`, a Telegram message. Without the header, the second call is accepted with a WARNING under `monitor` and gets a 401 under `enforce`.

Tests: `cd services/trade-webhook && python -m pytest tests/ -q` (network-free; Telegram is stubbed). Compose wiring is pinned in `tests/test_trade_webhook_auth_wiring.py`.

## Master-trader webhook config

Set in each bot's config (`FundingFadeV1.live.json` and the other deployed ones), with one body template per event type and an explicit `bot_name`:

```json
"webhook": {
  "enabled": true,
  "url": "http://trade-webhook:8088/freqtrade/event",
  "format": "json",
  "webhookstatus": {"type": "status", "bot_name": "FundingFadeV1", "status": "{status}"}
}
```

The token is not in the config. It comes from the container's environment (above), and the env keys must name exactly the templates the config defines.
