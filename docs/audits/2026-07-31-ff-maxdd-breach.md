# FF MaxDD breach + governance amendment — 2026-07-31

Routine fleet check that surfaced a breached pre-commitment. FundingFadeV1 (the
only real-money bot) tripped its pre-registered MaxDD trigger on **2026-07-29
04:19:17 UTC** and nothing noticed for two days. Bot is now PAUSED. Commits
`ddb1364`, `7bcd8a1`. Codex-reviewed; three defects it found in the first draft
are recorded below rather than quietly fixed.

## Measurement

Closed-equity drawdown, freqtrade `/profit` basis — the same quantity the
backtest's 2.40% figure came from.

| Reading | MaxDD | Peak | Trough |
|---|---|---|---|
| Full run (bot start 2026-04-21) | **8.60%** ($7.43) | $86.46 @ 2026-05-10 17:18 | $79.03 @ 2026-07-29 04:19 |
| Gate-v2 era only (peak re-baselined at 2026-05-19) | **4.32%** | $82.60 | same |

Account: `starting_capital` $80.65, `total_bot` $78.91. **The "$200 live" figure
in older session notes is wrong** — the API reports ~$80.

Overall: 23 closed, −$1.6227, PF 0.825, WR 47.8%, Sharpe −0.407. Gate-v2 era
(trades closing on/after 2026-05-19): 6 closed, **1W/5L, PF 0.078**, every loss
a full −5% stop with no intermediate exits.

| Close | Pair | P&L | Exit |
|---|---|---|---|
| 07-11 | HBAR | −0.7710 | stop_loss |
| 07-12 | ADA | −0.7640 | stop_loss (10h-stale funding; refresh fixed 177cdd1) |
| 07-20 | ETH | +0.2997 | roi |
| 07-24 | SUI | −0.7745 | stop_loss |
| 07-27 | ZEC | −0.7645 | stop_loss |
| 07-29 | LTC | −0.7898 | stop_loss ← trigger crossed here |

Trade IDs order by *open* date, not close — an early draft of this analysis put
the crossing at ZEC 07-27 for that reason. The `/profit` `max_drawdown_end`
field confirms 2026-07-29.

## Why it was invisible

`check_preregistrations` evaluated entries only by closed-trade count and review
date. The daily report printed "rules not yet evaluable" — true of the
trade-count-gated PF rule, and silent about the standing drawdown trigger
directly above it. A trigger only a human re-reading the registry can notice is
the exact failure mode `preregistrations.json` exists to prevent.

## The governance conflict

Two texts disagree on **both threshold and action**:

- **Commit `34ec07b`** (2026-05-19, the actual pre-declaration): "Demote to
  regime-halt-only if live MaxDD > 3.84% (1.5× backtest). Kill if DD > 8% or 5+
  consecutive losses or PF < 0.7 over 30+ trades."
- **`preregistrations.json`** entry added 2026-06-09: "Rollback gate v2 if
  account MaxDD > 3.60%."

These point opposite ways. *Demote to regime-halt-only* keeps the restrictive
filter (bot trades less); *rollback gate v2* removes it (bot trades more). The
June 9 registry changed number and action with no amendment recorded. 3.84% is
also arithmetically odd — the commit says "1.5× backtest" but 1.5 × 2.40 = 3.60,
so 3.84 (= 1.6×) looks like the original slip and 3.60 like a correction that
overreached into the action clause.

Resolution: **both texts kept as separate triggers; neither discarded.** All
three thresholds are breached on at least one reading.

## Why neither gate action was executed

Both gate actions loosen the gate. That made sense when written — the rule is a
*falsification* clause: gate v2 promised MaxDD 2.40%, so exceeding 1.5× means
the filter did not deliver and you stop paying its cost in trade scarcity.

But it was written **before** the 2026-07-13 OOS retest, which established that
the problem is not gate tightness:

> gate open 23.4% of the OOS window (backtest era 33.3%), yet 310 gate-open
> hours produced ONE funding signal — against a claimed 1.67 trades/wk.

The signal decayed, not the gate. Executing either action today would put real
money on a *looser* version of a strategy with live gate-v2-era PF 0.078 and no
demonstrated OOS edge.

**Independent corroboration this is structural, not small-N noise:**
`hl-carry-shadow-2026-07` has recorded zero episodes in 18 days because max
trailing-24h funding across 40 coins is 10.95%/yr against a 40%/yr entry
threshold. Same funding-yield compression, different venue, different
instrument.

**Statistical honesty:** N=6 cannot establish the edge is dead. The confidence
interval is very wide and the ADA loss was a since-fixed data fault. The honest
characterization is *severe adverse live evidence and payoff realization
inconsistent with the backtest, too few independent trades for a reliable edge
estimate*. The pause rests on the drawdown trigger and the OOS signal-scarcity
finding, **not** on a claim that N=6 proves anything.

## The kill arm — OPEN override, not resolved

Stated plainly because it would be easy to bury: **pausing is weaker than the
kill this pre-registration commits to.** The kill arm fired and was overridden,
not satisfied.

- `DD > 8%` — breached on the full-run reading (8.60%), **not** on the
  gate-v2-era reading (4.32%). Not executed.
- `5+ consecutive losses` — did NOT fire. Max streak within the gate-v2 era is
  3. The full-run streak of 7 spans the May window predating the declaration.
- `PF < 0.7 over 30+ trades` — not evaluable (6 closed).

Two things make the override defensible rather than an evasion, and neither
makes it automatic: (1) the denominator is ambiguous in the same way the demote
arm's is, and the full-run figure includes a drawdown whose peak predates the
pre-registration by nine days — the clause is being read against a window it was
not written for; (2) with the bot paused and one position running to its own
stoploss, the practical gap between pause and kill is capital allocation, not
risk taken.

