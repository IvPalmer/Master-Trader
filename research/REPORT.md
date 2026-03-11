# Master Trader - Research Synthesis & Recommendations

**Date:** March 2026
**Audience:** Experienced engineer and day trader based in Brazil

---

## TL;DR

**Start with crypto trading via Freqtrade + Binance.** It has the best ecosystem, lowest barrier to entry, 24/7 markets, excellent APIs, and you can start with R$500. Binary options are a scam - avoid entirely. US stocks via Alpaca/IBKR are a solid Phase 2 once you've validated your approach on crypto.

---

## The Honest Picture

- ~5-10% of retail algo traders are consistently profitable
- Simpler strategies outperform complex ML models in practice
- Implementation quality matters more than algorithmic sophistication
- Transaction costs destroy most ML-based "edges"
- The profitable minority focuses on risk management, not returns
- Beating buy-and-hold after costs is extremely hard

**Your advantages as an experienced engineer + day trader:**
- You understand markets (most algo traders are engineers who don't)
- You can build and debug systems (most traders can't)
- You can start small and iterate (no institutional constraints)
- You can trade in niche markets institutions ignore

---

## Market Comparison

| Factor | Crypto | US Stocks | B3 (Brazil) | Binary Options |
|--------|--------|-----------|-------------|---------------|
| API Quality | Excellent | Very Good | Poor | N/A |
| Bot Ecosystem | Best | Good | Limited | Avoid |
| Min Capital | $0 | $0 (Alpaca) | ~R$1000 | Avoid |
| Market Hours | 24/7 | 6.5h/day | 7h/day | Avoid |
| Tax (Brazil) | Domestic: exempt <R$35K/mo; Foreign (Binance): 15% all gains | 15% all gains | 15-20% | Avoid |
| Volatility | High | Medium | Medium | Avoid |
| From Brazil | Easy (Pix) | IOF 0.38% | Native | **AVOID** |

**Winner: Crypto** for starting out. Best risk/reward ratio considering ecosystem maturity, API access, capital requirements, and tax threshold.

---

## Recommended Architecture

### Phase 1: Crypto Bot (Weeks 1-8)

```
┌─────────────────────────────────────────┐
│            Your Machine / VPS            │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │  Freqtrade   │  │    FreqUI        │  │
│  │  (Bot Core)  │──│  (Dashboard)     │  │
│  └──────┬───────┘  └──────────────────┘  │
│         │                                 │
│  ┌──────┴───────┐  ┌──────────────────┐  │
│  │  FreqAI      │  │  Telegram Bot    │  │
│  │  (ML Module) │  │  (Alerts)        │  │
│  └──────────────┘  └──────────────────┘  │
└─────────────┬───────────────────────────┘
              │ API
    ┌─────────┴─────────┐
    │     Binance        │
    │  (Exchange)        │
    └───────────────────┘
```

**Stack:**
- **Bot:** Freqtrade (Python, 47K stars, battle-tested)
- **ML:** FreqAI module (XGBoost, LightGBM, or RL)
- **Exchange:** Binance (best API, Pix deposits)
- **Monitoring:** Telegram bot + FreqUI dashboard
- **VPS:** DigitalOcean SP or AWS sa-east-1 ($5-10/mo)

### Phase 2: Add US Stocks (After Crypto Validation)

- Open Alpaca or IBKR account
- Use QuantConnect/Lean for backtesting
- Port validated strategies to equities
- Consider NautilusTrader for multi-asset

### Phase 3: Multi-Strategy Portfolio

- Run 3-5 uncorrelated strategies simultaneously
- Mix: trend following + mean reversion + sentiment
- Portfolio-level risk management
- Automated rebalancing

---

## Recommended First Strategies

### 1. Trend Following (EMA Crossover + RSI Filter)
- **Why first:** Simple, well-understood, works in trending crypto markets
- **Implementation:** Fast EMA crosses slow EMA, RSI confirms trend strength
- **Timeframe:** 1h or 4h candles
- **Pairs:** BTC/USDT, ETH/USDT
- **Expected:** Captures big moves, many small losses in ranging markets

### 2. Mean Reversion (Bollinger Bands + Volume)
- **Why second:** Complementary to trend following (works when #1 doesn't)
- **Implementation:** Buy at lower BB, sell at upper BB, volume confirmation
- **Timeframe:** 15m to 1h
- **Expected:** Many small wins, occasional large loss if trend breaks

### 3. Grid Trading (Ranging Markets)
- **Why third:** Passive income in sideways markets
- **Implementation:** Set buy/sell grid 2-5% apart around current price
- **Risk:** Position accumulation if price trends strongly

### 4. AI-Enhanced (Phase 2)
- **FreqAI with XGBoost:** Use technical indicators as features
- **Sentiment overlay:** LLM-based news analysis as signal filter
- **Walk-forward training:** Retrain weekly/monthly

---

## Risk Management Rules

1. **Never risk more than 1-2% per trade**
2. **Maximum 10% of trading capital in any single position**
3. **Daily loss limit: 5% of capital → auto-pause**
4. **Weekly drawdown limit: 10% → reassess strategy**
5. **Start with 1/10th of intended capital**
6. **Paper trade for minimum 2 weeks before going live**
7. **Keep a trading journal (Freqtrade logs every trade)**

---

## Immediate Next Steps

1. **Install Freqtrade** locally and run through the tutorial
2. **Get Binance API keys** (read-only first, then trading)
3. **Download historical data** (BTC/USDT, ETH/USDT, 1h candles, 2 years)
4. **Backtest a simple EMA crossover** strategy
5. **Run paper trading** for 2 weeks
6. **Go live** with R$500-1000

---

## Detailed Research Files

- [Crypto Bot Ecosystem](crypto-bots.md) - Full analysis of crypto trading bots, exchanges, and platforms
- [Stock Trading Automation](stock-trading.md) - Equities frameworks, broker APIs, B3 access
- [Strategies & ML Approaches](strategies-and-ml.md) - Deep dive into strategies, ML, risk management, data sources
- [GitHub Projects Ranked](github-projects.md) - Top 15 open-source projects with analysis
- [Brazil Setup Guide](brazil-setup.md) - Tax, regulations, infrastructure, money flow
