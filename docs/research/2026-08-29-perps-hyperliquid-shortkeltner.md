# Perpetual Futures, Venue Microstructure, and the Conditional-Probability Trap: A Risk–Reward Analysis of `ShortKeltnerV2HL` on Hyperliquid

**Author:** Claude (Anthropic), prepared for the Master Trader research program
**Date:** 29 August 2026
**Status:** Internal research note. Contains original empirical computation. Not peer reviewed. No trading action taken or authorised by this document.

---

## Abstract

This note evaluates the perpetual futures contract as a trading instrument, examines how Hyperliquid's implementation differs from the centralised-exchange archetype, and assesses the risk–reward profile of `ShortKeltnerV2HL`, a short-side mean-reversion strategy deployed live on Hyperliquid with a 40 USDC dedicated account. Drawing on Pantera Capital's market analysis (Jiang & Poh, 2026), the perpetual-futures pricing literature (Ackerer et al., 2024), venue documentation, and original computation over 14,525 hourly observations spanning January 2025 to August 2026, three findings emerge. First, the instrument-level risks of Hyperliquid perps — oracle manipulation, socialised loss, and validator intervention — are real but are substantially mitigated by the strategy's restriction to BTC, ETH, and SOL, whose oracle prices derive from a five-venue weighted median. Second, the funding mechanism is a modest structural tailwind for a short: shorts on Hyperliquid received a mean 10.4% APR on BTC over the trailing sixty days, though over the strategy's 36-hour maximum holding period this amounts to only +0.043% of notional, an order of magnitude smaller than the 3.0% price target. Third, and decisively, the strategy's entry conditions are so conjunctively restrictive that they generated **four signals in twenty months across three instruments** — a rate of 0.20 trades per month. At that frequency, accumulating the thirty observations needed for even a naïve performance estimate would require approximately 12.5 years, and the strategy's economic ceiling (~6.5% annually under an implausible 100% hit rate) falls below the venue's own passive funding carry. The binding constraint is not the instrument, the venue, or the risk controls; it is a conditional-probability trap in which the entry trigger requires a local overbought condition while the macro gate requires a confirmed downtrend, two states that rarely co-occur.

**Keywords:** perpetual futures, funding rate, Hyperliquid, decentralised exchange, mean reversion, statistical power, conditional probability

---

## 1. Introduction

The Master Trader program operates six live strategies across two execution venues. Five are long-biased or signal-driven; one, `ShortKeltnerV2HL`, is the program's only structural short and its only autonomous strategy executing on a decentralised perpetual-futures venue. It was deployed to a bounded live epoch on 23 August 2026 with a dedicated Hyperliquid account funded with 40 USDC, following an extended dry-run period justified by the venue's inability to serve the historical data required by the program's validation workflow.

This note addresses four questions. §2 examines the perpetual futures contract as a financial instrument. §3 asks in what respects Hyperliquid's perpetuals constitute a *different* instrument rather than merely a different venue. §4 formalises the strategy. §5 presents original empirical analysis of its behaviour. §6 correlates that analysis with specific market episodes. §7 synthesises the risk–reward assessment, and §8 states limitations that materially qualify every quantitative claim made here.

---

## 2. The Perpetual Futures Contract

### 2.1 Origins and design intent

The perpetual futures contract descends from Shiller's (1993) proposal for perpetual claims on illiquid economic indices — real estate, human capital, consumer price levels — in which a periodic payment tied to observable cash flows would anchor the contract to its underlying without requiring settlement. Shiller's construction did not include the premium-versus-spot funding term that defines modern implementations (Elm Wealth, n.d.). The practical realisation arrived with BitMEX in 2016, which solved the problem of anchoring a never-expiring contract to spot using a periodic payment between position holders rather than a reference cash flow (Jiang & Poh, 2026).

### 2.2 The funding mechanism and its no-arbitrage anchor

In a perpetual contract, price convergence to spot is enforced by a funding payment exchanged directly between longs and shorts. When the contract trades above spot, longs pay shorts; when below, shorts pay longs. Basis arbitrageurs, who take the offsetting spot position, harvest this payment and in doing so compress the deviation.

Ackerer et al. (2024) provide the formal treatment. They derive closed-form no-arbitrage prices for linear, inverse, and quanto perpetuals in both discrete and continuous time, showing that

