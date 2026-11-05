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
    `binance_listing` source). A notice published *after* t0 never excludes. Only what the
    archive had received by t0 counts, revisions included; a notice or revision received
    later is recorded as descriptive (`late`) and never excludes;
  - the notice body says trading began before the notice.
- **Hyperliquid eligibility** is the Part C rule. Reuse `nes_venues.hl_facts` /
  `hl_status`: the perp is in `meta` and `fundingHistory` shows records in the 24 h
  before t0, including one in the last hour.
- **Comparable cohort** (the decision set) also requires:
  - **a Binance market before t0:** Binance 1 m klines (USDⓈ-M `fapi/v1/klines` first, else spot
    `api/v3/klines`, the Part C proxy order in `nes_venues.binance_candidates`) show trading in [t0 − 10 min, t0), counting only candles closed by t0 (open + 60 s ≤ t0).
    That is evidence from before t0, not today's `exchangeInfo`;
  - **the Binance leak test passed:** |drift| ≤ 2% between those klines' closes at
    t0 − 10 min and t0 − 2 min, the Part C rule. The same test on Hyperliquid candles is
    descriptive;
  - **a timely entry:** filled within 2 min of t0 + 5 min. Later entries, up to the 10 min
    deadline, are `delayed` and descriptive.
- **No known trading start is required.** *Claude's call (2026-11-05, implementation).*
  Part C required one, but Tree carries no Upbit notice body: the 3 Tree Upbit items in the
  VPS archive have an empty body, their raw JSON holds only the title, `en`, `kind` and
  `url`, and the VPS gets 403 from Upbit's announcements API. A deployable bot can act only
  on the title, so the forward cohort is defined by what such a bot can know. This is one
  more stated difference from Part C, beside the Tree clock, book fills and funding.
  - When a body is present, the start is read with `nes_classify.upbit_trading_start_ms`.
    A start before t0 still excludes the event (`began_before_notice`, above); a start at
    or after t0 gives `start_unknown = false`. With no body, or no start in it, the event
    stays comparable with `start_unknown = true`.
  - A later observation of the same notice (a duplicate Tree item or a revision) that states
    a start never creates a second event; it is a versioned evidence record. Received before
    the entry decision, it counts: a start before t0 excludes the event
    (`began_before_notice`) and stops the entry, and one at or after t0 sets
    `start_unknown = false`. The latest binding observation by receipt time sets the start,
    not the processing order. Received after the entry decision, it is descriptive only.
  - *Descriptive only:* `krw_market_first_seen_ms`, the time of the first `market/all`
    snapshot after t0 that lists `KRW-<TOKEN>`. It never selects events.
  - `status` and every resolution report show the `start_unknown` and
    `krw_market_first_seen` counts. The decision metric is over the whole comparable
    cohort; the subset with `start_unknown = false` is reported as descriptive only.
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
  excursion only*. It is `ok` only when every minute of the hold has a candle; otherwise it
  is retried, then stored as `partial` with candle counts and labelled partial extrema. The book observations at the checkpoints are kept as well.
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

## Addendum: live pilot (#252)

Added 2026-11-05. The sections above are unchanged and still describe the paper monitor,
which keeps running unchanged as the preregistered shadow measurement.

**Why.** At about 1.7 events a month the paper decision needs about a year. On 2026-11-05
the operator chose not to wait: "if our backtests support it lets put it live with a bit of
money". The authority is that decision and the Part C proxy result. No forward outcome
exists yet, and the graduation gates are not met and not claimed. Recorded as an amendment
of `upbit-krw-fade-forward-2026-11` and as the new prereg `upbit-krw-fade-live-pilot-2026-11`.

**Shape.** Two parts, copying the Killers pattern (a pass-through Freqtrade bot driven by
`/forceenter`):

