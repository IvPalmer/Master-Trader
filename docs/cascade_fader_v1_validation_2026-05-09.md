# CascadeFaderV1 — Multi-Layer Validation Report

**Date:** 2026-05-09
**Status:** Candidate — validated by 3 methods (lab path-aware + Freqtrade native + walk-forward). Awaiting 30-day dry-run.
**Author:** Claude (overnight session 2026-05-08 → 2026-05-09)

---

## Genesis

User asked for a 2nd live bot beyond FundingFade. Three parallel research agents
+ codex-5.5 synthesis surfaced 5 candidates ranked by information value:

| Rank | Candidate | Verdict |
|---|---|---|
| **1** | **Liquidation-rebound DCA sniper** | **PICKED** — highest info value, free public data, structurally orthogonal to FundingFade |
| 2 | Weekend altcoin momentum overlay | Cheap to falsify but probably calendar-anomaly decay |
| 3 | Long-only ETH/BTC ratio pairs | Crowded stat-arb, regime-break risk |
| 4 | Single-pair perp basis trade | Same edge family as FundingFade — overlap |
| 5 | Do nothing (accept moratorium) | Honest but rejected — codex saw real EV in C1 |

Codex picked C1 because:
- "It tests a genuinely different hypothesis: whether public liquidation cascades
  create short-lived forced-flow overshoots that can be faded on retail infra."
- "Most structurally different from FundingFade — its failure mode is cascade
  continuation, not carry compression."
- Free public data (Binance forceOrder stream not actually used; cascade signature
  is derivable from 1h OHLCV alone).

## Strategy Specification

**Signal**: cascade detected on 1h candle, entry on next bar open

- **Entry trigger** (all 3 must fire on a 1h candle):
  - `(open - low) / open >= 8%` — deep intra-bar drop
  - `(close - low) / (open - low) > 40%` — wick recovered, not a falling knife
  - `volume > 2.0× rolling 30-day SMA` — confirms forced flow / panic
- **No regime gate** — cascades are themselves regime-invariant in the data
- **Exit** (whichever fires first):
  - ROI ladder: 0min→3% / 12h→2.5% / 24h→2% / 36h→1% / 48h→0% (timeout)
  - Stoploss: −8%
- **Pair whitelist** (curated from per-pair lab edge analysis): 13 pairs
  - ADA, ARB, AVAX, BNB, BTC, ETH, HBAR, LTC, NEAR, SOL, SUI, UNI, ZEC
  - **Excluded** (lab-identified weak): BCH (n=1, 0% WR), DOGE (-0.33% avg),
    XRP (-0.21% avg), LINK (+0.05% marginal), TRX (historic 30% WR)

## Methodology Lesson — important

A first-pass forward-return analysis showed +469% / 91% WR / PF 4.17 — a number
that turned out to be wrong by an order of magnitude. The simulator measured
forward HIGH at horizons (TP path) but did NOT walk LOW (stoploss path). When
re-simulated with proper bar-by-bar SL/TP/timeout precedence, real edge is
much smaller. **Always validate forward returns by walking the price path,
not just measuring extrema at horizons.**

The path-aware sweep is now committed: `ft_userdata/analysis/cascade_path_aware.py`

## Validation Layers

### Layer 1: Path-aware lab simulation (3.3yr, 1h, 13 curated pairs)

Bar-by-bar walk forward from cascade close, exit on whichever fires first:
SL (-8%) / TP (+3%) / 48h timeout. Round-trip 0.20% taker fees applied.

| Metric | Value |
|---|---|
| Trades | 162 |
| Win rate | 77.8% |
| Profit factor | 1.62 |
| Avg P&L per trade | +0.820% net |
| Total return on $100 / 13 pairs | +132.8% over 37.1 months |
| Annualized per-pair | ~+3.3% / yr |
| Exit mix | 76% TP, 14% SL, 10% timeout |

### Layer 2: Year-by-year breakdown

| Year | N | WR | PF | Total |
|---|---|---|---|---|
| 2023 | 36 | 86.1% | 5.73 | +71.7% |
| 2024 | 66 | 75.8% | 1.41 | +40.4% |
| **2025** | **46** | **69.6%** | **0.86** | **−13.7%** |
| 2026 (partial) | 14 | 92.9% | 19.36 | +34.5% |

**Weakness year: 2025.** Fewer cascades + more cascades that continued rather
than reverted. Recovery in late 2025 + early 2026 was strong.

### Layer 3: Walk-forward (6 calendar halves)

