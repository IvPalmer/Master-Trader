# Risk Management Implementation Plan

> Created 2026-03-11. This is the master plan for implementing risk controls.
> All research files are in /research/ — read them before implementing.

---

## Current State (as of 2026-03-11 ~11:30 UTC)

### Portfolio
- 7 active bots (CombinedBinH PAUSED), $7K total dry-run capital
- +$89.79 closed profit, -$85.49 unrealized = **+$4.30 true net P/L**
- 17 open trades, 5 deeply underwater on XAI/USDT and PIXEL/USDT

### Critical Gaps Found
1. ZERO portfolio-level protections (no StoplossGuard, MaxDrawdown, CooldownPeriod)
2. Correlated exposure: 3 bots holding XAI ($605), 2 holding PIXEL ($407) = 30% on 2 coins
3. ClucHAnix -32% stoploss (insane for dip-buyer)
4. NASOSv5 and ElliotV5 have NO regime filters
5. NFI X6 has -99% stoploss with use_custom_stoploss=False
6. No time-based exit tightening on any strategy
7. All dip-buyers share same VolumePairList = guaranteed overlap

### Files Modified So Far
- `docker-compose.yml` — CombinedBinH commented out, depends_on updated
- `metrics_exporter.py` — CombinedBinH commented out
- `tournament_manager.py` — CombinedBinH commented out
- `strategies/ClucHAnix.py` — ADX regime threshold 25→35

---

## Research Files (read these first)
- `research/risk-management.md` — Overall risk strategy, Freqtrade protections, code templates
- `research/stoploss-evidence.md` — Evidence-based stoploss levels (PENDING)
- `research/portfolio-theory.md` — Kelly Criterion, position sizing, drawdown theory (PENDING)
- `research/trade-data-analysis.md` — Our own MAE/trade data analysis (PENDING)
- `research/freqtrade-protections-guide.md` — Exact Freqtrade config syntax (PENDING)

---

## Implementation Phases

### Phase 1: Protections + Stoploss Tightening -- DONE 2026-03-11
**Added `@property protections` to ALL 7 strategy .py files (not config JSON).**

Settings applied:
- **5m dip-buyers** (ClucHAnix, NASOSv5, ElliotV5):
  - CooldownPeriod: 5 candles (25min)
  - StoplossGuard: 3 stops in 24 candles (2h) → pause 12 candles (1h)
  - LowProfitPairs: -2% over 72 candles → lock pair 120 candles (10h)
  - MaxDrawdown: 10% over 576 candles (48h) → pause 288 candles (24h)
- **1h strategies** (Supertrend, MasterTraderV1):
  - CooldownPeriod: 2 candles (2h)
  - StoplossGuard: 2 stops in 48 candles (48h) → pause 24 candles (24h)
  - LowProfitPairs: -5% over 288 candles → lock pair 48 candles
  - MaxDrawdown: 20% over 48 candles → pause 12 candles
- **MasterTraderAI**: Similar to 1h but with higher trade_limit (4) and 10% MaxDrawdown
- **ClucHAnix pHSL**: Tightened from -0.32 to -0.20

All bots restarted and confirmed healthy. Protections ACTIVE.

### Phase 2: Stoploss Fixes -- DONE 2026-03-11
**Fixed dangerous stoploss settings and added regime filters.**

| Strategy | Before | After | Changes |
|----------|--------|-------|---------|
| ClucHAnix | -32% custom, ADX>25 | -20% custom, ADX>35 | Tightened pHSL, loosened regime filter |
| NASOSv5 | -15% custom, no filter | -15% + ATR/ADX regime | Added regime filter to all 3 entry conditions |
| ElliotV5 | -18.9% hard, no filter, ignore_roi=True | -18.9% + ATR/ADX regime, ignore_roi=False | Added regime filter, fixed ignore_roi |
| SupertrendStrategy | -26.5% hard | -26.5% | Already has regime filter, leave for now |
| MasterTraderV1 | -5% hard | -5% | OK — best risk profile |
| MasterTraderAI | -5% hard | -5% | OK — has ML regime filter |
| NFI X6 | -99% hard | -25% safety floor | Tightened from -99% to -25%, custom_exit handles normal exits |

