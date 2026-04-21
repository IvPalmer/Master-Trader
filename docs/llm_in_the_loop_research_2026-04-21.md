# LLM-in-the-Loop Trading: Evidence Survey 2026-04-21

## TL;DR (Lead verdict)

**LLM-in-the-loop trading is ~90% cycle hype and ~10% a narrow, legitimate research lane.** The strongest peer-reviewed evidence is for LLMs as **feature extractors from unstructured data** (news/filings → sentiment → systematic signal). Every other architecture — especially the Herkelman-style "LLM picks trades discretionarily" pattern — has no credible long-horizon track record and fails under rigorous out-of-sample evaluation that controls for lookahead bias. **Recommendation: do not open this as a research lane for a $400 crypto fleet.** The signal-to-noise ratio is worse than the phase-3 items already rejected (VPIN, CPCV, regime gate).

---

## Architecture ranking (strongest → weakest evidence)

| # | Architecture | Evidence quality | Verdict |
|---|---|---|---|
| 1 | **Feature extraction from unstructured text** (news/filings → sentiment → systematic model input) | Multiple peer-reviewed papers, mixed but real results | Real but narrow; equities only; news-driven tickers |
| 2 | **Research assistant / signal proposer** (LLM proposes hypotheses, human/system validates) | Practitioner evidence (Longmore, Chain-of-Alpha paper) | Real productivity aid; not a signal source |
| 3 | **Regime classification** (LLM reads macro context, gates existing strategies) | Thin evidence; mostly framework papers, no public track record | Speculative |
| 4 | **Parameter selection** (LLM tunes hyperparameters from context) | Essentially zero rigorous evidence; same overfitting risks as hyperopt | Unvalidated |
| 5 | **Discretionary trader** (LLM reads news, picks trades — Herkelman pattern) | FINSABER (arXiv 2505.07078) benchmarks show systematic failure | **Vaporware at scale** |

The gap between #1 and #5 is enormous. Most viral "Claude made me rich" content is #5 without any of the controls that matter.

---

## Top 3 credible findings

### 1. Lopez-Lira & Tang (2023, revised 2025): GPT sentiment on post-cutoff headlines has forecasting power

- arXiv 2304.07619, now widely cited, under review at top finance journals.
- Sampled news 2021-10 → 2024-05, deliberately *after* GPT's training cutoff to prevent memorization.
- Result: GPT-4 scores predict next-day returns, strongest on **small stocks + negative news**. ~90% hit rate on the non-tradable initial reaction; drift captures a meaningful portion.
- **Honest caveat the authors acknowledge**: most of the edge is in the first minutes after headline release — a latency game that retail cannot win against news-API-wired HFT.
- Source: https://arxiv.org/abs/2304.07619

### 2. Chain-of-Alpha (arXiv 2508.06312, Aug 2025): LLM-guided formulaic alpha mining on CSI 500/1000

- Dual-chain LLM iteratively proposes + refines formulaic factors, validated on Chinese equity indices.
- Annualized return 13.2%–14.7%, Information Ratio 1.40–1.42 on CSI 500/1000.
- The LLM here is **architecture #2** (research assistant) — it writes candidate factor formulas, standard IC/IR backtests validate.
- This is what's real: LLMs accelerate factor *proposal*, traditional quant validates.
- Source: https://arxiv.org/abs/2508.06312

### 3. FINSABER (arXiv 2505.07078, May 2025): LLM timing strategies collapse under broad, long evaluation

- 20 years of data, 100+ symbols, survivorship-bias-controlled.
- **FinAgent**: Sharpe 0.12 bull / -0.38 bear. **FinMem**: -0.19 / -0.97.
- No LLM strategy beats passive in bull regimes. "LLM advantages reported in recent studies often vanish under broader and longer evaluations."
- Best negative-result paper in this space — the LLM equivalent of an F&G backtest busting a fake edge.
- Source: https://arxiv.org/abs/2505.07078

---

## Top 3 red-flag findings

### 1. Herkelman-style / Polymarket Claude "beat SPY by 8%" claims

