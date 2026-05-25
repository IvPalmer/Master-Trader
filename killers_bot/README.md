# killers_bot

Copy-trader for the **Binance Killers VIP** Telegram channel. Mirrors every
classified signal into a Freqtrade Futures dry-run bot. Independent of the
`insiders_bridge/` infra (different channel, different `.session`).

## What it does

```
Telegram channel
  → killers_bot.observer (host, systemd user unit)
    → classifier (Claude CLI via `docker exec elder-brain-bot claude`)
    → simulator (local SQLite paper-sim, audit trail)
    → POST /event → killers-receiver (container, port 8089)
                      → maps signal → /forceenter on ft-killers-scalp
                      → tracks (signal_id, symbol) → ft_trade_id in receiver SQLite
                      → reconcile_loop every 60s links orphans + detects missed closes
                    → ft-killers-scalp (Freqtrade Futures, port 8099)
                      → dry-run wallet $200, max 10 concurrent, lev 5x
                      → real fills against Binance Futures market data
                      → webhook → trade-webhook → @elder_brain_bot Telegram alerts
                    → ft-dashboard polls /api/v1/status, renders in dry-summary
                      tab as a real fleet bot alongside keltner/cascade
```

## Status (post-2026-05-25)

- Real Freqtrade Futures dry-run bot, $200 wallet.
- Paper-sim stays as a local audit trail.
- Listens to **`Binance Killers Vip`** (private channel, id `-1001655061968`) —
  not the free signals channel.
- 51-pair whitelist covering the channel's actual symbol traffic. Symbols
  outside the whitelist get skipped at the receiver (logged, not errored).
- First successful end-to-end fill: signal `#2143` POL/USDT LONG at
  $0.092, stake $19.98, lev 5x.

## Layout

```
killers_bot/
├── README.md                 this file
├── observer.py               systemd-launched Telethon listener (host)
├── classifier.py             Claude CLI subprocess wrapper (Killers prompt)
├── simulator.py              virtual position state machine (audit only)
├── schema.sql                SQLite: raw_messages, classifications, paper_positions
├── generate_session.py       one-shot interactive auth (legacy)
├── auth_step1_send_code.py   non-interactive auth step 1 (sends code)
├── auth_step2_sign_in.py     non-interactive auth step 2 (signs in with code)
├── list_channels.py          enumerate user's TG channels (for channel-id discovery)
├── .env                      KILLERS_TG_*, KILLERS_RECEIVER_URL, etc (gitignored)
├── .env.example              template
├── killers.session           Telethon session credential (gitignored)
└── Dockerfile / docker-compose.yml — Phase-1 standalone container (now superseded
    by the systemd unit + the killers-receiver / ft-killers-scalp containers
    defined in ft_userdata/docker-compose.prod.yml)
```

## Related services (live)

- `services/killers-receiver/` — FastAPI executor, runs as the `killers-receiver`
  container on dokploy-network. Owns the position graph (`receiver.sqlite`) +
  reconcile loop.
- `ft_userdata/user_data/configs/KillersScalpV1.json` + `strategies/KillersScalpV1.py`
  — Freqtrade Futures dry-run bot config + pass-through strategy.
- `ft_userdata/docker-compose.prod.yml` — service definitions for
  `killers-receiver` (port 8089 host-bound) + `ft-killers-scalp` (port 8099
  host-bound). Both deployed via the safe pattern in
  `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md`.

## Observer runtime

Runs on the VPS host (not containerized) so it can `docker exec` into
`elder-brain-bot` for the Claude CLI without volume-mount complexity.

```
~/.config/systemd/user/killers-observer.service   # systemd user unit
sudo loginctl enable-linger ubuntu                # survive reboot/logout
systemctl --user start  killers-observer
systemctl --user status killers-observer
systemctl --user stop   killers-observer
tail -f /home/ubuntu/killers-bot/observer.log
```

## Setup history

1. **Phase 1 (2026-05-24):** Observer-only paper sim. Telethon listener +
   classifier + SQLite, no exchange.
2. **Phase 2 (2026-05-25):** Promoted to real Freqtrade Futures dry-run bot
   with receiver service. Now part of the fleet, visible in dry-summary
   alongside keltner / cascade.

