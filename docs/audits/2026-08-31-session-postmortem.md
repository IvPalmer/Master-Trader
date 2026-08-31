# Post-mortem: the 2026-08-30/31 fleet session

Written for review after the fact. It supersedes the narrative parts of
[2026-08-30-fleet-review-and-recalibration.md](2026-08-30-fleet-review-and-recalibration.md),
which was written mid-session and is wrong in places — most of its OITrend
section and its fleet table did not survive the day.

The session did three useful things and made nine mistakes. Both halves are
here, because the mistakes fall into three repeating patterns and the patterns
are the part worth remembering.

## Where the fleet ended up

| bot | state | why |
|---|---|---|
| KeltnerBounceV1 | **LIVE** | unchanged all session; measured and deliberately not touched |
| FundingFadeV1 | **LIVE** | demoted, then **reverted** — the demotion was a miscount |
| KillersScalpV1 | **LIVE** | the only PF > 1 source (1.57 / 42 trades) |
| InsidersScalpV2 | dry | zero post-remediation sample; source prior poor; ID-correlation risk |
| ShortKeltnerV2HLlive | dry | 0.20 signals/month — cannot be validated in a human timeframe |
| OITrendPullbackV1 | dry | its recalibration evidence was withdrawn as invalid |

Three preregistrations record the demotions, one records a proposed redesign,
and `ff-gate-v2-review` carries the reversal.

## What holds up

**The security work.** The two signal receivers accepted unauthenticated
trading instructions while sharing a Docker network with ~25 unrelated
containers. They now require a per-receiver bearer token on every route but
`/healthz`, enforced app-level so new routes are protected by default, with
`/docs` and `/openapi.json` disabled — those ignore app-level dependencies and
were serving the full route map. Verified in production: 401 without, 200
with, 404 on the docs, and the killers token rejected by the insiders
receiver. This was checked by an independent pass and stood.

**Two pre-existing bugs found in passing.** The metrics exporter resolved
`OITrendPullbackV1` to a hostname that does not exist, so a live bot sat
outside the circuit breaker's capital math; and `KillersScalpV1` — the only
leveraged bot — was excluded from the breaker by a flag that means something
else. Both fixed.

**The test suite audit.** `tests/test_configs.py` resolved every bot to
`{name}.json` while two live bots deploy as `{name}.live.json`, so sixteen
tests raised `FileNotFoundError` and the safety invariants they carry — no
committed API keys, stoploss/mode agreement, stoploss width, required fields —
**silently never ran on those two bots**. Eleven more tests demanded back a
feature that was removed *because it lost money*. Stable baseline went 31 → 4.

**One measurement that refuted its own hypothesis.** KeltnerBounceV1's ROI
ladder was proposed as cutting winners; across 22 trades the ROI exits landed
0.20–0.49% below their own maximum favourable excursion, and the worst
drawdown among winners was −5.32% against a −6% stop. No room either way. Left
alone.

## The nine mistakes, by pattern

### Pattern A — a number produced without interrogating its premise

**A1. The OI gate calibration.** Raised `oi_min_growth` 0.02 → 0.0 on a
simulation claiming PF 2.46 / +16.3%. It did not reproduce the deployed
contract on four counts: the OI window was misaligned by one hour against what
the bot reads at the decision point; `max_open_trades: 1` was unmodelled (it
ran eight concurrent slots); `custom_exit` was not simulated at all; and it
used perpetual klines for a spot bot, without fees, at 1h resolution on a
ROI+stop+trailing exit stack. Corrected it gives **PF 0.74 / −4.0%**, and a
placebo mask of equal pass rate scores median PF 0.69 — the gate sits at the
57th percentile of its own null. Caught before any trade. Evidence withdrawn,
bot moved to dry.

**A2. The FundingFade demotion.** Claimed "7 consecutive losses against a kill
clause of 5+". The losses were counted consecutive **in a result-ordered list
without looking at the dates**. By date they are two blocks with a 52-day
no-trade gap. The first block *is* the May 10–16 streak that already triggered
its own remediation (gate v2, 2026-05-19) — judging it again is double
jeopardy. The second block was a known stale-funding data bug, fixed
2026-07-13. The supporting "last 12 trades PF 0.08" spanned both the gate-v2
deploy and the funding fix, aggregating three versions of the strategy.
Post-remediation there are four closed trades. **Reverted.**

**A3. The Insiders rationale.** The decision (stay dry) survived review, but
the stated reasons did not. All seven trades are 5× and end 2026-08-13, before
every remediation — the same epoch error as A2, unnoticed until it was pointed
out. "Loss capping cannot create edge" is false: expectancy can turn positive
by shrinking average loss alone, and the sizing and limit-in-zone changes alter
*which* signals fill. The fee claim was inflated — freqtrade's ratios are
already fee-adjusted. The May WEEX validation covered the **paid** channel
under a different executor: adverse prior on the source, not a test of this
configuration.

