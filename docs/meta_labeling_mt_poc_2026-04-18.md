# Meta-Labeling PoC — MasterTraderV1 resurrection attempt

**Date**: 2026-04-18
**Verdict**: **FAIL**. Meta-labeling cannot rescue MasterTraderV1.

---

## TL;DR

A LightGBM meta-labeler trained on 17 regime features across 573 MT trades
(3.1 years) failed to identify any filter threshold that produces a positive
edge on the held-out test set. Best test AUC = **0.535** (essentially
random). No threshold produced PF > 0.6 on the test set. Quarterly analysis
reveals MT is not a genuine regime-dependent strategy — **only 1 of 14
calendar quarters** (2026-Q2, 8 trades) showed PF > 1.1, and that quarter
coincides with the live dry-run "superstar" period used to justify the
resurrection hypothesis. The apparent live edge was most likely sampling
luck inside a single month, not a latent regime-specific alpha that a
classifier could recover.

**Recommendation**: Leave MT retired. Do not redeploy with a meta-labeler.
The $200 freed from FundingShortV1 should go to orthogonal Phase-3 work
(DSR filter, delta-neutral FundingFade, microstructure features), not MT
resurrection.

---

## 1. Dataset

- **Source**: Freqtrade backtest of `MasterTraderV1` (primary model, default
  hyperoptable params) over `20230301-20260411` with 20-pair whitelist,
  $1000 wallet, 10% stake, `max_open_trades=10`, 1h timeframe,
  `StaticPairList`. Backtest zip:
  `/Users/palmer/ft_userdata/user_data/backtest_results/backtest-result-2026-04-18_21-27-27.zip`.
  Raw backtest: **573 trades, PF 0.53, -17.36%, max DD 18.62%**.
- **Trades file**: `ft_userdata/meta_labeling/trades.parquet` (573 rows).
- **Features file**: `ft_userdata/meta_labeling/features.parquet` (573 rows,
  17 features + pair + open_date + label).
- **Features engineered at entry time (no look-ahead, t-1h candle close)**:
  - BTC: `sma20_slope`, `sma50_slope`, `sma200_slope`, `rsi14`, `atr_pct`,
    `pos_vs_sma50`, `pos_vs_sma200`, `rv_24h`, `rv_percentile_30d`.
  - Pair: `atr_pct`, `adx14`, `rsi14`, `above_sma50`.
  - Market breadth: fraction of 20 pairs above their own SMA50.
  - Sentiment: Fear & Greed index (cached historical, 2989 daily values).
  - Calendar: `hour`, `dow`.
- **Label**: `profit_ratio > 0` (binary). Win rate: 43.1%.
- **Chronological split**:
  - Train: 276 trades (< 2024-07-01, win rate 41.3%)
  - Val:   173 trades (2024-07-01 → 2025-07-01, win rate 44.5%)
  - Test:  124 trades (≥ 2025-07-01, win rate 44.4%)
- Zero NaN values in feature matrix.

## 2. Model

- **Primary**: LightGBM `LGBMClassifier` — `n_estimators=300`, `lr=0.03`,
  `num_leaves=15`, `max_depth=5`, `min_child_samples=10`, `subsample=0.8`,
  `colsample_bytree=0.8`, `reg_lambda=1.0`, `class_weight=balanced`,
  early stopping on val at 30 rounds.
- **Sanity fallback**: sklearn `RandomForestClassifier`
  (`n_estimators=400`, `max_depth=6`, `min_samples_leaf=10`,
  `class_weight=balanced`).

### AUCs

| Model | Val AUC | Test AUC |
|---|---|---|
| LGBM | 0.527 | **0.535** |
| RF   | 0.491 | 0.482 |

Val AUC ≈ test AUC ≈ 0.5 (random). LGBM gets a marginal 0.035 lift on test
— within statistical noise for n=124. No out-of-sample predictive signal.

### Top feature importance (LGBM)

```
btc_sma20_slope        8
pair_atr_pct           8
pair_rsi14             6
btc_rv_24h             5
breadth_above_sma50    5
dow                    5
btc_sma50_slope        4
pair_adx14             3
fng                    3
```

No feature dominates; importance is diffuse, consistent with a weak signal.

## 3. Threshold sweep (LightGBM, test set, n=124)

| threshold | trades | win rate | PF    | total return | max DD  |
|-----------|-------:|---------:|------:|-------------:|--------:|
| raw       | 124    | 0.444    | 0.433 | -10.5%       | -13.6%  |
| 0.40      | 124    | 0.444    | 0.433 | -10.5%       | -13.6%  |
| 0.45      | 124    | 0.444    | 0.433 | -10.5%       | -13.6%  |
| 0.50      |  67    | 0.493    | 0.506 |  -5.4%       |  -8.1%  |
| 0.55      |   0    |   —      |   —   |    0         |    0    |
| ≥0.60     |   0    |   —      |   —   |    0         |    0    |