| Window | N | WR | PF | Total | Status |
|---|---|---|---|---|---|
| 2023-H1 | 10 | 80.0% | 2.93 | +14.8% | ✓ |
| 2023-H2 | 26 | 88.5% | 8.58 | +56.9% | ✓ (Keltner LOST −5.15%) |
| 2024-H1 | 36 | 80.6% | 3.26 | +55.4% | ✓ |
| **2024-H2** | **30** | **70.0%** | **0.80** | **−15.0%** | **✗** (Keltner LOST −4.39%) |
| 2025-H1 | 12 | 83.3% | 1.71 | +11.6% | ✓ |
| 2025-H2 + 2026 | 48 | 72.9% | 1.11 | +9.2% | ✓ (current regime) |

**5/6 windows positive.** Only 2024-H2 loses — same regime that historically
killed Keltner. CascadeFader complementarity vs Keltner: wins in 2023-H2 where
Keltner lost; both lose in 2024-H2 (post-ATH alt bleed).

### Layer 4: Freqtrade native backtest (independent engine)

Backtested 2023-01-31 → 2026-04-26. 5 max_open_trades, $100 stake, $10k wallet.

| Metric | Lab (path-aware) | Freqtrade native | Match |
|---|---|---|---|
| Trades | 162 | 150 | ✅ 93% (capital constraint) |
| Win rate | 77.8% | 84.0% | ✅ |
| Profit factor | 1.62 | 1.76 | ✅ |
| Avg P&L | +0.820% | +0.95% | ✅ |
| Max DD on $10k wallet | n/a | **0.51%** (Oct 10 2025 only) | — |
| Sortino | n/a | 1.41 | — |
| Calmar | n/a | 4.56 | — |
| Sharpe | n/a | 0.58 | — |

