# Live Deployment Checklist — FundingFadeV1 First

> Target: migrate FundingFadeV1 from dry-run to live with small real-money stake.
> Codex thesis: FundingFade is the faster measurement instrument (~2.5 trades/wk vs
> Keltner ~1/wk). Keltner stays dry-run until FundingFade completes 30 live trades.

## Phase A — Key provisioning (user does)

- [ ] Binance API key created with label `master-trader-fundingfade`
- [ ] Scopes enabled: **Habilitar Leitura** + **Ativar Trading Spot e de Margem** ONLY
- [ ] Scopes explicitly DISABLED: Habilitar Saques, Habilitar Futuros, Permitir Transferência Universal, Habilitar Empréstimo/Reembolso/Margem
- [ ] IP whitelist enabled with your actual IP (`curl ifconfig.me` from the bot host)
- [ ] Key + secret pasted into `~/Work/Dev/master-trader/.env` (NOT committed, NOT shared in chat)
- [ ] `.env` is in `.gitignore` (verified)

## Phase B — Pre-flight verification (I run)

- [ ] `python3 ft_userdata/scripts/check_balance.py` succeeds
- [ ] `canWithdraw: False` confirmed in output
- [ ] USDT balance present and matches expected deposit amount
- [ ] No open orders (unless intentional)
- [ ] IP restriction enforced (try from different IP, expect rejection)

## Phase C — Funding

- [ ] Binance spot wallet funded with intended live budget (suggest $50-100 USDT)
- [ ] Consider using a sub-account for extra isolation (optional but recommended)
- [ ] Deposit confirmed via `check_balance.py`

## Phase D — Live config preparation (I do)

- [ ] `ft_userdata/user_data/configs/FundingFadeV1.live.json` created with:
  - `dry_run: false`
  - `dry_run_wallet` removed
  - `stake_amount: 15` (smaller than dry-run's "unlimited")
  - `max_open_trades: 3` (unchanged, but means up to $45 exposed)
  - `stoploss_on_exchange: true`
  - `stoploss_on_exchange_interval: 60`
  - `cancel_open_orders_on_exit: true`
  - `exchange.key` + `exchange.secret` read from env via docker-compose env_file
- [ ] docker-compose.yml `fundingfadev1` service updated:
  - `env_file: - .env`
  - entrypoint points at `FundingFadeV1.live.json`
- [ ] Telegram bot token added for live alerts (new Phase 5 requirement per v2 Gate 4)

## Phase E — First live trade monitoring (user + I)

- [ ] Bot restarted in live mode
- [ ] `check_balance.py` confirms key is in use (balance changes if trade fires)
- [ ] Watch first 3 live trades via Grafana and Binance app:
  - Entry fill vs requested price (slippage measurement)
  - Exit fill vs ROI trigger
  - Any force-exit or stop-loss event
- [ ] Calibration starts ticking: live PnL / PF / DD vs scaled backtest expectation

## Phase F — Abort triggers (automatic)

If any of these fire in the first 30 live trades, stop the bot and investigate:
- [ ] Any single trade >8% loss
- [ ] Drift >30% from backtest expectation
- [ ] DD breaches 1.5× backtest DD (1.5 × 19.6% = 29.4% ceiling)
- [ ] 5 consecutive losses
- [ ] Any force-exit or API error that wasn't expected

## Phase G — Graduation path (v2 gates)

After 30 closed live trades (estimated ~3 months):
- [ ] Gate 1: sample size met
- [ ] Gate 2: live profit within ±25% of scaled expectation, PF within ±20%, DD ≤ 1.5× backtest
- [ ] Gate 3: max single loss ≤ 1.5× backtest worst-trade, consec losses ≤ 5
- [ ] Gate 4: operational checklist complete

If all pass → scale stake $15 → $25 (stage 1 of progressive scaling). Otherwise
pause, investigate, or demote.

## Keltner — STAYS DRY-RUN until FundingFade graduates

Reason: Codex critique — shipping two bots live simultaneously doubles the uncontrolled
variables. Keltner remains a dry-run control reference. If FundingFade graduates, Keltner
gets its own Phase A-G separately.

## DCA sleeve — use Binance auto-invest

Codex recommendation: no Freqtrade bot for DCA. Use Binance's native Auto-Invest feature
for scheduled BTC/ETH buys. Zero model risk, zero bot complexity. Set up separately in
Binance UI after live budget is deposited.
