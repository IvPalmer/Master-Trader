# YouTube Trading Research — 2026-04-20

**Author:** mining run (7 transcripts pulled, 2 bust-tested via third-party review, 3 reference articles cross-read)
**Purpose:** Surface concrete, pandas-implementable signals from YouTube practitioners worth a lab run. Nothing here is "obviously a bot" — all need the standard Phase 3 validation bar before live.
**Fleet context:** 2 long-only mean-rev bots ($400 dry-run). $200 free capital on hold per the stable checkpoint rule.

---

## Top 5 concrete setups

### 1. TradeSmart — Supertrend + Range Filter + RMI/EMA (BTC/ETH 2h)
- **Source:** "Simple 2 Indicator Strategy for Bitcoin & Ethereum Backtested: 2000% Profit!" — https://www.youtube.com/watch?v=-ND2II4bZnI (channel: TradeSmart)
- **Date:** Recent (post-optimization cutoff Jan 2024 referenced in video)
- **Timeframe:** 2h (explicitly dies on 1h / 30m / 15m / 4h)
- **Pair:** BTC/USDT and ETH/USDT
- **Long-only, entry rules (AND):**
  - Supertrend buy signal — `ATR period=20, source=hl2, multiplier=1.2`
  - RMI line above EMA(RMI) — `RMI length=10, momentum=10, EMA on RMI=10`
- **Exit:** Range Filter sell signal — `sampling=175, range multiplier=4`
- **Pyramiding:** re-enters on every signal while position open (up to 100)
- **Claimed stats (4yr 2020-2024 BTC 2h):** 247 trades, ~1000% net, PF 2.5, 25% MDD, 15k$ position on 10k$ account
- **ETH 2h:** 232 trades, ~2000% net, 48% win, PF 2.6, 20% MDD
- **Out-of-sample Jan–Aug 2024:** BTC 23 trades / 140% / PF 3.5 / 40% DD; ETH 31 trades / 330% / PF 4.0 / 19% DD
- **Feasibility: YES.** All indicators trivially portable to pandas/ta-lib. Supertrend and Range Filter already exist in ta/pandas_ta. 2h candles derivable from our 1m data.
- **Overfit risk: MEDIUM.** Creator did show an honest post-optimization window and two assets; pyramiding on every signal is the red flag — that's the kind of thing that works in trends and implodes in chop. Video admits 1h / 30m / 15m all lose. That timeframe sensitivity is a classic overfit tell.
- **Action:** Lab-test at 2h on all 20 pairs; include full 3.3yr window; report separate stats for pre/post Jan 2024 OOS. Disable pyramiding in one variant (our lab default).

### 2. Trading Midbusters — Bollinger + RSI mean reversion (bust-test)
- **Source:** "I Tested RSI + Bollinger Bands Strategy in 2025: Crypto, Stocks, Futures, Forex Markets" — https://www.youtube.com/watch?v=j2ESnjhT2no
- **Original signal (from the 1.5M-view TradingLab video being tested):** Long when price crosses lower BB + RSI crosses below lower threshold; exit at middle BB + RSI threshold. BB period=30, RSI period=13.
- **Already-backtested result:** FAILED on crypto at every timeframe except 1d (where Sharpe was 1.2 on $70 profit — noise). Sharpes of -33 to -1000 on 1h/30m/15m/5m/3m/1m. Freqtrade-based testbed, 100 most liquid crypto tickers.
- **Feasibility: YES but skip.** Already thoroughly busted by a third party using Freqtrade on the same universe we'd use. Our own Keltner+vol filter setup already dominates this.
- **Overfit risk: confirmed overfit to single-asset cherry-pick in the original video.**
- **Action:** SKIP — pre-rejected by independent Freqtrade reproduction.

### 3. Computer Science (Salah) — Multi-timeframe BB mean-rev with ADX squeeze + 4h Supertrend trend gate
- **Source:** "GPT: Mean Reversion strategy in Python makes 813%" — https://www.youtube.com/watch?v=5I2vtNovJcQ
- **Timeframe:** 1h trading, 4h confirmations
- **Entry (long):**
  - Price at/below lower Bollinger Band (current 1h)
  - RSI(14) > 70 on 4h (counter-intuitive — wants "trending but pulled back")
  - Supertrend uptrend on 4h
  - ADX > 40 on 4h AND ADX > 20 on 1h
- **Exit:** TP at upper BB; SL at entry − 6 × ATR (current 1h). Risk 2–3% per trade.
- **Long + short symmetric.** Uses limit orders at BB band, re-submits until filled or invalidated.
- **Claimed:** 813% backtest (cited in title; details not verified in this research).
- **Feasibility: YES.** All indicators native to ta-lib. Multi-timeframe straightforward in Freqtrade via `informative_pairs`.
- **Overfit risk: HIGH.** Four stacked filters with specific thresholds (70/40/20) + 6×ATR stop is the canonical overfit pattern. LLM-generated code path also means no human sanity check on leakage.
- **Action:** Run in lab *after* stripping to the minimum: BB-lower + 4h Supertrend up only. If that's profitable, add filters one at a time with DSR gate. Do NOT backtest the full 4-filter stack first.

