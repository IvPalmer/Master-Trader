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
| OI failed open after feed failure and selected the oldest sample in a two-hour buffer | Failed polls clear the entry gate, values expire after 15 minutes, the nearest eligible 45-minute baseline is selected, and HTTP work runs in a long-lived background pool. The EMA50 price exit is independent of OI availability, so an OI outage cannot suppress risk reduction on an existing position. |
| Dry fallback wrote into live-named Hyperliquid databases | Compose now selects a distinct dry or live DB from the effective `DRY_RUN` value at container startup and rejects malformed values. Dry mode also disables on-exchange stops. |
| Receiver could enter after live mark crossed the posted SL | Mark price is required whenever a posted SL is required; an already-breached signal is skipped before any position row or order. |
| Minimum-margin and execution displacement could exceed the configured $1 stop-risk | Killers and Insiders now size only after the live mark and final order type are known: market entries use the mark, limit-in-zone entries use their submitted limit, and both include the adverse 0.98 stop-limit fill edge. A strategy `custom_stake_amount` callback returns zero when Freqtrade would otherwise raise the approved margin to the venue minimum. Too-small receiver stakes still fail closed as `risk_below_exchange_minimum`; cents are floored. |
| Concurrent opens could race past `max_open` | OPEN admission, capacity check, position insert, and force-enter response are serialized by an application lock. Close/update paths remain concurrent. |
| Blocking receiver HTTP in `custom_stoploss` | The tagged stop is immediately available and receiver refresh runs on a two-worker executor; the Freqtrade loop never waits for that HTTP call. |
| Receiver stop refresh ran every five-second strategy loop and cached every historical trade ID | Refreshes now have a 30-second TTL, in-flight deduplication, and a 128-entry oldest-first bound. |
| Blocking OI polling in `bot_loop_start` | Fetches are submitted asynchronously and harvested on later bot loops. |
| Binance stop-limit gap | The limit ratio is widened from 0.985 to 0.98 on all three spot bots. A stop-limit fill gap is an inherent residual risk of Binance spot/Freqtrade support and cannot be eliminated by configuration alone. |
| Dashboard used SQLite `immutable=1` on a database still receiving dry trades | Production now mounts a frozen, SQLite-consistent ShortKeltner pre-live snapshot. The dashboard's immutable read is therefore valid. |
| Lineage scaling could explode on a tiny transient live balance | Rebase is allowed only for finite starting capital of at least $1 and scale in 0.01–100x. Invalid input renders a flat cutover point with an explicit normalization status. |
| Governance did not record the live override | `ff-gate-v2-review` is closed with an explicit override resolution; the fleet-v2 registration records scope, authorization, superseded prohibitions, operating rules, and the next review. ROADMAP D1/T-010 are marked superseded. |
| Runtime registry still described receiver bots as awaiting wallets | `bots_config.json` now distinguishes autonomous `active` from receiver-managed `production_live` and records the actual V2 runtime strategy/config. |
| ShortKeltner strategy documentation still said dry-only | Its module documentation now describes the frozen dry lineage and bounded live epoch. |
| Production execution engine used mutable `freqtrade:stable` | All seven production Freqtrade services are pinned to the exact multi-architecture digest deployed and verified as Freqtrade 2026.7: `sha256:50720a4af314a812be2cfbf5cc6331c63e9332b06f3f4372241f54bc61a35486`. A restart can no longer change callback or execution semantics implicitly. |
| FundingFade V2 shared its DB and dashboard gates with 24 pre-V2 trades; Keltner's empty V2 DB still showed its pre-V2 lab baseline as current | FundingFade V2 writes to `tradesv3.live.FundingFadeV1.v2.sqlite`; the former 24-trade live DB is immutable lineage. Both FundingFade and Keltner expose `baseline_status=stale-pre-v2`, exclude those baselines from gates/expected deltas, and retain them only as labelled historical context. |
| Equity seed could precede older DB points in array order | Every bot uses a persistent epoch start, pre-epoch trades are filtered, and live equity points are returned chronologically. Restarts no longer redefine the analytical epoch. |
| The OI EMA50 dataframe exit could silently veto a valid entry on the same candle | The EMA50 condition now runs in `custom_exit`, which only evaluates existing positions. `populate_exit_trend` stays zero, while the exit remains independent of OI freshness. |
| Round-3 code changes were being measured under round-2 epoch timestamps | OITrendPullback, Killers, and Insiders now begin current measurement epochs at their exact executable-ready timestamps: `18:08:52.845Z`, `16:32:41.248Z`, and `16:32:41.684Z` respectively on 2026-08-24. The registration records the amendment and why these three curves were rebased. Every affected live DB was empty at cutover. |

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
- FundingFade V2 has a new live database. Its former 24-trade live database
  (2026-04-22 through 2026-07-31) is historical lineage only.
