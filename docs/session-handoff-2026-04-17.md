# Session Handoff — 2026-04-17

Comprehensive state dump for continuing work in future sessions.

## Current fleet state

```
Port 8095  KeltnerBounceV1   SPOT      $200  ACTIVE  TA mean reversion
Port 8096  FundingFadeV1     SPOT      $200  ACTIVE  Non-TA funding-rate long
Port 8097  FundingShortV1    FUTURES   $200  ACTIVE  Non-TA funding-rate short (2x)
```

Total dry-run capital: **$600**. All 3 strategies validated via backtest.

All killed bots (6 total): SupertrendStrategy, MasterTraderV1, BollingerBounceV1, BearCrashShortV1, AlligatorTrendV1, GaussianChannelV1.

## Backtest Engine v2 — current state

### Infrastructure (working, production-ready)
- **6-stage pipeline**: data → calibration → viability → walk_forward → robustness → reporting
- **1m-detail enforced** at all stages
- **Calibration-aware**: Viability wrappers apply dynamic pairlist + F&G history
- **Registered strategies**: auto-detected from `ft_userdata/engine/registry.py`
- **Results**: `~/ft_userdata/engine_results/{timestamp}_{mode}/`

### Key findings through 2026-04-17
1. **1h backtesting LIES**. Trailing stops/ROI evaluated at candle close hide intra-hour whipsaw. 1m-detail is mandatory.
2. **Trailing stops add noise** at 1m detail. Supertrend original (trailing on) = -54%, no-trailing = -3% over 3.3yr.
3. **TA signal space mostly exhausted**. Only ~0.02% hit rate (1 winner / 4940 combos).
4. **Funding rate signals are orthogonal**. Adding funding anchors surfaced 3 new validated edges.
5. **Calibration without pairlist simulation = 80% error.** Raw backtest takes stablecoin trades live never sees. Viability wrapper fixes this.

### Engine v2 calibration accuracy
- MasterTrader Mar 11-Apr 11 window: Viability +3.60% vs live +4.20% = **86% match**
- Keltner 3.3yr Viability vs Lab: +53.69% vs +51.85% = **97% match**

### Known engine v2 issues
- **Hyperopt walk-forward timeouts** (1800s limit) on 1m-detail backtests. Fix: extend timeout to 3600s or skip hyperopt for fixed-param strategies.
- **Monte Carlo perturbation bug** (`NoneType not iterable`) at engine/monte_carlo.py:275 when base_params is None.
- **Futures 1m data missing** — blocks full validation of FundingShortV1 and BearCrashShortV1.

## Strategy Lab — current state

### Infrastructure (production-ready)
- `ft_userdata/strategy_lab.py` — main CLI
- `ft_userdata/strategy_lab/` — engine, signals, exporter modules
- `ft_userdata/analyze_combo.py` — deep analysis tool (per-pair, per-year, walk-forward, MC)
- `ft_userdata/grid_scan.py` — multi-param grid scanner
- `ft_userdata/download_funding_rates.py` — Binance futures funding fetcher

### Signal inventory (6864 total combos as of 2026-04-17)
**Anchors (23):**
- Trend-following: supertrend (4 variants), supertrend_all, ema (3), macd
- Mean reversion: bb (2), keltner (2)
- Breakout: donchian (2)
- Multi-indicator: ichimoku
- Volume-weighted: vwap (2)
- Price action: bullish_engulfing
- **Funding (4)**: funding_neg, funding_p5, funding_p10, funding_below_mean

**Confirmations (15):** rsi (3), vol (2), adx (3), stoch, combined variants, **funding_neg, funding_p10**

**Gates (5):** btc_sma50, btc_sma50+nc24, btc_sma200, btc_sma50+sma200, btc_sma50+rsi35

**Exits (4):** tight, balanced, wide, roi_only

### Critical bugs already fixed
1. **1m entry offset (look-back bias)** — sim started 59min before entry. Fixed 2026-04-16.
2. **max_open not enforced across pairs** — dead code, each pair ran independently. Fixed.
3. **Funding rate timestamp precision** — feather stores ms not ns. Fixed via `.apply(x.timestamp())`.

