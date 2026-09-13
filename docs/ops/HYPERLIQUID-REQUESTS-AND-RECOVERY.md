# Hyperliquid request handling and uncertain exits

The production `hl-gateway` service is a fixed-upstream REST gateway on the private compose network. It holds no signing keys, exposes no host port, and never retries or caches exchange actions. Freqtrade still signs orders. Observation clients cannot submit actions. The old unmanaged `ft-short-keltner-hl` must remain stopped; preserve its data as historical evidence.

Hyperliquid documents 1200 weighted REST units per IP per minute, with separate websocket and address-action limits. The gateway limits fleet traffic to 900, caps background traffic at 600, and reserves capacity for live order/account management and exchange actions. It reserves response-dependent weights before dispatch and refunds unused weight after observation. Market data alone may be cached briefly; order, fill and account observations are never cached. A 429 imposes a shared ten-second cooldown. A request that cannot obtain budget within twelve seconds is rejected locally before forwarding. Upstream requests have a fifteen-second timeout and are never replayed. See [Hyperliquid's published limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

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
