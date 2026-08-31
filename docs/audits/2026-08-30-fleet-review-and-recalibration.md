> **Partly superseded.** Written mid-session; its OITrend section and fleet
> table did not survive the day. Read
> [2026-08-31-session-postmortem.md](2026-08-31-session-postmortem.md) first.

# Fleet review, hardening and recalibration — 2026-08-30

One session, three phases: a code review of the live strategies, a security
hardening pass, and an evidence-driven recalibration of what the fleet
actually trades. This is the durable record; the per-change rationale lives in
the commit messages and `ft_userdata/preregistrations.json`.

Commits: `1335853` (merge) · `46f0dee` · `f82b9b3` · `277170e` · `5b7e745`

## Headline

The strategy code was clean. **No signal-logic bug was found in any of the
five live strategies.** The fleet's two real problems were elsewhere:

1. **Ingress and credentials.** Both signal receivers accepted unauthenticated
   trading instructions while sharing a Docker network with ~25 unrelated
   containers.
2. **Throughput.** Six bots produced two trades in seven days. That is not
   caution, it is an off switch — and one of them literally was.

## Phase 1 — security (deployed and verified)

`POST /event` on either receiver sizes a signal and calls Freqtrade
`/forceenter` with stored credentials. It had no authentication of any kind.

- Bearer token required on every route but `/healthz`, as an **app-level**
  FastAPI dependency so a future route is protected by default. The process
  refuses to start without a token rather than falling open.
- `/docs`, `/redoc` and `/openapi.json` **disabled**: FastAPI registers those
  as plain Starlette routes that app-level dependencies never reach, and they
  were answering 200 with the full route map and payload schemas. This was
  found by probing the running app, not by reading the code.
- One token **per receiver** — they drive separately funded accounts.
  Cross-token rejection verified in production.
- Four clients wired: host observer, the strategy's stop-refresh lookup, the
  dashboard's `/ingress` poll, the insiders bridge.
- `force_entry_enable: false` on ShortKeltnerV2HL (nothing issued forceenter
  to it); webhook alerts enabled on it (it was the only live bot with none).
- `MACRO_GATE_COLUMNS` now drives both the macro gate and its NaN watchdog.
  They had drifted: the gate read `btc_usdc_sma50_slope_1h`, the watchdog did
  not check it, so a NaN slope blocked every entry silently.
- Credential literals in six configs replaced with `OVERRIDE_VIA_ENV`; opt-in
  per-bot credentials with fallback to the shared pair; `api_utils` no longer
  retries freqtrade's public default credentials by default.
