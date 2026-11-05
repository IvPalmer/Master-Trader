# Cross-asset risk-off entry guard: results (#254)

Preregistration `xasset-riskoff-guard-2026-11` in `ft_userdata/preregistrations.json`. It was
frozen at ddf64ed (2026-11-05 19:45 UTC) and amended twice before any result (A1 at 0cb68ee,
A2 at f1334c7, from Codex Sol/high rounds 1–2; round 3 found nothing further). The run was
`xasset_guard.py` at f1334c7 on the VPS, 2026-11-05 20:00–20:01 UTC, with inputs sha256-verified.
This is research only. No bot, config or allocation changes.

## Verdict

**Primary (OR guard, 12 h, FF_V2_current): inconclusive.** Only 2 trades were blocked, below the
frozen floor of 10 from at least 3 months. Both were winners: HBAR +8.00% on 2024-11-16 and NEAR
+4.99% on 2026-03-02. The change is **−1.94 USDT** (95% month-block CI [−5.08, 0.00]); rotation
test p_helps 0.81 / p_hurts 0.19.

No cell anywhere has a positive point estimate. On FF the guard removes winners: blocked mean
+2.5% to +6.5% per trade, against +0.75% to +0.82% kept. FF fades negative funding, so it tends
to buy exactly when markets are washed out, and a risk-off guard switches it off at its best
entries. This is the same pattern as the CPI/FOMC blackout in `research/news_veto_2026-11`.
Cells other than the primary are descriptive only (A1).

## FF, Keltner, Killers (window 2024-06-15 → 2026-11-01; VIXD 2023-01-01 → 2026-11-01)

Net P&L is first order: a blocked trade is removed and the slot it frees is not refilled.
"p helps / p hurts" is the exact rank p over all whole-day rotations of the guard mask (868 or 1399).

| list | guard | N h | n | blocked (months) | net without → with | change (95% CI) | blocked / kept mean | p helps / p hurts |
|---|---|---:|---:|---:|---|---|---|---|
| FF_V2_current | OR | 12 | 158 | 2 (2) | +19.45 → +17.51 USDT | −1.94 [−5.08, 0.00] | +6.49% / +0.75% | 0.81 / 0.19 |
| FF_V2_current | OR | 24 | 158 | 6 (4) | +19.45 → +17.11 | −2.34 [−5.03, −0.30] | +2.61% / +0.75% | 0.77 / 0.23 |
| FF_V2_current | VIX20 | 12 | 158 | 2 (2) | +19.45 → +17.51 | −1.94 [−5.08, 0.00] | +6.49% / +0.75% | 0.91 / 0.09 |
| FF_V2_current | ES60 | 24 | 158 | 2 (2) | +19.45 → +18.70 | −0.75 [−1.95, 0.00] | +2.51% / +0.80% | 0.60 / 0.40 |
| FF_V2_current | VIXD | 24 | 226 | 0 | +23.02 → +23.02 | 0.00 | – | – |
| FF_PreV2_sens | OR | 12 | 210 | 4 (3) | +24.39 → +20.81 | −3.59 [−9.11, 0.00] | +6.00% / +0.68% | 0.91 / 0.09 |
| FF_PreV2_sens | OR | 24 | 210 | 14 (4) | +24.39 → +20.74 | −3.65 [−8.76, −0.08] | +1.75% / +0.71% | 0.86 / 0.14 |
| Killers_channel¹ | OR | 12 | 568 | 10 (7) | +413.67 → +411.35 mu | −2.32 [−4.84, −0.37] | +23% / +74% | 0.17 / 0.83 |
| Killers_channel¹ | OR | 24 | 568 | 29 (15) | +413.67 → +390.28 mu | −23.39 [−36.60, −12.26] | +81% / +72% | 0.59 / 0.41 |
| Keltner R4 / R5 | all | – | 14 / 29 | 0 | −1.22 / −27.68 USDT | 0.00 | – | – |
| Killers_dry | all | – | 16 | 0 | −53.58 USDT | 0.00 | – | – |
| FF_live² | OR (also ES60) | 24 | 35 | 1 (1) | −5.81 → −6.11 USDT | −0.30 | – | 0.79 / 0.23 |
| Keltner_live², Killers_live² | all | – | 3 / 20 | 0 | −0.00 / −46.85 | 0.00 | – | – |

¹ Channel-reported outcomes (no costs; unreported losers count 0 or their best partial), in
margin units. Timing check only: the 2026-05-28 real-price replay found these signals lose money.
² Closed trades from the 2026-11-05 nightly live-DB backup. Aggregates only; the per-trade rows
stay on the VPS.

Every cell, including the longs-only Killers sensitivity and the ±30-day local placebo, is in
`results/tables.md`. Machine-readable results are in `results/guard_results.json`, every
trigger in the fetched data, including those outside the windows, in `results/triggers.csv`, and the blocked backtest trades in
`results/blocked_backtest_trades.json`.

Guarded time is small: OR/12 h covers 2.9% of the window and OR/24 h 5.6%. Inside the window there are 33 ES60
and 30 VIX20 triggers. They cluster in the August 2024 unwind, around FOMC on 2024-12-18 and in
the April 2025 tariff crash (16 of the 33 ES60 triggers).

## Do prices lead headlines? 2026-11-05 (descriptive, outside every trade list)

All times UTC, from 1m bars.

| signal | time |
|---|---|
| BTCUSDT 1% below its 12:00 level | **14:15** |
| CNBC "Democratic sweep" headline (per #254) | 14:24 |
| NQ=F 1% below 12:00 | 14:31 |
| ES=F 30-min drop ≥ 1% (the exact 30-min rule) | 14:41 |
| ^VIX 1m close ≥ 1.20 × prior close (16.61) | 14:49 |
| BTCUSDT 30-min drop ≥ 1% | 14:53 |
| FT headline (per #254) | 15:02 |
| ES60 and VIX20 hourly rules take effect | 15:05 |

On this day prices did lead the FT headline, but BTC itself moved first. A guard keyed to ES or
VIX would have fired 26–50 min after BTC was already 1% down, and the hourly version not until
15:05. The 2026-11-05 move is one event and counts for nothing; it shows that cross-asset prices
give little lead over crypto's own price.

## Limitations

- Hourly stand-in. ES60 is a one-bar hourly drop, not the task's 30-min rule, because no free
  keyless sub-hour ES history covers the trade windows. The archive's new 1m snapshots
  (`px_es`, `px_vix`) make the exact rule testable forward.
- Small samples. The FF primary has 2 blocked trades. Keltner, Killers dry and the live lists
  have none or one in the window. No conclusion about Keltner is possible.
- First-order P&L only: freed slots (FF max_open 2) are not refilled.
- The thresholds were chosen after watching 2026-11-05 (hindsight), and that day is outside
  every list.
- The FF list starts in 2023, but intraday guard data start 2024-06-14, so 68 FF trades fall
  outside the intraday window. The daily VIXD guard covers 2023-01 onward and blocks no FF trade.