### Data
- **1h**: 78 pairs, Jan 2023 - Apr 2026 (3.3 years)
- **1m**: 20 pairs, Jan 2023 - Apr 2026 (24M candles total)
- **Funding**: 20 pairs, 73k records 2023-2026
- **Futures 1h**: ~40 pairs Jul 2025+ (partial)
- **Futures 1m**: NONE (blocks full FundingShort validation)

## Current strategies — detailed specs

### KeltnerBounceV1 (port 8095)
```
Signal: kelt(20,2.5)+vol(1.75) | btc_sma50 | wide
Entry:  close crosses above (SMA25 - 2.5*ATR25)
Confirm: volume > 1.75x SMA20(volume)
Gate:   BTC > BTC_SMA50
Exit:   stoploss -7%, trailing +3% at 5% offset, ROI {0:10%, 360:7%, 720:4%, 1440:2%}

Validation: Lab +53.69%/3.3yr PF 1.79 DD 12%, 6/6 walk-forward,
            Freqtrade-native +51.47% matches within 1%.
Weakness:   Choppy/euphoric regimes (2024-H2 +1.69%)
```

### FundingFadeV1 (port 8096)
```
Signal: funding_below_mean+adx(25)+vol(1.5) | btc_sma50+sma200 | roi_only
Entry:  funding_rate < (rolling_mean - 1std) over 500 periods
Confirm: ADX > 25, volume > 1.5x SMA20
Gate:   BTC > SMA50 AND BTC > SMA200
Exit:   stoploss -5%, ROI {0:8%, 360:5%, 720:3%, 1440:2%}, no trailing

Validation: Lab +60.66%/3.3yr PF 1.29 DD 19.6% 431 trades, 6/6 walk-forward.
            2024-H2 +20.85% (inverse of Keltner's weakness).
Weakness:   2026-YTD -9.70% (bear start regime)
```

### FundingShortV1 (port 8097)
```
Signal: funding_above_mean+adx(25)+vol(1.5) | BTC weak | roi_only (FUTURES, short)
Entry:  funding_rate > (rolling_mean + 1std) over 500 periods
Confirm: ADX > 25, volume > 1.5x SMA20
Gate:   BTC < SMA50 OR BTC_RSI < 40
Exit:   stoploss -5%, ROI {0:6%, 360:4%, 720:3%, 1440:2%}, 2x leverage

Validation: 1h-only Jul 2025-Apr 2026: 161 trades, PF 1.40, +51.78%, DD 14.41%
Limitation: No futures 1m data. Full 3.3yr 1m-detail test blocked.
```

## Calibration pattern (MANDATORY for new strategies)

**Every new strategy MUST have a Viability wrapper** at `ft_userdata/user_data/strategies/{Strategy}Viability.py`:

```python
from {Strategy} import {Strategy}
from dynamic_pairlist_mixin import DynamicPairlistMixin

class {Strategy}Viability(DynamicPairlistMixin, {Strategy}):
    PAIRLIST_VOLUME_MIN = 5_000_000
    PAIRLIST_VOLUME_TOP_N = 40
    PAIRLIST_VOLATILITY_MIN = 0.03  # Match live config
    PAIRLIST_VOLATILITY_MAX = 0.75
    PAIRLIST_RANGE_MIN = 0.03
    PAIRLIST_RANGE_MAX = 0.50

    def confirm_trade_entry(self, pair, ..., current_time, ...):
        if not self.passes_dynamic_pairlist(pair, current_time):
            return False
        return True
```

Engine v2 auto-detects `{Strategy}Viability.py` and uses it. Without this, backtest takes stablecoin/low-volume trades live filters out — results are wrong.

See `/Users/palmer/.claude/projects/-Users-palmer-Work-Dev-Master-Trader/memory/feedback_viability_wrapper_mandatory.md` for full context.