- Keltner's current live database had zero trades at the split. Its historical
  baseline is stale context, not data contamination and not an active gate.
- Explicit epoch timestamps, rather than the latest process restart time,
  bound live equity and measurement duration.
- OITrendPullback, Killers, and Insiders use a separate round-3 epoch because
  their executable exit/entry or risk-sizing contract changed on 2026-08-24.
  FundingFade, Keltner, and ShortKeltner retain their original cutovers.
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
- effective-entry and adverse stop-limit risk sizing for long and short orders;
- OI-independent EMA50 exits;
- Hyperliquid native-stop config;
- digest-pinned production images;
- dry/live DB isolation and OPEN serialization;
- bounded dashboard lineage normalization, stale-baseline exclusion, and
  chronological epoch filtering.

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

## Deployment receipt

Deployed on 2026-08-24 from `vps-deploy` merge `08d6409` (source commit
`a08c647`).

- Pre-deploy: all six bots stopped, all six reported zero open positions.
- ShortKeltner snapshot:
  `tradesv3.snapshot.ShortKeltnerV2HL.pre-live.sqlite`, SQLite
  `integrity_check: ok`.
- Local focused remediation suite: 19 passed.
- Full killers-receiver suite: 147 passed.
- Full dashboard suite: 25 passed.
- Production compose parse: passed locally and on the VPS.
- All six strategy/config pairs loaded in the Freqtrade image without
  `LOAD FAILED`.
- Effective production config: `dry_run=false` for all six; Binance for the
  three spot bots; Hyperliquid for the three futures bots.
- Effective stop config: limit + `stoploss_on_exchange=true` for all six;
  startup logs show ratio 0.98.
- Hyperliquid DB selection from PID 1 environment resolves to three distinct
  `tradesv3.live.*` paths.
- Receivers rebuilt and healthy with posted-SL mode enabled.
- OI feed after restart: `valid=8/8`; growth remains fail-closed until the
  45-minute baseline exists.
- Dashboard API after restart: six bots reachable, no poll errors, fleet status
  green.
- Final state: all six bots running live; zero positions opened during the
  maintenance window.

The repository's broad legacy `tests/` run also produced 145 passes and 11
skips, but 47 unrelated failures remain. They are concentrated in obsolete bot
expectations (for example retired BearCrash/Supertrend assertions), legacy
config filename assumptions for `.live.json` files, and laptop-only live
infrastructure checks (missing local containers, Grafana, symlink, and
`.env`). These are not counted as a green full-suite result and should be
cleaned up as a separate test-harness maintenance task.

Native Hyperliquid stop *configuration* is verified. Actual reduce-only stop
order placement cannot be evidenced with an empty position book; ROADMAP T-012
requires venue inspection after the first organic fill on each futures bot.

## Second-round closure receipt

The four residuals from the follow-up review were deployed on 2026-08-24 from
`vps-deploy` merge `01a917e` (source commit `52528e1`).

- Pre-deploy: all six Freqtrade books and both receiver state databases had
  zero open/requested positions.
- Tests: 150 killers-receiver, 27 dashboard, and 11 root remediation contracts
  passed (188 unique tests across the three suites).
- All six trading containers resolve to image ID
  `sha256:c19fdf05c17cf3ad11017aa3fae40ea2ea5f9de2e3580d11f5ce9ba157685cc8`,
  Freqtrade 2026.7, from the pinned repository digest recorded above.
- FundingFade V2 opened the new database with zero trades. The former database
  remains intact with 24 closed trades from 2026-04-22 through 2026-07-31 and
  zero open trades.
- Dashboard state is green: all six bots reachable and no poll errors.
  FundingFade and Keltner report `stale-pre-v2`, `baseline_comparable=false`,
  and no active baseline gates. FundingFade lineage exposes all 24 historical
  trades plus the `live + strategy v2` cutover.
- Effective configs report `dry_run=false` and exchange-resident stops for all
  six bots. Hyperliquid live DB paths remain distinct.
- Killers and Insiders receivers report healthy with
  `KILLERS_STOP_LIMIT_RATIO=0.98`; the deployed strategy exposes the minimum-
  stake rejection callback, 30-second stop refresh TTL, and 128-entry cache
  bound.
- The simultaneous restart briefly produced Hyperliquid public OHLCV 429s
  during startup. They cleared without intervention; the following 20-second
  clean window contained zero new 429s and every bot remained healthy. This was
  startup API contention, not a position or order failure.
- Final state: all six bots running live and zero open positions.

The remaining venue-only evidence item is unchanged: inspect the actual
reduce-only stop after the first organic Hyperliquid fill.

References: Freqtrade
[stop-loss documentation](https://docs.freqtrade.io/en/stable/stoploss/) and
[strategy callback documentation](https://www.freqtrade.io/en/stable/strategy-callbacks/).