> "the futures price is given by the risk-neutral expectation of the spot sampled at a random time that reflects the intensity of the price anchoring" (Ackerer et al., 2024, abstract).

Two implications matter for a practitioner. First, the perpetual price is not the spot price; it is a spot expectation under a stochastic sampling clock whose intensity is set by the funding specification. Second, the authors identify funding specifications under which futures and spot prices coincide exactly, and show that under those specifications the perpetual is replicable by dynamic trading in primitive securities — that is, the contract adds no spanning value and its economic content reduces entirely to leverage and funding.

### 2.3 Structural advantages and market dominance

Relative to dated futures, perpetuals eliminate the roll: there is no expiry calendar, no term structure to manage, and no discontinuity at settlement. Relative to options, they eliminate time decay and volatility exposure, offering linear directional exposure. Jiang and Poh (2026) summarise the design economy: "A perp collapses that complexity into one continuous position with no expiries and thus nothing to roll."

The market has voted accordingly. Pantera reports centralised-exchange perpetual volume of approximately **$62 trillion** in 2025 against roughly **$19 trillion** of spot, within a total derivatives volume of **$86 trillion** — "Perps are the majority of the $86tn total derivatives trading volume, showing the market's preference of perps over options" (Jiang & Poh, 2026). Decentralised perpetual venues, below 1% of centralised volume in early 2023, reached **14%** by June 2026.

---

## 3. Hyperliquid Perpetuals: A Different Instrument, Not Merely a Different Venue

Hyperliquid launched in February 2023 on a purpose-built Layer 1 blockchain, founded by Jeff Yan, a former high-frequency trader. As of the Pantera analysis it held approximately **40% of on-chain perpetual market share**, roughly **$250 billion in monthly volume**, and **$800 million in annualised revenue** (Jiang & Poh, 2026). The following features distinguish its contract from the Binance-style archetype in ways that materially affect a strategy's realised economics.

### 3.1 Funding cadence and computation

Hyperliquid settles funding **every hour**, against the eight-hour cadence standard on Binance and Bybit. The rate is computed as

> "Funding Rate (F) = Average Premium Index (P) + clamp(interest rate − Premium Index (P), −0.0005, 0.0005)" (Hyperliquid, n.d.-a),

with the premium "sampled every 5 seconds and averaged over the hour," an interest component "predetermined at 0.01% every 8 hours, which is 0.00125% every hour, or 11.6% APR paid to short," and a cap of "4%/hour" — materially less aggressive clamping than centralised counterparts (Hyperliquid, n.d.-a).

Two consequences follow. First, a position opened and closed within the same hour pays no funding, while one held across an hour boundary pays the full hourly amount on the snapshot size (perp.wiki, 2026). Second, the hourly cadence produces a materially noisier rate series: Hyperliquid's BTC perpetual funding has been observed to be approximately **1.95× more volatile** than Binance's, with hourly maxima near 0.067% (BTC) and 0.075% (ETH) (perp.wiki, 2026).

Critically, the funding payment is computed as `position_size × oracle_price × funding_rate`, using "the spot oracle price … not the mark price" (Hyperliquid, n.d.-a). The venue therefore deliberately decouples the funding notional from its own order book.

### 3.2 Oracle and mark price construction

Hyperliquid maintains two distinct prices. The **oracle price** is a "weighted median of CEX prices" that "does not depend on hyperliquid's market data at all," updated roughly every three seconds by validators (Hyperliquid, n.d.-b). The **mark price** is a median of three inputs: the oracle adjusted by a 150-second EMA of the Hyperliquid-mid-to-oracle spread; the median of Hyperliquid's best bid, best ask, and last trade; and a weighted median of Binance, OKX, Bybit, Gate.io, and MEXC prices with weights 3, 2, 2, 1, and 1 respectively (Hyperliquid, n.d.-b).

The division of labour is consequential: the oracle drives funding, while the mark price drives "margining, liquidations, triggering TP/SL, and computing unrealized pnl" (Hyperliquid, n.d.-b). A strategy's stop-loss therefore triggers off a composite that *includes* Hyperliquid's own book, whereas its funding accrues off a composite that excludes it.

### 3.3 The HLP vault and socialised tail risk