## Future ideas — prioritized for next session

### Phase 3: More non-TA signals (2-3 sessions)
- **On-chain metrics** (Glassnode/Santiment APIs): whale transfers, exchange inflows/outflows, stablecoin supply
- **Order book imbalance** (requires real-time or depth snapshots)
- **Cross-exchange spread** (spot vs perp basis, exchange arbitrage)
- **Open interest divergence** (OI rising while price falling = hidden selling)

### Phase 4: Deploy-readiness hardening (1 session)
- [ ] Download futures 1m data for all active pairs (enables FundingShort full validation)
- [ ] Add FundingShortV1Viability wrapper
- [ ] Fix engine v2 hyperopt timeout (extend 1800s → 3600s or disable hyperopt for fixed-param strategies)
- [ ] Fix monte_carlo.py NoneType bug at line 275
- [ ] Wire Grafana FundingShort panel properly (currently one slot still shows "(available slot)")
- [ ] Clean up Grafana cached session state (timeframe variable still shows old bot list — user needs to click "Reset" in UI)

### Phase 5: Pre-live graduation checklist
- [ ] 30 days dry-run on all 3 bots matches backtest ±20%
- [ ] No bot exceeds 5 consecutive losses
- [ ] Portfolio DD < 15% overall
- [ ] Each bot's live trade count within 50-150% of backtest pace
- [ ] Individual pair P&L aligns (no single pair dominates losses)

### Phase 6: Scale
- Graduate to live with $17 per bot (minimum stake)
- Run 60 days live ≈ backtest
- Scale proportionally based on live:backtest convergence
- Deploy more strategies via Strategy Lab as orthogonal edges emerge

### Phase 7: Research (opportunistic)
- **Regime detection for MT**: MT failed backtest but has clear regime-dependent edge. Build regime classifier (BTC trend, volatility, F&G) + re-test MT gated by classifier. Might resurrect if regime-aware version has PF > 1.3.
- **Short-side Strategy Lab sweep**: mirror long-side signals for short entries. Currently lab is long-only.

## Critical files to read first in next session

1. `docs/session-handoff-2026-04-17.md` (this file)
2. `/Users/palmer/.claude/projects/-Users-palmer-Work-Dev-Master-Trader/memory/MEMORY.md`
3. `ft_userdata/engine/registry.py` — authoritative bot list + statuses
4. `ft_userdata/strategy_lab/signals.py` — signal inventory
5. `ft_userdata/strategy_lab/engine.py` — combo generator

## Key memory files to preserve
- `feedback_viability_wrapper_mandatory.md` — calibration pattern (MUST READ for new strategies)
- `feedback_1m_detail_required.md` — always use --timeframe-detail 1m
- `feedback_pairlist_strategy.md` — never blacklist individual coins
- `feedback_trading_philosophy.md` — win big, lose small
- `feedback_nbar_trailing_disaster.md` — trailing stops are noise
- `project_backtest_engine_v2.md` — engine architecture
- `project_graduation_criteria.md` — gates for going live

## Commits this session (2026-04-16 and 2026-04-17)

Recent session commits (in order):
- `47d75fb` — deploy KeltnerBounceV1, retire Supertrend + BollingerBounce
- `e3866c5` — KeltnerBounceV1Viability wrapper for accurate calibration
- `2c687b4` — fleet rationalization + funding rate signal infrastructure
- `3502a20` — deploy FundingFadeV1 (first non-TA strategy)
- `912d9ff` — kill MT + BearCrash (both failed backtest)
- `[latest]` — deploy FundingShortV1 + $200 wallet upgrade

## Open questions for user

1. **Should we download futures 1m data?** (~several hours of API calls, enables proper FundingShort validation)
2. **Regime detection for MT** — worth resurrecting with regime filter, or accept it's dead?
3. **Next orthogonal signal type** — funding worked, what's next? On-chain? Order book? Cross-exchange?
4. **Live graduation timing** — comfortable with 30 days? 60? Longer?
