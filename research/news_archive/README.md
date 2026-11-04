# news-archive — point-in-time (PIT) news archive

Part A of [#229](https://github.com/IvPalmer/Master-Trader/issues/229). Design:
[spec §4](../../docs/superpowers/specs/2026-11-03-news-archive-design.md#4-part-a--pit-news-archive).
A host-side research monitor on the VPS in the `listing-monitor` / `hl-shadow` pattern:
stdlib-only Python 3.12, a systemd **user** unit, no fleet containers, never touches the
Dokploy checkout. **It never trades and no bot reads it.** A crash here cannot affect a bot.

## What it does

`news_archive.py run` is one process with one sequential scheduler loop (5 s tick, no
threads). Each source is polled at its interval. Every item is stored once in SQLite
(`data/archive.sqlite`, WAL) with:

- `received_at`: our clock when the HTTP response arrived;
- `published_at`: the source's claimed time, normalized to UTC, or NULL;
- the raw item as canonical JSON, plus its sha256 `content_hash`.

When an item seen again differs from its **latest** version, an `item_revisions` row records
the transition (A→B→B→A stores two). The `items` row keeps the first version.

## Sources (v1)

| key | endpoint | interval | item id | `published_at` |
|---|---|---|---|---|
| `tree` | `news.treeofalpha.com/api/news?limit=200` | 60 s | `_id` | `time` (ms) |
| `binance_listing` | Binance CMS catalog 48, page 1, 20 items | rotation | `id` | `releaseDate` (ms) |
| `binance_delisting` | Binance CMS catalog 161, page 1, 20 items | rotation | `id` | `releaseDate` (ms) |
| `upbit` | `api-manager.upbit.com/api/v1/announcements?…category=trade` | 120 s | `id` | `first_listed_at` (KST) |
| `okx_listings`, `okx_delistings` | `okx.com/api/v5/support/announcements` | 300 s | URL without locale | `pTime` (ms) |
| `hyperliquid_universe` | `POST api.hyperliquid.xyz/info {"type":"meta"}` | 300 s | `universe:<seq>`, `add:/remove:/delisted:<NAME>:<seq>` | none (`received_at` is the event time) |
| `rss_coindesk`, `rss_theblock`, `rss_decrypt`, `rss_blockworks`, `rss_cointelegraph`, `rss_fed` | RSS 2.0 / Atom feeds (`na_sources.RSS_FEEDS`) | 300 s | `guid` / Atom `id`, else link | `pubDate` / `published`, else `updated` |
| `ff_calendar` | `nfs.faireconomy.media/ff_calendar_thisweek.json` | 6 h | `sha1(title|country|date)` | `date` (event time) |
| `fear_greed` | `api.alternative.me/fng/?limit=1` | 1 h | `timestamp` | `timestamp` (s) |

**Binance budget.** At most one CMS request every 180 s across *every* caller (this
service, `once`, the Part C harvester), through the file-locked limiter in
`data/binance_cms_state.json`. Each catalog therefore polls about every 6 min
(`interval_s` = 360). One attempt, no retry. HTTP 403/418/429, or any non-JSON body,
suspends all Binance sources for 6 h, persisted in the same file, and opens a `suspended`
gap. Redirects are never followed (a 3xx is a failed poll, and for Binance a block
signal); an oversized or stalled Binance response with an HTTP status also suspends. A
limiter state file that exists but cannot be parsed fails closed with a 6 h suspension.
Within one boot the gap and the suspension are also enforced in monotonic time, so a
forward wall-clock step cannot shorten them.
`listing-monitor` is not touched.

**Findings from the fixture capture (2026-11-03):**

- **Binance monitoring tag:** monitoring-tag notices are published in catalog **161**
  (Delisting), e.g. id 277436, "Binance Will Extend the Monitoring Tag to Include …", so
  no separate `binance_monitoring` source was added. Only one appeared in the 50 most recent
  161 notices; the Part C harvester should still confirm that none live elsewhere.
- **Upbit is blocked from the VPS IP.** Cloudflare returned 403 "Attention Required" from
  the VPS with both our User-Agent and a browser one; the same request from another IP
  returned 200. Expect `once` to report `FAILED upbit` at install; per spec §8 it is then
  disabled (`NEWS_ARCHIVE_DISABLE=upbit`) and noted on #229. The Part C Upbit harvest
  cannot run from the VPS either until this changes.
- **Upbit publish time:** `listed_at` moves when a notice is edited (id 6687:
  `listed_at` 21:50 KST, `first_listed_at` 20:00 KST), so `published_at` uses
  `first_listed_at`. The raw item keeps both.
- **OKX** returns locale-prefixed URLs from the VPS (`/pt-br/help/…`); the item id drops
  the locale segment so a locale change cannot duplicate items.
- CoinDesk and Blockworks redirect (308); the source table uses the final URLs.
  Blockworks is Atom, the other five feeds are RSS 2.0.

## Coverage holes and the PIT rule

Holes are durable rows in `gaps` (never pruned):

| reason | opens | closes |
|---|---|---|
| `restart` | at startup, closed at once: last OK poll → startup | — |
| `outage` | a source has no OK poll for more than 2 × `interval_s` | its next OK poll |
| `overflow` | a list-feed page holds no previously seen id; one bounded backfill (Tree `limit=2000`, Upbit/OKX ≤ 3 extra pages, Binance and RSS none). Written closed, `detail` = `recovered` / `unrecovered` | — |
| `suspended` | a Binance block signal (any caller) | that source's next OK poll, or at startup once the 6 h have passed |
| `disk` | free space below 15 GiB: nothing is stored, the poll counts as failed | the next OK poll, or at startup |
| `clock` | wall clock jumps > 2 s against the monotonic clock (checked each tick and again before each poll's writes), or `timedatectl` reports NTP unsynchronized (all sources) | the first tick with no jump; after an unsynchronized report, or at startup, only once `timedatectl` explicitly reports synchronized |

While an ongoing gap (`clock`, `disk`, `suspended`, `outage`) is open for a source, every
item and revision written for it gets `after_gap = 1`. So does the first OK poll after
startup, a poll whose previous OK poll is older than 2 × `interval_s`, and every backfill
item.

**PIT rule for readers** (Part C, any later gate): a record is PIT-valid only if
`after_gap = 0` **and** its `received_at` lies outside every gap interval of its source
(bounds inclusive, open gaps extend to now). Use `na_store.pit_valid(conn, source,
received_at)`.

## Limits

`MemoryMax=256M`, `CPUQuota=25%`, `Nice=10`, `IOSchedulingClass=idle`, `Restart=always`
with `RestartSec=30`; after 5 failed starts in 10 min the unit stays down. Response reads
cap at 5 MB; a poll stops issuing requests (backfill included) after 20 s. Backoff is
`interval × 2^failures` capped at 30 min, never shorter than the base interval; a 429
`Retry-After` is honoured. `polls` rows are pruned after 180 days; items, revisions, gaps
and `clock_checks` never are. `run` and `once` take `data/archive.lock`, so only one writer
runs at a time.

Known limitations:

- Revisions are only seen for items still on a source's first page.
- Each request gets the poll's remaining time (at most 10 s) as its socket timeout, and the
  20 s deadline is checked between 64 KB body chunks, so one slow read can overrun the
  deadline by at most one socket timeout.
- `received_at` relies on the VPS clock (NTP-synchronized; checked hourly).

## Commands

```bash
python3 news_archive.py run                     # the service (systemd)
python3 news_archive.py once [--source KEY ...] # one poll per source, then exit; exit 1 if any failed
python3 news_archive.py status                  # per source: last OK poll, failures, 24 h OK ratio,
                                                # items 24 h / 7 d / total, newest published_at; open gaps
```

`once` waits for the Binance limiter, so a full run takes 3–6 min. `once` refuses to run
while the service holds the writer lock (exit 3); stop the unit first.

## Monitoring and backup

- **Nightly report.** The health report's last block, `NEWS ARCHIVE`, reads this database
  read-only (`ft_userdata/news_archive_report.py`): sources OK out of enabled, one line per
  stale source (no OK poll for `3 × interval + 10 min`), open gaps, gaps closed in 24 h and
  unrecovered overflow in 7 d, plus the backup state. Only liveness counts, so a feed that
  polls OK but publishes nothing (`rss_blockworks`) reports OK. Non-list feeds
  (`fear_greed`, `ff_calendar`, `hyperliquid_universe`) have no loss detector.
- **Backup.** A separate root job, `deploy/vps/backup_news_archive.py`, snapshots this
  database daily to `/home/ubuntu/backups/news-archive/`; off-host upload and restore
  drills are opt-in. Contract, install and rollback:
  [docs/ops/news-archive-backup.md](../../docs/ops/news-archive-backup.md).

## Install (spec §8, only after the operator's go-ahead)

1. Copy `research/news_archive/` from the merged `main` commit to
   `/home/ubuntu/master-trader/research/news_archive/` on the VPS. Never into the Dokploy
   checkout.
2. `cd /home/ubuntu/master-trader/research/news_archive && python3 news_archive.py once`.
   Every source must report `OK`; disable the failing ones with
   `Environment=NEWS_ARCHIVE_DISABLE=<keys>` in the unit and note them on #229.
3. `cp news-archive.service ~/.config/systemd/user/ && systemctl --user daemon-reload &&
   systemctl --user enable --now news-archive`.
4. Record the source commit SHA and date below and on #229.
5. After 24 h and after 7 days, post `python3 news_archive.py status` on #229.
6. Confirm the limits: `systemctl --user show news-archive -p MemoryMax -p
   CPUQuotaPerSecUSec -p Nice -p IOSchedulingClass`.

Logs: `journalctl --user -u news-archive -f`, or `monitor.log` (daily rotation, 14 gzipped
files).

**Rollback:** `systemctl --user disable --now news-archive`. The data stays in `data/`.

## Install log

| date | source commit | by |
|---|---|---|
| 2026-11-04 01:29 UTC | `beccbb0` | Claude, on the operator's go-ahead. `once`: 14/15 OK; `upbit` FAILED with HTTP 403 from the VPS IP, as expected, so the installed unit sets `Environment=NEWS_ARCHIVE_DISABLE=upbit`. Unit limits confirmed. `rss_blockworks` polls OK, but the newest item in its feed is dated 2026-01-07: the feed itself is stale. |
