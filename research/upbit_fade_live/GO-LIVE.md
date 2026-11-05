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
recreates `hl-gateway`, which every Hyperliquid bot, including live Killers, calls through.

1. Merge the PR to `main`, open the release PR `main` → `vps-deploy`, merge it, then on the VPS:

   ```bash
   cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code && sudo git pull --ff-only
   ```

2. Optional, per-bot API credentials: add all three or none of `FT_API_USER_UPBITFADE`,
   `FT_API_PASS_UPBITFADE`, `FT_API_JWT_UPBITFADE` (at least 32 chars) to the stack `.env`.
   Without them the bot uses the shared fleet credentials. Check:
   `./deploy/vps/preflight-credentials.sh .env`.
3. Gateway (adds the `upbit` client; the bot cannot load markets without it). Pick a moment
   with no Killers entry in flight:

   ```bash
   cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata
   sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml build hl-gateway
   sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml up -d --no-deps hl-gateway
   curl -sf http://127.0.0.1:8104/healthz
   ```

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
   journalctl --user -u upbit-fade-live-trigger -n 20    # "start: prereg ..., kill switch off"
   ```

7. Plumbing check in dry-run (a dry-run trade; not a result):

   ```bash
   curl -s -u "$U:$P" -X POST http://127.0.0.1:8105/api/v1/forceenter -H 'Content-Type: application/json' \
     -d '{"pair":"BTC/USDC:USDC","side":"short","stakeamount":50,"leverage":1,"ordertype":"market","entry_tag":"plumbing-check"}'
   curl -s -u "$U:$P" http://127.0.0.1:8105/api/v1/status | jq 'map({trade_id, pair, is_short, leverage, stake_amount})'
   curl -s -u "$U:$P" -X POST http://127.0.0.1:8105/api/v1/forceexit -H 'Content-Type: application/json' -d '{"tradeid":"all"}'
   ```

   Then leave it running until at least one real paper event has passed through the trigger
   (`python3 -B live_trigger.py status` shows its decision and, if entered, its dry-run trade
   closes about 24 h later by `roi`).

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
  live database, on an unobserved `/forceenter` outcome, and if the URL answers for another
  strategy. The operator engages it for an orphaned position, a missing exchange stop or a
  double entry. Resuming needs a recorded decision (a prereg amendment).
- After an `unknown` outcome: check `/api/v1/status` for entry tag `upbit-fade:<event id>`
  and the Hyperliquid account before removing `KILL`. The trigger never resends that event.

## Remove entirely

`systemctl --user disable --now upbit-fade-live-trigger`, close positions, then
`sudo docker compose -p compose-bypass-mobile-port-fbk1m6 -f docker-compose.prod.yml stop ft-upbit-fade-hl`.
The databases and the trigger's `data/` stay for the record.
