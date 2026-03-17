# Michael Ionita (Michael Automates) - Channel Learnings
## 17 videos analyzed on 2026-03-17

Channel: https://youtube.com/@michaelionita
Focus: AI-assisted trading strategy development, TradingView automation, crypto trend-following

---

## Key Takeaways (Ranked by Relevance to Our Setup)

### 1. TIMEFRAME: Higher is Better (4H minimum)

**Source**: "Why Trading On Low Timeframes Sucks" (35min deep-dive)

- It costs ~$22M to move BTC 1%. On 5m charts, stops are 0.5% away = trivially huntable
- On daily charts, you need 2.5-4.5% manipulation = far too expensive to be worth it
- Institutional/HFT players have ms-level co-located servers; retail has seconds of latency
- **Everything below 4H is structurally disadvantaged for retail**
- Solution: 4H+ timeframe, trend-following, diversify across 15-25 assets for trade frequency
- **Implication for us**: Our 1h strategies (Supertrend, MasterV1) are borderline; the FuturesSniperV1 needs to be on 4H minimum

### 2. STRATEGY EVALUATION: The 5-Rule Framework

**Source**: "What Makes a Really Good TradingView Strategy?"

| Priority | Metric | Threshold | Notes |
|----------|--------|-----------|-------|
| 1 | Max Drawdown | <50% disqualify, <30% good | THE most important number |
| 2 | Net Profit | Must be % based | Meaningless alone |
| 3 | Profit/Drawdown Ratio | Higher = better | `Net Profit % / Max DD %` — primary ranking metric |
| 4 | Profit Factor | >1.0 min, >3.0 good | Unreliable with few trades |
| 5 | Win Rate | No minimum | Psychological metric only, not mathematical |

- **The Profit/Drawdown Ratio** is the core quality metric (e.g., 1895%/30% = 63 is decent; 565 is excellent)
- A strategy with 500% profit / 20% DD beats one with 1200% profit / 50% DD
- **Implication**: Add Profit/DD ratio to our health reports and tournament ranking

### 3. ROBUSTNESS: Multi-Asset Testing is Non-Negotiable

**Sources**: Multiple videos consistently emphasize this

- A strategy that works on only 1 coin is overfitted — guaranteed to fail on future data
- Test same strategy, same params, across BTC, ETH, SOL, and 5+ diverse altcoins
- The best indicator on BTC (Bollinger) was the WORST on ETH (SuperTrend was best)
- Single-indicator strategies had 40-72% max drawdown across all tests
- Multi-indicator strategies achieved 2.5x less risk with 2x more profit
- **Implication**: Before graduating any strategy to live, backtest across full pair universe without param changes

### 4. SHORTING: Fundamentally Different Risk Profile

**Source**: "The Risks of Shorting Bitcoin and Crypto" (40min deep-dive)

