# Cross-Venue Funding Spread Infrastructure — 2026-04-21

**Status**: Infrastructure BUILT, preliminary signal analysis AMBIGUOUS — below fee-friction threshold at naive execution, needs deeper study before a full Phase 3 validation pass.

## Summary

Downloaded Hyperliquid perpetual funding-rate history and built a cross-venue spread
analysis pipeline as the first step in testing the "trade the spread, not the level"
hypothesis (Kris Longmore, Feb 2026: same carry signal profits on Binance but loses on
Hyperliquid due to exit-liquidity informed flow).

Headline result: the Binance-minus-Hyperliquid funding spread is statistically present
(65 pairs matched, 1.2M records, 2023-05-12 → 2026-04-20) but its magnitude — typically
1-3 bps per hour at the pairs with the largest mean spreads — is well below the
round-trip fee friction (~29 bps) of a naive long-Binance-spot / short-Hyperliquid-perp
execution. The Sharpe 20 printed by the naive backtest is unit-inflated: hourly
funding-differential units with tiny stddev, not executable PnL.

## Infrastructure shipped

| Asset | Path |
|-------|------|
| Hyperliquid loader | `ft_userdata/download_hyperliquid_funding.py` |
| Cross-venue spread analysis | `ft_userdata/analysis/cross_venue_funding_spread.py` |
| Hyperliquid funding data | `ft_userdata/user_data/data/hyperliquid/funding/*.feather` (65 pairs) |
| Per-pair stats CSV | `docs/artifacts/cross_venue_funding_spread.csv` |

