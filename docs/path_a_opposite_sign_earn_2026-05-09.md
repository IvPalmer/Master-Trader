# Path A — Lane #1: Opposite-Sign Funding Earn (Binance perp + Hyperliquid perp)

**Date:** 2026-05-09
**Status:** **CLOSED — fee-friction kills the edge.** Even optimistic maker-only execution caps at +1.20%/yr/pair on a 15-pair-month sample. Two orders of magnitude smaller than fleet's existing edges (FundingFade ~18%/yr, Keltner ~15%/yr).
**Lane:** Path A reformulation #1 of 3 (per `docs/hyperliquid_spread_infra_2026-04-21.md`)

---

## Hypothesis

When `sign(binance_funding) ≠ sign(hyperliquid_funding)`, a delta-neutral two-leg
position can collect funding on BOTH legs simultaneously. ICP/DASH/ZEC show
opposite-sign 30-34% of the time per the prior cross-venue study.

Setup:
- `b > 0` (longs pay) AND `h < 0` (shorts pay) → **SHORT binance + LONG hl** (both receive)
- `b < 0` AND `h > 0` → **LONG binance + SHORT hl** (both receive)
- Same-sign hours: stay flat (one leg always pays)

## Method

Simulator: `ft_userdata/analysis/opposite_sign_earn_sweep.py` (working copy in `/tmp/`)
- Hourly state machine on overlap window per pair
- Binance 8h funding forward-filled, divided by 8 for hourly equivalent
- Fees: taker 0.04% (Binance) + 0.045% (HL) = 0.085% per side, 0.17% RT all-in
- Maker variant: 0.02% Binance + −0.01% HL rebate = 0.02% RT all-in
- Sweep: combined-magnitude threshold ∈ {0, 1bp, 5bp, 10bp, 20bp}, min-hold ∈ {0, 4, 8, 24h}

Sample (data overlap, per pair):
- ICP: 2025-11-08 → 2026-04-20 (5.4 months)
- DASH: 2026-01-18 → 2026-04-20 (3.1 months)
- ZEC: 2025-10-02 → 2026-04-20 (6.7 months)
- Total: 15.2 pair-months

## Results

### Taker fees (realistic retail-tier execution)

**Every parameter combination is negative.** Best config:

| min_combined | min_hold (h) | net_total ($) | annualized %/pair |
|---|---|---|---|
| 0.0020 | 24 | −0.48 | **−0.13%/yr** |
| 0.0010 | 24 | −1.23 | −0.32%/yr |
| 0.0005 | 24 | −5.14 | −1.36%/yr |
| 0 | 0 (baseline) | −101.46 | **−26.77%/yr** |

The baseline (every hour, no filter) is catastrophic — 659 flips at $0.17 each chews
through every dollar of gross earn ($10.65 over 15 pair-months).

### Maker-only fees (HL maker rebate −0.01%, Binance maker 0.02%)

**Best config: +1.20%/yr per pair.**

| min_combined | min_hold (h) | net_total ($) | annualized %/pair |
|---|---|---|---|
| 0.0005 | 24 | +4.54 | **+1.20%/yr** |
| 0 | 24 | +4.06 | +1.07%/yr |
| 0.0005 | 8 | +3.39 | +0.89%/yr |
| 0.0010 | 24 | +2.07 | +0.55%/yr |
| 0 | 0 (baseline) | −2.54 | −0.67%/yr |

Even with a 24h min-hold filter, optimal maker execution clears 1.20%/yr per pair.

## Why this fails

1. **Gross earn is small.** Across 15.2 pair-months, gross funding harvest = $10.65 on
   $300 notional (3 pairs × $100). That's 3.5%/yr maximum gross signal — and that's
   IF you trade every hour with zero costs.

2. **Flip cadence is high.** 659 flips in 15.2 pair-months on no-filter baseline =
   1.4 flips/day per pair. Each flip is a full close+reopen across two venues = 4 leg
   trades. Even at maker rates these accumulate.