**7 asymmetric risks of shorting:**
1. Continuous borrow fees (10-15% profit reduction)
2. Unlimited loss potential (vs max 100% loss on longs)
3. Fighting the long-term upward trend
4. Liquidation risk exists even at 1x short (you're already borrowing)
5. Short squeeze cascades
6. Amplified emotional pressure
7. Exchange counterparty risk (locked to exchange until close)

**Performance data**: Adding shorts to the Gaussian Channel strategy = slightly more profit but 11% higher drawdown. The short trades themselves were net negative.

**Mitigations:**
- Use only 25% of normal position size for shorts
- Keep shorts open for days only, not weeks/months
- Take profits aggressively on shorts
- **Implication**: FuturesSniperV1's -2% stoploss is appropriate. Consider reducing position size for short trades to 25% of long trades.

### 5. REPAINTING: The Silent Backtest Killer

**Source**: "Detect and Avoid Repainting in TradingView Strategies"

**5 root causes:**
1. Intra-bar execution / tick-size mismatch (backtest sees full candle at once)
2. "On Every Tick" mode (signals change as candle forms)
3. `security()` using current bar data (future data leak)
4. Lookahead enabled on cross-timeframe data
5. Markers plotted shifted into the past

**Fixes:**
- Trade on candle close ONLY
- Always use previous bar's data for cross-timeframe (`close[1]`)
- Never use "on every tick" / process_only_new_candles = True
- **Freqtrade equivalent**: `process_only_new_candles = True` (already set), proper `shift` on informative pairs

### 6. BACKTESTING PITFALLS: 4 Ways Results Lie

**Source**: "Stop Losing Money with WRONG TradingView Strategies and Settings"

1. **Order sizing bug**: "1 contract" = 1 BTC on $100 capital → impossible leverage
2. **Zero fees**: Going from 0% to 0.1% commission dropped returns by 10,800 percentage points
3. **Zero slippage**: Unrealistic on short timeframes (recommend 3 ticks minimum)
4. **Future data leakage**: Changing PineScript v2→v3 turned +20,000% into -60%

**Implication**: Always verify backtest configs have realistic fees (0.1% spot, 0.04% futures taker), startup_candle_count sufficient for indicator warmup

### 7. GAUSSIAN CHANNEL: Best Free Trend-Following Strategy

**Sources**: Multiple videos (automate, 10-month review, market timing)

**BTC Daily performance**: +1,895% since 2018, 30% max DD, PF 3.2
**10-month live results**: +51.74%, 8.57% max DD, 44% win rate

- Buy when price > upper Gaussian band, sell when price < upper band
- Daily chart preferred (4H variant: HL2, poles=4, sampling=144, multiplier=2)
- Lost money on Solana (sideways chop kills trend-following)
- No explicit stop-loss — all exits are signal-based
- 100% in/out position sizing (one trade at a time)
- **Implication**: Worth implementing as a Freqtrade strategy. Simple logic, proven live results, low drawdown

### 8. AI-ASSISTED STRATEGY DEVELOPMENT: Best Practices

**Sources**: "Claude AI can NOW auto-build strategies", "All Steps to Creating a GREAT Strategy with AI", "BEST AI for PineScript"

**AI model ranking (for trading code):**
1. OpenAI o1 — best overall, handles all difficulty levels
2. Claude Sonnet/Opus — strong on medium tasks, needs more context for hard ones
3. Horizon AI — TradingView-specific, slow and buggy
4. Gemini — only useful for easy tasks

**The correct workflow:**
1. Manually identify indicator on chart (AI cannot do this well)
2. Use AI to convert indicator → strategy code
3. Evaluate baseline results
4. Iteratively: find largest losing trade → ask AI to add filter/stoploss → verify improvement
5. Check for overfitting (multi-asset test)
6. Check for repainting

**Claude Code + local backtesting engine**:
- Demonstrated V1 (44% P&L) → V4 (3,605% P&L) via autonomous overnight iteration
- Claude can run backtests locally, evaluate results, and iterate without human intervention

### 9. TREND-FOLLOWING > BUY-AND-HOLD > DCA

**Sources**: "BUY & HOLD and DCA are HORRIBLE for Crypto", "How to Time the Crypto Market"

| Strategy | Net Profit (BTC 2018-present) | Max Drawdown |
|----------|-------------------------------|-------------|
| HODL | 369% | 76% |
| DCA | 3,185% | 13.6% |
| Trend Following (free) | 1,600% | 26% |
| Trend Following (paid) | 2,400% | 15% |

- HODL only works for indices, NOT individual assets
- DCA doesn't protect from drawdowns
- Any trend-following strategy (even basic 200 SMA) massively beats HODL on risk-adjusted returns
- **Key insight**: Evaluate strategies by drawdown performance, not peak performance
- Having cash during bear markets = purchasing power when everything is cheap

### 10. INDICATORS: Single vs Multi

**Source**: "How TradingView Indicators LIE TO YOU"

| Strategy Type | BTC Profit | Max Drawdown |
|---------------|-----------|-------------|
| Bull Market Support Band | 736% | 58.8% |
| SuperTrend | Less | ~47% |
| SMA 200 | Similar | ~40% |
| MACD | Moderate | 50% |
| Bollinger Bands | 1,187% | 50% |
| Multi-indicator | 2,300% | **19%** |

- Every single-indicator strategy had 40%+ drawdown
- Multi-indicator strategy: 2,300% with only 19% drawdown
- **Always combine 2-3 confirming signals**, never rely on a single indicator

### 11. BEST BUY SIGNALS: Contrarian Fear-Based Entries

**Source**: "The Best BUY SIGNALS are Scary AF"

- The best entry points coincide with maximum fear (crashes, FUD events)
- After 4-5 losing trades, humans skip signals — the next one is often the big winner
- Automation removes this emotional failure mode
- **Implication**: Our bots' advantage is that they execute mechanically during fear events

### 12. MARKET TIMING INDICATOR RANKING

**Source**: "How to Time the Crypto Market"

Ranked by effectiveness for crypto market timing:
1. **Gaussian Channel** — best free timing indicator
2. **MACD Crossover** — simple signal cross on longer TFs
3. **200 SMA** — simplest approach (buy above, sell below)
4. **Ichimoku (4H)** — viable free alternative
5. **Hull Suite (1D)** — mentioned as option

---

## Specific Strategy Ideas to Implement

### Gaussian Channel Strategy (highest priority)
- **Logic**: Buy when close > upper Gaussian band, sell when close < upper band
- **Timeframe**: 1D (primary) or 4H (with params: HL2, poles=4, sampling=144, multiplier=2)
- **Live results**: +51.74% in 10 months, 8.57% max DD
- **Backtest**: +1,895% since 2018, PF 3.2
- Would need custom Gaussian/Ehlers filter implementation in Freqtrade

### Williams Alligator Strategy
- **Logic**: Lips crosses above Jaw = buy, Lips crosses below Jaw = sell
- **Enhancement**: ATR-based stop-loss + additional filtering indicators
- **Results**: 2,200% profit, 42% DD on BTC; works across BTC/ETH/SOL/XRP
- Standard TA-Lib indicator, easy to implement

### Improved Ichimoku (4H)
- **Logic**: Tenkan/Kijun + Cloud + EMA confirmation
- **Results**: 3,500% on BTC, 33% DD, PF 3.1 (35% WR)
- Our killed IchimokuTrendV1 may have used wrong timeframe/params

---

## Validation of Our Current Approach

Things Michael's channel **confirms we're doing right**:
1. Full automation (removes emotional trading failures)
2. Multiple strategies running simultaneously
3. Stop-loss protection on all positions
4. BTC market guard / regime detection
5. Conservative drawdown limits (20%)
6. Bot rotation / killing underperformers
7. Sub-account isolation per bot
8. "Obsessed about not losing money" philosophy

Things to **consider changing**:
1. Move to 4H+ timeframes (away from 1h)
2. Add Profit/Drawdown ratio to evaluation metrics
3. Implement Gaussian Channel as a new strategy
4. Reduce short position sizes to 25% of longs
5. Multi-asset robustness testing before graduation
6. Let winners run longer (our ROI exits at 1-5% may be too aggressive for trend-following)
