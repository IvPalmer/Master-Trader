# Take-profit design review — issue #28

## Question and fixed diagnostic (2026-09-18)

Can an earlier whole-position target retain more profit when the current executor
cannot sustain a multi-target ladder at small size? Before running this diagnostic,
fix one alternative: exit at the nearer of the final source target and **2R**,
where R is the distance from entry to the original posted stop. Keep entries,
original stops and the historical loader unchanged. No threshold search. Compare
against the final-target baseline and the previously tested 2R/1R trail.

This is exploratory reuse of an already studied corpus, not a preregistered
holdout. The existing immutable forward epoch remains unchanged. Acceptance for
this code is reproducible aggregate results, long/short and adverse-bar tests,
explicit missed-winner reporting and no runtime integration. Acceptance for live
promotion is separate and is not met by this diagnostic.

## Result: earlier cash-out helps the full sample but fails robustness

Reproduce with:

```sh
python3 -m research.profit_retention.take_profit research/copier-validation/killers
python3 -m pytest tests/test_take_profit.py -q
```

The local private cache is required; it is not published with the aggregate output.
The loader admits 241 of 661 signals: 381 lack complete signal fields, 21 enter
past the stop/first target, 17 lack cache and one lacks the full horizon.
At 10 bps per side and zero carry:

| Policy | Mean net R/trade | Win rate | Mean days held | Late 30% delta vs baseline |
|---|---:|---:|---:|---:|
| Final source target proxy | -0.3086 | 18.3% | 5.50 | — |
| Nearer source target or 2R | -0.2134 | 29.0% | 4.36 | -0.0976R |
| Existing 2R/1R trail | -0.2473 | 29.0% | 4.51 | -0.0740R |

The cap improves 32 cases and worsens 22. Those 22 sacrifice a combined 54.75R
of positive baseline returns. Its full-sample mean improvement is +0.0952R;
excluding its best improvement leaves +0.0831R. It remains negative in all nine
fixed cost/carry stresses, and the late-block improvement is negative in all nine.
A higher win rate and less time exposed therefore do not establish a viable edge.
Results: [aggregate JSON](results/2026-09-18-take-profit.json).

The older [T1 study](../copier-validation/killers/T1_EXIT_RESULTS.md), using a
different entry/venue model, also found that earlier full exits reduced losses
without producing positive total returns. Do not pool these studies or treat
these historical numbers as current live expected returns.

## What a smarter exit should actually do

1. **Choose executable size before promising a ladder.** Current receiver grouping
   accumulates undersized slices at later source targets and reserves an executable
   remainder. This preserves source allocation, but can leave a small position
   waiting for one distant target. An alternative small-position policy must be
   explicit: one full exit, versus a core realization plus a runner only when both
   portions pass the actual executor checks. Exchange minimums alone are not enough;
   precision, filled quantity and the remaining-position rule also matter. Do not
   increase capital merely to make a ladder possible.
2. **Match the exit to the signal's economics.** For channel mean reversion, test
   realization on return toward the channel mean against the existing time-based
   ROI schedule. For a funding trade, test exit when expected remaining carry no
   longer covers exit costs and directional risk. For copied directional trades,
   test partial realization plus a runner only on genuinely executable positions.
   These are separate hypotheses, not interchangeable fleet-wide settings.
3. **Use information available before the decision.** A volatility-aware runner
   could use completed-bar ATR and confirmed trend deterioration. Establish the
   stop after the observation and allow it only to tighten. Never choose an exit
   using the final maximum favorable excursion or a future candle's high. This
   study does not test ATR/trend exits: its per-signal cache does not guarantee an
   adequate pre-entry lookback, and adding parameters now would invite fitting.
4. **Account for opportunity cost without arbitrary timers.** A stale trade ties
   up one of the bot's slots, but earlier exit is only useful if its replacement
   opportunities improve portfolio net results. Compare identical entry streams
   first, then a capacity-constrained portfolio replay; shorter holding time alone
   is not profit. Retain the existing Keltner stale-loser protection separately.
5. **Treat fill reliability as part of the rule.** A target touch is not a fill.
   Use actual partial fills, source exits, fees/funding and fixed depth/delay
   stresses. Reconcile remaining inventory and reduce-only order sizes after each
   fill, and verify stop coverage before cancel/replace operations. Hyperliquid
   mark-triggered TP/SL differs from resting limit TP orders; a triggered stop-limit
   can remain unfilled after a gap. These distinctions must survive the replay.

## Decision and outstanding work

Do **not** promote the cap or the existing trail from these results. No new live
settings, orders, allocations, observer policy or immutable epoch changed here.
The next useful candidate is a **size-aware realization plus runner** design,
with a separately specified whole-position fallback. It needs an execution-aware
paired replay of the actual target ladder and sufficient causal price history
before choosing an ATR/trend rule. Avoid a threshold sweep or selecting parameters
from the losing late block. Record every tested candidate, including failures.

Issue #28 remains open for that design, fresh completed forward pairs and strategy
validation. Current forward accounting implementation is already complete; fresh
market evidence remains pending. These results do not justify restarting its epoch
or relabeling pre-epoch positions. The separately tracked settled-funding reporting
discrepancy is also not repaired by a take-profit rule.

Promotion would require a frozen candidate on a new, clearly separated evaluation
epoch, positive net evidence after costs/funding, uncertainty that accounts for
dependent trades, acceptable missed winners and downside, and executable fills
under fixed stresses. The 241 already studied cases cannot supply that evidence.

## External references

- [Hyperliquid TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl):
  mark triggers, fixed-size orders and stop-limit nonfill behavior. This describes
  exchange mechanics, not evidence that a particular exit policy is profitable.
- [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf):
  repeated strategy selection on the same data creates false discoveries. This
  motivates reporting failed candidates and limiting exploratory trials; no PBO
  estimate or statistical significance is claimed for this small diagnostic.
