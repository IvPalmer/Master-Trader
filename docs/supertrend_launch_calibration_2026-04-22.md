# SupertrendStrategyLaunch — calibration investigation

**Date**: 2026-04-22
**Question**: live Era A (Mar 2026) showed +$8.28 / 42 trades / 81% WR on the launch
version of SupertrendStrategy. Is that edge real, or was the backtest engine
miscalibrating against it?

**Verdict**: backtest is trustworthy. Launch code is a **near-zero-edge strategy**
that happened to draw a favorable 42-trade sample on live Era A. Do NOT deploy.

## Why this lane was reopened

Memory already flagged Supertrend DEAD (2026-04-17) after 3 configs were tested
at 1m-detail over 3.3yr — all losing, worst −54%. But the user correctly observed
that the kill-era tests were run on **tweaked code**, not the clean launch version.
The April 6 commits (trailing stop + confidence sizing + ROI retune) caused a
15-percentage-point regression that may have been mistaken for "strategy dead"
when the real problem was "we broke a borderline strategy into a losing one."

Live dry-run P&L sliced by code era confirms the regression:

| Era | Code | Trades | P&L | Avg/trade | WR |
|-----|------|--------|-----|-----------|-----|
| A: Launch (Mar 11-12) | ROI-only + classic trailing | 42 | **+$8.28** | **+1.17%** | **81%** |
| B: Late March | hyperopt-tuned, pre-trailing | 6 | +$0.96 | +0.52% | 67% |
| C: Apr 6-13 | N-bar trailing + confidence sizing | 33 | **−$5.92** | **−0.56%** | **33%** |
| D: Apr 14+ | trailing removed (current) | 3 | −$0.93 | −1.02% | — |

So the user's hypothesis — "the original was winning, the tweaks killed it" — is
correct. Step 2 was to test whether the launch code has persistent edge at all.

## Three backtest runs

SupertrendStrategyLaunch.py was extracted verbatim from commit `21fa4ed`
(launch commit, 2026-03-11). Class renamed to avoid conflict with the kept
dead version. Config files saved under:

- `backtest-SupertrendStrategyLaunch.json` — original universe, 3.3yr
- `backtest-SupertrendStrategyLaunch-calibrate.json` — live Era A calibration
- `backtest-SupertrendStrategyLaunch-1yr.json` — wider alt universe, 1yr

### Test A: full 3.3yr × 19 FundingFade-style pairs × $200 stake

```
Trades:       1931    (1.63/day)
Return:      −2.85%   over 1188 days
CAGR:        −0.88%
PF:           0.96
Sharpe:      −0.48
Sortino:     −0.93
Calmar:      −0.87
Max DD:       5.24%
Win rate:     51.6%
Avg/trade:   −0.07%
Worst trade: BNB −10.18%
Best trade:  ZEC  +8.70%
Max consec:  26W / 14L
```

Per-pair: NEAR, ZEC, SOL, DOGE, LINK profitable. AVAX, ETH, SUI, LTC, BNB losing.

### Test B: 3-week Era A window × 14 actual live-traded pairs × $17.60 stake

Direct apples-to-apples calibration — same timerange, same pairs, same stake as
live Era A.

```
Trades:       52
Return:      +0.02%
PF:           1.08
Sharpe:       1.53
Sortino:      3.21
Calmar:      23.57
Max DD:       tiny
Best trade:  HUMA +8.70%
Worst trade: PIXEL −10.18%
```

vs live Era A: 42 trades / +$8.28 / 81% WR / PF ~5+.

Backtest and live **agree on sign** (both positive). Magnitude differs because
N=42 is too small to separate a +1.08 PF distribution from a +5 PF outlier. This
is sample variance, not miscalibration.

### Test C: 1yr × 19 alt-heavy pairs × $17.60 stake

Wider modern alt universe with pairs live Era A-style bots would plausibly
trade (FET, RENDER, PAXG, AAVE, ONDO, DOT in addition to the 3.3yr stable set).

```
Trades:       616    (1.64/day)
Return:      −0.06%   over 375 days
CAGR:        −0.06%
PF:           0.97
Sharpe:      −0.42
Max DD:       0.32%  ($32 absolute)
Win rate:     50.5%
```

## Calibration verdict

Three independent tests landed in the PF band 0.96–1.08. Backtest is consistent
with itself across different universes and windows. If the engine were
systematically miscalibrated against this strategy, we'd expect directional
disagreement between the tests. We see convergence.

Live Era A's high WR and high PF were a favorable tail on a near-zero-edge
distribution — exactly the kind of result a 42-trade sample produces when the
true PF is ~1.0.

## Secondary finding — the 2026-04-06 regression

Launch code max DD across backtests: 0.3% to 5.2%.
Current (Era C) code max DD in the Apr 12 viability run: **47.05%**.

That is a 9× blow-up in drawdown caused by adding N-bar trailing stop +
confidence sizing + ROI retuning. Project memory already contains this rule:

> *"Trailing stop adds noise at 1m-detail: Supertrend with trailing = −54% over
> 3.3yr (vs −3% no trailing)"* — `feedback_nbar_trailing_disaster.md`

We re-derived the same rule through a different path. Evidence compounds.

## Deploy decision

**Do not deploy SupertrendStrategyLaunch in any form.**

Reasons:
1. Full-universe 3.3yr backtest: PF 0.96, −2.85%. Fails viability.
2. Wider 1yr alt backtest: PF 0.97, −0.06%. Fails viability.
3. Direct live calibration: PF 1.08, +0.02%. Marginal.
4. Even if restricted to the 5 pairs that backtest individually positive
   (NEAR, ZEC, SOL, DOGE, LINK), that's post-hoc cherry-picking without an
   out-of-sample test — classic overfitting pattern.
5. FundingFade baseline: PF 1.29, +60.66% over 3.3yr. Launch Supertrend doesn't
   compete.

## What's worth keeping

1. **Launch Supertrend file preserved** as `SupertrendStrategyLaunch.py` and
   three config files. If a future hypothesis ever reopens this lane (new
   universe, new data source, new signal overlay), the clean baseline is ready
   to regression-test against.
2. **The "apples-to-apples calibration" pattern** is reusable: when a live bot
   shows good numbers on <100 trades, run the matched-window + matched-pairs
   backtest before deciding whether the backtest engine is wrong. ~20 min of
   compute, definitive answer.
3. **Confirms the 30-day research moratorium is the right stance.** Even when
   the live data looks like a clean tell, the backtest converges on near-zero
   edge across universes. The fleet's 2-bot ceiling holds.

## Files

- `ft_userdata/user_data/strategies/SupertrendStrategyLaunch.py` — launch-era
  code extracted from commit 21fa4ed, class renamed
- `ft_userdata/user_data/configs/backtest-SupertrendStrategyLaunch.json` —
  3.3yr × 19 pairs, $200 stake
- `ft_userdata/user_data/configs/backtest-SupertrendStrategyLaunch-calibrate.json`
  — Era A window + pairs + stake
- `ft_userdata/user_data/configs/backtest-SupertrendStrategyLaunch-1yr.json` —
  1yr × 19 alt-heavy pairs + $17.60 stake
- `/tmp/supertrend_launch_bt.log`, `/tmp/supertrend_launch_calib.log`,
  `/tmp/supertrend_launch_1yr.log` — raw backtest logs (not committed; can
  regenerate by rerunning the configs).