- **Bot** `ft-upbit-fade-hl` (`UpbitFadeLiveV1`, `127.0.0.1:8105`): Hyperliquid perps,
  futures, isolated, leverage 1, `can_short`, stake 50 USDC, `max_open_trades` 2. It has no
  signals of its own. The 24 h exit is `minimal_roi {"0": 100, "1440": -1}`, evaluated by
  Freqtrade on every loop (no `custom_exit`, which the fleet showed is dead without exit
  signals). The emergency stop is -0.60, above the worst Part C adverse move (+48.7%), so
  it does not change the tested rule. The stop sits on the exchange when live and is off in
  dry-run, set by the compose entrypoint from the dry-run flag. `HL_UPBIT_GATEWAY_CLIENT`
  picks its `hl-gateway` client. In dry-run it is the deployed gateway's `short` client
  (background reads, exchange actions refused; a dry-run Freqtrade sends none), so the
  dry-run deploy does not touch the gateway. Live it is `upbit`, which may submit exchange
  actions, and the entrypoint refuses live on any other client. Its keys come only from
  Dokploy env vars; the repo holds none.
  It starts in dry-run (`HYPERLIQUID_UPBIT_FADE_DRY_RUN` defaults to `true`), and the
  entrypoint refuses to start live without both the wallet address and the key.
- **Trigger** `research/upbit_fade_live/live_trigger.py` (user unit
  `upbit-fade-live-trigger`): stdlib, host-side. It tails the paper ledger read-only and,
  for each paper entry of an event that `uff_report.classify` puts in the comparable cohort
  with every requirement established, sends one `POST /api/v1/forceenter` (short, stake 50,
  leverage 1, market, entry tag `upbit-fade:<event id>`) to the local bot with HTTP Basic
  auth. It talks only to a loopback URL; it never signs an order or calls Hyperliquid.

**Selection.** Exactly the paper monitor's own: eligibility at t0 is unchanged and the paper
entry (t0 + 5 min) is the trigger. An event whose requirements are not yet established
waits, and is skipped if they are not established by t0 + 7 min. *Claude's call:* the paper
keeps such an event comparable with a missing outcome, but the pilot does not trade
something the paper could not judge.

**Guards** (each decision is one record in the trigger's append-only, fsynced
`data/decisions.jsonl`):

- one decision per event id; the intent is written before the request, and the request is
  sent once and never retried;
- no entry after t0 + 7 min (`stale`);
- the bot must answer for strategy `UpbitFadeLiveV1` and be running, with fewer than 2
  open trades;
- the pair must be an active perp in the bot's markets, else `unavailable_pair` (Freqtrade's
  own "Symbol does not exist" rejection maps to the same status). `kPEPE` maps to
  `KPEPE/USDC:USDC`, as ccxt names it;
- kill-switch file `data/KILL`: while it exists, no entry is sent. *Claude's call:* the
  trigger engages it itself when the cumulative realized P&L of the bot's database is
  -75 USDC or worse (read on every loop, not only when a paper event arrives), when a
  `/forceenter` outcome could not be observed (timeout, or an unexpected status), and when
  the URL answers for another strategy. An intent without a result after a crash is
  recorded `unknown` and engages it too;
- an unknown outcome writes the pause file **before** the outcome record. While any
  unknown outcome has no reconciliation record, the trigger stays paused and puts the file
  back on every loop and at every start, so deleting it does not resume. The operator
  checks the bot and Hyperliquid, then records the outcome with
  `live_trigger.py reconcile <event id> --outcome entered|not_entered`, and only then
  removes the file;
- a failure to persist any record or the pause file stops every further entry from that
  process (and writes the pause file if it can).

