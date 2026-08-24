# Live fleet review remediation — 2026-08-24

## Decision and scope

This audit remediates the changes-required review of commits
`3249459..18aea83`. The six production bots were stopped before editing and
had zero open positions. Capital remained in the existing accounts; no funds
were moved by this remediation.

The operator explicitly authorized a bounded, maintainable live fleet and
rejected treating historical evaluations as immutable retirement decisions.
That authorization is now recorded in
`micro-live-fleet-v2-2026-08-23` in `ft_userdata/preregistrations.json`.
Historical adverse evidence remains part of the record; the new epoch is not a
claim of proven profitability.

## Findings and corrections

| Review finding | Resolution |
|---|---|
| FundingFade and Keltner `custom_exit` callbacks were disabled by `use_exit_signal = False` | Both strategies now set `use_exit_signal = True`. Their dataframe exit columns remain zero, so this only activates the intended time/reversion callbacks. |
| Hyperliquid positions had no exchange-resident stop | Killers, Insiders, and ShortKeltner configs now use Hyperliquid-supported limit stops on exchange, refreshed every 60 seconds with a 0.98 limit ratio. |
| Killers' initial -7% floor could not widen to the posted stop; relative cache accidentally trailed | The receiver embeds the absolute posted SL in `entry_tag`. `custom_stoploss` explicitly accepts `after_fill`, caches the absolute price, and recomputes the relative stop at every rate. Receiver refresh is asynchronous. The -7% value remains only a catastrophe fallback when no posted stop can be recovered. |
| OI failed open after feed failure and selected the oldest sample in a two-hour buffer | Failed polls clear the gate, values expire after 15 minutes, the nearest eligible 45-minute baseline is selected, and HTTP work runs in a long-lived background pool instead of the strategy loop. |
| Dry fallback wrote into live-named Hyperliquid databases | Compose now selects a distinct dry or live DB from the effective `DRY_RUN` value at container startup and rejects malformed values. Dry mode also disables on-exchange stops. |
| Receiver could enter after live mark crossed the posted SL | Mark price is required whenever a posted SL is required; an already-breached signal is skipped before any position row or order. |
| Minimum-margin clamp could exceed the configured $1 stop-risk | Sizing no longer rounds a too-small risk budget up to venue minimum. Such signals are skipped as `risk_below_exchange_minimum`. Stake cents are floored rather than rounded upward. |
| Concurrent opens could race past `max_open` | OPEN admission, capacity check, position insert, and force-enter response are serialized by an application lock. Close/update paths remain concurrent. |
| Blocking receiver HTTP in `custom_stoploss` | The tagged stop is immediately available and receiver refresh runs on a two-worker executor; the Freqtrade loop never waits for that HTTP call. |
| Blocking OI polling in `bot_loop_start` | Fetches are submitted asynchronously and harvested on later bot loops. |
| Binance stop-limit gap | The limit ratio is widened from 0.985 to 0.98 on all three spot bots. A stop-limit fill gap is an inherent residual risk of Binance spot/Freqtrade support and cannot be eliminated by configuration alone. |
| Dashboard used SQLite `immutable=1` on a database still receiving dry trades | Production now mounts a frozen, SQLite-consistent ShortKeltner pre-live snapshot. The dashboard's immutable read is therefore valid. |
| Lineage scaling could explode on a tiny transient live balance | Rebase is allowed only for finite starting capital of at least $1 and scale in 0.01–100x. Invalid input renders a flat cutover point with an explicit normalization status. |
| Governance did not record the live override | `ff-gate-v2-review` is closed with an explicit override resolution; the fleet-v2 registration records scope, authorization, superseded prohibitions, operating rules, and the next review. ROADMAP D1/T-010 are marked superseded. |
| Runtime registry still described receiver bots as awaiting wallets | `bots_config.json` now distinguishes autonomous `active` from receiver-managed `production_live` and records the actual V2 runtime strategy/config. |
| ShortKeltner strategy documentation still said dry-only | Its module documentation now describes the frozen dry lineage and bounded live epoch. |

## Stop architecture

Hyperliquid futures use three layers:

1. Native exchange limit stop managed by Freqtrade, surviving receiver/VPS loss.
2. Receiver posted-SL monitor and market force-exit fallback.
3. Strategy catastrophe stop when a posted stop is temporarily unavailable.

The native stop is limit-only because that is the order type supported by the
Freqtrade Hyperliquid futures integration. A gap can still leave a limit stop
unfilled; the receiver fallback reduces that risk while the service is healthy.
The first organic fill on each Hyperliquid bot must be inspected to verify the
actual reduce-only stop order exists at the venue.

## Data and epoch integrity

- Dry and live databases have separate filenames selected from effective
  runtime mode.
- ShortKeltner's historical curve is copied with SQLite backup semantics to
  `tradesv3.snapshot.ShortKeltnerV2HL.pre-live.sqlite`.
- Historical dry curves stop at the recorded transition timestamp.
- Live dollars are not added directly to historical simulated dollars; the
  visual lineage is explicitly rebased and bounded.
- Portfolio totals use only actual live account snapshots.

## Verification contract

The regression suite covers:

- exit-callback activation;
- OI freshness, invalidation, and nearest-baseline selection;
- absolute Killers stop behavior and explicit `after_fill`;
- posted-SL entry guard and stop propagation through `entry_tag`;
- no risk oversizing to venue minimum;
- Hyperliquid native-stop config;
- dry/live DB isolation and OPEN serialization;
- bounded dashboard lineage normalization.

Deployment is complete only after:

1. JSON/YAML/static validation passes.
2. Receiver and dashboard tests pass locally.
3. Strategy/config validation passes in the deployed Freqtrade image.
4. A consistent ShortKeltner history snapshot exists on the VPS.
5. Services restart healthy but bots remain stopped during inspection.
6. Effective config shows the intended venue, live DB, and stop-on-exchange.
7. Receivers resume only after their Freqtrade dependencies are healthy.
8. The full fleet is explicitly restarted and the dashboard reports all bots.

## Residual risks accepted for observation

- Exchange stop-limit orders can gap and remain unfilled.
- Small live samples cannot establish durable edge; maintenance decisions remain
  judgment calls informed by expectancy, drawdown, execution quality, and
  concentration.
- Copy-trader performance depends on channel latency and fill availability.
- Binance spot bots share wallet capital; the dashboard must continue to avoid
  counting that shared balance once per strategy.
- Hyperliquid account separation prevents position netting between bots but
  increases operational key/account surface.

References: Freqtrade
[stop-loss documentation](https://docs.freqtrade.io/en/stable/stoploss/) and
[strategy callback documentation](https://www.freqtrade.io/en/stable/strategy-callbacks/).
