# Crypto market-sentiment / social-intelligence aggregators: provider landscape (as of 2026-11-03)

Research date: 2026-11-03. Unless marked otherwise, vendor pages were fetched on this date. "Vendor-only" means the claim comes from the provider itself. "Secondary" means it comes from a third-party aggregator or a search snippet and was not confirmed on a primary page. Several vendor sites (CryptoPanic, Token Metrics, Velo, Messari/Blockworks pricing) are JavaScript-rendered, rate-limited (429) or blocked (403) for automated fetches. Those numbers are listed under Gaps and were not guessed.

## Q1. What does each provider measure, from which sources, and is it per-coin or market-wide?

### Takeaway
The landscape splits three ways. (a) Market-wide composite "fear and greed" gauges: Alternative.me, CMC, CFGI. Most of their weight is price, volatility and volume, so they carry little new information. (b) Per-coin social analytics: LunarCrush, Santiment, Elfa, Messari Sentiment, Augmento, Kaito, The TIE. These are mostly built on X/Twitter, with Reddit, Telegram, Bitcointalk, 4chan, YouTube or news added depending on the vendor. (c) Crowd-positioning proxies: Coinglass and Velo (OI, liquidations, long/short), CryptoQuant market data. Only (b), the social and news parts of the composites, and the CryptoPanic news feed actually add information beyond OHLCV and funding.

### Cited Findings

