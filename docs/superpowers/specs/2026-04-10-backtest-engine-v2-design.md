# Backtest Engine v2 — Design Spec

**Date:** 2026-04-10
**Status:** Draft
**Author:** Claude (architect) + Palmer (PM/stakeholder)

## Problem

Current backtesting infrastructure is fragmented across 3 scripts (`backtest_gate.py`, `hyperopt_optimizer.py`, `walk_forward.py`) with critical issues:

1. **Stale registries** — reference 5 killed bots, miss 4 active ones, wrong timeframe for SupertrendStrategy
2. **Walk-forward is broken** — optimizes params but tests OOS with BASE params, not optimized ones
3. **Invalid flags** — `--disable-param-export` doesn't exist for backtesting (hyperopt-only)
4. **Single loss function** — only SharpeHyperOptLoss, no robustness against metric overfitting
5. **No live calibration** — no mechanism to verify backtest reproduces actual live trading results
6. **No Monte Carlo** — no trade-shuffle or parameter perturbation analysis
7. **No Freqtrade analysis tools** — lookahead-analysis and recursive-analysis never used
8. **Limited pair coverage** — small static pairlists, no dynamic universe

## Solution

Single unified `backtest_engine.py` with 6-stage pipeline, 3 operating modes, and Bloomberg-grade analytics.

## Architecture

```
backtest_engine.py              # Main orchestrator (~1200 lines)
engine/
  __init__.py
  registry.py                   # Strategy registry (single source of truth)
  data.py                       # Data download + validation
  calibration.py                # Live vs backtest comparison
  viability.py                  # Full-year screening + Freqtrade analysis tools
  walk_forward.py               # WF with proper param injection
  hyperopt.py                   # Multi-loss tournament
  monte_carlo.py                # Trade shuffle + parameter perturbation
  reporting.py                  # Report generation + Telegram
  parsers.py                    # Freqtrade output parsing (shared)
  config_builder.py             # Dynamic config generation
```

Old scripts (`backtest_gate.py`, `hyperopt_optimizer.py`, `walk_forward.py`) become 5-line wrappers that import from `engine/` for backward compatibility with existing cron jobs.

## Strategy Registry — Single Source of Truth

```python
# engine/registry.py
STRATEGIES = {
    "SupertrendStrategy": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8084,
        "max_open_trades": 3,
        "stake_amount": 88,          # $88 USDT
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],   # needs BTC/USDT 1d for market guard
        "backtest_config": "backtest-SupertrendStrategy.json",
        "status": "active",
    },
    "MasterTraderV1": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8086,
        "max_open_trades": 3,
        "stake_amount": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-MasterTraderV1.json",
        "status": "active",
    },
    "AlligatorTrendV1": {
        "timeframe": "1d",
        "trading_mode": "spot",
        "port": 8091,
        "max_open_trades": 5,
        "stake_amount": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": [],
        "backtest_config": "backtest-AlligatorTrendV1.json",
        "status": "active",
    },
    "GaussianChannelV1": {
        "timeframe": "1d",
        "trading_mode": "spot",
        "port": 8092,
        "max_open_trades": 5,
        "stake_amount": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": [],
        "backtest_config": "backtest-GaussianChannelV1.json",
        "status": "active",
    },
    "BearCrashShortV1": {
        "timeframe": "1h",
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "port": 8093,
        "max_open_trades": 2,
        "stake_amount": 22,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-BearCrashShortV1.json",
        "pair_blacklist": ["BTC/USDT:USDT"],
        "status": "active",
    },
    "BollingerBounceV1": {
        "timeframe": "1h",
        "trading_mode": "spot",
        "port": 8094,
        "max_open_trades": 3,
        "stake_amount": 88,
        "image": "freqtradeorg/freqtrade:stable",
        "informative_tfs": ["1d"],
        "backtest_config": "backtest-BollingerBounceV1.json",
        "status": "active",
    },
}
```

## Operating Modes

| Mode | Epochs | WF Windows | Train/Test | Monte Carlo | Param Perturb | Use Case |
|------|--------|------------|------------|-------------|---------------|----------|
| `fast` | 300 | 3 | 90d / 30d | Skip | Skip | Weekly validation |
| `thorough` | 500 | 6 | 90d / 30d | 500 shuffles | ±10% | Monthly deep check |
| `rigorous` | 1000 | 6 | 120d / 30d | 1000 shuffles | ±10%, ±20% | Initial / quarterly |

