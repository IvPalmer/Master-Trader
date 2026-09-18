# Position chart component

TypeScript + pinned TradingView Lightweight Charts. The Python dashboard and its
existing Alpine state remain; portfolio analysis continues to use ECharts.

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
