# Strategy Lab — Design Spec

**Date**: 2026-03-30
**Goal**: Modular framework to discover profitable entry signal combinations via fast screening + Freqtrade validation.

## Problem

Both SupertrendStrategy (PF 0.81) and MasterTraderV1 (PF 0.46) are unprofitable over 7-12 months. Parameter optimization (stoploss, ROI, trailing) cannot fix bad entry signals. We need to test fundamentally different entry approaches.

## Architecture

```
strategy_lab/
  signals.py      — Signal module library (entry, regime, exit)
  engine.py       — Fast screening engine (precompute, simulate, score)
  exporter.py     — Freqtrade strategy file generator
strategy_lab.py   — CLI entry point
```

### Phase 1: Precompute Indicators
Load candle data for all pairs + BTC. Compute every indicator variant once:
- SMA: 9, 20, 50, 100, 200
- EMA: 5, 9, 12, 21, 26, 50
- RSI: 7, 14, 21
- MACD: standard (12,26,9)
- Bollinger: (20,2), (20,3)
- Supertrend: multipliers 1-7, periods 7-21
- ADX: 14
- Stochastic: 14
- ATR: 14
- Volume SMA: 20

All cached as DataFrame columns per pair.

### Phase 2: Screen Combos
Generate ~480 signal combinations using tiered approach:
- Tier 1 (anchor): 1 of supertrend/ema_cross/bollinger/macd — with param variants
- Tier 2 (confirm): 1-2 of rsi_range/volume_spike/adx_trending/stoch_oversold
- Tier 3 (regime): 1-2 of btc_sma/btc_crash/volatility_regime
- Tier 4 (exit): 3 profiles (tight/balanced/wide)

For each combo, iterate all pairs:
1. Apply entry signals (AND) → entry timestamps
2. Apply regime gates → filter blocked entries
3. Simulate each trade forward candle-by-candle (reuses rebuild_history.py logic)
4. Collect metrics: trades, wins, losses, PF, P&L%, max DD%, Profit/DD ratio

Score: `PF * (P&L% / max(DD%, 0.1)) * min(1, trades/50)`

### Phase 3: Validate Winners
Top 10 combos → auto-export as Freqtrade .py files → run real backtest across 3 windows:
- Bull (Sep-Oct 2025)
- Bear (Nov 2025-Feb 2026)
- Recent (Feb-Mar 2026)

Robust = profitable (PF > 1.0) in >= 2 of 3 windows.

### Phase 4: Export
Winners exported as deployable `LabStrategy_NNN.py` files with:
- All indicator computation in `populate_indicators()`
- Entry logic in `populate_entry_trend()`
- BTC informative pair for regime gates
- Standard Freqtrade exit params (stoploss, ROI, trailing)
- `exit_profit_only` if specified
- No market_intelligence dependency (added manually post-deployment)

## Signal Modules

### Entry Signals
| Signal | Parameters | Logic |
|--------|-----------|-------|
| `supertrend` | multiplier, period | All N supertrend bands = 'up' |
| `ema_crossover` | fast, slow | fast EMA crosses above slow EMA |
| `rsi_range` | low, high | RSI within [low, high] |
| `macd_crossover` | — | MACD line crosses above signal |
| `bollinger_bounce` | period, std | Close was below lower band, now above |
| `volume_spike` | multiplier | Volume > multiplier * SMA(20) of volume |
| `price_above_sma` | period | Close > SMA(period) |
| `adx_trending` | threshold | ADX > threshold |
| `stoch_oversold` | threshold | Stochastic K < threshold and crossing up |

### Regime Gates (BTC-based)
| Gate | Parameters | Logic |
|------|-----------|-------|
| `btc_above_sma` | period | BTC close > BTC SMA(period) |
| `btc_rsi_floor` | threshold | BTC RSI > threshold |
| `btc_no_crash` | lookback, pct | BTC not dropped pct% in lookback candles |
| `volatility_regime` | max_mult | Pair ATR < max_mult * ATR SMA(50) |

### Exit Profiles
| Profile | Stoploss | Trail | Trail Offset | ROI |
|---------|----------|-------|-------------|-----|
| tight | -3% | 1.5% | 2% | 3%/2%/1.5%/0.8% |
| balanced | -5% | 2% | 3% | 5%/3%/2%/1% |
| wide | -7% | 3% | 5% | 10%/7%/4%/2% |

## Combo Generation

```
anchors = [
    supertrend(3,10), supertrend(4,8), supertrend(5,14),
    ema_crossover(9,21), ema_crossover(12,26),
    bollinger_bounce(20,2),
    macd_crossover(),
]
confirmations = [
    [], [rsi_range(30,70)], [rsi_range(25,65)],
    [volume_spike(1.5)], [volume_spike(2.0)],
    [adx_trending(20)], [adx_trending(25)],
    [rsi_range(30,70), volume_spike(1.5)],
    [rsi_range(30,70), adx_trending(25)],
    [stoch_oversold(20)],
]
gates = [
    [btc_above_sma(50)],
    [btc_above_sma(50), btc_no_crash(24, 3)],
    [btc_above_sma(200)],
    [btc_above_sma(50), volatility_regime(2.0)],
]
exits = [tight, balanced, wide]

total = 7 * 10 * 4 * 3 = 840 combos
```

## CLI Usage

```bash
# Full run: screen + validate + export
python3 strategy_lab.py --timerange 20250901-20260331 --top 10

# Quick screen only (no Freqtrade validation)
python3 strategy_lab.py --timerange 20250901-20260331 --screen-only

# Test a specific combo
python3 strategy_lab.py --combo "supertrend(3,10)+rsi_range(30,70)|btc_sma(50)|balanced"

# Use pairs from existing bot config
python3 strategy_lab.py --pairs-from SupertrendStrategy --timerange 20250901-20260331
```

## Success Criteria
- At least 1 combo with PF > 1.2 across full 7-month window
- At least 1 combo profitable in both bull AND bear windows
- Screening completes in < 20 minutes for ~800 combos
- Generated strategy files run in Freqtrade without modification
