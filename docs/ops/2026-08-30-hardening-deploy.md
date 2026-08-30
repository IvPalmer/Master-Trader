# Deploying the 2026-08-30 fleet hardening

Five fixes from the live-fleet security review. Read this before deploying:
one of them **stops both copy-trader receivers until new secrets exist**, by
design. Blast-radius tiers are in
[UPDATING-WITHOUT-BREAKING-BOTS.md](UPDATING-WITHOUT-BREAKING-BOTS.md).

## What changed

| # | Change | Touches the live execution path? |
|---|---|---|
| 1 | Receivers authenticate every route but `/healthz` | **Yes** — killers + insiders |
| 2 | `force_entry_enable: false` on ShortKeltnerV2HL | No (removes an endpoint nothing used) |
| 3 | Macro-gate NaN watchdog covers `btc_usdc_sma50_slope_1h` | No (logging + fail-closed reindex) |
| 4 | Webhook alerts enabled on ShortKeltnerV2HL | No |
| 5 | Per-bot API credentials; no credential literals in configs | Only if you opt in |

## New environment variables

Add to the Dokploy stack `.env` **before** deploying.

### Required — the receivers refuse to start without these

```bash
openssl rand -hex 24   # run twice, use a DIFFERENT value for each
```

```
KILLERS_INGRESS_TOKEN=<first value>
INSIDERS_INGRESS_TOKEN=<second value>
```

Two distinct values on purpose: the receivers drive two separately funded
Hyperliquid accounts, and a token leaked from one must be useless against the
other. Compose fans these out to the receivers, to the two Freqtrade
containers (`SIGNAL_RECEIVER_TOKEN`, used by `KillersScalpV1.custom_stoploss`
to read moved stops) and to the dashboard (which reads `/ingress`).

### Optional — per-bot Freqtrade API credentials

Every bot still falls back to the shared `FREQTRADE__API_SERVER__*` pair, so
you can migrate one bot at a time, or never. Slugs: `KELTNER`, `FUNDINGFADE`,
`OITREND`, `KILLERS`, `INSIDERS`, `SHORTKELTNER`.

```
FT_API_USER_KILLERS=...
FT_API_PASS_KILLERS=...
FT_API_JWT_KILLERS=...     # >= 32 chars (freqtrade schema minimum)
```

Set all three for a bot, or none. The exporter, the dashboard and that bot's
receiver all resolve the same slug, so a bot moves as one unit.

### Optional — legacy credential fallback

```
FT_ALLOW_LEGACY_API_CREDS=false   # default
```

`api_utils` no longer retries with freqtrade's published `freqtrader` /
`mastertrader` defaults. Set `true` only to unblock a legacy dry-run bot that
still uses them; leaving it off is what stops a reachable bot from being
guessable.

## The observer is outside compose

`killers_bot/observer.py` runs on the host (systemd/nohup), not in the stack,
and it is the producer for `POST /event`. It needs the same two tokens:

```
KILLERS_RECEIVER_TOKEN=<same as KILLERS_INGRESS_TOKEN>
INSIDERS_RECEIVER_TOKEN=<same as INSIDERS_INGRESS_TOKEN>
```

in `killers_bot/.env` (the observer loads it via `_load_dotenv`). **Restart
the observer as part of this deploy.** Until you do, every signal it posts is
answered 401, logged at ERROR, and dropped without retry — loud, and no trade
is taken, but signals in that window are lost.

## `--build` is not optional

`killers-receiver`, `insiders-receiver` and `ft-dashboard` are **`build:`
services pinned to a tag**. `docker compose up -d` recreates their containers
from the *existing* image. The new env vars would appear in `docker inspect`
while the containers still ran the old, unauthenticated code — a deploy that
looks successful and changes nothing. Every command below that touches those
three services passes `--build`.

## Order

Run steps 4–7 back to back. Between them the copy-trader path is down.