3. **Sign-divergence persistence is short.** Median time-in-position before sign flips
   back is ~5 hours. Below the 18-hour breakeven needed to amortize taker fees.

4. **Real maker fills on alt perps are unrealistic.** HL maker rebate exists but
   requires being top-of-book in low-liquidity alt orderbooks. ZEC/DASH/ICP HL volume
   is low — passive orders may not fill within the sign-divergence window.

5. **Capital efficiency is brutal.** Best case +1.20%/yr per pair × 3 pairs × $100
   notional = +$3.60/yr on ~$300 of locked margin. FundingFade's $50 live deploy
   produces +7.28% in 16 days on a single instrument.

## Sample-size caveats

- ICP and DASH overlap windows are short (3-5 months) — single regime, no winter/spring
  cycle representation.
- HL listing dates limit data availability. Older Binance funding history (2023-)
  cannot be used because HL didn't list these pairs yet.
- The first cross-venue analysis ([hyperliquid_spread_infra_2026-04-21.md]) found
  similar fee-friction failures across 65 pairs / 1.2M records — this is consistent
  with that broader finding, not a sample artifact.

## Verdict

**LANE #1 OF PATH A IS CLOSED.** Opposite-sign simultaneous earn on ICP/DASH/ZEC does
not produce a deployable bot at retail-tier fee structure. Even the optimistic
maker-only ceiling (+1.20%/yr) is two orders of magnitude smaller than fleet's
existing live edges (FundingFade ~18%/yr, Keltner backtest ~15%/yr) and requires
infrastructure (cross-venue maker provisioning) that is impractical at this scale.

## What this rules out vs leaves open

**Ruled out:**
- Trading the cross-venue funding spread *as a primary strategy* on ICP/DASH/ZEC.
- Deploying any version of this lane at retail taker fees.
- The maker-only escape hatch — even at theoretical ideal maker fees, ceiling is too low.

**Still open (Path A remaining lanes):**
- **Lane #2: >3σ short-duration dislocations.** Richer per-event signal (mean spread is
  small, but tail events may be large enough to cover fees). Worth ~3 days of focused
  analysis. Most defensible reformulation given lane #1's findings.
- **Lane #3: maker-only feasibility (RULED OUT EARLY).** The maker ceiling found here
  (+1.20%/yr) makes the engineering work to provision dual-venue maker fills not
  worth the prize.

## Recommendation

Move directly to **Lane #2 (>3σ short-duration dislocations)** — skip lane #3 entirely.
Pre-spec the test:
- Identify hours where `|b_8h| + |h_1h × 8| > 99th percentile` per pair
- Hold position for fixed window (e.g., 8h, 24h, 48h)
- Apply taker fees (don't bother with maker analysis given lane #3 dead)
- Pass criterion: net edge after fees > 5%/yr per pair on ≥2 pairs across the full
  overlap window AND survives a single-half OOS split

If Lane #2 also fails, **Path A is closed** and the moratorium extends to: "no live
research velocity available on retail-tier infra; the fleet IS the ceiling for this
project."

## Artifacts

- Simulator: `/tmp/opposite_sign_earn.py` (single-config), `/tmp/opposite_sign_earn_sweep.py` (parameter sweep)
- Run output: 40 configs × 3 pairs × 15.2 pair-months captured in this doc
- Source data:
  - `research/data/binance/funding/{ICP,DASH,ZEC}_USDT-funding.feather`
  - `research/data/hyperliquid/funding/{ICP,DASH,ZEC}_USDT-funding.feather`

## Related docs

- `docs/hyperliquid_spread_infra_2026-04-21.md` — original lane spec, naive backtest results
- `docs/keltner_abort_gate_policy_2026-05-09.md` — companion deployment policy doc
- `docs/keltner_regime_activation_gates_2026-05-09.md` — companion deployment policy doc
- Memory: `project_moratorium_revision_2026-05-09.md` — Path A/F sanction context