### Pattern B — a dry/live coupling nothing enforced

Three separate instances in one day, each found by a different accident.

**B1. `stoploss_on_exchange`.** Demoting the two spot bots to dry left it
`true`. Dry-run stop orders live in memory and are lost on restart — a
documented incident (2026-04-07, BearCrashShortV1). The Hyperliquid services
guard this in their entrypoint; the spot services have no dry branch. Found
only because fixing the config-path bug made the test run again.

**B2. The circuit breaker's capital base.** The breaker's peak is absolute
(`base + pnl`) where base is the sum of the *live* bots' starting capital.
Adding Killers to its scope raised the peak to $254.96; demoting FundingFade an
hour later dropped the base to $165.53; the breaker read the $89.43 that walked
out as a **35% drawdown** and stopped both remaining live bots. Total P&L at
that moment was −$0.11. **This was the expensive one**: a stopped freqtrade
processes no exits, and KillersScalpV1 held an open leveraged DOT position with
no exchange-resident stop, so it ran unmanaged for roughly fifteen hours and
drifted +3.2% → −3.5%.

**B3. `db_url`.** OITrendPullbackV1 was moved to dry while still pointed at
`tradesv3.live.OITrendPullbackV1.sqlite` — the first simulated trade would have
contaminated the live equity curve. Found by adversarial review, not by me.

All three now have tests or rebasing logic that enforce the coupling.

### Pattern C — verification that did not verify

**C1. `systemctl list-units` without `--user`.** Concluded the observer was an
unsupervised process, killed it and started a bare `nohup` orphan. There *was*
a `killers-observer.service` user unit with `Restart=on-failure`, left enabled
but dead — a user-manager restart would have started a second observer against
the same Telethon session. Restored under systemd.

**C2. A test that was silently skipped.** The breaker regression test was
written with `pytest.importorskip("prometheus_client")` and did not run on any
machine without the package. Rewritten to stub the module. **Check for skips,
not just passes.**

**C3. A test pinning state that then changed.** A test asserted the OI prereg
was `status: open`; closing that prereg made it fail. Not harmful, but it
showed the test was pinning bookkeeping rather than behaviour.

## How to check any of this yourself

- Fleet state: `/show_config` per bot on 8095/8096/8102/8099/8098/8103 —
  `dry_run` and `state` are the two fields that matter.
- Breaker: `portfolio_peak.json` in the exporter's state volume, plus
  `docker logs ft-metrics-exporter | grep -i "capital refreshed\|rebasing"`.
  **Any promotion or demotion perturbs it — check after every one.**
- The OI claim that survives (2% above the p99 of real OI growth) is
  reproducible from `ft_userdata/research/oi_gate_calibration_2026-08-30.py`;
  the P&L in that script is wrong and the file says so at the top.
- Test regressions: compare against the baseline **excluding**
  `tests/test_infrastructure.py`, which probes the VPS from localhost and flaps
  with tunnel state. That file is why the baseline read 47, then 33, then 31.

## Open, and owed to you

- **Killers sizing.** The only PF > 1 source. Account is $98.37, and the
  observed 16.2R drawdown at the current $2/trade is already 33% of it. An
  earlier suggestion in-session to double to $4 is **retracted** — that would
  have been 66%. The lever is the capital base, not the risk fraction:
  consolidating the ~$90 idle in the two demoted HL wallets supports
  `KILLERS_RISK_USD=3.50` and `KILLERS_MAX_MARGIN_USD=20` at a slightly
  *lower* risk fraction. Moving funds between HL accounts is yours to do.
- **Hyperliquid native stops.** Still never observed working end-to-end on an
  organic fill, and the Killers record contains a −2.8R trade where the stop
  did not hold. The largest unquantified risk in the fleet, and B2 above is
  what happens when it coincides with a halted bot.
- **Insiders re-entry** needs the receiver to synthesise a correlation key from
  the opener's message id, plus market-entry-with-SL using the live mark. Then
  a fresh dry epoch. Not the old seven trades.
- **OITrend** should run its dry epoch with shadow-cohort measurement: record
  every TA-qualified setup, its continuous OI value, whether the gate passed,
  and outcomes for the *rejected* ones, against placebo masks.
- **ShortKeltner** needs a new strategy file with a breakdown trigger, not a
  relaxed gate. Frequency is measured (0.20 → 8.01/month); profitability is
  not, deliberately.

## The honest summary

Of five decisions taken alone about bots, one was wrong and reverted, one had
the right action for wrong reasons, and two carried coupling bugs that only
surfaced under review. Everything that went through adversarial verification
before being applied has held. Everything that did not, did not.

The rule that follows: **no demotion, promotion or parameter change on a
money-holding bot without adversarial review first — not after.**