LGBM probabilities cap at ~0.55 (class-balanced calibration) — above 0.55
nothing remains to trade. Best filter (thr=0.5) improves PF from 0.43 to
0.51 and halves drawdown — but is still a losing configuration.

## 3b. Robustness sweep

Six alternative configurations tried in `04_robustness.py`:

| Config                                   | Test AUC | Best thr | n  | PF   | Return  | DD    |
|------------------------------------------|---------:|---------:|---:|-----:|--------:|------:|
| raw label, no class_weight               |   0.526  |   0.40   | 93 | 0.46 |  -7.9%  | -10.7%|
| raw label, balanced                      |   0.535  |   0.50   | 67 | 0.51 |  -5.4%  |  -8.1%|
| strict label (pr>0.01), no cw            |   0.520  |   0.36   | 74 | 0.57 |  -4.6%  |  -7.2%|
| strict label, balanced                   |   0.433  |   —      |  — |   —  |    —    |   —   |
| alt split (wider test 2025-2026)         |   0.544  |   0.30   |196 | 0.48 | -13.7%  | -15.6%|
| sample_weight=|profit_ratio|            |   0.434  |   —      |  — |   —  |    —    |   —   |

**No configuration crosses PF = 1.0, let alone the PF > 1.3 pass threshold.**
Best PF achieved anywhere is 0.57. Meta-labeling cannot flip MT's sign.

## 4. Why it failed — quarterly MT performance

| Quarter | n  | Win rate | PF    | Mean return |
|---------|---:|---------:|------:|------------:|
| 2023-Q1 | 15 | 0.40     | 0.56  | -0.58%      |
| 2023-Q2 | 43 | 0.44     | 0.73  | -0.28%      |
| 2023-Q3 | 46 | 0.22     | 0.24  | -1.07%      |
| 2023-Q4 | 54 | 0.52     | 0.61  | -0.52%      |
| 2024-Q1 | 71 | 0.41     | 0.69  | -0.33%      |
| 2024-Q2 | 47 | 0.47     | 0.92  | -0.07%      |
| 2024-Q3 | 65 | 0.48     | 0.62  | -0.42%      |
| 2024-Q4 | 36 | 0.39     | 0.35  | -1.37%      |
| 2025-Q1 | 26 | 0.50     | 0.51  | -0.68%      |
| 2025-Q2 | 46 | 0.43     | 0.63  | -0.41%      |
| 2025-Q3 | 45 | 0.49     | 0.56  | -0.62%      |
| 2025-Q4 | 40 | 0.25     | 0.13  | -2.07%      |
| 2026-Q1 | 31 | 0.52     | 0.80  | -0.22%      |
| **2026-Q2** |  **8** | **0.88** | **5.23** | **+0.96%** |

**Only one profitable quarter out of 14, containing only 8 trades**. That
quarter is 2026-Q2 — the live dry-run "superstar" period that triggered the
resurrection hypothesis in the first place.

### Regime separation is real but unexploitable

The winning-quarter trades DO differ from losing-quarter trades in a few
features (z-score differences):

- **FNG**: mean 13.8 vs 59.8 (z = **-2.5**) — winners occur in extreme fear.
- **pair_rsi14**: 64.4 vs 60.3 (z = +1.0)
- **btc_rsi14**: 70.3 vs 62.0 (z = +0.9)
- **btc_sma200_slope**: -0.02 vs +0.03 (z = -0.8)

Interpretation: MT's "edge" appears when FNG is deeply negative, BTC has
just started recovering (high RSI after falling SMA200 slope), and pairs
are extended (RSI ~64). In other words — **V-bottom rebounds after a crash**.

BUT: this profile occurred **only in 2026-Q2**. The training data
(2023-2024) does not contain a comparable FNG-under-15 regime with 8+ MT
entries. The meta-labeler literally has nothing to learn from — the
"winning regime" is out-of-sample to the training set.

## 5. Verdict: FAIL

Pass criteria (from task spec):
- PF > 1.3 on test set → **NO** (best achievable: 0.57)
- Max DD < 25% → yes, but vacuous (the whole backtest is only -17%)
- ≥ 30 trades after filtering → conditionally yes at low thresholds
- No obvious look-ahead → confirmed clean

Any 3 of 4 required. Only the second and fourth are met; the PF criterion
is decisively missed.

## 6. Recommendation

**Leave MasterTraderV1 retired.** Do not redeploy with meta-labeler.
Reasons:

1. **No exploitable signal**: AUC 0.535 is indistinguishable from random
   on 124 test trades. No feature set we engineered separates winners
   from losers.
