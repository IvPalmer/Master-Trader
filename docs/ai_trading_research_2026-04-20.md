# AI-Driven & Algorithmic Crypto Trading Research — State of the Art, April 2026

**Scope:** what actually works for retail/prop crypto quants in 2025–2026, filtered for the user's stack (Freqtrade, Binance spot, 3.3yr 1m-detail engine, strategy lab, meta-labeling pipeline, funding-rate corpus for 89 pairs).
**Bias:** practitioner-grade sources (Robot Wealth / Edge Alchemy, BitMEX research, Kaiko, SSRN, arXiv). Hype is flagged explicitly.

---

## Top Recommendation: Cross-Venue Funding-Rate Spread (Binance vs. Hyperliquid)

The user already owns the adjacent skill (FundingFadeV1 directional funding edge) and has funding data wired in. The single highest-ROI idea in the current literature that fits this stack is **cross-venue funding arbitrage** — not naive delta-neutral on one venue (now dead per BitMEX), but trading the **spread** between Binance and Hyperliquid funding rates.

### Hypothesis
Funding rates on Binance and Hyperliquid are structurally different because the trader populations are different. Kris Longmore's Jan 2026 post ("Hyperliquid Carry Looks Trendy") shows the *same* carry signal that makes ~50% frictionless on Binance "goes nowhere" on Hyperliquid post-2024: on Hyperliquid, high funding often comes from *informed* "exit-liquidity" sellers dumping via perps, so the price move swamps the carry. On Binance, high funding comes from FOMO retail longs, which mean-revert as carry compensates.

That asymmetry is the edge. Concretely: when Hyperliquid funding significantly diverges from Binance funding for the *same* asset, **long the cheaper-funding venue, short the more-expensive-funding venue**. Boros / Pendle's data shows spreads frequently >20% APR, peaking 23–48% APR on BTC/ETH during 2025.

### Data requirements
- Funding rate feeds for both Binance and Hyperliquid (hourly Hyperliquid, 8-hourly Binance) — the user already has Binance; Hyperliquid is a free public REST/WS endpoint.
- No L2 order book needed — funding is already published.
- Historical Hyperliquid funding back to Aug 2023 (launch) — ~2.5 years, shorter than the 3.3yr corpus but adequate for CPCV with 5–6 splits.

### Rough implementation plan
1. **Data adapter** in `ft_userdata/data/` to pull Hyperliquid funding history (one-off) and live (cron). Align to Binance's 8h grid for backtest sanity.
2. **Backtest as a synthetic spread**: reuse the existing lab framework but the P&L is `funding_received_hl - funding_paid_bn + price_change_hl - price_change_bn` (spot leg on Binance, perp short on Hyperliquid, or both perp with opposing signs).
3. **Entry rule:** spread > some threshold (e.g. 10% APR difference, annualised). **Exit rule:** spread decays back to 0 or threshold reversal. Use the existing triple-barrier / meta-labeling infra to size.
4. **Walk-forward with CPCV** (López de Prado; `mlfinlab` is already on the roadmap). This matters because funding-spread regimes change — Aug 2025 is nothing like post-Oct-2025.

### Risk of decay/overfit
- **Oct 10–11 2025 ADL cascade** (see decay warnings below) is the dominant tail risk. Hyperliquid's ADL is aggressive and will kill the short leg exactly when you need the hedge. Mandatory: stress-test on that week specifically before sizing.
- Funding-rate arb yields have compressed from ~19% (2024) to ~5.98–11.4% fixed APR (Boros 2025). The edge is smaller than headlines suggest but real. Medium-confidence, not a gold rush.
- Carry sign **inverts on Hyperliquid** for some assets — do not symmetrise the signal across venues.

### Sources
- Kris Longmore, "Hyperliquid Carry Looks Trendy" (Feb 2026): https://edgealchemy.robotwealth.com/p/hyperliquid-carry-looks-trendy
- Pendle/Boros research on cross-exchange funding arb, 2025: https://medium.com/boros-fi/cross-exchange-funding-rate-arbitrage-a-fixed-yield-strategy-through-boros-c9e828b61215
- pi2 Network, "Arbitrage Opportunities in Perpetual DEXs": https://blog.pi2.network/arbitrage-opportunities-in-perpetual-dexs-a-systematic-analysis/
- BitMEX State of Perpetual Swaps 2025: https://www.bitmex.com/blog/2025q3-derivatives-report

