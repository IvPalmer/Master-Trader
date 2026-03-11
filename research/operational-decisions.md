# Operational Decisions: Dry-Run, Pairs, Exchange, UI, AI Strategy

Research synthesis from 4 parallel deep dives.

---

## 1. Is Dry-Run Trustworthy on High-Volume Pairs?

### The Short Answer
**Moderate-high for direction (will I profit?), low for exact PnL numbers.** On BTC/USDT specifically, slippage simulation is a non-issue — the real problem is timing.

### Documented Discrepancies (GitHub Issues)
- **#3902:** +262 USDT dry-run vs -94 USDT live (same config, same machine)
- **#5489:** Dry-run and live running simultaneously traded **different pairs entirely**
- **#8846:** Dry-run fill prices didn't match the actual orderbook
- **#10139:** Execution order bug — `adjust_trade_position()` runs before entry signals in live/dry-run but AFTER in backtesting (structural difference)

### Why BTC/USDT Is Actually Fine for Slippage
- Binance BTC/USDT 1% depth: **>$600 million**
- Real slippage for $1K-$10K orders: **<0.1%**
- The 5% max slippage cap is irrelevant for BTC — it would never be hit
- Top-10 coins: 0.05-0.1% real slippage. Outside top-100: 0.5-2%. Microcaps: 5-10%.

### The Real Problem: Timing
- Freqtrade must analyze ALL pair dataframes before entering trades → seconds of delay after candle open
- For 5m+ candles on BTC/USDT: minimal impact
- For 1m candles: significant — price can move before order fires
- Use `ignore_buying_expired_candle_after` to limit stale entries
- Use `--timeframe-detail 1m` in backtesting for more realistic simulation

