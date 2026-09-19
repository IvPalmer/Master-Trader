# Dashboard chart components

TypeScript + pinned TradingView Lightweight Charts. The Python dashboard and its
existing Alpine state remain. Candle charts use bundled Lightweight Charts; accounting histories use D3 calendar-time SVG plots;
account and contribution comparisons use semantic HTML tables. ECharts is removed.

```
npm ci
npm run typecheck
npm run build
npx playwright install chromium
npm test
```

Tests use synthetic candles in a browser without an HTTP server or production
credentials. Locally `CHROME_CHANNEL=chrome npm test` uses installed Chrome.
CI checks that the committed static bundle matches its TypeScript source.

Price action uses visible candle scaling. All exits includes reported entry,
current price, bot stop and target levels. Target states come from the receiver
ledger; active is a ledger state, not a new exchange reconciliation. Persistent
text labels retain out-of-range exit visibility without forcing candles flat.
Closed trades do not display the legacy API's inferred historical stop as fact.
Polling preserves viewport, timeframe changes reset to the recent 90 bars, and
resizing/expanding retains the same chart instance.

The committed bundle allows the existing Python image to deploy without Node.
Keep CHART-NOTICE.txt, CHART-LICENSE.txt, attribution links and the chart logo.

Equity history contains realized values and optional labeled historical paper
lineage. Current equity is a separately labeled snapshot, not an interpolated
unrealized return path. Drawdown scales to the observations; historical reference
limits remain textual so they cannot compress small live movements.

Generate a self-contained synthetic preview without a local server:

```
node scripts/preview.cjs /tmp/master-trader-preview.html
```

The preview and browser suite share `tests/fixture.cjs`. No production API or
account data is used. The preview intercepts fetch and bundles all scripts/styles.
