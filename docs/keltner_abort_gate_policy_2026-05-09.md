# KeltnerBounceV1 — Live Abort-Gate Policy

**Date:** 2026-05-09
**Status:** PROPOSED — pre-flight policy fix before any Keltner live flip
**Supersedes:** the FundingFade −7% operator abort threshold (was inherited verbatim, but Keltner has a 1.84× larger DD envelope)

---

## Why this exists

The FundingFade live deploy (2026-04-21) inherited a flat **−7% per-trade operator abort gate**. That is a sensible threshold for FundingFadeV1 because the strategy's own software stoploss is −5% and the −7% gate catches gap risk only.

For KeltnerBounceV1 the same threshold is **wrong by construction**:

| Metric | FundingFadeV1 | KeltnerBounceV1 |
|---|---|---|
| Strategy stoploss | −5% | −7% |
| Backtest portfolio max DD | (small) | 12.88% (Freqtrade native) |
| Weakness-window DD | n/a (6/6 WF) | 11–12% (2023-H2, 2024-H2) |
| Backtest DD duration | n/a | 163 days |

A −7% per-trade gate combined with a 12.88% portfolio DD envelope means the operator
will pull the plug during behavior the backtest already validates as normal. The live
readout becomes corrupted (sample truncated by a discretionary stop) AND the bot fails
to capture the post-DD recovery the backtest depends on for its +51% return.

This policy reconciles abort thresholds with the validated DD distribution.

---

## Policy

### Tier 1 — Single-trade abort (gap-risk catcher only)

**−10% on a single closed trade.** (1.43× strategy SL of −7%.)

Rationale:
- Strategy SL fires at −7%. Anything worse than −10% means the SL did NOT fire (gap event, Docker wedge, exchange outage, slippage spike) — i.e., a plumbing problem the backtest does not model.
- Backtest worst-trade is bounded by the −7% SL plus normal slippage (~−7.5% to −8% historical). −10% is a 2σ envelope around expected worst-trade.
- This gate is for plumbing, not edge — pause and investigate root cause; do NOT use it to second-guess the strategy.

### Tier 2 — Cumulative drawdown circuit breaker

**−20% on running portfolio equity** (1.55× backtest max DD of 12.88%).

Rationale:
- Backtest max DD across 3.3 years is 12.88%. Walk-forward windows show 11–12% DD in weakness regimes.
- Hitting 20% means we are 1.55× the historical worst, which is unambiguously a regime the backtest did not see — kill the bot pending investigation.
- This is the only true "strategy is broken" signal. Below 20%, observed DD is statistically consistent with the validated distribution.

### Tier 3 — Drawdown duration tolerance

**Do NOT panic-kill before 240 days of unbroken drawdown.** (1.47× backtest worst DD duration of 163 days.)

Rationale:
- Backtest DD duration is 163 days (May–Oct 2024).
- Operators tend to kill bots after ~30–60 days of underwater equity. For Keltner, that's *expected* behavior, not failure.
- 240-day clock is the operator's psychological commitment: if you cannot sit in DD for 8 months, do not deploy this strategy.

### Tier 4 — Consecutive-loss tripwire

**Pause and review at 6 consecutive losses.** (2× backtest max consec losses of 3.)

Rationale:
- Lab backtest: max consecutive losses = 3.
- 6 consecutive is 2× the historical worst — early signal that signal generation has decayed, well before Tier 1/2 fire.
- "Pause and review" ≠ kill. Compare current trades to backtest distribution by win rate, exit reason mix, and pair concentration. Resume if explainable; kill if not.

---

## Decision tree

```
Trade closes:
├── Loss > −10% (Tier 1) ──► PAUSE bot, investigate plumbing (gap/slippage/SL fail)
├── Cumulative DD > 20% (Tier 2) ──► KILL bot, post-mortem before any restart
├── 6 consecutive losses (Tier 4) ──► PAUSE bot, review distribution
├── DD duration > 240 days (Tier 3) ──► Mandatory review, not auto-kill
└── Else ──► Continue, log to telemetry
```

Tier 1 and Tier 4 are pauses (recoverable). Tier 2 is a kill (post-mortem mandatory).
Tier 3 is a forced review checkpoint.

---

## What this is NOT

- **Not a strategy change.** No code in `KeltnerBounceV1.py` changes. Strategy SL stays
  −7%, ROI tiers stay as-is, trailing stop stays as-is.
- **Not a research action.** This is deployment hygiene, sanctioned by the moratorium
  framing as "operations on already-validated bots."
- **Not optional.** This must be in place BEFORE Keltner flips live. Without it, the
  live readout is structurally invalid (operator would kill the bot during normal
  drawdown, generating non-stationary sample).

---

## Pre-flip checklist (Keltner specifically)

- [ ] This abort policy committed to docs/ and operator memorized
- [ ] `live_deployment_checklist.md` updated to reference this doc for Keltner row
- [ ] Telegram alert templates configured: per-trade loss > −8% (early warn), DD > 15% (watch), DD > 20% (circuit-breaker fired)
- [ ] Telemetry dashboard shows running cumulative DD vs backtest envelope (red zone at 13–20%)
- [ ] Regime activation gates met (see `keltner_regime_activation_gates_2026-05-09.md`)
- [ ] 30-day clean dry-run track record from the 2026-04-22 baseline

---

## When to revisit

- Live sample reaches 50 closed trades AND ≥6 calendar months — recalibrate Tier 2/3
  thresholds to live-observed DD if statistically distinguishable from backtest.
- New strategy or new pair universe → throw this policy out and recompute from scratch.
- Backtest is rerun on materially newer data (Jan 2025+ added) → recompute envelope.

---

## Calibration source

- `docs/keltner-bounce-v1-validation.md` (Layer 5: Freqtrade native backtest, 1m detail)
- Backtest result zip: `research/backtest_results/backtest-result-2026-04-22_19-24-17.zip`
- Lab walk-forward: `engine_results/20260417_rigorous/KeltnerBounceV1_walk_forward.json`
