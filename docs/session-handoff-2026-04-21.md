# Session Handoff — 2026-04-21

## TL;DR
Five research lanes closed on evidence this session (short, trend-long, LLM-as-trader,
VPIN veto, Hyperliquid spread naive execution). Graduation criteria revised v1→v2
(calibration-based, progressive stake scaling). Live deployment infrastructure built
and tested: minimum-privilege Binance API key validated, read-only balance check
working, pre-flight checklist written. Fleet still 2 dry-run bots. Next session:
fund Binance USDT balance → flip FundingFade to live per Phase D of the checklist.

## What happened this session (2026-04-20 → 2026-04-21)

### Fleet hygiene + discovery
- **Broken symlink `~/ft_userdata`** was causing silent SQLite I/O errors; relinked to
  `/Users/palmer/Work/Dev/master-trader/ft_userdata` and force-recreated containers.
- **Funding data expanded** 20 → 89 pairs (Binance). New pairs: APT, AAVE, TON, WLD,
  FET, DOT, FIL, TRUMP, XLM, DYDX, TIA, PENDLE, INJ, ONDO, RENDER, VIRTUAL, PUMP, +
  the 10 original live-whitelist pairs that were silently skipped.
- **Stablecoin blacklist extended** (+RLUSD, USDE, XAUT) to avoid contamination.

### Research: lanes closed on evidence (5)
Each got a 1m-detail backtest or walk-forward. All FAILED Phase 3 validation.

| Lane | Result | Doc |
|------|--------|-----|
| Pairlist widening FundingFade 19→36 | FAIL: PF 1.29→1.11, DD 19.6%→31.15% | commit history |
| Pairlist widening Keltner 18→36 | Marginal: PF 1.58→1.47, edge/trade -11%, reverted | commit history |
| BearRegimeShortV1 (short-side) | FAIL: 2024 carried sample, 2025 -19.63%/DD 39% | `short_research_2026-04-20.md` |
| 1092-combo trend-long grid | FAIL: zero combos pass +20%/PF 1.3/6+WF | `trend_research_2026-04-20.md` |
| LLM-in-the-loop trading | FAIL: 90% hype, only feature-extraction sub-lane real, too latency-sensitive for retail | `llm_in_the_loop_research_2026-04-21.md` |
| VPIN veto on Keltner | FAIL: hypothesis inverted, 169 trades too few, WF 3/6 | `vpin_keltner_veto_2026-04-21.md` |
| Cross-venue Hyperliquid spread | AMBIGUOUS: infra built (65 pairs), spread exists (1-3bps/hr) but below fee friction (~29bps round-trip) | `hyperliquid_spread_infra_2026-04-21.md` |

### Research agents dispatched (secondary outputs)
- AI trading web-research survey → `ai_trading_research_2026-04-20.md`
- YouTube setups survey → `youtube_trading_research_2026-04-20.md`

### Graduation criteria v2
Rewrote `ft_userdata/GRADUATION_CRITERIA.md`:
- Dropped unreachable absolute thresholds (PF ≥ 2.0, WR ≥ 55%).
- Replaced with calibration-match: live within ±25% of scaled backtest, PF within
  ±20%, DD ≤ 1.5× backtest DD.
- Progressive stake scaling $50 → $100 → $250 (was flat $17).
- Tighter demotion triggers (drift >30%, any trade >8% loss, DD breach 1.5×).
- Memory pointer updated.

### Codex second opinion (2026-04-21)
Called out a contradiction in my earlier recommendation and sharpened the thesis:
- *"You may have already found the ceiling of this data."*
- Micro-live at $50 tests **plumbing, not alpha**.
- If going live, pick the **faster measurement**: FundingFade (~2.5 trades/wk) not
  Keltner (~1/wk, structurally dormant in current uptrend).
- DCA-with-regime-gate bot reintroduces model risk. Use **Binance auto-invest** instead.
- Real statistical hole after 4940+1092 combo sweeps is **multiple-testing / false
  discovery**. Stop searching this lane.
- Prop-trader frame: passive beta sleeve + ONE live measurement instrument + research
  only on new data/execution edge.

Memory updated to reflect the revised operating stance. DCA Freqtrade bot plan
(Path C) SHELVED in favor of Binance auto-invest.

### Live deployment infrastructure built
- `.env.example` — template at repo root for Binance credentials
- `.env` (gitignored, user-populated) — real credentials
- `ft_userdata/scripts/check_balance.py` — read-only sanity check. Calls:
  - `/api/v3/account` (balance + account-level flags)
  - `/sapi/v1/account/apiRestrictions` (API-key scope flags — the authoritative check)
  - `/api/v3/openOrders` (open order count)
  - Logs only last-4 chars of credentials
- `docs/live_deployment_checklist.md` — Phase A-G deployment path

