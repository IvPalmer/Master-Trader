# Stable Checkpoint — 2026-04-18

Project transitioned from **build / experiment** mode into **watch** mode. No more
backtest-engine features, no more strategy-lab sweeps, no more bot deployments
unless a hard Phase 3 validation pass is achieved. The only active job is
monitoring the 2 live-validated bots.

## Fleet (authoritative)

```
Port 8095  KeltnerBounceV1   SPOT  $200  TA mean reversion     PF 1.79 / +51.47% / 3.3yr
Port 8096  FundingFadeV1     SPOT  $200  Non-TA funding long   PF 1.29 / +60.66% / 3.3yr
```

API creds: `freqtrader:mastertrader`. Dry-run wallet $400 total. Long-only.
$200 freed from FundingShort kill — HOLD, do not redeploy.

All other strategies retired (see MEMORY.md).

## Why this is the checkpoint

Tonight's three parallel PoCs — the top 3 Phase 3 research priorities —
all produced negative results:

1. **DSR on Lab shortlist** — 0 / 31 combos pass Bailey-Lopez de Prado DSR
   at N=6900 trials. `E[SR_max]=3.77 vs best obs SR=2.09`. The lab ranking
   cannot distinguish skill from luck. The live bots also fail DSR but
   retain independent validation (calibration + Freqtrade WF).
2. **Meta-labeling MT resurrection** — best test-set PF=0.57 across LGBM
   threshold/feature sweeps. Cannot flip MT's -17.36% baseline.
3. **Delta-neutral FundingFade** (Hummingbot pattern) — Sharpe -8.86 vs
   directional +1.10. Hedge destroys edge across every regime sampled.

Combined with earlier kills (MT, BearCrash, Supertrend, Bollinger,
Alligator, Gaussian, FundingShort), every research path tried in 2026 Q1
has converged to the same verdict: **the two bots we have are the two we
keep**. Additional engine work is negative expected value at this point.

## Freeze rules

1. **No new backtest-engine features** unless a bot live-fails and the
   engine is confirmed root cause.
2. **No new strategy-lab runs** unless a fundamentally new signal idea
   arrives (not another TA tweak of the same 4 families).
3. **No new bots** unless a candidate passes full Phase 3:
   Viability +20% / PF >1.3 / 6+/6 WF / calibration within ±20% of live.
4. **No redeploys of killed strategies** without fresh validation cycle.

## Watch-mode weekly checklist

- `docker ps --filter "name=ft-"` — expect 6 containers (2 bots + grafana
  bridge + metrics exporter + grafana + prometheus). If FundingShort or
  any retired strategy restarted, it's an auto-restart bug, not an intent.
- Pull `/api/v1/profit` from 8095 + 8096.
- **FundingFade DD vs backtest**: currently in worst-case regime
  (46 consecutive days negative 30-day BTC funding, Apr 2026 — longest
  streak since Nov 2022 / FTX). Backtest expects PF 1.29 long-horizon;
  short-horizon DD may exceed historical average during this streak.
- **Keltner DD vs backtest**: 2023-H2 and 2024-H2 were the historical DD
  windows (163-day streak) in choppy/euphoric regimes. Compare live DD to
  backtest 9.0% / 12.9% (lab / Freqtrade native).
- Skim Kris Longmore Substack, Robot Wealth, Kaiko Research (listed in
  MEMORY.md) for ideas worth breaking the freeze.

## Phase 5 graduation criteria (unchanged)

After 30 days dry-run each bot moves to live at $17 min-stake if:
- Live P&L within ±20% of backtest expectation
- Max consecutive losses ≤ 5
- Portfolio DD < 15%

## Recent commits (reference)

```
58aa768 infra: meta-labeling pipeline, keltner WF script, calibration configs
b003039 chore: evolution snapshots + engine rigorous-run artifacts
57fab75 research: phase 3 negative-result trilogy (DSR, meta-labeling, delta-neutral)
904fa52 chore: kill FundingShortV1 (failed full 3.3yr validation) + engine futures fix
29de19a docs: session handoff — current state + future ideas
fbb9d63 feat: deploy FundingFadeV1 + boost all wallets to $200
```

## Conditions that would re-open this checkpoint

Break the freeze only if ALL of these happen:

1. One of the 2 live bots fails graduation gates (live P&L outside ±20%
   of backtest, or DD exceeds 15%).
2. OR: a fundamentally new signal class arrives (on-chain, microstructure,
   cross-exchange) with third-party validation from a trusted source
   (not another TA indicator).
3. OR: 60+ days of stable watch passes and the infrastructure allows
   expanding to real live trading at scale.

Otherwise: watch.
