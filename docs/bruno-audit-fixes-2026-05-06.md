# Bruno Audit Fixes — 2026-05-06

External code review (Bruno Queiroz) flagged 5 live-money risks in the
FundingFade live deployment + monitoring stack. Verified and patched 4;
1 accepted as-is.

## Findings + verdicts

| # | Claim | Verdict | Action |
|---|-------|---------|--------|
| 1 | `stoploss_on_exchange: false` in `FundingFadeV1.live.json` — software-side stop only | TRUE but bounded | Accepted — Binance spot doesn't support clean exchange-side stops; max single position $15 |
| 2 | `FundingFadeV1.py` silently runs forever on missing funding feather (one WARNING, then NaN forever, no further alert) | TRUE | Fixed — re-warn at ERROR every 4h |
| 3 | `metrics_exporter.py` portfolio peak in process memory only — restart loses real high-water mark | TRUE | Fixed — persist to `/state/portfolio_peak.json` |
| 4 | `INITIAL_CAPITAL = 550.0` hardcoded while live wallet ≈ $52 — circuit breaker can't fire until wallet near-zero | **TRUE — most critical** | Fixed — derive dynamically from `/show_config` + `/balance` per bot, exclude dry-run |
| 5 | `download_funding_rates.py` silent-fail modes: corrupt feather truncates history; no range/sanity validation | PARTIALLY TRUE | Fixed — bounds check at `±0.0075`, corrupt feather renamed `.CORRUPT` instead of overwritten |

Empty-page-mid-fetch part of #5 was rejected — existing merge logic preserves
old data via `pd.concat` + dedupe, so a partial fetch is not destructive when
the existing feather is healthy.

## Why #4 was the worst

```
old: portfolio_value = 550 + portfolio_pnl
     drawdown threshold = 10% of $550 = $55 loss
     live wallet = $52 → could hit ZERO without firing
```

Plus dry-run Keltner's simulated P&L was mixed into the same number,
diluting the signal further. Combined effect: circuit breaker was decorative
on the only real-money bot in the fleet.

```
new: live_initial_capital = sum(starting_capital for bot in BOTS if not bot.dry_run)
     portfolio_value = live_initial_capital + sum(live_bots_pnl)
     drawdown threshold = 10% of $51.78 = $5.18 loss
```

Verified live: exporter logs `Circuit breaker capital refreshed: 1 live
bots, $51.78 total starting capital`. Threshold gauge reads `$55.06` peak,
`0.01%` drawdown — finally meaningful numbers.

## Files changed

- [ft_userdata/metrics_exporter.py](../ft_userdata/metrics_exporter.py) — biggest rewrite (+216 lines)
  - `fetch_bot_meta()` reads `dry_run` + `starting_capital` per bot
  - `refresh_live_capital()` rebuilds live-bot list every 60 scrapes (~1h)
  - `scrape_all()` returns `(total_pnl, live_pnl)` tuple — total for Prometheus, live-only for breaker
  - `check_circuit_breaker(live_pnl)` operates on live-only math
  - `_load_peak_state()` / `_save_peak_state()` read/write `/state/portfolio_peak.json` atomically
  - `WEBHOOK_URL` defaults to `http://trade-webhook:8088/webhooks/freqtrade` (was Mac `host.docker.internal`)
- [ft_userdata/user_data/strategies/FundingFadeV1.py](../ft_userdata/user_data/strategies/FundingFadeV1.py)
  - `_missing_funding_last_warn` dict tracks per-pair last-warn timestamps
  - First missing-file detection logs ERROR (was WARNING)
  - Re-warns at ERROR every 4h while file remains missing
- [ft_userdata/download_funding_rates.py](../ft_userdata/download_funding_rates.py)
  - `FUNDING_RATE_CAP = 0.0075` — Binance perpetual cap
  - Reject batch on NaN or out-of-range rate (no save, log REJECT)
  - Corrupt-feather path renames file to `.CORRUPT` and aborts save (no longer silently truncates)
- [ft_userdata/docker-compose.yml](../ft_userdata/docker-compose.yml) + VPS `docker-compose.prod.yml`
  - New named volume `ft_exporter_state` mounted at `/state`

## Deployment

VPS containers recreated:
- `ft-metrics-exporter` (new code + volume mount)
- `ft-funding-fade` (new strategy via `docker cp` — strategy lives in named volume, not bind-mounted)
- `ft-funding-refresh` (bind-mount inode-pinned, `up -d --force-recreate` to repoint)

Backups on VPS:
- `/tmp/prod-compose.bak.20260506`
- `ft-funding-fade:/freqtrade/user_data/strategies/FundingFadeV1.py.bak.20260506`

HBAR open trade preserved across FF restart (trade_id 10 visible post-restart).

## What this does NOT fix

- **#1 stoploss_on_exchange=false**: kept as-is. Real risk if VPS dies mid-position; bounded to $15/position. Path forward (later): switch to OCO orders or move FundingFade to Binance USDT-M perps where exchange-side stops work cleanly.
- **Multi-testing risk**: unrelated to this audit but flagged in 2026-04-21 ceiling review — any survivor of the 4940+1092 combo sweep is statistically suspect. This patch does not address that.
- **Funding-feather watchdog at platform level**: re-warning is in-process. A separate cron checking feather mtimes + alerting via trade-webhook would catch the case where the bot itself is hung. Deferred.

## Verification commands

```bash
# Threshold sanity
docker exec ft-metrics-exporter cat /state/portfolio_peak.json

# Live capital detection
docker logs ft-metrics-exporter | grep "Circuit breaker capital refreshed" | tail -1

# Strategy code is the new version
docker exec ft-funding-fade grep _MISSING_REWARN /freqtrade/user_data/strategies/FundingFadeV1.py

# Funding refresh sees new bounds check
docker exec ft-funding-refresh grep FUNDING_RATE_CAP /app/download_funding_rates.py
```
