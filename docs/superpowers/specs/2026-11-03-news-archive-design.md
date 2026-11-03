# News/Sentiment Layer, Steps 0–1 — Design Spec

**Date:** 2026-11-03
**Status:** Draft for operator review
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
| `binance_listing` | Binance CMS `article/list/query?type=1&pageNo=1&pageSize=20&catalogId=48` (browser UA, as in `listing_short_forward/monitor.py`) | 180 s | `id` | `releaseDate` (ms) |
| `binance_delisting` | same endpoint, `catalogId=161` | 180 s | `id` | `releaseDate` |
| `upbit` | `GET https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=20&category=trade` | 120 s | `id` | `listed_at` (KST → UTC) |
| `okx_listings` / `okx_delistings` | `GET https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings` / `…-delistings` | 300 s | `url` | `pTime` (ms) |
| `hyperliquid_universe` | `POST https://api.hyperliquid.xyz/info {"type":"meta"}` | 300 s | synthetic `add:<NAME>` / `remove:<NAME>` (or `delisted:<NAME>`) from diffing the last stored universe | none; `received_at` is the event time |
| `rss_coindesk`, `rss_theblock`, `rss_decrypt`, `rss_blockworks`, `rss_cointelegraph`, `rss_fed` | the six feed URLs in the research notes | 300 s | `guid`, else `link` | `pubDate` |
| `ff_calendar` | `GET https://nfs.faireconomy.media/ff_calendar_thisweek.json` | 6 h | `sha1(title|country|date)` | `date` (event time) |
| `fear_greed` | `GET https://api.alternative.me/fng/?limit=1` | 1 h | `timestamp` | `timestamp` |

**Binance monitoring tag.** Binance also publishes "monitoring tag" announcements. The builder confirms which CMS catalog carries them. If it is not 48 or 161, that catalog is added as `binance_monitoring` with the same adapter and the same 180 s interval.

