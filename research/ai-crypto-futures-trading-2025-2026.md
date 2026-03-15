# AI-Powered Cryptocurrency Futures Trading: 2025-2026 Research Report

**Compiled: 2026-03-13**

---

## Table of Contents
1. [AI Models for Futures Trading](#1-ai-models-for-futures-trading)
2. [High-Conviction "Sniper" Strategies](#2-high-conviction-sniper-strategies)
3. [Signal Generation: Features That Matter](#3-signal-generation-features-that-matter)
4. [Entry/Exit Precision: State of the Art](#4-entryexit-precision-state-of-the-art)
5. [Successful Projects, Papers, and Open-Source Systems](#5-successful-projects-papers-and-open-source-systems)
6. [Optimal Timeframes](#6-optimal-timeframes)
7. [Key Takeaways and Practical Recommendations](#7-key-takeaways-and-practical-recommendations)

---

## 1. AI Models for Futures Trading

### 1.1 Reinforcement Learning (RL) — The Leading Approach

RL is the dominant paradigm for AI futures trading in 2025-2026. A systematic review of 167 studies (2017-2025) found cryptocurrency trading has the second-highest RL performance premium at 0.375, behind only market making (0.488).

**Best RL Algorithms by Application:**

| Algorithm | Strengths | Crypto Performance |
|-----------|-----------|-------------------|
| **PPO (Proximal Policy Optimization)** | Constrains policy updates, prevents catastrophic drops | Sharpe ratio 2.15 +/- 0.05 in portfolio optimization |
| **SAC (Soft Actor-Critic)** | Entropy-regularized, robust in noisy markets | Greater stability than DDPG; auto-balances exploration/exploitation |
| **Rainbow DQN** | Combines 6 improvements over standard DQN | Best for discrete action spaces (buy/sell/hold) |
| **A2C (Advantage Actor-Critic)** | Multi-timeframe portfolio construction | Used in crypto futures portfolio system across 18 assets |

**Critical finding from the meta-analysis:** Algorithm choice is nearly irrelevant compared to implementation quality. The importance scores were:
- Implementation quality: **0.92**
- Domain expertise: **0.85**
- Data quality: **0.19**
- Algorithm selection: **0.08**

In other words, a well-implemented DQN with proper domain knowledge will beat a poorly-implemented PPO every time.

**RL Performance Benchmarks:**
- Backtests spanning 2024-2026: Sharpe ratios exceeding 2.0, max drawdowns below 15%
- Hybrid RL approaches (RL + traditional quant): Sharpe 1.57 vs pure RL 1.35 vs traditional 0.95
- Risk control agents detected volatility spikes and reduced exposure by 60%, preventing larger losses

**Source:** [Reinforcement Learning in Financial Decision Making: Systematic Review (2025)](https://arxiv.org/html/2512.10913v1)

### 1.2 Temporal Fusion Transformers (TFT)

TFTs are the state-of-the-art supervised learning approach for crypto price prediction. They process multiple input streams (price, on-chain metrics, sentiment, macro) with built-in attention mechanisms that provide interpretability.

**Adaptive TFT Performance (ETH-USDT, 10-min intervals):**
- Adaptive TFT: **51.36% directional accuracy**, 17.22% profit over test period
- Standard LSTM: 49.15% accuracy, 12.43% profit
- Standard TFT: 47.75% accuracy
- Buy-and-hold: 8.32% profit

The adaptive approach dynamically segments time series based on volatility patterns rather than using fixed windows. The key finding: **volatility rate** was the single most important feature, capturing "the most salient dynamics" for high-frequency pattern categorization.

**Source:** [Adaptive TFT for Cryptocurrency Price Prediction (2025)](https://arxiv.org/abs/2509.10542)

### 1.3 LSTM + XGBoost Hybrid

This combination leverages LSTM for temporal sequence patterns and XGBoost for non-linear feature interactions. A 2025 paper proposed using XGBoost for feature selection from market variables and technical indicators, feeding into LSTM + Double DQN for buy/sell decisions.

**Live performance data (FreqAI framework, 3-week test):**
- XGBoost: **+7% profit** over 3 weeks
- CatBoost: +2% profit (and significantly slower training)
- XGBoost was faster for both training and inference, critical for 5-minute retraining cycles

**Source:** [Emergent Methods: XGBoost vs CatBoost Real-Time Study](https://emergentmethods.medium.com/real-time-head-to-head-adaptive-modeling-of-financial-market-data-using-xgboost-and-catboost-995a115a7495)

### 1.4 Limit Order Book (LOB) Transformers

The newest frontier. LiT (Limit Order Book Transformer) uses dual attention to capture spatial (across price levels) and temporal dependencies in LOB data for short-term prediction.

**Critical finding: Simple models beat deep networks on LOB data.**

A 2025 study on BTC/USDT LOB snapshots found:
- XGBoost + Savitzky-Golay filtering: **72.8% accuracy** (binary, 500ms horizon)
- DeepLOB (complex neural net): 71.9% accuracy
- Logistic Regression + filtering: competitive at ternary classification

The paper concluded: "Data quality, noise-handling assumptions, and training methodology drive performance far more than model complexity."

**Source:** [Exploring Microstructural Dynamics in Cryptocurrency LOBs (2025)](https://arxiv.org/html/2506.05764v2)

### 1.5 GANs for Data Augmentation

TimeGAN generates synthetic financial time series preserving autoregressive properties. Used to augment limited crypto training data, particularly for rare events like liquidation cascades.

### 1.6 Regime Detection Models

**RegimeNAS** (2025) introduces regime-aware architecture search for crypto trading:
- Classifies markets using ADX (trend strength) + ATR (volatility)
- **Trending:** ADX > 20, MA difference > 0.3x ATR
- **Ranging:** ADX < 25, price range ratio < 0.03
- **Volatile:** BB width > 1.5x average, ATR > 1.2x average
- **Quiet:** BB width < 0.8x average, ATR < 0.9x average

k-Means and Gaussian Mixture Models (GMM) are the primary clustering techniques, with GMM preferred for soft/probabilistic regime boundaries useful in risk management.

**Source:** [RegimeNAS: Regime-Aware Architecture Search (2025)](https://arxiv.org/html/2508.11338v1)

---

## 2. High-Conviction "Sniper" Strategies

### 2.1 What Makes a "Sniper" Strategy

High-conviction strategies for leveraged futures require:
- **Win rate > 55-60%** (University of Toronto threshold for profitable scalping)
- **Tight stops** (2-5 ticks for scalping, 1-2% for swing)
- **Selective entry** — fewer, higher-quality trades vs high-frequency
- **Asymmetric R:R** when possible (though 1:1 is standard for scalping)

### 2.2 Liquidation Cascade Hunting

The October 10-11, 2025 cascade erased $19 billion in open interest in 36 hours, liquidating 1.6 million traders. AI models can detect buildup conditions:

- **Detection lead time:** AI detected the October 2025 downturn **112 minutes early** in simulations
- **Key signals:** Extreme positive funding rates + rising OI = overleveraged longs ripe for cascade
- **AI reduces defaults by 20-30%** but cannot predict exogenous shocks (tariff announcements, etc.)
- **Practical alpha:** Position against the crowd when funding rates hit extremes + OI is elevated

**Source:** [Anatomy of the Oct 2025 Crypto Liquidation Cascade (SSRN)](https://papers.ssrn.com/sol3/Delivery.cfm/5611392.pdf?abstractid=5611392)

### 2.3 Order Flow Imbalance Sniping

Order flow imbalance is the **#1 predictive feature** for short-term price direction, contributing 43.2% to feature importance in microstructure models.

**Strategy pattern:**
1. Monitor L2/L3 order book for aggressive buy/sell imbalance
2. Confirm with volume delta (aggressive buying vs selling)
3. Enter on imbalance confirmation, exit on reversion
4. AI-enhanced footprint charts improve VWAP breach prediction by 20%+

**Source:** [ML for Crypto Market Microstructure Analysis (Amberdata)](https://blog.amberdata.io/machine-learning-for-crypto-market-microstructure-analysis)

### 2.4 Multi-Timeframe Regime-Filtered Entries

The highest-ROI improvement documented in practice:
1. Use 1h/4h for regime classification (trending/ranging/volatile)
2. Only take trades aligned with regime (trend-following in trends, mean-reversion in ranges)
3. Use 1m-5m for precise entry timing
4. AI models re-train every 1-6 hours to adapt to regime shifts

### 2.5 Funding Rate Arbitrage + Directional Overlay

When funding rates are extremely positive (>0.1%/8h):
- Longs are paying shorts heavily
- Market is overleveraged long
- High probability of mean reversion / long squeeze
- AI monitors for divergence between spot and perp prices

---

## 3. Signal Generation: Features That Matter

### 3.1 Feature Importance Rankings (from 2025 research)

**Tier 1 — Highest Predictive Power:**
| Feature | Importance | Source |
|---------|-----------|--------|
| Order flow imbalance | 43.2% | LOB microstructure studies |
| Volatility rate (realized) | Primary feature | Adaptive TFT paper |
| Funding rate extremes | High | Derivatives signal research |
| Open interest changes | High | Combined with funding rates |
| Liquidation heatmap levels | High | CoinGlass/Amberdata analysis |

**Tier 2 — Strong Predictive Power:**
| Feature | Notes |
|---------|-------|
| Bollinger Bands | Consistently top in XGBoost feature importance |
| Exponential Moving Averages | Fast-reacting, preferred for scalping |
| Market cap metrics | Macro-level regime signal |
| Volume profile / VWAP | Institutional footprint detection |
| ATR / ADX | Regime classification (trend strength + volatility) |

**Tier 3 — Supplementary:**
| Feature | Notes |
|---------|-------|
| Sentiment scores (NLP) | Useful for swing trades, less for scalping |
| On-chain metrics | Transaction volume, whale movements |
| Macroeconomic indicators | Regime-level (tariff announcements, Fed decisions) |
| Cross-asset correlations | BTC dominance, DXY, S&P 500 correlation |

### 3.2 Derivatives-Specific Signals

**The "Trifecta" for futures trading (well-documented in 2025):**

1. **Funding Rate** — When extreme positive, shorts are paid; when extreme negative, longs are paid. Reversion signal.
2. **Open Interest** — Rising OI + price rise = genuine trend. Rising OI + extreme funding = overleveraged, cascade risk.
3. **Liquidation Levels** — Liquidation heatmaps show price levels with concentrated stop-losses. Price gravitates toward liquidity pools.

**Combined framework accuracy:** Integrated frameworks combining all three achieved "substantially higher accuracy than relying on single indicators alone."

**Source:** [How Futures OI, Funding Rates, and Liquidation Data Predict Crypto Price Movements (Gate.io)](https://web3.gate.com/crypto-wiki/article/how-do-futures-open-interest-funding-rates-and-liquidation-data-predict-crypto-price-movements-20251226)

### 3.3 LOB Features and Depth

Using 40-level LOB data achieved **71.5% accuracy** vs 57.9% with 5-level data — a massive gap. But this requires low-latency data feeds typically available only on exchanges like Hyperliquid or via premium APIs.

For practical implementation:
- **T=10 snapshots** (1-second of history at 100ms intervals) improved F1 by ~2% over T=1
- Savitzky-Golay filtering essential for noise reduction
- Real-time latency constraints dominate: prediction must be faster than forecast horizon

---

## 4. Entry/Exit Precision: State of the Art

### 4.1 How AI Improves Over Traditional TA

| Aspect | Traditional TA | AI-Enhanced |
|--------|---------------|-------------|
| Entry timing | Fixed indicator thresholds | Dynamic thresholds adapted to current regime |
| Exit timing | Static take-profit/stop-loss | Adaptive exits based on predicted price distribution |
| Position sizing | Fixed % or Kelly criterion | Volatility-aware dynamic sizing (PPO agent reduced exposure 60% during spikes) |
| Feature processing | 2-5 indicators manually combined | 50-200+ features processed simultaneously |
| Adaptation speed | Manual parameter tuning | Re-trains every 1-6 hours automatically |

### 4.2 VWAP Execution with Deep Learning

A 2025 paper introduced deep learning for VWAP execution in crypto, bypassing intermediate volume curve prediction to directly optimize execution quality. AI improves VWAP breach prediction accuracy by 20%+.

**Source:** [Deep Learning for VWAP Execution in Crypto Markets (2025)](https://arxiv.org/html/2502.13722v1)

### 4.3 Adaptive Stop-Loss and Take-Profit

State-of-the-art systems use:
- **Predicted volatility envelopes** rather than fixed percentages
- **Time-weighted exits** — wider stops early in trade, tightening as time passes
- **Regime-conditional exits** — wider in trending markets, tighter in ranging
- **RL-optimized exits** — the agent learns optimal exit timing as part of the reward function

### 4.4 The "Sniper Entry" Pipeline

Best practice for high-precision leveraged entries in 2025-2026:

```
1. REGIME FILTER (1h/4h)
   -> ADX + ATR classify market state
   -> Only trade if regime matches strategy type

2. SIGNAL GENERATION (5m/15m)
   -> XGBoost/TFT processes 50+ features
   -> Outputs probability of direction + confidence score
   -> Only trigger if confidence > threshold (e.g., 65%)

3. ENTRY TIMING (1m)
   -> Order flow imbalance confirmation
   -> LOB analysis for optimal price level
   -> Funding rate check (avoid crowded trades)

4. POSITION SIZING
   -> RL agent or Kelly criterion adjusted for regime volatility
   -> Scale with confidence score
   -> Hard max leverage cap

5. EXIT MANAGEMENT
   -> Predicted take-profit from price distribution model
   -> Adaptive trailing stop (wider in trend, tighter in range)
   -> Time-based forced exit (prevent holding losers)
   -> Liquidation level monitoring (exit before cascade reaches you)
```

---

## 5. Successful Projects, Papers, and Open-Source Systems

### 5.1 Open-Source Frameworks

**FinRL (AI4Finance Foundation)**
- GitHub: https://github.com/AI4Finance-Foundation/FinRL
- 14k+ stars, actively maintained
- Three-layer architecture: market environments, RL agents, applications
- FinRL Contests 2023-2025 attracted 200+ participants from 100+ institutions
- Reduced overfitting by 46% vs traditional methods (AAAI '23)
- Supports PPO, SAC, DDPG, A2C with Stable-Baselines3 and RLlib
- **Best for:** Research-grade RL trading experimentation

**FreqAI (Freqtrade)**
- GitHub: https://github.com/freqtrade/freqtrade
- Built into Freqtrade, supports XGBoost, CatBoost, LightGBM, PyTorch
- **Proven live results:** +7% in 3 weeks with XGBoost
- Retrains models on rolling windows (configurable, typically every few hours)
- **Best for:** Production deployment with existing Freqtrade infrastructure

**Passivbot**
- GitHub: https://github.com/enarjord/passivbot
- Python + Rust, perpetual futures specialist
- Evolutionary algorithm optimizer iterates thousands of backtests
- v7.5+ includes Sharpe/Sortino-based optimization metrics
- Runs on Bybit, Bitget, OKX, GateIO, Binance, Hyperliquid
- **Best for:** Grid/DCA futures strategies with automated parameter optimization

**OctoBot**
- GitHub: https://github.com/Drakkar-Software/OctoBot
- AI connectors for OpenAI and Ollama models
- TradingView integration, 15+ exchanges including Hyperliquid
- **Best for:** Accessible AI-enhanced trading without deep ML expertise

**Intelligent Trading Bot (asavinov)**
- GitHub: https://github.com/asavinov/intelligent-trading-bot
- 1.4k stars, feature engineering focused
- ML signal generation with automated feature derivation
- Two-phase: offline training + online streaming
- **Best for:** Feature engineering research and experimentation

**Hummingbot**
- GitHub: https://github.com/hummingbot/hummingbot
- High-frequency market making and arbitrage specialist
- Community-driven, supports custom strategies
- **Best for:** Market making and arbitrage on crypto futures

### 5.2 Key Academic Papers (2025)

| Paper | Key Finding | Link |
|-------|------------|------|
| Cryptocurrency Futures Portfolio Trading (MDPI, 2025) | A2C RL across 18 crypto futures, high-freq vs low-freq timeframe categorization | [Link](https://www.mdpi.com/2076-3417/15/17/9400) |
| Adaptive TFT for Crypto Prediction (arXiv, 2025) | 51.36% accuracy, 17.22% profit, volatility rate as primary feature | [Link](https://arxiv.org/abs/2509.10542) |
| RL Systematic Review — 167 Studies (arXiv, 2025) | Implementation quality >> algorithm choice; hybrid approaches best | [Link](https://arxiv.org/html/2512.10913v1) |
| LOB Microstructure Dynamics (arXiv, 2025) | XGBoost beats DeepLOB; data preprocessing > model complexity | [Link](https://arxiv.org/html/2506.05764v2) |
| DRL with LSTM + XGBoost Feature Selection (ScienceDirect, 2025) | Hybrid LSTM-DQN with XGBoost feature selection outperforms standalone | [Link](https://www.sciencedirect.com/science/article/abs/pii/S1568494625003400) |
| RegimeNAS (arXiv, 2025) | Regime-aware neural architecture search for crypto trading | [Link](https://arxiv.org/html/2508.11338v1) |
| Deep Learning for VWAP Execution (arXiv, 2025) | Direct optimization bypasses volume curve prediction | [Link](https://arxiv.org/html/2502.13722v1) |
| LiT: LOB Transformer (Frontiers, 2025) | Dual attention for spatial + temporal LOB dependencies | [Link](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1616485/full) |
| DQN for Bitcoin Technical Strategy Selection (2025) | RL agent selects among RSI, SMA, BB, Momentum, VWAP strategies | [Link](https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2594873) |
| TFT Multi-Crypto Trading with On-Chain Indicators (MDPI, 2025) | TFT + on-chain data for multi-asset portfolio optimization | [Link](https://www.mdpi.com/2079-8954/13/6/474) |

### 5.3 Real-World Performance Data Points

| System | Period | Return | Sharpe | Max DD | Win Rate | Notes |
|--------|--------|--------|--------|--------|----------|-------|
| FreqAI XGBoost (live) | 3 weeks | +7% | N/A | N/A | N/A | Live on crypto, beat CatBoost |
| RL Backtests (meta) | 2024-2026 | N/A | >2.0 | <15% | N/A | Across multiple studies |
| PPO Portfolio (paper) | Backtest | N/A | 2.15 | N/A | N/A | Risk-adjusted leader |
| Hybrid RL+Quant | Various | 15-20% improvement | 1.57 | N/A | N/A | Over pure RL (1.35) |
| Adaptive TFT | 1 week | +17.22% | N/A | N/A | 51.4% | ETH-USDT, bullish period |
| AI self-tuning bots | Backtests | N/A | N/A | N/A | +15-20% WR | Over non-AI baselines |

### 5.4 Platforms for Data and Execution

| Platform | Data Provided | Link |
|----------|--------------|------|
| CoinGlass | Liquidation heatmaps, OI, funding rates, order flow | https://www.coinglass.com/ |
| Coinalyze | OI, funding rates, liquidation data | https://coinalyze.net/ |
| TradingLite | Advanced order flow charts | https://tradinglite.com/ |
| Cignals.io | Order flow charts for BTC/crypto | https://cignals.io/ |
| Amberdata | Institutional-grade derivatives analytics | https://blog.amberdata.io/ |
| Hyperliquid | Low-latency perp DEX with full API | https://hyperliquid.xyz/ |

---

## 6. Optimal Timeframes

### 6.1 Research Findings by Timeframe

**High-Frequency (1m-5m):**
- Best for scalping with tight stops (2-5 ticks)
- Requires low-latency infrastructure (VPS near exchange)
- AI retraining needed every 1-6 hours
- 70-75% win rates achievable when aligned with higher-timeframe bias
- Fee structure is critical — maker orders essential for profitability
- **Best models:** LOB transformers, order flow imbalance, XGBoost

**Medium-Frequency (10m-15m):**
- Sweet spot for AI prediction models (most research uses 10m-15m)
- Adaptive TFT paper used 10-minute intervals specifically
- Enough data for pattern recognition, less noise than 1m
- **Best models:** TFT, LSTM+XGBoost hybrid, RL agents

**Low-Frequency (1h-4h):**
- Best for regime detection and trend-following
- RegimeNAS and ADX/ATR classification operate at this level
- Lower transaction costs, more forgiving on timing
- **Best models:** RL portfolio optimization, regime-aware strategies

**Multi-Timeframe (recommended approach):**
- 1h/4h for regime classification and directional bias
- 5m/15m for signal generation and trade decisions
- 1m for precise entry/exit timing
- This layered approach is the consensus best practice in 2025

### 6.2 The A2C Crypto Futures Study

The 2025 MDPI paper on RL crypto futures specifically found strategies categorize into:
- **High-frequency group:** 10, 30, and 60-minute timeframes
- **Low-frequency group:** Daily timeframe
- The two groups required fundamentally different reward functions and risk management

---

## 7. Key Takeaways and Practical Recommendations

### 7.1 What Actually Works (Evidence-Based)

1. **XGBoost is the workhorse.** It beats deep learning on LOB data (72.8% vs 71.9%), trains fast enough for live retraining, and is already proven live via FreqAI (+7% in 3 weeks). Start here.

2. **Implementation quality matters 11x more than algorithm choice** (0.92 vs 0.08 importance). A well-engineered XGBoost pipeline will crush a poorly-implemented transformer.

3. **Hybrid approaches outperform pure methods.** RL + traditional quant: Sharpe 1.57 vs pure RL 1.35. LSTM + XGBoost > either alone. Regime filter + signal model + entry timing > any single model.

4. **Data preprocessing > model complexity.** Savitzky-Golay filtering of LOB data was more valuable than switching from logistic regression to deep learning.

5. **Regime detection is the highest-ROI addition** to any existing strategy. ADX + ATR classification is simple to implement and dramatically filters bad trades.

6. **Order flow imbalance is the single most predictive feature** (43.2% importance) for short-term direction.

7. **Funding rate + OI extremes** predict liquidation cascades with up to 112 minutes of lead time.

### 7.2 Practical Architecture for a Futures Sniper Bot

```
Layer 1: DATA COLLECTION
  - OHLCV (1m, 5m, 15m, 1h)
  - Order book snapshots (L2 minimum, L3 ideal)
  - Funding rates (every 8h, interpolated)
  - Open interest (hourly)
  - Liquidation levels (CoinGlass API)

Layer 2: FEATURE ENGINEERING
  - Technical indicators (BB, EMA, RSI, ATR, ADX)
  - Derivatives features (funding rate z-score, OI change rate, liquidation density)
  - Microstructure features (order flow imbalance, bid-ask spread, volume delta)
  - Regime labels (trending/ranging/volatile/quiet)

Layer 3: MODELS
  - Regime classifier: XGBoost or GMM on 1h data
  - Direction predictor: XGBoost or TFT on 5m/15m data
  - Entry timer: Order flow model on 1m data
  - Position sizer: PPO or SAC RL agent
  - Exit manager: Adaptive trailing based on predicted volatility

Layer 4: RISK MANAGEMENT
  - Hard leverage cap (never exceed 5-10x)
  - Regime-conditional position sizing
  - Funding rate filter (skip when extreme)
  - Liquidation level buffer (don't hold through nearby liquidation clusters)
  - Circuit breaker (halt on portfolio drawdown threshold)
```

### 7.3 What to Avoid

- **Overfitting to backtests:** The FinRL Crypto project specifically addressed this, reducing overfitting by 46%. Always use walk-forward validation.
- **Ignoring fees:** At 1m scalping, the fee structure alone determines profitability. Maker rebates are essential.
- **Complex models without infrastructure:** A transformer requiring 500ms inference is useless for 100ms LOB prediction horizons. Match model complexity to latency budget.
- **Ignoring regime changes:** All models degrade during regime transitions. The biggest losses come from trend-following in ranges and mean-reversion in trends.
- **Exogenous shock blindness:** AI detected the October 2025 cascade 112 minutes early, but it was triggered by a tariff announcement. No model can predict policy shocks.

---

## Sources

### Academic Papers
- [Cryptocurrency Futures Portfolio Trading System Using RL (MDPI 2025)](https://www.mdpi.com/2076-3417/15/17/9400)
- [Adaptive TFT for Cryptocurrency Price Prediction (arXiv 2025)](https://arxiv.org/abs/2509.10542)
- [RL in Financial Decision Making: Systematic Review (arXiv 2025)](https://arxiv.org/html/2512.10913v1)
- [Exploring Microstructural Dynamics in Cryptocurrency LOBs (arXiv 2025)](https://arxiv.org/html/2506.05764v2)
- [DRL with LSTM + XGBoost Feature Selection (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/abs/pii/S1568494625003400)
- [RegimeNAS: Regime-Aware Architecture Search (arXiv 2025)](https://arxiv.org/html/2508.11338v1)
- [Deep Learning for VWAP Execution in Crypto (arXiv 2025)](https://arxiv.org/html/2502.13722v1)
- [LiT: Limit Order Book Transformer (Frontiers 2025)](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1616485/full)
- [Anatomy of Oct 2025 Crypto Liquidation Cascade (SSRN)](https://papers.ssrn.com/sol3/Delivery.cfm/5611392.pdf?abstractid=5611392)
- [LSTM+XGBoost Crypto Price Prediction (arXiv 2025)](https://arxiv.org/abs/2506.22055)
- [ML Approaches to Crypto Trading Optimization (Springer 2025)](https://link.springer.com/article/10.1007/s44163-025-00519-y)
- [DRL for Risk-Aware Portfolio Optimization: PPO, SAC, DDPG (ResearchGate)](https://www.researchgate.net/publication/398486187)
- [TFT Trading Strategy for Multi-Crypto Assets (MDPI 2025)](https://www.mdpi.com/2079-8954/13/6/474)
- [DQN for Bitcoin Technical Strategy Selection (Taylor & Francis 2025)](https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2594873)
- [FinRL Contests: Data-Driven FinRL (Wiley 2025)](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/aie2.12004)

### Open-Source Projects
- [FinRL Framework](https://github.com/AI4Finance-Foundation/FinRL)
- [Freqtrade / FreqAI](https://github.com/freqtrade/freqtrade)
- [Passivbot](https://github.com/enarjord/passivbot)
- [OctoBot](https://github.com/Drakkar-Software/OctoBot)
- [Intelligent Trading Bot](https://github.com/asavinov/intelligent-trading-bot)
- [Hummingbot](https://github.com/hummingbot/hummingbot)
- [FinRL Crypto (Overfitting Reduction)](https://github.com/berendgort/FinRL_Crypto)

### Industry / Analytics
- [XGBoost vs CatBoost Real-Time Study (Emergent Methods)](https://emergentmethods.medium.com/real-time-head-to-head-adaptive-modeling-of-financial-market-data-using-xgboost-and-catboost-995a115a7495)
- [ML for Crypto Market Microstructure (Amberdata)](https://blog.amberdata.io/machine-learning-for-crypto-market-microstructure-analysis)
- [Derivatives Market Signals (Gate.io)](https://web3.gate.com/crypto-wiki/article/how-do-futures-open-interest-funding-rates-and-liquidation-data-predict-crypto-price-movements-20251226)
- [Funding Rate + Open Interest (TradeLink)](https://tradelink.pro/blog/funding-rate-open-interest/)
- [Liquidations in Crypto: How to Anticipate Volatile Moves (Amberdata)](https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves)
- [Predictive Analytics Tools for Crypto (Nansen)](https://www.nansen.ai/post/how-predictive-analytics-tools-enhance-crypto-trading-decisions-in-2025)
- [Machine Learning in Fintech 2026 (Darkbot)](https://darkbot.io/blog/machine-learning-in-fintech-2026-optimizing-crypto-trading)
- [CoinGlass Derivatives Analytics](https://www.coinglass.com/)
- [Coinalyze Futures Data](https://coinalyze.net/)
