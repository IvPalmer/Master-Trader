# Session handoff — 2026-05-25

Long session spanning the Killers VIP copy-trader build from zero to first
live dry-run trade, dashboard refactor for per-bot tabs, and an ops
hardening pass (Dokploy auto-deploy off, Tailscale SSH check off, runbook
for safe updates).

## Headline outcomes

1. **Killers VIP copy-trader is live as a real Freqtrade Futures dry-run
   bot in the fleet.** First end-to-end fill: signal `#2143` POL/USDT LONG
   at $0.092, stake $19.98, leverage 5x, currently open.
2. **Dashboard is per-bot.** 7 tabs: live-summary, dry-summary, trades,
   plus a dedicated tab per bot (funding-fade · keltner · cascade ·
   killers). Each per-bot tab has full equity / drawdown / per-pair charts
   + hero tiles + open positions + recent trades. Killers gets a bespoke
   tab too (paper-sim audit + classification feed) because its data shape
   differs from Freqtrade.
3. **Ops never breaks bots on deploy again.** Dokploy auto-deploy OFF for
   `master-trader-stack`; deploys are explicit via SSH+compose using the
   safe `--no-deps --force-recreate` pattern documented in
   `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md`. Tailscale SSH ACL flipped
   from `check` → `accept` so SSH sessions don't trigger browser
   re-auth.

## State at handoff

### Fleet

