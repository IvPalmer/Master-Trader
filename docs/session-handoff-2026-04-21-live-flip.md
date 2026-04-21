# Session Handoff — 2026-04-21 Live Flip

## TL;DR
FundingFadeV1 **flipped from dry-run to LIVE** at ~23:35 UTC with $52.10 real
USDT and an IP-whitelisted min-privilege Binance API key. Restart-recovery test
passed cleanly. Zero open trades at flip — first signal will fire on funding
divergence (expected ~2.5/week cadence). Keltner remains dry-run per plan.

## What this session actually did (2026-04-21)

### Phase D artifacts built and committed (commit 4025ed7)
- `ft_userdata/user_data/configs/FundingFadeV1.live.json` — live Freqtrade config
  (dry_run false, stake 15, max_open 2, StaticPairList 19 pairs, BTC/USDT
  blacklisted, SL-on-exchange off, dedicated live DB, explicit 0.1% fees).
- `ft_userdata/docker-compose.yml` — `fundingfadev1` service now reads `../.env`
  and points at the live config.
- `ft_userdata/scripts/preflight_whitelist.py` — per-pair Binance exchangeInfo
  check (status TRADING, SPOT-allowed, minNotional × 1.5, LOT_SIZE, PRICE_FILTER).
  19/19 pass at $15.

### Core bug fixes bundled into the same commit
- **Funding cache bug**: `FundingFadeV1.py` cached funding forever after first
  read. Now keyed by `(mtime_ns, df)` — feather refresh propagates to running
  bot. 12h staleness warning added. No NaN-poisoning on read failure.
- **Funding downloader bugs**:
  - `--end` defaulted to midnight UTC of current day → missed same-day 08:00
    and 16:00 fundings. Fixed to use current UTC time.
  - Added `--incremental` mode (last_ts − 24h) for cheap 4h cron runs.
  - `save_pair` now merges with existing feather before writing — partial API
    page can't truncate history.
  - Atomic write via temp + `os.replace` — bot reading mid-refresh sees
    old-or-new, never half-written.
- **Calibration SL filter**: `engine/calibration.py` previously dropped
  `stoploss_on_exchange` trades from graduation stats, silently undercounting
  live SL losses. Now INCLUDED by default. Opt-out via
  `MT_CALIB_EXCLUDE_SL_ON_EXCHANGE=1`.

### Ops hardening
- `automation_scheduler.sh`:
  - Funding refresh cron every 4h (`download_funding_rates.py --incremental`).
  - Daily 02:00 UTC SQLite `.backup` (WAL-consistent, 14-day rolling retention).
  - Health-report cron now sources `../.env` so rotated creds propagate.
- `api_utils.py`, `metrics_exporter.py`, `strategy_health_report.py`: read local
  Freqtrade API creds from `FREQTRADE__API_SERVER__USERNAME/PASSWORD` env with
  legacy `freqtrader/mastertrader` fallback.
- `.env.example`: extended with `FREQTRADE__EXCHANGE__*` mirror and rotated
  local API / JWT placeholders.
- `docs/live_deployment_checklist.md`: Path 2 recommended / Path 1 fallback;
  Mac-on-phone-hotspot IP test; BNB-fee toggle notes; stoploss docs clarified
  (-5% strategy, -7% operator abort gate); 12h staleness abort trigger;
  restart-recovery test; N=5 sanity pause + event checkpoints + N=10 plumbing
  KPI incl. timeout/cancel rate; N≥30 for statistical triggers; corrected
  panic-runbook compose service name.

### Live flip sequence (tonight)
1. `bash ft_userdata/automation_scheduler.sh` → new crons installed.
2. `docker compose up -d --force-recreate fundingfadev1` → **first attempt
   failed** with `Invalid Api-Key ID`. Root cause: `.env` holds two key
   entries (`BINANCE_*` for check_balance.py and `FREQTRADE__EXCHANGE__*` for
   Freqtrade), user rotated only the BINANCE_ pair after the key leak, leaving
   the Freqtrade entries pointing at the now-deleted leaked key. A small
   sync script copied BINANCE_* values into FREQTRADE__EXCHANGE__* and the
   next recreate booted cleanly.