## Pipeline Stages

### Stage 1: Data Preparation (`engine/data.py`)

```
Input:  mode, strategy list
Output: downloaded data for all required pairs + timeframes

Steps:
1. Fetch top 50 Binance pairs by 24h quote volume (spot)
   - API: GET /api/v3/ticker/24hr, sort by quoteVolume, filter USDT pairs
   - Filter: >$20M daily volume, listed >180 days
   - Exclude: stablecoins, leveraged tokens
2. For futures strategies, fetch top 20 futures pairs
   - API: GET /fapi/v1/ticker/24hr
3. Determine all required timeframes from strategy registry
   - Base TFs: 1h, 1d (covers all strategies)
   - Informative TFs: 5m (for --timeframe-detail), 1d (for BTC guard)
4. Download via Freqtrade: docker run ... download-data
5. Validate: check each pair has data spanning full backtest range
   - Read .feather files, verify date range coverage
   - Report gaps
```

### Stage 2: Live vs Backtest Calibration (`engine/calibration.py`)

**Purpose:** Ensure backtest engine reproduces live trading results. If it doesn't, all other stages are meaningless.

```
Input:  strategy, its sqlite DB, its live config
Output: calibration score (0-100), divergence report

Steps:
1. Read actual trades from sqlite DB
   - SELECT pair, open_date, close_date, open_rate, close_rate,
     close_profit, close_profit_abs, exit_reason, stake_amount
     FROM trades WHERE is_open=0
2. Determine exact timerange from first to last trade
3. Extract exact pairlist from trades (SELECT DISTINCT pair)
4. Generate backtest config matching live exactly:
   - Same pairs, same stake_amount, same max_open_trades
   - Same stoploss, trailing, ROI from live config
5. Run backtest on that exact timerange + pairlist
6. Compare trade-by-trade:
   - Match trades by pair + open_date (±2 candles tolerance)
   - Compare: entry price, exit price, profit, exit reason
   - Metrics:
     a) Trade match rate: % of live trades found in backtest
     b) Profit correlation: Pearson r between live and BT profit per trade
     c) Aggregate P&L delta: |live_total - bt_total| / live_total
     d) Exit reason concordance: % matching exit reasons
7. Calibration score:
   - 90-100: Excellent reproduction, trust backtest fully
   - 70-89: Good, minor divergences (slippage, timing)
   - 50-69: Moderate — some structural difference
   - <50: Broken — backtest doesn't represent this strategy's live behavior
8. If score < 70: flag for investigation, log specific divergent trades
```

### Stage 3: Viability Screening (`engine/viability.py`)

**Purpose:** Kill dead strategies before wasting compute on optimization.

```
Input:  strategy, top-50 pair data
Output: viable (bool), viability report

Steps:
1. Lookahead analysis (Freqtrade built-in)
   - docker run ... lookahead-analysis --strategy X --timerange ...
   - Detects if strategy uses future data (indicator bias)
   - FAIL = immediate kill, no exceptions

2. Recursive analysis (Freqtrade built-in)
   - docker run ... recursive-analysis --strategy X --timerange ...
   - Detects if indicators depend on dataset length
   - WARN = flag but don't kill

3. Full-period backtest (top 50 pairs, full year)
   - Parse: trades, PF, WR, DD, Sharpe, Sortino, Calmar, per-pair breakdown

4. Kill criteria (ANY = kill):
   - 0 trades in full year
   - PF < 0.5 over full year
   - Max DD > 50%
   - Lookahead analysis FAIL
   - Fewer than 10 trades AND negative P&L

5. Per-pair analysis:
   - Backtest with --export trades, parse JSON results
   - Group by pair: profit, trade count, win rate, avg duration
   - Identify: top 5 profit pairs, bottom 5 loss pairs
   - "Pair concentration risk": if >50% profit from 1-2 pairs = flag

6. Output:
   - VIABLE / MARGINAL / DEAD
   - Per-pair heatmap data
   - Lookahead/recursive results
   - Recommended pair whitelist (pairs with positive expectancy)
```

### Stage 4: Walk-Forward Optimization (`engine/walk_forward.py`, `engine/hyperopt.py`)

**Purpose:** Find robust parameters via rolling optimization with proper OOS validation.

