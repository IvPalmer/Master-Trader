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

- **Primary:** the PIT news archive (`research/news_archive/data/archive.sqlite`, read-only,
  WAL). The Tree of Alpha source relays Upbit notices. The CARDS KRW addition on 2026-11-05
  was published at 06:03:04Z and received at 06:03:43Z.
  - Poll every 15 s for new `items` from source `tree` whose `url` is an
    `upbit.com/service_center/notice` page.
  - Classify with `nes_classify.upbit_addition` and the KRW membership read from the title,
    for example `(KRW, BTC, USDT 마켓)`. Reuse that code by import; don't copy it.
- **Audit:** poll `api.upbit.com/v1/market/all` every 5 min. It answers from the VPS, while the
  announcements API returns 403. A new `KRW-*` market with no matched notice within 24 h is
  logged as a missed detection. It never triggers an entry. *Claude's call.*
- **t0** is Tree's `published_at`, and `received_at` is stored too. If Tree's time is
  missing, t0 = `received_at`.

## Eligibility at t0 (Part C rules a bot can know)

- **Excluded** when:
  - the token already trades on Upbit KRW (it is in `market/all` before t0);
  - a Binance new-listing notice for it falls within the 24 h *before* t0 (the archive's
    `binance_listing` source; A4 kept this rule);
  - the notice says trading began before the notice.
- **Required:** a Hyperliquid perp for the token in `meta` at t0 that is not delisted. Use
  the Part C name mapping (`nes_venues.hl_names`).
- **Recorded, not required:** whether a Binance market existed before t0. Part C needed one
  for its proxy, so reports show both populations.

## Paper trade

- **Notional:** 100 USDC per event. *Claude's call:* small enough to be realistic for a first
  live size, large enough to touch book depth.
- **Entry** at max(t0 + 5 min, detection time). Walk the bids of `l2Book` for 100 USDC to get
  the VWAP fill. Record mid, best bid and ask, depth used, and any delay past t0 + 5 min.
- **Checkpoints** at +30 m and +4 h: a book-walk mark only.
- **Exit** at entry + 24 h: walk the asks to buy back.
- **Fee:** 4.5 bps taker per side, the Part C value. Store the fee tier as a constant.
- **Funding:** the sum from `fundingHistory` over the hold; a short receives positive funding.
- **MAE/MFE:** from 1 m `candleSnapshot` highs and lows over the hold.
- **Failures:** a book or API failure at a scheduled time is retried for 10 min and then
  recorded as `missing`. The event is never dropped.
- **Restarts:** after a restart, overdue actions use the first successful book after the
  scheduled time, flagged `late`. State lives in an append-only JSONL ledger.

## Resolution (frozen in a new prereg entry before the first event)

- Prereg id: `upbit-krw-fade-forward-2026-11`, status open.
- Metric: the announcement-level mean net return, with book fills, fees and funding, of the
  24 h hold.
- Interval: the A4 calendar-month block bootstrap at 95%, since this is one hypothesis.
- **EDGE** when the lower bound is above 0, **NO EDGE** when the upper bound is at or below 0,
  otherwise **NOT DETERMINABLE**.
- **Checks:** at 20 events, then every 10 more; it closes at 40 events or on 2027-11-05,
  whichever comes first. Expect about 1.7 events a month, so roughly a year to 20. *Claude's
  call.*
- **What it authorizes:** EDGE at a check authorizes only a proposal for a small live pilot
  under the graduation gates; it does not authorize live trading. NO EDGE closes the lane.
- **Reporting:** the +4 h mark result, latency, missed detections and the MAE distribution
  are descriptive.

## Runtime

- Host-side Python 3 using only the standard library, as user systemd unit
  `upbit-fade-forward` on the VPS, in the same style as `news-archive`.
- Code goes in the new directory `research/upbit_fade_forward/`, with ledger and logs under
  its `data/` (gitignored).
- Calls to the Hyperliquid info API are bounded to at most 1 per second.
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
