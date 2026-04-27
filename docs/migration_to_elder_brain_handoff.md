# Master Trader → Elder Brain VPS Migration Handoff

**Status as of 2026-04-26 23:58 UTC** — laptop stack running, FundingFade just recovered from 2-day IP-drift outage. Migration not yet started.

This document is for a future session that will execute the migration. Read it cold; don't assume context.

---

## 1. Why we're migrating

- **Single point of failure today:** stack runs on Palmer's MacBook with hotspot/residential ISP. Public IP drifts (`187.89.222.43` → `187.89.223.208` last week) and broke Binance IP whitelist auth → FundingFade crash-looped silently for 50h with $200 of real money on the books. Pure luck the missed signals were flat.
- **Goal:** stable public IP, 24/7 runtime, survives laptop sleep/power events.
- **Target host:** Elder Brain — Oracle Cloud Always-Free ARM (A1.Flex 4 CPU / 24 GB / 200 GB) in `sa-saopaulo-1`. Public IP `159.112.191.120`, tailnet `100.96.225.124`. Ubuntu 24.04. Already runs 7 apps via Dokploy. See `~/Work/Dev/elder-brain/` for full architecture.

---

## 2. What's running on the laptop right now

`docker-compose.yml` lives at `~/ft_userdata/docker-compose.yml` (which is symlinked from `~/Work/Dev/master-trader/ft_userdata/`). 6 active services, all bound to 127.0.0.1:

| Service | Container | Port | Purpose | RAM cap |
|---|---|---|---|---|
| `keltnerbouncev1` | `ft-keltner-bounce` | 8095 | **DRY-RUN** Keltner mean-rev bot | 768M |
| `fundingfadev1` | `ft-funding-fade` | 8096 | **LIVE** funding-fade bot ($200 real money) | 768M |
| `grafana-bridge` | `ft-grafana-bridge` | (internal) | Custom Python candle-data proxy for dashboards | 192M |
| `metrics-exporter` | `ft-metrics-exporter` | 9090 | Prometheus exporter scraping bot REST APIs | 128M |
| `prometheus` | `ft-prometheus` | 9091 | TSDB, 90d retention | 256M |
| `grafana` | `ft-grafana` | 3030 | Dashboards (anonymous admin enabled — tailnet-only) | 384M |

**Total budget:** ~2.5 GB RAM, well under Elder Brain's 24 GB.

Inactive services in compose are commented out (KILLED bots: cluchanix, bollinger-rsi, futures-sniper, supertrend, alligator, gaussian, funding-short, etc.). Don't migrate them.

### Compose-file specifics worth knowing
- `extra_hosts` pins Binance API hostnames to specific IPs (was for VPN bypass on laptop). May not be needed from Oracle São Paulo region. **Test without it first** — if API works clean, drop the block.
- `env_file: ../.env` resolves to `~/Work/Dev/master-trader/.env`. On Elder Brain, mirror the directory structure OR change to inline `./env`.
- Healthcheck uses `curl -sf http://localhost:8080/api/v1/ping` from inside container. Fine portable.
- Staggered `sleep N` entrypoints to avoid Binance 429 on cold-start. Keep them.

---

## 3. State that MUST migrate (lossy if lost)

| Path | Size | Why critical |
|---|---|---|
| `~/Work/Dev/master-trader/.env` | < 1 KB | Binance API key + secret (rotated 2026-04-21), Freqtrade REST creds + JWT secret (rotated 2026-04-22). **chmod 600. Never git.** |
| `~/ft_userdata/user_data/tradesv3.live.FundingFadeV1.sqlite` (+ `-wal`, `-shm`) | < 1 MB | **LIVE trade DB. Real money. 1 closed trade so far (ARB -5.18%).** Loss = real-money trade history gone. |
| `~/ft_userdata/user_data/tradesv3.dryrun.KeltnerBounceV1.sqlite` | < 1 MB | Dry-run history — calibration data for graduation criteria |
| `~/ft_userdata/user_data/data/binance/funding/*.feather` | 3.5 MB | Funding rates for 19 pairs — strategy needs these. Rebuildable via `download_funding_rates.py` but takes ~15min |
| `~/ft_userdata/user_data/configs/{FundingFadeV1.live,KeltnerBounceV1}.json` | < 50 KB | Live config files referencing strategy params, db paths, whitelist |
| `~/ft_userdata/user_data/strategies/{FundingFadeV1,KeltnerBounceV1}.py` | < 50 KB | Strategy code — already in git but verify HEAD matches running container |
| Prometheus volume (`prometheus_data`) | ~100 MB | 90d historical metrics. **Optional** — losing it costs visibility into past month, doesn't break bots. |
| Grafana volume (`grafana_data`) | ~50 MB | Dashboard state. Provisioning can rebuild from `grafana/dashboards/*.json` (in git). **Optional.** |
| `~/ft_userdata/user_data/shared_positions.json` | 4 KB | PositionTracker cross-bot state |
| `~/ft_userdata/user_data/fear_greed_history.json` | 53 KB | F&G snapshot history (rebuildable but slow) |

