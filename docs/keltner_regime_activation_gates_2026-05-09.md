# KeltnerBounceV1 — Regime Activation Gates

**Date:** 2026-05-09
**Status:** PROPOSED — objective pre-conditions for any Keltner live flip
**Companion to:** `keltner_abort_gate_policy_2026-05-09.md`

---

## Why this exists

KeltnerBounceV1 backtests +51.47% over 3.3 years (Freqtrade native) — but **2 of 6
calendar-half walk-forward windows lose money**, and both losing windows share a
regime profile:

| Window | P&L | PF | DD | Regime |
|---|---|---|---|---|
| 2023-H2 | −5.15% | 0.67 | 12.0% | Sideways chop, no trend, low vol |
| 2024-H2 | −4.39% | 0.73 | 11.0% | Post-ATH alt bleed, BTC-led, high BTC.D |

The current crypto regime (May 2026) is closer to 2024-H2 than to any of the four
profitable windows:
- BTC ~$80–82K, recovering from Feb 2026 −30% deleveraging crash
- BTC trades below the **weekly** SMA50 (resistance overhead), near 200DMA
- Fear & Greed = 47 (Fear, just exited 108-day Fear streak)
- BTC dominance 60.7%, Alt Season Index 37 — Bitcoin Season, alt weakness
- Kaiko Q1 2026: alt liquidity concentrating, slippage on long tail of 15-pair universe elevated

Flipping live INTO the strategy's known weakness regime is structurally bad evidence-
generation: live result will look bad even if the strategy is fine, and look fine even
if it's broken. We need the regime to be one Keltner has historically performed in
before any live flip.

These gates are **objective and pre-committed**. No discretionary call at flip time.

---

## Activation gates (ALL must be met)

| # | Gate | Reading | Source |
|---|---|---|---|
| G1 | BTC closes above daily SMA50 for **14 consecutive days** | Calculated on daily closes from `BTC/USDT` 1d data | `freqtrade backtesting --pairs BTC/USDT --timeframe 1d` or live data |
| G2 | BTC dominance **30-day rolling slope ≤ 0** OR **BTC.D < 60.0%** | TradingView `CRYPTOCAP:BTC.D`, monthly close-on-close slope | Manual TV check or scripted via TV MCP |
| G3 | Alt Season Index **≥ 50** | [blockchaincenter.net/altcoin-season-index](https://www.blockchaincenter.net/en/altcoin-season-index/) | Web fetch |
| G4 | F&G Index **≥ 50** for at least 7 consecutive days | [alternative.me/crypto/fear-and-greed-index](https://alternative.me/crypto/fear-and-greed-index/) | Already cached in `research/fear_greed_history.json` |
| G5 | 30-day clean Keltner dry-run track record from 2026-04-22 | No anomalies vs backtest (PF, exit-reason mix, win rate, pair concentration within 25% of backtest distribution) | `freqtrade /api/v1/profit` + `/performance` |

**ALL FIVE gates must be green for ≥3 consecutive days before the flip.**

---

## Anti-gates (ANY of these blocks the flip)

| # | Anti-gate | Reading |
|---|---|---|
| A1 | BTC weekly close < weekly SMA50 (resistance overhead) | Daily close-of-week comparison |
| A2 | Cumulative dry-run DD > 8% in trailing 30 days | Half of backtest max DD |
| A3 | Any abort-gate policy not committed and operator-acknowledged | See companion doc |
| A4 | FundingFade live deploy in active drawdown >5% | Don't compound concurrent live-bot stress |
| A5 | Less than $50 of redeployable capital available | Don't dilute FundingFade or Keltner allocations |

---

## Current reading (2026-05-09)

| Gate | Status | Notes |
|---|---|---|
| G1 (BTC > daily SMA50, 14d) | ❓ | Need check — BTC near 200DMA, daily SMA50 likely close. Confirm. |
| G2 (BTC.D ≤0 slope OR <60%) | ❌ | BTC.D = 60.7%, breakout regime. FAIL. |
| G3 (Alt Season ≥50) | ❌ | Currently 37. FAIL. |
| G4 (F&G ≥50, 7d) | ❌ | Currently 47, just exited 108-day Fear streak. FAIL. |
| G5 (30-day clean dry-run) | ⏳ | Started 2026-04-22 — earliest met 2026-05-22. PENDING. |

| Anti-gate | Status |
|---|---|
| A1 (BTC < weekly SMA50) | ⚠️ Confirm — likely true given BTC ~$80K, weekly SMA50 ~$82K |
| A2 (DR DD >8%) | ✅ PASS (only 2 trades closed, both winners) |
| A3 (abort policy committed) | ❌ This is the OTHER companion doc — must be committed |
| A4 (FundingFade DD >5%) | ✅ PASS (FF live +7.28%) |
| A5 (capital >$50) | ✅ PASS ($50 freed from FundingShort) |

**3 of 5 activation gates are FAIL today. 1 anti-gate (A3) is FAIL pending policy
commit. Keltner does NOT activate today.**

---

## Re-check cadence

- **Weekly automated check** every Monday — 5-minute task: pull readings, log to docs/
- **Manual check on demand** when user wants to ask "are we live-ready yet?"
- **Auto-flip is forbidden.** Even if all gates green, operator must acknowledge before flip — gates are necessary, not sufficient.

---

## Why these specific gates

- **G1 (BTC > SMA50 daily, 14d):** Aligns with the strategy's own internal regime gate (`btc_sma50`). 14 consecutive days filters out flips/whipsaws.
- **G2 (BTC.D):** Identifies the BTC-led / alt-weakness regime that crushed Keltner in 2024-H2. Below 60% OR a falling slope indicates capital rotating out of BTC into alts — the regime where Keltner's lower-band touches mean-revert reliably.
- **G3 (Alt Season Index):** Independent third-party index. Composite of top-50 alt performance vs BTC over 90 days. Above 50 = "Alt Season," structurally favorable for alt-pair mean reversion.
- **G4 (F&G ≥ 50):** Filters out post-crash Fear regimes where mean reversion gets crushed by continuation breakdowns. Backtest's losing windows had F&G in low 30s.
- **G5 (clean 30-day dry-run):** Final sanity check that live infra (data feeds, exchange API, position-tracker) is behaving as backtest predicts.

---

## What this is NOT

- **Not a market timing system.** These gates do not predict where Keltner will be
  most profitable — they screen for "Keltner's expected normal-functioning regime."
- **Not optional.** Skipping them means flipping into a known weakness window.
- **Not a substitute for the abort-gate policy.** Activation gates filter when to
  start; abort gates govern when to stop.

---

## Sources

- Strategy weakness regimes: `docs/keltner-bounce-v1-validation.md` (Layer 6)
- Current regime snapshot: research agent brief 2026-05-08 (incl. VanEck, Kaiko Q1 2026, Fortune, Robot Wealth references)
- BTC.D / F&G / Alt Season indexes: see G2/G3/G4 source URLs above