65 pairs matched on both venues (24 skipped — HL doesn't list them). Total 1,223,867 HL
funding records. Hyperliquid funding settles **hourly**, Binance **8-hourly** — the
analysis resamples both to common hourly cadence via forward-fill on Binance.

## Key findings

### Pairs with largest absolute mean spread

| Pair | n_hours | mean_spread | std | % Binance premium >1σ | % HL premium >1σ | % opposite sign |
|------|---------|-------------|------|----------------------|------------------|-----------------|
| AVNT | 5056 | +0.000070/hr | 0.000223 | 5.2% | 0.6% | 13.7% |
| BIO | 11313 | +0.000037/hr | 0.000255 | 3.8% | 0.2% | 20.0% |
| WIF | 19737 | -0.000024/hr | 0.000116 | 1.2% | 4.2% | 19.9% |
| SUPER | 21006 | +0.000021/hr | 0.000251 | 2.4% | 0.2% | 18.0% |
| ORDI | 21463 | -0.000019/hr | 0.000043 | 1.8% | 9.0% | 16.3% |
| TAO | 17645 | -0.000018/hr | 0.000045 | 3.0% | 7.8% | 18.9% |
| ZEC | 4706 | -0.000018/hr | 0.000061 | 2.6% | 6.9% | 30.8% |
| DASH | 2204 | +0.000017/hr | 0.000123 | 4.2% | 1.1% | 33.5% |
| NEAR | 21527 | -0.000016/hr | 0.000038 | 3.7% | 10.1% | 21.3% |
| TIA | 21629 | -0.000015/hr | 0.000048 | 6.1% | 9.2% | 24.1% |

### Opposite-sign pairs (arbitrage candidates)

Three pairs have opposite funding signs ≥30% of the time — meaning when Binance is
charging longs, HL is paying them (or vice versa). Richest setup for a bidirectional
spread harvest:

| Pair | % opposite sign | binance_mean | hl_mean | n_hours |
|------|----------------|--------------|---------|---------|
| ICP | 34.4% | -0.000018 | -0.000016 | 3908 |
| DASH | 33.5% | -0.000019 | -0.000036 | 2204 |
| ZEC | 30.8% | -0.000018 | 0.000000 | 4706 |

DASH and ICP both have sub-year HL histories, so these stats are fragile. ZEC has 4700+
hours and is the most statistically defensible.

### Naive backtest result

Signal: go short funding where it's premium (`spread > mean + 2σ` on 30-day rolling).
Position held for the single hour where signal fires. No fees, no slippage.

- Portfolio (65 pairs, 2023-05-12 → 2026-04-20): total return 0.0292 in funding-diff
  units, Sharpe 20.14, max DD -0.000026.
- Top per-pair Sharpe: XLM 14.88, WLFI 14.40, ADA 14.23, POL 13.23, PNUT 12.94.

**These Sharpe numbers are unit-inflated and should be ignored.** The hourly return
series is ~99% zeros with ~1% tiny positive hits. Any ratio-of-moments statistic will
blow up. The meaningful number is **total return**, which ranges 0.007-0.039 on
top-10 pairs — i.e., 0.7%-3.9% cumulative funding-differential captured across a
3-year window at 3-5% time-in-position.

## Why this likely FAILS on fee math

Naive execution requires:
1. Long spot on Binance (pay/receive Binance spot taker 0.1%)
2. Short perp on Hyperliquid (pay HL taker ~0.05%)
3. Exit both legs (same fees again)

Round-trip fee: **~0.29%** per complete position.

Top mean-spread observations are 0.007%/hr (AVNT). To cover 0.29% in fees you need to
hold the position for ~41 hours at maximum spread — but signals only fire for brief
1-2 hour dislocations. **Edge-minus-fees is negative** on this naive structure.

### Where the signal MIGHT still work

1. **Maker-only execution**: if you can provide liquidity on both venues, HL maker can
   be -0.02% (rebate), Binance maker 0.02%. Round-trip drops to ~0.08%. Marginal.
2. **Bigger dislocations**: the analysis thresholds at >1σ. >3σ events (far rarer but
   much larger) may have favorable edge/fee ratio. Not yet tested.
3. **Opposite-sign pairs**: ICP/DASH/ZEC — harvest Binance NEGATIVE funding (longs
   getting paid) while holding HL short that pays similarly negative funding. Both
   legs EARNING simultaneously. This is the real hypothesis worth testing.
4. **Carry persistence**: hold position through multiple 8-hour Binance settlements
   during regime windows rather than single-hour opportunistic trading.

## Verdict

**AMBIGUOUS — do not open Phase 3 validation pass yet.** The infrastructure is
in place and the data is real, but the naive signal fails the fee-friction test.
Before a full lab + WF + calibration run, the hypothesis needs to be reformulated:

- Test **opposite-sign simultaneous earn** on ICP/DASH/ZEC with realistic fees.
- Test **large-deviation (>3σ) short-duration plays** where per-hour spread is large
  enough to cover friction.
- Research **maker-only execution** feasibility on both venues — does Hyperliquid
  have reliable maker fills at scale on these pairs?

None of these are quick. Each needs a focused analysis pass. Cheaper than building
more infra — the infra is done.

## What to do next

- **Keep the data and pipeline** — it's real infra, not dead weight. Useful for any
  future cross-venue work (basis trade, cash-and-carry, liquidation-cascade
  forensics on the Oct 10-11 2025 event).
- **Don't deploy a bot** — no signal validated.
- **Opposite-sign simultaneous-earn is the best honest follow-up**, when/if appetite
  returns. 3 candidate pairs, small universe, easier to backtest rigorously than 65
  pairs of marginal spread noise.

## Caveats

- HL history varies dramatically by pair (2023-05 for BTC/ETH, mid-2025 for ASTER/AVNT/WLFI). Cross-venue stats for young tokens have high variance.
- Hyperliquid's "funding" includes their proprietary impact-adjusted component that's
  not identical to Binance's index-based calc. Raw arithmetic difference is a first
  approximation, not a perfect arb equation.
- Forward-fill resampling gives Binance funding the same value for 8 consecutive
  hours; this slightly smooths the spread in each direction but doesn't change sign
  or magnitude statistics.
- Retail-accessible Hyperliquid execution on low-cap pairs (AVNT, BIO) is thin; real
  fills will have higher slippage than fees alone suggest.
