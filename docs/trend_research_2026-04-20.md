# Trend-Following Research — 2026-04-20

## Verdict: **FAIL — RETIRE LONG TREND LANE**

1092-combo grid + targeted refinement: **zero** trend signals pass +20% / PF 1.3 / year-consistency on 3.3yr of 1m-detail data across 32 pairs. Best candidate (donch100+adx20+btc_sma200+roi_only) gets +18.91% / PF 1.02 / DD 42.1% — half the P&L bar, bottom-rail PF, triple the DD cap. Every year-split shows single-year regime luck, same pattern as killed Supertrend/BearRegime/FundingShort.

Do not deploy a 3rd bot. $200 stays HOLD. Trend lane closed alongside the short lane.

---

## Hypothesis chosen

**H1 — Donchian breakout with volume + BTC alignment** plus **H2 — EMA ribbon + ADX** (lab tests both nearly free, so I ran them jointly). Rejected: H3 Supertrend retest (already killed 3 configs), H4 sector-rotation (no infrastructure).

## Methodology

- **Grid**: 13 trend anchors (donch 20/30/55/100, ema 9/21, 12/26, 5/21, 21/55, st 3-10/5-14, macd, ichi, vwap) × 7 confirmations (vol 1.5/2.0, adx 20/25, combos) × 4 BTC gates × 3 exits = **1092 combos**, 1m-detail, 32 pairs, Jan 2023 – Apr 2026, wallet $200, max_open 3. Script: `ft_userdata/grid_scan_trend.py` (807s runtime).
- **Year-split** top-4 candidates: `ft_userdata/trend_year_split.py`.
- **Refinement** on 16 top-cap majors with stricter gates (rsi40, nc48) + tighter Donchian: `ft_userdata/trend_refine.py`.
- Raw logs preserved: `docs/research_artifacts/trend_{scan,years,refine}_20260420.log`.
- **No Freqtrade-native or Viability-wrapper run**: no combo survived year-split, so calibration would validate a failed strategy (same rule as short_research).

## Results

### Top-5 by raw P&L% (3.3yr aggregate)

| Entry | Gate | Exit | Trd | WR | PF | P&L | DD |
|---|---|---|---|---|---|---|---|
| donch(100)+adx(20) | sma200 | roi_only | 1190 | 58.6% | 1.02 | **+18.91%** | 42.1% |
| ema(12,26)+vol(2.0) | sma50+200 | roi_only | 507 | 61.1% | 1.05 | +15.59% | 36.0% |
| ema(21,55)+adx(25)+vol(1.5) | sma200 | wide | 210 | 67.6% | **1.12** | +14.67% | 28.1% |
| donch(100)+adx(20) | sma50+200 | roi_only | 1119 | 58.4% | 1.02 | +12.79% | 51.3% |
| ema(21,55)+adx(25)+vol(1.5) | sma50+200 | wide | 192 | 67.2% | 1.11 | +11.93% | 34.5% |

Best PF = 1.12 (210 trades, marginal sample). Nothing near 1.3. Nothing clears +20%. Supertrend variants actually top the score-by-trade-count chart with -50% to -200% P&L — a reminder that trade-volume scoring lies.

### Year-split (the honesty check)

| Candidate | 2023 | 2024 | 2025 | 2026YTD |
|---|---|---|---|---|
| donch(100)+adx(20) | -2.5% | **+32.3%** | +0.7% | -8.6% |
| ema(12,26)+vol(2.0) | **-18.9%** | +25.8% | -4.5% | +13.2% |
| ema(21,55)+adx(25)+vol(1.5) | **+31.2%** | +1.5% | **-19.0%** | +1.0% |
| ema(21,55)+adx(20)+vol(1.5) | +3.8% | +7.4% | -8.5% | +8.4% |

Every candidate has 1-2 losing years. Single-year regime luck, same signature as Supertrend/MasterTrader/FundingShort/BearRegime.

### Refinement (top-cap majors, stricter gates)

All 6 refined configs got worse or stayed flat. Best refined: ema(21,55)+adx(25)+vol(1.5) / sma50+sma200+rsi40 — 141 trades, +8.35% / PF 1.10, but 2025 = -14.9% / DD 18.2%. Stricter gates reduced trade count without improving win rate — the signal is structurally weak, not undertuned.

## Why trend-following fails here

1. **Entry lateness.** donch100 + BTC-trend gate fires after 10-20% of the move is already done. Crypto trends are short and explosive; what's left is mean-reversion chop that bleeds into ROI exits.
2. **2025 chop regime.** BTC tapped SMA200 from below multiple times in H1 2025, each time triggering long entries into V-reversals (same mechanism that killed BearRegime in reverse).
3. **Volume/ADX are coincident, not predictive.** Both peak AT the top of moves.
4. **Alt correlation-1.0 on drawdowns.** BTC gate lags collapse by 1-4 bars — portfolio DD explodes beyond 15% cap.
5. **Keltner + FundingFade isn't taste — it's what survives.** Crypto return distribution (high kurtosis, short trends) favors mean reversion at local extremes over breakout capture.

## What was NOT tested (honestly)

- Native Freqtrade validation + Viability calibration — no signal to validate.
- Hyperopt — would overfit the single winning year (2024 for donch, 2023 for ema21/55).
- 4h/1d timeframes or donch 200/365 — FundingFade already fills the slow-signal slot.
- Sector rotation (DOGE/PEPE leadership) — needs new feature pipeline, deferred.

## Recommendation

- **No 3rd bot deployed.** Fleet stays at Keltner + FundingFade ($400 dry-run).
- **$200 stays HOLD.** Stable-checkpoint rule enforced.
- **Close trend lane.** Second validated-negative report in 3 days after short lane. The gap is real but cannot be closed with TA on this universe/timescale.
- **Keep artifacts** (`grid_scan_trend.py`, `trend_year_split.py`, `trend_refine.py`, logs) for forensic reference.
- **Update MEMORY.md**: fleet is deliberately 100% mean-reversion + BTC-bullish-gated because that's what empirically survives 3.3yr of 1m-detail crypto data. Accepting the trend-capture gap is the correct action.

A validated NO, as closed as the short lane. The research lanes for "add a 3rd bot on this data" are exhausted.