### State that's REBUILDABLE — don't waste bandwidth migrating
- `user_data/data/binance/*.feather` candle files — **1.7 GB**. Re-download via `freqtrade download-data` (slow but cheap; do this on VPS *before* live cutover so it doesn't block startup).
- `user_data/backtest_results/` — disposable.
- `user_data/hyperopt_results/` — disposable.
- `user_data/logs/` — keep last week for forensic, drop the rest.
- Other `tradesv3.dryrun.*.sqlite` files for retired bots — archive in git LFS or drop.

---

## 4. Secrets inventory (`~/Work/Dev/master-trader/.env`)

```
BINANCE_API_KEY                          (rotated 2026-04-21)
BINANCE_API_SECRET                       (rotated 2026-04-21)
FREQTRADE__EXCHANGE__KEY                 (mirror of above for env-substitution)
FREQTRADE__EXCHANGE__SECRET              (mirror)
FREQTRADE__API_SERVER__USERNAME          (rotated 2026-04-22 — old freqtrader:mastertrader DEAD)
FREQTRADE__API_SERVER__PASSWORD          (rotated 2026-04-22)
FREQTRADE__API_SERVER__JWT_SECRET_KEY    (rotated 2026-04-22)
```

**Binance key permissions (set 2026-04-26):** Read ✓, Spot Trade ✓, Withdrawals OFF, Universal Transfer OFF, Margin Loan OFF, IP whitelist UNRESTRICTED (relaxed during outage fix; **re-tighten to `159.112.191.120` after migration**).

**Recommendation:** rotate Binance key set during migration. Belt-and-suspenders: old key gets revoked the moment we cut over, even if it leaked it's now useless.

**Storage on Elder Brain:** per Elder Brain convention, place at `/home/ubuntu/stack/master-trader/.env`, chmod 600, never git. Or use Dokploy secrets UI (stored in Dokploy's Postgres). Either is fine — Dokploy UI is more discoverable for future-Palmer; raw file matches what compose already expects.

---

## 5. Migration order (do not deviate)

### Phase 0 — Prep (laptop still authoritative)
1. SSH to Elder Brain. Create `/home/ubuntu/stack/master-trader/`.
2. `git clone https://github.com/<repo>/master-trader.git .` into that dir (verify branch — current is `main`, no migration branch yet).
3. Place `.env` at `/home/ubuntu/stack/master-trader/.env`, chmod 600. Mirror compose's `../.env` reference by either keeping the structure or updating compose to `./env`.
4. **Pre-download all candle + funding data on VPS** so the bots boot fast at cutover:
   ```sh
   docker compose run --rm fundingfadev1 download-data \
     --config user_data/configs/FundingFadeV1.live.json \
     --pairs <19 pairs> BTC/USDT --timeframes 1h --timerange 20230101-
   python download_funding_rates.py
   ```
   This is the slow step (~30 min on residential bandwidth, faster on Oracle's network).
5. Verify Docker daemon, compose v2 plugin, ports 8095/8096/9090/9091/3030 free.

### Phase 1 — Cutover window (laptop bots running)
6. Wait for FundingFade `/api/v1/status` to return `[]` (zero open trades). Don't migrate mid-trade. KeltnerBounce can be cut anytime (dry-run).
7. On laptop: `cd ~/ft_userdata && docker compose stop fundingfadev1 keltnerbouncev1`.
8. **SQLite WAL checkpoint** before copying live DB:
   ```sh
   sqlite3 ~/ft_userdata/user_data/tradesv3.live.FundingFadeV1.sqlite \
     "PRAGMA wal_checkpoint(TRUNCATE);"
   ```
9. rsync the critical state to Elder Brain:
   ```sh
   rsync -avz --progress \
     ~/ft_userdata/user_data/tradesv3.live.FundingFadeV1.sqlite* \
     ~/ft_userdata/user_data/tradesv3.dryrun.KeltnerBounceV1.sqlite \
     ~/ft_userdata/user_data/shared_positions.json \
     ~/ft_userdata/user_data/data/binance/funding/ \
     ubuntu@159.112.191.120:/home/ubuntu/stack/master-trader/ft_userdata/user_data/...
   ```
10. On Elder Brain: `docker compose up -d fundingfadev1 keltnerbouncev1 metrics-exporter prometheus grafana grafana-bridge`.
11. Tail logs until both bots heartbeat:
    ```sh
    docker logs -f ft-funding-fade | grep -E "Bot heartbeat|ERROR"
    ```
12. Verify via REST (use container env for creds):
    ```sh
    FF_USER=$(docker exec ft-funding-fade printenv FREQTRADE__API_SERVER__USERNAME)
    FF_PASS=$(docker exec ft-funding-fade printenv FREQTRADE__API_SERVER__PASSWORD)
    curl -s -u "$FF_USER:$FF_PASS" http://localhost:8096/api/v1/profit
    ```
    Match closed_trade_count, profit_all_coin against pre-migration snapshot. Mismatch = abort.

### Phase 2 — Lock down
13. Re-enable Binance IP whitelist: add `159.112.191.120`, save. Test: bot keeps trading. (If using Dokploy egress proxy, double-check egress IP matches host IP.)
14. **Optional:** rotate Binance keys → update `.env` on VPS → `docker compose restart`.
15. Expose Grafana via Traefik with `ipAllowList` middleware restricted to tailnet (`100.64.0.0/10`). Don't expose publicly.
16. Set up Restic backup of `/home/ubuntu/stack/master-trader/ft_userdata/user_data/tradesv3.live.*.sqlite` and `.env` to B2 (Elder Brain has the convention; copy from another app's restic config).

### Phase 3 — Sunset laptop
17. After **48h clean runtime** on Elder Brain (no crashes, expected trade behavior, dashboards green):
    - `cd ~/ft_userdata && docker compose down` on laptop.
    - Keep the directory in place as cold rollback for 30 days.
    - Rebuild laptop's local dev env to talk to VPS instead of localhost (update any scripts referencing `127.0.0.1:8096`).

---

## 6. Rollback plan

- **During cutover (steps 6-12):** if anything fails verification, stop VPS containers, restart laptop containers — they have authoritative DB, no harm done.
- **Post-cutover (steps 13+):** keep laptop's compose untouched for 48h. If VPS fails: stop VPS, rsync VPS DB *back* to laptop, restart laptop bots. Then debug VPS offline.
- **Worst case (DB corruption):** Freqtrade can rebuild dry-run trade history from logs. Live DB has only 1 closed trade — could be manually re-entered if catastrophic. Don't let it come to that.

---

## 7. Networking decisions for Elder Brain

- **Bot REST UIs (8095, 8096):** tailnet-only via Traefik `ipAllowList` middleware. Same pattern Elder Brain already uses for Dokploy admin. Don't expose publicly.
- **Grafana (3030):** same — tailnet-only.
- **Prometheus (9091):** internal, no exposure needed beyond Grafana.
- **Outbound to Binance:** straight from VPS public IP. No VPN needed. The `extra_hosts` Binance IP pinning in compose was a laptop-VPN workaround — try removing it on VPS first.
- **Tailscale:** Elder Brain already enrolled. Palmer's Mac can SSH-tunnel or hit `100.96.225.124:8096` directly via Tailscale.

---

## 8. Observability decisions

**Recommendation: keep all 4 monitoring containers self-contained inside master-trader stack.** Don't try to merge with Elder Brain's planned-but-unbuilt Phase 1 lake snapshot-cron. Self-contained = portable + isolated + no cross-app blast radius.

If at some future point Elder Brain ships a unified Prometheus/Grafana, *then* consider scrapeing the metrics-exporter from Elder Brain's central instance and dropping master-trader's Prom/Graf. Defer.

`grafana-bridge` is a custom Python service that proxies live candle data into Grafana dashboards. It's bot-specific. Don't try to replace with Loki/promtail — different purpose.

---

## 9. Dokploy vs raw SSH — which?

**Open question; recommend raw SSH for this stack.**

- Dokploy's "Compose" support exists but the master-trader stack has 6 services + custom builds (`grafana-bridge` builds from `./grafana-bridge`, `metrics-exporter` builds from `./exporter/Dockerfile`) + extra_hosts + named volumes + envfile relative pathing. Dokploy may abstract some of this in ways that fight back.
- Raw SSH `docker compose up -d` matches what already works on the laptop. Lowest cognitive load.
- Dokploy benefit (auto-domain, build webhooks, dashboard) is small here — bots aren't HTTP services.
- Counter-recommendation: use Dokploy if Palmer wants to stay 100% inside Elder Brain's house style. Trade-off is ~half a day debugging Dokploy quirks.

Decide explicitly in next session before starting Phase 0.

---

## 10. Things NOT to migrate

- **Everything in `~/.claude/projects/...`** — global memory, stays on Mac.
- **Backtest Engine v2 / Strategy Lab** (`ft_userdata/engine/`, `ft_userdata/strategy_lab.py`) — research tools, frozen per the moratorium. Stay on Mac. Bots don't need them at runtime.
- **Hyperopt results / backtest results** — disposable; archive in git LFS if sentimental.
- **Retired-bot configs and DBs** — archive but don't deploy.
- **Any analysis notebooks / Jupyter state.**

---

## 11. Open questions for next session

1. **Dokploy or raw SSH?** (See §9. Recommend raw SSH; confirm before Phase 0.)
2. **Re-enable Binance IP whitelist after migration?** (Recommend yes — `159.112.191.120` only.)
3. **Rotate Binance keys during migration?** (Recommend yes — clean break.)
4. **Tailscale-only Grafana or SSH tunnel?** (Recommend Tailscale-via-Traefik-ipAllowList since Elder Brain has the pattern.)
5. **Restic backup target?** (B2 bucket per Elder Brain convention. Copy config from another Elder Brain app.)
6. **Drop `extra_hosts` Binance IP pinning?** (Test on VPS without it first; should be unnecessary outside the Brazilian-VPN context.)
7. **Where do we put the .env?** (`/home/ubuntu/stack/master-trader/.env` chmod 600 — matches compose. Or Dokploy UI if going that route.)

---

## 12. Reference: how to reach the running bots in any future session

```sh
# Both bots (works whether on laptop or Elder Brain — same commands)
KB_USER=$(docker exec ft-keltner-bounce printenv FREQTRADE__API_SERVER__USERNAME 2>/dev/null || echo freqtrader)
KB_PASS=$(docker exec ft-keltner-bounce printenv FREQTRADE__API_SERVER__PASSWORD 2>/dev/null || echo mastertrader)
FF_USER=$(docker exec ft-funding-fade printenv FREQTRADE__API_SERVER__USERNAME)
FF_PASS=$(docker exec ft-funding-fade printenv FREQTRADE__API_SERVER__PASSWORD)

curl -s -u "$KB_USER:$KB_PASS" http://localhost:8095/api/v1/profit | jq .
curl -s -u "$FF_USER:$FF_PASS" http://localhost:8096/api/v1/profit | jq .
curl -s -u "$FF_USER:$FF_PASS" http://localhost:8096/api/v1/status | jq .   # open trades
```

After migration, replace `localhost` with `100.96.225.124` (Elder Brain tailnet IP) when running from Mac.

---

## 13. Pointers to deeper context (don't re-read unless needed)

- Architecture, fleet status, accepted risks — `~/.claude/projects/-Users-palmer-Work-Dev-master-trader/memory/MEMORY.md`
- Live deployment risk acceptance — `memory/project_live_deployment_accepted_risks.md`
- This week's outage post-mortem — `memory/project_funding_fade_outage_2026-04-24.md`
- Why bot-on-laptop is the bigger problem — `memory/feedback_bot_on_laptop_risk.md`
- Cred-rotation gotcha — `memory/feedback_freqtrade_creds_via_container_env.md`
- Elder Brain architecture — `~/Work/Dev/elder-brain/` (read its own README + docs)
- Stable session checkpoint — `docs/session-handoff-2026-04-18-stable-checkpoint.md`

---

**End of handoff. Next session: read this top to bottom, answer §11 questions explicitly with Palmer, then start Phase 0.**
