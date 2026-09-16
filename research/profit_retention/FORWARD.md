# Killers profit-retention forward observation v1

Related to #28. Frozen hypothesis: full-position trailing stop arms at +2R and
trails 1R, with risk based on actual fill and original posted stop. Baseline
remains the live source policy. No live order submission or allocation change.

## What is running versus still required

`collector.py` runs once per minute on the VPS, reading Freqtrade trade status
and history plus Hyperliquid mark contexts and top-20 order-book levels. It uses
existing dashboard credentials internally, only for GET requests. Hyperliquid
requests are unsigned `/info` reads; no account key is loaded. Every observation
is private (0700 directory, 0600 files). An immutable manifest records the actual
start timestamp and collector hash. Code changes require a new directory/version.

`shadow.py` rebuilds diagnostics from the observation tape. It activates stop
changes on the following observation, respects tighter observed source stops,
and estimates full-size execution from available depth within a 2% stop-limit
band. An unfillable triggered limit remains unresolved, never counted as profit.
A quote is not an execution; sampled marks can miss intraminute triggers. The
funding snapshots are retained, but **no net profitability score or promotion
is issued** without matched cash-flow and execution validation.

The collector is the first stage of the proposed study, not its completion.
Still required before a scored paired comparison: partial-fill/source-exit event
replay, settled funding attribution through each alternative exit time, consistent
fees, conservative latency/nonfill stress, and uncertainty/drawdown reporting.
Keep those gaps visible in #28. Do not interpret `promotion_ready: false` as a
failed strategy result: it is an intentional research safety boundary.

Only entries filled after the recorded start are prospective. Existing positions
are recorded for operational diagnostics, flagged `pre_epoch_observational`, and
never scored as fresh evidence. First observation more than 120 seconds after
entry, gaps over 120 seconds, missing/stale market data and changed position size
are explicitly flagged. Even unflagged samples remain minute-sampled evidence,
not exchange-tick-accurate fills. All counts/exclusions must accompany results.

Review at 90 days, with at least 30 completed pairs and 10 armed challengers as a
review floor, not statistical adequacy. No threshold tuning on that cohort.
Missing samples or unresolved execution/accounting mean inconclusive. A strategy
version revision needs a new preregistration/amendment and fresh evaluation.

## Historical falsification result

The fixed +2R/1R candidate was also tested against a broader, already-researched
Binance corpus using cached five-minute trade and mark bars. 661 signals were
examined; 241 had usable complete inputs. All exclusions and nine fixed cost/carry
sensitivity scenarios are in `results/2026-09-16-historical.json` with an input
fingerprint. There was no parameter sweep.

At 10 bps transaction cost per side and zero modeled funding, baseline was
-0.309R/trade and candidate -0.247R/trade. The improvement was +0.061R overall,
but **-0.074R in the later 30%**. 54 trades armed the trail; 32 improved and 15
worsened. Across all cost/carry scenarios, both variants remained negative and
late-sample relative performance remained negative. This rejects any claim that
the six-current-trade result establishes a robust improvement.

This older sample is development/falsification evidence, not an untouched holdout.
It assumes next-full-bar market entry, a full exit at the final posted target,
14-day maximum observation, adverse-first bar ordering and no source revisions
or liquidation. It is not a reproduction of today's bounded copier or actual TP
grouping. Funding is signed sensitivity (-10/0/+10 bps/day), not reconstructed
cash flows. Costs are modeled, not measured. Do not use these figures to estimate
live expected returns or to select the best cost scenario.

## Manual deployment and checks

Use the reviewed main commit's `collector.py` and `shadow.py` in a dedicated VPS
research directory. Record source SHA and manifest start in #28. This is a
manual research observer, separate from the application release branch. Do not
restart the fleet or deploy unrelated main changes.

Run collector as the existing Docker-authorized ubuntu user:

```
python3 /private/tool/collector.py --once --directory /private/observations
python3 /private/tool/shadow.py /private/observations
```

A systemd oneshot and timer run the first command with `OnUnitInactiveSec=60s`
and `TimeoutStartSec=110`. Bound execution with a process lock; overlapping runs
fail without modifying observations. Check timer state, successful health timestamp,
private permissions and a second appended observation before declaring it active.
Errors contain only an exception type; remote bodies and credentials are not logged.
The full tape and trade identifiers must never be posted to GitHub.

Rollback: disable the observer timer and service, retaining its private tape and
manifest for audit. This does not change live trades or exchange orders. Monitor
stale health (older than five minutes), failed jobs, eligibility flags and new
completed/armed observations. Notify only on meaningful changes or needed action.
