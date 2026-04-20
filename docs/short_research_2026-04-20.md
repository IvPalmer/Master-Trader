# Short-Side Research — 2026-04-20

## Verdict: **FAIL — RETIRE**

Regime-gated Turtle-style short passes aggregate headline numbers (+19.67% / 3.3yr / PF 1.10) but year-by-year shows **3/4 years losing** and 2025 gave back 39% of account. Same failure pattern as FundingShortV1: one great year carrying three losing years. Not deployable. Short coverage is deferred indefinitely — capital stays on hold.

---

## Hypothesis chosen

**H1 — Regime-gated momentum short** (from memory's deferred research lane).

Rationale: prior shorts (FundingShort, BearCrash) died because signals fired across the 77% of time BTC is NOT in confirmed bear. A signal that is dormant 77% of the time and only fires on strict regime + acceleration should avoid the choppy-rally grind.

Pre-flight sanity: contiguous BTC bear windows (6-bar confirmed, >=2d) from Jan 2023 -> Apr 2026 yielded **25/25 profitable BTC shorts, avg +4.11% per window, +102.8% cumulative**. So the theoretical edge exists in the bear windows themselves. The question is whether per-pair signals can capture it without bleeding in bear-flicker periods.

## Signal definition

Strategy: `BearRegimeShortV1` (futures, 2x leverage, $100 stake / $200 wallet, max 2 concurrent).

**Regime gate** (BTC 1h, required for all entries):
- `close < SMA50` AND `close < SMA200` AND `20-day momentum < 0`
- 6-bar smoothing: gate active only when above is true for 6 consecutive 1h bars
- AND BTC making a fresh 7-day low (within 2% of 168h-low) — filters sideways bear-flicker

**Pair entry**:
- `close < Donchian low (5d)` — Turtle breakout
- `close < SMA50`
- `volume > 1.2 x vol_SMA20`
- `ADX > 20` AND `-DI > +DI`
- Anti-squeeze: BTC RSI > 25

**Exit**:
- BTC closes back above SMA50 (regime flip)
- OR pair RSI < 28 (oversold bounce risk)
- OR 2-bar `+DI > -DI` confirmation
- ROI tiered (6% / 4% / 2.5% / 1.5% over 0-24h), break-even at 36h
- SL -5%, no trailing, hard time exit at 36h

Viability wrapper created with futures pairlist filters (20M min volume, vol 2-50%, range 2-40%) and F&G > 15 anti-capitulation gate. F&G wrapper was NOT used in the failing test — raw backtest only, so wrapper cannot save these numbers (it can only further restrict entries).

## Results

Full 3.3yr backtest, 20 futures pairs, Jan 11 2023 -> Apr 11 2026, `max_open=2`.

| Window | Mode | Trades | Profit | PF | WR | DD | Verdict |
|---|---|---|---|---|---|---|---|
| Full 3.3yr | 1h only | 198 | +19.67% | 1.10 | 54.0% | 28.17% | borderline |
| 2023 | 1h | 21 | **-6.58%** | 0.71 | — | 10.2% | FAIL |
| 2024 | 1h | 47 | +31.25% | 1.86 | — | 9.4% | PASS |
| 2024 | 1m-detail | 45 | +26.18% | 1.74 | — | 7.2% | PASS |
| 2025 | 1h | 93 | **-19.63%** | 0.82 | — | 39.1% | FAIL |
| 2025 | 1m-detail | 91 | **-15.91%** | 0.85 | — | 37.4% | FAIL |
| 2026 YTD | 1h | 17 | -0.79% | 0.96 | — | 9.4% | FAIL |

**Walk-forward analog**: 1/4 calendar years profitable. Bar requires 6+/6 — strategy scores effectively 1/4. Fails hard.

**1m-detail sanity**: run on the two pivotal years (2024 winner, 2025 loser). Both moved in the same direction as 1h (2024 still wins modestly less, 2025 still loses modestly less). So the 1h signal is not a mirage at 1m resolution — the edge is real in 2024, the bleed is real in 2025. The problem is regime sensitivity, not simulation fidelity.

**Drawdown**: 28% over 3.3yr headline, 39% in 2025 alone. Portfolio DD target is 15%. Fails.

## Why it failed

1. **2024 carries the sample**. +31% in one year, everything else negative. This is textbook single-year regime luck — same as Supertrend, MasterTraderV1, FundingShortV1.
2. **2025 was a "stairstep-down then V-bounce" year**. Fresh 7d lows on BTC (the entry gate) kept firing through Feb-Mar, but each local low was followed by aggressive recovery. Shorts entered at confirmed bear-acceleration, hit ROI 6% only rarely, then got stopped out on snap rallies.
3. **The June-Sept 2025 DD (71 days, -86 USDT)** is directly the +100% drawdown window visible in equity curve. Bear regime kept re-activating every time BTC tapped SMA50 from below during the summer chop.
4. **Crypto's persistent upward drift** means even "confirmed bear + fresh low" shorts have negative long-run expectancy because exits (regime flip, oversold RSI, DI flip) come cheap while entries happen at local-low prices that are about to mean-revert.

## What I did NOT test (honestly)

- **Calibration vs. live**: not run; the strategy failed year-by-year before reaching that step. No point calibrating a strategy that loses 3/4 years.
- **Hyperopt**: skipped deliberately. Hyperopting on the 3.3yr data that includes 2024 would just curve-fit to 2024 — adds survivorship bias, doesn't fix the regime problem.
- **Hypotheses 2 + 3**: not pursued. Hypothesis 2 (VPIN/OFI) requires orderbook data we don't have locally. Hypothesis 3 (funding-extreme fade short) was the core FundingShortV1 thesis which was already killed.
- **Pair-level filtering**: only 20 pairs tested uniformly. Could cherry-pick best pairs from 2024 to boost numbers, but that IS curve-fit to a single year.

## What remains valid

- The **BTC-bear-regime-window level observation** (25/25 windows profitable on BTC) stands. A short that perfectly surfs only BTC would have +100%. The problem is translating to a per-pair signal that doesn't bleed between regimes.
- **Takeaway for future attempts**: any short strategy must pass year-by-year, not just aggregate. FundingShort, BearCrash, and now BearRegime all looked fine in aggregate but died in year-split. Make year-consistency the first gate, not the last.

## Recommendation

- **Retire BearRegimeShortV1**. Do not deploy.
- **Leave files in repo** (`user_data/strategies/BearRegimeShortV1*.py`, `user_data/configs/backtest-BearRegimeShortV1.json`) for future forensic reference, same convention as prior killed shorts.
- **Short coverage remains absent** in the fleet. Fleet stays long-only (Keltner + FundingFade).
- **$200 freed from FundingShort stays HOLD**. Stable-checkpoint rule reinforced: no new bots without year-by-year validation ahead of aggregate.
- **Deferred shorts indefinitely**. Hypotheses 2 (OFI/VPIN) and 3 (funding fade short) would each need new data infrastructure or would just repeat FundingShort's thesis. Not worth the time.

This is a validated NO. As useful as a validated YES — it closes the short-side research lane cleanly.
