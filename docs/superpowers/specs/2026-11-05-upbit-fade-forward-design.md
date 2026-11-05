# Upbit KRW listing fade: paper forward monitor (design)

Issue #229. Status: approved by the operator for build ("Sim, monta o dry-run", 2026-11-05).
Everything marked *Claude's call* was decided by Claude, not by the operator.

## Why

Part C Phase 2 (#248, main 9991e23; #229 comment 6664557105) measured shorting Hyperliquid
perps 5 min after an Upbit KRW-addition notice. These are proxy results on Binance prices.

- **+24 h hold:** +7.4% mean net per announcement, interval [+2.9%, +11.4%], win rate 81%,
  positive in 2024, 2025 and 2026 (n = 57). The interval stays above zero with stress costs
  and Bonferroni over 9 tests.
- **+4 h hold** (the registered primary): not determinable.
- **Adverse excursion:** p90 is 24.8% and the maximum 48.7%.

The result is not executable evidence: the prices are Binance proxies, funding is not
modelled, and detection was assumed. This monitor measures the same rule forward, with real
Hyperliquid order books and funding. **It places no orders and holds no keys.**

## Goals

- Detect every Upbit KRW-addition notice on the VPS within minutes.
- Apply the bot-knowable Part C eligibility at t0.
- Record a paper short at t0 + 5 min and its exit 24 h later. Both fills come from
  walking the live Hyperliquid L2 book for a fixed notional, plus the taker fee and the
  real funding over the hold.
- Record the +30 m and +4 h checkpoints, MAE and MFE from 1 m candles, and the detection
  latency.
- Resolve with the A4 rule after a preregistered number of events.

Non-goals: live orders, stops, sizing logic, Telegram trading commands. Anti-goals:
touching `listing-short-forward-2026-07`, `research/listing_short_forward/`, any running bot
or container.

## Detection

- **Primary:** the PIT news archive (`research/news_archive/data/archive.sqlite`), opened
  read-only through WAL. Its Tree of Alpha source relays Upbit notices. The CARDS KRW addition
  on 2026-11-05 was published at 06:03:04Z and received at 06:03:43Z.
  - Every 15 s, read with durable cursors over **both** `items` (`item_pk`) and
    `item_revisions` (`rev_pk`). A revised title can turn into a listing.
  - Take Tree items whose `url` is an `upbit.com/service_center/notice` page, and deduplicate
    them per notice id (the url `id`).
  - Classify with `nes_classify.upbit_addition` and `upbit_krw_membership` (title, plus the
    body when present), by import.
  - Upbit notices that mention 거래지원 or 마켓 but don't classify go to an `unclassified`
    queue in the status output and are never traded.
  - Gap diagnostics come from the archive's `gaps` and `polls` tables.
- **Audit:** poll `api.upbit.com/v1/market/all` every 5 min and store each timestamped
  snapshot. It answers from the VPS, while the announcements API returns 403. A new `KRW-*`
  market with no matched notice is logged as a missed detection. The audit shows missed
  market additions, but it cannot recover a notice's time or prove that detection was
  complete. *Claude's call.*
- **t0 and timing:**
  - t0 is Tree's `published_at`, and `received_at` is kept too. Part C used Upbit
    `first_listed_at`, which is not readable from the VPS.
  - This is a **Tree-clock cohort**. Tree's time is checked only for plausibility, not
    for equivalence with Upbit's, and every report says so.
  - Timing is flagged `unverified` when `published_at` is missing, is later than
    `received_at`, or lags it by more than 5 min. Unverified events are reported but left
    out of the comparable cohort.

## Eligibility at t0 (Part C rules a bot can know, with evidence from that time)

- **Excluded** when:
  - the token already trades on Upbit KRW: it is in the last `market/all` snapshot taken
    before t0 (no snapshot within 15 min before t0 → `unknown`);
  - a Binance new-listing notice for it falls within the 24 h *before* t0 (the archive's
    `binance_listing` source). A notice published *after* t0 never excludes;
  - the notice body says trading began before the notice.
- **Hyperliquid eligibility** is the Part C rule. Reuse `nes_venues.hl_facts` /
  `hl_status`: the perp is in `meta` and `fundingHistory` shows records in the 24 h
  before t0, including one in the last hour.
- **Comparable cohort** (the decision set) also requires:
  - **a known trading start:** the notice body states a start time at or after t0, read with
    `nes_classify.upbit_trading_start_ms`. With no body, or no start in it, the event goes
    to the descriptive cohort;
  - **a Binance market before t0:** Binance 1 m klines (USDⓈ-M `fapi/v1/klines` first, else spot
    `api/v3/klines`, the Part C proxy order in `nes_venues.binance_candidates`) show trading in [t0 − 10 min, t0). That is evidence from before t0,
    not today's `exchangeInfo`;
  - **the Binance leak test passed:** |drift| ≤ 2% between those klines' closes at
    t0 − 10 min and t0 − 2 min, the Part C rule. The same test on Hyperliquid candles is
    descriptive;
  - **a timely entry:** filled within 2 min of t0 + 5 min. Later entries, up to the 10 min
    deadline, are `delayed` and descriptive.
- Every other Hyperliquid-eligible event is still measured and reported as the
  **descriptive cohort**.

## Paper trade

- **Entry** at max(t0 + 5 min, detection). Read `l2Book` and sell about 100 USDC into the
  bids, then freeze the exchange-valid quantity **q** (rounded to `szDecimals`).
  - Record the VWAP, mid, best bid and ask, levels used, book time and any delay.
  - A book older than 5 s, or depth below q, is `rejected` for that attempt.
  - Part C priced the close of the 1 m candle that contains t0 + 5 min; the difference is
    noted, not corrected.
- **Exit** at entry + 24 h: buy back **q** from the asks, with the same checks.
  **Checkpoints** at +30 m and +4 h are book-walk marks of q only.
- **Fee:** 4.5 bps taker on each leg's actual notional. No extra slippage term; the book
  walk is the slippage.
- **Funding:**
  - The rates come from finalized `fundingHistory` records, the authoritative source, for
    each hourly settlement during the hold.
  - The cashflow is q × oraclePx × rate, with the sign set so that positive funding pays a
    short. It is labelled **estimated**, because oraclePx is observed through
    `metaAndAssetCtxs` within ±60 s of each boundary, not read from a settlement receipt.
  - A boundary with no rate or no observation inside that tolerance makes the event's funding
    `missing`. The net is then incomplete: it stays out of the decision mean and counts as
    missing in the tipping point.
- **Excursion:** MAE/MFE from 1 m `candleSnapshot` highs and lows, *descriptive price
  excursion only*. The book observations at the checkpoints are kept as well.
- **Missing and late:** every scheduled action has a 10 min deadline, including after a
  restart. Missing the deadline makes the outcome `missing`; a later recovery is stored as
  `late`, never as the scheduled outcome.
- **Ledger:** an append-only JSONL ledger with event ids, idempotent on replay. The
  resolution reports how many outcomes are missing and gives the A4 tipping point.

## Resolution (frozen in a new prereg entry before the first event)

- Prereg id: `upbit-krw-fade-forward-2026-11`, status open. This is a **new hypothesis**:
  the 24 h hold. +4 h is descriptive, even though it was Part C's registered primary, which
  came out not determinable.
- **Metric:** the announcement-level mean net return of the comparable cohort, computed from
  book fills, fees and funding.
- **Interval:** the A4 calendar-month block bootstrap, passed `level=0.95` explicitly (the
  helper defaults to 98.33%).
- **One decision**, at 40 events or on 2027-11-05, whichever comes first. The 20- and
  30-event reports are descriptive only.
  - **EDGE** when the lower bound is above 0, **NO EDGE** when the upper bound is at or
    below 0, otherwise **NOT DETERMINABLE**.
  - No interval (fewer than two months) → NOT DETERMINABLE.
- At about 1.7 events a month, expect roughly 20 to 30 events by the deadline. *Claude's
  call.*
- **What it authorizes:** EDGE authorizes only a proposal for a small live pilot under the
  graduation gates. NO EDGE closes the lane.
- **Descriptive:** +4 h marks, latency, missed and unclassified notices, MAE, and the
  non-comparable cohort.

## Runtime

- Host-side Python 3 using only the standard library, as user systemd unit
  `upbit-fade-forward` on the VPS, in the same style as `news-archive`.
- Code goes in the new directory `research/upbit_fade_forward/`, with ledger and logs under
  its `data/` (gitignored).
- Calls to the Hyperliquid info API are bounded to at most 1 per second, with backoff on 429.
  The bots share this IP, and the monitor is idle between events.
- Systemd caps: `MemoryMax=512M`, `CPUQuota=25%`, `Nice=10`. It writes only to its own
  `data/` and reads the archive read-only.
- `status` CLI: open paper positions, closed results, latency and misses.
- No Telegram in v1. *Claude's call:* results are posted on #229 at each check.

## Tests

Network-free fixtures cover:
- notice classification from real Tree titles (CARDS, and non-listing notices such as ENJ
  deposits and server maintenance);
- the eligibility rules;
- book-walk VWAP for both sides and on a thin book;
- the funding sign for a short;
- checkpoint scheduling across restarts;
- the ledger replay;
- the resolution rule.