**This is live now and does not wait for the 2026-08-17 review.** If the
operator wants the pre-commitment honoured literally, the action is to kill:
stop the container and withdraw the allocation. Declining to decide is itself a
decision and should be recorded.

## What was changed

| Change | File | Effect |
|---|---|---|
| Structured `triggers` + `amendments` | `ft_userdata/preregistrations.json` | Both conflicting texts recorded; drawdown rules become machine-checkable |
| `_closed_equity_maxdd` + `_evaluate_dd_triggers` | `ft_userdata/strategy_health_report.py` | Daily report evaluates DD triggers; unbreached ones print headroom (silence ≡ unevaluated was the bug) |
| Guard F2 | `ft_userdata/user_data/strategies/FundingFadeV1.py` | Per-pair funding fails closed; a bar whose resolved funding event is >12h old gets NaN |
| `initial_state` `running` → `paused` | `ft_userdata/user_data/configs/FundingFadeV1.live.json` | PAUSED is in-memory only — any restart/redeploy/reboot would have silently resumed live trading |
| `pytest.skip` replacing `sys.exit(0)` | both staleness tests | Bare exit aborted pytest collection with INTERNALERROR instead of skipping |

Strategy md5 `ac4e0d1e…` → `976c9164…`. The `oos-retest-2026-07` provenance
block was deliberately **not** updated: it records what was measured at
registration and must stay historical.

F2 threshold note: 12h is a *pipeline-death* detector, not a tightening of
signal freshness. Binance posts every 8h and the refresh runs hourly at :10, so
healthy staleness at signal time is ≤ ~9.2h. It deliberately does **not** catch
the 10h-stale ADA trade — that is prevented at the source by the hourly refresh,
and a threshold under the healthy ceiling would block normal entries.

The registered "shadow-log then deploy" stage was collapsed: it existed to avoid
changing entry behaviour mid-measurement on a running bot, and FF is paused. The
guard logs every blocked bar, preserving that stage's visibility.

## Defects codex found in the first draft

Recorded because two were material.

1. **The amendment evaded the kill commitment.** First draft addressed two
   actions when there were three, and asserted "the bot is paused, so no action
   fires either way" — true of the gate arms, false of the kill. Rewritten; the
   kill arm now has its own section here and in the registry.
2. **F2 guarded only the terminal tail.** The mask anchored on the feather's
   final event, so an outage *inside* a feather — feed died, recovered, file now
   ends fresh — was waved through while every bar in the gap carried stale
   funding. Backtests and OOS calibration read exactly those gaps. Rewritten to
   measure per bar against the event that bar resolved to.
3. **The end-to-end test could not fail.** It supplied 49 bars against
   `min_periods=50`, so `funding_below_mean` was 0 everywhere regardless of the
   guard. Rebuilt with a positive control that proves fresh bars signal 1 before
   asserting stale bars signal 0.

Codex was **wrong** on one point: it claimed `initial_state: "paused"` is not a
valid freqtrade value and would crash-loop under `restart: always`. The deployed
image's schema is `enum: ["running", "paused", "stopped"]` and the restart
confirmed it — `RestartCount=0`, container healthy.

## Verification

- 12 tests for trigger evaluation (`tests/test_prereg_dd_triggers.py`). Test 1
  cross-checks `_closed_equity_maxdd` against freqtrade's own reported
  `max_drawdown` (0.08595131702355367) over the real 23-trade sequence — if the
  implementations disagree, ours is wrong.
- 4 tests for guard F2 (`tests/test_ff_per_pair_funding_staleness.py`), verified
  RED first (36/36 stale bars carried frozen funding) and re-verified against a
  deliberately tail-only variant so the internal-gap case cannot silently pass
  (fails 59/59 there).
- Existing BTC-macro staleness test still passes against the candidate.
- Health report run on the VPS against live data, `--stdout` only, no outbound
  send: all three triggers render as BREACHED with both readings.
- Post-restart: container healthy, `RestartCount=0`, `state: paused`,
  `runmode: live`, open NEAR trade preserved with stoploss intact. WAL-safe
  SQLite backup taken beforehand
  (`user_data/backups/tradesv3.live.FundingFadeV1.pre-f2-20260731.sqlite`).

Pre-existing suite failures (`test_supertrend_improvements`,
`test_infrastructure`, `test_configs`, `test_evolution_tracker`) were left
untouched — none reference changed files.

## Provenance of the pause

The pause was first applied at 2026-07-31 03:29:46 UTC by an **unintended
state-changing API call** during this audit — a `POST` issued while probing
whether an endpoint existed, which executes rather than tests. It was reported
to the operator immediately with a revert command offered; the operator reviewed
the finding and confirmed the pause as the intended action in the same session.
Recorded because a governance record must not launder how its own state arose.

## Open

1. **Kill-arm override — operator sign-off, now.** Not absorbed by the pause,
   not deferred to 08-17.
2. **Which text is authoritative** for the demote/rollback arms — deferrable to
   2026-08-17, since both loosen a gate on a paused bot.
3. **Auto-Invest R$300/mo** (BTC 70 / ETH 30) — still pending the operator's
   click since 2026-07-13. Per the program-state thesis this is the passive beta
   sleeve, the one component that compounds without depending on any 08-17
   verdict.

Out of scope, flagged not fixed: config tests never run against the live bot's
actual config (they look for `FundingFadeV1.json`; the bot runs
`FundingFadeV1.live.json`); `test_evolution_tracker` mutates tracked repo state
during a suite run; the freqtrade image is an unpinned `:stable` tag moving
under a real-money bot (running digest `sha256:f77b7ebf…`, reports 2026.3).