```
Input:  viable strategies, mode config
Output: consensus params per strategy

Window Generation (mode=thorough):
  Window 1: train 2025-04-10→2025-07-09, test 2025-07-09→2025-08-08
  Window 2: train 2025-05-10→2025-08-08, test 2025-08-08→2025-09-07
  ...
  Window 6: train 2025-09-10→2025-12-09, test 2025-12-09→2026-01-08

For each strategy:
  For each loss function [SharpeHyperOptLossDaily, SortinoHyperOptLossDaily, CalmarHyperOptLoss]:
    For each window:
      1. Run hyperopt on train period
         - --spaces all (buy sell roi stoploss trailing)
         - --epochs {mode.epochs}
         - --min-trades 10
         - --print-json
         - -j -1 (all CPU cores)
      2. Parse best params from hyperopt output
      3. Generate temp config with optimized params injected
         KEY FIX: create config where:
         - minimal_roi = hyperopt result
         - stoploss = hyperopt result
         - trailing_* = hyperopt result
         - buy/sell params written to strategy's hyperopt results file
      4. Run backtest on OOS test period with injected params
      5. Record: OOS profit, trades, WR, DD, Sharpe

  Consensus scoring:
    For each param set (roi, stoploss, trailing):
      - Score = average OOS Sharpe across all 3 loss functions × all windows
      - Params must be OOS-profitable under >= 2/3 loss functions
      - Params must be OOS-profitable in >= 4/6 windows
      - Reject if any window has DD > 35%
    Best consensus params = highest average OOS score meeting all criteria

  Output per strategy:
    - Best params per loss function
    - Consensus params (recommended)
    - Per-window OOS performance table
    - Robustness %: (profitable_windows / total_windows) across all loss functions
```

### Stage 5: Robustness Validation (`engine/monte_carlo.py`)

**Purpose:** Stress-test consensus params. Catch fragile overfitting.

#### 5a: Monte Carlo Trade Shuffle

```
Input:  backtest trade list (from Stage 4 best OOS run)
Output: MC score, DD distribution, survival rate

Method:
1. Run full-year backtest with consensus params, export trades JSON
2. Parse trade list: [profit_abs, duration, pair, ...]
3. For N iterations (500 or 1000 per mode):
   a. Randomly shuffle trade execution order
   b. Optionally skip X% of trades (simulate missed entries)
      - Skip rate: random 0-15%
   c. Simulate equity curve with shuffled trades
   d. Record: final equity, max drawdown, max consecutive losses
4. Analyze distribution:
   - Median final equity (must be > starting capital)
   - 95th percentile max DD (must be < 2x base DD)
   - Probability of ruin (equity < 50% of start): must be < 5%
   - Worst-case DD across all shuffles
5. MC Score:
   - 80-100: Robust — strategy survives trade reordering
   - 60-79: Acceptable — some fragility but tradeable
   - <60: Fragile — results depend on specific trade sequence

Note: This runs in pure Python, no Docker needed. Fast (~10s for 1000 shuffles).
```

#### 5b: Parameter Perturbation

```
Input:  consensus params from Stage 4
Output: stability score, sensitivity map

Method:
1. For each numeric param (stoploss, ROI values, trailing values):
   a. Create variants: base × [0.8, 0.9, 1.0, 1.1, 1.2]
   b. Run backtest with each variant (other params held at base)
   c. Record: P&L, PF, DD for each variant
2. Stability analysis:
   - "Flat top": param changes ±20% and P&L stays within 30% → stable
   - "Cliff edge": param changes ±10% and P&L drops >50% → overfitted
   - "Monotonic": P&L consistently improves in one direction → param not at optimum
3. Per-param sensitivity:
   - LOW: ±20% changes P&L < 15% → robust
   - MEDIUM: ±20% changes P&L 15-40% → normal
   - HIGH: ±10% changes P&L > 40% → fragile, likely overfitted
4. Overall stability score: average of per-param scores
   - PASS: no HIGH sensitivity params, avg score > 60
   - WARN: 1 HIGH sensitivity param
   - FAIL: 2+ HIGH sensitivity params

This requires N backtests where N = params × 5 variants.
For typical strategy (~8 params): 40 backtests. At ~30s each = ~20 min.
```

### Stage 6: Reporting (`engine/reporting.py`)