Hyperliquid's liquidation backstop is the HLP (Hyperliquidity Provider) vault, a community-funded pool that absorbs positions from liquidations. This design substitutes a depositor-funded vault for the insurance fund of a centralised venue, and it transmits tail losses to depositors rather than to the exchange's balance sheet.

The March 2025 JELLY incident demonstrated the failure mode. A trader opened a large leveraged long in the low-liquidity JELLY perpetual while shorting the same asset, then pumped the spot price; the resulting liquidation transferred the short to HLP, leaving the vault involuntarily long a rapidly appreciating token, with unrealised losses reaching approximately **$13.5 million** (CoinDesk, 2025; Halborn, 2025). Validators convened and voted within roughly two minutes to delist JELLY and settle the market at $0.0095, far below the prevailing spot price, with the foundation reimbursing affected long positions (OAK Research, 2025). Commentators noted that the two-minute quorum revealed "a high level of centralization" (OneKey, 2025).

For the present analysis the lesson is specific rather than general: the attack vector required a thin oracle and a manipulable spot market. It is not available against BTC, ETH, or SOL, whose oracle prices are weighted medians across five major venues. **The strategy's pair restriction is, inadvertently or otherwise, its most important venue-risk control.**

### 3.4 Instrument comparison

| Dimension | Spot | Dated future | CEX perpetual (Binance) | Hyperliquid perpetual |
|---|---|---|---|---|
| Expiry / roll | None | Fixed; roll required | None | None |
| Funding cadence | n/a | Implicit in basis | 8 hours | **1 hour** |
| Funding notional | n/a | n/a | Mark price | **Oracle price** |
| Liquidation reference | n/a | Exchange mark | Exchange mark | Composite incl. own book + 5 CEX median |
| Backstop | n/a | Clearing house | Insurance fund | **HLP depositor vault** |
| Tail intervention | n/a | Exchange rules | Exchange discretion | **Validator vote (JELLY precedent)** |
| Custody | Exchange or self | Broker | Exchange | **Self-custody; API wallet trades, cannot withdraw** |
| Base fees | Varies | Varies | Varies | 0.015% maker / 0.045% taker (Hyperliquid Guide, 2026) |

The final row of self-custody deserves emphasis as a risk *reduction* relative to centralised venues: the deployment signs with an agent wallet that can trade but cannot withdraw, bounding counterparty and key-compromise loss to the funded balance.

---

## 4. The Strategy Under Analysis

### 4.1 Specification

`ShortKeltnerV2HL` is a short-side mean-reversion strategy on the 1-hour timeframe, restricted to BTC/USDC, ETH/USDC, and SOL/USDC perpetuals. An entry is signalled when all of the following hold on the closing bar:

1. **Band rejection.** Close crosses back below the upper Keltner band, defined as SMA(25) + 2.5 × ATR(25), having closed at or above it on the prior bar.
2. **Volume confirmation.** Bar volume exceeds 1.75 × SMA(20) of volume.
3. **Recent overbought.** RSI(14) exceeded 60 on either of the two prior bars.
4. **Macro bear gate.** BTC simultaneously satisfies four conditions: hourly close below its 1-hour SMA(50); below its 1-hour SMA(200); a negative 24-bar slope of the 1-hour SMA(50); and below its **daily** SMA(200).

Exits are governed by a ROI ladder (6%, 4%, 2.5%, 1.5%, 0% of margin at 0, 6, 12, 24, and 36 hours), a −5% stop, a signal exit on BTC regime flip or RSI below 30, and a hard 36-hour time exit. Leverage is capped at 2×; stake is 18 USDC with a maximum of two concurrent positions; the stop is exchange-resident with a 0.98 limit ratio.

### 4.2 Translation into price space

Freqtrade expresses ROI and stop thresholds as ratios of margin, so at 2× leverage every threshold corresponds to half that move in price:

| Threshold | Margin ratio | Required price move | Cash impact on 18 USDC |
|---|---|---|---|
| First ROI rung (0–6h) | +6.0% | −3.00% | +1.08 USDC |
| Second rung (6–12h) | +4.0% | −2.00% | +0.72 USDC |
| Third rung (12–24h) | +2.5% | −1.25% | +0.45 USDC |
| Fourth rung (24–36h) | +1.5% | −0.75% | +0.27 USDC |
| Stop loss | −5.0% | **+2.50%** | −0.90 USDC |