1. Add `KILLERS_INGRESS_TOKEN` and `INSIDERS_INGRESS_TOKEN` to the stack `.env`.
2. Add the same values to `killers_bot/.env` on the host as
   `KILLERS_RECEIVER_TOKEN` and `INSIDERS_RECEIVER_TOKEN`.
3. Merge `main` → `vps-deploy`, push, `sudo git pull` on the VPS, then:

```bash
./deploy/vps/preflight-credentials.sh .env
```

Fix anything it reports before continuing.

4. Note the last message id the observer processed, so you can replay the gap:

```bash
sqlite3 /home/ubuntu/killers-bot/state.sqlite 'SELECT MAX(msg_id) FROM raw_messages;'
```

5. Rebuild and recreate the receivers with their bots — they must agree on the token:

```bash
docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps --build killers-receiver insiders-receiver ft-killers-scalp ft-insiders-scalp
```

6. **Wait for both Freqtrade APIs before restarting the observer.** Their
   entrypoints `sleep 60` before exec'ing freqtrade, so `up -d` returns long
   before either bot can accept an order. An event that arrives in this window
   is authenticated, reaches the receiver, and then fails its REST call — which
   can leave a position row `requested` with no order behind it, and a
   redelivery is deduped as already-seen. Wait:

```bash
for p in 8099 8098; do
  until curl -sf "http://127.0.0.1:$p/api/v1/ping" >/dev/null; do sleep 5; done
  echo "port $p ready"
done
```

7. Restart the observer on the host.

8. Replay anything the gap swallowed. Compare the id from step 4 against the
   receiver's ingress audit and the channel; the observer backfills on start,
   but confirm nothing sits in `requested` with no Freqtrade trade:

```bash
curl -s -H "Authorization: Bearer $KILLERS_INGRESS_TOKEN" http://127.0.0.1:8089/positions | head -c 2000
curl -s -H "Authorization: Bearer $KILLERS_INGRESS_TOKEN" http://127.0.0.1:8089/events/pending
```

9. Recreate the rest. Only `ft-dashboard` needs a rebuild here; the bots are
   config-only:

```bash
docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps ft-short-keltner-hl-live keltnerbouncev1 fundingfadev1 oi-trend-pullback metrics-exporter
docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps --build ft-dashboard
```

## Verifying

```bash
docker logs --tail 20 killers-receiver
```

Expect `receiver up ft=... risk=...`. If instead the container restart-loops
with `KILLERS_INGRESS_TOKEN is required`, the `.env` value did not reach it.

Unauthenticated calls must be refused, and `/healthz` must not be:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8089/ingress
```

Expect `401`. With the token it must be `200`:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $KILLERS_INGRESS_TOKEN" http://127.0.0.1:8089/ingress
```

The generated API docs must be gone — app-level dependencies never covered
them, so they are disabled rather than exempted:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8089/openapi.json
```

Expect `404`. A `200` means the container is still on the old image: redo
step 5 with `--build`.

Then confirm the dashboard still renders receiver readiness for both copy
bots (a 401 there shows as "receiver unavailable" while `/healthz` still
answers — that pattern means the token is wrong, not the network).

The next daily health report (23:00 UTC) must still cover all six bots. It
now reads each bot's effective credentials from that bot's own container, so
it survives per-bot rotation; if a bot goes blank, check
`/home/ubuntu/master-trader/research/logs/health_report.log` for the
`could not read credentials` warning.

## Rolling back

Every change is config or env. Reverting the commit and recreating the
containers restores the previous behaviour; the tokens can stay in `.env`
harmlessly. There is no schema or database migration.

## Not fixed here

The stop-limit band (`stoploss_on_exchange_limit_ratio: 0.98`) still means a
gap of more than 2% past a stop trigger can leave a position open, and
Hyperliquid native stop placement has still never been observed end-to-end on
an organic fill. Both are tracked separately from this deploy.
