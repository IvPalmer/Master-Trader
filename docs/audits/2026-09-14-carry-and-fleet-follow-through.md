# Strategy review follow-through — 2026-09-14 UTC

Decision: keep current live allocations unchanged. Do not launch a funded carry
executor. Corrected shadow performance does not meet the existing 12% deployed-
capital annualized hurdle, even before unresolved execution realism is addressed.

## OI readiness

The executor remains at 0.0 OI growth. It now publishes `oi_min_growth` in its
analyzed candles; the dashboard reads that value for each pair. Missing threshold
telemetry is unavailable, not an inferred 2% gate. The stale static 2% gate label
is removed. Entry rules, risk, sizing and allocation are unchanged. Only the dry
OI bot needs a restart to expose the new field; its live OI baseline then warms
again, so temporary warming is expected.

## Carry replay

Original input archive on VPS:
`/home/ubuntu/master-trader/state/backups/carry-correction-20260914/shadow`.
Corrected replay:
`/home/ubuntu/master-trader/research/hl_carry_2026-07/replay-v2-final-20260914`.
The existing paper monitor resumes with corrected state and version-controlled
tracker. Original records are preserved. No exchange orders are submitted.

The replay covers 1,510 recorded hourly decisions, July 13–September 14, with the
original funding thresholds, concurrency and study fees. Nine completed episodes,
zero open at cutoff. Corrected fill timing changes the selected trade sequence;
this is a replay, not simply repricing the original nine trades.

| Measure | Corrected model |
|---|---:|
| Net P&L | $27.64 (original report $38.89) |
| Modeled funding | $42.05 |
| Modeled basis P&L | $4.49 |
| Modeled fees | $18.90 |
| Completed position-hours | 1,754.35 |
| Annualized return on matched deployed capital-time | 9.20% |
| Full-period return on $4,500 provisioned | 0.614% |
| Annualized return on $4,500 provisioned | 3.57% |
| Extra 5 bps on each of four fills per episode: net | $9.64 |
| Extra 10 bps on each fill: net | -$8.36 |
| Fills at/before signal | 0 |

These are modeled results, not realized money or forecasts. Five original fills
preceded their signal. The old short exits used the bid instead of the ask.
Weekly exposure included whole lifetimes of closed trades and omitted open ones;
v2 clips intervals correctly and does not publish an annualized weekly return
without boundary marks. First-post fraction among fills is not an overall fill
success rate.

The recorded depth screen finds 20/36 legs lack the full modeled base quantity
at the relevant top-of-book quote. This does not prove fills impossible at other
prices; it invalidates assuming full-size best-quote execution without modeling
those prices. Quote timestamps are batch starts, not atomic per-leg observations;
funding arrival timestamps are absent. Actual account fees, marked funding
notional, margin requirements and hedge latency remain unvalidated. The modeled
$1,500 capital per hedge is an assumption, not an established deployable budget.

## Current fleet exposure and next evidence

Read-only snapshot during this work: FundingFade and Keltner have no open trades.
Killers has five long altcoin positions, approximately $90.79 marked notional.
Their combined entry-to-stop loss is approximately $8.38; marked value to the
same stops is approximately $14.58. These sums exclude fees, funding and slippage;
stop prices do not guarantee fills. The second number includes surrendering
current open gains. Positions and original exit orders are not changed.

Keep the existing measurement epochs distinct from historical dry-run lineage.
FundingFade/Keltner need exact-current-rule, cost-aware validation; OI needs a
price-only control; copiers need current-policy realized exits, including the
small-stake target grouping. Short Keltner remains a research redesign candidate.
No new directional strategy or parameter optimization was introduced here.

Before revisiting carry promotion, validate executable depth and per-leg timing,
actual fees/funding notional, same-base-quantity hedges and collateral recovery.
Do not lower entry thresholds or the return hurdle to force this replay to pass.
The existing preregistration contains the explicit correction amendment.