2. **The "live edge" is one quarter**: 13/14 quarters losing is not
   regime-dependence, it's a losing strategy that happened to be live
   during its one good month. Classic survivorship illusion.
3. **The one good quarter is out-of-distribution**: 2026-Q2's FNG ≈ 14
   regime is unprecedented in the 2023-2024 training set. A meta-labeler
   cannot generalize to an untrained regime, so even if we believe the
   edge is real, we have no way to predict it will trigger correctly in
   the future.
4. **Honest data point**: this is the scenario López de Prado's
   meta-labeling is designed for — and it still couldn't rescue MT. That
   tells us MT's primary signal is simply not good enough; the edge isn't
   hiding in a regime filter.

**Where the capital should go instead** (per Phase 3 priorities):
- **DSR filter on Lab shortlist** (cheapest win, ~1 session)
- **Delta-neutral FundingFade upgrade** (preserves funding edge, cuts
  directional risk in the current hostile regime)
- **Microstructure features** (orthogonal alpha lane — OFI, Kyle's Lambda)

**Revive MT conditional**: if we later observe another FNG < 20 crash-recovery
window in live market, sample its returns in paper-trading for 30 days.
If MT prints PF > 1.5 on ≥ 30 trades in that window alone, revisit.

## 7. Caveats

- **Small sample**: 124 test trades is underpowered for AUC confidence
  intervals. A ±0.05 band is plausible — but even 0.58 AUC is weak, and
  the threshold-sweep PF results are what actually matter.
- **No CPCV**: we used a single chronological split. Combinatorial
  purged-K-fold CV (mlfinlab) would give a more stable AUC estimate but
  cannot change the threshold-sweep outcome, which is grounded in actual
  test-set P&L.
- **Fixed MT params**: we used the default (hyperoptable) params. A
  hyperopt pass could in theory find better primary signals, but prior
  engine v2 runs timed out and 3.3yr MT has been tested extensively
  already — unlikely to change qualitatively.
- **Binary label only**: we didn't try triple-barrier labeling
  (López de Prado Ch.3). Given how weak the AUC is even on binary
  label, triple-barrier is unlikely to flip the sign.
- **Primary model fixed**: meta-labeling assumes the primary model
  *produces* trades in winning regimes. If MT never enters in winning
  regimes (e.g., because BTC guard is OFF in deep-fear windows), no
  meta-labeler can fix that; you'd need to also relax the primary filter.
  Worth noting but out-of-scope for this PoC.
- **Training regime imbalance**: winning regime (deep fear) has only 8
  trades in 3.1yr. Any classifier would struggle to learn a minority
  class with n=8. A longer history (2019-2022 spanning FTX collapse and
  COVID crash) might help — but we don't have 1h data for that period
  in the current dataset.
- **Fixed stake sizing**: simulation used 10% of equity per trade. Real
  fleet sizing is ~25% — but the *sign* of PF is invariant to stake
  size, so this doesn't affect the pass/fail verdict.

## 8. Artifacts

All under `/Users/palmer/Work/Dev/Master Trader/ft_userdata/meta_labeling/`:

- `01_extract_trades.py` — extracts trades from backtest zip
- `02_build_features.py` — computes regime features (no look-ahead)
- `03_train_eval.py` — trains LGBM + RF, threshold sweep, equity curves
- `04_robustness.py` — alternative configurations sweep
- `05_regime_analysis.py` — quarterly PF + winning-regime profile
- `trades.parquet` — 573 MT trades
- `features.parquet` — 573 trades × 17 features
- `threshold_sweep.csv`, `threshold_sweep_rf.csv`
- `summary.json` — full LGBM summary (feature importances, sweep, AUCs)
- `robustness.json` — 6 alternative configurations output
- `model.joblib` — trained LGBM + feature list (kept for reference)
- `equity_curves.png` — raw vs filtered equity curves on test set
- `venv/` — isolated Python venv (lightgbm, sklearn, matplotlib, joblib,
  pyarrow)

## 9. Changes NOT committed / reverted

- **`engine/registry.py`**: no edits. MT still marked `killed`.
- **`backtest-MasterTraderV1.json`**: not edited. Created separate
  `metalabel-MasterTraderV1.json` with the 20-pair whitelist.
- **No code committed to git** per task constraint.
- **No live bot configs touched.** Fleet unchanged (Keltner 8095 +
  FundingFade 8096 only).

---

**Conclusion**: Meta-labeling is the right tool for MT's backtest-live
divergence profile — and when applied honestly, it returns a clean
negative result. MT's apparent live edge cannot be systematized. Retire
MT for good and reinvest the capital + research cycles in the Phase-3
priorities that have remaining structural alpha.
