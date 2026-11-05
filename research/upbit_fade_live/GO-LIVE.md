# Upbit fade live pilot: deploy, go live, roll back (#252)

Rules: prereg `upbit-krw-fade-live-pilot-2026-11` in `ft_userdata/preregistrations.json`.
Design: the "Addendum: live pilot (#252)" section of
`docs/superpowers/specs/2026-11-05-upbit-fade-forward-design.md`.

| Piece | Name | Where |
|---|---|---|
| Freqtrade bot | compose service `ft-upbit-fade-hl`, strategy `UpbitFadeLiveV1` | Dokploy stack, REST on `127.0.0.1:8105` |
| Gateway client | `hl-gateway` route `/upbit` (may submit exchange actions) | Dokploy stack |
| Trigger | systemd user unit `upbit-fade-live-trigger` | `/home/ubuntu/master-trader/research/upbit_fade_live/` |
| Trigger secrets | `~/.config/upbit-fade-live/trigger.env`, mode 600 | VPS only, never committed |
| Kill switch | `data/KILL` beside the trigger | VPS |
| Trigger ledger, log | `data/decisions.jsonl`, `data/trigger.log` | VPS |

Path of one entry: paper ledger record → trigger → `POST http://127.0.0.1:8105/api/v1/forceenter`
(HTTP Basic auth) → Freqtrade → `hl-gateway:8080/upbit` → Hyperliquid. The trigger never
signs or sends an exchange request.

Merging does not authorize any step below. Each part needs the operator's go-ahead.

## Part 1: deploy in dry-run

Run the pre-flight checklist in `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md` first: step 3
recreates `hl-gateway`, which every Hyperliquid bot, including live Killers, calls through,
and has its own procedure below.

1. Merge the PR to `main`, open the release PR `main` → `vps-deploy`, merge it, then on the VPS:

   ```bash
   cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code && sudo git pull --ff-only
   ```

2. Optional, per-bot API credentials: add all three or none of `FT_API_USER_UPBITFADE`,
   `FT_API_PASS_UPBITFADE`, `FT_API_JWT_UPBITFADE` (at least 32 chars) to the stack `.env`.
   Without them the bot uses the shared fleet credentials. Check:
   `./deploy/vps/preflight-credentials.sh .env`.
3. Gateway: follow **Gateway deploy (Killers is live)** below. It adds the `upbit` client
   (the bot cannot load markets without it), the pilot's budget slice and the cold-start
   rule.

4. Bot, dry-run (the default while `HYPERLIQUID_UPBIT_FADE_DRY_RUN` is unset):

   ```bash
   sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps ft-upbit-fade-hl
   until curl -sf http://127.0.0.1:8105/api/v1/ping >/dev/null; do sleep 5; done
   U=$(sudo docker exec ft-upbit-fade-hl printenv FREQTRADE__API_SERVER__USERNAME)
   P=$(sudo docker exec ft-upbit-fade-hl printenv FREQTRADE__API_SERVER__PASSWORD)
   curl -s -u "$U:$P" http://127.0.0.1:8105/api/v1/show_config | jq '{dry_run, strategy, state, stake_amount, max_open_trades, stoploss_on_exchange}'
   curl -s -u "$U:$P" 'http://127.0.0.1:8105/api/v1/markets?base=KPEPE&quote=USDC' | jq '.markets | keys'
   ```

   Expect `dry_run: true`, `UpbitFadeLiveV1`, `running`, 50, 2, `stoploss_on_exchange: false`,
   and `["KPEPE/USDC:USDC"]`.
5. Exporter: it reads `bots_config.json` once at start, through a single-file bind mount that
   `git pull` replaces, so recreate it (a plain restart keeps the old file):
   `sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps --force-recreate metrics-exporter`.
