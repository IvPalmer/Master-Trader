# Profit retention research — 2026-09-16

Related to [#28](https://github.com/IvPalmer/Master-Trader/issues/28).
Original study status: descriptive research and proposed forward experiment.
For the subsequently implemented forward collector and accounting, see
[ACCOUNTING.md](ACCOUNTING.md). No live exit,
allocation, runtime configuration or preregistration has changed. Shadow
collection is **not running** as part of this work.

## Recommendation

Evaluate a full-position risk-based trailing stop for Killers before adding
another strategy or increasing capital. Keep the original protective stop until
the trade reaches +2R, then trail its favorable high-water mark by 1R. R is the
price distance from the actual entry fill to the original posted stop, independent
of leverage. Example: entry 100, original stop 90; at 120 the candidate stop is
110; at 130 it becomes 120. This is a hypothesis, not an approved live rule.

The current executor groups small TP allocations at the last target in each
group and checks both minimum notional and Freqtrade's remaining-position
reserve (`services/killers-receiver/app/tp_plan.py`). That can leave a small
position waiting for a distant target after a substantial favorable move. A
full-position protective stop avoids dependence on a multi-slice ladder. Audit
venue reduce-only exceptions and executor constraints separately before changing
grouping; do not increase stakes just to obtain partial exits.

## Evidence and limits

Earlier [exit research](../copier-validation/killers/RESULTS.md) found that
breakeven/trailing exits raised win rates but did not beat the fixed-stop variant
on total return. The [broader search](../copier-validation/killers/STRATEGY_SEARCH_RESULTS.md)
also found a negative out-of-sample return for a different trailing overlay.
Those were different execution/venue epochs: useful caution, not validation of
today's copier. Some apparent historical winners hit their original stop before
their eventual peak; that later profit was not available to the stopped trade.

This diagnostic uses six current-epoch entries, their immutable posted stops,
actual closed endpoint or current observation mark, and Hyperliquid 15-minute
trade candles captured on September 16. One trade is closed; five remain open.
Raw input stays private on the VPS. The sample was selected after seeing
giveback and is **not a holdout or a preregistered experiment**.

| Overlay | Mean gross R | Change from observed mean | Improved / worse / unchanged |
| --- | ---: | ---: | --- |
| Observed endpoint | -0.052 | — | — |
| Breakeven after +1R | -0.008 | +0.044 | 1 / 0 / 5 |
| Lock +0.5R after +2R | +0.075 | +0.127 | 1 / 0 / 5 |
| Trail 1R after +2R | +0.701 | +0.753 | 2 / 0 / 4 |

These are equally weighted per-trade price-risk units, **not portfolio return,
realized profit or an expected improvement forecast**. The apparent advantage
comes from two observations and can reverse when remaining trades finish.
All three tried variants are shown to avoid hiding unsuccessful trials.

`replay.py` checks an already-active stop before updating the high-water mark;
new stops apply on the next bar. Gaps receive the adverse open, not a better
stop fill. It excludes partial entry and endpoint bars, which can miss triggers.
It assumes ordered complete input; collection quality must be checked separately.
No TP ladder or source-stop revisions are simulated. Thus it is a bounded
stop-overlay diagnostic to observed endpoints, not a complete strategy backtest.

Trade OHLC is not mark-price history. Hyperliquid [triggers TP/SL on mark price](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl),
and triggered stop-limit orders can remain unfilled. This replay cannot establish
actual executable fills: it omits intrabar paths, latency, depth, nonfills, fees,
funding, replacement entries and portfolio capacity. Gross breakeven still loses
costs. Full entry coverage was checked, but that does not solve these limitations.

## Proposed forward experiment

1. Implement a read-only shadow collector and freeze its version and start time
   before collecting new eligible entries. Register the protocol then. Exclude
   existing positions from the scored cohort; never apply their old peaks
   retroactively. Baseline keeps the actual admitted entries and source exit
   policy; challenger changes only the full-position stop after +2R to a 1R
   trail. Keep the baseline's executable TP rules in both arms.
2. Record actual fills, original risk, source revisions, timestamped mark prices,
   bid/ask, fees, funding and baseline exits privately. A tighter source stop
   always wins; neither arm widens a protective stop. Include source revisions
   and order update latency in the simulation. Missing/stale observations and
   unfillable stop-limit exits must be flagged, not credited as successful fills.
3. Compare paired **net** R and dollar returns, downside/drawdown, missed large
   winners and cost sensitivity. Follow the baseline after an earlier shadow
   exit; do not truncate its later recovery. Report remaining open pairs
   separately. Also assess capital-release/replacement effects before any
   portfolio-level claim; the initial paired study holds admission fixed.
4. First review at 90 days, requiring at least 30 completed pairs and 10 armed
   challengers as an operational review floor, not statistical proof. If fewer,
   report inconclusive. Show uncertainty and date-clustered sensitivity rather
   than treating correlated coins as independent evidence. Positive net
   improvement must survive realistic cost/nonfill stress without a material
   deterioration in downside. Ambiguous evidence means no promotion.
5. Do not tune thresholds on that cohort. A revision starts a new version and
   fresh evaluation. Record all trials: [selection bias and multiple testing](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
   can make an apparently excellent backtest unrepeatable.
6. Before any separately authorized rollout, test exchange-resident stop updates,
   safe replacement with continuous protection, partial fills, restart recovery,
   precision, rejected updates and stale data. Verify exchange acceptance and
   retain the stronger existing protection on failure. A shadow result alone
   is insufficient deployment evidence.

## Priorities beyond this overlay

First make profit retention measurable (peak favorable excursion while actually
held, realized/marked giveback, net costs and exit reason). Then evaluate this
one candidate on fresh entries. Keep funding, Keltner and copier epochs separate;
do not transplant this policy fleet-wide. Aggregate correlated exposure and the
current validation gaps remain tracked in #28. A new strategy does not itself
solve exit giveback, so it should not displace this work.

## Reproduction and validation

Run `python research/profit_retention/replay.py /private/path/cases.json` with a
private list of entries matching the fields consumed by `replay`. Prices and
OHLC must use the same units; start/end timestamps must share units. Never commit
raw account data. Synthetic tests cover delayed activation, adverse gap fills,
short symmetry and exclusion of pre-entry candles. They validate replay mechanics,
not trading profitability or the live executor.
