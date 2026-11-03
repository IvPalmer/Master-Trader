# Architecture and integration: a sentiment/news layer for a small Freqtrade fleet (as of 2026-11-03)

Basis: Freqtrade facts were checked against the official docs (`/en/stable/`) and against the source on the `stable` branch, whose `__version__` is `2026.10`. GitHub repo stats come from the GitHub REST API, queried 2026-11-03. Local facts come from this repository's own files and are cited by absolute path.

## Q1. Which Freqtrade mechanisms suit external signals, and which give a fail-safe veto?

### Takeaway
`confirm_trade_entry` is the only hook that also gates `/forceenter`, so it is the only one that covers the Killers copy-trader. Use it, feed it from a local snapshot file that `bot_loop_start` reloads, and wrap it in an explicit internal try/except: Freqtrade swallows exceptions from this callback and lets the trade go through. For bots that enter on their own signals, REST pair locks (`POST /api/v1/locks`) are a good push-style veto: side-aware, time-limited, global via `"*"`. Locks do not stop `/forceenter`. RemotePairList in `blacklist` mode can serve as a coarse second layer. Producer/consumer and FreqAI fit features, not vetoes.

### Cited Findings
- **Version.** The current release is Freqtrade 2026.10, dated 30 Oct. The four before it were 2026.9 (29 Sep), 2026.8 (31 Aug), 2026.7 (31 Jul) and 2026.6 (29 Jun) — [GitHub releases](https://github.com/freqtrade/freqtrade/releases); [stable `__init__.py`](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/__init__.py).
- **`confirm_trade_entry(pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs) -> bool`.** It runs right before the entry order is placed. Returning False aborts the entry; the default returns True. The docstring says timing is critical and the method should not do heavy computation or network requests — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).
- **Callback call site.** In `execute_entry`, Freqtrade calls `confirm_trade_entry` only when `mode == "initial"`. The call goes through `strategy_safe_wrapper(..., default_retval=True)`, and a denial logs `User denied entry for {pair}.`. Position adjustments (`pos_adjust`) and order replacements skip the callback — [freqtradebot.py (stable)](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py).
- **Exception handling.** `strategy_safe_wrapper` catches `ValueError` and any other `Exception`, logs it, and returns `default_retval` when one is set. If a veto callback raises, `default_retval=True` applies and the trade is placed. Freqtrade's default is fail-open — [strategy_wrapper.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/strategy/strategy_wrapper.py).
- **`/forceenter` and the callback.** `RPC._rpc_force_entry` calls `execute_entry(..., mode="pos_adjust" if trade else "initial")`. A forced entry into a new position therefore passes through `confirm_trade_entry`; a forced add to an existing trade does not — [rpc.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/rpc.py); route `POST /forceenter` in [api_trading.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/api_server/api_trading.py).
- **Pair locks.** `IStrategy.lock_pair(pair, until, reason, side="*")` blocks a locked pair from analysis and from opening new trades. Locks can only be extended, and `side` can be `long`, `short` or `*` — [interface.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/strategy/interface.py). The REST API has `GET /locks`, `POST /locks` (taking a list of `{pair, side, until, reason}`), `DELETE /locks/{id}` and `POST /locks/delete` — [api_trading.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/api_server/api_trading.py), [api_schemas.py `LocksPayload`](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/api_server/api_schemas.py). Locking pair `'*'` locks all pairs (a global lock) — [pairlock_middleware.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/persistence/pairlock_middleware.py).
- **Where locks are enforced.** The global-lock check lives in `enter_positions` and the per-pair check in `create_trade`. I found no `is_pair_locked` or `is_global_lock` call in `rpc.py`, so `/forceenter` appears to bypass locks — [freqtradebot.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py), [rpc.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/rpc.py). (Based on reading the source, not on a runtime test.)
- **`bot_loop_start`.** In dry/live mode it runs at the start of each throttling iteration, about every 5 s by default; in backtest and hyperopt it runs once per candle. The docs list loading external data as an intended use — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/). Backtesting calls it with `supress_error=True` — [backtesting.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/optimize/backtesting.py).
- **Backtesting.** It calls `confirm_trade_entry` (default True) and `custom_stake_amount` (default: the proposed stake). A veto that reads point-in-time sentiment keyed on `current_time` can therefore be replayed in a standard Freqtrade backtest — [backtesting.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/optimize/backtesting.py).
- **`custom_stake_amount`.** Returning 0 or None blocks the trade. An exception makes Freqtrade fall back to `proposed_stake`, which fails open on size. Out-of-range values are clamped — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).
- **`leverage`.** The callback runs only in futures mode, and values above `max_leverage` are clamped. It can lower leverage for perps under a caution regime — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).
- **`adjust_trade_position`.** It runs very often during a trade. Loose logic can trigger a re-entry about every 5 s, and the docs warn that adjustments can make live and backtest results diverge — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/). Because `confirm_trade_entry` does not gate DCA adds (see the call-site finding above), a DCA bot needs its own sentiment check inside `adjust_trade_position`.
- **`@informative` caching.** 2026.8 added call caching for `@informative` functions, which changes behaviour for strategies that do non-dataframe work inside them. Do not put sentiment fetches there — [GitHub releases](https://github.com/freqtrade/freqtrade/releases).
- **RemotePairList.** Options:
  - `mode`: `whitelist` or `blacklist`.
  - `processing_mode`: `filter` or `append`.
  - `pairlist_url`: HTTP, or a local `file:///` path.
  - `refresh_period`, `keep_pairlist_on_failure` (default true), `read_timeout` (default 60 s), `bearer_token`, `save_to_file`.
  - JSON format: `{"pairs": [...], "refresh_period": N}`.

  On a server error it keeps the last list, or returns an empty list if `keep_pairlist_on_failure` is false — [Plugins docs](https://www.freqtrade.io/en/stable/plugins/).
- **RemotePairList source details.**
  - The default `refresh_period` is 1800 s, and a remote file can only raise it.
  - A `blacklist`-mode RemotePairList cannot be first in the chain.
  - If the first fetch fails, it raises `OperationalException` (the bot will not start). Later failures return the last list.
  - A valid empty list is cached as `[None]`.

  Source: [RemotePairList.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/plugins/pairlist/RemotePairList.py).
- **Other exclusion filters.** `MarketCapPairList` and `PairInformationFilter` have blacklist modes, and `DelistFilter` drops pairs scheduled for delisting — [Plugins docs](https://www.freqtrade.io/en/stable/plugins/). The docstring on the whitelist refresh in `freqtradebot.py` mentions pairs with open trades. Removing a pair from the whitelist does not close its position. — [freqtradebot.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py)
- **Producer/consumer.** It shares `analyzed_df` and `whitelist` messages over the message websocket. Consumers read them with `dp.get_producer_pairs()` and `dp.get_producer_df(pair)` and need `process_only_new_candles = False`. Config includes `wait_timeout` (300 s), `ping_timeout` (10 s), `sleep_time` (10 s) and `initial_candle_limit` (100–1500). The page does not document what happens to stale data when a producer disconnects, and does not give a message format that would let a non-Freqtrade process act as producer — [Producer/consumer docs](https://www.freqtrade.io/en/stable/producer-consumer/).
- **Retries after a denial.** `ignore_buying_expired_candle_after` defaults to 0, and `enter_positions` / `create_trade` / `get_entry_signal` run every loop iteration — [interface.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/strategy/interface.py), [freqtradebot.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py).
- **Local: current Fear & Greed gate.** `FearGreedIndex` makes a synchronous `requests.get` with a 10 s timeout and a 6 h cache whose initial value is `{"value": 50, "last_fetch": 0}`. On an exception it logs a warning and returns the old cache. `last_fetch` is updated only on success. Several strategies call it from `confirm_trade_entry` (for example AlligatorTrendV1, GaussianChannelV1, BollingerRSIMeanReversion) — [../../../../ft_userdata/user_data/strategies/market_intelligence.py](../../../../ft_userdata/user_data/strategies/market_intelligence.py).
- **Local: Killers.** `KillersScalpV1` implements `custom_stake_amount` but not `confirm_trade_entry` — [../../../../ft_userdata/user_data/strategies/KillersScalpV1.py](../../../../ft_userdata/user_data/strategies/KillersScalpV1.py). The receiver enters through `/forceenter` — [../../../../services/killers-receiver/app/main.py](../../../../services/killers-receiver/app/main.py).

### Inferences
- **Ranking for a fail-safe veto:**
  1. `confirm_trade_entry` plus a local snapshot file. It covers strategy entries and `/forceenter` (and so Killers), can be replayed in backtests, and keeps all logic in-process. It needs an explicit internal fail mode because of `default_retval=True`.
  2. REST locks pushed by the sentiment service. They need no strategy change, persist in the bot DB, expire on their own, can block one side only (`side="long"` for crash news), show up in FreqUI, and `"*"` gives a fleet-wide circuit breaker. They do not cover `/forceenter`, and they need REST credentials for every bot, which widens the auth surface that the 2026-08-30 hardening narrowed.
  3. RemotePairList blacklist via `file:///`. Fine for multi-hour exclusions such as hacks or delistings, but bounded by `refresh_period` (default 30 min). A missing or bad file stops the bot from starting, and after a failure the last list is kept indefinitely.
  4. `custom_stake_amount` / `leverage` for size-down rather than block.
  5. Producer/consumer. The data is candle-aligned per-pair dataframes, disconnect semantics are undocumented, the producer must be a Freqtrade instance, and it forces `process_only_new_candles=False`. Wrong tool.
  6. FreqAI. Sentiment can only enter as dataframe features, which needs long point-in-time history for training. A Santiment-infused fork of Freqtrade exists (see Q2), which suggests there is no first-class external-feature hook; I did not verify this in the FreqAI docs. Revisit only after months of collected data.
- **Retry leakage.** A denied entry is re-checked on every loop while the signal candle is current. The shadow log will show many denials per signal (deduplicate by `(bot, pair, side, candle_open)`). If the veto clears mid-candle, the trade can enter late at a worse price. Decide whether a veto should hold for the rest of the signal candle. A strategy-side `lock_pair` until the next candle is a simple way to do that.
- **The current Fear & Greed gate has two latent defects relevant to the new layer.**
  - (a) Unbounded staleness. After one success, a failing API leaves the last value in force indefinitely; at cold start the value is the neutral 50.
  - (b) During an alternative.me outage, every `confirm_trade_entry` call retries a blocking HTTP request with a 10 s timeout, because `last_fetch` is never updated on failure. That probably stalls the bot loop.

  The new gate should not repeat the pattern. Do no network I/O in callbacks, read a local file in `bot_loop_start`, check an explicit max age, and fall back to an explicit default.
- **Minimal gate shape** (design sketch, not tested):
  - `bot_loop_start` reads `/freqtrade/user_data/sentiment/state.json` (mtime-checked) into memory.
  - `confirm_trade_entry` checks `now - state.generated_at <= max_age` and looks up `state.veto[pair][side]` and `state.market.halt_long/short`.
  - If `mode == "shadow"` it logs `would_veto` and returns True; if `mode == "enforce"` it returns False.
  - It catches every exception itself and returns the chosen fail-mode value, logging `gate_error`.
- **Killers.** Adding a veto means adding `confirm_trade_entry` to `KillersScalpV1`, or having the receiver check the snapshot before it calls `/forceenter`. The receiver check has the advantage that it can record the reason in the receiver's own ledger. The memory note "no killers reload with TP-ladder open" applies to deploying either change.

### Gaps
- I did not fetch the FreqAI docs this session, so the claims about external-feature mechanics come from the fork's existence and from general knowledge.
- Producer disconnect and stale-data behaviour is not in the docs; it needs a source read of the `external_message_consumer` module.
- I did not check whether `/forceenter` enforces whitelist membership or the `force_entry_enable` flag text in 2026.10.
- Lock bypass by `/forceenter` comes from a static source read and should be confirmed with a dry-run test.

## Q2. Which open-source projects combine sentiment/news with crypto bots, and what is actually reusable?

### Takeaway
None of these projects is a drop-in sentiment veto for Freqtrade. The large LLM-agent frameworks are research or demo stacks: equity-centric, discretionary, API-key driven, and they produce no exchange orders. The reusable parts are narrower:
- exchange SDKs (ccxt and the Hyperliquid SDKs, already used indirectly through Freqtrade);
- OctoBot's architecture of one evaluator per source feeding a strategy matrix, as a design reference;
- TradingAgents' recent point-in-time data contract, as a methodology reference;
- NautilusTrader, if an event-driven engine is ever needed.

The operator's own Telethon observer and `claude -p` classifier is closer to the needed pattern than any of them.

### Cited Findings
GitHub API on 2026-11-03: stars, last push, license.

- **freqtrade/freqtrade.** 56,390 stars, pushed 2026-11-03, GPL-3.0 — [repo](https://github.com/freqtrade/freqtrade). I found no official sentiment integration. Third-party pieces: a PyPI package `lunarcrush-provider` that describes itself as a FreqTrade external data provider and needs a paid LunarCrush subscription — [PyPI](https://pypi.org/project/lunarcrush-provider/1.0.5/); a Codeberg fork, `5queezer/freqai`, with `include_santiment_data` in the FreqAI feature params, maturity unverified — [Codeberg](https://codeberg.org/5queezer/freqai). GitHub search found only tiny projects: `tickernelz/trading-bot` (0 stars, pushed 2026-10-26, GPL-3.0, "LLM voter swarm (median)" as an entry gate on Freqtrade), `Logashan/freqtrade-news-ml` (2 stars, 2025-08-14), `nicolasbanados/lunarcrush-trading-bot` (0 stars, 2026-04-19) and `fxmarty/binance-listing-announcement-bot` (2021-11-18). My GitHub and web searches found no CryptoPanic–Freqtrade integration; treat that as absence of evidence, not proof.
- **TauricResearch/TradingAgents.** 120,275 stars, pushed 2026-10-27, Apache-2.0, a multi-agent LLM framework built on LangGraph. Recent releases:
  - v0.7.0 (2026-10): runs on a ChatGPT Plus/Pro subscription; backtests scored from the first close after each decision.
  - v0.5.0 (2026-09): point-in-time integrity across every dated path.
  - v0.5.2: backtests that see only data published by each analysis date.
  - v0.3.1 (2026-07): "working crypto sentiment sources".

  Claude is reachable only through `ANTHROPIC_API_KEY` or Bedrock; there is no Claude-subscription path. It also supports Ollama and OpenAI-compatible endpoints. Crypto tickers use the `BTC-USD` form. The README calls it a research framework and not trading advice — [README](https://github.com/TauricResearch/TradingAgents).
- **hsliuping/TradingAgents-CN** (Chinese fork). 32,781 stars, pushed 2026-09-22, license NOASSERTION — [repo](https://github.com/hsliuping/TradingAgents-CN).
- **virattt/ai-hedge-fund.** 64,459 stars, pushed 2026-11-02, MIT. The README says it is a proof of concept for educational purposes only, not intended for real trading. It needs a model API key (Anthropic, OpenAI, DeepSeek and others) and has an equity-curve backtester — [repo](https://github.com/virattt/ai-hedge-fund).
- **AI4Finance-Foundation/FinRobot.** 8,363 stars, pushed 2026-10-24, Apache-2.0 — [repo](https://github.com/AI4Finance-Foundation/FinRobot). **FinGPT:** 21,522 stars, pushed 2026-10-25, MIT — [repo](https://github.com/AI4Finance-Foundation/FinGPT).
- **elizaOS/eliza.** 19,761 stars, pushed 2026-11-03, MIT, "agentic operating system" — [repo](https://github.com/elizaOS/eliza). `elizaOS/plugin-hyperliquid` returned 404 — [GitHub API](https://github.com/elizaOS/plugin-hyperliquid).
- **NoFxAiOS/nofx.** 13,193 stars, pushed 2026-10-21, AGPL-3.0, 515 open issues. Supports Binance USDT perps, Hyperliquid, OKX and Bitget. Some data uses paid "Claw402" routes, and the README carries exchange referral links — [README](https://github.com/NoFxAiOS/nofx).
- **HKUDS/AI-Trader.** 23,094 stars, last push 2026-06-11, no license detected — [repo](https://github.com/HKUDS/AI-Trader).
- **Xtra-Computing/CryptoTrade** (EMNLP 2024 reflective LLM crypto agent). 166 stars, last push 2024-12-01 — [repo](https://github.com/Xtra-Computing/CryptoTrade).
- **hummingbot/hummingbot.** 20,924 stars, pushed 2026-10-20, Apache-2.0 — [repo](https://github.com/hummingbot/hummingbot). `hummingbot/mcp` is archived (59 stars, last push 2026-03-23) — [repo](https://github.com/hummingbot/mcp).
- **jesse-ai/jesse.** 8,761 stars, pushed 2026-11-03, MIT — [repo](https://github.com/jesse-ai/jesse).
- **nautechsystems/nautilus_trader.** 31,199 stars, pushed 2026-11-03, LGPL-3.0, "Rust-native trading engine with deterministic event-driven architecture" — [repo](https://github.com/nautechsystems/nautilus_trader).
- **Drakkar-Software/OctoBot.** 6,886 stars, pushed 2026-11-02, GPL-3.0 — [repo](https://github.com/Drakkar-Software/OctoBot). Its `OctoBot-Tentacles` (176 stars, last push 2026-02-03, LGPL-3.0) has `Evaluator/Social` evaluators (`forum_evaluator`, `news_evaluator`, `signal_evaluator`, `trends_evaluator`) and service feeds for Google, Reddit, Telegram (bot and API), TradingView and Twitter — [OctoBot-Tentacles](https://github.com/Drakkar-Software/OctoBot-Tentacles).
- **SDKs:**
  - `hyperliquid-dex/hyperliquid-python-sdk`: 1,874 stars, last push 2026-06-04, MIT, 112 open issues — [repo](https://github.com/hyperliquid-dex/hyperliquid-python-sdk).
  - `nktkas/hyperliquid` (TypeScript): 451 stars, pushed 2026-09-30, MIT — [repo](https://github.com/nktkas/hyperliquid).
  - `ccxt/ccxt`: 44,702 stars, pushed 2026-11-03, MIT — [repo](https://github.com/ccxt/ccxt).
  - `sendaifun/solana-agent-kit`: 1,731 stars, last push 2026-05-14, Apache-2.0 (Solana, off-scope) — [repo](https://github.com/sendaifun/solana-agent-kit).

### Inferences
- **Maturity classes:**
  - **Production infrastructure:** Freqtrade, ccxt, NautilusTrader, Hummingbot, Jesse, the Hyperliquid SDKs.
  - **Research/demo agent frameworks:** TradingAgents, ai-hedge-fund, FinRobot, FinGPT, AI-Trader, CryptoTrade. Self-described research or educational, decision-per-ticker-per-day cadence, equity-centric data, no exchange risk plumbing.
  - **Commercial-leaning open source:** NOFX (AGPL, paid data routes, referral links).
  - **Abandoned or toy:** the GitHub search hits for Freqtrade sentiment and news.
- **What to borrow, not adopt:**
  - From OctoBot: one evaluator per source, normalised to [-1, 1] and combined in a matrix.
  - From TradingAgents v0.5: stamping every dataset with "published-at ≤ decision time" and recording run settings in every report.
  - From TradingAgents' TypeSafe step: screen out off-topic posts before scoring.

  None of these frameworks fits a veto whose decisions take milliseconds to seconds and run on the subscription CLI.
- **Constraint conflict.** TradingAgents and ai-hedge-fund reach Claude only through an API key or Bedrock, which conflicts with the operator's no-API-key rule. Using them would mean a different model vendor or local models via Ollama/OpenAI-compatible endpoints. That is another reason to keep the in-house `claude -p` classifier.
- **Licensing** (not legal advice). Freqtrade strategies run in-process under GPL-3.0, which is fine for private use. AGPL-3.0 (NOFX) imposes source-disclosure duties if a modified version is offered over a network. LGPL (Nautilus) is permissive for linking.

### Gaps
- I did not audit the code quality of OctoBot's `news_evaluator`, the LunarCrush provider package, or the Santiment fork; maturity is unverified.
- I found no Hummingbot or Jesse sentiment integrations, and no ElizaOS Hyperliquid plugin under the elizaOS org (it may live elsewhere).
- I did not check FinRobot's crypto-specific capabilities.

## Q3. What design patterns and scoring structures work for regime breakers, per-coin vetoes, event bots and sizing?

### Takeaway
Keep two separate outputs: a market-wide regime state and a per-coin veto list. Drive both from a deterministic scorer, not directly from LLM output. The LLM only labels individual items (event type, entity, polarity, severity, confidence). The scorer applies time decay, normalises volume against a rolling baseline (robust z-score), and requires conjunctions: polarity × volume × independent-source agreement, optionally plus price confirmation. Hard primary-source events (hack, delisting, depeg, exchange halt) get deterministic, TTL-bounded vetoes. Soft social sentiment should at most cut position size until shadow data supports it.

### Cited Findings
- **Santiment "Sentiment Weighted".** Sentiment balance times unique social volume. It stays near 0 when volume is high but sentiment is mixed, and also when polarity is strong but volume is low — [Santiment Academy](https://academy.santiment.net/metrics/sentiment-metrics/weighted-sentiment-metrics/). That is a volume-gated conjunction built into the metric.
- **Santiment "Sentiment Volume Consumed".** A rolling z-score of unique social volume × sentiment balance over a sliding window — [Santiment sentiment metrics article](https://santiment.github.io/articles/sentiment-metrics). A third-party doc uses a z-score above +2 to mean statistically significant conviction (secondhand; it also conflicts with the Academy's "sum of scores" unit) — [CryptoBuzz docs](https://cryptobuzz.gitbook.io/cryptobuzz-docs/metrics/weighted-sentiments).
- **OctoBot** splits social input into per-type evaluators (news, forum, trends, signals) fed by per-platform service feeds — [OctoBot-Tentacles](https://github.com/Drakkar-Software/OctoBot-Tentacles).
- **TradingAgents' Sentiment Analyst** can screen StockTwits and Reddit posts with an external model, dropping posts not about the asset and counting the rest by stance (bullish/bearish/neutral/unclear). This is a relevance filter applied before scoring — [TradingAgents README](https://github.com/TauricResearch/TradingAgents).
- **Freqtrade levers by granularity:**
  - side-aware pair locks (`long`/`short`/`*`) with an expiry `until`, global via `"*"` — [interface.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/strategy/interface.py), [pairlock_middleware.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/persistence/pairlock_middleware.py);
  - per-entry block via `confirm_trade_entry`;
  - size via `custom_stake_amount`;
  - leverage via the `leverage` callback.

  Source for the last three: [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).

### Inferences
These are design proposals, to be pre-registered before they are tuned.

- **Item schema (LLM output).** `{item_id, entities:[symbol], event_type ∈ {hack_exploit, delist_or_monitoring, depeg, exchange_halt, regulatory_action, listing, unlock, macro, partnership, fud_rumor, price_commentary, other}, polarity ∈ [-1,1], severity ∈ {0,1,2,3}, is_primary_source, is_rumor, confidence, rationale≤20 words}`. Validate `entities` against the exchange market map, and drop unknown symbols.
- **Source weighting.** Use an explicit tier table, not learned weights:
  - tier 1: exchange announcement APIs, official project or exchange accounts, on-chain incident monitors;
  - tier 2: established news wires;
  - tier 3: social accounts above a follower or age floor.

  Cap each account at a maximum contribution per window.
- **Per-coin score.** `S_i(t) = Σ_k w_source × confidence × polarity × severity × exp(-(t − received_at_k)/τ_type)` with type-specific half-lives (for example a rumor ≈ 2 h, a hack ≈ 24–72 h). Use `received_at` (our clock), never the publisher timestamp. Volume anomaly: `z_i(t) = robust_z(log1p(mentions_1h))` against a 30-day same-hour baseline, using median/MAD so that one-off spikes do not inflate σ.
- **Per-coin veto (long side).** Require all of:
  - `S_i ≤ −θ_S`;
  - `z_i ≥ θ_z` (for example 3);
  - either ≥2 independent sources (distinct domains or authors after dedup) or ≥1 tier-1 hard event.

  Optionally also require price confirmation, such as the coin underperforming BTC over the last 60 min. Issue it as a lock or veto with `until = now + TTL_type` and hysteresis: it clears only when the score recovers past `θ_S/2` and a minimum hold has elapsed. A hard tier-1 event (hack, delist, depeg) vetoes longs deterministically, with no z or agreement requirement.
- **Market regime (circuit breaker).** Three states: `normal` → `caution` (stake ×0.5, leverage capped) → `halt_long` (global long lock). Drive it from:
  - a market-wide negative-mass z-score across BTC, ETH and "crypto" entities;
  - tier-1 systemic events (major-exchange hack or halt, stablecoin depeg);
  - optionally, existing price-based guards (the BTC trend guard).

  Require two consecutive snapshots to escalate. De-escalate one level at a time with a minimum dwell, to avoid flapping.
- **Scheduled macro blackout** (CPI, FOMC, NFP). This is a calendar, not NLP. Block new entries or size down from about 15–30 min before to 30–60 min after the release. It is the cheapest gate to build and the easiest to backtest point-in-time, since the calendar is known in advance.
- **Sizing modulation.** Use only multipliers ≤1 (1.0 / 0.5 / 0) until shadow evidence justifies anything else. Never let sentiment raise size or leverage on existing strategies. That keeps its worst case at "missed trades", not "bigger losses".
- **Event-driven standalone bot.** A narrow whitelist of hard events with a fixed playbook each, for example:
  - exploit or hack of token X → short X perp on Hyperliquid if listed, entering only after confirmation, with a time stop;
  - delisting or monitoring-tag notice → short or avoid;
  - listing on a major venue → long on a venue where it already trades.

  Each playbook gets its own pre-registration, stake cap and time-based exit. Prefer reacting to a confirmed post-event drift over racing the headline (see Q6).
- **Cooldowns.** Implement them as lock TTLs (pair or global). They persist across restarts in the bot DB and expire on their own, so no cleanup job is needed.

### Gaps
- I found no practitioner source giving empirically validated half-lives, z thresholds or agreement rules for crypto news. All numbers above are placeholders to pre-register and test.
- Whether price confirmation helps or just adds lag is untested.

## Q4. Fail-open or fail-closed? How should staleness and manipulation be handled?

### Takeaway
Choose the failure mode per layer and make it explicit, because Freqtrade's own defaults fail open (callback exceptions → trade allowed; stake exceptions → proposed stake) and the existing Fear & Greed code fails open silently, with no staleness bound.
- **Soft sentiment veto:** fail-open with an alarm. A dead feed must not freeze a fleet whose edge never depended on it.
- **Active halts and hard-event vetoes:** sticky. They hold until their TTL even if the feed dies.
- **The news bot itself:** fail-closed. No fresh data means no new trades.

Because sentiment can only remove or shrink trades on existing bots, a manipulation attack costs opportunity, not capital.

### Cited Findings
- **Freqtrade defaults.** `confirm_trade_entry` exceptions return `default_retval=True`, so the trade proceeds — [strategy_wrapper.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/strategy/strategy_wrapper.py), [freqtradebot.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py). A `custom_stake_amount` exception falls back to `proposed_stake` — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).
- **RemotePairList** keeps the last list on fetch failure by default. Its first-fetch failure is fatal (`OperationalException`), and an empty list is valid and cached — [RemotePairList.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/plugins/pairlist/RemotePairList.py), [Plugins docs](https://www.freqtrade.io/en/stable/plugins/).
- **Locks** can only be extended (count up) and carry an explicit `until` — [interface.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/strategy/interface.py).
- **Local: Fear & Greed gate.** The cache starts at the neutral value 50, and the old value survives indefinitely on fetch errors. Fetch errors are retried on every call because `last_fetch` updates only on success — [../../../../ft_userdata/user_data/strategies/market_intelligence.py](../../../../ft_userdata/user_data/strategies/market_intelligence.py).
- **Local: Killers classifier.** It shells out to `claude -p ... --output-format json` with a 10 s default timeout and returns None on timeout or parse failure. A separate `rules_classifier.py` and `confidence_gate.py` exist — [../../../../killers_bot/classifier.py](../../../../killers_bot/classifier.py).
- **Santiment's weighted-sentiment design** keeps strong polarity at low volume near zero, which dampens isolated-account noise by construction — [Santiment Academy](https://academy.santiment.net/metrics/sentiment-metrics/weighted-sentiment-metrics/).

### Inferences
- **Staleness model.** The snapshot carries:
  - `generated_at`;
  - for each source, `last_poll_ok_at` (a heartbeat) and `last_item_at`;
  - `classifier_last_ok_at`;
  - `mode` (shadow/enforce).

  "Quiet" (heartbeat fresh, no items) is not "dead" (heartbeat stale): judge staleness by poll heartbeats, not by item arrival.

  Gate rules:
  - snapshot older than `max_age` (for example 3× the scorer interval) → status `STALE`; soft vetoes are ignored (fail-open), hard-event vetoes and halts already issued keep their TTL;
  - ≥50% of tier-1 sources dead → `caution` sizing, not halt;
  - classifier dead → fall back to the rules classifier for hard-event keywords only.
- **Observability** (fits the existing Prometheus setup): `sentiment_snapshot_age_seconds`, `sentiment_source_heartbeat_age_seconds{source}`, `sentiment_classifier_failures_total`, `sentiment_gate_state{state}`, `sentiment_veto_decisions_total{bot,mode,reason}`. Alert on staleness. Add a nightly health-report section with vetoes, staleness minutes and counterfactual P&L.
- **Manipulation resistance:**
  - deduplicate (canonical URL plus SimHash/MinHash over normalised text) before counting volume;
  - cap each author per window and apply account-age and follower floors;
  - require independent-source agreement for soft vetoes;
  - make hard events need tier-1 primary sources;
  - optionally require price confirmation;
  - use median rather than mean across sources.

  Because sentiment only removes or shrinks trades on existing bots, the attack surface is "induce a missed trade". The news bot must never enter on social-only signals.
- **Prompt injection.** Tweets and articles are untrusted input to the classifier. Run the CLI with no tools or MCP servers, a fixed JSON schema and a short output. Validate symbols against the market map, and discard any field outside the schema. The existing classifier already parses strictly and returns None on bad output.
- **Freshness of the Fear & Greed gate itself.** Give it the same treatment: async or background refresh in `bot_loop_start`, a maximum age (for example 36 h, since the index updates daily), and an explicit default. That is a separate small fix that is worth doing first.

### Gaps
- I found no rigorous public evaluation of shill-detection heuristics for crypto social data. The heuristics above are standard practice, not measured in this context.
- I did not verify whether Freqtrade's main loop blocks during a slow `confirm_trade_entry`. This is very likely, since the loop is synchronous, but it is untested here.

## Q5. How can a veto gate and a news bot be validated honestly?

### Takeaway
Separate two questions:
1. Signal validity: does a negative score predict worse forward returns? This can be tested on a large panel of coin-hours.
2. Fleet impact: does vetoing this fleet's entries raise P&L or cut drawdown? This has a small N and is path-dependent.

Start collecting point-in-time data, keyed on our own `received_at` clock, now. Only forward-collected, forward-classified data is truly out of sample. Historical LLM labelling must be split at the model's cutoff or anonymised. Pre-register thresholds, the minimum N and the decision rule in `ft_userdata/preregistrations.json`. Label the shadow period as its own epoch.

### Cited Findings
- **Replay in Freqtrade backtests.** Backtesting calls `confirm_trade_entry`, `custom_stake_amount` and, once per candle, `bot_loop_start`. A gate that reads a time-indexed snapshot history can therefore be replayed through Freqtrade's own backtester — [backtesting.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/optimize/backtesting.py), [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).
- **Look-ahead bias, cutoff split.** A late-2025 paper uses Llama-3.3-70B's December 2023 cutoff to define in-sample (2012–2023, 91,357 headline-day observations, 1,587 firms) and out-of-sample (2024) windows. It finds the LLM signal is amplified where the model appears to recall outcomes — [arXiv 2512.23847](https://arxiv.org/pdf/2512.23847). A 2026 ABFER slide deck reports the apparent memorisation measure collapsing at the training cutoff — [ABFER 2026 slides](https://abfer.org/media/abfer-events-2026/annual-conference/slides-tech-ai/260518-AI-A-Test-of-Lookahead-Bias-in-LLM-Forecasts.pdf). (Both summarised from search results; full text not read.)
- **Look-ahead bias, anonymisation.** Glasserman & Lin anonymise company names in headlines. In sample, anonymised headlines did better, which they attribute to a "distraction" effect from general company knowledge outweighing look-ahead bias — [arXiv 2309.17322](https://arxiv.org/html/2309.17322v1).
- **Look-ahead bias, chronologically consistent models.** ChronoBERT trains models with rolling cutoffs to remove look-ahead bias. It reports modest effects in its asset-pricing test and says the bias is model- and application-specific — [arXiv 2502.21206](https://ar5iv.labs.arxiv.org/html/2502.21206).
- **Framework practice.** TradingAgents added "point-in-time integrity across every dated path" (v0.5.0, 2026-09) and backtests that see only data published by each analysis date (v0.5.2) — [TradingAgents README](https://github.com/TauricResearch/TradingAgents).
- **Local.** The Killers observer schema already separates `received_at`, `posted_at` and `edited_at` in `raw_messages` (SQLite) — [../../../../killers_bot/schema.sql](../../../../killers_bot/schema.sql). A pre-registration file exists at [../../../../ft_userdata/preregistrations.json](../../../../ft_userdata/preregistrations.json). The repo rules require keeping paper, live and historical epochs distinct — [../../../../AGENTS.md](../../../../AGENTS.md).

### Inferences
- **Shadow ledger** (one row per deduplicated decision): `(decision_id, bot, strategy, pair, side, signal_candle_open, decided_at, entry_tag, price_at_decision, gate_mode, would_veto, reasons[], snapshot_id, snapshot_age_s, S_i, z_i, regime, fail_mode_applied)`. Also log non-vetoed decisions with the same fields, because the comparison group matters as much as the vetoed group. Deduplicate retries by `(bot, pair, side, signal_candle_open)` (see Q1).
- **Counterfactual P&L, two levels:**
  - **Quick:** for each would-veto entry that actually executed in shadow mode, its realised trade P&L is the counterfactual cost or benefit of vetoing it. This is direct, because in shadow mode the trade really happened.
  - **Correct:** replay the full strategy through Freqtrade backtests with the recorded snapshot history, gate on and gate off. A veto frees a `max_open_trades` slot, which changes later trades, so summing vetoed P&L is biased.
- **Signal-level panel test** (large N): for every coin-hour, compute forward 1/4/24 h returns, excess over BTC, against the score buckets and veto flag. This answers "is there information?" with thousands of observations even while fleet vetoes number in the dozens. Correct for overlapping horizons (block bootstrap by day) and for cross-coin correlation (cluster by time).
- **Sample-size arithmetic** (illustrative). If per-trade return SD is about 3% and the aim is a 1-percentage-point mean difference between vetoed and allowed trades at roughly 2σ, the requirement is about 2·(2·3/1)² ≈ 72 trades per group. At a fleet rate of tens of entries per month and a veto rate of about 10%, that takes many months. Hence:
  1. pre-register a decision rule that tolerates small N, for example "enforce only hard-event vetoes; soft vetoes stay shadow until N ≥ X and the panel test passes";
  2. evaluate drawdown and tail outcomes, not only the mean.
- **Rare-event market halts.** Evaluate them as event studies: list every would-halt episode and the fleet's outcomes in the following 24 h. Pre-register the episode definition so that episodes cannot be picked after the fact.
- **LLM look-ahead rules:**
  - (a) Only items classified at receipt time count as out-of-sample.
  - (b) For historical backfill, use only news dated after the classifier model's training cutoff, or anonymise tickers and project names. Note that anonymisation hurts crypto badly, because the ticker is the signal.
  - (c) Store `model_id`, `prompt_hash` and `classified_at` per item, and never reclassify history with a newer model and mix it with older labels.
  - (d) Treat the subscription CLI's model as a moving target: a silent model upgrade is a regime change and should be logged.
- **Pre-registration contents:**
  - hypotheses (H1: vetoed long entries have lower mean and worse tail P&L than allowed entries; H2: halt episodes precede fleet drawdown);
  - thresholds (θ_S, θ_z, half-lives, TTLs) frozen at registration;
  - metrics, minimum N and evaluation date;
  - the decision rule (enforce / stay shadow / kill);
  - the multiple-testing plan. If more than a few threshold sets are tried, keep a holdout period and apply the deflated-Sharpe or false-discovery discipline the project already uses.
- **News bot.** Dry-run first, with fills stressed: add adverse slippage of at least 0.5–1% on event entries, in line with the project's Cascade fill-stress practice. Count every event, including those skipped for liquidity, so that survivorship does not flatter results.

### Gaps
- I found no published methodology specific to sentiment-veto evaluation, such as shadow-mode counterfactual standards. The approach above is assembled from general backtesting practice.
- Per-trade return SD for this fleet was not computed. The sample-size figure is illustrative and should be recomputed from the fleet's trade DBs.

## Q6. What are the execution realities for a news bot on Hyperliquid and Binance?

### Takeaway
A VPS retail stack with an LLM in the loop has a realistic news-to-order latency of several to tens of seconds. Hyperliquid's own order round-trip is about 0.2 s median when co-located and about 0.9 s from AWS Tokyo. Headline-speed competition is measured in milliseconds and is lost before it starts, and the one controlled academic attempt at listing-sniping lost money. Target slower post-news drift (minutes to hours) and confirmed events. Use limit or IOC entries with explicit slippage caps, and keep stakes small.

### Cited Findings
- **Hyperliquid latency (official).** For a geographically co-located client, end-to-end order latency is 0.2 s median and 0.9 s at p99 — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/overview).
- **Hyperliquid latency (independent).** Glassnode's monitor recorded a median of 884 ms for market orders from AWS Tokyo across 120 samples in March 2026. It attributes almost all of that to server-side processing, and labels itself a research project — [Glassnode latency monitor](https://latency.glassnode.com/hyperliquid/fill-latency).
- **Hyperliquid rate limits:**
  - 1,200 REST weight per minute per IP. Exchange actions weigh 1 (batched: `1 + floor(n/40)`); most info requests weigh 20.
  - WebSocket: max 10 connections and 1,000 subscriptions per IP.
  - Address limit: 1 request per 1 USDC traded cumulatively, plus an initial 10,000-request buffer. When exceeded, 1 request every 10 s, with a higher cancel allowance.
  - Default limit of 1,000 open orders.

  Source: [Hyperliquid rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).
- **Listing-sniping thesis.** A University of Economics, Prague thesis built notification and trading bots for exchange listings. It found profitable trading not achievable at the required latency (network response times in the tens of ms were the limiting factor) and lost 40% of invested funds in real testing — [VŠE thesis record](https://vskp.vse.cz/english/98688).
- **Practitioner anecdotes** (unverified, forum). About 40–50 ms was the lowest polling interval on Binance's announcement endpoint without rate-limiting. Snipes "always got a bad price", and Telegram alert channels were faster — [r/algotradingcrypto thread (mirror)](https://redlib.hbubli.cc/r/algotradingcrypto/comments/1ktgys6/algo_crypto_sniping). A listing-alert vendor claims under 1 ms dispatch (vendor claim) — [cryptolistingws docs](https://cryptolistingws.gitbook.io/docs/introduction.md).
- **Local.** The existing classifier's `claude -p` call has a 10 s default timeout — [../../../../killers_bot/classifier.py](../../../../killers_bot/classifier.py). Freqtrade's loop throttle is about 5 s by default — [Strategy callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/).

### Inferences
- **Latency budget** (estimates; measure in MVP):
  - provider or source delivery: seconds for social and news APIs, typically more for RSS;
  - dedup and prefilter: about 10 ms;
  - LLM classification via the CLI: about 3–10 s including process start (the 10 s timeout implies seconds-scale);
  - scorer and snapshot interval: 5–30 s;
  - Freqtrade loop or `/forceenter`: up to about 5 s;
  - Hyperliquid order: about 0.2–0.9 s.

  Total: about 10–60 s. That fits post-news drift and veto use, not first-move trading.
- **Fast path for hard events.** Rules or keyword triggers on tier-1 primary sources (exchange announcement endpoints, official accounts) can skip the LLM and issue a provisional veto in under 1 s, with the LLM confirming or revoking. This is safe for vetoes and unsafe for entries.
- **Slippage on news spikes.** Use limit or IOC orders with a max deviation from mid. Backtest with stressed fills. The Hyperliquid address-based limit scales with cumulative traded USDC, so a small account doing many cancel-replace cycles can hit the address limit during exactly the volatile minutes that matter. Batch and minimise order churn.
- **Venue choice for the news bot.** Hyperliquid perps allow shorting on bad news (exploit → short) and are already in the fleet. Binance spot permits only "long or avoid" reactions.

### Gaps
- I found no measured end-to-end latency for X/Twitter provider delivery, or for `claude -p` cold-start on the VPS. Both should be instrumented in the MVP. The killers-receiver logs may already contain classifier latency, but I did not check them.
- I found no rigorous public evidence on post-news drift duration in crypto; that is covered by the evidence researcher.

## Q7. What would an MVP cost, and how complex would it be?

### Takeaway
The MVP is small: about 5 components and roughly 1.5–3k lines of Python. It fits on the existing VPS, with SQLite (WAL) as the event store, the existing Prometheus for gauges, and no new database. The binding constraint is the Claude Max weekly usage cap, which is shared with the operator's interactive use. Exact token budgets are unpublished, so the classifier must prefilter aggressively, batch items, and degrade to rules when the CLI is throttled.

### Cited Findings
- **Claude subscription limits** (third-party sources). Headless `claude -p` signed in with a plan draws from that plan's limits. Max has two weekly limits (all models, and Sonnet-class), and Anthropic does not publish fixed token numbers — [alexcloudstar guide](https://alexcloudstar.com/md/blog/claude-code-usage-limits-2026/), [claude-monitor guide (Oct 2026)](https://claude-monitor.com/claude-usage-limits). A June 2026 post says `claude -p` and Agent SDK usage would move into a separate monthly credit — [DEV Community post](https://dev.to/jovan_chan_9500711396d4e6/claude-code-agentic-api-rate-limits-in-june-2026-what-the-new-credit-separation-means-for-solo-1kal). Later third-party guides say plan-signed `claude -p` still draws plan limits, and the search results described the separate credit as announced and then paused. The reports conflict. These are not primary Anthropic sources, so the current policy should be checked with `/usage` and `/status`.
- **Reusable local pieces:**
  - Telethon observer writing SQLite `raw_messages` with `received_at`, `posted_at` and `edited_at` — [../../../../killers_bot/schema.sql](../../../../killers_bot/schema.sql);
  - `claude -p --output-format json` classifier with strict JSON schema and timeout handling, a rules classifier and a confidence gate — [../../../../killers_bot/](../../../../killers_bot/);
  - FastAPI receiver calling `/forceenter` — [../../../../services/killers-receiver/app/main.py](../../../../services/killers-receiver/app/main.py).
- **Freqtrade-native veto plumbing needs no new dependencies:** a local file read, `confirm_trade_entry`, `/locks`, and RemotePairList with `file:///` — [Plugins docs](https://www.freqtrade.io/en/stable/plugins/), [api_trading.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/api_server/api_trading.py).

### Inferences
- **Components and rough size:**
  1. Source pollers or streamers (1 per source, about 100–200 LOC each).
  2. Normaliser and dedupe with symbol mapping (about 200–300 LOC).
  3. Classifier worker, reusing `classifier.py`'s subprocess, timeout and JSON-validation pattern with a batch prompt (about 200–300 LOC).
  4. Deterministic scorer and snapshot writer (about 300–500 LOC, the core of the testable logic).
  5. `market_intelligence.SentimentGate` for the strategies, plus shadow-ledger writes (about 150–250 LOC).
  6. Metrics, health-report section and a nightly counterfactual job (about 300–500 LOC).

  Testing should centre on the pure scorer and the gate's fail-mode table, both network-free and in line with the repo's test policy.
- **Storage.** SQLite in WAL mode with tables `items_raw`, `items_classified`, `snapshots` (point-in-time history) and `gate_decisions`. Even 50k items a day is about 18M rows a year, which SQLite handles. Consider Postgres or Timescale only if multi-writer contention appears. Prometheus is for gauges and counters, not an event store: keep per-item data out of labels.
- **LLM throughput plan:**
  - The cheap prefilter drops more than 80–95% of items (price chatter, duplicates, unknown symbols, tier-3 accounts under the follower floor).
  - Batch 20–50 headlines per CLI call, with short JSON rows out.
  - Classify hard-event candidates immediately; send soft items in batches every 5–15 min.

  With a few thousand raw items a day, that is about 20–150 CLI calls a day. That is likely well within a Max plan, but unverified since the token budgets are unpublished. Measure the consumption shown by `/usage` during the shadow phase. When the CLI is throttled, keep hard-event rules active and mark soft scores stale, so the gate fails open on soft vetoes per Q4.
- **Money.** Incremental infrastructure cost on the existing VPS is about zero. Data-provider fees are the main variable and are covered by the provider researcher. The Max subscription is already paid.

### Gaps
- I found no authoritative Anthropic statement in this session on current Max weekly limits or on how `claude -p` is metered, so the throughput figure is an estimate.
- I did not measure the existing classifier's tokens per message or its latency.

## Q8. What reference architecture and MVP sequencing follow?

### Takeaway
Build one sentiment service, with collectors → classifier → deterministic scorer → versioned snapshot file plus SQLite history. Every bot reads it through one `SentimentGate` in `market_intelligence.py`, starting in shadow mode. Add a standalone event bot later, using the proven receiver-and-`/forceenter` pattern. Sequence the work to start the point-in-time data clock as early as possible, because honest evaluation needs weeks to months of forward-collected data, and to fix the existing Fear & Greed gate's fail-mode first.

### Cited Findings
- `confirm_trade_entry` gates both strategy entries and `/forceenter` new positions, and is called in backtests. Locks are side-aware, TTL-bounded and settable over REST, but `/forceenter` bypasses them — [freqtradebot.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py), [rpc.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/rpc.py), [backtesting.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/optimize/backtesting.py), [api_trading.py](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/rpc/api_server/api_trading.py).
- The existing observer, classifier and receiver pattern and its storage conventions — [../../../../killers_bot/classifier.py](../../../../killers_bot/classifier.py), [../../../../killers_bot/schema.sql](../../../../killers_bot/schema.sql), [../../../../services/killers-receiver/app/main.py](../../../../services/killers-receiver/app/main.py).

### Inferences

**Reference architecture (components and data flow):**

```
 SOURCES                       SENTIMENT SERVICE (new container on VPS, no exchange keys)
 ───────                       ─────────────────────────────────────────────────────────
 X/Twitter provider ──┐
 News API / RSS ──────┤   [1] collectors ──► items_raw (SQLite WAL; received_at = our clock)
 Exchange announce ───┤         │ heartbeat per source ──► Prometheus
 Telegram news chans ─┘         ▼                         (REUSE Telethon observer pattern)
 (Telethon, reused)       [2] normalise + dedupe + symbol map + source tier/author caps
 Macro calendar ─────────►      │            │
                                │            └─► fast path: tier-1 hard-event rules (<1 s)
                                ▼
                          [3] classifier worker: `claude -p --output-format json`, batched,
                              strict schema, no tools; rules fallback
                              (REUSE killers_bot/classifier.py + rules_classifier.py pattern)
                                ▼  items_classified (model_id, prompt_hash, classified_at)
                          [4] deterministic scorer (pure function, unit-tested):
                              decay · robust z · multi-source agreement · hysteresis · TTLs
                                ▼
                          [5] snapshot writer ──► state.json (atomic rename, generated_at,
                              per-source heartbeats, regime, veto{pair:{side,until,reasons}},
                              size_mult) + snapshots table (point-in-time history)
                                │                     │
            ┌───────────────────┘                     └──► optional: POST /locks to bots that
            ▼                                              don't use /forceenter (side-aware TTL)
 FREQTRADE BOTS (FF, Keltner, OITrend, ShortKeltnerHL, Killers)
   market_intelligence.SentimentGate
     bot_loop_start: read state.json (local file, no network)
     confirm_trade_entry: staleness check → shadow log / enforce veto (explicit fail-mode)
     custom_stake_amount / leverage: size_mult ≤ 1
   Killers: same gate in KillersScalpV1.confirm_trade_entry (covers /forceenter)
     and/or killers-receiver pre-check before /forceenter (records reason in receiver ledger)
            │
            ▼
 gate_decisions ledger ──► nightly counterfactual job ──► health report + Prometheus
                                                          (vetoes, staleness, cf-P&L)

 STANDALONE NEWS BOT (later): event queue (hard events only) ──► news-receiver
   (REUSE killers-receiver FastAPI + /forceenter + reconcile pattern) ──► dedicated
   Freqtrade instance on HL perps, dry-run first; limit/IOC, stake cap, time stop.
```

**MVP sequencing (what to build first to learn fastest):**
- **Step 0: harden what exists (1 small PR).**
  - Fix the `FearGreedIndex` fail-mode: refresh in `bot_loop_start` with a back-off on failure (also update a `last_attempt`), set a maximum age, add explicit fail-open logging, and add a staleness metric.
  - Add structured gate-decision logging to the shared module.

  Learning: it establishes the decision ledger format and removes the 10 s blocking retries.
- **Step 1: start the data clock, no trading influence.** Build collectors for 1–3 sources: exchange announcement endpoints (tier-1 and cheap), one news aggregator, and Telegram news channels via a second Telethon observer instance (direct reuse). Write `items_raw` with `received_at`, add the source heartbeats and the Prometheus gauges. Learning: real volumes, duplication rates, symbol-mapping misses and source uptime. Without this there is nothing to evaluate.
- **Step 2: classify and score in shadow mode.** Add the batched `claude -p` classifier (reusing the Killers pattern), the deterministic scorer and the snapshot writer, plus `SentimentGate` in every bot with `mode="shadow"`. Pre-register thresholds, half-lives, metrics, the minimum N and the decision date in `preregistrations.json` *before* turning shadow on. Learning: CLI usage per day, classifier latency, would-veto frequency, and early panel-test signal.
- **Step 3: enforce the narrowest, highest-confidence piece first.** Enforce two pieces:
  - hard-event vetoes from tier-1 sources (hack or exploit, delisting or monitoring tag, depeg or exchange halt), side `long`, with a TTL;
  - the scheduled macro blackout, which is calendar-based and fully backtestable.

  Keep soft social-sentiment vetoes and size-down in shadow until the pre-registered N and panel test pass. Learning: real-world effect with the minimum blast radius.
- **Step 4: standalone event bot, dry-run.** Pick one event class with a clear direction and a liquid Hyperliquid perp (for example exploit → short). Build the news-receiver by cloning the killers-receiver pattern (auth, idempotency, reconcile, `/forceenter`). Enter on confirmation, not on the first headline, with stressed-slippage paper accounting. Promotion follows the project's graduation gates. Merging the code does not authorise live deployment.
- **Step 5 (only if earlier phases show information): enrichment.** Add the X/Twitter provider at scale and per-coin soft scores feeding sizing, optionally FreqAI features once months of point-in-time history exist.

**Why this order:** the slowest dependency is evidence (forward point-in-time data plus enough veto events), not code. Steps 0–2 are cheap, carry zero trading risk and start that clock. Step 3 enforces only vetoes whose logic is close to deterministic and whose worst case is a missed trade.

### Gaps
- The architecture assumes the provider choices made by the other researchers. Source tiers and polling cadences must be filled in from their notes.
- The Step 3 enforcement rules for Killers depend on confirming at runtime that `/forceenter` bypasses locks and goes through `confirm_trade_entry`, in a dry-run instance.