6. Trigger. Copy `research/upbit_fade_live/` from the merged `main` commit to
   `/home/ubuntu/master-trader/research/`, beside the running `upbit_fade_forward/` (it
   imports `uff_ledger` and `uff_report` from there and reads `upbit_fade_forward/data/ledger.jsonl`).
   Never copy it into the Dokploy checkout. Then:

   ```bash
   mkdir -p ~/.config/upbit-fade-live && install -m 600 /dev/null ~/.config/upbit-fade-live/trigger.env
   # Fill it from trigger.env.example: FT_API_USER/FT_API_PASS = $U/$P above,
   # TRADE_WEBHOOK_NOTIFY_TOKEN = the stack's value (or NOTIFY_URL= empty for no alerts).
   cd /home/ubuntu/master-trader/research/upbit_fade_live && python3 -B live_trigger.py status
   cp upbit-fade-live-trigger.service ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now upbit-fade-live-trigger
   journalctl --user -u upbit-fade-live-trigger -n 20    # "start: prereg ..., pause: off"
   ```

7. Dry-run acceptance (dry-run trades; plumbing checks, not results). The bot refuses any
   entry without a tag `upbit-fade:<event id>@<deadline ms>`, so the checks build one.
   Pause the trigger meanwhile: `touch .../upbit_fade_live/data/KILL`.

   ```bash
   fe() {  # pair, event id, deadline (ms)
     curl -s -u "$U:$P" -X POST http://127.0.0.1:8105/api/v1/forceenter -H 'Content-Type: application/json' \
       -d "{\"pair\":\"$1\",\"side\":\"short\",\"stakeamount\":50,\"leverage\":1,\"ordertype\":\"market\",\"entry_tag\":\"upbit-fade:$2@$3\"}"; echo; }
   D=$(( $(date +%s%3N) + 300000 ))
   # a. three concurrent entries: exactly two open, the third refused under the entry lock
   fe BTC/USDC:USDC plumbing:1 $D & fe ETH/USDC:USDC plumbing:2 $D & fe SOL/USDC:USDC plumbing:3 $D & wait
   curl -s -u "$U:$P" http://127.0.0.1:8105/api/v1/status | jq 'map({trade_id, pair, is_short, leverage, stake_amount, enter_tag})'
   # b. refused: a past deadline, a reused event id, a missing tag
   curl -s -u "$U:$P" -X POST http://127.0.0.1:8105/api/v1/forceexit -H 'Content-Type: application/json' -d '{"tradeid":"all"}'
   fe AVAX/USDC:USDC plumbing:4 $(( $(date +%s%3N) - 1000 ))
   fe AVAX/USDC:USDC plumbing:1 $D
   sudo docker logs ft-upbit-fade-hl --since 5m 2>&1 | grep "refused entry"
   ```

   Expect exactly two trades in (a), each `is_short`, leverage 1, stake 50. The third call
   fails with `Maximum number of trades is reached.` (it arrived after the others were
   committed) or `Failed to enter position` (refused under the entry lock, with a
   `refused entry ... 2 trades open` log line). Both calls in (b) fail with `Failed to enter
   position` and a `refused entry` line naming the deadline and the reused event. Then:
   - **stop settings:** `show_config` gives `stoploss: -0.6`, `stoploss_on_exchange: false`
     (dry-run), `minimal_roi: {"0": 100, "1440": -1}`;
   - **ROI time exit, real Freqtrade code:** open one more trade
     (`fe BTC/USDC:USDC plumbing:5 $(( $(date +%s%3N) + 300000 ))`), leave it, and about
     24 h later check that `/api/v1/trades` shows it closed with `exit_reason: "roi"` and a
     `close_date` at least 24 h after its `open_date` (the repo test only reproduces
     `min_roi_reached`);
   - remove `data/KILL` and leave the trigger running until at least one real paper event
     has passed through it (`python3 -B live_trigger.py status`).

## Gateway deploy (Killers is live)

Recreating `hl-gateway` interrupts every Hyperliquid call of live Killers (exits, order
status, account reads) for the recreate, and the new gateway starts with an empty rolling
window while Hyperliquid still counts the old one. The code's cold-start rule assumes the
last minute ran at the cap and lets it decay: Killers' actions wait about 1 s, its exit
reads about 4 s and background about 22 s after the start, all inside their queue deadlines.

**Pre-checks** (stop if any fails):

