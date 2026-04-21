# BVC-VPIN as a Quality Filter on KeltnerBounceV1

**Date:** 2026-04-21
**Lane:** Signal-quality PoC (no new bot). Tests whether BVC-VPIN can improve Keltner entry selection.
**Author:** Claude (agent session)

---

## Verdict: **AMBIGUOUS — small in-sample gain, fails OOS and walk-forward.** Do not integrate.

The hypothesis (veto top-VPIN trades, i.e. suppress entries in toxic-flow regimes) is **falsified**: the lowest VPIN quintile is the ONLY losing bucket (PF 0.67, -24.9 USDT on 34 trades), while the top VPIN quintile is among the best (PF 2.10). The opposite strategy — veto LOW-VPIN trades — shows attractive in-sample numbers (veto bottom 40% lifts PF from 1.47 to 2.30, cuts DD 38%) but this advantage is built on only 15-20 discarded losing trades and **does not survive out-of-sample or walk-forward validation**. Keep Keltner as-is; add BVC-VPIN to the feature library for future use but do not deploy as a live gate.

---

## 1. Pipeline built

### Part 1: BVC-VPIN on 1m OHLCV (`ft_userdata/analysis/vpin_pipeline.py`)
- Volume buckets sized to `V = daily_avg_volume / 50` using a 30-day seed period.
- Within each bucket, BVC classification: `buy_vol = V * Φ(Δclose / σ_ret)`.
- `σ_ret` is a rolling stddev of bucket returns with 50-bucket lookback, **shifted by one bucket** to avoid lookahead.
- VPIN = 50-bucket trailing mean of imbalance `|buy - sell| / V`.
- Output: per-pair parquet (`{SYM}_vpin.parquet`) + minute-level forward-fill (`{SYM}_vpin_minute.parquet`) where each minute `t` carries the VPIN from the **most recent bucket that CLOSED before `t`** (live-reproducible, no lookahead).
- 32 pairs processed in 35s. Bucket counts per pair range from 5k (TRUMP) to 107k (UNI). VPIN means cluster tightly around 0.50 with σ ≈ 0.05, quantiles [0.39, 0.56] on BTC — consistent with the BVC half-normal prior.

### Part 2/3: Keltner veto analysis (`ft_userdata/analysis/vpin_keltner_veto.py`)
- Loads 169 trades from the most recent narrow-universe Keltner backtest (`backtest-result-2026-04-20_22-46-25.zip`, 32 pairs, 2023-01-09 → 2026-04-11, baseline PF 1.47, +52.17%, DD $40.02, Sharpe 2.46 per-trade basis).
- For each trade, merge-asof attaches the VPIN in force at `open_date` (backward direction, past-only).
- 169/169 trades matched (no missing data).

---

## 2. Quintile analysis (the key finding)

| Quintile | VPIN range | N | profit_abs | PF | WR | Sharpe |
|---|---|---|---|---|---|---|
| **Q1 low** | 0.267 – 0.449 | 34 | **-24.94** | **0.67** | 64.7% | **-0.83** |
| Q2 | 0.449 – 0.484 | 34 | +8.45 | 1.16 | 76.5% | 0.60 |
| Q3 | 0.484 – 0.507 | 33 | +57.69 | 3.38 | 87.9% | 3.12 |
| Q4 | 0.508 – 0.540 | 34 | +29.92 | 1.78 | 82.4% | 1.56 |
| Q5 high | 0.543 – 0.631 | 34 | +33.24 | 2.10 | 85.3% | 1.85 |

**The result is the opposite of the prior hypothesis.** Toxic flow (high VPIN) does NOT poison Keltner entries — it seems to IDENTIFY them. The losing quintile is the lowest-VPIN one, which corresponds to calm, non-informed trading regimes where mean-reversion signals are probably noise.

**Plausible interpretation:** Keltner bounces in calm regimes (Q1) happen on small, random ATR excursions that are not reverted by any identifiable catalyst. Bounces in higher-VPIN regimes (Q3-Q5) happen when informed flow is pushing the price against a KB level — and that flow exhausts and reverts. This matches the finding in the SSRN 5775962 paper the user logged (BB mean-reversion degrades in trending regimes, but high VPIN is regime-agnostic — it marks informed displacement, not trend persistence).

