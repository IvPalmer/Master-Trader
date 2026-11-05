# upbit-fade-forward: Upbit KRW listing fade, paper forward monitor

Issue [#229](https://github.com/IvPalmer/Master-Trader/issues/229). Design:
[2026-11-05-upbit-fade-forward-design.md](../../docs/superpowers/specs/2026-11-05-upbit-fade-forward-design.md).
Frozen rules: preregistration `upbit-krw-fade-forward-2026-11` in
`ft_userdata/preregistrations.json` (`uff_common.py` holds the same constants, and
`tests/test_upbit_fade_forward_prereg.py` pins one to the other).

**Paper only. It places no orders and holds no keys.** Nothing in the fleet imports it, and no
result changes a deploy, a config, sizing or an allocation. A host-side research monitor on the
VPS in the `news-archive` pattern: stdlib-only Python 3, one sequential loop, a systemd
**user** unit, no containers, never touches the Dokploy checkout.

## What it measures

Part C Phase 2 (#248) found shorting Hyperliquid perps 5 min after an Upbit KRW-addition
notice and holding 24 h positive, on Binance proxy prices with no funding and assumed
detection. This monitor measures the same rule forward:

1. **Detection.** Every 15 s it reads the PIT news archive (`research/news_archive`)
   read-only, with durable cursors over `items.item_pk` and `item_revisions.rev_pk`. Tree
   records whose `url` is an `upbit.com/service_center/notice` page are classified with
   `nes_classify` (by import). One event per (notice id, token). Notices mentioning 거래지원
   or 마켓 that do not classify go to the unclassified queue and are never traded.
2. **t0** is Tree's `published_at` (a **Tree-clock cohort**). Timing is `unverified` when
   `published_at` is missing, later than `received_at`, or more than 5 min earlier.
3. **Eligibility at t0.** Excluded: already on Upbit KRW (last `market/all` snapshot before
   t0, at most 15 min old), a Binance new-listing notice in the 24 h before t0 that the
   archive had received by t0 (`binance_listing`, revisions included; later receipts are
   descriptive `late`), or a body saying trading began before the notice. Hyperliquid eligibility is the Part C rule (`nes_venues.hl_facts`), plus the perp
   must be in today's `meta`.
4. **Paper trade.** At max(t0 + 5 min, detection) it walks the live `l2Book` bids for about
   100 USDC and freezes q (rounded to `szDecimals`). Marks of q at +30 min and +4 h; exit
   buys q back from the asks at entry + 24 h. A book older than 5 s, or thinner than q, is
   rejected for that attempt. Fee 4.5 bps on each leg's actual notional; the walk is the
   slippage. Funding: finalized `fundingHistory` rates x q x `oraclePx` observed through
   `metaAndAssetCtxs` within 60 s after each hour (estimated; positive funding pays the
   short). MAE/MFE from 1 m `candleSnapshot` candles (descriptive; `ok` only with every
   minute of the hold, else `partial` with candle counts).
5. **Cohorts.** *Comparable* (the decision set) also needs Binance 1 m klines closed
   by t0 in [t0 - 10 min, t0) (USDⓈ-M first, else spot), the Part C leak test passed on them, and an
   entry filled within 2 min of t0 + 5 min. A requirement that fails makes the event
   *descriptive*; one that cannot be established (a fetch that never succeeded, an entry
   never filled) keeps it comparable with a **missing** outcome, so it counts in the tipping
   point. A known trading start is **not** required (Tree carries no Upbit body; spec,
   *Claude's call 2026-11-05*): no body, or no start in it, sets `start_unknown = true`. Two
   descriptive extras never select events: `start_unknown`, and `krw_market_first_seen_ms`
   (the first `market/all` snapshot after t0 that lists `KRW-<TOKEN>`). A later duplicate or
   revision of the notice with a stated start is a versioned `evidence` record, never a
   second event: before the entry decision it can exclude the event or make its start
   known; after it, it is descriptive only.
6. **Resolution.** Announcement-level mean net 24 h return of the comparable cohort, A4
   calendar-month block bootstrap at **95%** (`nes_returns`, level passed explicitly). One
   decision, at 40 comparable announcements or on 2027-11-05: EDGE (lower bound > 0), NO
   EDGE (upper bound <= 0), else NOT DETERMINABLE. Reports at 20 and 30 are descriptive.
   Every report also gives the `start_unknown` and `krw_market_first_seen` counts and, as
   descriptive only, the same resolution on the `start_unknown = false` subset.

Every scheduled book action has a 10 min deadline, also across restarts: past it the outcome
is `missing`, and one later book walk (within 6 h) is kept as a separate `late` record, never
as the outcome. An entry is never opened late.

## Files

| file | role |
|---|---|
| `upbit_fade_forward.py` | CLI: `run`, `status` |
| `uff_monitor.py` | the loop: detection, fills, funding, audit, decision |
| `uff_detect.py` | archive cursors, notice ids, classification, Binance-prior lookup |
| `uff_venues.py` | paced Hyperliquid client (`nes_venues.HlClient`), Binance klines, Upbit markets; pure book walk, funding, excursion |
| `uff_report.py` | cohorts, outcomes, resolution, status |
| `uff_ledger.py` | append-only JSONL ledger, idempotent on replay |
| `data/ledger.jsonl` | every event, fill, mark, rejection, oracle read, funding, audit and decision (gitignored) |
| `data/upbit_markets.jsonl` | `market/all` snapshots: each poll's time and hash, each distinct market set once |
| `data/state.json` | the archive cursors (a lost file falls back to the epoch cursors) |
| `data/monitor.log` | log, daily rotation, 14 gzipped files |

The first `run` writes the **epoch**: the archive cursors start at its current maxima, so
nothing published before the monitor started is measured.

## Commands

```bash
python3 upbit_fade_forward.py run              # the service (systemd)
python3 upbit_fade_forward.py status           # open positions, closed results, cohorts,
                                               # latency, misses, unclassified, resolution
python3 upbit_fade_forward.py status --json
```

`--data-dir` and `--archive` override the defaults (`data/` beside the script,
`research/news_archive/data/archive.sqlite`) and go before the command
(`python3 upbit_fade_forward.py --data-dir /tmp/x status`). `run` takes `data/monitor.lock`;
`status` only reads and creates nothing.

## Install (only after the operator's go-ahead)

1. Copy `research/upbit_fade_forward/` **and** `research/news_event_studies/` from the merged
   `main` commit to `/home/ubuntu/master-trader/research/` on the VPS (the monitor imports
   `nes_classify`, `nes_venues`, `nes_returns` and `nes_util`; `nes_returns.tipping_point`
   needs the `level` argument from the same commit). `research/news_archive/` is already
   there and must stay running. Never copy into the Dokploy checkout.
2. From the VPS, check every endpoint answers 200:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' 'https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=1'
   curl -s -o /dev/null -w '%{http_code}\n' 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1'
   curl -s -o /dev/null -w '%{http_code}\n' 'https://api.upbit.com/v1/market/all?is_details=true'
   curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' \
        -d '{"type":"l2Book","coin":"BTC"}' https://api.hyperliquid.xyz/info
   ```

   A 451 or 403 from `fapi.binance.com` means USDⓈ-M klines are unreachable from the VPS:
   every Binance fact would then end `unknown` (a failed USDⓈ-M read never falls through to
   spot). Stop and report it on #229.
3. `cd /home/ubuntu/master-trader/research/upbit_fade_forward && python3 upbit_fade_forward.py status`
   prints `epoch not started`.
4. `cp upbit-fade-forward.service ~/.config/systemd/user/ && systemctl --user daemon-reload &&
   systemctl --user enable --now upbit-fade-forward`.
5. After 10 min, `status` shows the epoch and two `market/all` snapshots. Record the source
   commit and date below and on #229.
6. Confirm the limits: `systemctl --user show upbit-fade-forward -p MemoryMax -p
   CPUQuotaPerSecUSec -p Nice -p IOSchedulingClass`.

Logs: `journalctl --user -u upbit-fade-forward -f`, or `data/monitor.log`.

**Rollback:** `systemctl --user disable --now upbit-fade-forward`. The ledger stays in `data/`.

## Limits

`MemoryMax=512M`, `CPUQuota=25%`, `Nice=10`, `IOSchedulingClass=idle`, `Restart=always`
with `RestartSec=30`. Hyperliquid info calls: at most one per second; a 429 opens a backoff
(2 s doubling to 120 s) during which no request is sent. The bots share this IP; the monitor
is idle between events (one `market/all` request every 5 min, one archive read every 15 s).

## Known limitations

- **Tree carries no notice body** (the 3 Tree Upbit items in the VPS archive, 2026-11-05),
  and the VPS gets 403 from Upbit's announcements API. Nearly every event is therefore
  `start_unknown`, and the "began before the notice" exclusion can fire only if a body ever
  arrives. A notice that states a start before t0 cannot be screened out from the title.
- If Upbit lists `KRW-<token>` in `market/all` before the notice's t0, the already-on-KRW
  rule excludes the event. Check the first real events.
- Funding is estimated (observed `oraclePx`, not a settlement receipt).
- `received_at`, deadlines and book staleness use the VPS clock; t0 uses Tree's.
- Revisions are seen only while Tree still serves the item (Part A limitation).

## Install log

| date | source commit | by |
|---|---|---|
| 2026-11-05 18:54 UTC: installed, epoch 2026-11-05T18:54:28.399Z, archive cursors items_pk 1681 / rev_pk 2383, first market/all snapshot 300 KRW markets; 21 files hash-verified; code backup `~/backups/news_event_studies-code-pre249-20261105T1854Z.tgz` | main dcba075 (PR #249) | Claude |
