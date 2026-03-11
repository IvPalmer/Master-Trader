# Stock/Equities Trading Automation

## Open-Source Frameworks

### Backtesting Frameworks

#### Backtrader (~14K stars)
- **Language:** Python
- **Status:** Stable/maintenance mode (core is complete)
- **Features:** Event-driven, multi-data/multi-strategy, live trading via IB
- **Pros:** Mature, extensive documentation, large community
- **Cons:** Aging codebase, single-threaded

#### VectorBT (~5K stars)
- **Language:** Python (NumPy/Pandas)
- **Status:** Active
- **Features:** Vectorized backtesting (extremely fast), portfolio optimization
- **Pros:** 1000x faster than event-driven frameworks for simple strategies
- **Cons:** Limited for complex order types, less realistic execution modeling

#### Zipline-Reloaded
- **Language:** Python
- **Status:** Community fork of Quantopian's Zipline
- **Features:** Event-driven, pipeline API for factor modeling
- **Pros:** Well-designed API, good for equity factor strategies
- **Cons:** Documentation gaps since Quantopian shutdown

#### backtesting.py (~5K stars)
- **Language:** Python
- **Status:** Active
- **Features:** Lightweight, Jupyter-friendly, interactive HTML reports
- **Pros:** Simplest to get started, beautiful visualizations
- **Cons:** Less suitable for production/live trading

### Full Platforms (Backtest + Live)

#### QuantConnect / Lean Engine (~9K stars)
- **Language:** C#, Python
- **Status:** Very active, VC-backed
- **Features:**
  - Cloud-based IDE + open-source engine
  - Multi-asset (equities, options, futures, crypto, forex)
  - Institutional-grade data included
  - Live trading via many brokers
  - Alpha Marketplace (sell strategies)
- **Pros:** Most complete free platform, great data
- **Cons:** C# core (Python is a wrapper), cloud dependency for full features
- **Verdict:** Best for US equities if you want free data + backtesting

#### NautilusTrader (~9.1K stars)
- **Language:** Python/Rust
- **Status:** Very active
- **Features:** High-performance, multi-asset, IB and crypto exchange support
- **Verdict:** Best for performance-critical strategies

### ML-Specific

#### FinRL (~12K stars)
- **Language:** Python
- **Status:** Active (AI4Finance Foundation)
- **Features:**
  - Full pipeline: data processing -> model training -> backtesting -> live trading
  - Algorithms: DQN, DDPG, PPO, A2C, SAC, TD3
  - Environments for stock, crypto, forex
  - Integration with Alpaca for live trading
- **Reality check:** Research tool more than production system. Results in papers ≠ live performance. Good for learning RL applied to finance.

---

## Broker APIs Accessible from Brazil

### US Market Access

#### Interactive Brokers (IBKR)
- **Access from Brazil:** Yes, supports Brazilian residents
- **API:** TWS API (Java, Python, C++, C#), REST API
- **Minimum deposit:** $0 (was $10K, removed)
- **Fees:** $0 for US equities (IBKR Lite), $0.0035/share (IBKR Pro)
- **Markets:** US, Europe, Asia, options, futures, forex, bonds
- **Bot frameworks:** Supported by Backtrader, NautilusTrader, ib_insync (Python wrapper)
- **Verdict:** Best choice for stock trading from Brazil. Widest market access.

#### Alpaca
- **Access from Brazil:** Yes, supports international accounts
- **API:** Excellent REST + WebSocket, purpose-built for algo trading
- **Fees:** $0 commission
- **Markets:** US equities and crypto
- **Paper trading:** Excellent built-in paper trading
- **Bot frameworks:** Native Python SDK, supported by FinRL, many tutorials
- **Verdict:** Best API for beginners. Free, clean, well-documented.

#### Tradier
- **Access from Brazil:** Unclear, may not support non-US residents
- **API:** Good REST API
- **Fees:** $0 equities, $0.35/contract options

### Brazil Stock Market (B3)

#### Current State of B3 API Access
- **No direct retail API access** like US brokers offer
- B3 uses FIX protocol (institutional only, very expensive)
- MetaTrader 5 is available through some Brazilian brokers (Clear, XP)
- **Profit/MetaTrader route:** Some Brazilian brokers (Clear, Rico) offer MetaTrader 5 with Expert Advisors
- **Limitations:** Latency, limited API features vs US brokers

#### Brazilian Brokers with Some Automation
| Broker | Platform | Automation |
|--------|----------|-----------|
| Clear (XP) | Profit Pro, MT5 | Expert Advisors, DDE/API |
| XP Investimentos | XP Pro | Limited API |
| BTG Pactual | BTG Trader | Limited |
| Rico | Profit | DDE integration |
| Toro | Profit | Limited |

#### Brazilian Algo Trading Communities
- **QuantBrasil** - Python-focused quant trading for B3
- **MQL5 Brazil** - MetaTrader community
- **Clube de Finanças** - Academic groups at USP, FGV, INSPER

### Verdict on Markets

**For an experienced engineer in Brazil wanting to automate trading:**

1. **Crypto (via Binance)** - Easiest to start. Best APIs, 24/7 markets, no minimum capital, best open-source ecosystem. Tax reporting is the main hassle.

2. **US Stocks (via IBKR or Alpaca)** - Excellent API access, lots of tools, but market hours matter and some strategies need PDT exemption ($25K minimum).

3. **B3 (Brazilian stocks)** - Hardest to automate. Limited API access, fragmented ecosystem. Only worth it if you specifically want Brazilian market exposure.

---

## Technical Analysis Libraries

| Library | Language | Indicators | Speed | Notes |
|---------|----------|-----------|-------|-------|
| **TA-Lib** | C (Python wrapper) | 150+ | Fastest | Industry standard, C core |
| **pandas-ta** | Python | 130+ | Good | Pure Python, Pandas-native |
| **ta** | Python | 80+ | Good | Simple API, Pandas-friendly |
| **tulind** | C (bindings) | 104 | Very fast | Lightweight, C core |
| **finta** | Python | 80+ | Good | Pandas-based |

**Recommendation:** pandas-ta for prototyping (pure Python, easy), TA-Lib for production (speed).

---

## LLM/AI-Powered Trading Projects

### Notable Projects (2024-2026)
- **FinGPT** - Open-source financial LLM. Fine-tuned for sentiment analysis on financial data.
- **TradingGPT** - Multi-agent system using LLMs for trading decisions
- **Various sentiment bots** - Using GPT-4/Claude APIs to analyze news and generate signals

### Realistic Assessment
- LLMs are best used for **sentiment analysis** and **information processing**, not direct price prediction
- Useful for: earnings call analysis, news sentiment scoring, macro analysis
- NOT useful for: tick-by-tick trading decisions, short-term price prediction
- The edge is in processing information faster than manual traders, not in predicting price movements