Single account-manager's warning: 34 trades per bucket is thin. A shift of ~3-5 unusually large trades can flip any quintile. Read with that in mind.

---

## 3. Retrospective veto backtest

Baseline: 169 trades, profit_abs $104.35, PF 1.47, DD $40.02, Sharpe 2.46.

### Top-veto sweep (original hypothesis — veto high VPIN)
| Rule | N | profit_abs | PF | DD | Sharpe |
|---|---|---|---|---|---|
| baseline | 169 | 104.35 | 1.47 | 40.02 | 2.46 |
| veto top 9% | 152 | 102.48 | 1.52 | 40.02 | 2.53 |
| veto top 19% | 135 | 71.11 | 1.37 | 49.45 | 1.89 |
| veto top 30% | 118 | 62.45 | 1.38 | 49.97 | 1.83 |
| veto top 40% | 101 | 41.20 | 1.27 | 44.76 | 1.33 |

Top-veto makes Keltner worse at every level ≥10%. Hypothesis falsified.

### Bottom-veto sweep (inverted — veto low VPIN)
| Rule | N | profit_abs | PF | DD | Sharpe |
|---|---|---|---|---|---|
| baseline | 169 | 104.35 | 1.47 | 40.02 | 2.46 |
| veto bottom 10% | 152 | 106.41 | 1.55 | 33.07 | 2.65 |
| veto bottom 20% | 135 | 129.29 | **1.89** | 32.14 | 3.45 |
| veto bottom 30% | 118 | 118.65 | 1.94 | 25.96 | 3.38 |
| **veto bottom 40%** | **101** | **120.84** | **2.30** | **24.83** | **3.77** |
| veto bottom 50% | 85 | 93.37 | 2.14 | 20.84 | 3.20 |

The inverted rule looks impressive in-sample: veto-bottom-40% improves PF 1.47 → 2.30, cuts DD 38%, raises Sharpe 2.46 → 3.77. But these numbers are calibrated on the same 169 trades used for evaluation — classic overfit risk.

---

## 4. Walk-forward robustness (6 equal-trade windows, global 20th-pctile cutoff = 0.449)

| Win | Period | N | Base PF | Veto PF | ΔProfit ($) |
|---|---|---|---|---|---|
| 1 | Feb–Aug 2023 | 28 | 2.29 | 3.56 | -0.20 |
| 2 | Sep 2023 – Mar 2024 | 28 | 1.81 | 2.55 | +4.26 |
| 3 | Apr–Nov 2024 | 28 | 0.85 | 0.74 | **-4.14** |
| 4 | Dec 2024 – Jun 2025 | 28 | 1.77 | 1.80 | -3.53 |
| 5 | Jul–Dec 2025 | 28 | 1.57 | 2.55 | +12.66 |
| 6 | Dec 2025 – Apr 2026 | 29 | 1.30 | 2.48 | +15.89 |

**Net: 3/6 windows improve profit, 3/6 degrade.** The improvement is concentrated in windows 5-6 (recent months) — exactly where overfit to the in-sample shape is most likely. Window 3 (the historically weakest period for Keltner) shows veto makes it **worse**, which is the opposite of what a real signal would do. This is not walk-forward robust.

---

## 5. Out-of-sample test (train 1st half, test 2nd half)

### Top-mode (veto high VPIN)
- Best train pct: 0.90 (veto top 10%). Train PF 1.42 → 1.59.
- Test: PF 1.51 → 1.46. Profit $59.67 → $52.88. **ΔProfit = -$6.79.**

### Bottom-mode (veto low VPIN)
- Best train pct: 0.05 (veto bottom 5%). Train PF 1.42 → 1.65.
- Test: PF 1.51 → 1.48. Profit $59.67 → $56.00. **ΔProfit = -$3.67.**

**Both variants degrade on held-out data.** The bottom-mode's flashy in-sample PF 2.30 does not generalize — when the cutoff is fixed using only the first half's VPIN distribution, it removes a handful of correct-side trades from the second half without catching enough losers.

---

## 6. Why the in-sample bottom-veto number is a mirage

