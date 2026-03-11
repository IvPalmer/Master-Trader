# Automated Strategy Management System

> Created 2026-03-11. Documents the self-improving automation layer for all Freqtrade bots.

---

## Overview

Five automation scripts run on schedule to monitor, analyze, validate, optimize,
and rebalance the 7-bot Freqtrade portfolio without manual intervention.

All scripts live at `~/ft_userdata/` and send reports to Telegram via webhook.

---

## Scripts

### 1. strategy_health_report.py — Daily Health Check

**Schedule:** Daily 23:00 UTC (20:00 São Paulo)

**What it does:**
- Queries all 7 bot APIs for trades, open positions, profit data
- Computes health score (0-100) per strategy based on:
  - Win rate (20pts), risk/reward ratio (25pts), profit factor (20pts)
  - Exit quality (15pts), return consistency (10pts), trading activity (10pts)
- Flags issues: inverted risk/reward, stale positions, high force-exit rate
- Generates actionable recommendations
- Saves state for trend comparison (day-over-day deltas)

**Health labels:** EXCELLENT (90+), GOOD (70-89), WARNING (50-69), POOR (30-49), CRITICAL (0-29)

**Usage:**
```bash
python3 strategy_health_report.py           # Full report → Telegram
python3 strategy_health_report.py --stdout   # Print only
python3 strategy_health_report.py --json     # Raw JSON metrics
```

### 2. backtest_gate.py — Backtesting Validation

**Schedule:** Weekly Sunday 04:00 UTC

**What it does:**
- Runs Freqtrade backtesting via Docker for each strategy
- Uses static pairlist (top 10 by volume) for consistency
- Evaluates against pass/fail thresholds:
  - Sharpe > 0.3, max drawdown < 20%, win rate > 45%, profit factor > 0.8
- Reports which strategies PASS or FAIL the gate

**Usage:**
```bash
python3 backtest_gate.py SupertrendStrategy          # One strategy
python3 backtest_gate.py --all --report              # All + Telegram
python3 backtest_gate.py ClucHAnix --days 90         # Custom window
```

### 3. hyperopt_optimizer.py — Parameter Optimization

**Schedule:** Weekly Sunday 06:00 UTC

**What it does:**
- Runs Freqtrade hyperopt (200 epochs) on 60-day training window
- Optimizes: ROI table, stoploss, trailing stop parameters
- Validates optimized params on 20-day out-of-sample window
- Generates proposals: APPROVE / REJECT / SKIP with reasoning
- Proposals saved to `~/ft_userdata/optimization_proposals/`
- **Does NOT auto-deploy** — requires human approval

**Usage:**
```bash
python3 hyperopt_optimizer.py ClucHAnix              # Optimize one
python3 hyperopt_optimizer.py --all --report         # All + Telegram
python3 hyperopt_optimizer.py ClucHAnix --apply      # Apply approved proposal
```

### 4. tournament_manager.py — Capital Rebalancing

**Schedule:** Weekly Sunday 05:00 UTC

**What it does:**
- Ranks strategies by composite score (Sharpe 35%, win rate 20%, profit factor 20%, profit 15%, drawdown -10%)
- Computes EMA-weighted risk-adjusted allocations ($350-$2100 per bot)
- **Health score integration** (added 2026-03-11):
  - Auto-pauses strategies with health score < 30 for 3+ consecutive days
  - Reduces allocation by 50% for strategies scoring < 50
- Updates config files and restarts Docker containers

### 5. walk_forward.py — Overfitting Prevention

**Schedule:** Monthly 1st at 07:00 UTC

**What it does:**
- Splits history into rolling windows (60-day train / 20-day test)
- Hyperopt on each training window, backtest on each test window
- Aggregates all out-of-sample results for true strategy assessment
- Verdict: ROBUST (75%+ windows profitable) / MARGINAL / WEAK / FAILED

**Usage:**
```bash
python3 walk_forward.py SupertrendStrategy           # One strategy
python3 walk_forward.py --all --windows 4            # 4 windows, all strategies
```

---

## Schedule (all UTC)

| Time | Frequency | Script | Output |
|------|-----------|--------|--------|
| 23:00 | Daily | `strategy_health_report.py` | Health scores + flags → Telegram |
| 03:00 Sun | Weekly | Cron: data download | Fresh 5m/1h data for backtesting |
| 04:00 Sun | Weekly | `backtest_gate.py --all` | Pass/fail per strategy → Telegram |
| 05:00 Sun | Weekly | `tournament_manager.py` | Rebalance allocations + Telegram |
| 06:00 Sun | Weekly | `hyperopt_optimizer.py --all` | Optimization proposals → Telegram |
| 07:00 1st | Monthly | `walk_forward.py --all` | Robustness validation → Telegram |

Additionally, claude-assistant runs:
- 09:00 São Paulo (12:00 UTC) — Morning portfolio status
- 21:00 São Paulo (00:00 UTC) — Evening portfolio status
- 20:00 São Paulo (23:00 UTC) — Health report via Claude

---

## State Files

| File | Purpose |
|------|---------|
| `health_report_state.json` | Previous health scores for trend comparison |
| `tournament_state.json` | Tournament history, health score tracking |
| `optimization_proposals/*.json` | Hyperopt proposals awaiting review |
| `walk_forward_results/*.json` | Walk-forward validation results |

---

## Design Principles

1. **No auto-deploy of parameter changes** — all optimization results require human approval
2. **Evidence over intuition** — every decision backed by backtest data
3. **Out-of-sample validation** — never trust in-sample results alone
4. **Layered defense** — health report catches issues, tournament reduces allocation, circuit breaker stops everything
5. **Transparency** — every script sends Telegram reports, all results saved to disk
