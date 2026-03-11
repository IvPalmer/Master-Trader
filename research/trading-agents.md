# TradingAgents - Deep Dive

**Repo:** https://github.com/TauricResearch/TradingAgents
**Paper:** https://arxiv.org/abs/2412.20138
**License:** Apache-2.0
**Latest:** v0.2.0 (Feb 2026)

---

## What It Is

A multi-agent LLM framework that simulates a real trading firm. Specialized AI agents (analysts, researchers, trader, risk manager) collaborate to evaluate markets and produce trading decisions. Built on LangGraph.

**It does NOT execute real trades.** Output is analysis + signals only. A community fork (AlpacaTradingAgent) adds real execution via Alpaca.

---

## Architecture

Replicates a trading firm's org structure:

```
┌─────────────────────────────────────────────┐
│              ANALYST TEAM (parallel)         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │Fundamental│ │Sentiment │ │ Technical │    │
│  │ Analyst   │ │ Analyst  │ │ Analyst   │    │
│  └────┬──────┘ └────┬─────┘ └────┬──────┘   │
│       │     ┌───────┐│           │           │
│       │     │ News   ││           │           │
│       │     │Analyst ││           │           │
│       │     └───┬────┘│           │           │
└───────┼─────────┼─────┼───────────┼──────────┘
        └─────────┴─────┴───────────┘
                    │
        ┌───────────┴───────────┐
        │    RESEARCH TEAM      │
        │  ┌──────┐  ┌──────┐  │
        │  │ Bull │◄►│ Bear │  │  ← Configurable debate rounds
        │  │Resrch│  │Resrch│  │    (default: 1, max: 10)
        │  └──┬───┘  └──┬───┘  │
        └─────┼─────────┼──────┘
              └────┬────┘
                   ▼
           ┌──────────────┐
           │    Trader     │  ← Synthesizes debates
           └──────┬───────┘
                  ▼
           ┌──────────────┐
           │ Risk Manager  │  ← Assesses volatility, liquidity
           └──────┬───────┘
                  ▼
           ┌──────────────┐
           │  Portfolio    │  ← Final buy/sell/hold decision
           │  Manager      │
           └──────────────┘
```

All agents use **ReAct prompting** with structured output.

---

## LLM Support

| Provider | Config Value | API Key? | Notes |
|----------|-------------|----------|-------|
| OpenAI | `"openai"` | Yes | GPT-5.2, o1-preview, etc. |
| Google | `"google"` | Yes | Gemini 2.0 Flash |
| Anthropic | `"anthropic"` | Yes | Claude Opus |
| xAI | `"xai"` | Yes | Grok-3 |
| OpenRouter | `"openrouter"` | Yes | Aggregated models |
| **Ollama** | `"ollama"` | **No** | Any local model, free |

Two model slots:
- `deep_think_llm` — complex reasoning (analysts, researchers, risk)
- `quick_think_llm` — rapid processing (trader, formatting)

---

## Data Sources

- **Default:** yfinance (free)
- **Alternative:** Alpha Vantage (API key needed)
- **Data types:** OHLCV prices, Bloomberg/Yahoo news, social sentiment, insider transactions, financial statements, technical indicators (MACD, RSI, Bollinger Bands)
- All data cached locally in `tradingagents/dataflows/data_cache/`

---

## Setup

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
conda create -n tradingagents python=3.13
conda activate tradingagents
pip install -r requirements.txt
```

### Usage (Python)
```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "ollama"        # Free, local
config["deep_think_llm"] = "llama3"
config["quick_think_llm"] = "llama3"
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
final_state, decision = ta.propagate("NVDA", "2026-01-15")
```

### CLI
```bash
python -m cli.main
```

---

## Costs

No official breakdown, but estimates:

- Each analysis = 4 analysts + 2 researchers debating + trader + risk manager + portfolio manager
- More debate rounds = more API calls
- **Cloud APIs:** ~$0.50-$3.00+ per single stock analysis (1 debate round)
- **Heavy usage (30M tokens/month):** $5K-$10K/month cloud vs ~$200/month GPU rental
- **Ollama:** $0 API cost, just needs local GPU (your Mac Studio would work)

---

## Reported Results (from paper)

Testing on AAPL, GOOGL, AMZN from Jan-Mar 2024:

| Metric | AAPL | GOOGL | AMZN |
|--------|------|-------|------|
| Cumulative Return | 26.62% | 24.36% | 23.21% |
| Annualized Return | 30.5% | 27.58% | 24.90% |
| Sharpe Ratio | 8.21 | 6.39 | 5.60 |
| Max Drawdown | 0.91% | 1.69% | 2.11% |

### Reality Check
- Sharpe ratios of 5.6-8.2 are **unrealistically high** (anything >3.0 is a red flag)
- Only 3 months, 3 large-cap tech stocks, during a bull market
- No out-of-sample testing, no bear market testing
- **No transaction cost modeling at all**
- Authors themselves acknowledged the Sharpe was inflated by few pullbacks
- **Do not take these results at face value**

---

## Can It Be Integrated with Freqtrade?

**No built-in integration.** Options:

1. **AlpacaTradingAgent** (community fork) — bridges to Alpaca for real execution (paper + live)
   - https://github.com/huygiatrng/AlpacaTradingAgent
   - 133 stars, supports stocks + crypto, has web UI
   - Requires Alpaca, Finnhub, FRED, CryptoCompare API keys

2. **DIY bridge** — parse `ta.propagate()` output → feed into Freqtrade/IBKR/Binance API
   - Would require custom code
   - A Freqtrade MCP Server exists that could theoretically be a bridge

3. **Use as analysis supplement** — run TradingAgents for signal generation, manually validate before acting

---

## Competitors

| Framework | Real Trading? | Key Difference |
|-----------|:---:|---|
| **TradingAgents** | No | Multi-agent firm simulation |
| **AgenticTrading** (Open Finance Lab) | No | More advanced: DAG planning, Neo4j memory, audit trails |
| **FinMem** | No | Single agent + layered memory (IJCAI 2024) |
| **FinGPT** | No | Fine-tuned LLMs for sentiment, lightweight |
| **AlpacaTradingAgent** | **Yes** | TradingAgents fork with Alpaca execution |
| **LLM_trader** | Yes (crypto) | Vision AI chart analysis, simpler |
| **Freqtrade + FreqAI** | **Yes** | Production-grade, ML not LLM-native |

**AgenticTrading** (https://github.com/Open-Finance-Lab/AgenticTrading) is the most architecturally ambitious competitor — DAG-based orchestration, Neo4j memory, protocol-oriented. NeurIPS 2025 workshop paper.

---

## Verdict

### Good for:
- Research and learning about multi-agent AI reasoning
- Generating structured market analysis reports (free with Ollama)
- Getting a "second opinion" on trade theses
- Starting point for building custom LLM trading systems

### Not good for:
- Actual automated trading (no execution)
- High-frequency or intraday strategies (too slow, minutes per decision)
- Production deployment (164 open issues, rough edges)
- Anything requiring deterministic, repeatable results (LLM outputs vary)

### Bottom line:
Interesting research project, worth experimenting with via Ollama (free), but **Freqtrade is where you actually trade.** The ideal future setup might be: TradingAgents for daily macro analysis → feed signals into Freqtrade for execution.
