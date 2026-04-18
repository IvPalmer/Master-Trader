# Delta-Neutral FundingFade — Research PoC

**Date**: 2026-04-18
**Status**: FAIL (decisive)
**Artifacts**: `ft_userdata/delta_neutral_poc/` (simulate.py, results.json, trades_*.csv)

## TL;DR

Converting FundingFadeV1 from a directional SPOT long into a delta-neutral
SPOT-long + PERP-short carry trade **destroys the edge across every hold
horizon tested (8h / 16h / 24h / 48h), in both the literal and mirrored
construction**. Directional variant returns +82% over 3.3yr; delta-neutral
returns −33%. The problem isn't execution — it's that FundingFade's entry
triggers capture **price mean-reversion**, not **funding-rate carry**. The two
are orthogonal. Stripping out the price exposure removes 100% of the edge;
what's left (gross funding carry ~1.1 bps per trade) cannot cover 24 bps of
round-trip taker + slippage cost. Do not deploy this, and do not pursue a
refined version without a fundamentally different signal.

---

## Methodology

### Signal (matches live FundingFadeV1)
- 1h timeframe, 19 non-BTC pairs from live whitelist (ADA, ARB, AVAX, BCH, BNB, DOGE, ENA, ETH, HBAR, LINK, LTC, NEAR, SOL, SUI, TAO, TRX, UNI, XRP, ZEC).
- Entry: `funding_rate < rolling_mean_500 − 1σ` AND `ADX(14) > 25` AND `volume > 1.5 × SMA(20)` AND BTC > SMA50 AND BTC > SMA200.
- Max 3 concurrent positions, no duplicates per pair.
- Period: 2023-01-01 → 2026-04-16 (3.29 yr).

### Delta-neutral payoff model
- `funding_pnl_pct = −Σ funding_rate` across 8h settlements (00/08/16 UTC) inside the hold window — perp short receives when funding>0, pays when <0.
- Fees: 0.04% × 4 legs (spot buy, spot sell, perp open, perp close) = 0.16%.
- Slippage: 0.02% × 4 legs = 0.08%.
- Round-trip cost floor: **24 bps**.
- `net_pct = funding_pnl_pct − 24 bps`.
- Stake: $66.67 per slot (matches live $200 / 3 slots).

### Directional baseline
- Same entry signal, spot-only, fixed hold window (for apples-to-apples comparison).
- Cost: 12 bps round-trip (2 legs spot only).
- Not the exact live ROI ladder — but same regime-sensitivity profile.

### Documented simplifications (honest list)
1. **Ignores spot-perp basis drift** — assumes perfect hedge. Reality: basis whips during stress (Oct 10-11 2025 ADL is the canonical counterexample; we cannot simulate ADL).
2. **No borrow cost on spot** — spot-long does not pay borrow on Binance, so this is fine for the literal construction. The mirror (spot-short) is physically infeasible on Binance without margin borrow — included as theoretical sanity check only.
3. **No funding-rate prediction model** — our entry is *extreme low funding*, a point predicting near-term mean reversion. The directional strategy profits when the *price* reverts. Funding reverts too, but the carry earned inside a 24h window is tiny because funding is already mid-reversion.
4. **No pairlist dynamics** — static 19-pair whitelist. Minor effect; live DynamicPairlistMixin would slightly reduce trade count but not change the sign of the result.
5. **Fixed hold window** replaces live ROI ladder. Tested 8/16/24/48h sensitivity; result is consistent.
6. **No ADL / forced liquidation simulation** — perp short is assumed to survive all price moves. For delta-neutral this is a HIGHLY favorable assumption; reality punishes harder.

---

## Results

### Full-period comparison (hold = 24h; other horizons in results.json)

|                       | Delta-neutral | Directional |
|-----------------------|--------------:|------------:|
| Trades                |           433 |         433 |
| Win rate              |          2.1% |       51.0% |
| Profit factor         |         0.011 |        1.43 |
| Total return          |       −33.05% |      +82.29% |
| CAGR                  |       −11.63% |      +20.33% |
| Max drawdown          |       −33.00% |      −15.03% |
| Sharpe                |         −8.86 |        1.10 |
| Sortino               |         −8.11 |        1.23 |
| Calmar                |         −0.35 |        1.35 |
| Avg trade             |        −0.23% |       +0.57% |
| Median trade          |        −0.25% |       +0.08% |

Delta-neutral is **uniformly destroyed**. Sharpe is negative-single-digits (not
borderline). Every horizon tested shows the same pattern; longer holds only
amortize the fee hit slightly (48h DN: −27.9% vs 8h DN: −41.7%).

### Why it fails — the decomposition

