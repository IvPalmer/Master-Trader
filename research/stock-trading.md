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
- **Access from Brazil:** Yes, confirmed. **As of Dec 2025, IBKR added direct B3 access.**
- **API:** TWS API (Java, Python, C++, C#), Client Portal Web API, FIX CTCI
- **Minimum deposit:** $0 (was $10K, removed)
- **Fees:** $0 for US equities (IBKR Lite), $0.0035/share (IBKR Pro)
- **Markets:** US, Europe, Asia, **Brazil (B3)**, options, futures, forex, bonds - 150+ markets in 33 countries
- **Bot frameworks:** Supported by QuantConnect/Lean, Backtrader, NautilusTrader, ib_insync (Python wrapper)
- **Verdict:** Best choice for trading from Brazil. Only broker with US + B3 access via a single API.

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
- B3 uses PUMA platform (Platform Unified Multi Asset-class) with FIX protocol
- **Nelogica Profit Pro** is the dominant platform in Latin America for B3 trading
  - Strategy Automation module for building robot traders
  - B3 Data API (DLL) for real-time data feeds
  - Available through XP, Clear, Rico, BTG, Genial, Itau, Toro
- **SmarttBot** - Brazil's largest automated day trading platform (smarttbot.com)
  - Cloud-based robot hosting
  - Strategy marketplace
  - Works with B3 equities and futures (mini-indice, mini-dolar)
- **OnTick** - Automated platform partnered with XP (free up to certain limits)
- MetaTrader 5 available through some Brazilian brokers (Clear, XP)
- **NEW: Interactive Brokers now offers direct B3 access** (Dec 2025) - use Python + TWS API

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

### Major Projects (2024-2026)

#### TradingAgents (~31.8K stars - fastest growing)
- **URL:** https://github.com/TauricResearch/TradingAgents
- Multi-agent LLM framework mirroring real trading firms
- Specialized agents: fundamental analyst, sentiment analyst, technical analyst, bull/bear researchers, risk management, portfolio manager
- Supports GPT, Claude, Gemini, Grok, Ollama (local models)
- Built on LangGraph for modularity

#### FinGPT (~18.8K stars)
- Open-source financial LLM fine-tuning framework
- Financial sentiment analysis achieving 0.882 F1 (competitive with GPT-4)
- Trainable on a single RTX 3090 (~$17 vs BloombergGPT's $2.67M)
- FinGPT-Forecaster: stock price movement prediction from news

#### AI-Trader (HKUDS, ~11.6K stars)
- Competitive benchmark: AI models battle autonomously on NASDAQ 100, SSE 50, crypto
- Live dashboard at ai4trade.ai
- Uses MCP (Model Context Protocol) for tool access

#### Other Notable
- **FinMem** - LLM trading with layered memory (IJCAI2024 paper)
- **LLM_trader** - Multi-agent with Vision AI chart analysis
- **OctoBot AI** - OpenAI/Ollama integration for ready-to-use bot
- **Alpaca MCP Server** - Trade from Claude/LLMs in plain English

### MCP (Model Context Protocol) - Emerging Pattern
- **Alpaca MCP Server:** Trade stocks, ETFs, crypto, options from Claude
- **Hummingbot MCP Server:** AI agent integration for market making
- **CCXT MCP Server:** Exchange connectivity for LLMs
- Enables conversational trading: "Buy 100 shares of AAPL if RSI drops below 30"

### Realistic Assessment
- LLMs are best used for **sentiment analysis** and **information processing**, not direct price prediction
- Useful for: earnings call analysis, news sentiment scoring, macro analysis, strategy ideation
- NOT useful for: tick-by-tick trading decisions, short-term price prediction
- Sentiment features are most valuable around earnings and event-driven volatility
- The edge is in processing information faster than manual traders, not predicting prices
- LLM API costs can be significant for real-time trading