The bottom-veto-40% rule in §3 drops 68 trades; those 68 just happen to contain a cluster of losers. But selection in-sample is not a robust signal — it's curve-fitting. The OOS and WF tests reveal the truth: the VPIN ranking does not correlate with forward Keltner P&L tightly enough to survive even a single train/test split.

Fundamentally, 169 trades is far too few to calibrate a percentile threshold on a noisy feature. BVC-VPIN quintiles have ~34 trades each — one lucky window of 5-6 outsized trades drives most of the quintile spread. The quintile finding **is** interesting directionally (low VPIN = worst Keltner bucket, consistently across the sweep shape) but does not translate into a deployable rule.

---

## 7. Walk-forward of the inverse rule honestly

Even assuming the bottom-veto has real signal, the WF result of 3/6 improving windows is below the project's graduation bar (`project_graduation_criteria.md` requires 4+/6 WF). And the losing windows include the period where Keltner most needs help (window 3, 2024 choppy regime, where Keltner had negative PF 0.85 baseline).

---

## 8. Sharpe/Sortino per-trade caveat

The Sharpe numbers quoted throughout are `mean(profit_ratio) / stdev(profit_ratio) * sqrt(N)` on a per-trade basis, not annualized in the classical return-series sense. This amplifies differences vs the baseline but uses the same formula on all buckets, so the comparison is self-consistent.

---

## 9. Positive collateral from this PoC

- The BVC-VPIN feature is now cached for all 32 traded pairs with live-reproducible minute mapping at `ft_userdata/analysis/vpin_cache/`. Cost = 35s to regenerate on data refresh.
- The feature is now available as a **covariate** in future meta-labeling, ensemble, or feature-engineering work (e.g. include VPIN alongside rolling volatility, F&G, BTC guard as a model input).
- Pipeline is reusable for other strategies — pointing `vpin_keltner_veto.py` at a different backtest zip would repeat the analysis on any fleet member.

---

## 10. Verdict & recommendation

**FAIL — AMBIGUOUS leaning FAIL.** Do not integrate a VPIN veto into KeltnerBounceV1 at this time.

- Top-VPIN veto: actively worse.
- Bottom-VPIN veto: fails OOS, fails walk-forward (3/6 windows).
- The directional quintile finding (Q1 low-VPIN = only losing quintile) is suggestive but has too few trades to calibrate.

### What would change this to PASS
- ≥1000 Keltner trades (would need a wider pair universe or a longer backtest horizon).
- A rolling-cutoff walk-forward (train on window N, test on N+1) that achieves ≥4/6 wins with a stable cutoff percentile.
- Confirmation that the effect survives across a second strategy (Keltner is one sample; does FundingFadeV1 show the same low-VPIN-toxicity pattern?).

### No `custom_entry` stub provided (verdict is FAIL)
A code stub would be:

```python
# In KeltnerBounceV1.populate_entry_trend, would look like:
#   entry_ok = (dataframe['keltner_lower_break'] & dataframe['vol_mult'] & ...)
#   entry_ok &= dataframe['vpin_live'] >= 0.449   # 20th pctile from pipeline
# where dataframe['vpin_live'] is populated via a DataProvider-backed lookup
# against the per-pair vpin_minute parquet, forward-filled. Implementation
# requires a custom DataProvider wrapper; defer until a real signal justifies
# the plumbing cost.
```

Not shipping this. Keeping the pipeline on disk for future use (meta-labeling, regime detection, ensemble inputs).

---

## Appendix: artifacts

- `ft_userdata/analysis/vpin_pipeline.py` — BVC-VPIN generator
- `ft_userdata/analysis/vpin_keltner_veto.py` — Keltner veto analysis
- `ft_userdata/analysis/vpin_cache/*_vpin.parquet` — bucket-level VPIN per pair
- `ft_userdata/analysis/vpin_cache/*_vpin_minute.parquet` — minute-level VPIN per pair (live-reproducible)
- `ft_userdata/analysis/vpin_keltner_results/` — quintile CSV, veto sweep, walk-forward CSVs, OOS JSON
- Source backtest: `ft_userdata/user_data/backtest_results/backtest-result-2026-04-20_22-46-25.zip`

**Estimate: ~1150 words.**