Regime filter logic (NASOSv5, ElliotV5, ClucHAnix):
- `regime_volatile`: ATR(14) > 2.0 × SMA(ATR, 50) → skip entry
- `regime_trending`: ADX(14) > 35 → skip entry (mean reversion only in ranging markets)

### Phase 2b: MAE-Based Stoploss Tightening -- DONE 2026-03-11
**Tightened stoplosses based on actual trade data (95% of winners MAE < -4.95%)**
- ClucHAnix pHSL: -20% → **-8%** | NASOSv5: -15% → **-8%** | ElliotV5: -18.9% → **-8%** | Supertrend: -26.5% → **-10%**
- Force-exited 5 bleeding positions (XAI×3 at -13-16%, PIXEL at -9%, FLOW at -4%)

### Phase 3: Time-Based Exit Tightening -- DONE 2026-03-11
**Aggressive time exits for 5m strategies (93% of winners close in <50min)**

5m dip-buyers (ClucHAnix, NASOSv5, ElliotV5): 0-2h normal → 2-4h ATR×2 → 4-8h -3% max → 8h+ force close

Changes:
- ClucHAnix: Added time-based logic before existing stepped profit-lock + `_atr_stoploss()` helper
- NASOSv5: Added time-based logic before existing tiered profit-lock + `_atr_stoploss()` helper
- ElliotV5: Enabled `use_custom_stoploss = True`, added full `custom_stoploss()` with time-based exits + `_atr_stoploss()` helper

### Phase 4: Anti-Correlation / Pairlist Diversification -- DONE 2026-03-11
**Goal: Prevent 5 bots buying the same coin**

Solution: OffsetFilter to split 3 dip-buyers into non-overlapping segments of top-40 volume pairs.

| Bot | Offset | Pairs | Segment |
|-----|--------|-------|---------|
| ClucHAnix | 0 | 14 | Top volume (BTC, ETH, SOL...) |
| NASOSv5 | 14 | 13 | Mid volume (PEPE, LINK, FIL...) |
| ElliotV5 | 27 | 13 | Lower volume (WLD, FET, ENA...) |
| SupertrendStrategy | — | 40 (full) | 1h timeframe, different logic |
| MasterTraderV1 | — | 40 (full) | 1h timeframe, different logic |
| MasterTraderAI | — | 10 static | Already isolated |
| NFI X6 | — | 60 (own list) | Already separate |

Result: 100% → 3% overlap between dip-buyers. Minor residual overlap from independent exchange queries.

### Phase 5: Portfolio Circuit Breaker -- DONE 2026-03-11
**Goal: Emergency stop if portfolio drawdown exceeds threshold**

Added to `metrics_exporter.py` (already runs 24/7, scrapes every 60s):
- Tracks portfolio high-water mark across scrapes
- Calculates drawdown from peak: `(peak - current) / peak × 100`
- **Threshold: 10% portfolio drawdown ($700 loss)**
- On trigger: stops ALL bots via `/api/v1/stop`, sends Telegram alert
- Cooldown: 1h between re-alerts
- Auto-resets when drawdown recovers below 5%
- New Prometheus metrics: `freqtrade_portfolio_drawdown_pct`, `freqtrade_portfolio_value_total`
- Manual restart required after trigger (safety: no auto-resume)

---

## Restart Sequence After Changes
```bash
cd ~/ft_userdata
docker compose down
docker compose up -d
# Verify all bots healthy:
for port in 8080 8082 8083 8084 8086 8087 8089; do
  echo -n "Port $port: "
  curl -s -u freqtrader:mastertrader http://localhost:$port/api/v1/ping
  echo
done
```

---

## Principles (agreed with Palmer)
1. Be OBSESSIVE about not losing money
2. Prefer missing a trade over taking a bad one
3. No arbitrary numbers — evidence-based settings only
4. Portfolio-level protection, not just per-bot
5. Correlated exposure is the #1 risk to eliminate
6. Time kills bad trades — force-close stale losers
