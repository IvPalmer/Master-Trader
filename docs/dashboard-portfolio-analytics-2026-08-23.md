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
- Profit factor, average win/loss, payoff, equity, and pair contribution use the dashboard's available recent-trade snapshots (currently up to 30 trades per bot). Closed-trade count and win rate come from each bot's aggregate Freqtrade statistics. If histories grow beyond the snapshot window, expanding the backend history endpoint is required for exact all-time portfolio curves and PF.

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

- Dashboard test suite: 22 tests passing.
- JavaScript syntax and repository whitespace checks passing.
- Repeated browser navigation without refresh: Overview → Funding Fade → Portfolio → Overview.
- Verified full-width equity, drawdown, and pair canvases after tab changes.
- Verified consolidated production values and account deduplication.
- Dashboard container healthy after deployment.
- Trading bot containers were not restarted; dashboard deployment used `--no-deps` and targeted only `ft-dashboard`.

## Deployment

Dashboard-only releases follow [ops/UPDATING-WITHOUT-BREAKING-BOTS.md](ops/UPDATING-WITHOUT-BREAKING-BOTS.md). The production checkout tracks `vps-deploy`; changes land on `main`, merge into `vps-deploy`, and rebuild only `ft-dashboard`.

Implementation commits:

- `4e96050` — selection-aware dashboard analytics.
- `df2105e` — unknown expectancy shown honestly without trade history.
- `4ef1f58` — consolidated Portfolio analytics.
- `0e941c8` — chart recreation after hidden-tab transitions.