The trade is therefore, in price terms, a 3.0%-target against a 2.5%-stop with a 36-hour clock: a gross reward-to-risk ratio of approximately **1.2 : 1** before costs, decaying toward 1 : 3.3 if the position survives into the fourth rung. Maximum loss per position is 2.25% of the 40 USDC account; two concurrent positions place 72 USDC of notional against a 40 USDC balance, or 1.8× gross account leverage.

### 4.3 Cost stack

On 36 USDC of notional per position:

- **Fees.** Round-trip taker at 0.045% per side costs 0.032 USDC (0.18% of margin); round-trip maker at 0.015% costs 0.011 USDC. The live configuration posts limit orders but prices them at the opposite side of the book, so taker execution should be assumed.
- **Funding.** Own computation over the trailing sixty days of Hyperliquid hourly funding (n = 500 observations per instrument, retrieved 29 August 2026) gives mean rates of **+0.00119%/hour for BTC (10.4% APR), +0.00121% for ETH (10.6% APR), and +0.00098% for SOL (8.6% APR)**, positive in 99%, 100%, and 92% of hours respectively. Positive funding is paid *to* shorts. Over a full 36-hour hold this yields **+0.043% of notional for BTC (≈ +0.016 USDC)**.

Funding is thus a genuine but economically trivial tailwind at this holding period — roughly half the round-trip taker fee, and 1.4% of the 1.08 USDC target. The often-cited "shorts get paid on Hyperliquid" advantage is real for carry strategies measured in weeks; it is noise for a 36-hour directional trade.

---

## 5. Empirical Analysis

### 5.1 Method and its limits

All computations below were performed on 14,525 hourly and 972 daily Binance klines for BTCUSDT, ETHUSDT, and SOLUSDT spanning 1 January 2025 to 29 August 2026, retrieved from the public Binance API on 29 August 2026, plus Hyperliquid hourly funding history retrieved from the public `info` endpoint on the same date. The strategy's indicator stack (Keltner with SMA-based ATR, volume SMA, Wilder RSI, and the four-term macro gate) was reimplemented faithfully from source.

**This is not a backtest and must not be read as one.** Three limitations are disqualifying for any performance claim. (a) Binance USDT markets are a *proxy* for Hyperliquid USDC markets; prices for these three majors track closely, but **volume distributions differ materially**, and the volume filter is one of the binding entry conditions — signal timing on Hyperliquid will differ. (b) The analysis is conducted on hourly bars without 1-minute detail, which the program's own standards identify as a source of systematic error in path-dependent exit modelling. (c) Where a bar contains both the target and the stop, the outcome is unknowable at this resolution and has been scored conservatively as a loss.

What follows is therefore a **signal-frequency and structural analysis**, for which hourly data is adequate, and not an estimate of profitability, for which it is not.

### 5.2 The macro gate is open 18% of the time, in very short windows

| Period | Hours gate open / valid hours | Share |
|---|---|---|
| 2025 (Jan–Dec) | 898 / 8 561 | 10.5% |
| 2026 (Jan–Aug) | 1 710 / 5 765 | 29.7% |
| **Full sample** | **2 608 / 14 326** | **18.2%** |

(Valid hours exclude the initial warm-up window in which the 200-bar hourly average and its 24-bar slope are undefined.)

Monthly variation is wide: 0.0% in five separate months of 2025, against 47.3% in February 2026 and 44.4% in June 2026. The gate opened in **165 discrete episodes** with a **median duration of four hours**; the longest was 135 hours (1–7 June 2026). The distribution matters more than the mean: a four-hour median window means the gate is typically open for fewer bars than it takes for an independent entry trigger to appear.

Decomposing the conjunction reveals why it is so restrictive despite plausible-looking components:

| Sub-condition | Marginal frequency |
|---|---|
| Close < 1h SMA(50) | 48.5% |
| Close < 1h SMA(200) | 50.0% |
| 1h SMA(50) slope < 0 | 48.8% |
| Close < daily SMA(200) | 55.3% |
| **All four (gate open)** | **18.2%** |
| Without the daily SMA(200) term | 29.1% |
| Without the slope term | 22.2% |