---

## #2: VPIN / Order-Flow-Toxicity as an *Entry Filter*, Not a Standalone Signal

The user already flagged VPIN as a deferred research lane. 2025–2026 literature has matured: the Bitcoin wild-moves paper (Nov 2025) shows **VPIN significantly predicts price jumps with positive serial correlation**, and Binance Futures OFI backtests from Jan 2022–Oct 2025 show taker *and* maker strategies profitable on BTC.

### Hypothesis
Don't trade VPIN alone — use it as a **veto** on existing signals (Keltner, FundingFade). Mean-reversion strategies historically fail in toxic-flow regimes because apparent overextension is actually informed one-sided pressure that *keeps going*. VPIN > 0.7 is the warning band. Gate Keltner entries on VPIN ≤ 0.6 and expect fewer but cleaner trades.

### Data requirements
- This is the honest constraint. VPIN needs **trade data with signed volume** (BVC bulk-volume classification works on 1-minute aggregates as a fallback). OFI needs L2 order book snapshots.
- BVC-VPIN from 1-min OHLCV+volume is feasible with existing data (free). True OFI requires tick-level L2 (~$200–$500/mo from CoinAPI/Tardis for the 20 pairs).
- Algoindex (algoindex.org) publishes pre-computed VPIN/Kyle-λ/OFI for 25+ instruments every 5 min — cheapest on-ramp.

### Rough implementation plan
1. Start cheap: compute BVC-VPIN on existing 1m data for the 20 pairs. One-week spike, not a month-long build.
2. Add `vpin_ok` gate to Keltner entries in the lab; grid-scan thresholds 0.5 / 0.6 / 0.7.
3. Expect 20–40% fewer trades but stronger PF on the surviving ones. If it shrinks Keltner's known weak spots (2023-H2, 2024-H2 chop), ship it.
4. Validate with CPCV — VPIN filter is exactly the kind of single extra knob that overfits easily.

### Risk of decay/overfit
- BVC-VPIN is a degraded proxy for tick-level VPIN; the edge might live entirely in the tick data and die at 1m. Must compare.
- VPIN distributions are regime-dependent — a fixed threshold will need recalibration.

### Sources
- "Bitcoin wild moves: Evidence from order flow toxicity and price jumps" (ScienceDirect 2025): https://www.sciencedirect.com/science/article/pii/S0275531925004192
- Buildix, "What Is VPIN? Flow Toxicity Detection for Crypto Traders": https://www.buildix.trade/blog/what-is-vpin-flow-toxicity-crypto-trading
- VisualHFT, "VPIN and Real-Time Order Toxicity": https://www.visualhft.com/blog/vpin-real-time-order-toxicity-what-your-execution-stack-cannot-see
- Algoindex: https://algoindex.org/

---

## #3: Weekend-Momentum Long on Altcoins (with HMM Regime Gate)

Lowest infra cost of the three. The *Advances in Consumer Research* 2025 paper (data Jan 2020 – Apr 2025) reports that **crypto momentum returns are significantly higher on weekends**, with altcoins showing a bigger differential than BTC/ETH, *and* higher Sharpe + lower max-DD. The driver is clean: retail-dominated weekend flow + thin institutional liquidity.

### Hypothesis
Long weekend momentum (Fri 20:00 UTC → Sun 20:00 UTC, top-decile 7-day return altcoins) gated by an HMM regime classifier trained on BTC returns + realised vol. Skip the trade in "bear/ranging" regime; take it in "bull". Non-homogeneous HMM is the current best-fit per Preprints.org 2026. Two-state (bull/bear) outperforms three-state despite being coarser.

### Data requirements
- Already have it: 1m data on 20 pairs, 3.3 years. No new data needed.
- `hmmlearn` or `pomegranate` in Python.