- All documented Polymarket viral wins (OpenClaw, "$1,400 → $238K in 11 days", "$1 → $3.3M") share the same pattern: small sample, no on-chain strategy disclosure, survivorship.
- Protos and MEXC reporting on the "bet No" Polymarket bot shows its creator **keeps losing money** over any window longer than the viral clip.
- 92.4% of Polymarket wallets are unprofitable (>50K wallet study). The viral winners are selection artifacts.
- Herkelman's 30-day +8% vs SPY with 6 positions = **N≈6**. On a t-stat this is indistinguishable from noise.
- Sources: https://protos.com/this-bot-only-bets-no-on-polymarket-and-its-creator-keeps-losing-money/

### 2. Lookahead bias is the #1 methodological sin and nearly all non-peer-reviewed LLM backtests commit it

- arXiv 2309.17322 (Glasserman): even sentiment scores on pre-cutoff news "know" what happened — GPT has memorized earnings outcomes.
- arXiv 2512.23847 ("A Test of Lookahead Bias in LLM Forecasts"): 1σ LLM prediction = 0.197% next-day return driven primarily by memorization. Subtract training-period overlap → signal largely evaporates.
- **DatedGPT** (arXiv 2603.11838) exists precisely because standard LLMs are unusable for honest backtests without rebuilding them with strict temporal cutoffs. No retail trader can do this.
- Any LLM backtest that doesn't use post-cutoff data or temporally-partitioned models is untrustworthy by default.
- Sources: https://arxiv.org/abs/2309.17322, https://arxiv.org/html/2512.23847v1

### 3. LLM trading agents are trivially adversarially attackable (TradeTrap, arXiv 2512.02261)

- Prompt injection into news feed → panic sells / irrational buying cascades.
- Tool-calling LLMs "overreact to rich but corrupted signals."
- In crypto especially, every news source is adversarial — X posts, Telegram, pump groups. A live LLM trading agent is a liability surface, not an edge surface.
- Also: Oct 2025 Bloomberg / Exploring Sentiment Manipulation (arXiv 2502.16343) shows LLM agents *learn to manipulate* each other's sentiment inputs in multi-agent simulations. The attack surface is inherent.
- Source: https://arxiv.org/abs/2512.02261

---

## What serious funds actually do (for calibration)

- Two Sigma: LLMs for alt-data processing (satellite imagery OCR, social-media aggregation). **Not** as a discretionary trader. LLM output is a feature for downstream models.
- Renaissance: publicly silent but widely believed to use transformer models on text features. Architecture #1, not #5.
- The pattern across all credible institutional LLM usage: **LLM = encoder/featurizer, not decision-maker**.
- This confirms architecture #1 is the only lane with institutional validation.

---

## Feasibility for the user's stack

### Why architecture #1 (the only legit lane) doesn't fit the user

The evidence base for LLM feature extraction is **US equities, news-driven**. The infrastructure required:

1. **News API with timestamp-accurate headlines**: Bloomberg Event-Driven Feed ($$$), Benzinga Pro (~$200/mo), or noisy free Twitter/RSS.
2. **Post-training-cutoff data discipline**: either DatedGPT-style partitioned models (not available to retail) or accepting that every backtest before model cutoff is contaminated.
3. **Equity universe**: the effect concentrates in small caps with news shocks. Crypto doesn't have the equivalent — funding events, governance proposals, and exchange listings don't produce the same news-surprise distribution, and any edge compresses in seconds.
4. **Tick/sub-minute data**: the Lopez-Lira edge lives in minutes 1-15 post-headline. With 1m OHLCV as the finest resolution, you're arriving after the edge is gone.

**On crypto specifically**: the only positive crypto-LLM paper (arXiv 2510.08068 and similar) reports Sharpe ~1.08 with 21.75% annualized — worse than the user's existing Keltner bot (PF 1.58, +51% over 3.3yr). And those papers haven't been validated by an independent group or gone live.

### If the user insisted on trying it

Minimum viable integration to do it *honestly*:
- Benzinga Pro or similar timestamped news API: ~$200–500/mo.
- Crypto-news tagger (ETH/BTC/specific-pair headlines).
- Anthropic API for scoring (free at current usage; meaningful cost at volume).
- Backtest window strictly after Claude's training cutoff (currently Jan 2026 per environment). **That gives ~3 months of OOS as of 2026-04-21.** Not enough to reject noise.

