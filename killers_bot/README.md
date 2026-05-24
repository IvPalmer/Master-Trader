# killers_bot

Standalone observer-bot for `t.me/BinanceKillers_FreeSignal`. Independent
of the `insiders_bridge/` and `insiders-receiver/` infra — different
channel, different format, different `.session`.

## What it does (Phase 1 — observe-only)

1. Subscribes to the channel via Telethon (user's own session).
2. Persists every raw message to SQLite.
3. Classifies each message via Claude CLI (Killers-format prompt).
4. For "open"-class signals: virtually opens a paper position (entry mid,
   SL, target list captured).
5. For "close_*"/"move_sl"-class events linked by `signal_id`: updates
   the matching paper position.
6. Logs every step to stdout in a human-readable tail so you can watch
   the bot's behavior live with `docker logs -f killers-bot`.

No real orders. No exchange connection. Pure observation.

## Layout

```
killers_bot/
├── README.md                  this file
├── Dockerfile                 python:3.13 + telethon + aiohttp
├── requirements.txt
├── generate_session.py        run on Mac one-time to create killers.session
├── schema.sql                 SQLite schema (raw_messages, classifications, positions)
├── classifier.py              Claude CLI wrapper with Killers prompt
├── simulator.py               virtual position state machine
└── observer.py                main: listener → classifier → simulator → log
```

## Setup (one-time)

1. **Register Telegram app** at https://my.telegram.org → API development
   tools. Note `api_id` (int) + `api_hash` (32-char string).
2. **Join the channel** in Telegram on your phone: search
   `BinanceKillers_FreeSignal`, tap Join.
3. **Generate session** (on Mac):
   ```bash
   cd killers_bot
   pip install telethon
   python3 generate_session.py
   # Prompts for api_id, api_hash, phone, SMS code.
   # Writes killers.session next to the script.
   ```
4. **Transfer session to VPS** (age-encrypted using the existing
   `insiders-handover.pub` keypair):
   ```bash
   age -r $(cat ../docs/insiders-signals/insiders-handover.pub) \
       -o killers.session.age killers.session
   scp killers.session.age ubuntu@100.96.225.124:/tmp/
   # On VPS:
   age -d -i ~/.age/insiders-handover.key /tmp/killers.session.age \
       > /home/ubuntu/killers-bot/secrets/killers.session
   chmod 600 /home/ubuntu/killers-bot/secrets/killers.session
   ```
5. **Set env** in `killers_bot/.env`:
   ```
   KILLERS_TG_API_ID=12345678
   KILLERS_TG_API_HASH=abcdef...
   KILLERS_TG_SESSION=/run/secrets/killers.session
   KILLERS_TG_CHANNEL_USERNAME=BinanceKillers_FreeSignal
   KILLERS_CLAUDE_BINARY=claude
   KILLERS_DB=/var/lib/killers/state.sqlite
   ```
6. **Build + start**:
   ```bash
   docker compose --profile killers up -d --build
   docker logs -f killers-bot
   ```

## Watching live

- `docker logs -f killers-bot` — every msg + classification + simulated
  position update in real-time
- Dashboard: TBD (Phase 3)