### Rough implementation plan
1. Train 2-state HMM on BTC daily log-returns + 7d realised vol, walk-forward re-train annually.
2. Lab backtest: weekend-momentum cross-sectional long on top-decile 7d return altcoins, held Fri close → Sun close, gated on HMM = bull.
3. Size via meta-labeling (triple-barrier labels already in place per MEMORY.md).
4. Compare CPCV Sharpe to directional buy-and-hold on same regime filter.

### Risk of decay/overfit
- Anomaly is **retail-flow dependent**. If retail flow structure changes (more institutional weekend algos), it decays.
- Only 5 years of data — 260 weekends. Danger of fitting to a handful of outliers. Deflated Sharpe mandatory.
- Known weakness: a single crypto can blow up a cross-sectional momentum book (momentum crashes are a documented crypto effect). Cap per-name at 10% of book.

### Sources
- "Weekend Effect in Crypto Momentum" (Advances in Consumer Research, 2025): https://acr-journal.com/article/the-weekend-effect-in-crypto-momentum-does-momentum-change-when-markets-never-sleep--1514/
- "Markov and Hidden Markov Models for Regime Detection in Cryptocurrency Markets (2024–2026)" (Preprints.org): https://www.preprints.org/manuscript/202603.0831
- QuantInsti HMM + RF regime-adaptive trading: https://blog.quantinsti.com/regime-adaptive-trading-python/

---

## Dead Ends (skip)

- **"Vibe quant" / LLM-authored strategies.** Kris Longmore's "More of the Disease, Faster" (2026) and "Brave New Backtest" show LLMs flood the pipeline with false discoveries; they have no theory of edge and cannot distinguish a statistical mirage from a structural opportunity. Architecturally bad at tracking time-varying variables ("Unable to Forget" paper). https://edgealchemy.robotwealth.com/p/more-of-the-disease-faster
- **Naive delta-neutral funding yield on one venue.** Dead. Yields compressed to ~4% (below T-bills) per BitMEX. User already proved this with their own failed PoC.
- **Deep RL end-to-end signal generation.** 2025 arXiv systematic review: naive P&L-reward RL consistently negative in bearish regimes; DDPG unstable; simpler models beat complex ones. State of the art is RL for *execution* (slippage/fill optimisation), not for *signal*. https://arxiv.org/html/2512.10913v1
- **DEX/CEX gas-fee arbitrage for retail.** Profits eaten by gas + withdrawal fees at retail size. Documented in every 2025 guide.
- **Single-venue cash-and-carry as a standalone business.** Same reason as naive delta-neutral.
- **Bitcoin monthly seasonality ("September effect" etc.).** Coinbase Research Sep 2025 monthly: statistically insignificant, dominated by single-outlier years (e.g. 2013 November +449%).
- **Grid bots / DCA bots as sold in consumer-bot marketplaces.** The "best bot" ventureburn-style listicles are SEO affiliate content, not practitioner signal.

---

## New Decay Warnings (setups that stopped working in the last 6 months)

1. **Oct 10–11 2025 ADL cascade.** $19–20B liquidation in ~40 min; 70% of liquidations in one 40-min window; Hyperliquid ADL triggered 35,000 events across 20,000 users and 161 tokens. USDe traded at ~$0.65 on Binance. This event **broke delta-neutral strategies** that relied on short-leg persistence; market-makers got stuffed with inventory. Any strategy sized without modelling this regime is under-reserved. https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity
2. **Funding-rate compression post-2025.** BitMEX: exchange-native delta-neutral products (Ethena et al) flood markets with structural short flow, compressing funding to ~4% annualised. Passive yield strategies dead; spread/relative-value approaches live. https://www.bitmex.com/blog/2025q3-derivatives-report
3. **Carry-signal inversion on Hyperliquid.** Per Longmore, the Binance carry signal does not generalise — informed-trader population differs by venue. Do not port strategies across venues without re-validation.
4. **Mean-reversion (incl. Bollinger / Keltner) degrades in persistent-trending or persistent-toxic-flow regimes.** Already flagged in user's memory from SSRN 5775962; reinforced by VPIN literature. The Keltner weak spots (2023-H2, 2024-H2) are exactly the toxic-flow periods.
5. **Market-maker inventory overhang (Jan 2026).** BitMEX flags order-book depth at post-2022 lows; market makers stuffed with coins post-Oct crash. Expect worse slippage and wider spreads than 2023–2024 backtests imply. Lab slippage assumptions may need a 1.5–2× haircut for any 2026-forward forward-test.

