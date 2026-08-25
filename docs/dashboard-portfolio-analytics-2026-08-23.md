# Dashboard portfolio analytics

Status: deployed to production on 2026-08-23.

The front-facing dashboard at `master-trader.grooveops.dev` has two complementary fleet surfaces:

- **Overview** is the operational command surface. It shows fleet health, every live bot in a comparison table, a selectable Fleet/bot performance workspace, current drawdown, pair contribution, expectancy, and recent trades.
- **Portfolio** is the consolidated analytical surface. It shows portfolio equity and drawdown, account and venue allocation, strategy and pair contribution, current exposure, payoff quality, and a cross-strategy trade ledger.

## Consolidation rules

- Live strategy count includes every bot with `dry_run === false`.
- Funded account count is deduplicated by `account_group`.
- Capital for strategies sharing an account is counted once. The Binance spot wallet therefore appears once even though Funding Fade, Keltner Bounce, and OI Trend Pullback share it.
- Dedicated Hyperliquid accounts are counted independently.
- Portfolio P&L is the sum of live-bot P&L.
- Portfolio equity sequences the available closed trades chronologically from deduplicated starting capital.
- Portfolio drawdown is calculated from the running peak of that consolidated realized-equity curve. It is distinct from the worst individual bot drawdown shown in bot detail.
- Strategy contribution sums P&L by bot. Pair contribution sums P&L for the same pair across bots.
- Profit factor, average win/loss, payoff, equity, and pair contribution use the complete active-epoch ledger. The backend requests close-time ordering and paginates against Freqtrade's `total_trades` field until it reaches each bot's epoch boundary; `trades_count` is only the current page length. The 30-row list in bot detail is display-only and never limits calculations. A partial fetch is discarded and the last complete ledger is retained.
- Every displayed bot statistic is recomputed from epoch trades. Freqtrade's lifetime `/profit` totals are not used for dashboard P&L, return, trade counts, win rate, profit factor, or drawdown.

## Live observability contract

Every bot publishes one explicit measurement contract in the Overview and bot detail surfaces:

- strategy/version and immutable epoch start;
- signal path health, last analysis or channel event, representative pair/timeframe, and the dominant entry gate;
- complete/incomplete epoch-ledger status;
- for Hyperliquid, native-stop verification state: `awaiting-first-fill`, `awaiting-stop`, `verified`, or `missing`.

Autonomous bots derive readiness from the latest analyzed Freqtrade dataframe for every whitelisted pair. OI Trend Pullback additionally exposes per-pair OI growth, baseline readiness, BTC trend state, and the dominant fleet gate. Copy-traders derive readiness from their receiver health and ingress audit trail; only actionable `open`, `close_full`, `close_partial`, and `signal_update` classifications count as signals. A stale feed, incomplete ledger, or missing Hyperliquid stop becomes a command-bar incident.

`verified` is evidence-based and position-specific: every filled open Hyperliquid position must expose an active stop order. Cancelled, rejected, expired, or closed stop records never qualify. A resting entry remains `awaiting-fill`; its 120-second placement window starts from `open_fill_timestamp`, not trade creation. One unprotected filled position makes the aggregate state `missing` even when another position is protected.

## Dry-run → live strategy lineage

Funding Fade, Keltner Bounce, Killers Scalp, Insiders Scalp, and Short Keltner
retain their prior closed-trade curves as historical strategy lineage. Funding
Fade's source is its now-frozen pre-V2 live DB; the others use their recorded
pre-live history. In each bot's selected Overview curve and detail tab, the
historical segment ends at its last known equity and the new live segment
begins at the same visual level. A dashed vertical marker names the
production/strategy cutover.

The joined curve is normalized, not an account statement. Live returns are
rebased onto the final dry-run equity so continuity and post-update slope can be
compared despite different account sizes. Bots without historical lineage still
render their active epoch as a dashed chart marker, so a forward-only strategy
keeps its version boundary. All fleet cards, portfolio capital,
P&L, exposure, and risk continue to use only actual live wallets and trades.
Open trades from retired dry-run databases are excluded. Historical databases
are frozen with SQLite backup semantics and mounted read-only into the dashboard
container; `immutable=1` is used only for those snapshots. If a validation
container keeps running in parallel, it writes to a different database and
cannot mutate the chart lineage.

Funding Fade and Keltner expose their prior lab baselines as
`stale-pre-v2`. The UI labels that status directly and never uses those numbers
for current-epoch expected return, PF/DD deltas, graduation gates, or incident
generation. Keltner's live DB was empty at cutover; its issue was stale
comparison metadata, not mixed trade data.

Live equity uses a persistent per-strategy epoch timestamp. Pre-epoch trade
rows are excluded and chart points are sorted chronologically, so restarting a
container cannot move the analytical start or place older closes after a newer
seed point.

Rebasing is refused when live starting capital is below $1, non-finite, or
would require a scale outside 0.01–100x. In that state the API reports
`normalized: false` and renders a flat cutover point instead of amplifying a
transient balance error.

## Chart lifecycle safeguard

ECharts must not be initialized while an Alpine `x-show` panel is hidden. A hidden initialization can create a full-width canvas whose internal coordinate grid remains only a few pixels wide; resizing that canvas alone does not reliably repair the plot.

The dashboard now:

1. Waits for Alpine to apply the destination tab layout.
2. Waits one animation frame so the browser has visible container dimensions.
3. Disposes chart instances created for the previous tab.
4. Recreates the active tab's charts against visible DOM nodes.
5. Explicitly resizes after asynchronous data completion and later container changes.
6. Detects DOM replacement and refuses to reuse a chart bound to a detached element.

This behavior applies to Overview, Portfolio, Trades, Validation, and per-bot detail navigation. A page refresh must not be required to recover chart geometry.

## Verification performed

- Dashboard test suite: 39 tests passing.
- JavaScript syntax and repository whitespace checks passing.
- Repeated browser navigation without refresh: Overview → Funding Fade → Portfolio → Overview.
- Verified full-width equity, drawdown, and pair canvases after tab changes.
- Verified consolidated production values and account deduplication.
- Dashboard container healthy after deployment.
- Trading bot containers were not restarted; dashboard deployment used `--no-deps` and targeted only `ft-dashboard`.
- Dry-run lineage tests verify closed-only history, bounded live rebasing,
  missing-database fallback, and invalid-capital fallback.

## Deployment

Dashboard-only releases follow [ops/UPDATING-WITHOUT-BREAKING-BOTS.md](ops/UPDATING-WITHOUT-BREAKING-BOTS.md). The production checkout tracks `vps-deploy`; changes land on `main`, merge into `vps-deploy`, and rebuild only `ft-dashboard`.

Implementation commits:

- `4e96050` — selection-aware dashboard analytics.
- `df2105e` — unknown expectancy shown honestly without trade history.
- `4ef1f58` — consolidated Portfolio analytics.
- `0e941c8` — chart recreation after hidden-tab transitions.
- `00c2f61` — normalized dry-run → live strategy lineage and cutover markers.
