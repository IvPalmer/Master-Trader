# Master Trader

Where: `~/Dev/finance/trading/master-trader` on the operator's Mac (district `finance`,
area `trading`); lead `master-trader-lead` (see `## Lead`).

Read docs/STATUS.md first, then `RUNTIME.md` before runtime work.

This repository trades real money. Merging, testing and editing are agent work; live
switches, allocation or key changes, fund movements and deploys are the operator's.

## Repository rules

Read `RUNTIME.md` before runtime work. This checkout is for source edits and
network-free tests; do not start local Docker, databases or application servers.

Read `CONTRIBUTING.md` and `docs/workflows/global-github-policy.md` before changes.
Use an existing issue or create one, work on an issue-linked branch, and submit a
PR. Do not push changes directly to main or vps-deploy. Review actual behavior,
run relevant tests, and record results and remaining limitations in the PR.
Merging does not authorize live deployment or changes to trading allocations.
Preserve the research preregistrations and distinguish paper, live and historical
measurement epochs. Never commit secrets or raw private production data.

Dashboard work (`ft_userdata/ft_dashboard/`) must follow `PRODUCT.md` and `DESIGN.md`
at the repository root. They are authoritative UI policy, not tooling output: planned
targets are not exchange orders, a reported bot stop is not exchange verification,
and missing telemetry or mark-to-market history is never fabricated.

## Shipping

- Work: issue, `claude/<issue>-<description>` or `codex/<issue>-<description>` branch from
  `main`, PR to `main`, review, squash merge.
- Release, only when a rollout is authorized: a PR from `main` to `vps-deploy`. Both
  branches are strict with admin enforcement and drift apart (release merges exist only
  on `vps-deploy`), so `gh pr update-branch` fails. Branch off `origin/vps-deploy`, merge
  `origin/main` into it, check that `git diff origin/main HEAD` is empty, and open that
  branch as the release PR. Never use an admin bypass.
- Dokploy auto-deploy is off for this stack: a merge to `vps-deploy` changes nothing
  running until someone deploys it. Deploys are manual and targeted; follow
  `docs/ops/UPDATING-WITHOUT-BREAKING-BOTS.md` (blast-radius tiers, pre-flight checks,
  recovery).
- Use the smallest tier in the runbook. A Freqtrade JSON config change can be picked up
  with `/reload_config` (the configs directory is mounted read-only, so host edits are
  visible); env, mount, image or strategy code changes need a recreate. On this stack
  always pass `--no-deps` to `docker compose up`: without it Compose recreates sibling
  bots mid-trade. Prefer a flat book before reloading or restarting a copy-trader bot.
- `killers-observer` (systemd user unit) and `trade-webhook` run from the VPS host
  checkout, not from Dokploy; after a release, that checkout is pulled too, or the
  fleet snapshot reports `host_checkout_drift`.
- Never copy files from the Mac into the VPS code paths (`scp`, `rsync`); go through
  GitHub so history stays complete.

## Working rules

- Check a bot's mode (live or dry-run) with its own `/api/v1/show_config`, never from
  docs or memory. REST credentials rotate: read them from the container's environment
  (`FREQTRADE__API_SERVER__*`).
- Agents never place orders, cancel exchange orders, move funds or touch exchange keys.
  Operator scripts such as `scripts/hyperliquid/hl-funds.sh` stay operator-run.
- Backtests always run with `--timeframe-detail 1m`; 1h-only results hide intra-candle
  stops and have shown profits that turned into losses at 1m.
- Calibration and research reproduce the deployed epoch: the live bots run fixed
  `StaticPairList` universes, so use the live pair list, protections and fees as the
  preregistration states. The `<Strategy>Viability.py` wrappers model a dynamic pairlist
  and fit only a bot that runs one.
- Never blacklist a coin after a loss; a universe change is a preregistered decision,
  not a reaction.
- Dry-run configs keep `stoploss_on_exchange: false`: dry-run exchange stops live only in
  memory and vanish on restart.
- Copy-trader bots (Killers, Insiders) are judged on whether the plumbing works, not on
  strategy backtest gates.
- Statistical claims account for multiple testing (deflated Sharpe) after the large
  parameter sweeps. Pre-commitments live in `ft_userdata/preregistrations.json`; change
  one only through a recorded amendment.
- On the VPS, run scratch Python from `~/`, not `/tmp` (a stray module there shadows
  the standard library).

## Tests

Network-free; no exchange access, credentials or Docker. CI runs Python 3.13 and the
suites listed in `.github/workflows/tests.yml`: `tests/`, `services/killers-receiver`,
`ft_userdata/ft_dashboard`, `services/hl-gateway`, `services/trade-webhook`,
`killers_bot/tests`, then the dashboard chart frontend gates
(`ft_userdata/ft_dashboard/frontend`: `npm ci`, `npm run typecheck`, `npm run build`
with a clean `../static/price-chart.js` diff, `npm test`). Setup is in `CONTRIBUTING.md`.

## Lead

`master-trader-lead` (Paperclip) owns this project's roadmap (`docs/ROADMAP.md`) and
reads this file. It plans, reviews evidence and proposes; it does not deploy this stack,
change live modes or allocations, or move money. Those need the operator's explicit
go-ahead every time.
