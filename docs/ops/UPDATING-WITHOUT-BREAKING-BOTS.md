# Updating the master-trader stack without breaking live bots

A runbook. Written 2026-05-25 after a `docker compose up -d --build ft-dashboard`
recreated keltner + cascade mid-trade and fired "STATUS process died" alerts.

**Rule of thumb:** every change has a blast radius. Know it before you act.

If the bots were live and a recreate happened during a price spike, an SL
that should have triggered at $X could fire at $X−5% on resume because the
bot was blind for 3 minutes. Dry-run forgives. Live doesn't.

---

## Blast-radius tiers

Classify every change before running anything.

### Tier 0 — zero-impact
Operations the bots cannot observe. Safe any time, no notification needed.

- Editing files in `docs/`, `research/`, `strategy_lab/`, `ft_userdata/engine/`
- Reading SQLite databases (read-only queries, even via mounted volume)
- Running offline backtests / replays from outside the running containers
- Inspecting container logs, `docker ps`, `docker stats`
- Git commits + pushes that don't trigger a Dokploy auto-deploy
- Anything inside `killers_bot/` SQLite (read-only mounted into ft-dashboard,
  doesn't touch the trading bots at all)

### Tier 1 — bot-internal (no container touch)
Pick up via Freqtrade's REST API or hot-reload. No process restart.

- `/forceexit_all` — close all positions at market (use sparingly, but no
  process disruption)
- `/stopentry` — bot keeps managing open positions but stops opening new ones
- `/start` — resume after a stopentry
- `/reload_config` — reloads JSON config (pairlists, exchange settings).
  Does NOT reload strategy `.py` code.
- Watching `/api/v1/status`, `/api/v1/profit`, etc. (read-only polling)

### Tier 2 — container restart (no rebuild)
`docker compose restart SERVICE`. Container stops + starts on the same image.
~10s of bot downtime. Trades persist via the sqlite volume.

- Picking up new env vars that affect runtime only (e.g., log level)
- Recovering from a transient stuck-state crash
- Forcing a fresh exchange connection

**Cost if live:** ~10s blind window. Acceptable for most bots most of the
time. Avoid during high-volatility windows.

### Tier 3 — container recreate (config change, no image change)
`docker compose up -d --no-deps --force-recreate SERVICE`. Container destroyed
+ rebuilt with new config. ~20-40s blind window plus REST API spin-up.

- Adding/removing volume mounts
- Adding/removing networks
- Changing depends_on
- Changing port mappings
- Any docker-compose.yml edit affecting that service

**Cost if live:** 20-40s blind window. Critical: the bot comes back in
`stopped` state on some restart paths (depends on Freqtrade version + how
the container exit was signaled). After recreate, ALWAYS verify
`/api/v1/status` returns trades AND `/api/v1/show_config` shows `state: running`.
If `stopped`, send POST `/api/v1/start` to resume.

### Tier 4 — image rebuild (code change)
`docker compose build SERVICE` then Tier 3 recreate. Old image stays until
the new container is running.

- Strategy `.py` code changes (KeltnerBounceV1, etc)
- Freqtrade base image bump
- New Python dependency
- Anything in the bot's Dockerfile

**Cost if live:** same 20-40s as Tier 3, plus the risk that the NEW strategy
code computes signals differently from the OLD on the same OHLCV data. The
bot may decide to exit an open trade immediately on resume because the new
strategy code re-evaluated and didn't like the position. Test strategy
changes in dry-run for ≥7 days before promoting to live.

### Tier 5 — destructive (volume changes, data migrations)
`docker compose down` + volume manipulation + `up`. Multiple minutes of
downtime, potential for data loss.

- Database schema migrations
- Volume removal (NEVER without a backup of `user_data/tradesv3.dryrun.sqlite`
  or `tradesv3.sqlite` for live)
- Switching exchange (Binance ↔ Hyperliquid)
- Renaming containers (changes Docker network identity)

**Cost if live:** multiple minutes blind + risk of state loss. NEVER do
this with open positions. Drain first.

---

## Pre-flight checklist (read EVERY TIME before any Tier-2+ change)

Run these checks. If you can't tick all, don't proceed.

```
[ ] Which tier is this change?
[ ] Which bots have open positions right now?
      ssh ubuntu@100.96.225.124 'for p in 8095 8096 8097; do
        echo "port $p:"; curl -sf -u $CREDS http://localhost:$p/api/v1/status |
        python3 -c "import json,sys; t=json.load(sys.stdin); print(f\"  {len(t)} open\")"
      done'
[ ] Are any of those positions near SL? (i.e., would a 3-min blind window be costly?)
[ ] Have I scoped my command with --no-deps so I don't catch sibling bots?
[ ] Do I have a rollback path? (For code changes: previous git SHA.
    For config changes: the previous docker-compose.yml.)
[ ] Will this fire a "STATUS process died" Telegram alert? If yes,
    is the operator (Palmer) aware so they don't think the bot crashed?
```

**For live capital, add:**
```
[ ] Is now a safe window? (Avoid 13:30 UTC US market open, major news, weekends.)
[ ] If I'm uncertain, can I /stopentry first, let positions drain, then act?
[ ] Have I posted the change window to the Telegram bot so alerts in that
    window are pre-attributed?
```

---

## Safe commands by operation

### Updating ft-dashboard only (Tier 4)

```bash
# Build NEW image without touching anything else
docker compose -f docker-compose.prod.yml build ft-dashboard

# Recreate ONLY ft-dashboard. --no-deps prevents Compose from
# touching keltner/cascade/funding-fade.
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate ft-dashboard

# Verify
docker ps --filter name=ft-dashboard
curl -s http://localhost:8000/healthz
```

### Updating a trading bot strategy (Tier 4 on a single bot)

```bash
# Pre-flight: list open trades on this bot
curl -sf -u $CREDS http://localhost:8095/api/v1/status | jq 'length'

# If there are open trades you don't want to risk:
curl -sf -X POST -u $CREDS http://localhost:8095/api/v1/stopentry
# wait for /status to show 0 trades (or accept the risk)

# Rebuild + recreate JUST this bot
docker compose -f docker-compose.prod.yml build ft-keltner-bounce
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate ft-keltner-bounce

# Verify it came back in the correct state
curl -sf -u $CREDS http://localhost:8095/api/v1/show_config | jq .state
# If "stopped", restart manually:
curl -sf -X POST -u $CREDS http://localhost:8095/api/v1/start

# Verify trades are tracked
curl -sf -u $CREDS http://localhost:8095/api/v1/status | jq 'map({trade_id, pair, profit_pct})'
```

### Pulling new code from git (lower-tier path)

```bash
# On the VPS, in the Dokploy compose dir:
cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code
git pull --ff-only

# Now apply ONLY the changed services. List what changed:
git diff HEAD~1 HEAD --name-only | grep -E "^ft_userdata/" | head

# For each affected service, use the Tier-4 pattern above.
# Do NOT run `docker compose up -d --build` without a service name —
# it will rebuild ALL services and recreate every bot.
```

### Adding a new service (Tier 3, no impact on existing)

```bash
# Compose smart enough to leave existing containers alone for a new service.
# Still safer to be explicit:
docker compose -f docker-compose.prod.yml up -d --no-deps NEW_SERVICE
```

---

## Recovery patterns

### "STATUS process died" alert fired and you didn't expect it
1. `docker ps --filter name=ft-` — confirm container is running again
2. `curl /api/v1/status` for each bot port — confirm open trades preserved
3. `curl /api/v1/show_config | jq .state` — if "stopped", `/start` it
4. Verify equity curve in the dashboard didn't show a phantom gap

### Bot won't start after recreate
1. `docker logs ft-XXX --tail 100` — look for crash reason
2. Common causes:
   - Exchange API key permission error → check `docker exec ft-XXX printenv | grep API`
   - Stale lockfile in `user_data/` → may need to remove on volume
   - Pairlist filter excluding ALL pairs → check `freqtrade test-pairlist` output

### Trade state mismatch after recreate
1. `sqlite3 user_data/tradesv3.dryrun.sqlite "SELECT id, pair, is_open, open_date FROM trades ORDER BY id DESC LIMIT 10"`
2. Cross-check with `/api/v1/status`
3. If divergent, the bot may have lost a fill mid-recreate. For dry-run,
   acceptable. For live, manual reconciliation: cancel orphan exchange
   orders, force-close phantom trades via `/forcesell`.

### Need to roll back a deployment
```bash
git -C /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code log --oneline -5
git -C /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code checkout <PREVIOUS_SHA>
docker compose -f docker-compose.prod.yml build ft-<service>
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate ft-<service>
```

---

## "Imagine live" scenarios

Walk through these every time you propose a change.

### Scenario A — strategy parameter tweak (KeltnerBounceV1 BB width)
- Tier 4
- If a trade is open and the new BB width says "exit immediately," the bot
  will close at market on next candle close, possibly at a loss
- **Mitigation**: only deploy strategy changes during the bot's quietest
  hour (depends on timeframe). For 1h-timeframe bots, deploy mid-candle
  so any decision happens at the NEXT candle close, not mid-flight.
- **Or**: pre-validate the new params against current open positions in a
  scratch backtest before deploying

### Scenario B — adding a new bot
- Tier 3, no risk to existing bots (with --no-deps)
- **But** new bot's stake may conflict with existing bots' wallet allocation
  if all share one funding pool. Currently each bot has its own $200 dry
  wallet, so no conflict.
- **For live**: pre-allocate funded sub-account BEFORE deploying

### Scenario C — Freqtrade base-image upgrade (Tier 4 + Tier 5 hybrid)
- New Freqtrade may change DB schema → migration runs on first start
- Run on ONE bot first (e.g. cascade — lowest trade volume) and watch
  for 24h before promoting to keltner + funding-fade
- Keep the previous image tag pinned so a rollback is `docker tag old new && up`

### Scenario D — Dokploy auto-pull triggers a deploy you didn't want
- Dokploy watches GitHub `vps-deploy` branch and auto-pulls on push
- Auto-pull → `docker compose up -d --build` (broad recreate)
- **Mitigation**: pause Dokploy auto-deploy before pushing dashboard-only
  changes, OR push to a separate branch and merge later, OR accept the
  recreate and confirm bots resume cleanly
- The 2026-05-25 incident was actually triggered by manual `up --build`,
  not Dokploy. But Dokploy auto-pull has the same blast radius if a
  compose-affecting commit lands

### Scenario E — REST credentials rotated
- Old creds invalidate → dashboard polls fail, alerts fire
- **Sequence**: update creds in container env via Dokploy UI → recreate
  via Tier 3 → update dashboard env to match → recreate dashboard via
  Tier 3 → verify both
- Per memory `feedback_freqtrade_creds_via_container_env.md`, always
  pull current creds from `docker exec ... printenv` before assuming
  the value in your terminal history is still valid

---

## What we changed after the 2026-05-25 incident

1. This runbook exists.
2. Memory `feedback_docker_compose_no_deps.md` codified the `--no-deps`
   rule with the specific failure mode.
3. No code changes — the incident was operational, not a code bug.

If you find a NEW pattern that bit you, add it here so the next session
doesn't relearn it the hard way.
