# CascadeFaderV1 — 30-day dry-run gate evaluation (2026-06-09)

Evaluation of the gate set in `cascade_fader_v1_validation_2026-05-09.md`
("total trades ≥ 5 in 30 days"), which expired ~2026-06-08 without review.
Triggered by the 2026-06-09 fleet audit, which found the gate both expired
and mis-specified.

## Verdict

**EXTEND with a corrected, sample-based gate. Do not kill.**
Plumbing is verified working; the trade shortfall is signal starvation,
statistically unremarkable under the backtest's own cadence.

## Evidence

### Live record (VPS trade DB, ft-cascade-fader, read 2026-06-09)

| # | Pair | Signal candle (UTC) | Entry | Exit | Result |
|---|------|--------------------|-------|------|--------|
| 1 | ZEC/USDT | 2026-06-05 02:00 | 03:00 | 05:24 | −8.20% (SL) |
| 2 | ZEC/USDT | 2026-06-05 07:00 | 08:10 | 09:29 | +3.26% (ROI/TP) |

2 trades in the 30-day window (2026-05-09 → 2026-06-08). Gate required ≥ 5.

### Signal-availability scan (Binance spot 1h, public klines, run 2026-06-09)

Re-implemented the exact deployed entry rule — `(open−low)/open ≥ 8%`,
`(close−low)/(open−low) > 0.4`, `volume > 2.0 × SMA720(volume)` (min_periods
360) — over all 13 whitelist pairs, 2026-05-09 → 2026-06-09, with full 30-day
volume-SMA warmup from 2026-04-09.

**Result: exactly 2 qualifying candles fired market-wide in the window —
ZEC 06-05 02:00 (drop 9.0%, recovery 0.70, vol 9.3×) and ZEC 06-05 07:00
(drop 21.8%, recovery 0.84, vol 29.7×). The bot captured 2/2 with correct
next-bar entries.** 34 near-misses (drop ≥ 5%, vol > 1.5×) — none qualified;
most failed the 8% depth or 0.4 recovery filter, behaving as designed.

So the question the audit posed — "entry path broken vs no signal" — is
answered: **entry path 100% functional; the market produced almost no
cascades** in a month where BTC ground down −24% without panic-wick events
on these pairs.

### Was 2 trades anomalous?

Backtest cadence: 162 trades / 37.1 months = 4.37 trades/month fleet-wide.
P(N ≤ 2 in 30d | Poisson λ=4.37) ≈ **19%** — not even mildly anomalous.
The original gate ("≥5 in 30d") had only ~44% pass probability *if the
backtest were perfectly correct*: it was mis-specified at birth, which is
why it could not be meaningfully "passed" or "failed".

## Corrections to the record

1. The validation doc's frequency rationale ("~1/week per pair × 13 pairs")
   is wrong by ~13×: actual lab cadence is 0.34 trades/pair/month.
2. "Max DD 0.51%" is on a $10k wallet with $100 stakes (1% exposure). On the
   deployed $200 wallet / 3-slot unlimited-stake config, the equivalent
   relative DD is ~50× larger. The −8.20% single-trade SL on trade #1 is the
   realistic per-trade loss scale.
3. MEMORY.md's "PF 1.76, 84% WR" does not match the deployed strategy's own
   docstring (PF 1.62, WR 77.8%, N=162) — the docstring is the authority for
   the deployed config.

## New gate (pre-registered in ft_userdata/preregistrations.json)

- **id:** `cascade-dry-run-gate-v2`, review by **2026-09-30**
- At ≥ 20 closed trades: continue if PF ≥ 1.0 AND WR ≥ 60%
  (backtest: PF 1.62, WR 77.8%); else kill.
- If < 10 closed trades by review date: frequency anomaly
  (P ≈ 3.9% under backtest cadence, λ=16.2 over the 113-day window) —
  investigate signal-rate mismatch before extending.
- Surfaced daily by `strategy_health_report.py` (PRE-REGISTRATIONS section)
  so it cannot expire silently like the v1 gate did.