### Known Binance-Specific Bugs (2024-2026)
1. **Futures time desync (#10652):** Informative pair candle timestamps drift in dry-run futures mode. Spot mode NOT affected.
2. **Stoploss API change (#12610):** Binance migrated to Algo Order API, breaking live futures stoploss. Dry-run still works → **false confidence**.
3. **Memory leak (#11317):** Binance futures mode leaks memory, needs daily restart.
4. **Pricing bugs (#8846, #11216):** Occasional dry-run fill prices that don't match orderbook.

### Recommended Validation Path
```
Backtest (historical) → Dry-run 2-4 weeks → Live with $50-100/trade → Compare side-by-side → Scale up
```

**The most reliable validation is live with minimum capital, running alongside dry-run to compare.**

---

## 2. What Pairs Should We Trade?

### Don't Limit to BTC/USDT
BTC moves 1-3% on a normal day. Altcoins move 5-15%. A bot needs volatility for entries. **Trade 20-40 pairs dynamically.**

### What Top Strategies Actually Trade
NostalgiaForInfinity (most popular community strategy) trades **40-80 pairs** selected dynamically by volume. Core always includes:
- BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT
- Mid-caps: LINK, ADA, DOT, LTC, AVAX
- Rest filled dynamically — whatever has volume that week
- **All USDT-quoted** (never BTC-quoted pairs)

### Pair Selection Config (Freqtrade)
```json
{
    "pairlists": [
        {"method": "VolumePairList", "number_assets": 40, "sort_key": "quoteVolume"},
        {"method": "SpreadFilter", "max_spread_ratio": 0.005},
        {"method": "VolatilityFilter", "min_volatility": 0.05, "max_volatility": 0.50, "lookback_days": 10},
        {"method": "AgeFilter", "min_days_listed": 30},
        {"method": "PriceFilter", "min_price": 0.00000010}
    ],
    "exchange": {
        "pair_blacklist": [
            ".*BULL/USDT", ".*BEAR/USDT", ".*UP/USDT", ".*DOWN/USDT",
            "USDC/USDT", "BUSD/USDT", "DAI/USDT", "TUSD/USDT"
        ]
    }
}
```

### Spot vs Futures
**Spot only.** Reasons:
- Zero liquidation risk
- Simpler execution
- **Binance futures banned for Brazilians** (CVM fined Binance R$9.6M in 2024)
- Freqtrade docs: "Do not trade with leverage >1x using a strategy that hasn't shown positive results in a live spot run"
- Consider futures only after 3-6 months of profitable spot, and only on Bybit (legal for BR)

---

## 3. Is Binance Really the Best Exchange?

### Yes, for Spot from Brazil
| Factor | Binance | Bybit | OKX |
|--------|---------|-------|-----|
| Freqtrade support | Best (officially tested) | Official | Official |
| Liquidity | Highest globally | Strong | Strong |
| API rate limits | Weight-based (flexible) | 600 req/5s | Per-endpoint |
| Spot fees | 0.1%/0.1% (0.075% w/ BNB) | 0.1%/0.1% | 0.08%/0.10% |
| BRL deposit (Pix) | Yes | Yes (P2P) | Limited |
| Brazil legal status | Spot: legal, licensed by BCB. Futures: banned by CVM | Fully legal | Legal |
| API uptime (H1 2025) | 99.98% (published report) | No report | No report |

### When to Consider Alternatives
- **OKX:** If you reach higher volume — has **negative maker fees** at VIP 7+ (you get paid to place limit orders)
- **Bybit:** If you want futures later (legal for Brazilians, good API)
- **KuCoin:** Skip — community-supported only in Freqtrade

### BRL Pairs?
**No.** Trade USDT pairs only. BRL pairs have low liquidity, wide spreads. Flow is:
1. Deposit BRL via Pix → Binance
2. Convert to USDT (one-time)
3. Bot trades USDT pairs
4. Convert back to BRL when withdrawing

---

## 4. Visualization & Monitoring

### Recommended Stack (Progressive)

#### Phase 1: Immediate (Zero Extra Infra)
| Tool | Purpose |
|------|---------|
| **FreqUI** | Web dashboard — open trades, profit, basic charts with entry/exit markers |
| **Telegram Bot** | Mobile alerts, trade notifications, emergency controls (`/forcesell`, `/status`, `/profit`) |

FreqUI shows: open/closed trades, profit tracking, candlestick charts with entry/exit points, performance per pair, backtest results viewer.

#### Phase 2: Professional
| Tool | Purpose |
|------|---------|
| **Grafana + InfluxDB** | Custom dashboards — equity curve, drawdown, rolling Sharpe, pair heatmaps, system health |
| **Grafana Mobile App** | Phone dashboard viewing |
| **PostgreSQL** | Replace SQLite for multi-tool access |

Community provides pre-built Grafana dashboards for Freqtrade.

#### Phase 3: Advanced
| Tool | Purpose |
|------|---------|
| **QuantStats** | Professional tearsheets — Sharpe, Sortino, monthly heatmap, benchmark comparison |
| **Streamlit** | Custom analysis app for backtest deep-dives |
| **TradingView lightweight-charts** | TV-quality charts in custom web app (open-source library) |

### TradingView Integration
**No native integration exists.** Options:
- TV can send webhook alerts → Freqtrade (TV as signal source)
- Freqtrade trades show on Binance UI (exchange-level view)
- Build custom dashboard using TV's open-source `lightweight-charts` library
- **Altrady** can show exchange-level trade history on charts

### Backtest Visualization
```bash
freqtrade plot-dataframe --strategy YourStrategy -p BTC/USDT  # Interactive HTML chart
freqtrade plot-profit --strategy YourStrategy                  # Equity curve
```
Output is interactive Plotly HTML. For professional tearsheets, use QuantStats library.

---

## 5. TradingAgents: Skip It

### The Verdict
**TradingAgents adds complexity without demonstrated value. FreqAI does the same job better.**

### Why Multi-Agent LLM Trading Doesn't Work (Yet)
- Multi-agent debate improves **factual accuracy** (math, trivia) but markets are **not factual reasoning tasks** — the "correct answer" is unknowable
- No published study shows multi-agent LLM outperforming single-agent for trading
- The bull/bear debate is just prompt decomposition — achievable with a single structured prompt
- LLMs are trained on general text, **not on specific market data**
- Non-deterministic (same inputs → different outputs across runs)
- Slow (minutes per decision) — only viable for daily/swing

### FreqAI vs LLM-Based Approaches

| Dimension | FreqAI (XGBoost/LightGBM) | TradingAgents (LLM) |
|-----------|---------------------------|---------------------|
| Trained on | Actual historical price data | General internet text |
| Speed | <1s per decision | 30-120s per decision |
| Cost | Free | $0.50-3.00/analysis (cloud) or free (Ollama) |
| Backtestable | Fully | Not meaningfully |
| GPU needed | No (CPU fine for XGBoost) | Yes (for Ollama) |
| Track record | Community results exist | None public |

### What to Do Instead
The practical "AI-enhanced" Freqtrade setup:

```
Freqtrade + FreqAI (XGBoost or LightGBM)
├── Features: RSI, MACD, BBands, ATR, volume, lagged returns
├── Optional: FinBERT sentiment score as one feature
├── Optional: Single daily Claude call for macro context (risk-on/risk-off)
└── Risk management: position sizing, stop-loss, max drawdown
```

**Rules:**
1. Start with FreqAI + XGBoost using only technical features. Get a baseline.
2. If baseline isn't profitable, adding LLMs won't help.
3. Never let the LLM make the trade decision. It's a feature extractor, not a decision maker.
4. One cheap daily API call for macro context is the maximum justifiable LLM involvement.

### If You Still Want to Experiment with TradingAgents
Use it as a daily "second opinion" tool via Ollama (free). Run it on a ticker you're considering, read the analysis, then make your own decision. Don't pipe its output into execution.

---

## Summary: The Plan

```
Exchange:    Binance (spot only, BRL via Pix → USDT)
Pairs:       40 dynamic pairs via VolumePairList (USDT-quoted)
Strategy:    Start with NostalgiaForInfinity or FreqAI + XGBoost
AI:          FreqAI for ML signals, skip TradingAgents
Monitoring:  FreqUI + Telegram (Phase 1) → add Grafana (Phase 2)
Validation:  Backtest → Dry-run 2-4 weeks → Live $50-100/trade → Scale
```
