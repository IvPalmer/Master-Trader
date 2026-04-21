# Live Deployment Checklist — FundingFadeV1 First

> Target: migrate FundingFadeV1 from dry-run to live with small real-money stake.
> Codex thesis: FundingFade is the faster measurement instrument (~2.5 trades/wk vs
> Keltner ~1/wk). Keltner stays dry-run until FundingFade completes 30 live trades.

## Phase A — Isolation + key provisioning (user does) — REQUIRED ORDER

**Blast radius rule (Codex review)**: A trading-scope API key on the main account can
churn ALL spot assets into losses even with withdrawals off. With BTC/BNB/dust in the
same account, the blast radius is ~$400, not $50. Sub-account isolation is MANDATORY.

- [ ] **Create Binance sub-account** specifically for this bot (one sub-account per bot)
- [ ] **Fund sub-account with ONLY the live bot budget** ($50-75 USDT). No BTC, no dust.
      Keep BTC/BNB/etc on the main account, out of the bot's reach.
- [ ] Binance API key created **on the sub-account** with label `master-trader-fundingfade`
- [ ] Scopes enabled: **Habilitar Leitura** + **Ativar Trading Spot e de Margem** ONLY
- [ ] Scopes explicitly DISABLED: Habilitar Saques, Habilitar Futuros, Permitir Transferência Universal, Habilitar Empréstimo/Reembolso/Margem
- [ ] IP whitelist enabled with your actual IP (`curl ifconfig.me` from the bot host)
- [ ] 2FA confirmed active on main Binance account (not verifiable via API)
- [ ] Key + secret pasted into `~/Work/Dev/master-trader/.env` (NOT committed, NOT shared in chat)
- [ ] `.env` is in `.gitignore` (verified)
- [ ] **Rotate local Freqtrade API creds** — current `freqtrader`/`mastertrader` + dev JWT
      secret in config are defaults, unsafe for a host that also holds a trading key.

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

Per Codex review: dynamic pairlist ≠ validated backtest universe. Freeze a static
whitelist for the first 30 trades. Start small, scale conservatively.

- [ ] `ft_userdata/user_data/configs/FundingFadeV1.live.json` created with:
  - `dry_run: false`
  - `dry_run_wallet` removed
  - `stake_amount: 15`
  - `max_open_trades: 2` (down from 3 — until wallet > $75)
  - `stoploss_on_exchange: true`
  - `stoploss_on_exchange_interval: 60`
  - `cancel_open_orders_on_exit: true`
  - **StaticPairList** (replaces VolumePairList for live) — freeze the 19 pairs from
    `backtest-FundingFadeV1.json` so live matches validated universe exactly
  - **Dedicated live DB**: `db_url: sqlite:////freqtrade/user_data/tradesv3.live.FundingFadeV1.sqlite`
  - **Exchange fees explicit**: `"exchange": { "fees": { "taker": 0.001, "maker": 0.001 } }` unless BNB-fee discount is active
  - `exchange.key` + `exchange.secret` read from env via docker-compose env_file
  - New local API creds (replace `freqtrader`/`mastertrader`) + new JWT secret
- [ ] docker-compose.yml `fundingfadev1` service updated:
  - `env_file: - .env`
  - entrypoint points at `FundingFadeV1.live.json`
- [ ] **Telegram bot token + chat_id configured** before flip (Codex: required, not optional)
- [ ] Pre-start validation: `docker run --rm ... show-config` with the live config + env
  to prove the container loads the intended strategy, universe, and keys before
  `trade` is started.
- [ ] **Static whitelist sanity check**: for each pair in the live whitelist, verify
  via `exchangeInfo`:
  - Symbol status == `TRADING`
  - `minNotional` ≤ `stake_amount`
  - Order size passes `LOT_SIZE` stepSize + `PRICE_FILTER` tickSize for current price
- [ ] **Calibration caveat logged**: `engine/calibration.py` filters out
  `stoploss_on_exchange` trades (line ~1088). Live stop-losses will be UNDERCOUNTED
  in graduation stats unless calibration logic is patched. Either patch it or track
  SL-on-exchange trades manually during the first 30.

## Phase E — First live trade monitoring (user + I)

- [ ] Bot restarted in live mode
- [ ] `check_balance.py` confirms key is in use (balance changes if trade fires)
- [ ] Watch first 3 live trades via Grafana and Binance app:
  - Entry fill vs requested price (slippage measurement)
  - Exit fill vs ROI trigger
  - Any force-exit or stop-loss event
- [ ] **Per-trade reconciliation**: each closed trade compared line-by-line to the
  corresponding Binance trade history (exact fill, exact fee, exact stop-loss path).
  Needed because SL-on-exchange trades are excluded from the calibration engine.
- [ ] **Alert on every stop-loss exit** — highest-risk exit class, must not be silent.
- [ ] **Daily wallet reconciliation**: real Binance wallet vs Freqtrade trade log.
  Divergence > $1 without a pending order = investigate.
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
