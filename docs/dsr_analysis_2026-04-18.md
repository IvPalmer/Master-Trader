# Deflated Sharpe Ratio Analysis — Strategy Lab Shortlist

**Date**: 2026-04-18
**Analyst**: Claude agent
**Scope**: Apply Bailey & López de Prado (2014) Deflated Sharpe Ratio to the 6900-combo Strategy Lab run logged 2026-04-17, plus live-fleet strategies (KeltnerBounceV1, FundingFadeV1).

Artifacts:
- Script: `/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis/dsr_analysis.py`
- Machine-readable output: `/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis/dsr_results.csv`

---

## TL;DR

At **N = 6900 trials**, the expected maximum Sharpe under the null of zero true skill is **E[SR_max] ≈ 3.77**. None of the Strategy Lab's top-50 combos comes close. The best observed per-trade-annualised Sharpe is **2.09** (`kelt(20,2.5)+vol(2.0)|btc_sma50|wide`). All 31 distinct combos analysed produce **DSR ≈ 0** (probability that observed Sharpe reflects real skill, after adjusting for multiple testing). **0 / 31 pass DSR > 0.95.**

The live-fleet signals behave the same way:

| Strategy | SR_ann | skew | kurt | T | DSR | Verdict |
|---|---|---|---|---|---|---|
| KeltnerBounceV1 (per-trade) | 1.87 | -1.32 | 3.51 | 139 | **0.0000** | Fails DSR |
| KeltnerBounceV1 (daily SR, Freqtrade-style) | 1.67 | 0.17 | 24.40 | 1164 | **0.0000** | Fails DSR |
| FundingFadeV1 (Lab row #14, roi_only) | 1.43 | -0.66 | 1.43 | 431 | **0.0000** | Fails DSR |
| FundingFadeV1 (balanced exit) | 1.02 | -0.66 | 1.43 | 452 | **0.0000** | Fails DSR |

**This does NOT mean the bots are unprofitable** — it means that at this trial count the Lab's screening ranking cannot distinguish skill from luck. Both bots have INDEPENDENT validation paths that remain intact (Freqtrade native backtests, walk-forward windows, Viability wrapper calibration against live). DSR is one test among several, not the final word.

---

## 1. Methodology

### Deflated Sharpe Ratio (Bailey & López de Prado 2014)

When N candidate strategies are tested and the max-Sharpe strategy is selected, the observed Sharpe is inflated by extreme-value statistics. DSR = Prob( true Sharpe > 0 | observed Sharpe, N, sample moments ).

Formulas implemented (see `dsr_analysis.py`):

```
E[SR_max] ≈ √V · [(1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))]
                                           γ = Euler-Mascheroni ≈ 0.5772

σ_SR(SR_hat) = √[ (1 - γ₃·SR + (γ₄-1)/4·SR²) / (T-1) ]   (Mertens 2002 non-normal adj.)

DSR = Φ( (SR_hat - E[SR_max]) / σ_SR )
```

Where `γ₃` = skewness, `γ₄` = kurtosis (full, not excess — normal = 3), `T` = sample length (trade count or daily bars), `V` = variance of SRs across trials (assumed 1 for conservative bound; we lack the full 6900 SR distribution to compute V directly).

### Data sources

- **Top-50 Lab log**: `/Users/palmer/ft_userdata/lab_output_funding_20260417.txt` (only persisted artifact from the 6900-combo run — full results were NOT dumped to JSON; `strategy_lab.py` only writes validated combos, not the full screen). 31 unique combos after deduplicating gate variants that produce identical metrics.
- **Keltner backtest zip**: `/Users/palmer/ft_userdata/user_data/backtest_results/backtest-result-2026-04-17_00-35-38.zip` — real per-trade `profit_ratio` series for exact skew/kurt/Sharpe.
- **FundingFadeV1**: No standalone backtest zip exists. Used Lab screen output (PF 1.29, WR 65.7%, 431 trades) to reconstruct.

### Reconstruction caveat

For 29 of 31 combos we only have (PF, WR, N, P&L, DD) from the text log, not per-trade returns. We reconstruct a two-point distribution: each win = `w`, each loss = `-l`, solved so `w/l = PF · (1-WR)/WR`. This:
- Is **scale-invariant** for Sharpe — correct by construction
- **Understates** kurtosis (real trades have within-class dispersion) and **overstates** Sharpe slightly
- Net effect: reconstructed DSR is **optimistic**. Real DSRs are at most equal, usually lower.

Keltner's "real per-trade" record (derived from exact backtest JSON) confirms the reconstruction doesn't save the verdict: with real kurt=3.51 and skew=-1.32 its DSR is still 0.0000 because `E[SR_max] = 3.77 >> SR_hat = 1.87`.

### Sanity checks (all passed)

```
E[SR_max | N=1]   = 0.0000   (expected ~0) ✓
N=10              = 1.57 (√(2·ln 10)=2.15)
N=100             = 2.53 (√(2·ln 100)=3.03)
N=1000            = 3.26 (√(2·ln 1000)=3.72)
N=6900            = 3.77 (√(2·ln 6900)=4.20)
σ_SR(SR=0, T=1000, normal) = 0.0316 (√(1/999)=0.0316) ✓
DSR(SR=1, T=1000, N=1)     = 1.0000 (no deflation when N=1) ✓
```

---

## 2. Top 20 by DSR

All 31 rows fail DSR > 0.95 at N=6900. Ranked by Sharpe (DSR is uniformly ~0):

| # | SR_ann | skew | kurt | T | PF | Combo |
|---|---|---|---|---|---|---|
| 1 | 2.09 | -1.22 | 2.48 | 97 | 2.16 | `kelt(20,2.5)+vol(2.0)|btc_sma50|wide` |
| 2 | 1.87 | -1.32 | 3.51 | 139 | 1.88 | **KeltnerBounceV1 (real per-trade)** |
| 3 | 1.74 | -0.94 | 1.87 | 192 | 1.59 | `kelt(20,2.5)+funding_neg|btc_sma50|wide` |
| 4 | 1.67 | 0.17 | 24.40 | 1164 | 1.88 | **KeltnerBounceV1 (daily SR)** |
| 5 | 1.60 | -1.05 | 2.09 | 98 | 1.81 | `kelt(20,2.5)+vol(2.0)|btc_sma50|balanced` |
| 6 | 1.53 | -0.93 | 1.86 | 98 | 1.76 | `kelt(20,2.5)+vol(2.0)|btc_sma50|roi_only` |
| 7 | 1.43 | -0.66 | 1.43 | 431 | 1.29 | **FundingFadeV1 (Lab #14, roi_only)** |
| 8 | 1.38 | -0.87 | 1.75 | 124 | 1.58 | `kelt(20,2.5)+funding_neg|btc_sma50+sma200|wide` |
| 9 | 1.25 | -0.81 | 1.65 | 228 | 1.36 | `kelt(20,2.5)+funding_neg|btc_sma200|wide` |
| 10 | 1.19 | -0.95 | 1.89 | 186 | 1.39 | `kelt(20,2.5)+vol(1.5)|btc_sma50|balanced` |
| 11 | 1.01 | -1.00 | 1.98 | 30 | 1.97 | `bb(20,3)+funding_neg|btc_sma50+sma200|balanced` |
| 12 | 0.99 | -0.95 | 1.86 | 22 | 2.16 | `donch(55)+stoch(20)|btc_sma50|balanced` |
| 13 | 0.99 | -0.86 | 1.72 | 57 | 1.62 | `kelt(20,2.5)+vol(2.0)|btc_sma50+sma200|wide` |
| 14 | 0.97 | -1.19 | 2.42 | 75 | 1.54 | `bb(20,3)+funding_neg|btc_sma200|tight` |
| 15 | 0.97 | -0.75 | 1.55 | 170 | 1.32 | `kelt(20,2)+funding_p10|btc_sma50+sma200|balanced` |
| 16 | 0.97 | -0.78 | 1.60 | 89 | 1.46 | `kelt(20,2.5)+funding_p10|btc_sma50+sma200|wide` |
| 17 | 0.95 | -1.00 | 1.98 | 30 | 1.90 | `bb(20,3)+funding_neg|btc_sma50+sma200|wide` |
| 18 | 0.91 | -1.08 | 2.15 | 100 | 1.42 | `kelt(20,2.5)+vol(2.0)|btc_sma50|tight` |
| 19 | 0.85 | -0.79 | 1.61 | 146 | 1.30 | `kelt(20,2.5)+funding_p10|btc_sma50|wide` |
| 20 | 0.85 | -0.76 | 1.58 | 237 | 1.23 | `kelt(20,2.5)+funding_neg|btc_sma200|balanced` |

Full ranked CSV with all DSR primitives at `ft_userdata/analysis/dsr_results.csv`.

---

## 3. Live-strategy survival check

### KeltnerBounceV1

Computed on **real per-trade returns** from the native Freqtrade backtest zip (139 trades, full 3.3y).

- Per-trade annualised Sharpe: **1.87** (skew -1.32, kurt 3.51)
- Daily Sharpe (Freqtrade-style): **1.67** (very fat-tailed: kurt 24.4 from a single large up-day)
- Freqtrade's reported Sharpe in the zip: 0.615 (uses different normalisation)
- **E[SR_max]** at N=6900: **3.77**
- **DSR = 0.0000** under both SR definitions

### FundingFadeV1

Reconstructed from Lab log row #14 (`funding_below_mean+adx(25)+vol(1.5)|btc_sma50+sma200|roi_only`, 431 trades, PF 1.29):

- SR_ann ≈ **1.43** (reconstructed)
- **DSR = 0.0000**

### What DSR failure does NOT say

1. The *true* Sharpe could still be positive — DSR answers "is the observed SR high enough to confidently reject SR ≤ E[SR_max]?" The true SR of a profitable crypto strategy is typically in the 0.5-2.0 range. DSR asks whether we can **distinguish** that from noise after 6900 trials — at that trial count the required threshold (~4.4) is absurd.
2. Keltner has independent validation paths that DSR cannot invalidate: 6/6 lab walk-forward windows profitable, 4/6 Freqtrade calendar-half windows profitable, Viability wrapper 97% match vs lab (+53.69% vs +51.85% 3.3yr), year-by-year PF 1.65-2.06 in every 4 of 4 years (see memory `project_keltner_validation.md`).
3. FundingFadeV1 has lab walk-forward 6/6 profitable (see memory). Its current drawdown risk (46d negative funding streak) is a regime concern, not a DSR issue.

### Break-even SR to pass DSR > 0.95

At T=139 trades, skew=-1.3, kurt=3.5 (Keltner's shape):

| Effective N | E[SR_max] | SR needed |
|---|---|---|
| 1 | 0.00 | 0.16 |
| 10 | 1.57 | 1.91 |
| 100 | 2.53 | 2.98 |
| 1000 | 3.26 | 3.80 |
| 6900 | 3.77 | **4.37** |

If we argue the 6900 combos are highly correlated (same 19 anchors × 13 confirms × 5 gates × 4 exits ⇒ effective N much smaller), the bar comes down. At effective N = 100 the required SR is ~3.0 — still unreached. At effective N = 10 the bar is 1.9, which the top combo (2.09) clears.

---

## 4. Survivorship rate

**0 / 31 combos analysed pass DSR > 0.95 at N = 6900** (0.0%).

**Blocker**: `strategy_lab.py` only persists VALIDATED combos to JSON (`lab_results_*.json`) after phase 3 Freqtrade validation. The 6900-combo screening output is only printed to stdout; line 330-333 writes `validated`, not `results`. The full SR distribution across 6900 trials is lost. Recommended engine change: dump `results` to a CSV in phase 2 before phase 3. Without this, true survivorship % is unknowable — but since the log shows only 738 combos had PF > 1 (10.7%) and only 27 passed the quality filter (trades ≥ 80, WR ≥ 55%, PF ≥ 1.3), any Sharpes outside the top 50 are strictly lower than the values analysed here, and they all fail too.

Best-effort survivorship estimate: **0% of 6900** pass DSR > 0.95 at their observed Sharpes.

---

## 5. Actionable

### Do NOT panic-kill the live fleet

DSR failure at N=6900 is **expected for any strategy family** with realistic crypto Sharpes in the 1-2 range. This is the whole point of the paper — ranking by Sharpe alone across thousands of variants is fundamentally unreliable, because the null-case maximum absorbs the signal. Independent validation paths (walk-forward, calibration vs live, multi-year stability) are what justify live deployment, not the Lab screening rank.

### Promote the engine (not the shortlist)

1. **Persist full Lab results** (CSV with SR + trade returns per combo) — one-line fix in `strategy_lab.py`. Without this every future DSR check is best-effort.
2. **Report DSR alongside score** in the Lab output. Would have prevented overweighting the top-50 ranking.
3. **Compute effective N** via correlation of trial return streams (López de Prado section 5). If correlation is high across the 19×13×5×4 grid, effective N ≪ 6900.

### Treat DSR as one signal, not a verdict

For the ongoing workflow:
- **KeltnerBounceV1**: keep live, continue calibration + live-vs-backtest monitoring. DSR adds no new information beyond "we know we ran many trials."
- **FundingFadeV1**: current 46-day negative-funding regime is the real risk, not DSR. Monitor live deviation.
- **Any NEW strategy** proposed from the Lab shortlist: require independent validation AND a break-even DSR check at effective N. Do not deploy purely on Lab rank.

### What this analysis DID find

- The Lab's "win big lose small" strategies have pronounced **negative skew** (-0.6 to -1.3 across the top 20) — confirms the regime where many small wins are offset by rare large losses. This is consistent with the trading philosophy note but worth monitoring per-strategy.
- **Daily-return Kurt 24.4** for Keltner indicates single-day tail risk (one large gain day dominates the distribution). Sharpe-based metrics will understate that risk; drawdown-based metrics (DD% = 12.89, Calmar = 8.03) are more honest.
- **Gate variants produce identical metrics** (multiple rows in the log have same PF/WR/PNL/DD/trades). The Lab generates 6900 combos but the effective distinct set is smaller — another reason effective N ≪ 6900.

### Highest-ROI follow-ups

1. Patch the Lab to persist all 6900 results to CSV (30 min work).
2. Compute **pairwise correlation of combo return streams** → effective N (60 min).
3. Re-run DSR at effective N. Likely survivors: the 2-3 Keltner variants at SR ≈ 2.
4. Proceed to **meta-labeling** as previously prioritised. DSR is a gate, meta-labeling is an additive edge.

---

## References

- Bailey, D. H., & López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality*. SSRN 2460551. <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- Mertens, E. (2002). *Comments on variance of the IID estimator in Lo (2002)*. Working paper.
- Hudson & Thames `mlfinlab` — reference implementation, not used here (formula implemented directly in ~40 lines).