| Bot | Tier | Status | Last trade |
|-----|------|--------|------------|
| FundingFade | LIVE futures | running, 5d uptime, 17 closed @ +$1.94, 0 open | — |
| Keltner | DRY spot | running, 3 trades open (SOL +0.30%, ETH +0.43%, ADA +0.25%) | 2026-05-24 23:10-23:23 burst |
| Cascade | DRY spot | running, 0 open trades | — |
| Killers (NEW) | DRY futures | running, 1 trade open (POL +0.??%) | 2026-05-25 12:32 (POL #2143) |

### Containers

```
ft-dashboard          Up <1h
ft-cascade-fader      Up 1h
ft-keltner-bounce     Up 1h
ft-funding-fade       Up 5d
ft-killers-scalp      Up <1h (NEW)
killers-receiver      Up <1h (NEW)
ft-metrics-exporter   Up 2w
ft-funding-refresh    Up 2w
ft-prometheus         Up 3w
```

Observer: `killers-observer.service` systemd user unit (linger enabled),
PID stable, ~40 MB.

## What was built this session

### Killers copy-trader, end-to-end

- `killers_bot/` standalone observer (Telethon → Claude CLI classifier →
  paper sim → POST to receiver). Runs on the VPS host under
  `~/.config/systemd/user/killers-observer.service`.
- `services/killers-receiver/` FastAPI executor — maps classified events
  to `/forceenter` / `/forceexit` on the Freqtrade bot. SQLite position
  graph keyed by `(signal_id, symbol)`. Reconcile loop every 60s.
- `ft_userdata/user_data/configs/KillersScalpV1.json` — Freqtrade Futures
  dry-run config, $200 wallet, max 10 concurrent, leverage cap 5x,
  51-pair whitelist covering the channel's actual symbol traffic.
- `ft_userdata/user_data/strategies/KillersScalpV1.py` — pass-through
  strategy (no auto entries/exits; everything driven by REST).
- `ft_userdata/docker-compose.prod.yml` — added `ft-killers-scalp`
  (port 8099) + `killers-receiver` (port 8089).
- `ft_userdata/ft_dashboard/app.py` — added `killers-ft` to the BOTS list
  so it polls + shows up as a regular dry-run card.

### Dashboard refactor

- One tab per bot with live/dry status badge in the nav.
- Live Summary + Dry Summary tabs with aggregate hero tiles + per-bot
  mini cards + fleet equity chart (multi-line, one color per bot).
- Killers integrated into Dry Summary as a per-bot card with classifier
  coverage panel + paper position stats + recent classifications feed.
- Killers detail tab has 3 charts: paper equity curve, per-symbol P&L
  bars, signal arrival rate by hour. Plus a prominent disclaimer
  explaining the paper-sim is NOT plugged to real execution (which is
  now wrong-but-historical — we DID plug it in. Update next session
  to point at the receiver-driven trades.)

### Ops + docs

- `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md` — tier system (T0
  zero-impact → T5 destructive), pre-flight checklist, safe command
  patterns by operation, recovery patterns, "imagine live" scenarios.
- Dokploy auto-deploy disabled in Dokploy postgres
  (`UPDATE compose SET "autoDeploy" = false WHERE "composeId" = 'gajntEdheyjvJKEVuUbbe';`).
  Deploys now explicit via SSH+compose or Dokploy UI button.
- Tailscale ACL flipped from `check` → `accept` via the API
  (`https://api.tailscale.com/api/v2/tailnet/-/acl`). No more
  browser-based SSH re-auth.
- Admin API key stored at `~/.config/tailscale/admin-key` (chmod 600)
  for future ACL edits.

## Codex review findings (all addressed)

Codex reviewed the killers-as-real-bot change. 6 findings:

1. **HIGH** — Receiver crash mid-open could orphan a Freqtrade trade.
   → Fixed via 60s reconcile loop in `services/killers-receiver/app/main.py`.
2. **HIGH** — No idempotency, duplicate event could double-enter.
   → Fixed via `UNIQUE(open_msg_id)` constraint + dedupe return path.
3. **HIGH** — Symbol-only close fallback could close wrong trade.
   → Fixed: fallback fires only when exactly one active position; multiple
     active = "ambiguous" → refuse close (safer than blind close).
4. **HIGH** — Receiver hardcoded auth that would 401 against rotated creds.
   → Fixed: env-driven `${FREQTRADE__API_SERVER__USERNAME/PASSWORD}` in
     compose, matching sibling pattern.
5. **HIGH** — `entry_pricing.price_side: "same"` + market orders = config
   validation error, bot wouldn't start.
   → Fixed: changed to `"other"` (was caught by codex BEFORE we saw the
     actual error in the container log, which then confirmed it).
6. **MEDIUM** — PEPE/1000PEPE alias inconsistency.
   → Fixed: identity aliases removed, 1000* explicit, whitelist
     includes 1000SHIB / 1000FLOKI / 1000BONK.

Plus 2 bugs we found during live testing (not in codex's scope):

- **Telethon `message` vs `text` key** — Telethon dicts use `message` for
  body, observer was reading `text` → empty text → every classify returned
  chat. Fix in `observer.py` (`persist_raw`, `_ingest`) +
  `classifier.py` (`build_prompt`).
- **datetime JSON serialization** — aiohttp `json=` encoder can't serialize
  Telethon `datetime` fields. Fix: pre-serialize with `json.dumps(default=str)`
  and POST as `data=`.

## Memory written / updated

- `feedback_dokploy_auto_deploy_disabled.md` — auto-deploy off + how to
  re-enable + safe deploy pattern.
- `feedback_docker_compose_no_deps.md` — never use bare
  `docker compose up --build SERVICE`; always pass `--no-deps`.
- `reference_ops_runbook.md` — pointer to
  `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md`.
- `reference_tailscale_admin.md` — admin API key location +
  recipe for future ACL edits.
- `reference_eduardo_melo_whatsapp_lid.md` — Eduardo Melo's WA chat is
  under his `@lid` ID, not phone-JID. Memory note from earlier in session.

## Known issues / next steps

### Should fix

- **Killers detail tab disclaimer** is now stale. It says "paper-sim only,
  not plugged to futures" but we DID plug it to dry-run futures via the
  receiver. Update copy to "dry-run futures, $200 virtual wallet, real
  exchange-market fills via Freqtrade." Same tab also still shows the
  paper-sim charts (equity, per-symbol, arrival rate). Decide: keep paper
  as comparison vs Freqtrade results, or remove and replace with
  Freqtrade-driven equivalents.

- **POL trade monitoring.** First real trade open since 12:32 UTC. Watch
  for SL hit (entry $0.092, SL $0.0810) or signaler-published close. Real
  fill prices will eventually drift from channel-published profit %.
  Worth comparing once a few trades complete: receiver-tracked PnL vs
  channel-published PnL. That's the "is the channel actually profitable?"
  ground-truth check we couldn't do with paper-sim.

- **Killers per-bot tab in the dashboard** still uses the SQLite-based
  bespoke renderer. Now that killers is also in the BOTS polling list,
  the standard per-bot tab (matched by `bot.key === 'killers-ft'`) also
  exists. Two views for one bot is confusing — pick one or merge.

### Defer

- **Phase 2 of receiver:** handle `move_sl` (Freqtrade lacks a native
  REST hook; need a custom_stoploss + side-channel signal table).
- **Phase 2 of receiver:** partial-amount close on `close_partial`
  (currently treats all closes as full exits since pct-based amount
  requires fetching trade amount first).

## Commits in this session

```
ffd5bb1 fix(killers_bot): JSON-serialize Telethon datetimes before POST to receiver
f602234 fix(killers_bot): read msg content from Telethon 'message' key, not 'text'
dffa1c5 fix(killers): apply codex review findings before first live signal
9ce8ae1 feat(killers): promote to full Freqtrade Futures dry-run bot
5fa944d feat(dashboard): killers tab gets charts + futures disclaimer
30ef155 feat(dashboard): summary tabs get aggregate hero + fleet equity chart
c4c03ac feat(dashboard): per-bot charts + Live Summary as per-bot list
0e72f58 feat(dashboard): one tab per bot + live/dry summaries
7cc5107 docs(ops): runbook for updating without breaking live bots
0d39ba9 feat(dashboard): killers tab — observer-bot state alongside Freqtrade fleet
be0743d feat(killers_bot): auto-load .env in observer.py
c8be3b8 fix(killers_bot): split classifier binary on whitespace
9d6439d feat(killers_bot): standalone observer-bot
7b27602 feat(insiders-receiver): extend live classifier prompt for Killers format
a99458e feat(insiders): Killers VIP analyzer (signal_id linkage + published PnL)
```

## Watch loop for next session

```bash
# Killers POL trade still open?
ssh ubuntu@100.96.225.124 \
  curl -sf -u "$FT_USER:$FT_PASS" http://localhost:8099/api/v1/status | jq

# Receiver state
ssh ubuntu@100.96.225.124 curl -sf http://127.0.0.1:8089/positions | jq

# Observer log tail
ssh ubuntu@100.96.225.124 tail -f /home/ubuntu/killers-bot/observer.log

# Dashboard
open https://master-trader.grooveops.dev
```

Reconciler runs in receiver every 60s. If the receiver crashes between a
/forceenter and the DB update, the next reconcile cycle will link the
orphan position by matching (pair, side). If Freqtrade closes a trade
without our /forceexit (liquidation, manual), the reconciler marks our
position closed locally within 60s.
