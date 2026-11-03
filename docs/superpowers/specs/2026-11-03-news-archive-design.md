# News/Sentiment Layer, Steps 0–1 — Design Spec

**Date:** 2026-11-03
**Status:** Draft for operator review. Adversarial review by GPT-6 Astra (high): 6 rounds, 28 findings handled, 26 accepted and 2 partly rejected (§11). VERDICT: APPROVED on 2026-11-03.
**Author:** Claude (with Palmer)
**Issue:** [#229](https://github.com/IvPalmer/Master-Trader/issues/229)
**Research:** [report](../../research/2026-11-03-news-sentiment/report.md) and [notes](../../research/2026-11-03-news-sentiment/notes/)

---

## 1. Intent

The operator wants a consolidated market-sentiment layer, built from X/Twitter and market news, that will eventually:

- (a) drive a standalone news/event bot;
- (b) veto or shrink entries of the existing bots, for example "don't take this long, crash news is spiking" or "this coin is being trashed".

The 2026-11-03 research changes the order of work:

- **No honest history is for sale at our scale.** Santiment documents that it revises its history, and no other vendor states a revision policy at all. Our own point-in-time (PIT) record is the only out-of-sample dataset we will be able to trust. It only starts the day we start recording, so recording comes first.
- **The evidence supports sentiment as a risk input, not as directional alpha.** A standalone bot is justified only by a measured event effect that survives costs. Measuring that effect is cheap, because exchange announcement archives are public.
- **Nothing live uses sentiment today.** The live bots do not import `market_intelligence.py`, so its Fear & Greed gate is not in effect.

This spec covers only the first two build steps:

1. Start an honest data clock: the PIT news archive (Part A), visible in the nightly report (Part B).
2. Run the cheapest decisive test of the standalone-bot idea: preregistered event studies (Part C).

Neither step changes what any bot does.

## 2. Goals, non-goals, anti-goals

**Goals**

1. Every item from the v1 sources is stored with our own receive time, the source's claimed publish time, and the raw payload, without duplicates. Later edits are kept as revisions.
2. A stale or broken source is visible within a day without anyone reading logs.
3. Two preregistered retrospective event studies produce a mechanical pass/fail. They cover news categories the closed listing study did not.

**Non-goals (later issues)**

- Any veto, gate, sizing or trading effect on any bot.
- LLM or model classification, entity linking beyond what a source already provides, sentiment scores.
- Paid feeds (X API or third-party X APIs, CryptoPanic, LunarCrush, Santiment, Grok).
- Telegram news channels.
- A standalone trading bot of any kind. A passing study authorizes only a paper forward monitor.
- Changes to `market_intelligence.py`. Its Fear & Greed hardening is "step 0" of the plan and moves to the gate work (§7).

**Anti-goals (failure even if it technically works)**

- The archive influences trading in any way, or a crash of it can affect a bot or the Killers pipeline.
- Raw archive data, account identifiers or credentials end up in this public repository.
- An event study gets tuned after its numbers are seen: criteria, horizons and filters change post hoc.
- Re-running the closed listing long-reaction lane under a new name.
- Hammering an undocumented endpoint until we are blocked.

## 3. Constraints

- **Runtime is VPS-only.** No local Docker or app servers in the Mac checkout (`RUNTIME.md`).
- **Follow the host-side research-monitor pattern** of `listing-monitor` and `hl-shadow`:
  - stdlib-only Python 3.12, run as a systemd **user** unit;
  - installed under `/home/ubuntu/master-trader/research/<name>/`;
  - no fleet containers, no `/etc/dokploy` changes.
- **The repo is public.** Fixtures must be small, sanitized samples of each payload's shape. The `data/` directory is gitignored.
- **Disk:** the VPS is at 82% (37 GB free). The expected archive size is under 1 GB per year (~1–3k items/day).
- **Clock:** the VPS clock is NTP-synchronized (checked 2026-11-03). `received_at` relies on it.
- **Workflow:** issue-linked branch → PR → review → merge. Merging does not authorize installing on the VPS; installation follows §8 after the operator's go-ahead.
- **Preregistrations are append-only research records.** `listing-reaction-study-2026-07` (closed) and `listing-short-forward-2026-07` (open, blinded) must not be touched.

## 4. Part A — PIT news archive

### 4.1 Shape

- **Repo location:** `research/news_archive/`, containing:
  - `news_archive.py` — the service and CLI;
  - `sources.py` — the per-source adapters;
  - `README.md` — ops, mirroring `research/listing_short_forward/README.md`;
  - `news-archive.service` — the unit template;
  - `.gitignore` — ignores `data/`.
- **Process:** one long-running process with a single scheduler loop. Each source has an interval and a next-due time; polls run sequentially, with a 10 s HTTP timeout. No threads.
- **Adapters:** each adapter is a pure parse function `parse(payload, received_at) -> list[Item]` plus a small fetch spec (URL, method, headers). Keeping parsing pure makes it testable without network access.

### 4.2 v1 sources

All sources were probed and answered without a key on 2026-11-03 (see the research notes, raw-feeds section).

| key | endpoint | interval | item id | publish time |
|---|---|---|---|---|
| `tree` | `GET https://news.treeofalpha.com/api/news?limit=200` | 60 s | `_id` | `time` (ms) |
| `binance_listing` | Binance CMS `article/list/query?type=1&pageNo=1&pageSize=20&catalogId=48` (browser UA, as in `listing_short_forward/monitor.py`) | rotating, see budget | `id` | `releaseDate` (ms) |
| `binance_delisting` | same endpoint, `catalogId=161` | rotating, see budget | `id` | `releaseDate` |
| `upbit` | `GET https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=20&category=trade` | 120 s | `id` | `listed_at` (KST → UTC) |
| `okx_listings` / `okx_delistings` | `GET https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings` / `…-delistings` | 300 s | `url` | `pTime` (ms) |
| `hyperliquid_universe` | `POST https://api.hyperliquid.xyz/info {"type":"meta"}` | 300 s | each time the universe differs from the latest stored snapshot, it is stored as a new occurrence `universe:<seq>`, where `seq` increases monotonically and the content hash is kept only for comparison. Transitions are synthetic items `add:<NAME>:<seq>` / `remove:<NAME>:<seq>` (or `delisted:…` if `meta` flags it). So A→B→A→B yields three distinct occurrences and every transition | none; `received_at` is the event time |
| `rss_coindesk`, `rss_theblock`, `rss_decrypt`, `rss_blockworks`, `rss_cointelegraph`, `rss_fed` | the six feed URLs in the research notes | 300 s | `guid`, else `link` | `pubDate` |
| `ff_calendar` | `GET https://nfs.faireconomy.media/ff_calendar_thisweek.json` | 6 h | `sha1(title|country|date)` | `date` (event time) |
| `fear_greed` | `GET https://api.alternative.me/fng/?limit=1` | 1 h | `timestamp` | `timestamp` |

**Binance monitoring tag.** Binance also publishes "monitoring tag" announcements. The builder confirms which CMS catalog carries them. If it is not 48 or 161, that catalog is added as `binance_monitoring` with the same adapter, in the same rotation.

**Binance request budget (Claude's call, tightened after review).** `listing-monitor` already polls catalog 48 every 60 s for the open, blinded `listing-short-forward-2026-07` preregistration. Its `_http` retries up to 4 times. That endpoint is not a documented public API, and a block on the VPS IP would cost that study events it sees about once every 81 days.

The archive adds as little as possible:

- **Rotation:** at most **one Binance CMS request every 3 minutes in total**, rotating through its catalogs, so each catalog is polled every 6–9 minutes. Each request is a single attempt with no retry inside the poll. This adds at most about 33% to today's Binance CMS traffic from the VPS. `listing-monitor` is untouched.
- **Block suspension:** HTTP 403/418/429, or a non-JSON or HTML body, suspends **all** Binance adapters for 6 h. The suspension writes a `gaps` row (reason `suspended`) and shows in `status` and in the nightly report.
- **One shared limiter for every new CMS caller (changed after round 2).**
  - The service, the `once` command and the Part C harvester take the same file-locked limiter in `data/binance_cms_state.json`: at most one request every 3 minutes across all of them.
  - The same file holds the persistent 6 h suspension, so a block seen by any caller stops all of them, across restarts.
  - The harvest therefore runs slowly. About 60 pages of catalogs 48 and 161 take roughly 3 hours, which is fine for a one-time job.
  - The harvester may first reuse the catalog-48 pages already cached on the VPS by the 2026-07 listing study, saving requests.
  - `data.binance.vision` kline downloads are a different host and are not counted against this budget.
- **Latency:** minutes of delay are irrelevant for an archive. The later hard-event veto only has to beat the bots' 5m–1h candles, and Tree also relays Binance notices.
- **Not done:** we do not isolate the archive on a separate egress IP. That is disproportionate at this volume, and the rotation plus suspension bound the risk.

### 4.3 Storage

The database is SQLite in WAL mode at `data/archive.sqlite`. All timestamps are ISO-8601 UTC with microseconds.

```sql
CREATE TABLE sources (source TEXT PRIMARY KEY, interval_s INTEGER NOT NULL,
                      enabled INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE items (
  item_pk        INTEGER PRIMARY KEY AUTOINCREMENT,
  source         TEXT NOT NULL,
  source_item_id TEXT NOT NULL,
  received_at    TEXT NOT NULL,   -- our clock, when the HTTP response arrived
  published_at   TEXT,            -- source-claimed, normalized to UTC; NULL if absent
  title          TEXT,
  body           TEXT,
  url            TEXT,
  symbols        TEXT,            -- JSON, only what the source itself provides (e.g. Tree `suggestions`)
  after_gap      INTEGER NOT NULL DEFAULT 0, -- 1 = inserted by a poll that followed a coverage gap (see rules)
  content_hash   TEXT NOT NULL,   -- sha256 of the canonicalized raw item
  raw_json       TEXT NOT NULL,
  UNIQUE(source, source_item_id)
);
CREATE TABLE item_revisions (
  rev_pk INTEGER PRIMARY KEY AUTOINCREMENT, item_pk INTEGER NOT NULL REFERENCES items(item_pk),
  received_at TEXT NOT NULL, prev_hash TEXT NOT NULL, content_hash TEXT NOT NULL,
  after_gap INTEGER NOT NULL DEFAULT 0, raw_json TEXT NOT NULL
);
CREATE TABLE gaps (            -- durable coverage holes; never pruned
  gap_pk INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
  gap_start TEXT NOT NULL, gap_end TEXT,   -- gap_end NULL while open
  reason TEXT NOT NULL,                    -- restart | outage | overflow | suspended | disk | clock
  detail TEXT
);
CREATE TABLE clock_checks (    -- hourly; never pruned
  checked_at TEXT NOT NULL, ntp_synchronized INTEGER, wall_minus_mono_s REAL, detail TEXT
);
CREATE TABLE polls (
  poll_pk INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, ok INTEGER NOT NULL,
  http_status INTEGER, n_items INTEGER, n_new INTEGER, n_revised INTEGER, error TEXT
);
```

Storage rules:

- **Versions are compared against the latest observed version,** not the first. Seeing the latest version again does nothing. Seeing a different one writes an `item_revisions` row with `prev_hash` → `content_hash`, in the same transaction as the poll's other writes. So A→B→B→A stores exactly two transitions, B and then A.
- The `items` row keeps its first version. This covers edited announcements and calendar actuals being filled in.
- **Revision coverage is bounded:** only items still on a source's first page can be seen to change. This is a documented limitation, not a gap.
- Items are never deleted. Rows in `polls` older than 180 days are pruned once a day.
- The service writes `sources` at startup, so readers know each source's interval.
- `after_gap` marks items whose `received_at` only means "when we got back", not "when it was new". PIT analyses exclude them by default. A poll counts as following a gap when it is the source's first successful poll since process start, or when that source's previous successful poll is older than `2 × interval_s`. This covers outages and backoff, not just restarts. The flag sits on the item itself, and every such interval also gets a `gaps` row, so PIT validity does not depend on `polls` history surviving the 180-day prune (Claude's call).
- **Overflow (list feeds only):** a successful poll can still lose coverage if more items arrived than one page holds.
  - **Which feeds:** detection applies only to list feeds with stable ids: `tree`, the Binance catalogs, `upbit`, OKX and RSS. It never applies to single-value or replace-style feeds (`fear_greed`, `ff_calendar`, `hyperliquid_universe`).
  - **Detection:** a list-feed page contains no previously seen id, and the source already has items.
  - **Response:** the poll does **one** bounded backfill: Tree with `limit=2000`, other list feeds up to 3 extra pages, Binance excepted. Items from the backfill are `after_gap = 1`.
  - **Closed, not open:** the overflow gap is written as a **closed** interval, from the previous successful poll to this one, with `detail` set to `recovered` or `unrecovered`. It never stays open; normal collection resumes from this poll.
- **Clock:** every hour the service runs `timedatectl show -p NTPSynchronized --value` and stores the result, plus wall-minus-monotonic drift, in `clock_checks`. If wall time jumps by more than 2 s against the monotonic clock between polls, or NTP reports unsynchronized, the service records a `gaps` row (reason `clock`) for all sources until the clock is healthy again.
- **Open gaps taint writes (changed after round 2).** Only ongoing conditions open a gap: `clock`, `disk`, `suspended` and `outage`. Each closes as soon as the condition clears. While such a gap is open, every item **and** revision written for that source gets `after_gap = 1`, even when its poll succeeded.
- **The PIT rule for readers:** a record is PIT-valid only if `after_gap = 0` **and** its `received_at` falls outside every `gaps` interval for its source. Part C forward analyses and any later gate must apply this rule. A helper `pit_valid(conn, source, received_at)` ships with the archive and is unit-tested.

### 4.4 Robustness

- No failure can kill the loop. Every exception is caught per poll, logged as one `[news-archive]` line, and recorded in `polls`.
- **Backoff:** after consecutive failures a source backs off exponentially from its base interval, capped at 30 min. On HTTP 429 the service honours `Retry-After` if present and backs off otherwise.
- **Identification:** a fixed, honest User-Agent, except for Binance, which needs the browser UA already proven in `listing_short_forward`.
- **Politeness on undocumented endpoints:** the poll intervals in §4.2 are the floor, not targets.
- **Resource ceilings,** because the archive shares a host and a disk with the live bots:
  - the systemd unit sets `MemoryMax=256M`, `CPUQuota=25%`, `Nice=10`, `IOSchedulingClass=idle`, and `Restart=always` with `RestartSec=30`;
  - after 5 failed starts within 10 minutes the unit stays down, and the nightly report shows it as stale;
  - each response read is capped at 5 MB, and each poll has a 20 s total deadline.
- **Disk guard:** before each write batch the service checks free space on the database's filesystem. Below 15 GB it stops writing, opens a `gaps` row (reason `disk`) and keeps polling only to show the condition. The bots and Docker volumes share that disk, at 82% used on 2026-11-03.
- **Bounded logs:** `[news-archive]` lines go to the journal, plus a `monitor.log` that rotates daily, keeping 14 files, gzipped.

### 4.5 CLI

| command | what it does |
|---|---|
| `python3 news_archive.py run` | the service, used by the systemd unit |
| `python3 news_archive.py once [--source KEY]` | one poll per source, then exit; for install checks |
| `python3 news_archive.py status` | per source: last OK poll, consecutive failures, OK ratio over 24 h, items over 24 h / 7 d / total, newest `published_at` |

## 5. Part B — visibility and off-server backup

### 5.1 Stale sources in the nightly report

`ft_userdata/strategy_health_report.py` gets one read-only section.

- **Opening the database:** it opens the archive with `sqlite3.connect("file:<path>?mode=ro", uri=True)`.
  - The path comes from env `NEWS_ARCHIVE_DB`, defaulting to `/home/ubuntu/master-trader/research/news_archive/data/archive.sqlite`.
  - A missing file prints `news-archive: not installed` and is not an error.
- **Staleness:** an enabled source is stale when its last OK poll is older than `3 × interval_s + 10 min`.
- **Output:**
  - With no stale sources, one summary line: sources OK out of total, plus items in the last 24 h.
  - Otherwise, one line per stale source with its age and last error.
  - **Open gaps:** always shown, independent of freshness, with the count of open `gaps` rows by reason and the oldest open gap's age. A source can be fresh and still have an integrity hole.
  - **Recent and lost coverage (changed after round 4):** also always shown:
    - gaps closed in the last 24 h, by source and reason, marked recovered or unrecovered;
    - a 7-day count of unrecovered gaps per source.
    A source that is fresh again but permanently lost events is therefore never reported as plain OK.
  - **Backup state:** the latest local snapshot's age, plus `local only` until the off-host leg passes its gate (§5.2).
- **Isolation:** the section never changes the report's exit status, and no exception from it can break the report.
- **Tests:** network-free, against a temporary SQLite database built with the §4.3 schema.
- **Release:** the report wrapper is symlinked into the Dokploy checkout, so this ships through a `vps-deploy` release PR. No container is recreated. `main` currently holds an undeployed Killers strategy change (#181/#183, on hold per #188), so the release branch cherry-picks only this work onto `vps-deploy`, as the #228 release did. It must never be a full `main` merge.

### 5.2 Off-server backup (Claude's call: in scope)

The archive is irreplaceable by design: no vendor sells the same PIT history. A disk loss would reset the data clock to zero.

- **Independent of the live-DB backup (changed after review).** `run_backup` in `deploy/vps/backup_live_dbs.py` is all-or-nothing: any failing item aborts the whole run (L134–160), and retention prunes whole run directories. Adding the archive to it would let an archive failure break the live trade-DB backup. So the archive gets its **own job**:
  - its own cron entry (daily, offset from the 03:15 UTC live-DB run);
  - its own destination namespace;
  - its own retention of 7 daily plus 8 weekly copies.
  It may import `backup_sqlite`, the consistent snapshot plus integrity check, and the prune helpers from that module, but it never shares a run with the live DBs.
- **The backup cannot fill the bots' disk (changed after round 2).**
  - Before snapshotting, the job requires free space of at least 15 GB plus twice the database size. Otherwise it skips the run and logs that.
  - It holds a singleton `flock`, so runs never overlap, and runs under `nice`/`ionice -c3`.
  - A failed run deletes its staging directory, as `run_backup` already does.
  - The retention tier above bounds the total number of snapshots.
- **Off-host is a gate, not an assumption.** `deploy/vps/README.md` states that only the local schedule was verified (2026-10-13), not the rclone off-host upload.
  - The archive's local snapshots start with the service. They protect against corruption and accidental deletion, not against disk loss.
  - The off-host leg counts as done only after three things: the operator configures and verifies the remote, a failed upload shows in the nightly report, and a restore drill passes. The drill restores the latest snapshot to a temporary path, then runs `PRAGMA integrity_check` and compares row counts.
  - Until then the report says `news-archive backup: local only`.
- **Release:** the same release as §5.1.

## 6. Part C — preregistered event studies

### 6.1 Why these two

The closed `listing-reaction-study-2026-07` measured Binance listing announcements for tokens already on spot, going long. It failed all three criteria, and its long lane is closed. Its short inverse is being validated forward and stays untouched.

The two categories here are different events with their own direction:

| id | event | direction | why it is a distinct hypothesis |
|---|---|---|---|
| `binance-delisting-reaction-2026-11` | Binance delisting and monitoring-tag announcements | short | Negative, forced-selling event. The research's per-coin "hard event" class. |
| `upbit-krw-listing-reaction-2026-11` | Upbit "KRW market addition" notices for tokens already trading on Binance | long | The Korean demand shock, an event source separate from Binance's own announcements. |

### 6.2 Protocol (frozen in each preregistration entry before any computation)

Each study runs in two phases. Phase 1 builds an **outcome-blind event manifest**. Phase 2 computes returns, and only from the frozen manifest.

**Phase 1 — manifest (no returns loaded)**

- **Window:** announcements dated 2023-01-01 00:00 UTC to 2026-10-31 23:59 UTC. The start is roughly when Hyperliquid perps begin to exist. Nothing after the window enters this study.
- **Events, delisting study (Claude's call):**
  - **Counted:** one event per (announcement, token) for two kinds of notice:
    - a full Binance spot delisting, where the token loses every spot pair;
    - a new monitoring-tag assignment.
  - **Excluded:**
    - removal of individual trading pairs where the token keeps at least one spot pair;
    - margin-only and futures-only delistings;
    - vote-to-delist and similar polls;
    - removals of a tag.
  - **Retractions and corrections stay in.** They are unknowable at entry time.
  - **Classification:** from the notice text as harvested. The CMS returns current versions, so later edits cannot be ruled out; this is recorded as a limitation.
  - **Overlap:** if the same token has a second qualifying notice within 24 h of the first, only the first counts. Notices more than 24 h apart are separate events.
  - **One test:** both kinds share one pass/fail. Per-kind results are reported as descriptive only.
- **Events, Upbit study:** one event per (notice, token) for Upbit `category=trade` notices whose title matches the KRW-market-addition pattern.
  - Tokens already on Upbit KRW are excluded.
  - So are tokens with a Binance catalog-48 listing announcement within ±24 h. That keeps the closed listing lane out of this sample.
  - Events whose Upbit KRW trading began before the notice are excluded too.
- **Timestamps:**
  - Binance: `releaseDate`.
  - Upbit: the builder documents whether `listed_at` or `first_listed_at` is the publish time. The prereg names the field before Phase 1 runs.
- **Execution venues (Claude's call):** Binance futures is CVM-blocked for the operator (see the `listing-reaction-study-2026-07` notes), so only these count:
  - **Delisting study (short):** Hyperliquid perp only. Binance spot cannot short.
  - **Upbit study (long):** a Hyperliquid perp, else Binance spot. Tokens that trade only on Binance futures are excluded.
- **Hyperliquid eligibility needs positive pre-entry evidence (changed after both rounds).** A token qualifies only if Hyperliquid candles exist for it in the 24 h before t0, including at least one in the last hour before t0. Nothing after t0 is used for eligibility; using it would exclude exactly the tokens that become untradeable right after the event. Tokens no longer in today's `meta` are looked up by name through `candleSnapshot`. The builder confirms in Phase 1 that this works for delisted coins and documents it.
  - Eligibility that cannot be verified is `unknown`. Unknown events are excluded and counted. An earliest daily candle alone is not enough.
- **Completeness evidence (changed after round 2).**
  - **Pagination (changed after round 3):** each Binance catalog (48 and 161, plus monitoring if separate) and the Upbit list are harvested **in full**, every page. The harvested count must equal the API's reported `total`.
    - Any shortfall is added to the `missing` count, conservatively assumed to fall inside the window.
    - If no total is reported, the study is **INCONCLUSIVE-by-data**.
    - This also covers the catalog-48 overlap exclusion.
  - **Candles (changed after round 3):** the exact 1m candles each calculation uses must exist. These are t0−10 min and t0−2 min for the leak test, the entry candle, and each horizon's exit candle. No interpolation and no forward-fill. If any is missing, and the halt rule does not resolve it, the event is `missing`.
  - **Halts after entry (changed after rounds 3–4):** if an exit candle is missing because trading halted, the exit is the first candle after trading resumes, within 72 h **of that scheduled exit time**.
    - Costs are always subtracted from the net return, whatever the side, never applied to a price.
    - If trading does not resume within that window, the event is `unresolved`.
    - `halted` events stay in every criterion.
  - **Any unresolved event makes the study INCONCLUSIVE (changed after rounds 4–5).** Their outcomes are outcome-dependent: terminal delistings would vanish. So with one or more `unresolved` events the result is **INCONCLUSIVE**. There is no imputation shortcut: imputed values can move the median and concentration criteria in either direction.
  - **Coverage gate:** `unknown`, `missing` and `unresolved` together above 20% of candidate events make the study **INCONCLUSIVE-by-data**. So does harvesting that cannot complete within the shared limiter.
- **Resource budget for Part C (changed after round 3):**
  - Harvesting, downloading, decompressing and analysis run under `systemd-run --user --scope -p MemoryMax=1G -p CPUQuota=50%` with `nice` and `ionice -c3`.
  - Before each download batch, the 15 GB free-disk guard from §4.4 applies.
  - Only the daily kline files covering each event's [t0−1 d, t0+5 d] window are downloaded. That covers entry+24 h plus the 72 h resumption window. Each zip is deleted after the needed rows are extracted.
  - The expected footprint is under 1 GB.
- **Symbols and price series:** the manifest freezes the token → Binance-symbol mapping, including 1000-prefixed contracts and renames, and which proxy series each event will use. Proxy series are Binance 1m klines from `data.binance.vision`, USDⓈ-M futures preferred, spot otherwise. Phase 1 checks only that the series exists; it computes no returns.
  - Events with missing proxy data are excluded and counted toward the coverage gate above.
- **Freeze:** the manifest file's SHA-256 is recorded in a preregistration amendment, merged before Phase 2 starts.

**Phase 2 — returns (frozen rules)**

- **Entry latency (changed after review):** taker entry at the close of the 1m candle containing **t+5 min**. Five minutes covers detection by a 60 s poller on Tree plus processing. A t+60 s entry is reported as descriptive only, because the archive's own Binance rotation could not detect that fast.
- **Exits:** the fixed horizons entry+30 min, entry+4 h and entry+24 h.
- **Costs:** taker fees of 4.5 bps per side on Hyperliquid or 7.5 bps on Binance spot, **plus 10 bps per side of slippage**. A stress case at 25 bps per side is reported. Hyperliquid funding is not modelled; at the +4 h primary horizon it is about four hourly payments. This is listed as a limitation.
- **Proxy status:** the returns come from Binance prices, not Hyperliquid fills. Basis and impact are not measured, so any result is labelled a **proxy result**. That is acceptable only because a pass authorizes nothing beyond a paper forward monitor, and that monitor measures executable prices.
  - **The forward monitor keeps each event's venue assignment (changed after round 2).** It uses Hyperliquid best bid/offer (BBO) for Hyperliquid-assigned events and Binance spot `bookTicker` for spot-assigned Upbit events. So a pass driven by spot events is validated on spot, not on a different subset.
- **Leak flag:** reuse the listing study's rule: more than 2% absolute drift over [t0−10 min, t0−2 min]. The primary set excludes leaked events; a sensitivity run includes them.
- **Unit of analysis (changed after review):** the **announcement**, not the token. One Binance notice often names several tokens.
  - Each announcement's return is the mean net return of its eligible tokens.
  - The chronological halves split announcements by date.
- **Primary horizon:** +4 h, declared now.
- **Pass (all required, evaluated at +4 h after fees and 10 bps slippage):**
  - at least **20 distinct announcements** in the primary set;
  - announcement-level median net return > 0;
  - a positive median in both chronological halves;
  - the top decile of announcements contributes less than 60% of the sum of announcement returns. This criterion **fails** whenever that sum is ≤ 0.
- **Also reported, not criteria:**
  - a bootstrap 95% CI of the announcement-level median (10,000 resamples);
  - BTC-adjusted returns;
  - all three horizons, both halves, per venue and per notice kind;
  - leak and slippage sensitivities;
  - excluded, unknown and missing counts.
- **Two separate hypotheses.** The two studies are never pooled, and a pass in one is not evidence for the other.
- **Kill:** with at least 20 announcements, any failed criterion closes that lane for this config. A pass authorizes only a paper forward monitor, preregistered separately, in the `listing-short-forward` style.
- **Too few announcements (Claude's call):** fewer than 20 is **INCONCLUSIVE-by-data**, the precedent from the listing study's Hyperliquid venue. The lane stays open, but nothing is authorized: no monitor and no bot. The archive keeps recording these events. Any re-test is a new, forward-only preregistration; retrospective and forward events are never mixed.
- **Code and data:**
  - Code lives in the repo under `research/news_event_studies/`.
  - Downloaded klines and results stay on the VPS under `research/news_event_studies/data/`, gitignored.
  - The resolution is written into the prereg entry mechanically, from the frozen criteria only.

## 7. Step 0 — deferred, on purpose

The research's step 0 was hardening `FearGreedIndex`: no blocking 10 s fetch on every call while the source is down, plus a maximum age. None of the live strategies imports it today. Its only consumers are retired or dry strategies and `engine/calibration.py`, so fixing it now changes nothing in production.

The gate work (step 2) will replace the in-strategy HTTP fetch with a local snapshot file. That fix lands there, with tests. Meanwhile Part A records Fear & Greed as PIT data. This is recorded as a checklist item on the step-2 issue.

## 8. Install and rollback (after operator go-ahead)

**Install**

1. Copy `research/news_archive/` from the merged `main` commit to `/home/ubuntu/master-trader/research/news_archive/` on the VPS. Never copy into `/etc/dokploy`.
2. Run `python3 news_archive.py once`. Every source must report OK, or the failing ones are disabled and noted.
3. Install `~/.config/systemd/user/news-archive.service` (`Restart=always`), then run `systemctl --user enable --now news-archive`.
4. Record the source commit SHA and install date in the README's install log and on #229.
5. After 24 h and after 7 days, record the `status` output on #229.

**Rollback:** `systemctl --user disable --now news-archive`. The data stays.

## 9. Verification

| part | checks |
|---|---|
| A | Unit tests with sanitized fixtures for every adapter, covering: parsing; timestamp normalization (KST, ms, RFC-822); Hyperliquid snapshot diff, including a relisting getting a new id; idempotent insert; version transitions against the latest version (A→B→B→A); `after_gap` and `gaps` rows after start, after a simulated outage, on page overflow with bounded backfill, on Binance block suspension, on the disk guard and on a clock jump; backoff and `Retry-After`; the Binance rotation of one request per 3 min; the response-size cap; `status` output. Then the VPS `once` check, the unit's resource limits confirmed with `systemctl --user show`, and 7 days of `status`. |
| B | Unit tests for the report section (missing DB, all fresh, one stale, corrupt DB, local-only backup) and for the archive backup job: its own retention, and a failure that leaves the live-DB run untouched. Then one manual `--stdout` report run on the VPS after release, with the cron state backed up and restored as in the #219 deploy, and one local snapshot plus restore drill. The off-host leg is verified only once the remote is configured. |
| C | The prereg diff merged before Phase 1. The manifest SHA amendment merged before Phase 2. Unit tests for event extraction and classification, Hyperliquid eligibility (including `unknown`), announcement-level aggregation, the leak flag, the cost model and the concentration rule when the sum is ≤ 0. All checked against hand-computed klines fixtures. |

## 10. Left to the builder

- Exact canonicalization for `content_hash`, and the RSS parsing details (Atom vs RSS 2.0).
- The Binance monitoring-tag catalog id, and the Upbit KRW-addition title pattern, verified against live payloads.
- Whether `tree` uses a smaller `limit` once steady-state volume is known (never a shorter interval).
- Module layout inside `research/news_archive/`, as long as parsing stays pure and network-free testable.
- Whether Parts A, B and C ship as one PR or three. Three is preferred for review; C's prereg must merge before C's analysis runs.

## 11. Calls made by Claude (for the operator to check)

These were decided without the operator; each can be overridden before the plan is written.

1. **Step 0 deferred to the gate work.** No live bot imports `FearGreedIndex` (§7).
2. **Different event studies.** Binance delisting/monitoring-tag (short) and Upbit KRW listing (long), not a re-run of the closed Binance listing study (§6.1).
3. **Tradeable venues only.** The delisting short counts only tokens with a Hyperliquid perp at t0. The Upbit long uses Hyperliquid or Binance spot. Binance futures is CVM-blocked, so it never counts as an execution venue (§6.2).
4. **One test for the delisting study.** Monitoring tags and delistings share a single pass/fail, with fixed rules for what counts as an event (§6.2).
5. **INCONCLUSIVE, not FAIL, when the data cannot decide.** This applies in three cases: fewer than 20 announcements; `unknown`, `missing` and `unresolved` events together above 20% of candidates; or any `unresolved` post-entry event at all. Nothing is authorized, and any re-test is forward-only (§6.2).
6. **Coverage holes are marked.** The `after_gap` flag and the durable `gaps` table cover restarts, outages, page overflow, suspensions, the disk guard and clock faults (§4.3).
7. **Binance request budget.** The archive sends at most one Binance CMS request every 3 minutes in total, suspends for 6 h on any block signal, and leaves `listing-monitor` untouched. It does not get a separate egress IP (§4.2).
8. **Separate backup job.** The archive gets its own job, independent of the live-DB backup. Off-host copies count only after the remote is verified and a restore drill passes (§5.2).
9. **Part C hardening after the Astra review (§6.2):**
    - window 2023-01-01 to 2026-10-31;
    - an outcome-blind manifest whose hash is frozen before any returns are computed;
    - positive-evidence Hyperliquid eligibility;
    - entry at t+5 min;
    - 10 bps per side of slippage in the criteria;
    - the announcement as the unit of analysis;
    - "proxy result" labelling.
10. **Astra review finding 4, partly rejected.** Astra asked that proxy (Binance-price) results count as inconclusive. They stay decisive for the screen, because a pass authorizes only a paper monitor that measures real Hyperliquid prices (§6.2).
11. **Resource ceilings.** The unit runs with `MemoryMax=256M`, a 25% CPU quota and idle IO priority, plus a 15 GB free-disk guard and bounded logs (§4.4).
12. **No Telegram news channels or X APIs in v1.**
   - Telegram: the only Telegram user session is the live Killers observer's. A second client on it, or a restart to add channels, puts the live pipeline at risk.
   - X APIs: they cost money and the third-party ones break X's terms.
   - Tree of Alpha already relays posts from more than 2,300 X accounts (§2).