```bash
KU=$(sudo docker exec ft-killers-scalp printenv FREQTRADE__API_SERVER__USERNAME)
KP=$(sudo docker exec ft-killers-scalp printenv FREQTRADE__API_SERVER__PASSWORD)
KW=$(sudo docker exec ft-killers-scalp printenv FREQTRADE__EXCHANGE__WALLET_ADDRESS)
T=$(date -u +%Y%m%dT%H%MZ); mkdir -p ~/backups/gateway-$T && cd ~/backups/gateway-$T
curl -s -u "$KU:$KP" http://127.0.0.1:8099/api/v1/status > killers-status.json
jq 'map({trade_id, pair, has_open_orders, open: [.orders[] | select(.is_open) | {ft_order_side, order_type, status}]})' killers-status.json
hl() { curl -s https://api.hyperliquid.xyz/info -H 'Content-Type: application/json' -d "$1"; }
hl "{\"type\":\"clearinghouseState\",\"user\":\"$KW\"}" | jq -S '.assetPositions' > hl-positions-before.json
hl "{\"type\":\"frontendOpenOrders\",\"user\":\"$KW\"}" | jq -S 'map({coin, side, sz, triggerPx, limitPx, orderType, reduceOnly, oid})' > hl-orders-before.json
sudo docker logs killers-receiver --since 10m 2>&1 | tail -20
```

- every Killers trade has `has_open_orders: false` (no entry or exit order in flight; the
  resting stop is not counted);
- `hl-orders-before.json` holds only the resting stops and TP orders you expect, and
  `hl-positions-before.json` matches the bot's trades;
- the receiver log shows no signal being handled; avoid the US open (13:30 UTC) and news.

**Keep the previous image** for rollback, then recreate:

```bash
cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata
IMG=$(sudo docker inspect -f '{{.Config.Image}}' ft-hl-gateway); IMG=${IMG%%:*}
sudo docker tag "$(sudo docker inspect -f '{{.Image}}' ft-hl-gateway)" "$IMG:pre-252"
sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml build hl-gateway
sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps hl-gateway
until curl -sf http://127.0.0.1:8104/healthz >/dev/null; do sleep 2; done
```

**Verify** (within a few minutes):

```bash
curl -s http://127.0.0.1:8104/healthz | jq '{status, weight_last_minute, slice_weight_last_minute, killers: .clients.killers, upbit: .clients.upbit}'
curl -s -u "$KU:$KP" http://127.0.0.1:8099/api/v1/status | jq 'map({trade_id, pair, has_open_orders})'
sudo docker logs ft-killers-scalp --since 5m 2>&1 | grep -iE "error|429|timeout|exception" | tail
sudo docker logs ft-hl-gateway --since 5m 2>&1 | tail -20
cd ~/backups/gateway-$T
hl "{\"type\":\"clearinghouseState\",\"user\":\"$KW\"}" | jq -S '.assetPositions' | diff hl-positions-before.json - && echo positions unchanged
hl "{\"type\":\"frontendOpenOrders\",\"user\":\"$KW\"}" | jq -S 'map({coin, side, sz, triggerPx, limitPx, orderType, reduceOnly, oid})' | diff hl-orders-before.json - && echo stops and TPs unchanged
```

- `healthz` lists `upbit`, and `clients.killers` counts `ok` reads (its order-status and
  account reads) with no `queue_timeout` or `rate_limited`;
- Killers `/status` has the same trades; its log has no new errors;
- positions, stops and TPs on Hyperliquid are unchanged (a price move can change `.assetPositions`
  marks; compare `szi`, `entryPx` and the order list).

**Rollback** (stop the pilot first: it needs the `upbit` route):

```bash
sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml stop ft-upbit-fade-hl
sudo docker tag "$IMG:pre-252" "$IMG:latest"
sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps --force-recreate hl-gateway
```

Then repeat the verification.

## Part 2: account and keys (operator only)

The agent never creates, sees or handles these values.

1. Create a **new, dedicated** Hyperliquid master account (a new wallet address, not the
   Killers or ShortKeltner account; Hyperliquid nets positions per account). Not a
   subaccount: see the spec addendum.
2. Deposit about **150 USDC** and make sure it sits in the perps balance.
3. In the Hyperliquid app's API page, create an **API (agent) wallet** for that account. An
   API wallet can trade but cannot withdraw. Note its validity period and set a reminder
   before it expires.
