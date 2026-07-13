# OOS retest results — 2026-07-13 (prereg oos-retest-2026-07)

Executed same-day per the pre-committed protocol
(2026-07-13-doubt-audit-oos-protocol.md). Artifacts: VPS
`~/master-trader/research/oos_retest_2026-07/` (R1–R7 exports, configs,
funding-availability variants, calibration outputs). Codex-reviewed wording.

## Calibration (primary metric)

| Check | Verdict | Detail |
|---|---|---|
| C1 FF drift-4h vs live | **PASS 2/2** | Both live trades (HBAR, ADA) reproduced exactly: entry deltas ≤0.175%, pnl within 0.01pp. The stale-availability fault model is proven — the simulator reproduces live behavior when fed live data-visibility. |
| C2 FF hourly-:10 vs live | PARTIAL 1/2 by design | ADA disappears under the fixed availability model; HBAR remains. Confirms the 2026-07-13 refresh fix eliminates the stale-entry trade class. |
| C3 Keltner 60-union vs dry | 5/5 matched + 24 extras | All real trades reproduced (entry deltas ≤0.164%); extras are the static-union ≠ point-in-time-VolumePairList artifact. Keltner is only partially reconciled as a live simulator. |
| C4 Cascade vs dry | **PASS 2/2** | Both ZEC trades matched. Anomaly: 2nd entry chased +4.8% in 10 min vs backtest's next-bar-open fill (see risks). |

Scope caveat: C1/C4 are N=2 each. The simulator is *calibrated on the observed
FF/Cascade cases*, not broadly validated.

## OOS performance (post-selection window, fee 0.00075, 1m-detail)

| Run | Config | Window | Trades | Profit | PF | maxDD |
|---|---|---|---|---|---|---|
| R2 | FF intended (hourly funding) | 05-19→07-13 | 1 | −0.39% | — | 0.4% |
| R3 | FF omniscient funding | 05-19→07-13 | 1 (identical) | −0.39% | — | 0.4% |
| R4 | Keltner **validated** 18 static | 04-16→07-13 | 14 | −0.61% | 0.92 | 3.8% |
| R5 | Keltner **deployed** 60-union | 05-25→07-13 | 29 | −13.84% | 0.48 | 13.8% |
| R6/R7 | Cascade (deployed ≡ lab-exit here) | 05-09→07-13 | 2 | −1.71% | 0.36 | 2.7% |

Key attributions:
- **FF trade-rate collapse is signal scarcity, not regime lockout**: gate open
  23.4% of the OOS window (backtest-era: 33.3%), yet 310 gate-open hours
  produced ONE funding signal. Claimed rate was 1.67 trades/wk. Consistent with
  the documented post-2025 funding-yield compression. By the 2026-08-17 review
  the prereg's gate-open-time fallback will bind, not the PF rule.
- **R5's bleeding comes from outside the validated universe**: −$65.6 gross
  losses from non-18 pairs (HOLO, PUMP, BIO, HYPER, SENT…). The dynamic
  VolumePairList admitted fresh listings the validation never saw. Also noted:
  the validation doc's own post-filter recommendation was 15 pairs with
  ENA/ETH/SOL blacklisted — the dry bot's only losses to date were SOL/ETH.
- **Keltner validated config shows no OOS edge either**: PF 0.92 at N=14 vs
  in-sample 1.99 — the DSR selection-luck warning playing out, though N is
  too small for a formal verdict.

## New risk registered: Cascade entry-chase
The 2nd dry ZEC entry filled 10 min late at +4.8% above the backtest's assumed
next-bar-open price — the limit order chased a fast rebound. Cascade's edge
thesis is "recovery happens fast", which is precisely when chase is worst.
**Any Cascade backtest number is suspect until a fill-model stress test runs**
(enter at next-1m VWAP/high, max-entry-slippage cancel). Registered follow-up;
do not promote Cascade on current backtest evidence.

## Actions taken (commit d16f100, deployed 2026-07-13 04:48 UTC)
- F5: Keltner → validated 18-pair static list. **New measurement epoch
  2026-07-13T04:48Z** (prior dry accounting measured a deviated config).
- F7: Cascade unconditional 48h timeout exit (verified firing on 2024 control
  run). **Same epoch stamp.** One PAXG trade was open at cutover (Keltner,
  survived restart normally); Cascade had none.
- F10: ShortKeltnerV2HL NaN-gate warning (restarted 04:48:34Z).
- FF live untouched throughout.

## Bottom line
No evidence of deployable edge in any tested config — consistent across live
(FF PF 1.06, ex-ZEC ~0.55), dry, and post-selection OOS backtests. No kills
today (small-N prereg rules); kill/demote decisions bind at the scheduled
reviews (FF + fleet: 2026-08-17). The fidelity fixes ensure that whatever the
forward instruments measure from today is at least the thing that was
validated. Paths worth operator consideration for actual profitability remain
outside this universe: new-data lanes (cross-venue funding spread ranked #1),
execution-edge work, passive beta.