### 4. CodeTrading — MACD crossover + EMA100 filter (4h trend-follow)
- **Source:** "MOST Effective (?) MACD Strategy for DAYTRADING Crypto" — https://www.youtube.com/watch?v=NQ3mGNJSzrI (CodeTrading / original from DataTrader)
- **Timeframe:** 4h (dies on 1h and lower — confirmed in-video)
- **Long-only entry (AND):**
  - MACD line crosses above signal line (default 12/26/9)
  - Close > EMA(100)
- **Exit:** static 3% SL, 4.5% TP (1.5× SL). Creator explicitly simplified DataTrader's subjective swing-low SL.
- **Per-asset backtest (2021–2022):** ETH 4h = +44% (buy-hold +72%), DOGE = +776% (buy-hold +101%), ADA = +776% over 2021+, **BTC FAILS** at every timeframe and period. 1h on ETH = -30%.
- **Feasibility: YES.** Trivially implemented. MACD + EMA is a 10-line Freqtrade strategy.
- **Overfit risk: MEDIUM-LOW.** Creator openly shows what breaks (BTC, sub-4h). Pattern matches our "trend-follow works on altcoin vol" prior. Honest practitioner.
- **Action:** Lab-run on full altcoin basket at 4h over 3.3yr. Expect it to look great in 2021 and die in 2022-2023. Useful as a baseline "dumb trend" reference rather than a candidate for capital.

### 5. Rob's Tech — AI-driven backtest replication workflow (not a strategy, a tool)
- **Source:** "ChatGPT can now BACKTEST and IMPROVE your Trading Strategy!" — https://www.youtube.com/watch?v=ff-jY7WDMec
- **What's actually demonstrated:** GPT o3 can reproduce a TradingView strategy backtest to within one trade of accuracy, given: (1) screenshot of Properties tab, (2) strategy inputs, (3) CSV of chart data.
- **Reported reproduction match:** 590% vs 591% net profit; 61 vs 62 trades; ~1% max-DD drift.
- **Feasibility: YES as workflow.** Relevant because it validates an idea-mining pipeline: take any Pine strategy from YouTube, feed to LLM, get a pandas reproduction in minutes for cheap OOS testing before lab commitment.
- **Overfit risk: N/A — this is tooling.**
- **Action:** Bookmark for when a Pine-only strategy is too appealing to skip but too tedious to port. Don't deploy.

---

## Dead-end section (surveyed, rejected)

- **Quant Factory Medium article (`medium.com/quant-factory/backtesting-popular-strategies-from-youtube-5-cbbf5f91e75a`)** — reviewed a TradingLab BB+RSI stock strategy that was unprofitable on TSLA. No crypto. Confirms the TradingLab signal is dead anywhere.
- **"Backtesting Your Crypto Strategies with a Quant Trader" (0BCnldjtAqM, 3Commas co-stream):** 50-min live is a 3Commas GUI tool demo for DCA with RSI-oversold entries. No specific rules, tool-ad content. Rejected.
- **Moon Dev / AI Trade Camp:** 2000+ AI-generated backtests filterable by Sharpe but they're strategy-zoo fishing without pre-registered hypotheses. Exactly the kind of Sharpe-hunting that DSR (which we already ran) crushes. Rejected on principle — this is the surface our 2026-04-18 DSR analysis already showed returns 0/31 passers.
- **Part Time Larry:** Educational code tutorials, no concrete tested signals. Rejected on scope.
- **"Highly Reliable Mean Reversion Trading Strategy" (gG_ONDRUPaQ):** transcript fetch failed (captions disabled/geo). Title is a well-known YouTube-strategy genre — one indicator, "millions of trades" — high a-priori overfit signature. Not worth a manual review round.
- **Ernest Chan content:** Robot Wealth and Chan himself do publish, but on blog posts / Substack / books. Kris Longmore (Robot Wealth) already in user's subscription list per memory. Not a YouTube angle.

---

## Synthesis

One genuine lab candidate: **TradeSmart Supertrend + Range Filter + RMI/EMA on BTC/ETH 2h (video #1)**. It has multi-asset support, a named post-optimization OOS window, and honest timeframe sensitivity disclosure (which is still a yellow flag). It's an orthogonal edge type to our existing Keltner (TA mean-rev) and FundingFade (funding non-TA) — it's trend-follow with an explicit volatility exit. That's the fleet gap.

Two secondary candidates for "minimum-viable stripped" lab runs: **video #3 stripped to 2-filter** (4h Supertrend + BB-lower) and **video #4 MACD+EMA100 on 4h altcoins** as a dumb-trend baseline.

Everything else is noise. Honestly, the strongest research output here is negative: the TradingLab BB+RSI (video #2) has been independently Freqtrade-tested on 100 crypto tickers and loses on every timeframe except a statistically-meaningless 1d. That's calibration data for our own overfit detection — the signal was plausible, it was popular (1.5M views), and it lost.

Per the stable checkpoint rule: none of these get deployed. Video #1 is eligible for a single lab run under the Phase 3 validation bar (+20% / PF 1.3 / 6/6 WF / ±20% calibration). If it fails any, it dies.

## Output locations

- Transcripts: `/tmp/video-context/research_2026-04-20/*.txt`
- This report: `/Users/palmer/Work/Dev/master-trader/docs/youtube_trading_research_2026-04-20.md`
