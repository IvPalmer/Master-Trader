# Doubt-audit + true-OOS retest protocol — 2026-07-13

Operator mandate: the backtest is not a source of truth; doubt everything; the goal is
strategies that are actually profitable. This doc records what was tested this session,
what it showed, and the pre-committed protocol for the OOS retest. Codex-reviewed
(3 rounds, thread 019f598a).

## What was tested against live data (2026-07-13)

| Doubt | Verdict | Evidence |
|---|---|---|
| Execution/slippage eats the edge | **CLEARED** | Avg entry fill −0.05% vs decision-candle open across all 19 FF live trades; only ADA chased (+0.175%). Fees actually paid 0.075%/side (BNB discount) vs 0.20% RT assumed by lab — assumptions conservative. |
| FF live record shows edge | **NOT SUPPORTED** | 19 closed: PF 1.06, +$0.41 net. Avg win +4.95% / avg loss −5.17%, WR 52.6% vs ~51.1% breakeven. Indistinguishable from zero edge. |
| Win quality | **RED FLAG** | ZEC = 5 of 10 wins, all in the Apr–May privacy-pump window. Ex-ZEC PF ≈ 0.55. Losses cluster at regime tops (May 5-SL streak, July 2-SL). Pattern reads "long weak alts in chop", not "harvest crowded shorts". |
| Gate-v2 backtest (PF 1.54) | **SELECTION-CONTAMINATED** (known, now quantified) | Built 2026-05-19 to excise the observed May streak; no OOS at build time. First true OOS: 0W/2L (July). |
| Live inputs match backtest inputs | **WAS BROKEN, FIXED** | ADA 07-11 entered on 10h-stale funding the fresh event had invalidated (commit 177cdd1 fixed refresh cadence). Residual guard = F2, pending. |
| Dry-run bots measure the validated configs | **NO** (Keltner) | Deployed VolumePairList(40)+ShuffleFilter ≠ validated 18 static pairs (F5). Cascade missing lab's unconditional 48h exit (F7). |

Key asset discovered: VPS OHLCV (20 pairs, 1h+1m) ends **exactly 2026-05-19**.
Everything after is untouched by any selection decision — ~8 weeks of pristine OOS
data for every frozen strategy, growing daily.

## Pre-committed OOS retest protocol (registered before any result exists)

### Order of operations (codex-mandated)
1. **Freeze provenance** (this doc + preregistrations.json): strategy git hash,
   config hash, pairlist source, freqtrade version, fee model, funding-availability
   model, data download timestamp, open-trade treatment.
2. **Trade-level calibration FIRST, on deployed-actual configs** — before any
   fidelity fix changes behavior, capture the baseline: does a backtest over
   2026-05-19→now with deployed-actual settings reproduce the trades the live/dry
   bots actually took? Metrics: expected-vs-actual entries, missing trades, extra
   backtest-only trades, entry-candle alignment, exit-reason alignment, PnL delta.
   **Calibration failure = profitability stats untrustworthy until explained.**
3. **Frozen/intended-config OOS backtests** over the post-selection window:
   - FF-gate-v2 (cleanest: selected 05-19, zero post-selection influence)
   - Keltner in BOTH variants: validated (18 static pairs) AND deployed (dynamic) —
     divergence between them is itself evidence
   - Cascade in BOTH variants: lab-intended (48h any-price timeout) AND
     deployed-actual (ROI-ladder only)
   - ShortKeltnerV2 Binance-config (frozen 05-28)
4. **Only then** apply fidelity fixes (F5/F7/F10) and declare new measurement epochs.
5. Kill/demote/continue decisions per thresholds below.

### FF funding-availability model (mandatory)
The OOS backtest must NOT use omniscient funding history. Two runs:
- **deployed-actual-before-fix**: 4h drifted cron availability (diagnostic — should
  reproduce the ADA artifact; proves the simulator can model the live fault)
- **intended-post-fix**: hourly :10 availability + expected-event guard
  (`floor(t/8h)*8h` with publication grace)

### Interpretation rules (pre-committed; small-N discipline)
- Expected N over 8 weeks is single-digits per bot → aggregate PF is directional
  only; NO kill/scale decision on OOS PF alone at N<10.
- Trade-level calibration is the PRIMARY metric: fidelity first, profitability second.
- Decision matrix at each bot's existing/next review date, combining OOS window +
  live/dry record: consistent negative across both → demote/kill per that bot's
  prereg; consistent positive → continue measuring (scaling still gated by
  graduation v2); divergent → find the fidelity bug before interpreting.
- Portfolio-level additions (required in the report): concurrent-bot DD, correlated
  same-regime loss clustering, per-pair contribution + leave-one-pair-out (FF ex-ZEC
  explicitly), fee/slippage sensitivity, rolling-window stability (not one aggregate).

### Explicitly out of scope
- No parameter changes, no re-optimization, no new signal search on old data
  (ceiling/moratorium stands). This protocol evaluates FROZEN strategies on NEW data.
- Cross-venue funding-spread lane (offense) is a separate operator decision.

## Honest bottom line (pre-registered so hindsight can't soften it)
Current live + dry evidence is consistent with **zero deployable edge** across the
fleet. This protocol exists to make keep/kill decisions fast and honest rather than
letting breakeven bots drift for months. "No deployable edge in this universe" is an
acceptable, pre-registered outcome.
