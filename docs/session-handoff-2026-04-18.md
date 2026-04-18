# Session Handoff — 2026-04-18

State dump after FundingShortV1 kill + parallel research synthesis.

## What happened this session

1. User watched Lewis Jackson "Claude Routines" video — judged mostly irrelevant (wrong layer for our stack).
2. Launched 3 parallel agents:
   - **Futures validation** (Phase 4 task): downloaded 20 futures pairs × 1m Jan2023-Apr2026, created `FundingShortV1Viability.py`, fixed engine futures `price_side` bug, ran full 3.3yr 1m-detail backtest.
   - **YouTube AI trading research**: curated 5 high-signal videos from noise.
   - **Web/papers research**: arxiv + quant blogs + industry reports.
3. **FundingShortV1 failed validation**: PF 1.06, DD 52.1%, 835 trades. KILLED. Fleet 3 → 2.
4. Two research agents independently converged on López de Prado toolkit (meta-labeling, DSR, CPCV) as highest-ROI next move.

## Current fleet (post-kill)

```
Port 8095  KeltnerBounceV1   SPOT      $200  ACTIVE  TA mean reversion
Port 8096  FundingFadeV1     SPOT      $200  ACTIVE  Non-TA funding-rate long
```

Total dry-run capital: **$400**. Long-only (lost short coverage).

Retired bots (7): FundingShortV1 (2026-04-18), MasterTraderV1, BearCrashShortV1, SupertrendStrategy, BollingerBounceV1, AlligatorTrendV1, GaussianChannelV1.

## Engine v2 changes

- **Futures config bug fixed** in `engine/config_builder.py`: `entry_pricing.price_side` was hardcoded `same`, now uses `other` for futures. Required for any futures strategy via engine.
- **Data downloaded**: 20 futures pairs (USDT-margined) × 1m candles Jan 2023 - Apr 2026. 755MB in `~/ft_userdata/user_data/data/binance/futures/`.
- **Known residual issues**: per-pair export zip parse fail (minor). Hyperopt WF timeout + MC NoneType bug still unpatched (weren't hit because Viability killed short-circuit).

## Live fleet risk watch

**FundingFadeV1 in worst-case regime NOW**:
- BTC in 46 consecutive days negative 30-day funding (Apr 2026)
- Longest streak since Nov 2022 / FTX
- Long-funding edge will struggle. Expect drawdown.
- Monitor live P&L deviation from backtest expectation.

## Phase 3 — REPRIORITIZED after research

### NEW priority order

1. **Deflated Sharpe Ratio on Lab shortlist** (cheap, immediate). 6864 combos = inflated Sharpes guaranteed. mlfinlab has impl.
2. **Meta-labeling PoC on MasterTraderV1** (highest ROI). Classifier on top of primary signal trained on divergence features. Textbook fit for MT's "backtest-fail live-profitable" profile.
3. **Delta-neutral FundingFade upgrade** (Hummingbot pattern: spot + perp hedge). Cuts directional exposure, preserves funding edge.
4. **VPIN / Kyle's Lambda / OFI microstructure features** (Algoindex). Orthogonal lane.
5. **CPCV replaces walk-forward** (mlfinlab). 3.3yr 1m at lower bound.
6. **Regime gate for Keltner** (SSRN 5775962 supports).

### Deferred (research-informed)

- On-chain whale tracking (start with free Glassnode SSR)
- Order book imbalance (wrong timeframe + must counter-trade if maker)
- Hyperliquid expansion (carry signal inverts vs Binance)
- Hyperopt WF timeout / MC NoneType / Grafana panel cleanup

## Decay warnings active

- Funding arb yields compressed ~4% post-2025 (BitMEX)
- Oct 10-11 2025 ADL cascade broke delta-neutral strategies
- BB mean-rev (Keltner) degrades in trending regimes (SSRN 5775962)

## Subscriptions (start)

- Kris Longmore Substack: https://krislongmore.substack.com/
- Robot Wealth: https://robotwealth.com/
- Kaiko Research: https://research.kaiko.com/insights

## Files modified this session

Uncommitted as of session end:
- MODIFIED `ft_userdata/engine/config_builder.py` (futures price_side fix)
- MODIFIED `ft_userdata/engine/registry.py` (FundingShortV1 status → retired)
- MODIFIED `ft_userdata/docker-compose.yml` (comment out fundingshortv1, update depends_on)
- MODIFIED `ft_userdata/user_data/configs/backtest-FundingShortV1.json` (pair whitelist)
- NEW `ft_userdata/user_data/strategies/FundingShortV1Viability.py`
- NEW `ft_userdata/engine_results/20260418_174345_rigorous/` (validation artifacts)
- NEW `ft_userdata/engine_results/viability-FundingShortV1.json`
- Memory: updated MEMORY.md, new `project_research_synthesis_2026-04-18.md`

## Open questions for next session

1. Commit meta-labeling track? (1-2 sessions)
2. Forensic check on FundingShort Oct 10-11 2025 ADL week in backtest — worthwhile?
3. DSR filter now or batched with meta-labeling?
4. $200 freed from FundingShort kill — deploy on meta-labeled MT resurrection, or hold?
5. Disk at 100% / 12GiB free — cleanup session warranted?

## Critical files to read first next session

1. This file (`docs/session-handoff-2026-04-18.md`)
2. `/Users/palmer/.claude/projects/-Users-palmer-Work-Dev-Master-Trader/memory/MEMORY.md`
3. `/Users/palmer/.claude/projects/-Users-palmer-Work-Dev-Master-Trader/memory/project_research_synthesis_2026-04-18.md`
4. `ft_userdata/engine/registry.py`