## Setup (one-time, if starting from scratch)

1. **Telegram app** at https://my.telegram.org → API development tools →
   note `api_id` + `api_hash`.
2. **Join the channel** in Telegram on your phone.
3. **Generate session** on your Mac:
   ```bash
   cd killers_bot
   pip install telethon
   python3 auth_step1_send_code.py +5511...        # sends SMS code
   python3 auth_step2_sign_in.py +5511... <hash> <code>
   # writes killers.session next to the script
   ```
4. **Resolve channel id** (optional, if joining a different channel):
   ```bash
   python3 list_channels.py
   ```
5. **Transfer .session to VPS** (age-encrypted or via secure SSH):
   ```bash
   scp killers.session ubuntu@100.96.225.124:/home/ubuntu/killers-bot/secrets/
   ssh ubuntu@100.96.225.124 'chmod 600 /home/ubuntu/killers-bot/secrets/killers.session'
   ```
6. **Configure observer .env** at `killers_bot/.env` on the VPS bare clone:
   ```
   KILLERS_TG_API_ID=...
   KILLERS_TG_API_HASH=...
   KILLERS_TG_SESSION=/home/ubuntu/killers-bot/secrets/killers.session
   KILLERS_TG_CHANNEL_ID=-1001655061968
   KILLERS_CLAUDE_BINARY="docker exec elder-brain-bot claude"
   KILLERS_CLAUDE_TIMEOUT_SEC=20
   KILLERS_DB=/home/ubuntu/killers-bot/state.sqlite
   KILLERS_HEARTBEAT_SEC=120
   KILLERS_RECEIVER_URL=http://127.0.0.1:8089/event
   ```
7. **Start the observer** via systemd user unit (see Observer runtime section).
8. **Deploy the receiver + Freqtrade bot** via the safe compose pattern
   from `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md`:
   ```bash
   ssh ubuntu@100.96.225.124
   cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata
   docker compose -f docker-compose.prod.yml build killers-receiver
   docker compose -f docker-compose.prod.yml up -d --no-deps \
       ft-killers-scalp killers-receiver
   ```

## Watch live activity

```bash
# Stdout log (observer)
ssh ubuntu@100.96.225.124 tail -f /home/ubuntu/killers-bot/observer.log

# Local paper-sim positions (audit)
ssh ubuntu@100.96.225.124 sqlite3 /home/ubuntu/killers-bot/state.sqlite \
  "SELECT pos_id, signal_id, symbol, state, realized_pnl FROM paper_positions ORDER BY pos_id DESC LIMIT 10"

# Receiver positions (real Freqtrade tracking)
ssh ubuntu@100.96.225.124 curl -sf http://127.0.0.1:8089/positions

# Freqtrade open trades (real dry-run fills)
ssh ubuntu@100.96.225.124 \
  curl -sf -u "$FT_USER:$FT_PASS" http://localhost:8099/api/v1/status

# Dashboard (any tab — killers shows as a regular bot card)
open https://master-trader.grooveops.dev
```

## Risk model

- **Dry run only.** `dry_run: true` in `KillersScalpV1.json`; Freqtrade uses
  exchange data for prices but simulates fills against a virtual wallet.
- **No keys.** `exchange.key` and `exchange.secret` are empty in the config;
  there's nothing to leak.
- **Stake cap.** $20 per trade × 10 max concurrent = $200 max notional, which
  matches the dry wallet. Receiver's `KILLERS_MAX_OPEN=10` guard enforces.
- **Idempotency.** `UNIQUE(open_msg_id)` in receiver schema + dedupe path so
  retries / observer-replay don't double-fire `/forceenter`.
- **Reconciler.** 60s loop links orphan `requested` positions to their actual
  Freqtrade `trade_id` (handles receiver crash between POST and DB update)
  and marks our positions closed when Freqtrade reports them gone (handles
  liquidation, manual close from Freqtrade UI, etc).
- **Symbol ambiguity.** If multiple active positions share a symbol and the
  classifier sends a close event without a clear `signal_id` linkage, the
  receiver refuses the close ("ambiguous_close") rather than closing the
  wrong trade.