4. In the Dokploy stack `.env` (the compose's Environment tab), set:

   ```
   HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS=<the master account address>
   HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=<the API wallet's private key>
   ```

   Never put them in the repo, an issue, a chat or a log.

## Part 3: go live

1. Pause the trigger while you check: `touch /home/ubuntu/master-trader/research/upbit_fade_live/data/KILL`.
2. In the stack `.env`, set `HYPERLIQUID_UPBIT_FADE_DRY_RUN=false`.
3. The one command:

   ```bash
   cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata
   sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps ft-upbit-fade-hl
   ```

   The entrypoint refuses to start (exit 64) if the wallet or key is missing. Live, it uses
   the separate database `tradesv3.live.UpbitFadeLiveV1.hyperliquid.sqlite` and turns the
   exchange stop on.
4. Verify:
   - `show_config`: `dry_run: false`, `state: running`, `stoploss_on_exchange: true`;
   - `/api/v1/balance`: about 150 USDC on the new account;
   - `/api/v1/profit`: `profit_closed_coin` 0 (the live database is new);
   - `sudo docker logs ft-upbit-fade-hl --tail 50`: no auth or market errors.
5. Record the epoch: a PR adding an amendment to `upbit-krw-fade-live-pilot-2026-11` with
   the UTC time of that first live start and the deployed commit, and setting
   `epoch_start` there. Record the same on #252.
6. Resume: `rm .../upbit_fade_live/data/KILL`. The trigger logs and alerts nothing until
   the next comparable event.
7. After the first live entry, check on Hyperliquid that the position has a resting stop
   (Freqtrade places it within about a minute: `stoploss_on_exchange_interval` 60). A live
   position without one is an execution defect: kill switch, then fix.

Expected alert once live: the exporter has no valuation adapter for the
`hyperliquid-upbit-fade` account yet, so it pages "Live bot outside the circuit breaker".
That is a known follow-up, not a fault of the pilot.

## Kill switch and rollback

- **Stop new entries** (any of these, strongest last):
  - `touch .../upbit_fade_live/data/KILL`: the trigger sends nothing while it exists;
  - `POST /api/v1/stopentry` (the same as `/pause` in Freqtrade 2026.7): the bot refuses
    every `/forceenter` ("trader is not running") and keeps managing open trades;
    `POST /api/v1/start` resumes;
  - `systemctl --user stop upbit-fade-live-trigger`.
- **Close what is open:** `POST /api/v1/forceexit` with `{"tradeid":"all"}`. Without it,
  open positions keep their 24 h exit and their exchange stop.
- **Back to dry-run:** close the live positions first (a dry-run bot does not see them, and
  their exchange stops stay on Hyperliquid with nothing managing the 24 h exit), then set
  `HYPERLIQUID_UPBIT_FADE_DRY_RUN=true` and run the same `up -d --no-deps ft-upbit-fade-hl`.
- **Kill rule (prereg):** the trigger engages the switch itself at -75 USDC realized in the
  live database (checked every loop; the bot also refuses entries at that level), on an
  unobserved `/forceenter` outcome, on a failed write, and if the URL answers for another
  strategy. The operator engages it for an orphaned position, a missing exchange stop or a
  double entry. Resuming needs a recorded decision (a prereg amendment).
- **After an `unknown` outcome** the trigger stays paused until the outcome is recorded;
  deleting `KILL` alone does not resume (it is put back on the next loop). Check the bot
  (`/api/v1/status` and `/api/v1/trades` for entry tag `upbit-fade:<event id>@...`) and the
  Hyperliquid account, then:

  ```bash
  systemctl --user stop upbit-fade-live-trigger
  cd /home/ubuntu/master-trader/research/upbit_fade_live
  python3 -B live_trigger.py reconcile '<event id>' --outcome not_entered --by palmer --note 'no trade, no HL position'
  #   or: --outcome entered --trade-id <id> --note 'trade <id> open with its stop'
  python3 -B live_trigger.py status
  rm data/KILL && systemctl --user start upbit-fade-live-trigger
  ```

  The trigger never resends that event. A `halted:` pause (a write failed) needs the disk
  or permission fixed, then a restart and the `KILL` file removed.

## Remove entirely

`systemctl --user disable --now upbit-fade-live-trigger`, close positions, then
`sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml stop ft-upbit-fade-hl`.
The databases and the trigger's `data/` stay for the record.