### 5.3 The entry funnel: 149 candidates collapse to 4 signals

| Instrument | Band rejections | + volume filter | + RSI filter | + macro gate |
|---|---|---|---|---|
| BTC | 285 (1.97% of bars) | 59 | 59 | **1** |
| ETH | 266 (1.83%) | 45 | 45 | **2** |
| SOL | 286 (1.97%) | 45 | 45 | **1** |
| **Total** | **837** | **149** | **149** | **4** |

Two observations follow immediately.

**The RSI condition is entirely non-binding.** It removed zero of 149 candidates across all three instruments: every band rejection accompanied by a volume spike had already printed RSI above 60 within the prior two bars. The condition is dead weight in the specification — harmless, but it contributes nothing and creates a false impression of independent confirmation.

**The macro gate removes 97.3% of surviving candidates.** This single filter is the difference between a strategy that trades roughly seven times per month and one that trades once every five months.

### 5.4 Frequency under gate variants

The following table reports **signal counts only**. It is a diagnosis of where frequency is lost, **not** a performance comparison, and no variant below should be read as recommended: the program's standing methodological position is that selecting among variants on the basis of in-sample counts or returns is precisely the multiple-testing error that produced its earlier false discoveries.

| Gate variant | BTC | ETH | SOL | Total | Signals/month |
|---|---|---|---|---|---|
| V0 — current (all four terms) | 1 | 2 | 1 | **4** | **0.20** |
| V1 — drop daily SMA(200) | 1 | 4 | 1 | 6 | 0.30 |
| V2 — drop slope term | 1 | 3 | 1 | 5 | 0.25 |
| V3 — hourly SMA(200) only | 10 | 14 | 8 | 32 | 1.60 |
| V4 — no macro gate | 58 | 45 | 45 | 148 | 7.40 |

