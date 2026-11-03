# Evidence review: does news / social sentiment predict crypto returns, volatility or crashes, and do sentiment filters or LLM news agents survive out-of-sample?

Scope: evidence only (providers and plumbing are covered elsewhere). Research done 2026-11-03 through web search and reading abstracts or full text. Most papers were read at abstract or summary level, and this is flagged per item. "IS" = in-sample, "OOS" = out-of-sample, "TC" = transaction costs.

## 1. Does X/Twitter, Reddit, Telegram, news or Google-Trends sentiment/attention predict crypto returns? (direction, horizon, effect size, costs, OOS, decay)

### Takeaway
Attention (search and tweet *volume*) has a documented weekly-horizon **momentum** association with BTC returns in IS time-series regressions (Liu–Tsyvinski). Text *sentiment* (tone) predicts returns only at very short horizons (≤15 min), only in the 2017 bubble, and the authors say the effect is too small to trade after costs (Guégan–Renault). The more robust and repeated finding is that social activity predicts **volume and volatility, not returns** (Shen–Urquhart–Wang). None of the core studies reports a cost-inclusive, preregistered OOS trading result. Several effects are regime-concentrated and weaken on newer data.

### Cited Findings
- **Liu & Tsyvinski (NBER WP 24877, 2018).** Sample: BTC, XRP, ETH, roughly 2011–2018. Method: time-series predictive regressions. Finding: of all the factors tested (stocks, FX, commodities, macro), only crypto-specific factors, momentum and investor-attention proxies, consistently explain crypto returns. — [NBER PDF](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf); [Causal Claims summary](https://causalclaims.trfetzer.com/paper/w24877.html)
- Liu–Tsyvinski effect sizes from press coverage (the PDF numbers were not checked): a 1-SD rise in Google searches for "bitcoin" is followed by about +2.3% over two weeks. A 1-SD rise in Twitter post counts is followed by about +2.5% within a week. A rise in the "bitcoin hack" to "bitcoin" search ratio is followed by about −2.75% within a week. The press figures differ in places. Direction is momentum, not contrarian. These are IS regressions with no TC. — [CoinDesk 2018](https://coindesk.com/markets/2018/08/10/google-search-can-predict-bitcoin-price-increases-study-finds); [Cryptoglobe 2018](https://cryptoglobe.com/latest/2018/08/google-search-volume-can-predict-crypto-price-movements-study-suggests)
- **Guégan & Renault (Finance Research Letters 38, 2021).** Sample: about 1M StockTwits messages and intraday BTC. Sentiment–return links are significant only at frequencies up to 15 minutes and disappear at lower frequencies. The effect is concentrated around the 2017 bubble. The magnitude is "rather small", making it impossible to earn economic profits from social-media information. — [IDEAS/RePEc](https://ideas.repec.org/a/eee/finlet/v38y2021ics1544612319314199.html)
- **Gao, Huang & Wang (Virtual Economics, 2021).** Sample: hourly Twitter data. Stronger bullish sentiment foreshadows higher BTC return *and volatility* over 24 hours. Small journal; OOS and TC not verified. — [EconPapers](https://econpapers.repec.org/RePEc:aid:journl:v:4:y:2021:i:1:p:7-18)
- **Shen, Urquhart & Wang (Economics Letters 174, 2019).** Sample: daily "Bitcoin" tweet counts, Sep 2014–Aug 2018. Method: linear and nonlinear Granger causality. Tweet counts significantly drive next-day **trading volume and realized volatility**. There is no significant evidence that prior tweets predict **returns**. — [Reading repository](https://centaur.reading.ac.uk/80420/); [RePEc](https://ideas.repec.org/a/eee/ecolet/v174y2019icp118-122.html)
- **Kraaijeveld & De Smedt (J. Int. Financial Markets, Institutions & Money, 2020).** Sample: 9 coins (BTC, ETH, XRP, BCH, EOS, LTC, ADA, XLM, TRX). Method: crypto lexicon sentiment with bilateral Granger tests. Sentiment Granger-causes returns for BTC, BCH and LTC only. A bullishness ratio works only for EOS and TRX. Read through a secondary summary. — [summary](https://thecurrencyanalytics.com/bitcoin/bitcoin-btc-returns-predicted-by-twitter-sentiment-forecasting-crypto-currency-prices-21797)
- A later student replication on newer data finds its own sentiment scores do not predict BTC returns. It reports that Kraaijeveld–De Smedt is one of several studies whose results weaken on newer data. This is a bachelor thesis, so weight it low. — [EUR thesis](https://thesis.eur.nl/pub/73761/Bachelor-Thesis-Jeroen-Frasa.pdf)
- **Li, Goodell & Shen (Int. Review of Economics & Finance 75, 2021).** Sample: 27 coins. Method: wavelet Granger causality. Causality runs both ways between attention and returns, and combined Twitter+Google attention is stronger than either alone. Two-way causality means attention partly *follows* price. — [IDEAS](https://ideas.repec.org/a/eee/reveco/v75y2021icp723-746.html)
- **Methodology audits.** A 2026 arXiv paper on BTC price prediction says the field lacks consensus on whether models beat a naive "today's price" baseline at short horizons. It proposes walk-forward evaluation, multi-regime holdouts and naive-baseline comparison as minimum standards. — [EconPapers arXiv 2606.00071](https://econpapers.repec.org/paper/arxpapers/2606.00071.htm). A 2024 systematic review covers 2014–2024 crypto prediction work, including sentiment. From its snippet it does not audit leakage. — [John, Binnewies & Stantic, Forecasting 2024](https://mdpi.com/2571-9394/6/3/34)
- A blog-level review claims simple sentiment scores often fail OOS. It is not peer-reviewed. — [Medium review](https://medium.com/@gwrx2005/sentiment-analysis-and-cryptocurrency-price-prediction-a-multidisciplinary-review-8696c97a5ea2)

### Inferences
- The literature splits cleanly. **Attention/activity volume → volatility and volume** is the robust direction. **Tone → returns** is fragile, short-horizon and regime-bound. That matches the operator's prior that apparent edges are regime luck: Guégan–Renault's effect sits in the 2017 bubble, and Liu–Tsyvinski's sample is dominated by 2013 and 2017 attention spikes.
- Multiple-testing exposure is high and rarely corrected. Kraaijeveld–De Smedt tests 9 coins × 2 measures × several lags and gets 3 + 2 "hits". With no family-wise or deflated correction, that pattern is consistent with noise.
- Reverse causality (attention follows price) means a lagged-attention momentum signal is largely a noisy proxy for price momentum, which the fleet can already compute from OHLCV.
- No study found reports a cost-inclusive, walk-forward, DSR-style test of a sentiment-driven crypto *trading rule* that survives. The best-cited intraday study explicitly says it does not survive economically.

### Gaps
- Exact Liu–Tsyvinski coefficients were not checked against the PDF. The press numbers differ. The paper was later published in a top journal (RFS, 2021, from memory and unverified this session).
- Rognone, Hyde & Zhang (IRFA 69, 2020), "News sentiment in the cryptocurrency market: an empirical comparison with Forex", exists ([EconBiz](https://econbiz.de/Record/news-sentiment-in-the-cryptocurrency-market-an-empirical-comparison-with-forex-rognone-lavinia/10012316867)), but its findings were not verified here.
- No crypto-specific post-publication-decay study (a McLean–Pontiff analogue for sentiment signals) was found.
- No rigorous Reddit-specific or Telegram-sentiment (non-pump) return studies were retrieved in this pass.

## 2. Fear & Greed index and crowd-sentiment extremes as contrarian signals; Santiment / LunarCrush claims vs independent replication

### Takeaway
The only academic contrarian Fear & Greed (F&G) test found (Łęt et al. 2023) reports that contrarian F&G strategies beat buy-and-hold on Sharpe over 2018–2021. That window is a single cycle, and TC and OOS are not reported in the abstract. Other peer-reviewed work finds a **momentum**-type positive sentiment–return link. Practitioner analyses conflict ("buy fear" versus "greed precedes more gains"). Extreme F&G regimes coincide with **significantly wider spreads**, which taxes exactly the trades a contrarian rule makes. No independent replication of LunarCrush or Santiment predictive claims was found. LunarCrush's Galaxy Score uses price as an input, which makes it partly circular.

### Cited Findings
- **Łęt, Sobański, Świder & Włosik (Springer, Eurasian Business and Economics Perspectives, 2023).** Sample: daily data, 1 Feb 2018–31 Dec 2021, the 20 largest non-stablecoins. They simulate F&G-driven strategies against buy-and-hold, using Sharpe with HAC-robust (Ledoit–Wolf) tests. Contrarian strategies "may" significantly outperform passive investment, results vary by coin, and the authors conclude the market is "still inefficient". TC and OOS are not mentioned in the abstract. — [IDEAS](https://ideas.repec.org/h/spr/eurchp/978-3-031-36286-6_16.html)
- **Huang et al. (Corporate Ownership & Control, 2024).** Method: ARDL and error-correction models. F&G sentiment has a positive, significant relationship with BTC returns (momentum, not contrarian). — [Virtus Interpress](https://virtusinterpress.org/How-does-the-Bitcoin-Sentiment-Index-of-Fear-Greed-affect-Bitcoin-returns.html)
- **arXiv 2602.07018 (2026).** Extreme-fear and extreme-greed regimes show significantly higher spreads than neutral periods, so the index tracks uncertainty and liquidity cost. — [arXiv](https://arxiv.org/pdf/2602.07018)
- **K33 Research (practitioner, 2022).** Buying extreme fear has been profitable on average, but BTC has also seen continued sell-offs after extreme fear. Extreme readings are rare, so samples are small. — [K33](https://k33.com/research/archive/articles/fear-and-greed-index-touched-2020-lows)
- **Ecoinometrics (practitioner newsletter).** Extreme Greed often precedes *further* short-term gains rather than marking a top. — [Ecoinometrics](https://ecoinometrics.substack.com/p/bitcoin-fear-and-greed-where-is-the)
- Another practitioner analysis concludes that "sell the greed" holds up but "buy the fear" fails at short horizons. It contradicts K33 on the fear side. The host is a mirror domain, so weight it low. — [analysis](https://san-1510.aid.brainsum.com/news/analysis/cryptos-favourite-adage-half-fails-bitcoin-hits-extreme-fear)
- **Tagus Capital (practitioner).** The index rarely predicts price moves, with predictive power only in specific regimes. — [Tagus via pulse.bot](https://www.pulse.bot/crypto/blogs/tagus-bits-n-bobs-issue-12-crypto-fear-greed-contrarian-causal-correlative-and-corrective-dynamics-m-c1c05961-7f0f-4ee3-89a6-9fe9ce8f21a1/)
- A vendor/promotional blog says trading on F&G alone is roughly a coin flip. — [dev.to](https://dev.to/gunnarthorderson/beyond-fear-greed-why-single-indicators-fail-and-what-works-1155). An exchange blog reports buy-the-fear returns and is promotional. — [KuCoin](https://www.kucoin.com/blog/what-happens-when-the-crypto-fear-greed-index-hits-extreme-fear)
- **LunarCrush (VENDOR).** LunarCrush describes the Galaxy Score as a leading indicator "that allows algorithmic trading for institutional investors" but publishes no backtest or OOS evidence. — [LunarCrush blog](https://lunarcrush.com/blog/what-is-social-intelligence). The score is built from price, user sentiment and social engagement. — [TradingView docs](https://in.tradingview.com/support/solutions/43000739595-galaxy-score/)
- A third-party outlet notes these metrics are indicators, not predictive guarantees. — [CryptoSlate](https://cryptoslate.com/?p=119934)

### Inferences
- The F&G evidence base is one cycle (2018–2021), one index, with no TC or OOS reported. That falls below the operator's bar (DSR, walk-forward, 1m detail).
- The spread result implies contrarian F&G entries carry higher execution cost exactly when they trigger, which a daily-close backtest would miss.
- Alternative.me's F&G is itself a composite of volatility, momentum/volume, social media, dominance and trends (component list from general knowledge; the methodology page was not fetched). A rule built on it is largely a repackaged volatility/momentum signal and should be tested against those raw inputs as baselines.
- Any score that includes price (Galaxy Score) cannot be a clean leading indicator. A test must orthogonalize it against past returns first.
- The project memory index notes historical F&G is already part of the fleet's market-intelligence/Viability layer (code not checked here). So the cheapest rigorous step is to measure the existing F&G gate's OOS contribution, not to buy another sentiment feed.

### Gaps
- No independent replication of Santiment metrics (social volume, crowd sentiment, "social dominance") was found. Santiment's own "crowd is contrarian" pieces were not retrieved, so treat any such claims as vendor research.
- No rigorous test of CMC's F&G index was found.
- The full Łęt et al. text (costs, trade count, OOS split) was not available.

## 3. Sentiment/news as a RISK signal: volatility, drawdowns, crash risk, liquidation cascades; does a veto gate help other strategies?

### Takeaway
This is the best-supported use. Social activity, news sentiment and crisis-sentiment measures repeatedly predict **higher volatility and crash risk**, including in at least one OOS volatility-forecasting setup. However, I found **no study showing that vetoing entries on sentiment improves the risk-adjusted returns of an independent strategy OOS**. The biggest liquidation cascades driven by exogenous news (e.g., tariff headlines) arrive *without* precursor signals. Scheduled macro releases create predictable 15–30-minute stress windows. A calendar blackout is better supported than a sentiment-score veto.

### Cited Findings
- Tweet counts predict next-day realized volatility and volume, not returns (Economics Letters 2019, 2014–2018 sample). — [Shen, Urquhart & Wang](https://centaur.reading.ac.uk/80420/)
- **"Ask 'Who', Not 'What'" (arXiv 2110.14317, 2021).** Uses more than 30M BTC tweets with 15-minute prices and a causal model, evaluated OOS over a 144-day horizon. *Who* tweets matters more than *what* is said for volatility forecasting. — [arXiv](https://arxiv.org/pdf/2110.14317)
- **News-based sentiment and BTC volatility (Int. Review of Financial Analysis, 2022).** Sample: 17,490 news items from 91 major English-language newspapers, 2012–2021. News sentiment plays a significant role in BTC volatility. This is a volatility result, not jumps or crashes. — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1057521922001454)
- **"Cryptocurrencies' price crash risk and crisis sentiment" (Finance Research Letters, 2021).** Crash risk is positively related to the FEARS crisis-sentiment index, a search-based measure. — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S154461232100009X)
- **"On the predictive power of tweet sentiments and attention on bitcoin" (IREF, 2022).** Tweet-sentiment *dispersion* proxies uncertainty, and higher dispersion goes with greater return volatility. — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1059056022000375)
- Exchange hacks and regulatory news significantly affect BTC volatility (Lyócsa et al. 2020, as cited in a 2026 working paper). — [arXiv 2602.07046](https://arxiv.org/html/2602.07046v2)
- **2026 liquidation-event study (press coverage).** Across 7 major BTC liquidation events, no single indicator reliably predicted the declines. Price/leverage warning signals failed when sell-offs were driven by external shocks: 2 of 7 events were tied to sudden tariff news and showed no usual precursors. — [Bloomingbit](https://en.bloomingbit.io/feed/news/117453); [Cryptorank](https://cryptorank.io/news/feed/fada7-new-bitcoin-study-shows-the-strongest-recurring-liquidation-warning-signs-cannot-warn-of-an-individual-crash)
- **Macro releases.** NY Fed Staff Report 1052 (intraday, 30-minute windows): Bitcoin is largely orthogonal to monetary/macro news and responds only to unexpectedly high or low core CPI. — [NY Fed SR1052](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf). A later Fed paper (minute data, 2015–2025, press summary only): crypto reactions were statistically weak before 2020. After 2021, volatility and activity rose immediately after macro announcements, and the 15–30 minutes around releases are a recurring stress window. — [index.vn summary](https://index.vn/en/news/fed-paper-finds-bitcoin-ethereum-increasingly-track-us-macro-signals-since-2021)
- **Volmex (VENDOR).** CPI and Fed decisions produce substantial jumps in BTC realized vol and BVIV implied vol, with IV declining after the event. — [Volmex PDF](https://volmex.finance/Macroeconomic%20Announcements%20Fuel%20Volatility%20An%20In-Depth%20Analysis.pdf)
- **Veto-gate evidence search.** The only "filter improves Sharpe" claim found is a self-reported TradingView script: Sharpe 0.22 → 0.455 and max DD −42% on BTC daily 2018–2026, "walk-forward stable". It is a trend/EMA regime gate, not sentiment, and is unverified. — [TradingView script](https://www.tradingview.com/script/brWAWunB/)

### Inferences
- Sentiment and attention behave like a **volatility forecaster**. The defensible way to use a volatility forecaster is **position sizing or stop width** (vol targeting), not a binary veto. Higher vol does not imply negative expected return, and the literature shows no reliable sign.
- A veto adds parameters (threshold, lookback, source), so it must be judged on the incremental Sharpe of an existing bot after DSR adjustment for the number of veto variants tried. With small live fleets and few trades per month, statistical power to detect a veto effect will be very low.
- The tariff-shock finding implies the dangerous tail events are exactly the ones a lagging sentiment score cannot see in advance. By the time negative-news volume spikes, the move is mostly done (see section 4 on reaction speed). A veto would mainly block *re-entries* during the elevated-vol aftermath.
- A **scheduled-event blackout** has fixed, known timestamps and no fitting, and recent Fed evidence supports elevated post-2021 sensitivity around CPI/FOMC. That makes it the cleanest "news-aware" risk control, especially for leveraged HL perps where a 15–30-minute spike can trigger stops or liquidations.

### Gaps
- No paper was found that tests "skip entries when negative-news/sentiment spikes" as an overlay on an independent strategy, OOS and net of costs.
- No rigorous study was found linking sentiment to perp funding/OI liquidation cascades specifically; the 2026 study is known only via press.
- The full text of the 2022 IRFA news-volatility paper (OOS design, effect size) was not read. Authorship was not confirmed in this session.

## 4. Event studies on specific news types: listings, hacks, regulation, ETF, macro; how fast is information priced?

### Takeaway
Exchange-listing announcements produce large, real abnormal returns: roughly +23% (Binance) to +33% (Coinbase) average first-day announcement returns in one academic study. But gains are **front-loaded before and at the announcement**, partly via insider trading (estimated in 10–25% of Coinbase listings), and post-listing gains largely **mean-revert within about two weeks** (vendor data). Upbit moves peak within hours. Telegram pumps peak within seconds to minutes. Regulatory news (bans, securities-law treatment) has the largest adverse effects. Evidence on hacks is thinner and mostly about volatility. Macro (CPI) is priced within minutes. For a retail bot polling news, the capturable part is mostly the post-event drift or reversal, which is not well established.

### Cited Findings
- **Li, Luo, Wang & Wei (AFT 2025 extended abstract; SSRN 4715718).** Event study of Coinbase vs Binance listings plus an 80-exchange regulation index. Both show positive short-run abnormal returns, with average first-day announcement returns of 32.8% for Coinbase and 22.7% for Binance. Binance tokens previously funded by Binance's venture arm have weaker fundamentals; Coinbase shows no such pattern. Stricter regulation is associated with higher initial listing returns. Sample period, N and TC are not in the excerpt. — [Dagstuhl AFT 2025](https://drops.dagstuhl.de/storage/00lipics/lipics-vol354-aft2025/html/LIPIcs.AFT.2025.11/LIPIcs.AFT.2025.11.html); [slides PDF](https://loyola.edu/_media/sellinger-business/documents/academics/departments/finance/wealth-management-conference/speakers/J_Li.pdf)
- **Félez-Viñas, Johnson & Putniņš (UTS working paper, 2022).** Sample: 146 Coinbase listings, Sep 2018–May 2022, examining abnormal run-ups 300–100 hours before listing. Insider trading is estimated in 10–25% of listings, with ≥$1.5M lower-bound insider profits. Not peer-reviewed at the time. Context: the SEC charged ex-Coinbase PM Ishan Wahi for front-running listings. — [UTS news](https://www.uts.edu.au/news/2022/08/insider-trading-crypto-markets); [CoinDesk](https://www.coindesk.com/research/2022/08/17/token-front-running-was-common-at-coinbase-a-new-study-argues); [CLS Blue Sky](https://clsbluesky.law.columbia.edu/2022/08/26/insider-traders-have-found-their-way-to-cryptocurrency-markets/)
- **The TIE (VENDOR, 2026; data from Jan 2023 on Binance, Upbit and others).** Price gains are front-loaded before the listing, the announcement matters more than the listing itself, and post-listing gains largely mean-revert within two weeks. Upbit has the most compressed announcement-to-listing timeline. — [The TIE 2026](https://www.thetie.io/insights/what-does-an-exchange-listing-actually-deliver-in-2026). For tokens already on 3+ major venues, the Binance listing run-up is muted, and the durable effect is liquidity: cross-exchange 1% depth roughly doubles. — [The TIE](https://www.thetie.io/insights/what-a-binance-listing-delivers-for-already-listed-tokens)
- **Blockworks (2024 listings).** Binance and Coinbase listings give a short-term bump; "sticking the landing is rare". — [Blockworks](https://blockworks.co/news/empire-newsletter-exchange-listings)
- **Blockchain Research Lab (2019).** Over a (−3, +3)-day window, only 5 exchanges show significant positive listing returns, and 6 show negative. — [BRL](https://www.blockchainresearchlab.org/de/2019/09/10/market-reaction-to-exchange-listings-of-cryptocurrencies-2/)
- **Upbit (media statistic).** After an Upbit listing announcement, the largest price increase generally occurs within two hours (BlockBeats analysis, reported by ChainCatcher; not a controlled study, exact article not verified). — [ChainCatcher](https://h.chaincatcher.com/en/article/2104510); [ChainCatcher](https://www.chaincatcher.com/en/article/2156308). There are on-chain allegations of pre-listing buying on Upbit (WIF, VVV); these are allegations, not findings. — [KuCoin news](https://www.kucoin.com/news/flash/upbit-suspected-of-front-running-with-wif-and-vvv-listings)
- **Telegram pumps.** Of 412 Telegram-organized pump events, the price typically peaks minutes, sometimes tens of seconds, after the start. — [Xu & Livshits / Brave 2019, "Anatomy of a Cryptocurrency Pump-and-Dump"](https://www.arxiv-vanity.com/papers/1811.10109/). A market-data detector cut expected detection time from 30 minutes to 25 seconds, with F1 rising from 62.7% to 94.5%. — [La Morgia et al., ACM TOIT 2023](https://iris.polito.it/handle/11583/3014027)
- **Regulation.** Auer & Claessens (BIS Quarterly Review 2018; CEPR DP14602 2020) run an event study of regulatory news. News on general bans or securities-law treatment has the largest adverse effect, followed by AML news. News on tailored legal frameworks is associated with strong gains. — [Causal Claims summary](https://causalclaims.trfetzer.com/paper/DP14602.html); [EconPapers](https://econpapers.repec.org/RePEc:cpr:ceprdp:14602)
- **Hacks and regulation compared.** A 2026 working paper classifies 31 events (infrastructure vs regulatory, positive vs negative; the "Infra_Negative" group includes exchange failures, hacks and collapses, with 8 analyzed). With block-bootstrap inference it finds no significant CAR difference between event types. The author calls it hypothesis-generating. — [Farzulla, arXiv 2602.07046](https://arxiv.org/html/2602.07046v2)
- **Macro.** BTC was historically unresponsive except to core-CPI surprises (30-minute windows). — [NY Fed SR1052](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf). Since 2021 there are immediate reactions, with a 15–30-minute stress window (press summary of later Fed work). — [index.vn](https://index.vn/en/news/fed-paper-finds-bitcoin-ethereum-increasingly-track-us-macro-signals-since-2021)

### Inferences
- **Speed hierarchy** (from the above): Telegram pumps peak in seconds to minutes. CPI/FOMC reactions happen within minutes. Upbit listings peak within about 2 hours. Coinbase/Binance listing gains are front-run in the 100–300 hours *before* the announcement and fade within about 2 weeks. A Freqtrade bot on 1h–5m candles, fed by a polled news API, will usually arrive after the announcement jump.
- The residual retail-accessible edge, if any, is the **post-listing fade** or the liquidity effect. Its evidence is vendor-only (The TIE) and recent-sample only. It would need its own preregistered event study with 1m data before trading.
- The magnitude of listing returns (20–30%) shows that information *is* priced fast and large. That is evidence of efficiency at the speed retail can access, not of a slow-diffusion edge.

### Gaps
- No rigorous academic event study with return magnitudes was found for **spot BTC/ETH ETF flows or news** (2024–2026). Daily ETF-flow predictability claims seen elsewhere are unverified.
- No peer-reviewed Upbit-specific listing study with intraday timing was found.
- No study was found measuring hack-announcement price reactions at second or minute resolution.
- Hyperliquid-specific listing effects (new perp listings) were not studied in anything found.

## 5. Manipulation and noise: bots, paid shilling, pump-and-dump coordination; can sentiment be gamed?

### Takeaway
Crypto social data is materially contaminated. Estimates run from 1–14% of tweets to about 14% of active accounts being bots. Coordinated Telegram pumps move prices in seconds, insider front-running of listings is documented, and newer work argues that most earlier sentiment studies did not control for fake accounts. Sentiment feeds are adversarially gameable at low cost, especially for small caps. That applies most to per-coin signals and less to BTC-level aggregates.

### Cited Findings
- At least 1–14% of tweets collected for 9 major coins were posted by bot accounts, estimated with a heuristic (Kraaijeveld & De Smedt 2020). — [summary](https://thecurrencyanalytics.com/bitcoin/bitcoin-btc-returns-predicted-by-twitter-sentiment-forecasting-crypto-currency-prices-21797). A later paper cites the figure as about 14% of *active accounts*; the two readings differ. — [arXiv 2411.05577](https://arxiv.org/html/2411.05577v1)
- A 2024 Univ. of Zurich (Digital Democracy Lab) arXiv paper criticizes earlier crypto social-media research for failing to account for fake accounts such as bots and marketing campaigns. — [arXiv 2411.05577](https://arxiv.org/html/2411.05577v1)
- Telegram pumps: 412 events, with price peaking within minutes, sometimes tens of seconds. — [Xu & Livshits 2019](https://www.arxiv-vanity.com/papers/1811.10109/)
- **PumpSense (arXiv preprint, May 2026).** Message-based Telegram detection can alert before or at the onset of the price reaction. Market-data methods detect only after abnormal trading starts, with latencies of tens of seconds to minutes. — [arXiv 2605.09431](https://arxiv.org/abs/2605.09431)
- Market-data pump detection in 25 seconds (F1 94.5%). — [La Morgia et al. 2023](https://iris.polito.it/handle/11583/3014027)
- Insider front-running in an estimated 10–25% of Coinbase listings. — [UTS 2022](https://www.uts.edu.au/news/2022/08/insider-trading-crypto-markets)
- Social metrics are not predictive guarantees (third-party note on LunarCrush-type data). — [CryptoSlate](https://cryptoslate.com/?p=119934)

### Inferences
- **Who** posts matters more than **what** is posted (section 3, "Ask Who, Not What"). Any sentiment layer that weights raw mention counts or average tone without account-quality filtering is easy to spoof.
- For a **per-coin negative-news veto**, gaming risk is asymmetric. A coordinated FUD campaign is cheap on small caps and would make the bot skip trades. That is a lost opportunity, not a loss, so the veto's downside is bounded. A *positive*-sentiment entry trigger is directly exploitable by pump groups, since bots that buy on social spikes are the exit liquidity.
- Studies rarely handle manipulation explicitly. Most published sentiment results should be read as "bots + humans" signals whose composition drifts over time, which is one more reason for decay.

### Gaps
- One result in search output was attributed to "Moura et al., ICWSM 2027 (in press)". It reportedly covers 47 events, finds manipulative signals extremely synchronized and preceding price moves by seconds, and finds pump messages linguistically indistinguishable from organic chat. I could not resolve its primary URL, so verify before citing.
- No quantification was found of how much bot filtering changes the predictive power of crypto sentiment OOS.
- Paid-KOL shilling on X (e.g., disclosed or undisclosed promotions) was not covered by rigorous return studies found in this pass.

## 6. LLM news/sentiment trading agents (CryptoTrade, FinMem, FinAgent, TradingAgents, FinGPT, 2025–2026 work, live arenas): reported results and critiques

### Takeaway
The crypto-specific flagship (CryptoTrade, EMNLP 2024) **does not beat buy-and-hold in bull markets for BTC or SOL**. It "wins" in bear markets mainly by holding cash, uses roughly 2-month daily test windows in 2023, and states no fee rate. Its test windows sit inside the training eras of the GPT-4-class models it uses; only GPT-3.5's cutoff is addressed. Leakage papers show LLM-agent backtests collapse after the model's knowledge cutoff (Sharpe decay above 50% for TradingAgents). LLMs recall pre-cutoff market numbers exactly, and masking or instructions don't fix it. Under survivorship- and snooping-controlled long-horizon tests (FINSABER), LLM strategies underperform simple baselines. The only live crypto-perp contest (Alpha Arena S1, Hyperliquid, about 2 weeks, 6 models) produced dispersion consistent with leveraged noise (+22% to −63%). There is no credible evidence yet that LLM news agents produce persistent OOS crypto alpha.

### Cited Findings
- **CryptoTrade (Li et al., EMNLP 2024; arXiv 2407.09546).**
  - Design: on-chain plus news, with market, news, trading and reflection agents. GPT-3.5-turbo serves as analyst and summarizer; GPT-4 and GPT-4o serve as the trader. Trading is daily on BTC, ETH and SOL.
  - Test windows: bear 2023-04-12→06-16, sideways roughly 2023-06/07→08, bull 2023-10-01→12-01; validation was Jan–Mar 2023.
  - Leakage control: the authors state only that tests come after GPT-3.5's Sep 2021 cutoff. No cutoff is stated for GPT-4 or GPT-4o.
  - Fees: proportional, but the rate is not given.
  - Results (total return %, Sharpe):

    | Asset, market | Buy and hold | CryptoTrade GPT-4 | CryptoTrade GPT-4o |
    |---|---|---|---|
    | BTC bull | 39.66 | 26.35 | 28.47 |
    | SOL bull | 176.72 | 99.84 | 115.18 |
    | ETH bull | 22.59 | 25.72 | 25.47 |
    | BTC bear | −15.61 | −11.72 | −13.71 |
    | SOL bear | −36.08 | −19.55 | −16.32 |

  - Ablation: removing news cuts return from 28.47% to 19.69% and Sharpe from 0.23 to 0.06 (labelled ETH bull GPT-4o in the extracted summary, but 28.47 matches the BTC GPT-4o row, so the label is uncertain).
  - Authors' own limitations: "relatively limited dataset", daily frequency only, and no LLM fine-tuning. — [arXiv HTML](https://arxiv.org/html/2407.09546v1); [ACL Anthology](https://aclanthology.org/2024.emnlp-main.63/)
- **Profit Mirage (Li, Zeng, Xing, Xu & Xu; arXiv 2510.07920, Oct 2025).** LLM-agent backtest returns collapse once evaluation passes the model's knowledge cutoff. The authors attribute this to leakage inside the LLM. Summaries report the best agent's performance dropping about 50%, and TradingAgents still suffering **55.68% Sharpe decay** post-cutoff. They release FinLake-Bench, a leakage-robust benchmark, and the FactFin counterfactual framework. — [arXiv](https://arxiv.org/abs/2510.07920); [HTML](https://arxiv.org/html/2510.07920v1)
- **FINSABER (arXiv 2505.07078, 2025).** Sample: 2000–2024, historical S&P 500 constituents including delisted names (survivorship control), with rolling windows (snooping control). LLM strategies generally **underperform** traditional strategies, and most fail to beat buy-and-hold. They are too conservative in bull markets and too aggressive in bear markets. Reviewers note possible residual look-ahead. — [arXiv](https://arxiv.org/html/2505.07078v3)
- **Lopez-Lira, Tang & Zhu, "The Memorization Problem" (SSRN/arXiv 2025, revised 2026).** LLMs recall exact pre-cutoff values: GPT-4o recalls S&P 500 levels on specific dates, unemployment to 0.1pp, and quarterly GDP. There is no recall after the cutoff. Masking names or dates fails, because models reconstruct them from context. Instructing models to respect time boundaries also fails. The authors recommend **post-cutoff evaluation only**. — [SSRN](https://papers.ssrn.com/abstract=5217505); [arXiv](https://arxiv.org/html/2504.14765v2)
- **Glasserman & Lin (arXiv 2309.17322, 2023).** GPT-3.5 headline sentiment for stocks, comparing original and anonymized headlines. In-sample, anonymized headlines performed better. The difference loses significance OOS, implying in-sample results mix look-ahead (positive) and "distraction" (negative) effects. Both are stronger for large, well-known firms, which is the analogue of BTC/ETH. — [arXiv](https://arxiv.org/abs/2309.17322)
- **He, Lv, Manela & Wu, ChronoBERT/ChronoGPT (arXiv 2502.21206, 2025).** They train vintage-by-year models from 1999 on date-filtered text. Real-time news→next-day stock-return Sharpe is comparable to a much larger Llama, suggesting look-ahead is "modest" *in that application*. The authors stress bias is model- and application-specific. — [arXiv](https://arxiv.org/html/2502.21206v3)
- **Alpha Arena Season 1 (Nof1; 18 Oct–~3/4 Nov 2025).** Six LLMs each got $10k on Hyperliquid perps with no human intervention. Results: Qwen3-Max +22.3%, DeepSeek V3.1 +4.89%, Gemini 2.5 Pro −56.71%, GPT-5 −62.66%; only 2 of 6 were profitable. Nof1 called S1 exploratory, and outlets note short duration and no statistical controls. End dates conflict across sources. — [GNcrypto](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/); [Forklog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/); [Datawallet explainer](https://www.datawallet.com/crypto/alpha-arena-nof1-ai-explained)
- **LiveTradeBench (arXiv 2511.03628, Nov 2025).** A 50-day live evaluation of 21 LLMs on US stocks and Polymarket, with live prices and news. General LLM benchmark (LMArena) scores do not predict trading performance; one summary says the correlation is about zero. No crypto. — [arXiv](https://www.arxiv.org/abs/2511.03628)

### Inferences
- **The CryptoTrade leakage gap is likely large.** GPT-4o's documented knowledge cutoff is generally reported as October 2023 (from memory, not verified this session), which would place all CryptoTrade test windows, Apr–Dec 2023, at or before the trader model's cutoff. Combined with Lopez-Lira et al.'s exact-recall finding, its news-ablation gain cannot be separated from memorization.
- The CryptoTrade samples are 3 assets × 3 windows of about 2 months of daily decisions, roughly 60 decisions each. Daily Sharpe differences such as 0.23 vs 0.06 on samples that size are far from significant after any multiple-testing correction. The "bear-market win" is the trivial effect of being partly in cash.
- **Alpha Arena S1 is one path**: about 2 weeks, 6 models, leveraged perps. A +22% to −63% spread is what leverage plus random direction produces. It carries no information about skill under a DSR lens. It is useful only as evidence that LLM agents left alone can blow up quickly on HL.
- For a fleet operator, the only valid LLM-agent evidence is **forward, post-cutoff, cost-inclusive paper trading** of a frozen prompt, model version and data pipeline, preregistered with DSR-style accounting for prompt variants. That mirrors the fleet's existing dry-run → live graduation gates.
- An LLM is better used as a **classifier/extractor** (e.g., "is this headline a hack, delisting or enforcement event for coin X?") feeding a rule whose effect is measured with classic event-study methods. That limits leakage to labeling, which can be audited on post-cutoff events, and avoids trusting the LLM's directional "judgment".

### Gaps
- FinMem, FinAgent and FinGPT published results and critiques were not individually retrieved. Their reported gains come from short backtests, often on single stocks, but this was not verified here.
- Later Alpha Arena seasons (S1.5 on US stocks; any 2026 crypto seasons) were not retrieved with verified numbers.
- No peer-reviewed crypto-specific post-cutoff LLM news-trading test was found.

## 7. What is the most defensible use of sentiment for a small retail fleet: alpha source, regime filter, or risk veto?

### Takeaway
Ranking by evidence quality: (1) **scheduled-event and volatility-aware risk control** (macro-calendar blackout, vol-scaled sizing using attention/news-volume as an extra vol input) is best supported. (2) A **market-wide sentiment veto** is plausible but unproven as a return improver. (3) A **per-coin negative-news veto** is a cheap, bounded-downside insurance rule but lacks direct evidence. (4) **Standalone sentiment alpha and LLM news agents** are not supported by rigorous OOS evidence. The fastest-moving news, listings and pumps, is priced in seconds to hours, often front-run by insiders, which puts it out of reach for polled-API Freqtrade bots.

### Cited Findings
- Attention/activity predicts volatility, not returns. — [Shen, Urquhart & Wang 2019](https://centaur.reading.ac.uk/80420/); [IRFA 2022 news-vol](https://www.sciencedirect.com/science/article/pii/S1057521922001454)
- Sentiment-return predictability is ≤15 min, regime-bound and not economically exploitable. — [Guégan & Renault 2021](https://ideas.repec.org/a/eee/finlet/v38y2021ics1544612319314199.html)
- Crash risk rises with crisis sentiment. — [FRL 2021](https://www.sciencedirect.com/science/article/abs/pii/S154461232100009X)
- Exogenous-news liquidation events lack precursors. — [Bloomingbit](https://en.bloomingbit.io/feed/news/117453)
- Macro releases create 15–30-minute stress windows post-2021. — [index.vn summary of Fed paper](https://index.vn/en/news/fed-paper-finds-bitcoin-ethereum-increasingly-track-us-macro-signals-since-2021)
- Listing gains are front-loaded and insider-traded, then revert within about 2 weeks. — [UTS 2022](https://www.uts.edu.au/news/2022/08/insider-trading-crypto-markets); [The TIE 2026, vendor](https://www.thetie.io/insights/what-does-an-exchange-listing-actually-deliver-in-2026)
- LLM agent backtests collapse post-cutoff, and LLM strategies underperform under robust testing. — [Profit Mirage](https://arxiv.org/abs/2510.07920); [FINSABER](https://arxiv.org/html/2505.07078v3)
- Extreme F&G regimes have wider spreads. — [arXiv 2602.07018](https://arxiv.org/pdf/2602.07018)

### Inferences
- **Recommended test design for the operator's veto idea.**
  - Treat the veto as an overlay on each existing bot's *already-recorded* trades. Measure the change in Sharpe, max DD and trade count with versus without the veto on 1m-detail data, walk-forward.
  - Count every threshold, lookback and source tried as a trial in the DSR.
  - Use point-in-time sentiment data only. Vendor histories are often backfilled or revised, which was not verified here but is a known risk to check per provider.
  - Compare the veto against a **pure realized-vol or funding/OI baseline**. If sentiment adds nothing beyond realized vol, drop it.
- With the fleet's low trade frequency, a veto that removes 10–20% of trades will rarely reach significance within months. Preregister it as a forward measurement, in the same spirit as the fleet's preregistrations, rather than expecting a backtest to settle it.

### Bottom-line verdict per use case
1. **Sentiment as standalone alpha: WEAK.** Return predictability is short-horizon (≤15 min), regime-concentrated (2017), too small after costs per its own authors, mostly IS, and LLM-agent versions collapse post-cutoff. There is no cost-inclusive OOS survivor.
2. **Sentiment as a market-wide risk veto: MIXED.** Sentiment, attention and news volume reliably forecast *volatility and crash risk*, but no study shows a veto improves another strategy's OOS risk-adjusted returns. The worst news shocks arrive without precursors. A scheduled macro blackout and vol-scaled sizing are better supported than a sentiment threshold.
3. **Per-coin negative-news veto: WEAK.** Hacks and enforcement news do cause large adverse moves and higher vol (Auer–Claessens; Lyócsa), but the reaction is priced fast. Hack-specific evidence is thin and small-N, and per-coin social data is bot- and FUD-contaminated. It is defensible only as cheap, bounded-downside insurance with a binary event classifier (hack, delisting, enforcement), not a sentiment score.
4. **Event-driven trading on specific news types: MIXED.** Effects are real and large (listing announcements +23–33% first day; regulatory bans strongly negative; CPI surprises move BTC), but they are priced in seconds to hours and front-run by insiders in 10–25% of Coinbase listings. The residual retail-accessible piece (post-listing fade, liquidity effects) rests mainly on vendor or recent-sample evidence and would need its own preregistered 1m event study.

### Gaps
- No direct evidence was found on whether point-in-time sentiment vendor histories are free of backfill or revision bias. This should be checked per provider before any backtest.
- No study was found on sentiment overlays specifically for Freqtrade-style mid-frequency (5m–1h) crypto strategies or for HL perps.
