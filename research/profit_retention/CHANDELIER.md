# Source exits plus a volatility-aware protection hypothesis — #28

## Fixed exploratory protocol, written before running (2026-09-18)

Test one Chandelier-style alternative on the existing 241-case historical loader.
Use **completed UTC one-hour trade candles**, Wilder ATR(22), the highest high
(long) or lowest low (short) of those 22 candles, and a 3 ATR distance. This is an
hourly adaptation, not the published daily default. Keep the existing +2R arming
threshold, original posted stop and final source-target proxy. A new level takes
effect only on the next five-minute bar and can only tighten. It becomes eligible
only when the proposed level protects a positive gross price return. Costs and
gaps can still make the realized result negative.

No guaranteed pre-entry history exists in the per-signal cache. Therefore warm up
using 23 full post-entry hourly candles (one prior close plus 22 true ranges).
Early trades are retained with their original stop; do not drop early losers.
Do not use a partially observed entry hour, missing candles or future highs.
No parameter sweep. This tests the explicitly delayed indicator, not a fully
warmed-at-entry live implementation. Existing forward epochs remain unchanged.

## Posted Killers exits: what we actually have

Checked source and the deployed receiver on 2026-09-18:

| Source information | Current handling | Important distinction |
|---|---|---|
| Initial TP ladder | Stored in the position/target-order records; executable groups placed as resting limits | Small slices accumulate at a later source target; not every posted rung gets an order |
| Target-hit / partial-close announcement | Reconciles real order state; may be audit-only when a live TP covers the trade | Does not imply our account filled at the channel's announced price or quantity |
| Full-close instruction | Matched position goes through the full-exit path | Must reconcile the actual exchange fill before scoring |
| Explicit close-at-first-target plan change | Consolidates remaining quantity at TP1, or exits according to the existing fallback logic | Separate from a target-hit announcement |
| Numeric or breakeven `move_sl` | Validated tightening updates receiver `sl_abs`; posted-stop monitor is enabled | Does not amend the native exchange stop; depends on receiver/price/executor availability |
| Generic `signal_update: tighten_sl` | Warning/log only; no executable primitive | Do not describe every source stop revision as implemented |

The read-only receiver snapshot had five open positions, five active target rows,
one pending and one unknown row (the prior audit tied the unknown row to a closed
position). These are local bookkeeping counts, not a new exchange-wide order
reconciliation. Source code and deployed code both implement explicit `move_sl`;
an older comment describing it as deferred is stale.

The historical archive has 661 signal records, 280 with ladders, 509 with channel
events and 75 with final channel-close timestamps. Its 1,014 events comprise 934
partial closes, 75 full closes and five stop moves. The compact event schema holds
only date/kind/percentage; the dedicated `sl_moves` arrays are empty. Therefore it
is not a complete reconstructable tape of all revised stop prices and plans.
No private identifiers or raw source messages are included here.

The existing forward [paired accounting](ACCOUNTING.md) already preserves actual
source-driven partial exits and their settled fees/funding before a hypothetical
exit. **This historical indicator diagnostic does not replay those events**: it
uses the unchanged final-source-target proxy. Do not claim it outperforms the
actual posted-exit strategy. A source-faithful comparison needs timestamped,
executable source instructions and actual fills, not channel headline percentages.

## Findings

Reproduce (requires the private local cache):

```sh
python3 -m research.profit_retention.chandelier research/copier-validation/killers
python3 -m pytest tests/test_chandelier.py -q
```

At 10 bps per side and zero carry, across the same 241 eligible cases:

| Metric | Result |
|---|---:|
| Final-target baseline mean | -0.3086R |
| Hourly ATR candidate mean | -0.2179R |
| Paired mean improvement | +0.0907R |
| Early 70% improvement | +0.1621R |
| Late 30% improvement | **-0.0736R** |
| Improvement excluding best case | +0.0687R |
| Improved / worsened cases | 32 / 15 |
| Candidate activated | 51 |
| Positive baseline returns reduced | 15, sacrificing 45.37R combined |

The candidate remains negative and the late-block delta remains negative under
all nine fixed cost/carry scenarios. It sacrifices less positive-baseline return
than the fixed 2R cap in the preceding study, but does not establish a profitable
or robust alternative. All cases share the earlier studies' admission and bar
execution limitations. Temporal blocks on this reused corpus are not holdout.
Aggregate output: [JSON](results/2026-09-18-chandelier.json).

## Recommendation

Keep posted exits as the benchmark. The useful indicator hypothesis is a
**source-preserving, volatility-aware protective overlay**, not replacing the
channel with an untested oscillator. ATR scales the allowed pullback with observed
volatility; a fixed percentage does not. A hypothetical long with a recent high
of 120 and ATR of 2 produces a level of 114 at 3 ATR. It only becomes a new stop
when the arming/profit requirements are met and the previous stop is lower.
A subsequent ATR increase cannot lower the stop. Short rules mirror this.

Do not deploy this particular configuration: it failed the historical late block.
Do not sweep ATR periods/multipliers until the same sample turns positive. The
next evidence step is to obtain causal pre-entry indicator history and evaluate
this fixed hypothesis alongside actual source exits using the existing paired
fill/cost framework in a separately specified epoch. Existing observations and
policy remain immutable. Partial realization plus a runner requires the separate
size-aware design in [TP_DESIGN.md](TP_DESIGN.md); it was not tested here.

Before any live overlay, explicit source-stop tightening should have a verified
exchange-native update path (or be clearly labeled as receiver-only protection),
and generic tightening instructions need unambiguous price semantics. Track these
execution dependencies in #28 and the availability work in #11. No live trading
settings, orders, observer timers or allocations changed in this study.

## Research sources and interpretation

- [StockCharts Chandelier Exit](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit)
  documents the 22-period extreme and 3 ATR construction, typically on daily bars.
  Hourly bars, +2R arming, profit eligibility and a one-way ratchet are our explicit
  hypothesis choices, not evidence-backed optimal defaults.
- [Fidelity ATR](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)
  explains true range and volatility-dependent stops. ATR measures volatility,
  not expected return; neither reference proves an edge for these crypto trades.