(V4 totals 148 against the funnel's 149 in §5.3 because the variant computation additionally requires the macro-gate inputs to be defined, excluding one early BTC candidate from the warm-up window.)

### 5.5 Statistical power: the decisive constraint

At the observed rate of 0.20 signals per month across the entire three-instrument portfolio:

- **N = 30** (a bare minimum for a naïve win-rate estimate): **≈ 12.5 years**
- **N = 100** (a plausible threshold for a deflated Sharpe ratio inference at this signal-to-noise level): **≈ 41.7 years**

The strategy's existing evidence base is recorded in the program's memory as failing a deflated Sharpe ratio test at N ≥ 4. The present analysis explains *why* that sample size was reached and why it will not grow: the design cannot produce observations fast enough to ever be validated. A strategy that requires four decades to falsify is, for practical purposes, unfalsifiable.

### 5.6 Economic ceiling

Combining frequency with the per-trade geometry of §4.2:

| Scenario | Trades/year | Expected annual P&L | Return on 40 USDC |
|---|---|---|---|
| 100% hit rate (impossible) | 2.4 | +2.59 USDC | +6.5% |
| 60% hit rate | 2.4 | +0.69 USDC | **+1.7%** |
| 50% hit rate | 2.4 | +0.22 USDC | +0.5% |
| Observed 1W/2L/1 timeout (N = 4, void) | 2.4 | negative | negative |

The benchmark that matters sits on the same venue: mean funding paid to shorts on BTC was **10.4% APR** over the trailing sixty days, and the program's own preregistered `hl-carry-extension` study passed 6/6 criteria across 194 episodes over 3.17 years, estimating **17.5% annually on majors** (with its shadow phase still gating any dry-run deployment). A delta-neutral carry position deployed on the same 40 USDC would, on that evidence, dominate the directional strategy's realistic outcome by roughly an order of magnitude — while the directional strategy additionally carries path risk that the carry position does not.

---

## 6. Market Episodes and Correlation with the Strategy

### 6.1 The cascade the gate filtered out: 10 October 2025

On 10 October 2025, an unscheduled announcement of 100% tariffs on Chinese imports triggered the largest liquidation cascade in the history of the instrument: approximately **$19 billion** of leveraged positions force-closed across roughly 1.6 million accounts within hours, of which about $16.7 billion were longs, collapsing total perpetual open interest 43% from $217 billion to $123 billion (FTI Consulting, 2025; Bitcoin.com News, 2025). Funding rates had climbed from roughly 10% to nearly 30% annualised in the preceding days, marking exactly the crowded-long condition a short strategy exists to exploit.

Own computation of the macro gate across that window:

| Date | Gate open | BTC close path |
|---|---|---|
| 2025-10-09 | 0 / 24 h | 122 839 → 121 662 (−1.0%) |
| **2025-10-10** | **0 / 24 h** | **121 745 → 112 774 (−7.4%)** |
| 2025-10-11 | 0 / 24 h | 112 515 → 110 644 (−1.7%) |
| 2025-10-12 | 0 / 24 h | 109 642 → 114 959 (+4.8%) |

The gate was **closed for every hour of the largest short opportunity in the instrument's history.** The reason is structural rather than accidental: BTC entered the cascade at approximately $122,000, far above its daily SMA(200), and a filter defined as "price below its long-run moving averages with negative slope" cannot by construction be open at a local high. The strategy pairs a *trend-following* macro filter with a *mean-reversion* entry trigger, and crashes from highs — the highest-payoff short regime — are systematically excluded.

### 6.2 The window with no trigger: 1–7 June 2026

The converse failure appeared in the sample's longest bear window. Between 1 and 7 June 2026 the gate was continuously open for 135 hours while BTC fell from 73,885 to 60,782, a decline of **17.7%** with a trough 19.6% below the window's open. The strategy generated **zero entries**. In a sustained directional decline, price does not stretch to the *upper* Keltner band, so the rejection trigger never fires.

Sections 6.1 and 6.2 together define the trap: the entry trigger requires a local overbought excursion, the macro gate requires a confirmed downtrend, and these two states are close to mutually exclusive in practice. The strategy is not merely selective; it is selecting on a near-empty intersection.

### 6.3 The four realised signals

| Date (UTC) | Instrument | 36-hour first-touch outcome |
|---|---|---|
| 2025-04-04 10:00 | BTC | Neither target nor stop; time exit |
| 2025-12-27 22:00 | SOL | Stop first |
| 2026-01-27 17:00 | ETH | Target first |
| 2026-03-28 14:00 | ETH | Stop first |

One target-first, two stop-first, one timeout. **This sample carries no inferential content whatsoever** (N = 4, hourly resolution, proxy venue) and is reported only for completeness. It is nonetheless consistent with the DSR failure already on record.

### 6.4 Regime context

BTC has declined from 87,809 to 77,590 year-to-date in 2026 (−11.6%), and the gate has been open 29.7% of hours in 2026 against 10.5% in 2025. The deployment year has therefore been *unusually favourable* to this design in regime terms — which strengthens rather than weakens the frequency finding, since even a favourable regime produced two signals in eight months.

---

## 7. Risk–Reward Assessment

### 7.1 Instrument and venue risk: well controlled

| Risk | Exposure | Mitigation in force |
|---|---|---|
| Oracle manipulation | Low | BTC/ETH/SOL oracles are five-venue weighted medians; the JELLY vector requires a thin market |
| Socialised loss / HLP | Low | Same; majors do not strand the vault |
| Validator intervention | Low but non-zero | JELLY precedent shows administrative settlement is possible; unquantifiable, accepted |
| Liquidation | Low | 2× leverage with a −5% margin stop triggers at a 2.5% adverse price move, far inside the liquidation band |
| Key compromise | Bounded | Agent wallet can trade but not withdraw; dedicated master account isolates position and margin |
| Funding volatility | Negligible at this horizon | 36-hour carry ≈ +0.04% of notional |
| Gap risk through the stop | Present | Exchange-resident stop with 0.98 limit ratio can be gapped through; unverified on this venue pending first fill |

The venue-level verdict is favourable. The design decisions already taken — majors only, 2× leverage, dedicated account, agent-wallet signing, exchange-resident stop — address the tail risks that the JELLY episode and the October 2025 cascade expose. The one item genuinely outstanding is empirical rather than analytical: no organic fill has yet occurred on this account, so the exchange-resident stop's actual placement on Hyperliquid remains unverified. (The equivalent verification was completed on the Binance-spot side on 28 August 2026, where a stop-limit order was confirmed resting at the venue.)

### 7.2 Strategy risk: the binding constraint

The strategy's problem is not that it loses money. It is that it does not generate enough observations to establish whether it makes money, and its frequency-adjusted ceiling is below the passive alternative available on the same venue with the same capital. Specifically:

1. **Frequency:** 0.20 signals/month portfolio-wide.
2. **Power:** 12.5 years to N = 30; 41.7 years to N = 100.
3. **Ceiling:** ~6.5% annually at an impossible 100% hit rate; ~1.7% at a favourable 60%.
4. **Opportunity cost:** ~10.4% APR observed funding carry; 17.5% in the program's own preregistered carry study.
5. **Specification defect:** the RSI term is non-binding (0 of 149 candidates removed).
6. **Design contradiction:** trend-following gate over mean-reversion trigger, empirically demonstrated in §6.1–6.2.

### 7.3 Interpretation

Item 6 is the finding of substance, and it is a design fact rather than a parameter-tuning matter. Two internally coherent designs exist. A **counter-trend short** would fade overbought excursions and should be gated on volatility or funding extremes, not on a confirmed downtrend — it would have been eligible on 10 October 2025. A **trend-continuation short** would sell weakness within a confirmed downtrend and should trigger on breakdowns rather than on upper-band rejections — it would have been eligible during June 2026. The current specification requires both conditions simultaneously and consequently trades in neither regime.

Relaxing the gate (variants V1–V3) would raise frequency, but selecting a variant on the evidence presented here would repeat the program's documented failure mode: choosing among specifications by in-sample counts, without preregistration, out-of-sample testing, or deflation for multiple comparisons. **The analytically honest position is that this strategy needs a redesign justified by a prior hypothesis, or retirement — not a loosened threshold.** Any such redesign falls under the program's Phase-3 validation bar and its preregistration requirements.

---

## 8. Limitations

1. **Proxy data.** Binance USDT klines substitute for Hyperliquid USDC candles. Price tracking is close for majors; **volume distributions are not comparable**, and volume is a binding filter. Signal counts on Hyperliquid will differ, plausibly materially.
2. **No 1-minute detail.** Path-dependent outcomes are modelled at hourly resolution, which the program's own standards identify as systematically misleading. All §6.3 outcomes are indicative only.
3. **No cost model in path analysis.** Fees, funding, slippage, and partial fills are excluded from the first-touch scoring.
4. **Sample specificity.** Twenty months spanning one major cycle turn; the gate's 18.2% open rate is not a stationary parameter.
5. **N = 4.** No inference about profitability is drawn, and none should be.
6. **Single-source claims.** Hyperliquid's market-share, volume, and revenue figures derive from a single interested source (Pantera Capital, an investor in the ecosystem) and are not independently verified here.

---

## 9. Conclusion

Perpetual futures are a genuine financial innovation whose economic content, as Ackerer et al. (2024) formalise, reduces to leverage plus a funding-determined anchoring intensity — and whose market adoption has surpassed that of every other derivative form in crypto. Hyperliquid's implementation differs from the centralised archetype in ways that are individually small but jointly consequential: hourly funding settled on an oracle notional, a mark price that blends its own book with a five-venue median, and a depositor-funded backstop whose tail behaviour is governed, as the JELLY episode showed, by a validator quorum that can act in two minutes. For a strategy trading only majors at 2× leverage from a dedicated, agent-signed account with an exchange-resident stop, these venue risks are well controlled.

The strategy's difficulty lies elsewhere. `ShortKeltnerV2HL` produced four signals in twenty months because it requires a local overbought rejection to coincide with a confirmed multi-timeframe downtrend — states that the October 2025 cascade and the June 2026 decline demonstrate are close to mutually exclusive. At 0.20 trades per month the design cannot be validated within a professional lifetime, and its economic ceiling sits below the passive funding carry available on the same venue with the same capital. The instrument is sound and the risk controls are sound; the entry logic embeds a conditional-probability trap. That is a design question, not a threshold question, and it should be resolved by a preregistered redesign or by retirement rather than by relaxing a gate.

---

## References

Ackerer, D., Hugonnier, J., & Jermann, U. (2024). *Perpetual futures pricing* (NBER Working Paper No. 32936). National Bureau of Economic Research. https://ideas.repec.org/p/nbr/nberwo/32936.html

Bitcoin.com News. (2025). *Liquidation cascades explained: How $19 billion in crypto vanished in a single day*. https://news.bitcoin.com/learning-insights/crypto-liquidation-cascades-explained/

CoinDesk. (2025, March 26). *HyperLiquid delists JELLY after vault squeezed in $13M tussle*. https://www.coindesk.com/markets/2025/03/26/hyperliquid-delists-jellyjelly-after-vault-squeezed-in-usd13m-tussle

CoinGecko. (n.d.). *How Hyperliquid's HLP vault turns market chaos into profit*. https://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis

Elm Wealth. (n.d.). *Perpetual futures: Mechanics, history and purpose*. https://elmwealth.com/perpetual-futures/

FTI Consulting. (2025). *Crypto crash October 2025: Leverage met liquidity*. https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity

Garcia Seuma, R. M. (2026). *Where does the criticality live? Early-warning signals are event-heterogeneous across seven crypto-perpetual liquidation cascades* (arXiv:2607.27070). arXiv. https://arxiv.org/html/2607.27070

Halborn. (2025). *Explained: The Hyperliquid hack (March 2025)*. https://www.halborn.com/blog/post/explained-the-hyperliquid-hack-march-2025

Hyperliquid. (n.d.-a). *Funding*. Hyperliquid Docs. https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding

Hyperliquid. (n.d.-b). *Robust price indices*. Hyperliquid Docs. https://hyperliquid.gitbook.io/hyperliquid-docs/trading/robust-price-indices

Hyperliquid Guide. (2026). *Hyperliquid fees 2026: 0.045% taker, 0.015% maker, and 4% off for life*. https://hyperliquidguide.com/guides/fees

Jiang, C., & Poh, C. (2026, June 2). *The rise of perps and Hyperliquid*. Pantera Capital. https://panteracapital.com/rise-of-perps-and-hyperliquid/

OAK Research. (2025). *Hyperliquid and the JELLY attack: Context, vulnerability and team solution*. https://oakresearch.io/en/analyses/investigations/hyperliquid-jelly-attack-context-vulnerability-team-solution

OneKey. (2025). *Lessons from the Hyperliquid JELLY incident*. https://onekey.so/blog/ecosystem/hyperliquid-jelly-incident-lessons/

perp.wiki. (2026). *Hyperliquid funding rates: Hourly settlement, mechanics & how to farm them*. https://perp.wiki/learn/hyperliquid-funding-rates-guide

Shiller, R. J. (1993). Measuring asset values for cash settlement in derivative markets: Hedonic repeated measures indices and perpetual futures. *The Journal of Finance, 48*(3), 911–931.

---

## Appendix A. Data and reproduction

| Series | Source | Retrieved | Observations |
|---|---|---|---|
| BTCUSDT 1h klines | Binance public REST `/api/v3/klines` | 2026-08-29 | 14 525 |
| BTCUSDT 1d klines | Binance public REST | 2026-08-29 | 972 |
| ETHUSDT, SOLUSDT 1h klines | Binance public REST | 2026-08-29 | 14 525 each |
| Hyperliquid funding history | `POST https://api.hyperliquid.xyz/info` (`type: fundingHistory`) | 2026-08-29 | 500 hourly per coin (BTC, ETH, SOL) |

Indicators were reimplemented from `ft_userdata/user_data/strategies/ShortKeltnerV2HL.py`: Keltner upper band as SMA(25) of close plus 2.5 × SMA-based ATR(25); volume SMA(20); Wilder RSI(14); macro gate per §4.1. First-touch scoring assumed short entry at signal-bar close, target at −3.0% and stop at +2.5% in price, evaluated over the subsequent 36 hourly bars, with same-bar ambiguity scored as a loss.

## Appendix B. Incidental observation

While reading the live configuration for §4.1, one non-analytical item was noted and is recorded here for the operator rather than acted upon: `ShortKeltnerV2HL-live.json` contains literal API-server credentials and a JWT secret (`jwt_secret_key`, `username`, `password`) alongside `force_entry_enable: true`. In production these three fields are overridden by environment variables supplied through `docker-compose.prod.yml`, so the deployed instance does not use them; the literals are nonetheless a latent hazard should the environment override ever be dropped, and they are committed to the repository. No change was made.