Per trade, averaged over 433 trades at 24h hold:
- Gross funding PnL (short perp): **+0.011% (1.1 bps)**
- Round-trip fees + slippage: **−0.24% (24 bps)**
- Net: **−0.23%**

Gross funding carry at these entry triggers is ~22× smaller than transaction
costs. The signal is timed such that funding is *already at its extremum*;
over the next 8–48h it reverts toward zero, so the area under the funding
curve is minuscule. Tested mirror construction (perp LONG + spot SHORT, which
would collect when funding < 0): identical failure with flipped sign. No
symmetric construction works.

### Regime breakdown (hold = 24h)

|              | DN trades | DN ret | DN PF  | DD trades | DD ret | DD PF |
|--------------|----------:|-------:|-------:|----------:|-------:|------:|
| Positive BTC 30d funding | 395 | −30.35% | 0.011 | 395 | +64.56% | 1.37 |
| Negative BTC 30d funding | 38  | −2.70%  | 0.016 | 38  | +17.73% | 2.11 |

Critical: in the **current 46-day negative-funding regime**, the directional
strategy has historically performed *better than average* (PF 2.11 on the 38
bear-regime trades across 2023-2026). The premise that delta-neutral would
*protect* FundingFade during the current regime is wrong on two counts:
1. Directional doesn't need protection — it has been a top performer when
   funding is broadly negative (38 trades, 17.7% return subset).
2. Delta-neutral loses in both regimes; the negative-regime subset is
   slightly less bad only because it has fewer trades.

### Oct 10-11 2025 ADL cascade

Only **1 trade** fired in the 2025-10-08 to 2025-10-15 window (signal gates
were largely off — BTC broke below SMA50 during the cascade, shutting off the
macro filter). DN: −0.09%, DD: −0.35%. Both negligible — this specific week
is not a meaningful stress test because FundingFade's own macro gate
protected it. Not evidence for or against delta-neutral robustness.

---

## Verdict: **FAIL**

Against the pre-declared criteria:
- DN Sharpe > directional Sharpe? **NO** (−8.86 vs +1.10)
- DN DD < 15%? **NO** (33.0%)
- DN positive in negative-funding regime? **NO** (−2.7%)

Not marginal. Not a refinement target. The signal premise is incompatible
with carry-harvest mechanics.

## Why no refined version is worth testing

The core issue is structural:

1. FundingFade's edge is a **price-reversion** edge, not a **funding-carry** edge. The funding-rate indicator is a sentiment proxy for crowded positioning; the *profit* comes from the price squeeze when crowding unwinds. Delta-neutralizing kills the only thing that pays.
2. A "real" delta-neutral funding harvester (Hummingbot-style) waits for *sustained* funding extremes of larger magnitude (~3–5 bps per 8h period) and harvests across days/weeks. It does not filter on ADX + volume + macro trend. The two strategies share one input (funding rate) but are otherwise unrelated.
3. To build a real DN carry bot we would need: (a) a funding-persistence predictor, (b) basis-monitoring exit rules, (c) liquidation/ADL awareness, (d) cross-exchange optionality (BitMEX research shows yield compressed to ~4% in 2025, on par with UST).
4. Research synthesis (2026-04-18) already flagged this: *"Naive delta-neutral = dead. Our 1h + TA confirm variants still viable but edge shrinking."* The directional FundingFade IS the "1h + TA confirm variant." This PoC confirms the naive path is closed.

## Recommendation

- **Kill this track**. Do not build further.
- **Keep directional FundingFadeV1 running** — backtest shows it performs fine in negative-funding regimes historically. The current 46-day streak may still bite (we are effectively long beta in a bear), but that's a different concern than "delta-neutralize to protect it."
- **Redirect the effort**: the research synthesis doc's top-ranked Phase 3 items (DSR on Lab shortlist, meta-labeling PoC on MT) remain higher-ROI unexplored paths.
- **If delta-neutral funding carry is ever revisited**, it needs a purpose-built signal (predicting 3d+ funding-rate persistence, not 1h mean-reversion) and must be benchmarked against the 1Token × Bybit Quant Strategy Index (~4% annualized yield baseline for crypto cash-and-carry).

## Files

- `ft_userdata/delta_neutral_poc/simulate.py` — reproducible simulation (no Docker / Freqtrade deps).
- `ft_userdata/delta_neutral_poc/results.json` — full metric dump across all 4 hold horizons, with regime + ADL breakdowns.
- `ft_userdata/delta_neutral_poc/trades_delta_neutral_{8,16,24,48}h.csv` — individual trade ledgers.
- `ft_userdata/delta_neutral_poc/trades_directional_{8,16,24,48}h.csv` — directional baseline trade ledgers.
