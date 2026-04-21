# Live Deployment Checklist — FundingFadeV1 First

> Target: migrate FundingFadeV1 from dry-run to live with small real-money stake.
> Codex thesis: FundingFade is the faster measurement instrument (~2.5 trades/wk vs
> Keltner ~1/wk). Keltner stays dry-run until FundingFade completes 30 live trades.

## Phase A — Isolation + key provisioning (user does) — REQUIRED ORDER

**Blast radius — two distinct scenarios:**

1. **Bot-behavior blast radius** ≈ `stake_amount × max_open_trades` + open positions + USDT
   (~$30-50). Freqtrade does NOT spontaneously sell pre-existing BTC; it only trades
   what it bought with stake currency. Bot whitelist constrains the universe.
2. **Leaked-key-from-compromised-Mac blast radius** = **ALL assets on the account the
   key lives on.** IP whitelist stops off-host abuse; it does NOT stop malware or a
   rogue local process. A stolen trading-scope key can place arbitrary spot orders
   against anything on that account — the bot's whitelist is irrelevant to the attacker.

**Implication**: choose the account with the PROPERTY that compromise is survivable.

**Path 2 (Codex-recommended): dedicated sub-account.**
- [ ] Create Binance sub-account labelled `fundingfade-bot` (verify tier allows sub-accounts)
- [ ] Fund sub-account with live bot budget ONLY; BTC stays on main
- [ ] 2FA active on main account

**Path 1 (only if sub-account unavailable): strip main account to bot budget.**
- [ ] Withdraw BTC + BNB + dust to cold wallet / another exchange
- [ ] Main Binance account holds ONLY the live bot budget in USDT
- [ ] No Auto-Invest, no manual trades, no dust conversion, no BNB top-ups during the sample
- [ ] 2FA active on main account (primary security layer under this path)
- [ ] Acknowledge: any new asset deposited or accumulated during the sample re-expands blast radius

**Common to both paths:**
- [ ] Binance API key created on the chosen account with label `master-trader-fundingfade`
- [ ] Scopes enabled: **Habilitar Leitura** + **Ativar Trading Spot e de Margem** ONLY
- [ ] Scopes explicitly DISABLED: Habilitar Saques, Habilitar Futuros, Permitir Transferência Universal, Habilitar Empréstimo/Reembolso/Margem
- [ ] IP whitelist enabled with your actual IP (`curl ifconfig.me` from the bot host)
- [ ] Key + secret pasted into `~/Work/Dev/master-trader/.env` (NOT committed, NOT shared in chat)
- [ ] `.env` is in `.gitignore` (verified)
- [ ] **Rotate local Freqtrade API creds** — replace `freqtrader`/`mastertrader` + dev JWT
      in `FundingFadeV1.live.json` with strong random values. Store new creds in a password
      manager; you'll need them to log into the local Freqtrade UI.
- [ ] Whitelist excludes `BTC/USDT` (or confirm acceptable if Path 1 moved BTC off-exchange)

## Phase B — Pre-flight verification (I run)

- [ ] `python3 ft_userdata/scripts/check_balance.py` succeeds
- [ ] `apiRestrictions.enableWithdrawals: False` confirmed (key-scope flag, not account-level)
- [ ] USDT balance present and matches budget
- [ ] No open orders (unless intentional)
- [ ] Server time drift < ±1s (HMAC signing tolerance)
- [ ] **IP whitelist enforcement verified from the bot's own machine**: tether the Mac
      to a phone hotspot (public IP will differ), rerun `check_balance.py`. Expected:
      HTTP 401 `Invalid API-key, IP, or permissions`. Reverting to home WiFi should work
      again. A phone-browser curl test is NOT equivalent — it can fail for other reasons.
- [ ] **Funding data fresh**: `ls -la ft_userdata/user_data/data/binance/funding/*.feather | tail -5`
      shows mtime within last 24h. If older, run `python3 ft_userdata/download_funding_rates.py`
      and confirm the cron from `automation_scheduler.sh` is installed.

## Phase C — Funding (folds into Phase A above)

- [ ] Live budget deposited into the isolated account (Path 1 main / Path 2 sub) — ONE budget number: **$50 USDT**
- [ ] Deposit confirmed via `check_balance.py`

## Phase D — Live config preparation (I do)

Per Codex review: dynamic pairlist ≠ validated backtest universe. Freeze a static
whitelist for the first 30 trades. Start small, scale conservatively.

- [ ] `ft_userdata/user_data/configs/FundingFadeV1.live.json` created with:
  - `dry_run: false`
  - `dry_run_wallet` removed
  - Budget math: **$50 USDT → `stake_amount: 15`, `max_open_trades: 2`** → $30 deployed + $20 reserve
  - `stoploss_on_exchange: false` — **DELIBERATELY OFF for first 30 trades**.
    Acknowledged experimental risk: gaps from Mac sleep, Docker wedge, network drop,
    or Binance API errors leave no exchange-side stop. Compensation: max deployed is
    ~$30; hard-stop tightened to 7% (below); Mac sleep disabled (Phase D ops below);
    daily SQLite backup. Revisit post-graduation once the SL filter is off.
    Calibration filter was patched this session (`engine/calibration.py`) so that
    `stoploss_on_exchange` trades are now INCLUDED by default; re-enabling SL-on-exchange
    no longer causes silent bleed in graduation stats.
  - `cancel_open_orders_on_exit: true`
  - **StaticPairList** (replaces VolumePairList for live) — freeze the 19 pairs from
    `backtest-FundingFadeV1.json` so live matches validated universe exactly
  - **Dedicated live DB**: `db_url: sqlite:////freqtrade/user_data/tradesv3.live.FundingFadeV1.sqlite`
  - **Fees — pick ONE and commit for entire 30-trade sample** (no mid-sample switch):
    - (a) BNB-fee discount DISABLED on Binance UI + `"fees": { "taker": 0.001, "maker": 0.001 }`
    - (b) BNB-fee discount ENABLED + pre-fund 0.05 BNB (enough for sample) + `"fees": { "taker": 0.00075, "maker": 0.00075 }`
    - **BNB-fee toggle is ACCOUNT-WIDE on Binance, not per-API-key.** Freqtrade
      cannot override it. Verify current state in Binance UI → Account → Fees →
      "Use BNB to pay fees" and set to match the chosen option.
    - Account already has ~0.00834 BNB. If the toggle is on, that BNB will silently
      cover fees until depleted, causing commission-asset flips mid-sample. Decision
      must be explicit.
    - Ambiguous/middle-ground not permitted (commission-asset flip pollutes reconciliation).
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
  - `minNotional × 1.5 ≤ stake_amount` (50% headroom for rounding + price drift)
  - Order size passes `LOT_SIZE` stepSize + `PRICE_FILTER` tickSize for current price
