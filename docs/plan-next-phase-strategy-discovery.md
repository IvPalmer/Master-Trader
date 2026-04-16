# Plan: Strategy Discovery & Edge Finding
## Post-Engine Phase — April 2026

### Context
Backtest Engine v2 is complete and validated. It revealed that none of our
current strategies have reliable edge at 1m-detail precision. The engine
is the weapon — we need better ammunition.

### Available Assets
- Engine: 6-stage pipeline, 1m detail, 3.3-year data (24M candles)
- strategy_lab.py: screens 2000+ signal combos in 90 seconds
- 14 pairs with 1m data back to Jan 2023
- MasterTraderV1 live at peak (+$3.67, PF 2.36 live)
- SupertrendStrategy live (deployed ROI-only, needs new signals)

---

## Phase 1: Signal Screening (1-2 sessions)

**Goal**: Find entry signals with >55% accuracy at 1m-detail pricing.

**Steps**:
1. Update `strategy_lab.py` to use `--timeframe-detail 1m`
2. Screen signal combos on the top 8 pairs (proven profitable pairs)
3. Use 3.3-year data for screening (Jan 2023 - Apr 2026)
4. Filter: minimum 200 trades, WR > 55%, PF > 1.2 at 1m detail
5. Export top 10 signal combos for deeper validation

**Signal types to test**:
- Supertrend variants (different multipliers/periods)
- EMA crossover + RSI (current MasterTrader signal, but optimized)
- Bollinger Band squeeze breakouts
- MACD histogram divergence
- ADX trend strength + directional movement
- Ichimoku cloud entries
- Volume-weighted entries (OBV, VWAP proximity)

**Success criteria**: At least 3 signals pass PF > 1.2 over 3.3 years at 1m detail.

---

## Phase 2: Walk-Forward Validation (1 session per signal)

**Goal**: Prove signals aren't overfit.

**Steps**:
1. Take top 3 signals from Phase 1
2. Run walk-forward: 6 windows, 90-day train (5m detail), 30-day OOS (1m detail)
3. Require 4/6 OOS windows profitable
4. Run Monte Carlo (1000 shuffles) on the full 3.3-year result
5. Require: 0% ruin probability, <40% median DD

**Success criteria**: At least 1 signal passes walk-forward with 4/6 profitable OOS windows.

---

## Phase 3: MasterTraderV1 Regime Detection (1 session)

**Goal**: Auto-pause MasterTrader when its regime ends.

**Steps**:
1. Analyze the 3.3-year backtest to identify WHEN MasterTrader is profitable
   (which months, what BTC conditions, what volatility regime)
2. Build a regime classifier: bull/bear/range based on BTC SMA200, ADX, volatility
3. Backtest MasterTrader WITH regime gating: only trade during favorable regime
4. If regime-gated backtest shows PF > 1.0 over 3.3 years, deploy

**Key question**: Is MasterTrader's edge "EMA crossover in bull markets" or "EMA
crossover with specific pairlist in recent months"? If the former, regime gating
fixes it. If the latter, it's unfixable.

---

## Phase 4: Edge Research (ongoing)

**Goal**: Identify what TYPES of signals have real edge in crypto.

**Research areas**:
1. **Funding rate arbitrage** — perpetual futures funding rate as entry signal
   (when funding is extremely negative, longing spot has positive expected value)
2. **Cross-exchange price dislocation** — brief price differences between exchanges
3. **On-chain metrics** — whale wallet movements, exchange inflows/outflows
4. **Volatility regime switching** — trade vol expansion/contraction, not direction
5. **Market microstructure** — order book imbalance, bid-ask spread as signal

**For each**: research → prototype in strategy_lab → validate with engine → deploy

---

## Phase 5: Infrastructure (if Phase 1-2 succeed)

**Goal**: Scale from dry-run to live.

**Steps**:
1. Graduate validated strategy from dry-run to live (per graduation criteria)
2. Start with minimum stake (R$100 / ~$17 USDT)
3. Run live for 30 days alongside dry-run for comparison
4. Scale if live matches dry-run within 10%

---

## Priority Order
1. Phase 1 (signal screening) — highest ROI, fast, uses existing tools
2. Phase 3 (regime detection) — protects MasterTrader, our only earner
3. Phase 2 (walk-forward) — validates Phase 1 winners
4. Phase 4 (research) — ongoing, long-term edge development
5. Phase 5 (live) — only after proven edge exists

## Time Estimate
- Phase 1: 1-2 sessions (strategy_lab runs + analysis)
- Phase 2: 1 session per signal (walk-forward is ~2 hours per signal)
- Phase 3: 1 session (regime analysis + implementation)
- Phase 4: ongoing research
- Phase 5: 30+ days live testing