**Binance request budget (Claude's call).** `listing-monitor` already polls catalog 48 every 60 s for the open, blinded `listing-short-forward-2026-07` preregistration. That endpoint is not a documented public API, and a block on the VPS IP would cost that study events it sees about once every 81 days. The archive therefore staggers its Binance catalogs so it sends at most one Binance request per minute in total. Binance load from the VPS at most doubles, and `listing-monitor` is left untouched. Three minutes of latency is irrelevant for an archive. The later hard-event veto only has to beat the bots' 5m–1h candles.

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
  received_at TEXT NOT NULL, content_hash TEXT NOT NULL, raw_json TEXT NOT NULL
);
CREATE TABLE polls (
  poll_pk INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, ok INTEGER NOT NULL,
  http_status INTEGER, n_items INTEGER, n_new INTEGER, n_revised INTEGER, error TEXT
);
```

Storage rules:

- An item seen again with an identical `content_hash` does nothing.
- An item seen again with a different hash writes a row to `item_revisions`; the `items` row keeps its first version. This covers edited announcements and calendar actuals being filled in.
- Items are never deleted. Rows in `polls` older than 180 days are pruned once a day.
- The service writes `sources` at startup, so readers know each source's interval.
- `after_gap` marks items whose `received_at` only means "when we got back", not "when it was new". PIT analyses exclude them by default. A poll counts as following a gap when it is the source's first successful poll since process start, or when that source's previous successful poll is older than `2 × interval_s`. This covers outages and backoff, not just restarts. The flag sits on the item itself, so PIT validity does not depend on `polls` history surviving the 180-day prune (Claude's call).

### 4.4 Robustness

- No failure can kill the loop. Every exception is caught per poll, logged as one `[news-archive]` line, and recorded in `polls`.
- **Backoff:** after consecutive failures a source backs off exponentially from its base interval, capped at 30 min. On HTTP 429 the service honours `Retry-After` if present and backs off otherwise.
- **Identification:** a fixed, honest User-Agent, except for Binance, which needs the browser UA already proven in `listing_short_forward`.
- **Politeness on undocumented endpoints:** the poll intervals in §4.2 are the floor, not targets.

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
- **Isolation:** the section never changes the report's exit status, and no exception from it can break the report.
- **Tests:** network-free, against a temporary SQLite database built with the §4.3 schema.
- **Release:** the report wrapper is symlinked into the Dokploy checkout, so this ships through a `vps-deploy` release PR. No container is recreated. `main` currently holds an undeployed Killers strategy change (#181/#183, on hold per #188), so the release branch cherry-picks only this work onto `vps-deploy`, as the #228 release did. It must never be a full `main` merge.

### 5.2 Off-server backup (Claude's call: in scope)

The archive is irreplaceable by design: no vendor sells the same PIT history. A disk loss would reset the data clock to zero.

- **Where:** add the archive database to `deploy/vps/backup_live_dbs.py`, the existing root cron that ships to Google Drive with tiered retention. It uses the same consistent-snapshot method it already applies to the other SQLite databases.
- **Retention:** the default tiers keep 30 daily copies, so the archive gets its own smaller tier, with the disk at 82%. Suggested starting point: the last 7 daily copies plus 8 weekly copies. A month-old archive is small, so the real constraint is growth; the builder checks the total against the Drive quota.
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

- **Events, delisting study (Claude's call):**
  - **Counted:** one event per (announcement, token) for two kinds of notice:
    - a full Binance spot delisting, where the token loses every spot pair;
    - a new monitoring-tag assignment.
  - **Excluded:**
    - removal of individual trading pairs where the token keeps at least one spot pair;
    - margin-only and futures-only delistings;
    - vote-to-delist and similar polls;
    - removals of a tag;
    - retractions.
  - **Overlap:** if the same token has a second qualifying notice within 24 h of the first, only the first counts. A monitoring tag and a later delisting more than 24 h apart are two events.
  - **One test:** both kinds share one pass/fail. Per-kind results are reported as descriptive only. This keeps it to one preregistered test instead of two.
- **Events, Upbit study:** one event per (notice, token) for Upbit `category=trade` notices whose title matches the KRW-market-addition pattern. Tokens already on Upbit KRW are excluded, as are tokens not tradeable on an execution venue at t0 (below).
- **Execution venues (Claude's call):** Binance futures is CVM-blocked for the operator (see the `listing-reaction-study-2026-07` notes), so a result is only tradeable on these venues:
  - **Delisting study (short):** only tokens with a live Hyperliquid perp at t0 qualify. Binance spot cannot short, and a Binance-futures short is not tradeable here.
  - **Upbit study (long):** a Hyperliquid perp if one existed at t0, else Binance spot. Tokens that trade only on Binance futures are excluded.
  - **Dating Hyperliquid perps:** `meta` lists only the current universe, so the builder dates each perp from its earliest Hyperliquid daily candle (`candleSnapshot`, interval `1d`), or another documented method. That date is the perp's existence at t0. History before Hyperliquid perps existed (2023) mostly fails this filter, which is intended.
- **Timestamps:**
  - Binance: `releaseDate`.
  - Upbit: the builder documents whether `listed_at` or `first_listed_at` is the publish time. The prereg names the field before any computation.
  - Upbit only: events whose Upbit KRW trading began before the notice are flagged and excluded.
- **Price data:** Binance 1m klines from `data.binance.vision`, USDⓈ-M futures preferred, spot otherwise. This is a price proxy only: Hyperliquid 1m history is retained for days. Each event records which proxy series was used.
- **Entry:** taker at the t+60s 1m close. **Exits:** the fixed horizons +30 min, +4 h and +24 h. **Fees:** 4.5 bps per side for Hyperliquid execution, 7.5 bps for Binance spot, matching the listing study.
- **Leak flag:** reuse the listing study's rule: more than 2% absolute drift over [t0−10 min, t0−2 min]. The primary set excludes leaked events; a sensitivity run includes them.
- **Primary horizon:** +4 h, declared now.
- **Pass (all required):**
  - median net return at +4 h > 0 across at least 20 qualifying events;
  - positive median in both chronological halves;
  - the top decile of events contributes less than 60% of the total.
- **Kill:** with at least 20 qualifying events, any failed criterion closes that lane for this config. A pass authorizes only a paper forward monitor, preregistered separately, in the `listing-short-forward` style.
- **Too few events (Claude's call):** fewer than 20 qualifying events is recorded as **INCONCLUSIVE-by-data**, the precedent from the listing study's Hyperliquid venue. The lane stays open, but nothing is authorized: no monitor and no bot. The archive keeps recording these events. Any re-test is a new, forward-only preregistration; retrospective and forward events are never mixed.
- **Report:** the full distribution at all three horizons, both halves, per venue, and the leak sensitivity.
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
| A | Unit tests with sanitized fixtures for every adapter: parse, timestamp normalization (KST, ms, RFC-822), Hyperliquid diff, idempotent insert, revision on hash change, `after_gap` after start and after a simulated outage, backoff and `Retry-After`, the Binance one-request-per-minute stagger, `status` output. Then the VPS `once` check, then 7 days of `status`. |
| B | Unit tests for the report section (missing DB, all fresh, one stale, corrupt DB) and for the archive's backup retention tier. Then one manual `--stdout` report run on the VPS after release, with the cron state backed up and restored as in the #219 deploy, and one verified backup copy of the archive on Drive. |
| C | The prereg diff merged before analysis. Unit tests for event extraction, the leak flag and the return formula, checked against hand-computed klines fixtures. |

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
5. **Fewer than 20 events is INCONCLUSIVE, not FAIL.** Nothing is authorized, and any re-test is forward-only (§6.2).
6. **`after_gap` flag.** It replaces a start-only flag, so items stored after an outage are marked too (§4.3).
7. **Binance request budget.** The archive sends at most one Binance request per minute and leaves `listing-monitor` untouched (§4.2).
8. **Off-server backup in scope.** The archive joins `backup_live_dbs.py` with its own smaller retention tier (§5.2).
9. **No Telegram news channels or X APIs in v1.**
   - Telegram: the only Telegram user session is the live Killers observer's. A second client on it, or a restart to add channels, puts the live pipeline at risk.
   - X APIs: they cost money and the third-party ones break X's terms.
   - Tree of Alpha already relays posts from more than 2,300 X accounts (§2).