- [ ] **Ops hardening (host-level)**:
  - Disable Mac sleep for bot host: `sudo pmset -a sleep 0 displaysleep 0 disksleep 0`
    (or use `caffeinate -di` wrapped around the docker-compose up) — logged as decision.
  - Daily SQLite backup cron: `cp tradesv3.live.FundingFadeV1.sqlite backups/$(date +%F).sqlite`
- [ ] **Restart-recovery test BEFORE first real trade**:
  1. Start live container. 2. If an open order is sitting, `docker stop` the container.
  3. `docker start` again. 4. Verify: Freqtrade reconciles the open order via
  `/trades` endpoint, no duplicate/orphan orders on Binance, DB state matches exchange.
  Only after this passes → let the bot actually run for real.

## Phase E — First live trade monitoring (user + I)

- [ ] Bot restarted in live mode
- [ ] Watch first 3 live trades via Grafana + Binance app:
  - Entry fill vs requested price (slippage measurement)
  - Exit fill vs ROI trigger
  - Any force-exit or stop-loss event
- [ ] **Per-trade reconciliation**: each closed trade compared line-by-line to the
  Binance trade history (exact fill, exact fee, exact exit path)
- [ ] **Alert on every stop-loss exit** — highest-risk exit class, must not be silent
- [ ] **Daily wallet reconciliation**: real Binance wallet vs Freqtrade trade log.
  Divergence > $1 without a pending order = investigate

### Event-based mini checkpoints (inspect the moment they first occur, no N threshold)
- [ ] First stop-loss exit → confirm it fired at expected pct, no exchange lag
- [ ] First canceled entry (10min limit timeout) → confirm bot re-evaluates cleanly
- [ ] First partial fill → confirm remaining qty handled (cancel or top-up)
- [ ] First container restart with an open trade → confirm reconciliation (same as
      Phase D restart-recovery, but under live conditions)
- [ ] First Binance API error (5xx, rate-limit, maintenance) → confirm retry/backoff sane

### Phase E0 — Sanity pause at N=5
If any event-checkpoint anomaly or an unexpected trade outcome appears in the first 5
trades, stop the bot and investigate before proceeding. Otherwise skip and continue.

### Phase E1 — Plumbing checkpoint at N=10 trades (before stat gates engage)
- [ ] Fill quality: median slippage < 5bps
- [ ] **Timeout / cancel rate KPI**: canceled-entry ratio < 30% of signals. Higher =
      limit-order strategy has a live-vs-backtest execution gap that matters more than slippage.
- [ ] Fee accuracy: actual taker/maker matches the path chosen in Phase D
- [ ] SL path: if any SL fired, it executed on software-side as expected
- [ ] Reconciliation: Binance wallet ↔ Freqtrade DB agree within $0.10
- [ ] No API errors, no force-exits from transient issues

If plumbing is clean → continue to N=30 for statistical gates. Otherwise pause + fix.

## Phase F — Abort triggers

**Hard stops (active from trade #1):**
- [ ] Any single trade **>7% realized loss**. This is the OPERATOR abort gate, set
      above the strategy's own -5% stop. If a trade closes worse than -7%, the
      strategy stop-loss did NOT work as expected (software SL missed due to gap,
      host sleep, network drop, or exchange outage) — halt and investigate.
- [ ] Any force-exit or API error not explicitly expected
- [ ] Stop-loss exit realized outside expected band (strategy stop = -5%, so a
      legitimate SL close should realize around -5% to -5.5%; anything notably worse
      means software SL had a timing gap)
- [ ] Wallet reconciliation divergence > $1 without a pending order
- [ ] Funding-data staleness warning in bot log (> 12h behind)

**Statistical triggers (active from N≥30, not before — PF 1.29 needs more samples):**
- [ ] Drift >30% from backtest expectation
- [ ] DD breaches 1.5× backtest DD (1.5 × 19.6% = 29.4% ceiling)
- [ ] 5 consecutive losses

### Panic runbook (bookmark this)
If something goes obviously wrong:
1. `cd ~/ft_userdata && docker compose stop fundingfadev1` — halts new orders.
   (Compose service name is `fundingfadev1`; container name is `ft-funding-fade`.)
2. Binance UI → API Management → **DELETE** the `master-trader-fundingfade` key
3. Binance UI → Spot → cancel any open orders manually
4. Log incident in `docs/incidents/`, then debug

## Phase G — Graduation path (v2 gates)

After 30 closed live trades (~3 months):
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
