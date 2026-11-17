# News veto on the existing bots (exploratory, 2026-11-05)

**Status: exploratory. Not preregistered.** No parameter was tuned; the windows below are the
ones given in the task. Nothing here changes a bot, a config or an allocation. Separate
preregistered event studies (#229 Part C) cover a standalone news bot; their results were not
opened for this work.

**Question.** Would blocking *new entries* around bad news have improved the existing bots, on
trade lists that already exist?

## Vetoes

- **V1_24h**: block entries in token X during [t0, t0+24 h) after every Binance delisting or
  monitoring-tag notice naming X. All 267 events of
  `news_event_studies/data/manifests/delisting-manifest.json` (126 `full_delist`, 141
  `monitoring_add`, 2023-01..2026-10), candidates or not.
- **V1_7d**: the same, [t0, t0+7 d).
- **V2_macro**: block all entries during [T-2 h, T+2 h) around 45 US CPI releases (08:30 ET) and
  31 FOMC statements (14:00 ET), 2023-01..2026-10, converted to UTC with `zoneinfo`
  America/New_York (DST handled). The calendar is listed at the end and in
  `results/macro_calendar.csv`.

## Trade lists used (no new backtests)

| label | file (under `research/`) | strategy key | period (entries) | n | notes |
|---|---|---|---|---:|---|
| FF_V2_current | `ff_roi_2026-09-30/user_data/backtest_results/backtest-result-2026-09-30_23-45-13.zip` | `FFX_V0_current` | 2023-01-31..2026-09-30 | 226 | Live config (gate v2, live ROI/SL), 19-pair static whitelist identical to the live one, spot, stake 15, max_open 2, 1m detail. Identical to `FFA_V2` in the 2026-10-01 ablation (226 trades, same net). |
| FF_PreV2_sens | `ff_entry_ablation_2026-10-01/.../backtest-result-2026-10-01_03-28-54.zip` | `FFA_PreV2` | same | 311 | Sensitivity only: the pre-gate-v2 entry rule, same pairs. |
| Keltner_R4_live18 | `oos_retest_2026-07/results/R4.zip` | `KeltnerBounceV1` | 2026-04-16..2026-07-13 | 14 | Whitelist identical to the current live `KeltnerBounceV1.json` (18 pairs); backtest used max_open 3 and unlimited stake (live: 2 and 10 USDT). |
| Keltner_R5_wl60 | `oos_retest_2026-07/results/R5.zip` | `KeltnerBounceV1` | 2026-05-25..2026-07-13 | 29 | The older 60-pair deployed whitelist. |
| OITrend_CausalOI | `oi_trend_causal_2026-10-02/.../backtest-result-2026-10-03_00-25-01.zip` | `OITrendPullbackV1CausalOI` | 2026-09-04..2026-09-30 | 13 | Closest to live semantics (the deployed class makes 0 trades in a backtest by design). |
| OITrend_PriceOnly | same zip | `OITrendPullbackV1PriceOnly` | same | 18 | OI term always passes. |
| Killers_channel | `copier-validation/killers/killers_signals.json` | - | 2024-04-15..2026-05-24 | 661 | 172 symbols, including later-delisted coins. **Outcome is channel-reported** (`channel_final_pct` on a logged close, else the largest reported partial `max_pct`, else 0; the rule of `killers_bot/simulator.py`), in margin units (1.0 = 100% of one position's margin), no costs. Entry = signal post time. |
| Killers_dry | `tg_bots_audit_2026-07/killers_trades_full.json` | - | 2026-05-25..2026-06-27 | 16 | Real dry-run fills, Binance futures. |

No long Keltner trade list exists any more: `docs/vpin_keltner_veto_2026-04-21.md` used
`backtest-result-2026-04-20_22-46-25.zip` (169 trades, 2023-01..2026-04), which is on neither the VPS
nor the Mac. The live DB backups in `state/backups/` hold only 3 to 22 trades per bot and were not used.

Pair to token: strip `/USDT` and `:USDT`, strip a Hyperliquid `k` prefix and a `1000`/`1000000`/`1M`
prefix, on both the trades and the manifest.

## Method

- A trade is vetoed if its entry time lies in a window of that veto (V1: only windows of the
  trade's own token).
- P&L change = -(sum of vetoed P&L), USDT (`profit_abs`, after the backtest fees) or margin units.
  **First-order only: it ignores the slots a veto frees** (FF max_open 2, Keltner 3, OITrend 1),
  so trades that would have replaced the vetoed ones are not simulated.
- Means and win rates use per-trade `profit_ratio`.
- 95% CI for the vetoed mean: calendar-month block bootstrap (resample the months that contain
  vetoed trades, 5,000 draws) when n_vetoed >= 5. A second CI resamples all months for the
  difference vetoed minus kept mean.
- Placebo: every window of the veto shifted by one common random offset of ±1..30 whole days
  (hour of day kept), 500 draws, seed 20261105. The reported percentile is the share of placebo
  P&L changes below the real one (ties count half). Above 95: the real veto beats date-shifted
  vetoes. Below 5: it does worse. With 0 vetoed trades the number only says how often shifted
  windows hit trades.
- Yearly split by entry year where anything was vetoed.

Script: `scripts/news_veto.py` (stdlib only). Outputs: `results/veto_results.json`,
`results/vetoed_trades.json`, `results/tables.md`, `results/macro_calendar.csv`.

Reproduce:

```bash
cd ~/master-trader/research/news_veto_2026-11
systemd-run --user --collect --wait -p MemoryMax=1G -p CPUQuota=50% -p Nice=10 \
  --working-directory=$PWD/scripts -p StandardOutput=file:$PWD/results/run.log \
  /usr/bin/python3 -I $PWD/scripts/news_veto.py
```

## Results

| strategy | veto | n | n vetoed | vetoed mean (95% month-block CI) | kept mean | vetoed win / kept win | P&L change | placebo pct |
|---|---|---:|---:|---|---:|---|---:|---:|
| FF_V2_current | V1_24h | 226 | 0 | - | +0.68% | - / 62% | +0.00 USDT | 49 |
| FF_V2_current | V1_7d | 226 | 3 | -1.42% | +0.71% | 33% / 63% | +0.64 USDT | 91 |
| FF_V2_current | V2_macro | 226 | 4 | +4.42% | +0.61% | 100% / 62% | -2.64 USDT | 2 |
| FF_PreV2_sens | V1_24h | 311 | 0 | - | +0.86% | - / 69% | +0.00 USDT | 48 |
| FF_PreV2_sens | V1_7d | 311 | 5 | -1.44% [-1.44%, -1.44%] | +0.89% | 40% / 69% | +1.08 USDT | 94 |
| FF_PreV2_sens | V2_macro | 311 | 5 | +1.78% [-1.07%, +4.52%] | +0.84% | 80% / 69% | -1.34 USDT | 24 |
| Keltner_R4_live18 | V1_24h | 14 | 0 | - | -0.11% | - / 71% | +0.00 USDT | 50 |
| Keltner_R4_live18 | V1_7d | 14 | 0 | - | -0.11% | - / 71% | +0.00 USDT | 50 |
| Keltner_R4_live18 | V2_macro | 14 | 0 | - | -0.11% | - / 71% | +0.00 USDT | 53 |
| Keltner_R5_wl60 | V1_24h | 29 | 0 | - | -1.48% | - / 52% | +0.00 USDT | 50 |
| Keltner_R5_wl60 | V1_7d | 29 | 0 | - | -1.48% | - / 52% | +0.00 USDT | 50 |
| Keltner_R5_wl60 | V2_macro | 29 | 0 | - | -1.48% | - / 52% | +0.00 USDT | 51 |
| OITrend_CausalOI | V1_24h | 13 | 0 | - | +0.21% | - / 38% | +0.00 USDT | 50 |
| OITrend_CausalOI | V1_7d | 13 | 0 | - | +0.21% | - / 38% | +0.00 USDT | 50 |
| OITrend_CausalOI | V2_macro | 13 | 0 | - | +0.21% | - / 38% | +0.00 USDT | 46 |
| OITrend_PriceOnly | V1_24h | 18 | 0 | - | +0.53% | - / 50% | +0.00 USDT | 50 |
| OITrend_PriceOnly | V1_7d | 18 | 0 | - | +0.53% | - / 50% | +0.00 USDT | 50 |
| OITrend_PriceOnly | V2_macro | 18 | 0 | - | +0.53% | - / 50% | +0.00 USDT | 48 |
| Killers_channel | V1_24h | 661 | 0 | - | +70.09% | - / 64% | +0.00 margin units | 50 |
| Killers_channel | V1_7d | 661 | 0 | - | +70.09% | - / 64% | +0.00 margin units | 56 |
| Killers_channel | V2_macro | 661 | 6 | +79.29% [+16.59%, +151.56%] | +70.00% | 67% / 64% | -4.76 margin units | 39 |
| Killers_dry | V1_24h | 16 | 0 | - | -16.91% | - / 12% | +0.00 USDT | 50 |
| Killers_dry | V1_7d | 16 | 0 | - | -16.91% | - / 12% | +0.00 USDT | 50 |
| Killers_dry | V2_macro | 16 | 0 | - | -16.91% | - / 12% | +0.00 USDT | 45 |

| strategy | veto | diff vetoed-kept mean CI | placebo mean change | placebo 5-95% | placebo draws vetoing anything |
|---|---|---|---:|---|---:|
| FF_V2_current | V1_24h | - | +0.01 | +0.00 .. +0.00 | 4% |
| FF_V2_current | V1_7d | - | +0.08 | -0.06 .. +0.73 | 17% |
| FF_V2_current | V2_macro | - | -0.36 | -2.24 .. +1.02 | 90% |
| FF_PreV2_sens | V1_24h | - | +0.02 | +0.00 .. +0.00 | 6% |
| FF_PreV2_sens | V1_7d | [-2.71%, -1.88%] | +0.13 | +0.00 .. +1.10 | 17% |
| FF_PreV2_sens | V2_macro | [-1.97%, +3.78%] | -0.58 | -2.55 .. +1.25 | 94% |
| Keltner_R4_live18 | V1_24h | - | +0.00 | +0.00 .. +0.00 | 0% |
| Keltner_R4_live18 | V1_7d | - | +0.00 | +0.00 .. +0.00 | 0% |
| Keltner_R4_live18 | V2_macro | - | +0.02 | -1.32 .. +1.37 | 18% |
| Keltner_R5_wl60 | V1_24h | - | +0.00 | +0.00 .. +0.00 | 0% |
| Keltner_R5_wl60 | V1_7d | - | +0.00 | +0.00 .. +0.00 | 0% |
| Keltner_R5_wl60 | V2_macro | - | +0.68 | -2.43 .. +8.78 | 24% |
| OITrend_CausalOI | V1_24h | - | +0.00 | +0.00 .. +0.00 | 0% |
| OITrend_CausalOI | V1_7d | - | +0.00 | +0.00 .. +0.00 | 0% |
| OITrend_CausalOI | V2_macro | - | +0.01 | -0.25 .. +0.27 | 19% |
| OITrend_PriceOnly | V1_24h | - | +0.00 | +0.00 .. +0.00 | 0% |
| OITrend_PriceOnly | V1_7d | - | +0.00 | +0.00 .. +0.00 | 0% |
| OITrend_PriceOnly | V2_macro | - | +0.00 | -0.25 .. +0.18 | 21% |
| Killers_channel | V1_24h | - | -0.01 | +0.00 .. +0.00 | 1% |
| Killers_channel | V1_7d | - | -0.10 | -0.89 .. +0.00 | 12% |
| Killers_channel | V2_macro | [-59.36%, +96.06%] | -5.35 | -12.55 .. -1.51 | 100% |
| Killers_dry | V1_24h | - | +0.00 | +0.00 .. +0.00 | 0% |
| Killers_dry | V1_7d | - | +0.00 | +0.00 .. +0.00 | 0% |
| Killers_dry | V2_macro | - | +0.38 | +0.00 .. +9.42 | 16% |

Yearly split (n / vetoed / vetoed mean / kept mean / P&L change):

- FF_V2_current V1_7d: 2023: 39/0/-/+0.92%/+0.00; 2024: 78/3/-1.42%/+0.49%/+0.64; 2025: 55/0/-/+0.80%/+0.00; 2026: 54/0/-/+0.77%/+0.00
- FF_V2_current V2_macro: 2023: 39/0/-/+0.92%/+0.00; 2024: 78/2/+4.32%/+0.31%/-1.28; 2025: 55/2/+4.52%/+0.66%/-1.36; 2026: 54/0/-/+0.77%/+0.00
- FF_PreV2_sens V1_7d: 2023: 57/0/-/+1.63%/+0.00; 2024: 107/5/-1.44%/+0.73%/+1.08; 2025: 82/0/-/+0.83%/+0.00; 2026: 65/0/-/+0.58%/+0.00
- FF_PreV2_sens V2_macro: 2023: 57/0/-/+1.63%/+0.00; 2024: 107/3/-0.04%/+0.65%/+0.02; 2025: 82/2/+4.52%/+0.74%/-1.36; 2026: 65/0/-/+0.58%/+0.00
- Killers_channel V2_macro: 2024: 302/2/+188.10%/+113.93%/-3.76; 2025: 279/3/+33.18%/+30.73%/-1.00; 2026: 80/1/+0.00%/+40.39%/-0.00

### Vetoed trades (reduced for the public repo)

The VPS copy of this file lists each vetoed trade with pair and entry hour. Those rows are
omitted here; only counts, trigger events (public dates) and aggregate outcomes remain.

| list | veto | vetoed trades | trigger events | outcome (aggregate) |
|---|---|---:|---|---|
| FF_V2_current | V1_7d | 3 | 1 Binance monitoring tag, 2024-01-04 | mean -1.42% (2 losses, 1 win) |
| FF_V2_current | V2_macro | 4 | FOMC 2024-09-18, 2024-11-07, 2025-05-07 (2 trades) | mean +4.42%, all 4 winners |
| FF_PreV2_sens | V1_7d | 5 | same monitoring tag | 3 losses, 2 wins, mean -1.44% |
| FF_PreV2_sens | V2_macro | 5 | CPI 2024-01-11 (2 trades), FOMC 2024-11-07, 2025-05-07 (2 trades) | mean +1.78% |
| Killers_channel | V2_macro | 6 | FOMC 2024-06-12, 2026-01-28; CPI 2024-10-10, 2025-03-12, 2025-04-10, 2025-05-13 | 4 winners, 2 flat (channel-reported %) |

No trade on any list was entered within 24 h after a notice in its token. Killers posted signals
in 31 tokens that later received notices, but the closest post-notice signal came 15.9 days
after the notice (BAKE, monitoring tag 2025-07-07); one WAVES signal came 2.8 days *before*
its delisting notice, which an entry veto cannot catch.

## Conclusions

- **V1_24h: no detectable effect.** It vetoes nothing on any list, so on this history it
  would neither have helped nor hurt.
- **V1_7d: no detectable effect.** One event (ZEC monitoring tag, 2024-01-04) caught 3 FF
  trades (+0.64 USDT if blocked, placebo percentile 91; +1.08 USDT and percentile 94 on the
  pre-v2 rule with 5 trades, CI degenerate because it is one month). One event and fewer than
  95 percent of placebos: not evidence.
- **V2_macro: no evidence it helps; the point estimates say it hurts.** FF's 4 vetoed trades
  were all FOMC-window winners (+4.42% mean against +0.61% kept), so the veto would have cost
  2.64 USDT, placebo percentile 2 (n = 4, no CI). The pre-v2 rule gives -1.34 USDT, percentile 24;
  Killers' channel outcomes give -4.76 margin units, percentile 39, difference CI
  [-59%, +96%]. Keltner and OITrend: nothing in their windows.

## Limitations

- **Survivorship makes V1 nearly untestable on the backtests.** FF, Keltner and OITrend use
  today's static whitelists (19, 18 or 60, and 8 pairs). A coin delisted in 2023-26 cannot be in
  them, so V1 could only ever hit surviving monitoring-tag coins (ZEC). The main use case of the
  veto, keeping the bot out of dying coins, is outside these trade lists. The engine's
  current-volume universe has the same bias and was not used.
- Killers covers the historical universe (172 symbols), but its outcomes are what the channel
  reported: unreported losers count 0 or keep their best partial, and there are no costs. The
  2026-05-28 real-price replay found the signals lose money. Treat its rows as timing checks only.
- Short lists: Keltner 14/29 trades in 2026-04..07, OITrend 13/18 trades in 2026-09, Killers dry 16.
  No long Keltner trade list survives.
- First-order P&L ignores freed slots and their replacement trades; no backtests were rerun.
- Month-block CIs with 1 to 6 blocks are unreliable. 8 lists × 3 vetoes = 24 rows, of which only 5 veto anything,
  with no multiplicity correction; one extreme placebo percentile among them is weak evidence.
- Macro dates come from the official pages (BLS CPI archive, Federal Reserve FOMC calendar),
  fetched 2026-11-05. The 08:30 ET CPI time is the BLS standard; the archive page itself does
  not print times. October 2025 CPI was never published; the 2025-08-22 FOMC notation vote
  is not a 14:00 policy statement and is excluded.

## US macro calendar used (V2)

| event | reference | date (ET) | time (ET) | UTC | UTC offset |
|---|---|---|---|---|---:|
| CPI | 2022-12 | 2023-01-12 | 08:30 | 2023-01-12 13:30 | -5 |
| FOMC | Jan/Feb 31-1 2023 | 2023-02-01 | 14:00 | 2023-02-01 19:00 | -5 |
| CPI | 2023-01 | 2023-02-14 | 08:30 | 2023-02-14 13:30 | -5 |
| CPI | 2023-02 | 2023-03-14 | 08:30 | 2023-03-14 12:30 | -4 |
| FOMC | Mar 21-22 2023 | 2023-03-22 | 14:00 | 2023-03-22 18:00 | -4 |
| CPI | 2023-03 | 2023-04-12 | 08:30 | 2023-04-12 12:30 | -4 |
| FOMC | May 2-3 2023 | 2023-05-03 | 14:00 | 2023-05-03 18:00 | -4 |
| CPI | 2023-04 | 2023-05-10 | 08:30 | 2023-05-10 12:30 | -4 |
| CPI | 2023-05 | 2023-06-13 | 08:30 | 2023-06-13 12:30 | -4 |
| FOMC | Jun 13-14 2023 | 2023-06-14 | 14:00 | 2023-06-14 18:00 | -4 |
| CPI | 2023-06 | 2023-07-12 | 08:30 | 2023-07-12 12:30 | -4 |
| FOMC | Jul 25-26 2023 | 2023-07-26 | 14:00 | 2023-07-26 18:00 | -4 |
| CPI | 2023-07 | 2023-08-10 | 08:30 | 2023-08-10 12:30 | -4 |
| CPI | 2023-08 | 2023-09-13 | 08:30 | 2023-09-13 12:30 | -4 |
| FOMC | Sep 19-20 2023 | 2023-09-20 | 14:00 | 2023-09-20 18:00 | -4 |
| CPI | 2023-09 | 2023-10-12 | 08:30 | 2023-10-12 12:30 | -4 |
| FOMC | Oct/Nov 31-1 2023 | 2023-11-01 | 14:00 | 2023-11-01 18:00 | -4 |
| CPI | 2023-10 | 2023-11-14 | 08:30 | 2023-11-14 13:30 | -5 |
| CPI | 2023-11 | 2023-12-12 | 08:30 | 2023-12-12 13:30 | -5 |
| FOMC | Dec 12-13 2023 | 2023-12-13 | 14:00 | 2023-12-13 19:00 | -5 |
| CPI | 2023-12 | 2024-01-11 | 08:30 | 2024-01-11 13:30 | -5 |
| FOMC | Jan 30-31 2024 | 2024-01-31 | 14:00 | 2024-01-31 19:00 | -5 |
| CPI | 2024-01 | 2024-02-13 | 08:30 | 2024-02-13 13:30 | -5 |
| CPI | 2024-02 | 2024-03-12 | 08:30 | 2024-03-12 12:30 | -4 |
| FOMC | Mar 19-20 2024 | 2024-03-20 | 14:00 | 2024-03-20 18:00 | -4 |
| CPI | 2024-03 | 2024-04-10 | 08:30 | 2024-04-10 12:30 | -4 |
| FOMC | Apr/May 30-1 2024 | 2024-05-01 | 14:00 | 2024-05-01 18:00 | -4 |
| CPI | 2024-04 | 2024-05-15 | 08:30 | 2024-05-15 12:30 | -4 |
| CPI | 2024-05 | 2024-06-12 | 08:30 | 2024-06-12 12:30 | -4 |
| FOMC | Jun 11-12 2024 | 2024-06-12 | 14:00 | 2024-06-12 18:00 | -4 |
| CPI | 2024-06 | 2024-07-11 | 08:30 | 2024-07-11 12:30 | -4 |
| FOMC | Jul 30-31 2024 | 2024-07-31 | 14:00 | 2024-07-31 18:00 | -4 |
| CPI | 2024-07 | 2024-08-14 | 08:30 | 2024-08-14 12:30 | -4 |
| CPI | 2024-08 | 2024-09-11 | 08:30 | 2024-09-11 12:30 | -4 |
| FOMC | Sep 17-18 2024 | 2024-09-18 | 14:00 | 2024-09-18 18:00 | -4 |
| CPI | 2024-09 | 2024-10-10 | 08:30 | 2024-10-10 12:30 | -4 |
| FOMC | Nov 6-7 2024 | 2024-11-07 | 14:00 | 2024-11-07 19:00 | -5 |
| CPI | 2024-10 | 2024-11-13 | 08:30 | 2024-11-13 13:30 | -5 |
| CPI | 2024-11 | 2024-12-11 | 08:30 | 2024-12-11 13:30 | -5 |
| FOMC | Dec 17-18 2024 | 2024-12-18 | 14:00 | 2024-12-18 19:00 | -5 |
| CPI | 2024-12 | 2025-01-15 | 08:30 | 2025-01-15 13:30 | -5 |
| FOMC | Jan 28-29 2025 | 2025-01-29 | 14:00 | 2025-01-29 19:00 | -5 |
| CPI | 2025-01 | 2025-02-12 | 08:30 | 2025-02-12 13:30 | -5 |
| CPI | 2025-02 | 2025-03-12 | 08:30 | 2025-03-12 12:30 | -4 |
| FOMC | Mar 18-19 2025 | 2025-03-19 | 14:00 | 2025-03-19 18:00 | -4 |
| CPI | 2025-03 | 2025-04-10 | 08:30 | 2025-04-10 12:30 | -4 |
| FOMC | May 6-7 2025 | 2025-05-07 | 14:00 | 2025-05-07 18:00 | -4 |
| CPI | 2025-04 | 2025-05-13 | 08:30 | 2025-05-13 12:30 | -4 |
| CPI | 2025-05 | 2025-06-11 | 08:30 | 2025-06-11 12:30 | -4 |
| FOMC | Jun 17-18 2025 | 2025-06-18 | 14:00 | 2025-06-18 18:00 | -4 |
| CPI | 2025-06 | 2025-07-15 | 08:30 | 2025-07-15 12:30 | -4 |
| FOMC | Jul 29-30 2025 | 2025-07-30 | 14:00 | 2025-07-30 18:00 | -4 |
| CPI | 2025-07 | 2025-08-12 | 08:30 | 2025-08-12 12:30 | -4 |
| CPI | 2025-08 | 2025-09-11 | 08:30 | 2025-09-11 12:30 | -4 |
| FOMC | Sep 16-17 2025 | 2025-09-17 | 14:00 | 2025-09-17 18:00 | -4 |
| CPI | 2025-09 | 2025-10-24 | 08:30 | 2025-10-24 12:30 | -4 |
| FOMC | Oct 28-29 2025 | 2025-10-29 | 14:00 | 2025-10-29 18:00 | -4 |
| FOMC | Dec 9-10 2025 | 2025-12-10 | 14:00 | 2025-12-10 19:00 | -5 |
| CPI | 2025-11 | 2025-12-18 | 08:30 | 2025-12-18 13:30 | -5 |
| CPI | 2025-12 | 2026-01-13 | 08:30 | 2026-01-13 13:30 | -5 |
| FOMC | Jan 27-28 2026 | 2026-01-28 | 14:00 | 2026-01-28 19:00 | -5 |
| CPI | 2026-01 | 2026-02-13 | 08:30 | 2026-02-13 13:30 | -5 |
| CPI | 2026-02 | 2026-03-11 | 08:30 | 2026-03-11 12:30 | -4 |
| FOMC | Mar 17-18 2026 | 2026-03-18 | 14:00 | 2026-03-18 18:00 | -4 |
| CPI | 2026-03 | 2026-04-10 | 08:30 | 2026-04-10 12:30 | -4 |
| FOMC | Apr 28-29 2026 | 2026-04-29 | 14:00 | 2026-04-29 18:00 | -4 |
| CPI | 2026-04 | 2026-05-12 | 08:30 | 2026-05-12 12:30 | -4 |
| CPI | 2026-05 | 2026-06-10 | 08:30 | 2026-06-10 12:30 | -4 |
| FOMC | Jun 16-17 2026 | 2026-06-17 | 14:00 | 2026-06-17 18:00 | -4 |
| CPI | 2026-06 | 2026-07-14 | 08:30 | 2026-07-14 12:30 | -4 |
| FOMC | Jul 28-29 2026 | 2026-07-29 | 14:00 | 2026-07-29 18:00 | -4 |
| CPI | 2026-07 | 2026-08-12 | 08:30 | 2026-08-12 12:30 | -4 |
| CPI | 2026-08 | 2026-09-11 | 08:30 | 2026-09-11 12:30 | -4 |
| FOMC | Sep 15-16 2026 | 2026-09-16 | 14:00 | 2026-09-16 18:00 | -4 |
| CPI | 2026-09 | 2026-10-14 | 08:30 | 2026-10-14 12:30 | -4 |
| FOMC | Oct 27-28 2026 | 2026-10-28 | 14:00 | 2026-10-28 18:00 | -4 |
