# Paired exit accounting — implemented 2026-09-16

Related to #28 and the cost-model work in #1. The +2R arm / 1R trail hypothesis
and original observation epoch are unchanged. This adds the accounting and stress
report promised by the forward protocol; it does not change any live exit.

## Inputs and reconciliation

`ledger.py` reads unsigned Hyperliquid `userFillsByTime`, `userFunding` and
`userFees` using the public account address inside the existing bot container.
It never reads the private-key variable or calls the exchange trading endpoint.
The first collection requests 90 days; subsequent collections overlap two hours.
Saturated time ranges are recursively split, including equal-millisecond events;
unresolvable saturation fails rather than silently dropping records. Exchange
fill retention is finite, so executor order quantities must also reconcile before
an older trade can be scored. Private immutable batches are written before the
cursor advances. Overlapping events are deduplicated with conflict detection.

`accounting.py` joins exchange fills to exact executor order IDs. Multiple fills
of an entry or partial TP are distinct events, each charged its actual fee once.
All matched entry quantities and exit quantities must reconcile with the executor.
Funding is the signed **settled USDC payment**, assigned only when its signed
position size matches the trade's remaining position. Positive is received,
negative is paid. Multiple overlapping positions that cannot be attributed this
way fail validation; they are not silently allocated pro rata.

For a fully closed trade, the exchange cash-flow ledger is the net baseline. The
executor's price/fee result is a separate tight numerical cross-check after
adjusting for any difference in reported versus settled funding. Funding
mismatches remain visible in `executor_funding_discrepancies`; actual exchange
funding is retained in every score. This is necessary: initial validation found a
closed trade whose executor funding field was zero despite settled funding paid.
The difference explained its approximately one-cent net P&L discrepancy. Raw
trade and ledger details remain private.

Authoritative schemas: [fills and fees](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
and [settled funding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals).

## Paired replay and fixed stresses

Both arms share actual entry fills, source-driven partial exits and settled
funding until the modeled full-position exit. Entry VWAP/risk are frozen only
after the final entry fill; increasing a position after exiting requires a
distinct protocol and is rejected. The challenger continues to honor source TP
and manual exits, but cannot borrow the original stop's fill after replacing it
with its tighter modeled stop. Source stop revisions and high-water changes
become effective on the following sampled mark.

Three fixed execution scenarios are always reported:

| Scenario | Delay after observed trigger | Available quoted depth | Extra adverse execution shift |
| --- | --- | --- | --- |
| Quoted | same observation | 100% | 0 bps |
| Stress 1 | one later observation | 50% | 10 bps |
| Stress 2 | two later observations | 25% | 25 bps |

A full-position fill must fit within the observed depth and the fixed 2% stop-limit
band even after stress. Otherwise the triggered limit remains pending and can
only fill at a later qualifying quote. Original-stop fills are not credited to
an unfilled challenger. Missing/stale marks, observation gaps, missing causal fee
rates, unresolved orders and ambiguous funding/exit timestamps remain exclusions.
Every scenario reports exclusions and nonfills alongside its completed pairs;
never interpret a subset's favorable result without the missing cases.

Simulated exit fees use the most recent account taker rate observed **before**
that exit, no older than two hours. Actual entry/source-exit fees come from fills.
Settled baseline funding after the alternative exit is excluded from the
challenger. A minute-sampled quote remains a model, not proof of execution; these
stress scenarios test sensitivity rather than calibrate a live fill probability.

## Reporting

Completed pairs report baseline/candidate mean net R, paired improvement, armed
count, worse pairs and missed baseline winners. A deterministic 2,000-resample
bootstrap clusters by entry UTC date; fewer than two dates produces no interval.
Small samples still have weak inference even with an interval. Drawdown is labeled
as the equal-risk completed-pair sequence, ordered by baseline close. It is
**not** a portfolio mark-to-market drawdown or a model of replacement entries.

Open baseline trades, pre-epoch positions and invalid cases remain counted as
exclusions. No promotion is automatic. The review still needs fresh completed
pairs, adequate independent periods, favorable cost/nonfill sensitivity and live
execution validation. These are evidence requirements, not unimplemented replay
features. Broader portfolio exposure work remains separate in #28.

## Operation and validation

The existing immutable minute collector continues unchanged. A separate reviewed
`master-trader-retention-accounting.timer` runs the ledger plus report every five
minutes. Inputs, cursor and `accounting-report.json` stay in the same private
observation directory. Tape and ledger processing stream from disk so raw history
is not loaded all at once. Reports fail on corrupt/conflicting records.

```
python3 ledger.py --directory /private/observations
python3 accounting.py /private/observations --write
```

The synthetic suite covers a full partial-entry/TP/funding/stop cycle with exact
cash totals, duplicate batches, missing fills, short cash flows, funding credits
and payments, executor funding omission, fee lookahead, pagination saturation,
latency and insufficient-depth nonfills, and date-clustered reporting. Initial
VPS read-only validation recovered seven fills and 721 settled funding events;
the closed trade's price/fee arithmetic reconciled after explicitly accounting
for its missing executor funding. No existing trade is reclassified as a fresh
experiment entry.

Rollback disables only the accounting timer/service and retains its private
ledger. The original observation timer and all live trading services are separate.

### Shared report cutoff (2026-09-18)

Each report selects the latest observation at or before the completed ledger
cutoff, then excludes later fills and funding from that same report. Repeated
observation scans use the frozen selected cutoff, so a concurrently appended
snapshot cannot create false missing-coverage/missing-fill flags. Both timestamps
and an explicit waiting status are reported; real historical coverage gaps still
fail validation. Raw observations, ledger batches and the research epoch are
unchanged.