3. Bot came up → `Bot heartbeat. state='RUNNING'`, `runmode=live`,
   `dry_run=False`, 0 open trades, $52.10 wallet visible.
4. Stop → start cycle → clean reconcile, 0 orphan orders on Binance,
   DB intact, heartbeat resumed.

## Key accepted risks (2026-04-21)

Memory file: `project_live_deployment_accepted_risks.md` under
`~/.claude/projects/-Users-palmer-Work-Dev-master-trader/memory/`.

1. **BTC stays on main Binance account alongside trading key** — blast radius
   under on-host compromise is ~$420, not $50. Sub-account rejected.
2. **IP-whitelist enforcement untested** — phone-hotspot test declined. Scope
   verified via API (IP restriction flag ENABLED), enforcement itself not
   proven from a non-whitelisted IP.
3. **Software-side stop-loss only** for first 30 trades. Gap risk from host
   sleep / Docker wedge / network drop = no exchange-side stop. Compensations:
   ~$30 deployed cap, operator abort gate at -7% above strategy's -5% stop.
4. **No Auto-Invest / manual trades / BNB top-ups** during the 30-trade sample.
5. **BNB fee toggle state unknown** — config at 0.1%; live-vs-backtest drift
   in conservative direction if BNB-for-fees is ON (live fees slightly lower).
6. **Telegram alerts via existing webhook pipe** to claude-assistant bot.
   Interactive Telegram commands (`/status`, `/forceexit`) unavailable.
7. **Mac sleep already disabled** on AC — pmset command from checklist was
   unnecessary and not run.

Plus a new lesson logged: never dump `docker compose config` with live env,
it expands vars inline. Key `...wHzs` was leaked that way, user rotated to
`...oBWZ` before flip.

## State at flip

| Item | Value |
|------|-------|
| Bot | FundingFadeLive (strategy FundingFadeV1) |
| Container | `ft-funding-fade`, healthy |
| Runmode | live, dry_run False |
| Stake / max_open | $15 / 2 slots |
| Whitelist | 19 static pairs, BTC/USDT blacklisted |
| Live DB | `tradesv3.live.FundingFadeV1.sqlite` |
| Wallet at flip | $52.10 USDT + 0.00417 BTC (not bot-managed) |
| API key | `...oBWZ`, IP-restricted, scopes correct |
| Open trades | 0 / 2 |
| Open orders on Binance | 0 |
| Restart-recovery test | PASSED |

## Next session — what I do first

1. `docker ps --filter "name=ft-"` — expect keltnerbouncev1 + funding-fade + monitoring stack.
2. `curl -sS -u "$USER:$PASS" http://localhost:8096/api/v1/status` via creds in `.env` — check for first live trade.
3. If a trade has fired: per-trade reconcile against Binance trade history (fill, fee, exit path), compare slippage vs backtest expectation.
4. Otherwise: watch-mode continues.

## Next session — decisions if trades fire

Following checklist `docs/live_deployment_checklist.md`:
- Event-based checkpoints (first SL, first cancel, first partial fill, first restart-with-open-trade).
- N=5 sanity pause if any anomaly.
- N=10 plumbing checkpoint (slippage median, timeout/cancel rate, fee accuracy, reconciliation).
- N≥30 statistical gates engage.
- Hard stops active from trade #1: single trade > -7%, force-exit, unexpected API error, wallet divergence, funding staleness.

## What's NOT committed this session
- Grafana overlay CSV regeneration (auto-updated daily) — harmless drift.
- `ft_userdata/analysis/vpin_keltner_results/` — stale research artifacts from
  the closed VPIN lane; can be deleted or gitignored next session.

## Files committed in 4025ed7
12 files, +663 / −92:
- `.env.example`
- `docs/live_deployment_checklist.md`
- `ft_userdata/api_utils.py`
- `ft_userdata/automation_scheduler.sh`
- `ft_userdata/docker-compose.yml`
- `ft_userdata/download_funding_rates.py`
- `ft_userdata/engine/calibration.py`
- `ft_userdata/metrics_exporter.py`
- `ft_userdata/scripts/preflight_whitelist.py` (new)
- `ft_userdata/strategy_health_report.py`
- `ft_userdata/user_data/configs/FundingFadeV1.live.json` (new)
- `ft_userdata/user_data/strategies/FundingFadeV1.py`