**Market-wide composites**
- Alternative.me Fear & Greed covers Bitcoin only, 0–100, updated daily. Weights: volatility 25% (current volatility and max drawdown vs 30/90-day averages), market momentum/volume 25%, social media 15% (Bitcoin hashtag activity on Twitter), surveys 15% (weekly strawpoll, **currently paused**), dominance 10%, Google Trends 10%. The page says its "reddit sentiment analysis is still not in the live index". About 60% of the weight (volatility, momentum, dominance) comes from price and market-cap data. — [Alternative.me F&G](https://alternative.me/crypto/fear-and-greed-index/)
- CFGI.io API v3 covers 595 assets (295 crypto tokens and 300 stocks) plus a `MARKET` crypto index and a `STOCK_MARKET` (S&P 500) index. The composite has 10 sub-signals, each normalized to 0–100: price, volatility, volume, impulse, technical, social, dominance, trends, whales, orders. Timeframes are 15m/1h/4h/1d lookbacks, recalculated about every 15 minutes. — [CFGI developer page](https://cfgi.io/developer/)
- CoinMarketCap has a "CMC Crypto Fear and Greed" index with Latest and Historical endpoints under Global Metrics. — [CMC API pricing](https://coinmarketcap.com/api/pricing/); [CMC Pro API reference](https://coinmarketcap.com/api/documentation/pro-api-reference/global-metrics). The CMC API section has no community-sentiment (vote) endpoint. It lists only "Community Trending Tokens" and "Community Trending Topics". — [CMC API pricing](https://coinmarketcap.com/api/pricing/)
- Glassnode Studio shows a Fear & Greed chart described as "an indicator from Alternative.me", plus a per-asset `FearGreedPit` variant. The methodology for the PIT variant was not retrievable. — [Glassnode Studio FearGreed](https://studio.glassnode.com/charts/indicators.FearGreed); [FearGreedPit](https://studio.glassnode.com/charts/indicators.FearGreedPit?a=BTC)

**Per-coin social analytics**
- LunarCrush: Galaxy Score is a proprietary score built from "technical indicators of price, average social sentiment, relative social activity" and how closely social indicators correlate with price and volume. It is partly price-derived. — [TradingView Galaxy Score support page](https://in.tradingview.com/support/solutions/43000739595-galaxy-score/); time-series docs via [lunarcrush-php SDK / lunarcrush.ai mirrors](https://packagist.org/packages/tigusigalpa/lunarcrush-php) (secondary). The definition of social dominance changed. In 2022 it was the coin's share of global social volume ([LunarCrush blog 2022](https://medium.com/lunarcrush/lunarcrush-api-v3-is-now-available-426148edb826)). Current docs describe it as "share of voice" relative to the asset's categories over a rolling 24h window (secondary, via search of lunarcrush.ai docs). Sources are reported as X, Reddit, YouTube, TikTok, Instagram and news. — [similarlabs.com](https://similarlabs.com/p/lunarcrush) (secondary, unverified)
- Santiment: social metrics include social volume, unique social volume, sentiment positive/negative/bullish/neutral/bearish, and sentiment balance v2, either totalled across sources or split by source for **Twitter, Reddit, Bitcointalk and 4chan**, plus Reddit "community social volume". — [Santiment PIT for social metrics](https://academy.santiment.net/metrics/details/point_in_time/). Santiment covers the top 3,000 assets by market cap and also offers on-chain metrics for about 13 chains (list as of February 2026). — [Santiment pricing](https://app.santiment.net/pricing)
- Elfa AI: core social data comes from **Twitter and Telegram** (trending tokens, top mentions, mention search, token news, "trending contract addresses on Twitter and Telegram"). — [Elfa pricing](https://docs.elfa.ai/get-started/pricing). API v2 offers chat, mentions/news, trending tokens/contracts and narratives. API v3 offers "events and storylines", call books and mindshare, accounts' calls/positions, and ranked accounts. "Auto" is a managed condition and trigger engine. — [Elfa docs](https://docs.elfa.ai/)
- Messari Sentiment API: `sentimentScore` (0–100) is "the difference between recent (24h) and baseline (20d) sentiment". Also `sentimentMomentumScore` (day-over-day change), positive/negative/neutral post % over 7 days, and `tweetVolume` (tweets over 7 days). Posts come from "high-mindshare users", so the data is X-centric. Reddit, Telegram and news are not mentioned. Endpoints: list, asset details, time series. — [Messari Sentiment docs](https://docs.messari.io/api-reference/endpoints/signal/sentiment/overview)
- Augmento: "93 sentiment topics" across X, Reddit and Bitcointalk, weighted equally (each source can be filtered). More than 25 assets. Collected hourly and consolidated daily. Single score from 0 to 1 (0.5 = neutral). — [augmento.ai](https://www.augmento.ai/)
- Kaito: token mindshare is "the number of tweets where a specific token is referenced… relative to the overall cryptocurrency market". This is from Kaito's API docs as indexed by search; the page now returns 404. — [Kaito Mindshare API (now 404)](https://kaito-ai.gitbook.io/product-docs/api/api-documents/mindshare-api)
- The TIE: the docs list `getquantsentiment` ("sentiment data (latest or historical) optimized for quantitative analysis"), "Historical Flat Files (Sentiment)", "Trending News" (articles with "25 or more tweets in the last 24 hours"), Trending News – Historical (tweet-count snapshots), and news metadata with AI summary and sentiment. "SigDev" is not mentioned. — [The TIE docs](https://docs.thetie.io/). The product is now sold as "Atlas" ("markets, derivatives, news, on-chain, developer, social, and sentiment data… built for institutions"). — [thetie.io](https://www.thetie.io/)
- Cookie DAO (Cookie3): a "mindshare" metric that tracks social volume against on-chain activity, aimed at AI agents. API access is gated by staking or locking COOKIE tokens. — [Bitget Academy](https://web3.bitget.cloud/en/academy/what-is-cookie-dao-the-crypto-data-engine-powering-ai-agent-analytics); [CMC AI explainer](https://coinmarketcap.com/cmc-ai/cookie/what-is/) (both secondary)
- CryptoPanic: a news aggregator with a JSON API of "recent posts and indicators". Its Enterprise tier is described as a "real time news API with sentiment data". — [CryptoPanic API about](https://cryptopanic.com/developers/api/about) (via search snippet; the page did not render for fetch)
- CryptoQuant: its only explicit sentiment metric is "Analyst Consensus", a daily −100…+100 index built from analyst posts over the last 30 days. — [CryptoQuant pricing](https://cryptoquant.com/pricing)
- Stocktwits: no crypto-specific sentiment endpoint found. The documented v2 API covers symbol, user and trending message streams. — [API Evangelist directory](https://providers.apievangelist.com/providers/stocktwits/) (secondary)

**Positioning proxies**
- Coinglass: 80–160+ API endpoints depending on plan, updated in ≤1 minute (derivatives positioning, OI, liquidations, long/short). — [Coinglass pricing](https://www.coinglass.com/pricing)
- Velo: its SDK covers "price OHLC candles to… historical open interest". The web app has OI, funding and liquidation alerts. 3,400+ symbols across Binance, Bybit, Coinbase and Hyperliquid. — [Velo docs](https://docs.velo.xyz/)

### Inferences
- For an operator whose OHLCV and funding edges were regime luck, the F&G composites (Alternative.me, CMC, CFGI) mostly re-encode price, volatility and volume. Only their social and trends sub-components are new information. CFGI exposes the sub-signals separately (the "fields" in its credit model), so the social sub-signal can likely be isolated. That is worth verifying before purchase.
- LunarCrush's Galaxy Score includes price technicals and a price-correlation term. Using it as a feature next to price risks double-counting. Raw social volume and sentiment are the cleaner inputs.
- Nearly every per-coin provider depends on X/Twitter. That makes X data access one shared single point of failure (see Q5).
- For a crash-news veto, the candidates with a news or event concept are Elfa v3 "events and storylines", The TIE Trending News, CryptoPanic, and Messari's sentimentScore (24h vs 20d, built for spike detection). The F&G indices are daily and lagging.

### Gaps
- CMC's composite F&G methodology was not fetched.
- LunarCrush's exact network list and current sentiment definition could not be retrieved from primary docs. The lunarcrush.ai pages returned "Limited data mode".
- Glassnode `FearGreedPit` methodology: not documented on the fetched pages.
- Sentora (ex-IntoTheBlock) social signals: no current product found (see Q5).
- Velo: no confirmed news or sentiment product.
- CryptoPanic vote/"panic score" field semantics were not verified on a primary page.

## Q2. How can each be consumed programmatically (API type, update frequency, rate limits, which tier unlocks API)?

### Takeaway
All of the serious providers have REST APIs. Santiment uses GraphQL with a Python SDK (sanpy). Elfa adds keyless pay-per-request over x402. LunarCrush, Kaito and Elfa now also sell MCP access. Live, unlagged data generally sits behind the mid tiers. Santiment's free and $49 Pro API tiers carry a **30-day lag** on restricted metrics, so they cannot drive a live veto. Elfa and CFGI are metered by credits, which suits a small bot polling a few coins.

### Cited Findings
- **LunarCrush:** every paid tier includes the API, and the lowest is Light: 10 req/min, 2,000/day. Medium: 100/min, 20,000/day. Heavy: 500/min, 100,000/day. "Limits are shared across the API, MCP, and CLI." Over-limit requests return 429 and are not billed. — [LunarCrush pricing](https://lunarcrush.com/pricing). Without a subscription, pages show "Limited data mode. Full metrics and data available with subscription or API credits". — [lunarcrush.ai](https://lunarcrush.ai/html/topic/$api3x). Time-series endpoint `/api4/public/topic/:topic/time-series/v2` with `bucket=hour|day`, `interval`/`start`/`end`, bearer-token auth. — [lunarcrush-php SDK](https://packagist.org/packages/tigusigalpa/lunarcrush-php) (secondary)
- **Santiment SanAPI** (GraphQL; every query counts as one call; per-minute, hour and month windows in UTC; 429 with `x-ratelimit-reset`; limits per account across all keys). — [SanAPI rate limits](https://academy.santiment.net/sanapi/rate-limits/). Limits by plan: Free 100/min, 500/h, 1,000/mo. Pro 100/min, 1,000/h, 5,000/mo. Max 100/min, 4,000/h, 80,000/mo. Business Pro 600/min, 30,000/h, 600,000/mo. Business Max 1,200/min, 60,000/h, 1,200,000/mo. — [SanAPI plans](https://academy.santiment.net/products-and-plans/sanapi-plans/). "Sanbase Max is the minimum plan required for accessing the real-time API data with no restrictions or time-lag." — [Santiment pricing](https://app.santiment.net/pricing). Some metrics are fully unrestricted on every plan, subject only to rate limits. Restrictions can be checked per metric with the `getAccessRestrictions` query. — [Santiment restrictions](https://academy.santiment.net/sanapi/historical-and-realtime-data-restrictions/). Python SDK: sanpy. — [PyPI sanpy](https://pypi.org/project/sanpy)
- **Santiment live-data caveat:** for social metrics, the default version "can still receive late data for up to 12 hours after a bar closes". Santiment advises excluding the last bar to get consistent values. — [Santiment restrictions](https://academy.santiment.net/sanapi/historical-and-realtime-data-restrictions/)
- **Elfa:** Free key gives 1,000 credits **in total** (not per month) at 60 RPM. PAYG is 60 RPM. Grow is 120 RPM. x402 pay-per-request runs at 1,000 RPM, paid in USDC on Base, Arbitrum, Polygon, Avalanche, BSC or Solana (or USDT on BSC), with no account needed. Requests returning `404 ERR_NO_RESULTS` are not charged (capped per wallet per hour). — [Elfa pricing](https://docs.elfa.ai/get-started/pricing). "Auto" provides a managed trigger pipeline for alerts and actions. — [Elfa docs](https://docs.elfa.ai/)
- **CFGI.io:** REST v3. Credit = field × token × value (e.g. 1 token × 4 fields = 4 credits). Webhooks cost 1 credit per field per reading. Max 1,200 rows per request. The keyless `/api/v3/coverage` endpoint is free. Per-minute rate limits are not stated. — [CFGI developer](https://cfgi.io/developer/)
- **Alternative.me:** `GET https://api.alternative.me/fng/`. `limit=0` returns all data. JSON or CSV. No key. — [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/). Verified 2026-11-03: a keyless call returned 3,194 rows, latest value 26 ("Fear"). — [api.alternative.me/fng/?limit=0](https://api.alternative.me/fng/?limit=0)
- **CMC:** `GET /v3/fear-and-greed/latest` and `/v3/fear-and-greed/historical`, 1 credit per call. Cache refreshes every 15 s, but values are daily (12am UTC). Added in API v2.0.10 on 14 Oct 2024. The latest endpoint is listed for Basic and up. Historical on Basic is confirmed only by a third-party connector page. — [CMC Pro API reference](https://coinmarketcap.com/api/documentation/pro-api-reference/global-metrics); [CMC changelog](https://coinmarketcap.com/api/documentation/changelog.md); [withone.ai connector](https://www.withone.ai/knowledge/coin-market-cap/conn_mod_def%3A%3AGMkK3lTnUwA%3A%3Ad_1N_se1R9CNs7d5XyZZ-w) (secondary). Basic plan: 15,000 credits/mo, 50 req/min. — [CMC API pricing](https://coinmarketcap.com/api/pricing/)
- **Coinglass:** Hobbyist 30 req/min, Startup 80, Standard 300, Professional 1,200. Updates ≤1 min. — [Coinglass pricing](https://www.coinglass.com/pricing)
- **CryptoQuant:** Basic free plan gives 10K API credits/mo at daily resolution. Advanced gives 300K at hourly and block level. Professional gives 500K and adds on-chain data, at 120 req/min. — [CryptoQuant pricing](https://cryptoquant.com/pricing)
- **CryptoPanic:** four API plans. Some tiers are rate-limited to 5 req/s, Enterprise to 10 req/s. One plan requires attribution "at the top of the news feed". — [CryptoPanic API about](https://cryptopanic.com/developers/api/about) (search snippet). A third-party wrapper names the plan segments developer, growth and enterprise, with search and content retrieval being Enterprise-only. — [cryptopanic-php](https://packagist.org/packages/tigusigalpa/cryptopanic-php) (secondary)
- **The TIE:** API docs with `getquantsentiment`, historical flat files and an MCP guide. — [The TIE docs](https://docs.thetie.io/)
- **Kaito:** "MCP access, included with all plans" (works with Cursor and Claude). API is "Contact Sales". — [Kaito Pro pricing](https://pro.kaito.ai/pricing)
- **Augmento:** "All plans include API access and CSV exports". Free users see delayed data. Paid tiers differ in recency, rate limits and commercial licensing. — [augmento.ai](https://www.augmento.ai/)
- **Velo:** HTTP API plus TypeScript SDK. — [Velo docs](https://docs.velo.xyz/). Python client `velodata`, latest 1.5.5, MIT-licensed, supports batched and streamed rows. — [PyPI velodata](https://pypi.org/project/velodata/)

### Inferences
- A practical live veto loop for a few-hundred-USD fleet polls every 5–15 minutes across about 10–30 pairs. That fits inside LunarCrush Light's 2,000/day only if requests are batched (e.g. a coins-list endpoint). It fits CFGI and Elfa if the field counts are kept small.
- Santiment's restricted social metrics cannot be used live below Max ($249/mo). Its free or Pro tier is still useful for **research**: one year of history, 30 days lagged.
- None of the vendors documented WebSocket streaming for sentiment on the pages fetched. Polling REST is the norm.

### Gaps
- Elfa credits-per-endpoint table: not fetched (docs.elfa.ai/get-started/rate-limits).
- LunarCrush update frequency for coin metrics: not found on primary pages.
- Which specific Santiment social metrics are restricted vs open: requires calling `getAccessRestrictions`, not done.
- CMC Basic access to the historical F&G endpoint is unconfirmed on a primary page.

## Q3. Historical depth, granularity, and point-in-time (PIT) vs revised history — backtest honesty

### Takeaway
**Santiment is the only social-sentiment vendor found that documents its revisions and sells a PIT version.** Its default social history is recomputed retroactively. The PIT version (`modern_pit:v1`) needs a **paid yearly Business Max** plan, and even then historical per-source metrics must be read from the non-PIT `modern:v1`. No other social or sentiment vendor (LunarCrush, Elfa, Messari, Augmento, Kaito, CFGI, Alternative.me, CMC) documents PIT or revision policy. Their history should be treated as possibly recomputed. Glassnode documents PIT for on-chain data (all metrics since July 2025). Free, deep history exists only for Alternative.me F&G (daily since 2018-02-01).

### Cited Findings
- **Santiment, on revisions:** "If we later recompute history for that period, the document is included and the original metric values change." Revisions come from late-arriving documents, scraper gaps and delayed ML processing. Santiment says this "can introduce look-ahead bias". PIT metrics store values "as they were known at the time". "`modern_pit:v1` requires a paid yearly Business Max plan." "Total metrics are always queried from `modern_pit:v1`." "Source metrics use `modern_pit:v1` for realtime data, but you must query `modern:v1` for historical data." The PIT start date is not stated. — [Santiment PIT](https://academy.santiment.net/metrics/details/point_in_time/)
- **Santiment versions:** original:v1 = 1.0 (what anonymous and low tiers get), modern:v1 = 2.0 (Business Pro or Business Max), modern_pit:v1 = 2.1. Most non-social metrics have only version 1.0. — [Santiment metric versions](https://academy.santiment.net/sanapi/metric-versions/) (via search summary); [SanAPI plans](https://academy.santiment.net/products-and-plans/sanapi-plans/)
- **Santiment history by plan (restricted metrics):** Free 1 year with a 30-day lag. Pro 1 year with a 30-day lag. Max 2 years, realtime. Business Pro 2 years. Business Max full. — [SanAPI plans](https://academy.santiment.net/products-and-plans/sanapi-plans/). Within an allowed window, the bar nearest `restrictedTo` may be partial. — [Santiment restrictions](https://academy.santiment.net/sanapi/historical-and-realtime-data-restrictions/)
- **LunarCrush:** "daily history back to January 2020", not tier-specific. — [LunarCrush pricing](https://lunarcrush.com/pricing). The time-series endpoint with `bucket=hour` reportedly returns "full historical data in hourly aggregation". — [lunarcrush-php / lunarcrush.ai mirrors](https://packagist.org/packages/tigusigalpa/lunarcrush-php) (secondary). These two statements conflict: the depth of hourly history is unclear. No PIT or revision statement was found.
- **Alternative.me (verified directly 2026-11-03):** 3,194 daily rows from **2018-02-01 to 2026-11-03**. Two gaps: 4 days after 2018-04-13 and 2 days after 2024-10-25. — [api.alternative.me/fng/?limit=0](https://api.alternative.me/fng/?limit=0). The methodology page says surveys are paused and Reddit is not in the live index. There is no changelog of component changes. — [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/)
- **CMC F&G:** CMC's public web chart endpoint (undocumented `data-api/v3/fear-greed/chart`) returned its first data point at timestamp 1687996800 = **2023-06-29**. Daily score with btcPrice and btcVolume. Verified by direct call 2026-11-03. — [CMC data-api chart](https://api.coinmarketcap.com/data-api/v3/fear-greed/chart?start=1&end=2000000000)
- **CFGI:** depth "varies by asset". Stored rows and date ranges per timeframe can be checked with the free `/api/v3/coverage` endpoint. Historical credits are cheaper (~$0.06 vs ~$0.22 per 1k on Starter). — [CFGI developer](https://cfgi.io/developer/)
- **Coinglass:** the 1-day interval gives all-time history on every plan. Lower tiers are limited to 6 days for 1-minute and 180 days for 1-hour data. Enterprise offers custom history and granularity. — [Coinglass pricing](https://www.coinglass.com/pricing)
- **Glassnode PIT:** `computed_at` has been recorded "since September 2024". Coverage expanded to "all metrics across the platform" from July 2025. Before that, only a specific list was covered (e.g. `mvrv_account_based_pit`, `sopr_account_based_pit`, `gini_pit`). Publication lag: median 15 s, p95 2:15, p99 9:42. — [Glassnode PIT docs](https://docs.glassnode.com/data/point-in-time-metrics)
- **Augmento:** "years of historical sentiment data", hourly collected and daily consolidated. No start date. — [augmento.ai](https://www.augmento.ai/)
- **The TIE:** historical sentiment time series and "Historical Flat Files (Sentiment)" exist. No depth stated. — [The TIE docs](https://docs.thetie.io/)
- **Messari Sentiment:** a "Sentiment Time Series" endpoint exists. No granularity or depth stated. — [Messari Sentiment docs](https://docs.messari.io/api-reference/endpoints/signal/sentiment/overview)
- **CryptoQuant:** Basic is daily resolution only. Advanced and above add hourly. Analyst Consensus full-history CSV/API is Premium-only. — [CryptoQuant pricing](https://cryptoquant.com/pricing)

### Inferences
- **Honest-backtest ranking for sentiment data:**
  1. Santiment PIT. Truly PIT, but costly (yearly Business Max) and partial (per-source history is non-PIT).
  2. Self-recorded forward data from any vendor. Polling live and storing the raw responses with your own `fetched_at` creates a PIT record from today. That is the honest default for cheap tiers.
  3. Vendor history, treated as "as recomputed today".
- Santiment documents that its own default history gets recomputed, and other vendors run similar ML pipelines (re-scored sentiment models, late scraping, bot filtering). So any LunarCrush, Elfa or Messari backtest on vendor history should be assumed to carry look-ahead bias until shown otherwise. LunarCrush's social-dominance definition changed between 2022 and current docs, which suggests methodology changes may be applied backward.
- Positioning data (Coinglass OI and liquidations, exchange-reported) is likely less revision-prone than ML sentiment. Lower-tier Coinglass still limits hourly history to 180 days, so daily all-time is the only deep series on cheap plans.
- Alternative.me's 8.75 years of daily data suits regime-level gating research, not intraday vetoes. Its component mix changed over time (surveys paused, Reddit never live), so early and late history are not like-for-like. The repo already consumes this index: `ft_userdata/user_data/strategies/*Viability.py` reference alternative.me/fear_greed (local grep, 2026-11-03).

### Gaps
- Start date of Santiment PIT data and price of Business Max: not found.
- Whether LunarCrush, Elfa, Messari, CFGI or Alternative.me ever back-revise published values: no documentation found.
- Elfa history depth: not stated on the pricing page.
- Kaito history depth: docs removed.

## Q4. Pricing (cheapest API-capable tier for a small trader) and license terms

### Takeaway
Free and keyless options: Alternative.me F&G, CMC Basic (F&G latest; historical probably included), CryptoQuant Basic (daily), and one-time trial credits at CFGI and Elfa (1,000 each). The cheapest **live** paid paths are about $27–$35/mo (CFGI Starter, Coinglass Hobbyist), $72–90/mo (LunarCrush Light), metered PAYG at Elfa ($0.0145/credit), and $249/mo (Santiment Max, the minimum for unlagged restricted metrics). Kaito ($833/mo annual Pro, API by quote), The TIE (institutional) and Elfa Grow ($870/mo) are out of budget. Licensing: CMC forbids redistribution as a standalone service. Coinglass's two cheapest tiers are "Personal use". Alternative.me requires attribution next to displayed data. LunarCrush allows commercial use "within the limits of your selected plan". None of the pages fetched explicitly prohibit automated trading on the data.

### Cited Findings

| Provider | Cheapest API-capable tier (USD) | Key limits on that tier | Next tier | Source |
|---|---|---|---|---|
| Alternative.me F&G | Free, keyless | Daily BTC index; attribution required; commercial OK with attribution next to data; no impersonation | — | [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/) |
| CMC (F&G) | Basic free | 15,000 credits/mo, 50/min; F&G = 1 credit/call | Builder $29/mo ($348/yr), 150k credits, 300/min | [CMC API pricing](https://coinmarketcap.com/api/pricing/) |
| CryptoQuant | Basic free | 10K credits/mo, daily resolution | Advanced $29/mo annual ($39 monthly), 300K credits, hourly; Professional $99 ($109 monthly), 500K + on-chain, 120/min; Premium $799 annual | [CryptoQuant pricing](https://cryptoquant.com/pricing) |
| CFGI.io | 1,000 free signup credits; "from $29 / 4 weeks" | Starter $319/yr, up to 100k credits per 4-week cycle (~$0.22/1k live, ~$0.06/1k historical); unused credits don't roll over; packs never expire | Growth $2,189/yr (1M credits); Scale $10,989/yr (10M) | [CFGI developer](https://cfgi.io/developer/) |
| Coinglass | Hobbyist $348/yr (≈$29/mo annual; page also shows $420/yr, apparently monthly billing ≈$35/mo) | 30 req/min, 80+ endpoints, **Personal use**; 1h history 180 days, 1m 6 days | Startup $79/mo annual (130+ endpoints, 80/min, personal); Standard $299 (commercial, 300/min) | [Coinglass pricing](https://www.coinglass.com/pricing) |
| Elfa AI | Free: 1,000 credits total; PAYG $0.0145/credit ($20 min top-up) | 60 RPM; x402 same price at 1,000 RPM | Grow $870/mo or $8,874/yr; 120k credits/mo; overage $0.009; 120 RPM | [Elfa pricing](https://docs.elfa.ai/get-started/pricing) |
| LunarCrush | Light $90/mo ($72/mo annual) | 10/min, 2,000/day shared across API/MCP/CLI; no free trial; payments "final and non-refundable" | Medium $300 ($240) 100/min, 20k/day; Heavy $900 ($720) | [LunarCrush pricing](https://lunarcrush.com/pricing) |
| Santiment | Free (1,000 calls/mo) / Pro $49/mo ($529/yr): 5,000 calls/mo, but **30-day lag, 1y history** on restricted metrics | 100/min | **Max $249/mo ($2,700/yr): 80k calls/mo, realtime, 2y history**; Business Pro/Max price not public; 10% annual discount, 20% off for SAN holders | [Santiment pricing](https://app.santiment.net/pricing); [SanAPI plans](https://academy.santiment.net/products-and-plans/sanapi-plans/) |
| Kaito | Enterprise single-seat $833/mo billed annually (MCP included) | API: "Contact Sales" | — | [Kaito Pro pricing](https://pro.kaito.ai/pricing) |
| Augmento | Free (delayed data) | Prices not listed; paid = real-time, higher limits, commercial license | — | [augmento.ai](https://www.augmento.ai/) |
| Cookie DAO | Token-gated (stake/lock COOKIE; one source says 10,000 COOKIE) | — | — | [Bitget Academy](https://web3.bitget.cloud/en/academy/what-is-cookie-dao-the-crypto-data-engine-powering-ai-agent-analytics) (secondary) |
| Velo | Unverified: "Developer $49/mo, 100k calls/mo, 7-day history"; "Professional $199/mo" | — | — | [scraped page](https://web-5gv.pages.dev/resources/velo-data) (low reliability) |

- CMC license: Basic through Professional include a "limited, non-exclusive and non-transferable" commercial license covering one product with up to 100k users. Data may not be redistributed or resold as a standalone service. The Builder card says "Personal projects" but also "Commercial use", which is internally inconsistent. — [CMC API pricing](https://coinmarketcap.com/api/pricing/)
- LunarCrush commercial use: "Yes, but within the limits of your selected plan". The page says nothing about trading use or redistribution. — [LunarCrush pricing](https://lunarcrush.com/pricing)
- Stocktwits terms (revised 10 July 2026) bar automated scraping and data extraction except through an approved API or with written authorization. — [Stocktwits terms](https://stocktwits.com/st/terms)
- An unverified single source lists older pricing of "Santiment Pro $49/mo (5,000 calls) and LunarCrush ~$72/mo". This matches current annual Light pricing. — [rfp.wiki](https://www.rfp.wiki/vendors/lunarcrush/santiment) (secondary)

### Inferences
- **Budget envelope for this operator** (a few hundred USD of capital): any data subscription above about $30/mo is large relative to capital and expected P&L. The defensible ladder:
  1. Free (Alternative.me, CMC Basic, CryptoQuant Basic, Elfa and CFGI trial credits).
  2. Metered or cheap (Elfa PAYG, CFGI Starter about $27/mo annualized, Coinglass Hobbyist).
  3. Only after a forward test shows value: LunarCrush Light or Santiment Max.
- Coinglass Hobbyist's "Personal use" license appears compatible with a personal trading bot, but redistribution (e.g. a public dashboard) would need Standard ($299). That is an inference; the full ToS was not read.
- No LLM API spend is needed to consume these feeds. If text summarization of news is wanted, the operator's Claude CLI route applies; no Anthropic API key needed.

### Gaps
- CryptoPanic plan prices (page JS-rendered; not retrieved).
- Messari API pricing after the Blockworks acquisition: messari.io/pricing now 302-redirects to app.blockworks.com/pricing, which returned 429.
- The TIE pricing: institutional, not public.
- Token Metrics API pricing: see Q5.
- Glassnode pricing and PIT tier: not fetched.
- Velo official pricing: not confirmed.
- Elfa credits per call: not fetched, so cost per poll is unknown.
- Full ToS texts (trading-use clauses) for LunarCrush, Santiment and Elfa were not read.

## Q5. Status in 2026: operating, acquired, deprecated, pricing changes

### Takeaway
2026 brought heavy consolidation and churn, so vendor survival risk is real:
- **Messari** was acquired by Blockworks (12 June 2026, ~$10M).
- **IntoTheBlock**'s legacy API was **sunset** when it relaunched as Sentora Research.
- **Token Metrics**' data API appears to be winding down (unconfirmed).
- **Kaito**'s public API docs are gone and it ended Yaps after X cut InfoFi API access on 15 Jan 2026.
- **The TIE** has repositioned to institutional Atlas and staking.

LunarCrush, Santiment, Elfa, CFGI, Alternative.me, CMC, Coinglass and CryptoQuant are operating with current pricing pages.

### Cited Findings
- **X policy shock, 15 Jan 2026:** X revoked API access for "InfoFi" apps that pay users for posting. X's head of product Nikita Bier: "They were already paying us millions for Enterprise API access… We don't want it." Kaito sunset Yaps and launched Kaito Studio. — [Decrypt](https://decrypt.co/354736/elon-musks-x-bans-access-infofi-crypto-projects-ai-slop-backlash); [Whale Alert story](https://whale-alert.io/stories/eb7aaf8a751c/Kaito-Shuts-Down-Yaps-After-X-Bans-Incentivized-Posts-Launches-Kaito-Studio); [Unchained](https://unchainedcrypto.com/x-bans-incentivized-posting-apps-prompting-shakeup-in-crypto-engagement-platforms/)
- **Kaito:** a third-party source says Kaito Pro and the API were unaffected by the X change ([Quasa.io](https://quasa.io/fr/video/kaito-le-bloomberg-de-lattention-crypto-qui-a-survecu-au-pivot-post-api-quasaio), secondary). However, the Mindshare API docs page now returns 404 and the docs sitemap lists no API pages. — [Kaito docs sitemap](https://kaito-ai.gitbook.io/product-docs/sitemap.md). Pricing page: Pro $833/mo annual, API "Contact Sales". — [Kaito Pro pricing](https://pro.kaito.ai/pricing)
- **Cookie DAO:** a CMC AI-generated page claims the same 15 Jan 2026 X revocation forced Cookie to shut down "Snaps". Unverified. — [CMC AI Cookie](https://coinmarketcap.com/cmc-ai/cookie/what-is/)
- **Messari → Blockworks:** acquisition announced 12 June 2026 for a little over $10M, versus a $300M 2022 valuation. — [Blockworks](https://blockworks.com/insights/blockworks-acquires-messari); [Cointelegraph](https://cointelegraph.com/news/blockworks-buys-rival-messari-at-fraction-of-2022-valuation?rand=50490); [The Defiant](https://thedefiant.io/news/infrastructure/blockworks-acquires-messari-crypto-data-consolidation). messari.io/pricing redirects (302) to app.blockworks.com/pricing (observed 2026-11-03). The Messari Sentiment API docs are still live. — [Messari Sentiment docs](https://docs.messari.io/api-reference/endpoints/signal/sentiment/overview)
- **Sentora (ex-IntoTheBlock):** "we've sunset the legacy web app, widgets, and API to relaunch as Sentora Research". Content is free. The page carries a 3 Nov 2026 date stamp, which may be auto-generated. No sunset date is given. — [Sentora](https://sentora.com/analytics-research)
- **Token Metrics:** developers.tokenmetrics.com now 301-redirects to a help article titled "Is the Token Metrics Data API still available" (observed 2026-11-03; the article body returned 403). — [Token Metrics help](https://help.tokenmetrics.com/en/articles/17030870-is-the-token-metrics-data-api-still-available). RootData reports that in H1 2026 Token Metrics announced it would sunset its analytics platform and API and move to on-chain indices and an AI daily brief. Single third-party source, unverified. — [RootData](https://www.rootdata.com/projects/detail/token%20metrics?k=OTA1NA%3D%3D). Earlier (June 2025): 21 endpoints, free tier, up to 500k calls/mo on VIP. — [Product Hunt](https://www.producthunt.com/products/token-metrics/launches)
- **The TIE:** current site lists Atlas, Data APIs, Terminal, Staking Rewards and staking infrastructure (via the Stakin acquisition). No SigDev branding. — [thetie.io](https://www.thetie.io/)
- **Augmento:** site live, "© 2026", owned by Postera Capital since 2020. — [augmento.ai](https://www.augmento.ai/); [Hedgeweek](https://www.hedgeweek.com/blockchain-specialist-postera-capital-acquires-augmento/)
- **LunarCrush:** pricing now Light $90 / Medium $300 / Heavy $900 per month, with API/MCP/CLI shared limits. — [LunarCrush pricing](https://lunarcrush.com/pricing)
- **Santiment:** pricing page live, with the chain list dated February 2026. — [Santiment pricing](https://app.santiment.net/pricing)
- **Stocktwits:** 2026 activity is equities and futures (CME futures data with Tradier execution, April 2026). No crypto sentiment API found. — [Pulse](https://www.pulse.bot/options-derivatives/news/stocktwits-to-offer-cme-futures-data-ddc83eb7-762d-4df2-9ccb-ea1650fbc96b)

### Inferences
- Sentiment data built on X is now priced against X's enterprise API, which X describes as costing "millions". Vendors either pass that cost on (LunarCrush's tiers now start at $90/mo; Elfa Grow is $870/mo) or degrade coverage. Any integration should be built vendor-agnostic, with a fallback to free composites.
- Given the Token Metrics, IntoTheBlock and Kaito-API churn, avoid annual prepayment. LunarCrush is non-refundable. Prefer monthly or metered plans until a forward test passes.

### Gaps
- Primary confirmation of Token Metrics' API status.
- Whether Kaito still sells API access, and at what price.
- Whether Elfa or LunarCrush lost or changed X data access after January 2026. Nothing found either way.
- Post-acquisition Messari pricing.

## Q6. Independent (non-vendor) evidence of predictive value

### Takeaway
No independent, peer-reviewed or practitioner backtest was found for any specific vendor signal (Galaxy Score, AltRank, Santiment sentiment, Elfa mindshare, Kaito mindshare, CFGI). The academic literature on crypto social sentiment in general is mixed: social volume tends to predict trading volume and volatility more reliably than returns. Directional gains are small and regime-dependent. Every "this signal predicts price" claim found was vendor-only or promotional.

### Cited Findings
- A search for independent Galaxy Score studies found none. TradingView's support page says a high score "often can signal potential for future growth", which is an assertion, not a test. — [TradingView Galaxy Score](https://in.tradingview.com/support/solutions/43000739595-galaxy-score/)
- A LASSO-VAR forecasting study of crypto log-returns with sentiment and attention variables found better directional accuracy but no RMSE improvement, and no "causality" from social sentiment to returns (summary level; paper not fully read). — [arXiv 2210.00883](https://export.arxiv.org/abs/2210.00883v1)
- An empirical study of Twitter, Telegram and Reddit posts (2017–2018) found post volumes may predict Bitcoin price moves but mainly predict trading volume (summary level). — [core.ac.uk PDF](https://core.ac.uk/download/493002704.pdf)
- No r/algotrading threads evaluating LunarCrush or Santiment were surfaced by search. Comparison pages found were vendor or affiliate content. — [rfp.wiki](https://www.rfp.wiki/vendors/lunarcrush/santiment); [Coinbound](https://coinbound.io/best-crypto-social-listening/)
- A 2026 "guide" claiming Augmento caught a March 2026 bottom reads as promotional and unsourced. Disregard. — [theledgermind.com](https://theledgermind.com/social-media-crypto-sentiment-tools/)
- Santiment itself acknowledges that its default social history is revised retroactively, so vendor-published backtests on that history can carry look-ahead bias. — [Santiment PIT](https://academy.santiment.net/metrics/details/point_in_time/)

### Inferences
- Under this operator's standards (DSR, preregistration, 1m-detail), a sentiment veto should be **preregistered and forward-tested** on self-recorded PIT data before any backtest on vendor history is trusted. The most plausible value is risk reduction: vetoing longs during crash-news or liquidation spikes, measured as drawdown and tail-loss reduction. Return alpha is less plausible.
- Volume-of-attention signals (spikes in mention counts, news-count bursts, liquidation bursts) have better support in the literature as **volatility and volume** predictors than as direction predictors. That fits a veto or position-size dampener rather than a standalone directional bot.

### Gaps
- No independent study of CFGI, Elfa, Kaito, Messari, Augmento or Coinglass-based crowding signals was found.
- A deeper literature search (e.g. SSRN, journals on liquidation cascades and long/short ratios) was out of the tool budget.

## Q7. Ranked shortlist: (1) market-wide risk/veto gate, (2) per-coin sentiment veto, (3) backtestable history

### Takeaway
Start free and metered. Use **Alternative.me F&G plus Coinglass liquidations/OI** for the market gate, **Elfa PAYG or LunarCrush Light** for per-coin vetoes (Santiment Max if budget allows), and **Santiment, Alternative.me and Coinglass daily** for history. Whatever is chosen, record live responses with your own timestamps from day one.

### Cited Findings
(Supporting facts are cited in Q1–Q6. Key sources: [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/), [Coinglass pricing](https://www.coinglass.com/pricing), [CFGI developer](https://cfgi.io/developer/), [Elfa pricing](https://docs.elfa.ai/get-started/pricing), [LunarCrush pricing](https://lunarcrush.com/pricing), [SanAPI plans](https://academy.santiment.net/products-and-plans/sanapi-plans/), [Santiment PIT](https://academy.santiment.net/metrics/details/point_in_time/), [Messari Sentiment docs](https://docs.messari.io/api-reference/endpoints/signal/sentiment/overview), [CMC API pricing](https://coinmarketcap.com/api/pricing/).)

### Inferences

**(1) Market-wide risk/veto gate**
1. **Alternative.me F&G.** Free, keyless, daily since 2018-02-01, already wired into the repo's Viability strategies. Weakness: daily, BTC-only, about 60% price-derived, so it acts as a regime filter, not a news detector.
2. **Coinglass Hobbyist (~$29–35/mo).** Liquidations, OI and long/short at ≤1-minute updates, so it catches crowding and liquidation cascades in near real time. Personal-use license fits a private bot.
3. **CFGI.io `MARKET` index (Starter ~$319/yr).** Recalculated every 15 minutes with 10 separable sub-signals, including social, whales and orders, so the price part can be stripped out. History depth is checkable for free before buying.
4. **Elfa v3 events/storylines (PAYG $0.0145/credit).** The only cheap, metered feed with an explicit "event" concept from X and Telegram, suited to a crash-news spike veto. Cost per call is unverified.
5. **CMC F&G (Basic free).** A second free composite for redundancy. History only from 2023-06-29.

**(2) Per-coin sentiment veto**
1. **Santiment Max ($249/mo).** Per-coin sentiment balance and social volume across Twitter, Reddit, Bitcointalk and 4chan for about 3,000 assets, with documented 12-hour late-data behaviour. Max is the minimum tier with no 30-day lag. Expensive for this capital.
2. **LunarCrush Light ($72–90/mo).** Per-coin social volume, sentiment and dominance across X, Reddit, YouTube, TikTok and news with an hourly time series. Use raw social fields, not the price-contaminated Galaxy Score. 2,000 calls/day is tight.
3. **Elfa PAYG.** Twitter+Telegram mentions, trending tokens and smart-account "calls" with no subscription. Best cost fit for a few pairs. History depth is undocumented.
4. **CFGI per-token (295 tokens, 15m).** Cheap per-coin composite with a separable social sub-signal. Mostly price-derived otherwise.
5. **Messari Sentiment API.** The 24h-vs-20d `sentimentScore` is purpose-built for spike detection. Pricing and roadmap are uncertain after the Blockworks takeover.

**(3) Backtestable history (honesty-weighted)**
1. **Santiment.** The only social vendor that documents revisions and sells true PIT (`modern_pit:v1`, yearly Business Max). Lower tiers give 1–2 years of history that is honestly labelled as revisable.
2. **Alternative.me F&G.** 3,194 free daily rows (2018-02-01 → 2026-11-03), verified. The revision policy is undocumented and the component mix changed over time.
3. **Coinglass.** All-time daily history on every plan for exchange-reported positioning data, which is likely less revision-prone than ML sentiment. Hourly history is capped at 180 days on cheap tiers.
4. **LunarCrush.** Daily since January 2020 with an hourly bucket option. There is no PIT statement and a changed social-dominance definition, so assume recomputed history.
5. **CFGI.** The free `/coverage` endpoint shows depth per asset and timeframe, and historical credits are cheap (~$0.06/1k on Starter). There is no PIT statement.
- Cross-cutting: for any cheap tier, the honest path is to **start logging live responses to the VPS now**, building a self-made PIT dataset for the preregistered forward test.

### Gaps
- The shortlist assumes Elfa's per-call credit cost is small. That needs checking against docs.elfa.ai/get-started/rate-limits and the endpoint credit table.
- CryptoPanic could rank in (1) as a cheap crash-news feed, but its prices and vote fields were not verified.
- The TIE and Kaito are excluded on price and opacity, not on evidence of signal quality.
