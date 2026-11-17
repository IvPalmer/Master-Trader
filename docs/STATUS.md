# Status

Public-safe: no keys, balances, account identifiers or positions. Check live state on
the VPS, not here.

## What runs where

- **VPS (production):** the Dokploy compose `master-trader-stack`
  (`ft_userdata/docker-compose.prod.yml`, built from `vps-deploy`, auto-deploy off): the
  Freqtrade bots, `killers-receiver`, `hl-gateway`, `metrics-exporter` (portfolio circuit
  breaker), `prometheus`, `funding-refresh` and `ft-dashboard`. Bot REST ports bind to
  `127.0.0.1`. Live trade databases live in a Docker volume, not in the code checkout.
- **VPS host checkout** (`/home/ubuntu/master-trader`, branch `vps-deploy`):
  `killers-observer` (systemd user unit, the Telegram observer) and `trade-webhook`
  (plain compose; Freqtrade events to the lake and Telegram). Bulk research data and the
  health-report state also live under that folder.
- **Mac** (`~/Dev/finance/trading/master-trader`): source edits and network-free tests
  only. No containers, databases or schedulers run from it.

## Fleet modes (2026-11-11, from each bot's `/api/v1/show_config`)

| Bot | Venue | Mode |
|---|---|---|
| FundingFadeV1 | Binance spot | live |
| KeltnerBounceV1 | Binance spot | live |
| UpbitFadeLiveV1 (pilot, since 2026-11-06) | Hyperliquid futures | live |
| KillersScalpV1 (dry-run since 2026-11-10) | Hyperliquid futures | dry-run |
| ShortKeltnerV2HL | Hyperliquid futures | dry-run |
| OITrendPullbackV1 | Binance spot | dry-run |

Retired: CascadeFaderV1 (2026-07-13), InsidersScalpV2 (2026-10-29). Modes change by
operator decision; re-check `show_config` before relying on this table.

## How to check

- Bot mode and state: `/api/v1/show_config` from inside the bot's container with the
  container's own `FREQTRADE__API_SERVER__*` credentials.
- Fleet totals and per-bot results: the dashboard (`ft-dashboard`), behind the edge login.
- Open work and decisions: `docs/ROADMAP.md` and the GitHub issues and milestones.