**Bot-side guard** (`UpbitFadeLiveV1.confirm_trade_entry`, #252 review). Freqtrade 2026.7
runs the `/forceenter` max-open and same-pair checks before it takes its entry lock, so two
concurrent calls (the trigger and a manual call) could both pass them. `execute_entry` calls
`confirm_trade_entry` under that lock, just before the order. The trigger's entry tag is
`upbit-fade:<event id>@<t0 + 7 min in ms>`, and the strategy refuses unless the tag parses,
the side is short, the time is not past the deadline (which may be at most 7 min ahead),
fewer than 2 trades are open, the pair has no open trade, no trade (open or closed)
carries the event id, and the realized P&L of the closed trades in the bot's database is
above -75 USDC. Any error refuses: Freqtrade's wrapper treats an exception as "confirmed".

**Timing rule** (amended; approved by the operator in chat, 2026-11-05 ('Approve it')).
Admission is by t0 + 7 min, checked by the trigger and again by the bot under its entry
lock. Submission is not bounded: after `confirm_trade_entry` Freqtrade prepares margin mode
and leverage, with retries, before it submits, and ccxt 4.5.68 does not sign Hyperliquid's
`expiresAfter` on ordinary orders (`create_orders_request` signs the action without it).
So the delay is measured instead: for every entry the trigger reads the entry order back
from the bot and records its submission (`order_timestamp`) and fill
(`order_filled_timestamp`) times against t0 and the paper entry (`timing:` records). A fill
after t0 + 10 min, or no timely fill confirmed by then (the trade unreadable, no entry
order on it, or not filled), is an execution defect and writes the durable pause.
Freqtrade takes those times from Hyperliquid's order data when ccxt provides them, else
from its own clock when it saw the order.

**Gateway allocation.** The `upbit` client's reads are background (tier 2) and share the
600-unit background allowance. Only its exchange actions and `orderStatus` reads are
priority, and those draw on its own slice of 40 weight per rolling minute, which is never
counted against the fleet's priority capacity; a slice waiter never blocks a fleet waiter.
Killers keeps its 250 + 50 units whatever the pilot does, and nothing changes for Killers
while the pilot is idle. Worst case through the gateway is 940 per minute (HL allows 1200
per IP). The paper monitor calls Hyperliquid directly from the same IP, at most one request
a second and only around events.

**Gateway restarts.** The gateway keeps no budget state: a recreated gateway starts with
an empty rolling minute while Hyperliquid keeps counting the last one. The `upbit` client
is added by one recreate at go-live, done only when Killers is flat (no open positions and
no open orders on Hyperliquid, the same rule as the #188 flat restart) and the
trailing-minute usage on `/healthz`, read just before, is under 300; Killers `/status` and
the gateway logs are checked after, and the previous image is kept for rollback
(GO-LIVE.md).

**Epochs.** Dry-run trades are plumbing checks, not results. The live epoch starts at the
first start with the dry-run flag false and is recorded in a prereg amendment. The live
database is a separate file, so the realized P&L for the kill rule starts at zero then.
Live results are reported per trade against the paper entry and exit of the same event and
are never pooled with paper results or used in the paper decision.

**Account.** *Claude's call:* a dedicated Hyperliquid master account with its own API
(agent) wallet, funded with about 150 USDC, as Killers runs. Not a subaccount: ccxt 4.5.68
sends orders with `vaultAddress` but reads balances and positions with
`subAccountAddress`, and the Freqtrade subaccount setup is unverified here. An API wallet
cannot withdraw.

**Runbook:** `research/upbit_fade_live/GO-LIVE.md`.

**Follow-ups, not in this change:** a valuation adapter for the `hyperliquid-upbit-fade`
capital account in the metrics exporter (until then a live bot pages as outside the
circuit breaker); listing the bot in the dashboard UI; per-trade live-versus-paper
reporting.

**Tests:** `tests/test_upbit_fade_live_trigger.py` and `tests/test_upbit_fade_live_bot.py`
cover idempotency, crash and restart, max open, the kill switch and the P&L kill, stale
records, unavailable pairs, auth headers and the loopback rule, the strategy and config
settings, the compose entrypoint in both modes, `--no-deps` safety, unique ports and
database and log files, and a pin of the code's constants to the prereg. Since the #252
review they also cover the durable pause and `reconcile`, the halt on a failed write, the
loss latch, the bot-side guard against Freqtrade's force-entry order (concurrent calls,
same pair, same event, deadline, loss limit, fail closed), and in
`services/hl-gateway/tests/` the pilot's contention with Killers, a gateway that keeps no
budget state and the deployed `short` client serving the dry-run bot, plus the entry
timing measurement and the pause when no timely fill can be confirmed. The
ROI test reproduces Freqtrade's `min_roi_reached`; the real code is checked in dry-run on
the VPS (GO-LIVE.md, Part 1).
