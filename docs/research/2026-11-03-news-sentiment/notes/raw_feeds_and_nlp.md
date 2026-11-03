# Raw-feed layer and text→signal processing for a crypto news/sentiment system (as of 2026-11-03)

Scope: raw data access (X/Twitter, crypto news, macro news, exchange announcements, other social) and the NLP layer that turns text into signals. Ready-made sentiment aggregators (LunarCrush, Santiment, etc.) are out of scope. All prices are as fetched or reported on 2026-11-03 unless another date is given. "Probe" means I called the public endpoint myself from the Mac on 2026-11-03 and recorded the response.

## X/Twitter access: official X API, third-party APIs, xAI Grok X Search

### Takeaway
The official X API is now pay-per-use only, with no subscription tiers. Reads cost $0.005 per post, deduplicated within a UTC day, with a 3M post-read monthly cap. Following 300–500 active accounts costs roughly $450–1,100/month, too much for a few-hundred-USD fleet. Third-party APIs are about 25–30x cheaper per tweet but break X's ToS and carry reliability risk. Grok `x_search` costs $5 per 1k posts fetched plus tokens, and only filters dates by calendar day. That makes it a coarse regime digest, not a real-time feed.

### Cited Findings
**Official X API (pay-per-use)**
- The X API "uses pay-per-usage pricing with no subscriptions". Credits are bought upfront and deducted per request, with no contracts or minimum spend. — [X docs pricing](https://docs.x.com/x-api/getting-started/pricing)
- Read prices per resource returned: Posts/Lists/Spaces/Communities/Notes $0.005; Users, DM events, Following/Followers $0.010; Likes/Mutes/Blocks $0.001; owned reads (your own data) $0.001. Counts: Recent $0.005, Counts: All $0.010; Trends $0.010. Writes: post create $0.015, or $0.200 with a URL. — [X docs pricing](https://docs.x.com/x-api/getting-started/pricing)
- Pay-per-usage is capped at 3 million post reads per monthly billing cycle. Higher volume needs Enterprise, which has no published rates. — [X docs pricing](https://docs.x.com/x-api/getting-started/pricing). Several third-party guides wrongly say 2M. — [WebSearch summary of opentweet / 1322.io guides](https://opentweet.io/x-api-pricing)
- Deduplication: a resource re-fetched within the same 24-hour UTC window (reset at midnight UTC) is not charged again. X calls this a "soft guarantee". — [X docs pricing](https://docs.x.com/x-api/getting-started/pricing); [OpenTweet, last checked against docs.x.com 2026-10-10](https://opentweet.io/x-api-pricing)
- Push alternative: Activity API webhook events are billed per event, e.g. `post.create` $0.005 and `follow.follow` $0.010. The pricing page does not describe a filtered stream. — [X docs pricing](https://docs.x.com/x-api/getting-started/pricing)
- Timeline: pay-per-use launched 2026-02-06. Legacy Basic moved to pay-per-use after 2026-06-01, and legacy Pro after 2026-09-01 (announced 2026-08-14). No free tier is listed. New accounts get $20 in credits after their first credit purchase (since 2026-10-02) plus a match of the first auto-recharge up to $50; credits expire after 3 months. An xAI credit rebate of 0–20% applies to cumulative X spend but only pays for xAI usage. — [OpenTweet, checked 2026-10-10](https://opentweet.io/x-api-pricing)
- OpenTweet sells a competing posting service, so its numbers should be checked against the X Developer Console. — [OpenTweet](https://opentweet.io/x-api-pricing)

**Third-party X data APIs**
- twitterapi.io: $0.15 per 1k tweets (15 credits per tweet; $1 = 100,000 credits). Profiles cost from $0.01 per 1k on batches of 100+ (18 credits each for 1–99). Every call has a minimum charge of $0.00015 (15 credits). A search returning 0–1 results costs $0.00015, 20 results cost $0.003. Free credits: up to $1 after a bot check, expiring in 31 days. Stream/monitor pricing, QPS limits and latency are not on the pricing page. — [twitterapi.io pricing](https://twitterapi.io/pricing)
- SocialData: $0.0002 per tweet ($0.20 per 1k) on endpoints such as Get User Tweets. User monitors are billed at a flat hourly rate per monitor, with tiers of $0.0042/h (501–1,000 monitors) and $0.0035/h (1,000+), about $2.99 and $2.49 per monitor per month. Search monitors have no hourly fee and cost $0.0002 per tweet delivered. The units in the tier table are ambiguous and the official monitoring page showed some prices as "TBD". — [SocialData pricing.md](https://socialdata.tools/pricing.md); [SocialData monitoring pricing](https://docs.socialdata.tools/monitoring/pricing)
- Apify has pay-per-result tweet scrapers, e.g. "kaitoeasyapi" at $0.25/1k tweets. — [Apify actor listing](https://apify.com/kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest?fpr=p2hrc6)
- Legal: in X Corp. v. Bright Data (N.D. Cal.), X's scraping claims were dismissed on 2024-05-09 as preempted by copyright law, because X only holds a non-exclusive licence to user content. — [CNBC](https://www.cnbc.com/2024/05/10/elon-musks-x-loses-lawsuit-against-bright-data-over-data-scraping.html); [MoFo](https://mofo.com/resources/insights/240604-california-federal-court-holds-x-s-claims). Commentators stress that the ruling is narrow and does not make scraping public data ToS-safe in general. X has since amended its ToS to prohibit facilitating or assisting violations. — [Zyte](https://www.zyte.com/blog/bright-data-x-lawsuit/); [NatLawReview](https://natlawreview.com/article/x-corp-loses-battle-over-public-data-access). A later ruling allowed X to revive parts of the case; I did not confirm its current posture. — [MediaPost](https://www.mediapost.com/publications/article/401510/x-corp-can-revive-scraping-battle-with-bright-dat.html)

**xAI Grok X Search (`x_search` server-side tool)**
- Parameters: `allowed_x_handles` or `excluded_x_handles` (max 20 each, 10 in the Vercel AI SDK, mutually exclusive), and `from_date`/`to_date` as `YYYY-MM-DD` only. Full date-times are not applied. Also `enable_image_understanding` and `enable_video_understanding`. — [xAI X Search docs](https://docs.x.ai/developers/tools/x-search)
- The model calls `x_keyword_search` (X advanced operators, sorted Top or Latest), `x_semantic_search`, `x_user_search` and `x_thread_fetch`, then "reads the posts it fetches and answers with citations". — [xAI X Search docs](https://docs.x.ai/developers/tools/x-search)
- Pricing: "$5 per 1k posts fetched and $10 per 1k user profiles fetched, in addition to token costs", in effect as of 2026-09-21. Counts include parent, quoted and thread posts, accumulate across searches in a request, and are not deduplicated. — [xAI X Search docs](https://docs.x.ai/developers/tools/x-search)
- Token prices per 1M tokens (prompt under 200k): grok-4.7/4.6/4.5 $2.00 in / $6.00 out (500k context); grok-4.3 and grok-4.20-0309 (reasoning, non-reasoning, multi-agent) $1.25 in / $2.50 out (1M context). — [xAI models page](https://docs.x.ai/developers/models)

### Inferences
- Official X cost for following accounts is roughly unique posts × $0.005, because same-day re-reads are deduplicated. Frequent polling of a List timeline therefore costs about the same as one read per new post. 300 accounts × ~10 posts/day ≈ 90k posts/month ≈ $450/month; 500 accounts × 15/day ≈ 225k ≈ $1,125/month. Cashtag or keyword search is open-ended and can burn the 3M cap quickly. Only ~100 hand-picked accounts (~$150/month) is defensible, and only if those accounts carry real signal.
- twitterapi.io for the same 400 accounts, polled with batched `from:a OR from:b …` advanced searches every ~2 minutes: about 120k tweets ($18) plus about 430k calls at the $0.00015 minimum (≤$65), so roughly $60–100/month. The per-call minimum dominates, so batch handles per query and widen the poll interval. My estimate; query-length limits per batch are unverified.
- SocialData user monitors at ~$2.5–3 per monitor-month make 300–500 accounts cost about $750–1,500/month. Its per-tweet polling ($0.20/1k) is the cheap path.
- Grok `x_search` suits periodic regime digests ("what is crypto X saying about SOL in the last day"). It does not suit per-post ingestion: the date filter is daily, the model decides how many posts to fetch (cost is not tightly cappable), and output is a model summary, not reproducible point-in-time data. Four digests a day at about 50 posts each ≈ 6k posts/month ≈ $30 plus tokens.
- ToS risk: third-party scrapers are a vendor-continuity risk (sudden breakage, account bans) more than a legal risk for a small end-user. Design the pipeline so the X source is swappable.

### Gaps
- Whether pay-per-use includes the filtered stream and full-archive search, and their rate limits. The pricing page lists neither.
- Whether the Activity API `post.create` webhook can subscribe to arbitrary third-party accounts, or only owned or authorised ones.
- Measured latency and uptime of twitterapi.io, SocialData or Apify actors. None was published, and I found no independent benchmark.

## Crypto news APIs and low-latency "news terminal" feeds

### Takeaway
CryptoPanic's free developer API is gone; access starts at $199/month for only 3,000 requests. Tree of Alpha (Tree News) is the de facto low-latency crypto terminal. Its paid tiers ($500–2,500/month) don't fit this budget, but it exposes an undocumented free public REST endpoint that returns the last ~4 days of X posts, blogs and exchange announcements with ticker suggestions, which makes it the best free aggregator found. Publisher RSS (CoinDesk, The Block, Decrypt, Blockworks, Cointelegraph) is free and works.

### Cited Findings
**CryptoPanic**
- The live API only accepts plan paths `growth`, `growth_weekly` and `enterprise` (an unknown path returns "Valid paths are /api/{growth|growth_weekly|enterprise}/v2/{posts|portfolio|status}/"), so there is no free developer path. — Probe of [cryptopanic.com/api/developer/v2/posts/](https://cryptopanic.com/api/developer/v2/posts/?public=true), 2026-11-03
- Growth is $199/month ($179/month billed annually) for 3,000 requests/month with real-time news. History is 1 year per one listing and 1 month per the fxpanic.com docs mirror. Growth weekly is $50/week for 600 requests, per week or per month depending on the source. Enterprise starts at $899/month. One review says the free developer plan ended on 2026-04-01. — [anygen.io review](https://www.anygen.io/showcase/cryptopanic/index.html); [fxpanic.com docs mirror](https://fxpanic.com/developers/api/about); [eakdigital](https://eakdigital.com/top-10-crypto-news-apis-real-time-data-for-trading/). Official pages are JS-rendered and could not be fetched, so treat as secondary.
- An older official description (undated) mentions a free API at 5 req/s with "real time news API with sentiment data". This is superseded by the probe above. — [CryptoPanic API about](https://cryptopanic.com/developers/api/about)

**CoinDesk Data (formerly CCData/CryptoCompare) news API**
- CoinDesk Data retired its free API tier (sources give 2026-04-17 and 2026-05-21 as the cutoff) and removed self-serve pricing. All paid plans, which include the News API, now go through sales. — [CoinMarketCap Academy comparison](https://coinmarketcap.com/api/resources/coindesk-api-alternatives-7-crypto-data-feeds-compared-in-2026); [CoinGecko learn](https://www.coingecko.com/learn/coindesk-api-alternatives). Both are competitor-written.

**Tree of Alpha / Tree News**
- Paid tiers: SPROUT $500/month (+10 Twitter accounts, +5 Telegram channels, subscriber Discord). SAPLING $2,500/month (+500 Twitter accounts, +20 Telegram channels, Advanced Sources, Exchange Announcements WebSocket, Tree Terminal). Both list "0 delay on all Blogs". Exchange announcements are relayed "through a dedicated Websocket based in Japan". Coverage is "1150+" sources and "2300+" Twitter accounts. No numeric latency is published. — [treeofalpha.com](https://www.treeofalpha.com/)
- Endpoints: main WebSocket `wss://news.treeofalpha.com/ws` (Twitter, blogs, Telegram, major announcements) and a low-latency Tokyo endpoint `ws://tokyo.treeofalpha.com:5124` for Binance/Bybit listing alerts, which needs a subscriber tier and an API key. CubeTerminal backfills gaps from Tree's "public REST endpoint" and marks those items "late". — [CubeTerminal TreeNews docs](https://www.cube-terminal.com/docs/news-sources/treenews)
- Public REST `GET https://news.treeofalpha.com/api/news?limit=2000` returned 2,000 items spanning 2026-10-30 22:57 to 2026-11-03 19:38 UTC (~4 days), no key needed. Fields: `_id, title, source, url, time (ms), kind, importance, venue, mainStock, suggestions, icon, image, info`. Source mix: Twitter 1,269; Blogs 684; Terminal 12; Bithumb 9; usGov 6; Bloomberg 6; Binance EN 6; Upbit 5. `suggestions` maps text to coins and exchange symbols, e.g. `{"coin":"TRUMP","symbols":[binance-futures TRUMPUSDT, binance TRUMPUSDT, bybit-perps TRUMPUSDT]}`. — Probe of [news.treeofalpha.com/api/news](https://news.treeofalpha.com/api/news?limit=2), 2026-11-03
- An unofficial JS WebSocket client exists (`@iam4x/treenews`), last pushed March 2023. — [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Fiam4x%2Ftreenews)

**Phoenix News, BWEnews and others**
- PhoenixNews.io is described by a directory page as aggregating 1,500+ sources, with a free API tier and Pro at $49/month. The listing is unverified and gives no latency. — [web-5gv directory](https://web-5gv.pages.dev/resources/phoenix-news)
- Benzinga Crypto News API offers REST, WebSocket and RSS, publishes 20–50 full crypto articles and 30–60 real-time headlines daily, and is priced through sales. — [Benzinga](https://www.benzinga.com/apis/cloud-product/crypto-news-api)
- Third-party listing-only WebSocket feeds exist, e.g. cryptolisting.ws, with pricing via Telegram. — [cryptolistingws docs](https://cryptolistingws.gitbook.io/docs/introduction.md)

**Publisher RSS**
- All returned HTTP 200 with valid feeds on 2026-11-03: CoinDesk `https://www.coindesk.com/arc/outboundfeeds/rss/` (0.47 s), The Block `https://www.theblock.co/rss.xml`, Decrypt `https://decrypt.co/feed`, Blockworks `https://blockworks.co/feed`, Cointelegraph `https://cointelegraph.com/rss`, and Fed press releases `https://www.federalreserve.gov/feeds/press_all.xml`. — Probe of [CoinDesk RSS](https://www.coindesk.com/arc/outboundfeeds/rss/), [The Block RSS](https://www.theblock.co/rss.xml), [Decrypt](https://decrypt.co/feed), [Blockworks](https://blockworks.co/feed), [Cointelegraph](https://cointelegraph.com/rss), [Fed](https://www.federalreserve.gov/feeds/press_all.xml)

### Inferences
- CryptoPanic Growth's 3,000 requests/month is about one poll every 15 minutes. At $199/month it is poor value against free Tree REST plus RSS. Its remaining edge is community votes and "important"/"bullish"/"bearish" flags, whose current API exposure I could not confirm.
- Tree's free REST already contains its curated X list (~1,269 tweets in ~4 days), so it partly substitutes for a paid X API for the "key crypto accounts" use case at $0. It is undocumented, though, and could be rate-limited or withdrawn. Archive every item locally, deduplicated on `_id`, so that point-in-time history builds up from day one.
- Free REST latency versus the paid WebSocket is unknown. Treat the REST feed as "minutes", not "seconds".

### Gaps
- BWEnews: I found no reliable source on its API, WebSocket, pricing or latency.
- Messari news API: not researched; tier and price unknown.
- Tree News free-tier delay, WebSocket access without a subscription, and Tree REST rate limits are not documented.
- Phoenix News latency and price could not be verified from a primary source.

## General / macro market news and economic calendars

### Takeaway
For macro context a retail bot does not need a paid news wire. The Fed RSS, the free ForexFactory/faireconomy weekly calendar JSON and GDELT (free, 15-minute cadence) cover FOMC/CPI/NFP timing and regime shocks. Marketaux ($0–49/month) is the cheapest entity-tagged news API. NewsAPI's free tier is dev-only with a 24 h delay, so it's useless live, and its real-time tier costs $449/month.

### Cited Findings
- NewsAPI.org: Developer $0, 24-hour article delay, 1 month of history, 100 requests/day, development only (no staging/production). Business $449/month, real-time, 5 years of history, 250k requests/month. Advanced $1,749/month, 2M requests/month, 99.95% SLA. — [NewsAPI pricing](https://newsapi.org/pricing)
- Marketaux: Free 100 requests/day at 3 articles per request; Basic $29/month (2,500/day, 20 articles); Standard $49 (10,000/day, 50 articles); Pro $99 (25,000/day, 100 articles); 20% off yearly. The pricing page doesn't cover sentiment fields, crypto coverage or history depth. — [Marketaux pricing](https://www.marketaux.com/pricing)
- GDELT 2.0 updates every 15 minutes. — [GDELT blog](https://blog.gdeltproject.org/gdelt-3-0-coming-soon/). The DOC 2.0 API is free and keyless, covers a rolling 3-month window, returns max 250 records per request and is limited to about 1 request per 5 s. Longer history is in the raw files or BigQuery. — [py-gdelt data sources](https://rbozydar.github.io/py-gdelt/getting-started/data-sources). The live API's own response says "Please limit requests to one every 5 seconds" and steers heavy users to its ngrams dataset. — Probe of [api.gdeltproject.org DOC API](https://api.gdeltproject.org/api/v2/doc/doc?query=bitcoin&mode=artlist&maxrecords=2&format=json&timespan=1h), 2026-11-03
- Finnhub: one July 2026 third-party summary puts the free tier at ~60 calls/min for personal, non-commercial use, including company news, and Premium at about $100–500+/month. Other sources say 30 calls/s. Economic-calendar tier is unconfirmed. — [apicostcalc Finnhub](https://apicostcalc.com/finnhub.html); [GitHub wiki](https://github.com/yyordanov-tradu/stock-scanner-mcp/wiki/API-Keys-&-Rate-Limits)
- Massive (Polygon.io rebranded 2025-10-30) sells Benzinga news as add-on "expansions" from $99/month on top of a base plan. Benzinga News v1 is sunset; use v2. — [Massive Benzinga partnership](https://ny5.massive.com/blog/benzingadata-partnership); [Massive news API blog](https://ny5.massive.com/blog/new-and-improved-financial-news-api); [qveris pricing guide](https://api.qveris.ai/guides/polygon-pricing-optimized)
- Economic calendar: `https://nfs.faireconomy.media/ff_calendar_thisweek.json` returned HTTP 200 with entries of the form `{title, country, date (ISO with offset), impact (High/Medium/Low/Holiday), forecast, previous}`. — Probe of [faireconomy FF calendar](https://nfs.faireconomy.media/ff_calendar_thisweek.json), 2026-11-03. It covers this week (optionally next). Sources disagree on whether actuals are published. Commercial terms are unclear. — [Apify FF wrapper](https://apify.com/scrapemint/forexfactory-economic-calendar); [qveris guide](https://qveris.ai/guides/free-economic-calendar-api/)
- Alpha Vantage lists "News & Sentiments", CPI and Federal Funds Rate endpoints. Premium plans run 150–1,200 requests/min. — [Alpha Vantage docs](https://www.alphavantage.co/documentation/)

### Inferences
- For entry vetoes, the useful macro signal is "is a high-impact US event within ±N minutes" (calendar) plus "is there a shock headline" (Fed RSS, GDELT/Marketaux spike). Both are free or under $50/month. Paid wires (Benzinga, NewsAPI Business) only pay off if you trade the headline itself, which this setup cannot do (see the latency section).
- Pull the calendar weekly into a local table. Event times are known in advance, so a pre-event entry blackout is fully deterministic and backtestable.

### Gaps
- Alpha Vantage NEWS_SENTIMENT free daily limit, history start date and crypto ticker coverage: the docs page was too long to read the relevant section.
- Finnhub's official free limits and whether the economic calendar is premium: the pricing page did not render.
- Whether the faireconomy feed publishes actuals, and its ToS for automated use.

## Exchange announcement feeds (Binance, Coinbase, Upbit, Bithumb, OKX, Hyperliquid) and listing dynamics

### Takeaway
Every major venue exposes announcements through a public (often undocumented) JSON endpoint that can be polled for free. Probes confirmed Binance CMS, OKX v5, Upbit api-manager, Hyperliquid `meta` diff and Coinbase products diff. These endpoints also hold timestamped history for event backtests. Listing pumps play out over 1–4 minutes or faster and are contested by sub-second terminals, and the Coinbase effect is on average muted. For a retail bot these feeds are worth more as delisting/risk vetoes than as entry triggers.

### Cited Findings
- **Binance**: `GET https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=N&catalogId=48` returns the "New Cryptocurrency Listing" catalog: total 2,292 articles, each with `id, code, title, releaseDate (ms)`. The latest was "Binance Will List Predict (PREDICT) with Seed Tag Applied". `catalogId=161` is "Delisting" (total 446). — Probe of [Binance CMS listing catalog](https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=2&catalogId=48), 2026-11-03
- A Binance developer-forum reply says bapi endpoints "are not public" and not recommended. The new-listing page is CloudFront-cached for ~30 s. Polling `exchangeInfo` only reveals a listing when trading goes live, not at announcement. — [Binance dev forum](https://dev.binance.vision/t/coin-listing-announcement-information/15081)
- **OKX**: `GET https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings` is public and returns `{annType, title, url, pTime, businessPTime}`. — Probe of [OKX announcements](https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings), 2026-11-03; types are listed via `/api/v5/support/announcement-types`, including `announcements-delistings`. — [rust-okx source](https://docs.rs/crate/rust-okx/0.6.3/source/src/api/support/api.rs). OKX delisting notices carry the off time in prose only. — [Apify listings tracker](https://apify.com/scrapemint/crypto-new-listings-tracker.md)
- **Upbit**: `GET https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=N&category=trade` returned 806 notices, each with `listed_at, first_listed_at (KST), id, title, category`. Examples: "닐리온(NIL) KRW 마켓 디지털 자산 추가" (KRW market addition, 2026-10-27 16:30 KST) and a BLUR trading-support termination. — Probe of [Upbit announcements](https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=2&category=trade), 2026-11-03
- **Hyperliquid**: `POST https://api.hyperliquid.xyz/info {"type":"meta"}` returns the perp universe: 235 assets, the last three being PONS, USELESS, XTEN. — Probe of [Hyperliquid info API](https://api.hyperliquid.xyz/info), 2026-11-03. `perpDexs` lists HIP-3 builder DEXes, which are queried via `meta` with `dex`. — [GoldRush perpDexs docs](https://goldrush.dev/docs/api-reference/hyperliquid-info/perp-dexs.md)
- **Coinbase**: `GET https://api.exchange.coinbase.com/products` returned 845 products and can be diffed for new markets. — Probe of [Coinbase Exchange products](https://api.exchange.coinbase.com/products), 2026-11-03
- **Tree of Alpha** aggregates exchange notices: its public REST feed included Bithumb (9), Binance EN (6) and Upbit (5) items within 4 days. — Probe of [Tree REST](https://news.treeofalpha.com/api/news?limit=2)
- Listing dynamics: a 2019 event study of 327 listings (180 coins, 22 exchanges) found positive pre-listing abnormal returns that often fade after listing. — [Blockchain Research Lab WP](https://www.blockchainresearchlab.org/wp-content/uploads/2019/10/Exploring-Market-Reactions-to-Exchange-Listings-of-Cryptocurrencies-BRL-working-paper3.pdf). Coin Metrics found the "Coinbase effect" fairly muted, with average/median returns of about −1% to +14% over a ±10-day window. — [Cointelegraph on Coin Metrics](https://cointelegraph.com/news/coinmetrics-finds-the-coinbase-effect-is-actually-pretty-lame). 2025 Coinbase roadmap additions produced spikes such as TOSHI ~+70%, Fartcoin ~+14% and TON/XPL +3%/+5%, often short-lived. — [Yellow](https://yellow.com/news/fartcoin-and-subsquid-hit-coinbases-roadmap-price-surge-follows-new-listing-announcement); [CCPress](https://theccpress.com/toncoin-plasma-coinbase-listing-announcement/amp)
- Upbit: a 2021 ALGO listing pumped to its top in 1–4 minutes, and 4Pillars argues the Upbit listing pump is fading as listings become frequent. — [4Pillars](https://research.4pillars.io/en/data/content/the-dying-upbit-listing-pump). A retail sniper on r/algotradingcrypto reports being consistently slower than Telegram alert channels. — [r/algotradingcrypto thread](https://redlib.hbubli.cc/r/algotradingcrypto/comments/1ktgys6/algo_crypto_sniping)
- A vendor claims lagged venues catch up within ~10–30 s after a Tier-1 listing. This is promotional and unverified. — [secret-terminal blog](https://secret-terminal.com/en/blog/how-a-crypto-listing-affects-price-a-phase-by-phase-breakdown-2026-en)

### Inferences
- Poll each venue every 15–60 s with backoff, which is free. The Binance CDN cache (~30 s) and terminal competition (dedicated Japan WebSocket) mean a VPS poller will typically see a listing seconds to tens of seconds after the fastest players. That is too late to capture the first leg of a pump, but fine for:
  - vetoing or exiting a coin on a delisting notice (Binance catalog 161, OKX delistings, Upbit "거래지원 종료"),
  - flagging an "event-driven coin" so mean-reversion bots stay out for N hours,
  - detecting new Hyperliquid perps to add to or exclude from pairlists.
- These endpoints keep full timestamped archives (Binance 2,292 listings, Upbit 806 notices), which makes them good free point-in-time datasets for testing "listing/delisting → N-hour drift" before building anything live.
- They are undocumented and unsupported, so they can break silently. Monitor freshness (e.g. alert if no new Binance article in 7 days).

### Gaps
- Bithumb announcement endpoint: not probed.
- Coinbase announcement/roadmap feed: no official API found beyond the products diff and the @CoinbaseMarkets / blog channels; not verified.
- Second-level measured latency of Binance CMS versus Tree's Tokyo WebSocket: no public measurement found.

## Reddit, Farcaster, YouTube, Google Trends

### Takeaway
All four are secondary for a crypto veto. Reddit's free OAuth tier (100 QPM, non-commercial, approval required) is usable for a few subreddits. Farcaster via Neynar is cheap ($0–49/month). Google Trends has no generally available API (alpha only). YouTube was not researched.

### Cited Findings
- Reddit: free limit of 100 queries/min per OAuth client ID, averaged over 10 minutes (10 QPM unauthenticated), non-commercial. The Responsible Builder Policy requires an access request and explicit approval, reportedly taking 2–4 weeks. Commercial pricing is negotiated, and the often-quoted 2023 figure (~$12k/year minimum, $0.24/1k calls) is not on Reddit's current terms. — [WebSearch summary of octolens, apiserpent, socialcrawl](https://octolens.com/blog/reddit-api-pricing); [apiserpent free Reddit API](https://apiserpent.com/blog/free-reddit-api). One vendor claims the free tier ends March 2027; unverified. — [bigideasdb](https://bigideasdb.com/reddit-api-pricing)
- Farcaster via Neynar: Beginner free; Starter $9/month (1M compute units); Growth $49/month (10M); Scale $249/month (60M). Pay-per-request via x402 is also supported. — [Neynar pricing](https://neynar.com/pricing); [Neynar quickstart](https://docs.neynar.com/reference/quickstart.md)
- Google Trends API: an alpha announced 2025-07-24 with rolling, application-only access. No GA, pricing or production guarantees as of late 2026. pytrends is reported dead. — [Google Search Central blog](https://developers.google.com/search/blog/2025/07/trends-api?hl=it); [konabayev landscape 2026](https://konabayev.com/blog/google-trends-api-landscape-2026/); [dev.to](https://dev.to/esteban_ortega/pytrends-is-dead-heres-how-to-get-google-trends-data-in-2026-1a18)

### Inferences
- Crypto retail chatter now concentrates on X and Telegram. The operator's existing Telethon reader plus X coverage already captures most of the social signal. Reddit and Farcaster add little for vetoes and are worth adding only as low-weight diversity sources.
- Google Trends is too slow (daily or weekly granularity) for vetoes. At most it is a regime/attention input.

### Gaps
- YouTube Data API quota and cost (and transcript access): not researched in this pass.
- Farcaster's crypto-signal density and per-endpoint CU costs: not measured.

## Latency: who gets news first, and what a retail bot can trade

### Takeaway
The hierarchy runs from paid terminals with colocated WebSockets (Tree SAPLING at $2,500/month, Japan) to Telegram alert channels and free Tree REST, then direct exchange polling (CDN-cached ~30 s), then publisher RSS and CryptoPanic, then GDELT (15 minutes). A VPS bot on cheap feeds cannot win the headline race on listings or breaking news. Its realistic edge is (a) vetoes and risk-off on crash or delisting news, where being 30–300 s late still prevents bad entries, and (b) slower drift or regime signals over hours to days.

### Cited Findings
- Tree News sells "0 delay" and a dedicated Japan WebSocket only in paid tiers ($500 / $2,500 per month). — [treeofalpha.com](https://www.treeofalpha.com/)
- Binance's new-listing page is CDN-cached for ~30 s. — [Binance dev forum](https://dev.binance.vision/t/coin-listing-announcement-information/15081)
- Retail snipers report being slower than Telegram alert channels; listing pumps peak within 1–4 minutes. — [r/algotradingcrypto](https://redlib.hbubli.cc/r/algotradingcrypto/comments/1ktgys6/algo_crypto_sniping); [4Pillars](https://research.4pillars.io/en/data/content/the-dying-upbit-listing-pump)
- GDELT updates every 15 minutes. — [GDELT blog](https://blog.gdeltproject.org/gdelt-3-0-coming-soon/)
- Academic work on crypto announcements finds significant cumulative-return effects with spikes in intraday volatility and volume, and Musk tweets moved BTC by +16.9% / −11.8%. These results are mostly measured at daily or intraday windows, not seconds. — [ScienceDirect, Economics Letters 2025](https://www.sciencedirect.com/science/article/abs/pii/S0165176525001429); [ScienceDirect breaking-news headlines](https://www.sciencedirect.com/science/article/abs/pii/S0264999323002092); [ResearchGate announcement effects](https://www.researchgate.net/publication/341117503_Announcement_effects_in_the_cryptocurrency_market)
- Peer-reviewed listing studies use daily windows. Sub-minute claims come from vendors. — [Blockchain Research Lab](https://www.blockchainresearchlab.org/wp-content/uploads/2019/10/Exploring-Market-Reactions-to-Exchange-Listings-of-Cryptocurrencies-BRL-working-paper3.pdf)

### Inferences
- Approximate end-to-end delay for a VPS pipeline (my estimates, not measured): direct exchange polling 15–60 s; Tree free REST polled each minute ~1–2 min; X via third-party polling every 2 min ~1–3 min; RSS 2–15 min; CryptoPanic Growth (15-minute budget) ~15 min; GDELT ~15–30 min. Adding an LLM classification step via `claude -p` adds seconds to tens of seconds per batch.
- So: do not build a "trade the headline" bot. Build (1) a veto/risk gate that blocks new entries or forces exits on hostile events, where speed only needs to beat your own bots' next candle (5m/1h); and (2) a slower "news-drift" strategy (e.g. delisting → short or avoid for 24–72 h, sustained negative coin-sentiment → skip longs) that must pass the fleet's usual backtest and graduation bar.
- Measure actual latency yourself: log `received_at − source_time` per source (Tree has `time` in ms, Binance `releaseDate`, OKX `pTime`, Upbit `listed_at`).

### Gaps
- No independent, published second-level latency benchmark across Tree, Phoenix, BWEnews, Telegram channels and exchange endpoints was found.

## Historical archives for point-in-time backtesting

### Takeaway
Free point-in-time history exists for exchange announcements (full Binance/Upbit/OKX archives with ms timestamps) and macro news (GDELT raw/BigQuery since 2015). Crypto-news and X history is either paid (NewsAPI 5 y at $449/month, CryptoPanic 1 month–1 year at $199/month) or short (Tree REST ~4 days, GDELT DOC 3 months). The pragmatic path is to start archiving every raw item now, with source timestamp and receive timestamp, and backtest forward on your own archive.

### Cited Findings
- Binance CMS listing catalog: 2,292 articles; delisting catalog: 446; each with `releaseDate` in ms. — Probe of [Binance CMS](https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=2&catalogId=48)
- Upbit announcements: 806 total, 403 pages, with `listed_at`/`first_listed_at`. — Probe of [Upbit api-manager](https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=2&category=trade)
- OKX announcements carry `pTime` and `businessPTime` (ms). — Probe of [OKX](https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings)
- Tree REST: `limit=2000` covered ~4 days (2026-10-30 to 2026-11-03). — Probe of [Tree REST](https://news.treeofalpha.com/api/news?limit=2)
- NewsAPI: Business/Advanced give up to 5 years of history; the free tier gives 1 month with a 24 h delay. — [NewsAPI pricing](https://newsapi.org/pricing)
- CryptoPanic Growth: 1 year or 1 month of history (sources conflict). — [anygen.io](https://www.anygen.io/showcase/cryptopanic/index.html); [fxpanic mirror](https://fxpanic.com/developers/api/about)
- GDELT: DOC API rolling 3 months; full history via raw 2.0 files or BigQuery. — [py-gdelt docs](https://rbozydar.github.io/py-gdelt/getting-started/data-sources)
- Grok `x_search` supports `from_date`/`to_date` at day granularity only. — [xAI X Search docs](https://docs.x.ai/developers/tools/x-search)
- NewsData.io advertises 2 years of historical news search. — [WebSearch result citing NewsData](https://dev.to/alexperigon/historical-news-api-search-long-range-news-archives-and-coverage-since-2016-41en)

### Inferences
- Grok search results are model-mediated and re-ranked with today's knowledge, so a Grok "historical sentiment" backfill is not point-in-time and is unusable for honest backtests. Mark any such data as a non-PIT measurement epoch, consistent with the repo's paper/live/historical separation.
- Exchange-announcement archives are the one free, clean, timestamped event set. A "delisting/listing → 1–72 h return" event study on Binance plus Upbit history, with 1m candles, is the cheapest first test of whether any news-driven rule earns its keep.
- Store `source_time`, `first_seen_at` (our clock), `source`, `raw_text`, `url`, `content_hash` per item from day one. Without `first_seen_at` you cannot model your own latency in backtests.

### Gaps
- X full-archive search pricing and availability under pay-per-use: unconfirmed.
- Open crypto-news datasets (Kaggle, Hugging Face) with reliable timestamps: not researched in this pass.
- Alpha Vantage and Marketaux history depth: not stated on the pages fetched.

## Text→signal processing: classification, entity linking, dedup, spam/credibility, throughput

### Takeaway
Use a cascade: cheap deterministic rules and keyword/regex for high-precision event types (hack, exploit, delist, halt, SEC, depeg, liquidation), a small local encoder (CryptoBERT for social posts, FinBERT for news) on CPU for bulk polarity, and the existing Claude Max CLI (`claude -p`) only for batched, pre-filtered, high-importance items needing reasoning (severity, target coin, direction, novelty). Tree's `suggestions` field already solves much of the ticker entity-linking for free. Claude Max programmatic use draws on the same subscription limits, so batching is mandatory.

### Cited Findings
- CryptoBERT (ElKulako/cryptobert): bertweet-base further trained on 3.2M crypto posts (StockTwits 1.875M, Telegram 664K, Reddit 172K, Twitter 496K), fine-tuned on 2M labelled StockTwits posts. Labels are Bearish/Neutral/Bullish. Max sequence length 128 is recommended (it can technically handle 514). MIT licence. No accuracy or F1 on the card. — [Hugging Face model card](https://huggingface.co/ElKulako/cryptobert)
- On crypto news, a 2024 comparative study reports a customised GPT-4 at 86.7% accuracy, FinBERT 84.3% and BERT 83.3%. — [Big Data and Cognitive Computing, Jun 2024 (DOAJ)](https://doaj.org/article/a9a9c365be7e4f7e964a211c21acaa87); [MDPI](https://www.mdpi.com/2504-2289/8/6/63)
- Across five financial sentiment datasets, Qwen3 8B and Llama3 8B beat FinBERT in most scenarios, even with 5% of the training data. This is not crypto-specific. — [arXiv 2512.00946](https://arxiv.org/html/2512.00946v1). A FinBERT2 paper found large general LLMs (Qwen2-72B) far behind a fine-tuned encoder on Chinese market-sentiment classification (<0.523 vs 0.9249). — [arXiv 2506.06335](https://arxiv.org/pdf/2506.06335). Deployment choices (prompt, input format) materially change LLM results. — [arXiv 2505.16090](https://arxiv.org/pdf/2505.16090)
- Entity linking: Tree REST items include `suggestions` with the matched string, the canonical coin, exchange symbols (binance, binance-futures, bybit-perps) and supply, plus `mainStock` and `venue`. — Probe of [Tree REST](https://news.treeofalpha.com/api/news?limit=2)
- Claude Max: `claude -p` (headless) signed in with the plan draws from the same 5-hour and weekly limits as interactive use. A planned 2026-06-15 split into a separate Agent-SDK credit pool was reported as paused, and as of July and October 2026 sources say plan sign-in still uses plan limits. Anthropic publishes no fixed numbers; check `/usage`. — [DataCamp, Jul 2026](https://www.datacamp.com/tutorial/claude-code-usage-limits); [redreamality, Oct 2026](https://redreamality.com/blog/claude-code-usage-limits-cost-2026/); [codersera](https://codersera.com/blog/how-to-stretch-claude-code-usage-limits-2026/)
- Grok token pricing, if Grok were used as a classifier instead: grok-4.3 at $1.25/$2.50 per 1M in/out. — [xAI models](https://docs.x.ai/developers/models)

### Inferences
- **Cascade throughput** (my estimates, unmeasured). Assume ~2,000–5,000 raw items/day (Tree REST ~500/day, plus X, RSS, exchanges, Telegram). Rules and dedup drop 50–80%. CryptoBERT/FinBERT, at ~110M parameters, should handle this on a VPS CPU in seconds to minutes per day. Escalate only items with `importance` high, a matched watchlist coin and non-neutral polarity, or a hit on a hostile keyword. That might be 50–300 items/day, which in batches of 20–50 per `claude -p` call is about 5–15 CLI calls/day, well within a Max plan. The large fixed Claude Code prompt overhead per invocation is the reason to batch.
- **Output schema** for the LLM step (JSON): `{coin(s), event_type ∈ {hack, exploit, delist, listing, regulatory, macro, depeg, outage, partnership, unlock, rumor, other}, direction (−1/0/+1), severity 0–3, novelty (new vs follow-up), confidence, source_credibility}`. Validate the JSON strictly and treat a failed parse as "no signal", never as "safe".
- **Dedup across sources**: use a normalised-title hash for exact duplicates, plus near-duplicate detection (MinHash/SimHash on shingles, or cosine similarity on small sentence embeddings within a 30–120-minute window). Cluster into "stories" with first-seen time and source count. "Number of independent sources in N minutes" is itself a strong severity feature for crash vetoes. (Standard technique; not sourced here.)
- **Spam, bot and shill filtering**: whitelist sources rather than blacklisting. Use curated account lists (Tree's list, your own ~100–300 accounts), require cashtag posts from non-whitelisted accounts to pass follower-age-engagement thresholds, drop posts with multiple unrelated cashtags or contract-address patterns, and down-weight accounts whose past calls had negative forward returns. Keep per-account credibility as a rolling score (precision of past "hostile" flags against realised 1–24 h moves).
- **Veto rule shape** (fits the existing fleet): block new entries on coin X for H hours if a severity ≥2 hostile story about X exists from ≥2 credible sources or from an exchange delisting endpoint. Block all new entries fleet-wide for M minutes around High-impact USD calendar events, and when a market-wide hostile cluster (hack of a major venue, stablecoin depeg) is detected. Log every veto with its triggering story ID so its counterfactual P&L can be measured. This should be a preregistered measurement epoch before it gates live entries.
- Open LLMs locally (Qwen3 8B via Ollama) are a viable fallback if Max limits bite. CPU-only inference on the VPS is likely slow (seconds per item), so use it only for the escalated subset.

### Gaps
- No crypto-specific benchmark directly comparing CryptoBERT, FinBERT, a local Qwen3-8B and Claude on the same labelled set; you would need your own labelled sample (~500 items).
- Actual Claude Max message or throughput numbers for `claude -p` batches: not published by Anthropic.
- CPU throughput of CryptoBERT and Qwen3-8B on the specific VPS: not measured.

## Recommended minimal and solid feed stacks (with estimated monthly cost)

### Takeaway
Minimal (~$0–15/month): free Tree REST, direct exchange-announcement polling, publisher and Fed RSS, the faireconomy calendar, the existing Telethon channels, an optional small twitterapi.io key-accounts poll, and a rules → CryptoBERT/FinBERT → batched `claude -p` cascade. Solid (~$100–200/month): add broader third-party X coverage (300–500 accounts plus a few cashtag searches), Marketaux Standard for entity-tagged macro news, and a 4x/day Grok `x_search` regime digest. Terminal-grade feeds (Tree SAPLING $2,500/month) and official X at scale (~$450–1,100/month) are out of proportion to a few-hundred-USD fleet.

### Cited Findings
- Tree REST is free and keyless, includes X posts, blogs and exchange notices, and carries ticker suggestions. — Probe of [Tree REST](https://news.treeofalpha.com/api/news?limit=2)
- Binance, OKX, Upbit, Hyperliquid and Coinbase announcement/market endpoints respond publicly. — Probes of [Binance CMS](https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=2&catalogId=48), [OKX](https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings), [Upbit](https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=2&category=trade), [Hyperliquid](https://api.hyperliquid.xyz/info), [Coinbase](https://api.exchange.coinbase.com/products)
- twitterapi.io charges $0.15/1k tweets with a $0.00015 per-call minimum. — [twitterapi.io pricing](https://twitterapi.io/pricing)
- Marketaux Standard is $49/month (Basic $29). — [Marketaux pricing](https://www.marketaux.com/pricing)
- Grok `x_search` costs $5/1k posts fetched plus tokens. — [xAI X Search docs](https://docs.x.ai/developers/tools/x-search)
- Official X costs $0.005/post read, capped at 3M per month. — [X docs pricing](https://docs.x.com/x-api/getting-started/pricing)
- CryptoPanic Growth is $199/month for 3,000 requests. — [anygen.io](https://www.anygen.io/showcase/cryptopanic/index.html)
- Tree SPROUT/SAPLING cost $500/$2,500 per month. — [treeofalpha.com](https://www.treeofalpha.com/)

### Inferences
**Minimal stack: ≈ $0–15/month**
| Layer | Source | Access | Est. cost |
|---|---|---|---|
| Crypto X + blogs + exchange notices | Tree of Alpha public REST, poll ~60 s, archive by `_id` | undocumented JSON | $0 |
| Exchange listing/delisting | Binance CMS (cat 48/161), OKX v5 announcements, Upbit api-manager, Hyperliquid `meta` diff, Coinbase `/products` diff; poll 15–60 s | public JSON | $0 |
| Crypto news | RSS: CoinDesk, The Block, Decrypt, Blockworks, Cointelegraph | RSS | $0 |
| Macro | Fed press RSS, faireconomy weekly calendar JSON, GDELT DOC (≤1 req/5 s) | RSS/JSON | $0 |
| Telegram | existing Telethon session (news/alert channels) | existing | $0 |
| X key accounts (optional) | twitterapi.io, ~50 handles in 2–3 batched queries every 3 min | REST | ~$5–15 |
| NLP | rules → CryptoBERT/FinBERT on CPU → batched `claude -p` on escalations | local + Max | $0 marginal |

**Solid stack: ≈ $100–200/month** (minimal stack plus the rows below)
| Layer | Source | Est. cost |
|---|---|---|
| Broad X coverage | twitterapi.io for 300–500 curated accounts (batched, ~2 min) + ~10 cashtag/keyword searches every 5 min | ~$60–100 |
| Macro/equity news with entity tags | Marketaux Standard (10k req/day) | $49 |
| X regime digest | Grok `x_search`, 4 runs/day × ~50 posts, per-coin "what changed" summaries for the watchlist | ~$30–45 incl. tokens |
| Optional | CryptoPanic Growth for votes/"important" flags (poor value at 3k req/month) | +$199 |
| Optional | official X API for ~50–100 must-not-miss accounts (reliability hedge against scraper outages) | +$75–150 |

- Under the existing ceiling/moratorium stance, the first deliverable should be the archive plus a preregistered veto measurement (counterfactual P&L of blocked entries), not a new live bot. The standalone news bot should only be funded after the free exchange-announcement event study shows a post-cost edge at 1m detail.

### Gaps
- All cost estimates assume ~10 posts/day per followed account and are unmeasured. Real volumes depend on the account list and should be measured in the first week.
- twitterapi.io and SocialData reliability under load and their real latency are unverified, so a one-week shadow comparison against Tree REST is advisable before committing.