```
Output formats:
1. Console: rich table summary
2. JSON: full structured results → engine_results/{date}_{mode}/
3. Telegram: condensed summary with kill/keep/optimize recommendations

Report card per strategy:
  ┌─────────────────────────────────────────────┐
  │ MASTERTRADERV1 — REPORT CARD                │
  ├─────────────────────────────────────────────┤
  │ Calibration:    87/100 (Good)               │
  │ Viability:      VIABLE (PF 1.24, 180 trades)│
  │ Lookahead:      PASS                        │
  │ Walk-Forward:   4/6 windows profitable      │
  │ Consensus PF:   1.18 (Sharpe/Sortino/Calmar)│
  │ Monte Carlo:    72/100 (Acceptable)         │
  │ Perturbation:   PASS (0 HIGH sensitivity)   │
  │                                             │
  │ RECOMMENDATION: KEEP + APPLY CONSENSUS      │
  │                                             │
  │ Top pairs: TAO, BNB, ETH                    │
  │ Drop pairs: DOGE, SHIB (negative expectancy)│
  │ Suggested params: [see full report]         │
  └─────────────────────────────────────────────┘

Kill/Keep logic:
  KILL:     viability=DEAD OR calibration<50 OR MC<40
  OPTIMIZE: viability=VIABLE AND calibration>=70 AND MC>=60
  MONITOR:  viability=MARGINAL OR calibration 50-69 OR MC 40-59
```

## CLI Interface

```bash
# Full pipeline, all active strategies, rigorous mode
python backtest_engine.py --mode rigorous

# Single strategy, thorough mode
python backtest_engine.py --strategy SupertrendStrategy --mode thorough

# Only specific stages
python backtest_engine.py --mode fast --stages calibration,viability

# Skip data download (already have it)
python backtest_engine.py --mode thorough --skip-download

# List strategies from registry
python backtest_engine.py --list

# Compare live vs backtest for one strategy
python backtest_engine.py --calibrate MasterTraderV1

# Report only (re-process last results)
python backtest_engine.py --report --telegram
```

## Output Structure

```
~/ft_userdata/engine_results/
  2026-04-10_rigorous/
    run_config.json           # Mode, strategies, timestamps
    data_prep.json            # Pairs downloaded, data ranges
    calibration/
      SupertrendStrategy.json
      MasterTraderV1.json
      ...
    viability/
      SupertrendStrategy.json # Includes per-pair breakdown
      ...
    walk_forward/
      SupertrendStrategy/
        sharpe_results.json
        sortino_results.json
        calmar_results.json
        consensus_params.json
      ...
    robustness/
      SupertrendStrategy/
        monte_carlo.json      # DD distribution, survival stats
        perturbation.json     # Per-param sensitivity
      ...
    report/
      summary.json
      report_cards.txt
      telegram_message.txt
```

## Backward Compatibility

Old scripts become thin wrappers:

```python
# backtest_gate.py (updated)
#!/usr/bin/env python3
"""Backward-compatible wrapper. Use backtest_engine.py directly."""
from engine.registry import STRATEGIES
from engine.viability import run_viability_screen
# ... delegates to engine modules
```

Existing cron jobs continue working. New cron:

```
# Weekly fast check
0 4 * * 0 cd ~/ft_userdata && python3 backtest_engine.py --mode fast --report

# Monthly thorough
0 2 1 * * cd ~/ft_userdata && python3 backtest_engine.py --mode thorough --report
```

## Constraints

- All backtests run via Docker (`freqtradeorg/freqtrade:stable`)
- Futures strategies need `freqtrade:stable` with `--trading-mode futures`
- No `--disable-param-export` on backtesting (hyperopt-only flag, use `--no-export` or omit)
- Hyperopt param injection: write to temp config file, NOT strategy JSON (avoids hyperopt auto-export bug)
- VPN check: verify Binance reachable before data download stage
- Respect MasterTraderV1 DO NOT TOUCH for live config — engine can propose but never auto-apply

## Success Criteria

1. Calibration stage reproduces MasterTraderV1 live results within 20% P&L delta
2. GaussianChannelV1 correctly flagged as DEAD (0 trades)
3. Full rigorous run completes in <12 hours for 6 strategies
4. Monthly thorough run completes in <6 hours
5. Weekly fast run completes in <2 hours
6. Monte Carlo catches obviously fragile params (e.g., N-bar trailing disaster)
7. Parameter perturbation flags cliff-edge params before they blow up live