### Binance API key verified
User created minimum-privilege key, IP-locked:
- Reading: ✅
- Spot & Margin Trading: ✅
- Withdrawals: ❌
- Futures / Margin / Transfer / Options: ❌
- IP restriction: ENABLED (187.89.222.43)

**Script bug fixed this session**: my first version warned on `canWithdraw:True`
which is an ACCOUNT-level flag (user can withdraw via web/app), not API-key scope.
Fixed to use `/sapi/v1/account/apiRestrictions` which returns the actual
key-scope flags. Important distinction for future runs.

### Current Binance balance
- USDT: $2.80 (insufficient)
- BTC: 0.00482 (~$366 at BTC $75,944)
- BNB: 0.00834 (~$5)
- Dust across ETHW, LUNA, LUNC, RUNE, LTC, BRL
- No open orders

## State at session end

### Fleet (dry-run, healthy)
| Bot | Port | Whitelist | Backtest baseline |
|-----|------|-----------|-------------------|
| Keltner | 8095 | 24 pairs | +51.47%, PF 1.58, DD 12.9% (3.3yr 1m-detail, 149 trades) |
| FundingFade | 8096 | 24 pairs | +60.66%, PF 1.29, DD 19.6% (3.3yr 1m-detail, 431 trades) |

### Capital
- $400 dry-run deployed (simulated)
- $200 dry-run freed from FundingShort kill — redirected away from new Freqtrade bots
- $2.80 real USDT + ~$366 real BTC on Binance

### Research lanes
- OHLCV + funding parameter sweeps: **CLOSED** (ceiling reached)
- LLM-as-trader: **CLOSED** (hype)
- New-infra lanes ranked:
  1. Hyperliquid spread — infra built, naive signal below fee friction. Opposite-sign
     pair (ICP/DASH/ZEC) follow-up is honest next step. Deferred.
  2. VPIN as meta-labeling feature (not veto) — pipeline exists, reusable. Deferred.
  3. Weekend altcoin momentum + HMM regime gate — untouched. Deferred.
- **30-day moratorium**: no new backtests/sweeps/lab runs unless a fundamentally
  new data source appears.

## Next session — starting fresh

### Session-start checklist
1. `docker ps --filter "name=ft-"` — expect Keltner + FundingFade + monitoring stack.
2. Check bot balances via API creds `freqtrader:mastertrader` (local Freqtrade UI).
3. Run `python3 ft_userdata/scripts/check_balance.py` — verify Binance key still valid.
4. Read `docs/session-handoff-2026-04-21.md` (this file) to rehydrate.

### The single next decision
**Fund the Binance USDT balance to ≥$50, then flip FundingFade to live per `live_deployment_checklist.md`.**

Two funding options:
- Sell ~0.00067 BTC → ~$50 USDT on Binance spot (instant)
- Deposit fresh USDT via PIX or transfer

After funding:
1. User tells me "funded" (next session)
2. I rerun `check_balance.py` → confirm USDT ≥$50, no changes to scope
3. I build Phase D: `FundingFadeV1.live.json` + docker-compose update
4. User approves the live config diff before I restart the bot
5. First 3 live trades watched manually

### Keltner stays dry-run
Per Codex critique: shipping two bots live at once doubles uncontrolled variables.
Keltner remains the control reference. Gets its own Phase A-G only after FundingFade
graduates.

### DCA sleeve
Use **Binance auto-invest** UI (native feature, no Freqtrade). $20-50/week into
BTC+ETH. Set up after live budget deposited. No regime gate, no model risk.

## Files in play

### Committed this session (on main)
- `docs/short_research_2026-04-20.md`
- `docs/trend_research_2026-04-20.md`
- `docs/ai_trading_research_2026-04-20.md`
- `docs/youtube_trading_research_2026-04-20.md`
- `docs/dca_accumulator_plan_2026-04-20.md` (shelved, doc kept)
- `docs/llm_in_the_loop_research_2026-04-21.md`
- `docs/vpin_keltner_veto_2026-04-21.md`
- `docs/hyperliquid_spread_infra_2026-04-21.md`
- `ft_userdata/GRADUATION_CRITERIA.md` (v2)
- Grid scan + analysis scripts (`grid_scan_trend.py`, `trend_refine.py`,
  `trend_year_split.py`, `download_hyperliquid_funding.py`, `cross_venue_funding_spread.py`,
  `vpin_pipeline.py`, `vpin_keltner_veto.py`)
- Evolution snapshots 20260421

### Staged for commit (this closing push)
- `.env.example`
- `ft_userdata/scripts/check_balance.py`
- `docs/live_deployment_checklist.md`
- `docs/session-handoff-2026-04-21.md` (this doc)

### Never committed (user holds)
- `.env` — Binance credentials, gitignored