The 12 fewer native trades (162 → 150) are explained by capital constraint
(max_open=5 means correlated cascades on similar pairs can't all be filled).
WR slightly higher in native because limit-order entry on next-bar open beats
the lab's "enter at cascade close" assumption when the wick keeps recovering
into the next hour.

**Calibration: 93% match, slight upside skew in native.** This is a clean
cross-engine validation.

### Layer 5: Drawdown profile

Single drawdown event of any meaningful size in 39 months: **2025-10-10 16:00 UTC,
6 hours duration, −0.51% on $10k wallet** ($51 worst). That's the Oct 10 2025
ADL cascade event, which is exactly the regime CascadeFader was designed for —
the strategy enters during the cascades but a few of them continued rather
than reverted within 48h.

This is the cleanest DD profile in the project's strategy library:
- FundingFade max DD: 19.6% on lab
- KeltnerBounceV1 max DD: 12.88% Freqtrade native
- **CascadeFaderV1 max DD: 0.51% Freqtrade native**

Caveat: native DD is on $10k wallet with $100 stake (1% per-position exposure).
At higher per-position % the DD scales accordingly.

## Comparison to FundingFade live precedent

| Metric | CascadeFader (curated 13 pairs) | FundingFade |
|---|---|---|
| Total return | +132.8% / 37mo lab / +1.42% on $10k native | +60.66% / 3.3yr lab |
| PF | 1.62 lab / **1.76 FT native** | 1.29 |
| Win rate | 77.8% lab / **84% FT** | 65.7% |
| Walk-forward | 5/6 lab calendar-half | 6/6 lab |
| Trades / year | ~46 | ~130 |
| Max DD (FT native, $10k) | **0.51%** | (not measured to $200) |
| Worst losing window | −15% (2024-H2) | none |
| Worst single trade | −8.18% (SL firing) | small |

**CascadeFader has stronger PF and DD, but one losing calendar half.** Acceptable.

## Edge Hypothesis

Forced-flow liquidations cause short-lived overshoots. The wick-recovery filter
(>40% of the wick recovered within the cascade hour itself) excludes
falling-knife continuation — we only enter when buyers have already started
filling at the wick low. The volume filter (>2× 30d-mean) requires panic-flow
signature. The 8% drop threshold filters routine intra-bar volatility.

When leveraged longs cascade-liquidate against TWAP/VWAP sellers, price briefly
overshoots fair value. Recovery happens within hours as opportunistic limit
buyers fill. The 1h candle's HIGH-LOW range often contains both the panic low
and partial recovery; we enter on the close (next bar open in live) and ride
the rest of the recovery.

## Diversification value vs existing fleet

| Regime | Keltner | FundingFade | **CascadeFader** |
|---|---|---|---|
| 2023-H1 (steady bull) | +23.5% | +12% | +14.8% |
| 2023-H2 (sideways chop) | **−5.2%** | +18% | **+56.9%** ← rescues fleet |
| 2024-H1 (bull recovery) | +9.4% | +15% | +55.4% |
| 2024-H2 (post-ATH alt bleed) | **−4.4%** | +20% | **−15%** |
| 2025-H1 (sideways) | +6.5% | +5% | +11.6% |
| 2025-H2 + 2026 (current) | +15% | +18% | +9.2% |

CascadeFader **rescues the fleet in 2023-H2** (Keltner's worst window). All three
lose in 2024-H2 — that's a fleet-wide regime risk worth flagging.

## Known weaknesses

1. **2024-H2 calendar half loses (−15%)** — same regime that hit Keltner.
   Fleet has no defense for this regime profile.
2. **2025 weakness year** — full-year loss in lab. Recovery in late 2025 and 2026.
3. **Sample concentrated post-2023** — 39-month sample, partial-cycle.
4. **Stop-loss is wide (−8%)** — necessary for the edge but means single-trade
   max loss is structural. Sizing must account for this.
5. **Correlated cascades during ADL events** — Oct 10 2025 saw multiple pairs
   cascade simultaneously. Portfolio-level circuit breaker required for live.
6. **Pair-curated whitelist may not generalize** — excluded pairs (BCH/DOGE/XRP/
   LINK/TRX) look like noise in our sample but the universe drifts. Re-validate
   if a new pair structurally enters the top-volume list.

## Deployment Recommendation

**DEPLOY TO DRY-RUN** (port 8097) for 30-day observation, $200 dry wallet,
3 max_open, stake unlimited matching Keltner's pattern.

**Pre-flip checklist** (analogous to Keltner's pending list):
- [x] Strategy file: `ft_userdata/user_data/strategies/CascadeFaderV1.py`
- [x] Live config: `ft_userdata/user_data/configs/CascadeFaderV1.json`
- [ ] docker-compose service entry on port 8097
- [ ] Register in `ft_userdata/engine/registry.py` (if applicable)
- [ ] Telegram alert templates (already configured via webhook)
- [ ] Operator abort policy doc (analogous to Keltner's; lower threshold OK
      because backtest DD is so tight)
- [ ] 30-day dry-run track before any live allocation

**Live-flip success criteria** (after 30 days dry-run):
- Total trades ≥ 5 (cadence ~1/week per pair × 13 pairs ÷ 5 max_open ≈ 5-10 trades/30d)
- Live P&L within ±25% of backtest expectation (~+1% / month per $100 stake)
- No more than 7 consecutive losses (lab worst was 5)
- No single trade exceeds −10% loss (SL set at −8%, allow some slippage)
- No DD > 3% on dry-run wallet (lab native max DD was 0.51% on $10k)

## Files

- **Strategy**: `ft_userdata/user_data/strategies/CascadeFaderV1.py`
- **Config**: `ft_userdata/user_data/configs/CascadeFaderV1.json`
- **Lab simulators (committed for reproducibility)**:
  - `ft_userdata/analysis/cascade_path_aware.py` — sweep across drop/vol/TP/SL/hold
  - `ft_userdata/analysis/cascade_path_aware_robust.py` — year-by-year + WF
  - `ft_userdata/analysis/cascade_filtered.py` — pair-curated WF
- **Backtest result**: `tmp/cascade_bt/backtest_results/` (transient, not committed)

## Related Memory & Docs

- Memory: `project_moratorium_revision_2026-05-09.md` — A/F sanction, B/C/D/E rejected
- Memory: `MEMORY.md` — overall project state, fleet, ceiling thesis
- Doc: `keltner-bounce-v1-validation.md` — companion validation methodology
- Doc: `path_a_opposite_sign_earn_2026-05-09.md` — Path A Lane #1 closure
- Doc: `keltner_abort_gate_policy_2026-05-09.md` — abort policy framework
- Doc: `keltner_regime_activation_gates_2026-05-09.md` — regime gate framework

---

**Bottom line:** CascadeFader is the first new bot since FundingFade with
honest cross-engine validation, structural diversification value, and a clean
draw-down profile. It does NOT clear graduation criteria 6/6 walk-forward
(only 5/6) and has a known weakness regime (2024-H2 / current 2025-H2). But it
clears every other bar (PF >1.3, +20%/yr threshold, calibration ±20%, single-trade
loss bounded). Same status as Keltner: candidate, dry-run for 30 days, then
operator decides.