- Two pre-existing bugs fixed in passing: the metrics exporter resolved
  `OITrendPullbackV1` to a hostname that does not exist (a LIVE bot sat
  outside the circuit breaker's capital math), and a failed receiver stop
  lookup never stamped its TTL (an HTTP call every bot loop during an outage).

Deploy notes and the `--build` trap: `docs/ops/2026-08-30-hardening-deploy.md`.
Preflight: `deploy/vps/preflight-credentials.sh`.

### The cutover

The observer is the linchpin — deploy receiver auth without restarting it and
every signal 401s. It had run **47 days** without a restart, started by hand,
from a separate stale checkout with uncommitted local modifications.

Order used, which has **zero dead window** and is better than the runbook's:
tokens into both env files → update only `killers_bot/observer.py` in the
stale checkout → restart the observer *while the receivers still accept
anything*, so that step alone is reversible → then rebuild the receivers.
Telethon reconnected on the existing session with no re-auth.

`ft-killers-scalp` was restarted **last** because it held an open DOT position
**with no exchange-resident stop** (`stoploss_order_id` empty). Both
protection layers terminate at the bot's REST API, so its ~81s restart window
left that position unprotected; it was 12.5% from its stop and survived
unchanged. **Rule for next time: check `stoploss_order_id` before restarting a
copy-trader that holds a position.**

## Phase 2 — what the evidence actually says about each strategy

Pulled from the trade databases, not from memory. Same receiver image, same
strategy class, same venue code — only the signal source differs:

| bot | source | sample | record | PF | admission |
|---|---|---|---|---|---|
| KillersScalpV1 | VIP channel | 42 trades | **+$53.13** | **1.57** | 38/57 = 67% |
| KeltnerBounceV1 | own | 22 trades | +$5.27 | 1.22 | — |
| FundingFadeV1 | own | 24 trades live | −$1.32 | 0.86 | — |
| InsidersScalpV2 | Dennis **free** channel | 7 trades | **−$15.26** | **0.16** | 4/65 = 6% |

### InsidersScalpV2 → dry-run

PF **0.16**. Wins of +16.88% / +2.24% / +1.01% against losses of −54.34% /
−33.18%. The largest win was held **720 hours** on a bot whose premise is
scalping. Every exit was `force_exit`.

The channel is not quiet — 65 `open` signals in 2.8 months (27/25/13 by month,
declining). Our filters rejected 94% of them, against 33% for the VIP channel
on identical code. Every Dennis event carries `signal_id: null`, so exits
correlate by symbol alone.

The 2026-08-27 adjustments bound loss; none create edge. Capping the −54%
still leaves a +1%/+2%/+17% win distribution at a 50% win rate, where two of
three wins barely clear HL taker cost at 3x. Capital left **idle**, not
stacked onto Killers. Prereg `insiders-demotion-2026-08-30` sets the re-entry
bar.

### ShortKeltnerV2HLlive → dry-run

0.20 signals/month. The 2026-08-29 research already established the ceiling at
~6.5%/yr under an impossible 100% hit rate, against ~10.4% APR available
passively as short funding carry **on the same venue** — holding the capital
idle beat running the strategy under perfect execution. Cause is a design
contradiction, not a threshold, so the gate was deliberately **not** loosened.
~$40 released. Prereg `shortkeltner-demotion-2026-08-30`.

### OITrendPullbackV1 → gate recalibrated

Instrumented first: the entry conjunction was refactored into named terms with
an hourly per-pair log naming the binding constraint. First live output —
`oi_growth_2pct = 0/500` on all eight pairs while every other term passed
180–500/500.

Binance `/futures/data/openInterestHist` serves 30 days at 15m, paginated.
**That retires the "OITrend cannot be backtested" finding**; the data existed
and was unused. Measured over 30 days × 8 pairs, 45-minute OI growth
distributes p50 +0.01%, p90 +0.39%, **p99 +1.46%**, max +6.76%. The deployed
threshold was **2.00%** — above the 99th percentile. The TA conjunction alone
produced **76 setups** in that window; the gate admitted zero.

Sweep under the deployed exit rules (1h bars, next-bar-open, no fees):

| threshold | trades/mo | PF | net 30d | win |
|---|---|---|---|---|
| +2.00% (was) | 0 | — | — | — |
| +0.25% | 3 | ∞ | +4.4% | 100% |
| **0.00% (now)** | **20** | **2.46** | **+16.3%** | **85%** |
| −0.50% | 29 | 1.34 | +9.0% | 76% |

`0.0` was chosen **on mechanism, not as the sweep's argmax**: it means open
interest is not *contracting* while price reclaims the EMA20 inside a 50/200
uptrend — participation holding through the pullback, which is the
continuation thesis. A +2% move in 45 minutes is a liquidation/squeeze
signature, plausibly the opposite regime. That the sweep degrades on both
sides of zero is corroboration, not the argument.

**The profitability evidence was WITHDRAWN the same day.** An independent
verification pass found the calibration script did not reproduce the deployed
contract on four counts:

1. **OI window off by an hour.** The sim scored each candle against OI over
   `[T−45m, T]`; the live bot reads `[T+15m, T+1h]` at the decision point.
   Disjoint windows — the sim tested a different rule than the one running.
2. **`max_open_trades: 1` not modelled** — the sim ran eight concurrent pair
   slots, overstating trade count ~2.5×.
3. **`custom_exit` (`ema50_break`) not simulated at all**, despite the
   docstring claiming the strategy's own exit rules.
4. **Perpetual klines for a spot strategy**, no fees, no slippage, 1h bars on
   a ROI+stop+trailing exit stack — a direct violation of the standing
   `--timeframe-detail 1m` rule.

Corrected, the same 30 days give **PF 0.74 and −4.0%**. A placebo mask of
equal pass rate scores median PF 0.69, putting the gate at the **57th
percentile of its own null** — no demonstrated discriminative power.

**What survives:** the distribution finding, which does not depend on the
simulation. 2.00% really does sit above the 99th percentile, so reverting
there would knowingly restore an off switch. The threshold therefore stays at
0.0 **and the bot moved to dry-run** — "not an off switch" is not "profitable".
Zero trades were taken under the recalibrated gate, so no capital was exposed
to the withdrawn evidence. Prereg `oi-gate-recalibration-2026-08-30` is closed
with the withdrawal recorded and the requirements for a valid redo.

### KeltnerBounceV1 → deliberately unchanged

The proposed change was refuted by its own measurement. Across 22 dry trades
the 17 ROI exits landed **0.20–0.49% below their own maximum favourable
excursion** — the ROI ladder is not cutting winners. The worst adverse
excursion among *winners* was **−5.32%**, just inside the −6% stop, so there
is no room to tighten either. The v2 stop change was already well calibrated.

### FundingFadeV1 → nothing to add but the decision

Two earlier concerns were already handled and the memory recording them was
stale: `_evaluate_dd_triggers` has been in the daily report since 2026-07-31,
and the 3.60% vs 3.84% contradiction is recorded as three separate triggers in
`ff-gate-v2-review`, all marked superseded pending operator sign-off.

## Fleet after this session

**Live (3):** KeltnerBounceV1 · FundingFadeV1 · KillersScalpV1
**Dry (3):** InsidersScalpV2 · ShortKeltnerV2HLlive · OITrendPullbackV1

## What the end-of-day verification caught

A four-lens independent pass over everything deployed. It confirmed the
security work, the demotions, the token wiring and the test baseline — and it
caught three things worth more than the rest of this document:

**The OI calibration was void** (above). Caught before a single trade.

**I broke the observer's supervision.** There was a `killers-observer.service`
systemd **user** unit with `Restart=on-failure` managing the process. I killed
it and started a bare `setsid nohup` orphan, leaving the unit enabled but dead
— so a user-manager restart would have started a *second* observer against the
same Telethon session. My check missed it because `systemctl list-units`
without `--user` does not list user units. Restored: single PID under systemd,
`Restart=on-failure`, verified.

**KillersScalpV1 — the only leveraged live bot — sat outside the circuit
breaker.** `bots_config.json` marks receiver-managed bots `active: false` by
design, and the exporter skipped on exactly that flag, so Killers was never
scraped: its losses did not count toward the 10% trip threshold and the
breaker could not halt it. Fixed at the exporter (`active OR production_live`)
rather than by flipping the flag, which would have broken 22 config tests that
correctly assume `active` means autonomous-strategy.

The real pre-existing test baseline is **33 failures**, not the 47 used
earlier in the session.

## Killers position sizing — analysed, not applied

The only PF > 1 source. Empirical distribution over 41 closed trades: 49% win
rate, +37.0% average win, −22.5% average loss, payoff 1.65, **worst losing
streak 8**, **worst drawdown 16.2R**, and a **worst single trade of −2.8R** —
the stop did not hold, which is the stop-limit gap risk materialising.

Account is **$98.37**, not the $188 previously assumed (that was the sum of
three HL wallets). Applying the historical 16.2R drawdown:

| risk/trade | % account | worst historical DD |
|---|---|---|
| **$2 (current)** | 2.0% | −$32 (**33%**) |
| $4 | 4.1% | −$65 (**66%**) |
| $6 | 6.1% | −$97 (99%) |

An earlier suggestion in this session to double to $4 was **wrong** and is
retracted: it would have taken 66% of the account in a drawdown that already
happened. Empirical Kelly is 18% full / 4% quarter, and quarter-Kelly is
already $4 — with PF 1.57 on 41 trades the standard error does not support
operating near it.

**$2 is approximately correct for a $98 account.** The binding constraint is
the capital base, not the risk fraction. With ~$90 now idle in the two demoted
wallets, consolidating to ~$188 would support `KILLERS_RISK_USD=3.50` and
`KILLERS_MAX_MARGIN_USD=20` — ~1.75× the dollar P&L at a slightly *lower* risk
fraction (1.86% vs 2.03%). Moving funds between HL master accounts is the
operator's action.

## Open, owed to the operator

- **Killers sizing** — awaiting the capital consolidation decision above.
- **FundingFadeV1** — which MaxDD action is correct (3.60% rollback vs 3.84%
  demote). Both recorded, neither executable without sign-off.
- **ShortKeltnerV2HL** — retire permanently, or specify a preregistered
  redesign committing to one regime.
- **Hyperliquid native stops** — still never observed end-to-end on an organic
  fill, and the Killers −2.8R tail shows the stop-limit band failing in
  practice. This is the largest unquantified risk in the fleet.
- **Credential rotation** — assessed and declined: withdrawals disabled,
  ~$198 ceiling, requires filesystem access to the operator's Mac. Revisit
  only if the spot account grows; the fix would be Binance's IP whitelist
  pinned to the VPS egress, not a key rotation.