---

## Infrastructure the user already has that de-risks all three ideas

- 3.3yr 1m-detail backtest engine (sufficient for weekend-momentum; adequate-with-caveats for cross-venue funding).
- Strategy lab with 4940-combo grid (reusable for VPIN gate sweeps).
- Meta-labeling pipeline (`ft_userdata/meta_labeling/`) — the sizing layer for all three ideas.
- DSR analysis (`dsr_analysis_v2.py`) — already proved the lab ranking is luck. Mandatory to rerun on any new candidate.
- Freqtrade native + Viability wrapper for calibration.

## What's missing (rank-ordered by ROI)

1. Hyperliquid funding history loader (~1 day of work).
2. BVC-VPIN computation on 1m candles (~2–3 days).
3. `hmmlearn` regime labelling pipeline (~1–2 days).
4. CPCV wrapper around the lab — currently walk-forward only (~3–5 days; `mlfinlab` handles most of it).

---

## Sources
- [Kris Longmore, Edge Alchemy](https://edgealchemy.robotwealth.com/)
- [Kris Longmore — Hyperliquid Carry Looks Trendy](https://edgealchemy.robotwealth.com/p/hyperliquid-carry-looks-trendy)
- [Kris Longmore — More of the Disease, Faster](https://robotwealth.com/more-of-the-disease-faster-what-happens-when-you-ask-an-llm-to-find-you-an-edge/)
- [BitMEX State of Perpetual Swaps 2025](https://www.bitmex.com/blog/2025q3-derivatives-report)
- [Kaiko Research — Crypto in 2026](https://research.kaiko.com/insights/crypto-in-2026-what-breaks-what-scales-what-consolidates)
- [FTI — Crypto Crash Oct 2025 forensics](https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity)
- [Navnoor Bawa — How hedge funds extracted alpha from Oct 2025 cascade](https://navnoorbawa.substack.com/p/how-hedge-funds-basis-traders-and)
- [Bitcoin wild moves — order flow toxicity / VPIN (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/pii/S0275531925004192)
- [VisualHFT — VPIN and order toxicity](https://www.visualhft.com/blog/vpin-real-time-order-toxicity-what-your-execution-stack-cannot-see)
- [Weekend Effect in Crypto Momentum (2025)](https://acr-journal.com/article/the-weekend-effect-in-crypto-momentum-does-momentum-change-when-markets-never-sleep--1514/)
- [HMM regime detection in Bitcoin markets 2024–2026 (Preprints.org)](https://www.preprints.org/manuscript/202603.0831)
- [López de Prado / Bailey — Deflated Sharpe Ratio (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Boros — Cross-exchange funding rate arbitrage](https://medium.com/boros-fi/cross-exchange-funding-rate-arbitrage-a-fixed-yield-strategy-through-boros-c9e828b61215)
- [pi2 Network — Arbitrage Opportunities in Perpetual DEXs](https://blog.pi2.network/arbitrage-opportunities-in-perpetual-dexs-a-systematic-analysis/)
- [Algoindex — microstructure features](https://algoindex.org/)
- [arXiv 2512.10913 — RL in Financial Decision Making: Systematic Review](https://arxiv.org/html/2512.10913v1)
- [Dobrynskaya — Cryptocurrency Momentum and Reversal (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3913263)
- [Beluská & Vojtko — Revisiting Trend-following and Mean-Reversion in Bitcoin (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4955617)
- [Algorithmic crypto trading: information-driven bars + triple barrier + DL (Financial Innovation 2025)](https://link.springer.com/article/10.1186/s40854-025-00866-w)
