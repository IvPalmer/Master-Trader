# Bot Graduation Criteria v2 — Dry-Run to Live

> Core principle: live must track the validated backtest, not chase unicorn absolutes.
> Revised 2026-04-20 after v1 proved unreachable — neither Keltner (PF 1.47 backtest)
> nor FundingFade (PF 1.29 backtest) could ever pass v1's PF ≥ 2.0 floor. v1 gated so
> tightly that no realistic bot graduated. v2 replaces absolute-thresholds with
> calibration-match discipline: if the live bot matches its backtest, graduate it.

## Gate 1: Minimum Sample Size

Small samples are noise. Must have enough data to judge.

| Metric | Requirement | Rationale |
|--------|-------------|-----------|
| Closed trades | **≥ 30** | Below ~20, single outlier fakes the win rate. |
| Days running | **≥ 14** | One weekend + one news cycle + multiple micro-regimes. |
| Unique pairs traded | **≥ 5** | Detects per-pair overfitting (v1 required 8 — too restrictive for narrow strategies). |

---

## Gate 2: Calibration Match (NEW — replaces absolute thresholds)

The bot must track its backtest expectation within tolerance. This is the central shift
from v1. We don't demand the bot be a superstar in absolute terms — we demand the bot
is **the bot we validated**.

| Metric | Requirement |
|--------|-------------|
| **Live total profit** | Within **±25%** of scaled backtest expectation (pro-rata trade count) |
| **Live profit factor** | Within **±20%** of backtest PF |
| **Live max drawdown** | **≤ 1.5× backtest max DD**, absolute ceiling 25% |
| **Net P/L** | **> 0** — non-negotiable |

**Scaled expectation formula**: If backtest produced +X% over N trades, then after n live
trades expect ~(n/N) × X% cumulative profit. Tolerance ±25% of that expected value.

Example — Keltner: backtest +52.17% over 169 trades (3.3yr). At 30 live trades the
pro-rata expectation is +9.3%. Tolerance band: +7.0% to +11.6%. Live inside = pass
Gate 2. Live >20% outside = drift — investigate before promotion/demotion.

**Why this is better**: MasterTraderV1 showed live PF 2.36 vs backtest PF 0.50 — a 372%
drift. v1 would have promoted it for the high live PF. v2 detects the drift and refuses:
even upward drift is unrecognized behavior, which breaks in the next regime.

---

## Gate 3: Risk Discipline

Prevents a single bad trade or losing streak from graduating.

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| **Max single loss** | **≤ 1.5× backtest worst-trade** | Adapts to strategy's natural worst-case. |
| **Max consecutive losses** | **≤ 5** | Up from v1's 4, since lower-PF strategies naturally have more runs. |
| **Single trade share of total P/L** | **≤ 30%** | Fragile-if-concentrated detector. |
| **Force / emergency exits** | **0** | Indicates bug, crash, or config error. |

---

## Gate 4: Live Readiness Checklist

Technical prerequisites — unchanged from v1.

- [ ] `stoploss_on_exchange: true`
- [ ] `stoploss_on_exchange_interval: 60`
- [ ] `cancel_open_orders_on_exit: true`
- [ ] API keys configured (key + secret)
- [ ] `dry_run: false`
- [ ] `dry_run_wallet` removed or ignored
- [ ] Wallet funded with allocated USDT
- [ ] `max_open_trades` set so min stake × max trades < wallet
- [ ] Telegram notifications enabled
- [ ] Circuit breaker active (10% portfolio drawdown kills all bots)
- [ ] VPN bypass configured (`extra_hosts` in docker-compose)
- [ ] One manual test trade placed and verified

---

## Post-Graduation: Progressive Stake Scaling

v1 graduated bots direct to target-size stake. v2 scales up in verified increments.

| Stage | Stake | Trigger to next stage |
|-------|-------|-----------------------|
| Graduate | **$50** | 30 live trades passing Gates 2 + 3 |
| Scale 1 | **$100** | +30 more trades passing Gates 2 + 3 |
| Scale 2 | **$250** | +60 more trades passing Gates 2 + 3 |
| Scale 3 | Full allocation | Manual review |

$50 initial instead of v1's $17 minimum — the smaller figure produced near-zero slippage
signal, defeating the purpose of going live. $50 gives meaningful fill data without
material risk.

---

## Demotion Triggers (tighter than v1)

Applied on any LIVE bot at any time:

| Trigger | Action |
|---------|--------|
| Live drift >30% from backtest expectation on any of profit/PF/DD | **Pause**, investigate |
| Any single trade >8% loss | **Pause**, review entry/exit logic |
| DD breaches 1.5× backtest max DD | **Kill** |
| 5 consecutive losses | **Pause**, reassess regime |
| Trailing 20-trade PF <1.2 | **Kill** |
| Profit <-5% of allocated capital | **Kill** |

"Pause" = set bot to `stopbuy` (hold existing positions, no new entries) while investigating.
"Kill" = full stop + demote to dry-run for re-validation.

---

## What changed from v1 (diff summary)

- **Gate 1 pairs**: 8 → 5 (too restrictive for narrow strategies)
- **Gate 2 PF 2.0 floor**: REMOVED. Replaced with ±20% backtest calibration.
- **Gate 2 WR 55% floor**: REMOVED. Win rate varies naturally with exit style; absolute floor penalized high-R:R strategies.
- **Gate 2 Max Loss 5%**: REMOVED. Replaced with "≤1.5× backtest worst-trade" (adapts to strategy).
- **Gate 2 Max DD 15%**: REPLACED with "≤1.5× backtest DD, absolute ceiling 25%".
- **Gate 2 consec losses 4**: 4 → 5.
- **Gate 3**: tightened. Removed rolling-7d and 10-trade WR-stability thresholds (duplicative with calibration gate).
- **Graduation stake**: $17 → $50, progressive scaling added.
- **Demotion**: added drift trigger, added any-trade-8% trigger.

## Fleet status vs v2

Updated 2026-04-20.

| Bot | Trades | Days | Gate 1 | Can pass v2? |
|-----|--------|------|--------|--------------|
| KeltnerBounceV1 | 0 | 3 | fail | Plausible — backtest +52%/PF 1.47/DD 12.9% is achievable calibration target. |
| FundingFadeV1 | 0 | 3 | fail | Plausible — backtest +60%/PF 1.29/DD 19.6% is achievable calibration target. |

Both bots' widened-universe variants were tested and rejected in favor of narrower
validated pair sets (Keltner 18 pairs, FundingFade original). Backtest baselines above
are the ones live performance is measured against.

## v1 archive

v1 criteria (2026-03 through 2026-04-20) required absolute PF ≥ 2.0, WR ≥ 55%, Max Loss
<5%, Max DD <15%, consec losses ≤4. No realistic strategy from the Strategy Lab explorations
passed these simultaneously in backtest. The gate was designed to kill bad bots but
effectively killed graduation itself. v2 preserves risk discipline via calibration-match
and progressive stake scaling instead.