This fails the user's own graduation criteria: cannot produce 12+ months of honest OOS, cannot validate Viability+PF+WF with 3 months of data, and news feed adds a $200+/mo overhead for a $400 dry-run fleet.

---

## Failure modes (ordered by how often they kill LLM trading in practice)

1. **Lookahead bias from training-data contamination** — almost every casual backtest commits this
2. **Overfitting / data snooping** — LLMs trained on finance text encode the same style factors everyone already knows; "novel" proposed alphas are often rediscoveries
3. **Latency** — post-news edge dies in minutes; retail is structurally late
4. **Adversarial inputs** — news/social feeds are gameable and getting more gameable
5. **Hallucination on numerical reasoning** — the Polymarket "67% support in a poll that doesn't exist" case is representative
6. **Regime dependence** — FinAgent/FinMem collapse in bear markets; Herkelman's 30-day window happens to be bull

---

## Honest conclusion

**Do not open LLM-in-the-loop as a phase 4+ research lane.**

Reasoning:

1. The only architecture with credible evidence (feature extraction from equity news) is structurally mismatched with the user's asset class, data resolution, and capital base.
2. The viral Claude-trader content (Herkelman, Polymarket) belongs in the same bucket as the Supertrend +$14 "regime luck" discovery that already cost the user weeks of work — high-variance short-window samples being mistaken for edge.
3. The user has already exhausted the phase-3 PoC trilogy with three negative results. Adding another lane with a worse prior distribution than VPIN or CPCV is a misallocation of research budget.
4. The stable-checkpoint rule ("no new research unless a bot live-fails and the engine is the root cause") was written for exactly this kind of shiny-new-object temptation.

**What *is* legitimate use of Claude here**: exactly what the user is already doing — Claude Code as a research assistant (architecture #2) writing/reviewing backtest code, reading papers, stress-testing assumptions. This is where the real practitioner evidence (Longmore's "AI will create millions of quants" — bearish on autonomy, bullish on supervised use) points. That use is already in place and needs no new infrastructure.

**Revisit trigger** (the only condition to reopen this):
- A peer-reviewed paper demonstrates LLM-derived crypto signal with ≥12 months OOS post-model-cutoff, independent replication, Sharpe >1.3 net of fees, on 1h or coarser resolution.
- Until then: watch-mode on Keltner + FundingFade.

---

## Sources

- [Lopez-Lira & Tang, Can ChatGPT Forecast Stock Price Movements? (arXiv 2304.07619)](https://arxiv.org/abs/2304.07619)
- [FINSABER: Can LLM-based Financial Investing Strategies Outperform the Market in Long Run? (arXiv 2505.07078)](https://arxiv.org/abs/2505.07078)
- [Chain-of-Alpha (arXiv 2508.06312)](https://arxiv.org/abs/2508.06312)
- [Glasserman: Look-Ahead Bias in GPT Sentiment (arXiv 2309.17322)](https://arxiv.org/abs/2309.17322)
- [A Test of Lookahead Bias in LLM Forecasts (arXiv 2512.23847)](https://arxiv.org/html/2512.23847v1)
- [DatedGPT: Time-Aware Pretraining (arXiv 2603.11838)](https://arxiv.org/abs/2603.11838)
- [TradeTrap: LLM Trading Agents Under Adversarial Perturbation (arXiv 2512.02261)](https://arxiv.org/abs/2512.02261)
- [Exploring Sentiment Manipulation by LLM Intelligent Trading Agents (arXiv 2502.16343)](https://arxiv.org/html/2502.16343v1)
- [Large Language Model Agent in Financial Trading: A Survey (arXiv 2408.06361)](https://arxiv.org/html/2408.06361v2)
- [Kris Longmore / Robot Wealth — "More of the Disease, Faster" (LLMs for edge)](https://robotwealth.com/more-of-the-disease-faster-what-happens-when-you-ask-an-llm-to-find-you-an-edge/)
- [Kris Longmore — "AI Will Create Millions of Quants" (Edge Alchemy)](https://edgealchemy.robotwealth.com/p/ai-will-create-millions-of-quants)
- [Protos: "bet No" Polymarket bot keeps losing money](https://protos.com/this-bot-only-bets-no-on-polymarket-and-its-creator-keeps-losing-money/)
- [Explainable zero-shot multi-agent LLM Bitcoin trading (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0306457325004078)
