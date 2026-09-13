# Hyperliquid request handling and uncertain exits

The production `hl-gateway` service is a fixed-upstream REST gateway on the private compose network. It holds no signing keys, exposes no host port, and never retries or caches exchange actions. Freqtrade still signs orders. Observation clients cannot submit actions. The old unmanaged `ft-short-keltner-hl` must remain stopped; preserve its data as historical evidence.

Hyperliquid documents 1200 weighted REST units per IP per minute, with separate websocket and address-action limits. The gateway limits fleet traffic to 900, caps background traffic at 600, and reserves capacity for live order/account management and exchange actions. It reserves response-dependent weights before dispatch and refunds unused weight after observation. Market data alone may be cached briefly; order, fill and account observations are never cached. A 429 imposes a shared ten-second cooldown. Live reads/actions wait at most twelve seconds; background history waits at most seventy seconds before a local rejection. Upstream requests have a fifteen-second timeout and are never replayed. See [Hyperliquid's published limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

All three managed Hyperliquid bots use the gateway for their sync and async CCXT REST clients. Websocket candle subscriptions are disabled so reconnect storms cannot bypass the shared budget. Freqtrade housekeeping runs every 30 seconds; receiver channel execution stays event-driven. Protecting live positions has priority over warming historical candles for dry-run observation. A saturated budget may delay observation data; such failures are visible rather than silently bypassing the limiter.

`GET /healthz` reports request outcomes, latency, queue depth and rolling weight without request bodies or wallet addresses. The exporter copies that health and actual account marks into `account_health.json`; the dashboard warns on recent request failures or missing/stale telemetry. A green dashboard is never justified by missing telemetry.

## Ambiguous order submission

A timeout, crash or unclassified server failure can occur after the exchange accepted an order and before Freqtrade recorded it. An empty Freqtrade order list therefore does **not** authorize a retry. The target stays `unknown`/`placing`, appears as a warning, and defers competing partial-close instructions. A uniquely identified new order/fill can resolve it automatically. Explicit validation rejections and confirmed pre-forward throttling remain distinct from ambiguous writes.

For an unresolved submission, read the receiver intent (`submitted_at`, `prior_order_ids`, price, amount), Freqtrade trade/orders, and the exchange's open orders and fills for that account. Match the exact order or filled quantity. Preserve stop orders. Back up both databases before any ledger correction. If a venue order exists but Freqtrade has no record, reconcile that orphan deliberately before authorizing any replacement. Do not delete uncertain rows or infer rejection merely from elapsed time. `rearm-killers-tp-ladders.sh` refuses uncertain or exchange-linked rows.

## Account equity and capital flows

The breaker and portfolio account total use each unique account once: Binance `/balance.total` from the declared representative, and Hyperliquid `clearinghouseState.marginSummary.accountValue`. Hyperliquid free capital is `withdrawable`, not Freqtrade's fractional-leverage stake estimate. Per-bot realized/unrealized P&L remains attribution data, not account equity.

`account_transfers.json` is the audit ledger for external deposits/withdrawals after the new valuation starts. Add a unique transfer ID, account, UTC observation time and signed amount after verifying the transaction. The breaker shifts its peak by the explicit cash flow, preserving trading drawdown. Trading P&L, fees and funding are not cash flows. Missing account data freezes valuation instead of inserting zero. The first migration preserves the prior measured dollar drawdown; it does not reset the peak to hide losses.

The 10% breaker halts new entries via `/stopentry`, leaving exit management running. Failed halt calls retry next cycle. A successful entry halt is not liquidation and does not promise that every position is closed. Resuming entries remains an operator action after reviewing the cause.

## Planned restart with resting exits

Production sets `cancel_open_orders_on_exit=false` so routine future restarts preserve resting take-profits. The initial migration from the old `true` setting needs special handling: pause receivers, capture and back up order/database state, stop the old Killers process without executing its cancellation cleanup, then recreate only that service with the new setting. Verify the exact exchange order IDs and five position quantities afterwards. The one-time abrupt stop relies on SQLite transaction recovery and exchange-resident stops, so it must never replace normal graceful restarts after the new setting is loaded. Never run a broad compose recreate or change volumes.

### 2026-09-13 completion and dashboard follow-up

The delayed rollout resumed at 15:14 UTC with a fresh backup at
`/home/ubuntu/master-trader/state/backups/fleet-completion-20260913T151409Z`.
All five Killers positions and all ten exchange exit order IDs survived the
one-time ungraceful restart. The old unmanaged Short container is retained,
stopped with restart disabled. Managed observation bots remain dry-run.

Runtime verification caught Freqtrade ignoring a JSON-valued uppercase
`CCXT_CONFIG` environment variable. Routing now uses nested environment leaves
(`CCXT_CONFIG__urls__api__public`, `private`, and lowercase `timeout`) and the
production verifier checks the parsed Freqtrade configuration. Background
history may queue for 70 seconds across a budget window; transport is bounded
to 15 seconds and Freqtrade waits up to 90. Exit reads/actions retain their
12-second queue deadline and reserved budget. Candle reservations use a bounded
requested interval rather than reserving 5,000 candles for every short request.

The Killers performance denominator is fixed at **98 USDC**: the exchange
non-funding ledger reports that amount transferred into perps at
`1787524880866`, with no subsequent ledger updates through this audit. Exchange
fills and funding queries from that transfer through the round-5 epoch returned
zero records. Freqtrade's reported starting capital (~73.15 during this audit)
varies with available collateral and must not normalize this performance curve.
The historical dry-run comparison is retained and explicitly labeled rebased;
it is not the current account balance. The solid realized series extends to
its latest observation, while a vertical dashed tip shows current open P&L.
There is no reconstructed intratrade P&L history. Actual account equity is
observed separately and can differ from trade P&L due to fees/funding and timing.

Trade-card candles now use their execution venue through the shared gateway,
including GRAM and other Hyperliquid markets unavailable on Binance. Cards wrap
at three/two/one columns and include loading, error, retry, and truncated-window
states. Stale bot measurements carry their last observed time.


The completion soak exposed hourly Killers restarts with SQLAlchemy pool
exhaustion while slow price/history requests held RPC resources. Live CCXT asset
context reads now receive exit-management priority. Background usage is capped
at 600 independently of live usage (combined reads <=850, all requests <=900),
so live traffic is not charged twice against the background allowance. Public
asset contexts cache for five seconds. Expired cached responses are pruned on
every request, with an 8 MiB response-byte cap and 128 entries.

Both pass-through copiers require only 10 startup candles, but CCXT's default
limit fetched 5,000 per pair repeatedly. Their five-minute OHLCV request limit
is now 100 through Freqtrade's `_ft_has_params` override. Other timeframes and
funding-history limits are unchanged, as are all signal/exit rules. This bounds
routine candle response cost near 22 units rather than 104 per pair. Account
membership failures retry on the next exporter cycle instead of waiting an hour.

The copier candle subscription list is BTC plus Freqtrade's automatically
included open positions. Source verification of the deployed Freqtrade RPC
shows force-entry admission checks the exchange's tradable markets and quote
currency, not the subscription whitelist. Neither copier reads indicators.
Thus newly signaled tradable pairs remain admissible; their open-position feeds
are added automatically. Keeping every possible signal pair subscribed caused
100 concurrent candle requests every five minutes across two copiers even after
limiting history depth. Autonomous strategy pairlists remain unchanged.
