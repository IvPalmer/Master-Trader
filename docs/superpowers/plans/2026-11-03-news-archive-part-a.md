# News Archive (Part A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A host-side, stdlib-only service that archives every item from the v1 news sources with our own `received_at` timestamp, records coverage holes, and can be checked with `status`.

**Architecture:** There are four modules in `research/news_archive/`:

- `na_store.py` — SQLite storage, versioning, gaps and the point-in-time (PIT) rule;
- `na_sources.py` — pure per-source parsers;
- `na_fetch.py` — bounded HTTP and the shared Binance limiter;
- `news_archive.py` — scheduler, CLI and ops.

Parsers and the store are pure and network-free. Only `na_fetch.fetch` touches the network, and the scheduler takes it as an injectable callable.

**Tech Stack:** Python stdlib only (`sqlite3`, `urllib`, `json`, `xml.etree`, `fcntl`, `logging.handlers`). It must run on Python 3.12 on the VPS and pass CI on 3.13. Tests use pytest.

**Spec:** [`docs/superpowers/specs/2026-11-03-news-archive-design.md`](../specs/2026-11-03-news-archive-design.md), §3, §4, §8 and §9 row A. The spec wins over this plan on any conflict. Parts B and C have their own plans: B depends on this schema, and C's preregistration must merge first.

## Global Constraints

- Stdlib only. No new dependency in any requirements file.
- Module names carry an `na_` prefix, except `news_archive.py`, so test-time `sys.path` imports cannot collide.
- Tests are network-free.
  - Fixtures are small, trimmed samples of real public payloads in `tests/fixtures/news_archive/`.
  - No credentials, no account identifiers, no raw archive data.
- `research/news_archive/data/` is gitignored. It holds `archive.sqlite` and `binance_cms_state.json`.
- All stored timestamps are ISO-8601 UTC with microseconds, e.g. `2026-11-03T20:15:53.061644+00:00`.
- Binance CMS: at most one request every 180 s across **all** callers. Single attempt, no retry. A block signal (HTTP 403, 418 or 429, or a body that is not JSON) suspends all Binance adapters for 6 h, persisted in `data/binance_cms_state.json`.
- Limits:
  - response reads capped at 5,000,000 bytes;
  - a 20 s deadline per poll and a 10 s HTTP timeout;
  - backoff capped at 1,800 s;
  - writes stop below 15 GB free (15 × 1024³ bytes);
  - `polls` rows pruned after 180 days;
  - `gaps`, `clock_checks` and `items` never pruned.
- An item or revision written while an ongoing gap (`clock`, `disk`, `suspended`, `outage`) is open for its source gets `after_gap = 1`.
- Overflow detection applies to list feeds only: `tree`, `binance_listing`, `binance_delisting`, `binance_monitoring`, `upbit`, `okx_listings`, `okx_delistings`, and every `rss_*` feed.
- Nothing in this plan touches `/etc/dokploy`, any container, any bot config, or `research/listing_short_forward/`.

## Review Focus

1. **A `200 OK` with an HTML error or captcha page** must be a failed poll, never a crash. For Binance it must be a block signal. Pinned in Task 4 (`test_html_body_is_block_signal`) and Task 5 (`test_html_200_records_failed_poll`).
2. **Missing or odd timestamps** (null, seconds instead of ms, naive datetimes, a non-UTC offset) must give `published_at = NULL` or a correct UTC value, never an exception. Pinned in Task 3 (`test_timestamp_edge_cases`).
3. **The same id twice in one page** must be stored once, with no false revision. Pinned in Task 1 (`test_duplicate_id_in_one_batch_is_one_item`).
4. **A reader holding a read transaction** (health report or backup) must not make the writer fail. WAL plus `busy_timeout=5000`. Pinned in Task 1 (`test_write_succeeds_while_reader_holds_snapshot`).
5. **A restart while `disk` or `suspended` gaps are open** must not leave gaps dangling forever. On startup the service re-evaluates each open ongoing gap and closes the ones whose condition is gone. The downtime itself becomes a closed `restart` gap. Pinned in Task 5 (`test_restart_closes_cleared_gaps_and_records_downtime`).

---

### Task 1: Store — schema, items, versions

**Files:**
- Create: `research/news_archive/na_store.py`, `research/news_archive/.gitignore` (one line: `data/`)
- Test: `tests/test_news_archive_store.py`. The module header puts `research/news_archive` on `sys.path`, then runs `import na_store`.

**Interfaces:**
- Produces:
  - `Item` — a frozen dataclass: `source_item_id: str`, `published_at: str | None`, `title: str | None`, `body: str | None`, `url: str | None`, `symbols: list | None`, `raw: dict`.
  - `connect(path: str) -> sqlite3.Connection` — creates the §4.3 tables, `PRAGMA journal_mode=WAL`, `busy_timeout=5000`.
  - `content_hash(raw: dict) -> str` — sha256 of `json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
  - `upsert_items(conn, source: str, items: list[Item], received_at: str, after_gap: bool) -> tuple[int, int]` — returns `(n_new, n_revised)` in one transaction.
  - `known_ids(conn, source: str, ids: list[str]) -> set[str]`.
  - `write_sources(conn, rows: list[tuple[str, int, bool]], now: str)`.
  - `record_poll(conn, source, started_at, finished_at, ok, http_status, n_items, n_new, n_revised, error)`.
  - `prune_polls(conn, now: str, keep_days: int = 180) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_items_inserted_once(tmp_path):            # same batch twice -> (2,0) then (0,0)
def test_duplicate_id_in_one_batch_is_one_item(tmp_path):  # [A, A] -> n_new == 1, no revision row
def test_versions_compare_against_latest(tmp_path):
    # upsert A, B, B, A for one id -> item_revisions has 2 rows:
    # (prev=hash(A), new=hash(B)) then (prev=hash(B), new=hash(A)); items row still holds A
def test_revision_inherits_after_gap_flag(tmp_path):   # revision written with after_gap=True stores 1
def test_write_succeeds_while_reader_holds_snapshot(tmp_path):
    # second connection opened "file:...?mode=ro", BEGIN; SELECT; then writer upsert succeeds
def test_prune_polls_keeps_180_days(tmp_path):         # rows at now-181d pruned, now-179d kept
```

- [ ] **Step 2:** Run `python -m pytest tests/test_news_archive_store.py -q`. Expected: FAIL (`ModuleNotFoundError: na_store`).
- [ ] **Step 3:** Implement `na_store.py` with the exact §4.3 DDL. Each item compares against its **latest** version: the newest `item_revisions.content_hash`, or else `items.content_hash`. Dedupe ids within a batch before writing, keeping the first occurrence.
- [ ] **Step 4:** Run the same command. Expected: 6 passed.
- [ ] **Step 5:** Commit with `git add research/news_archive tests/test_news_archive_store.py`, then `git commit -m "news-archive: store with latest-version revisions (#229)"`.

### Task 2: Store — gaps and the PIT rule

**Files:**
- Modify: `research/news_archive/na_store.py`
- Test: `tests/test_news_archive_store.py`

**Interfaces:**
- Consumes: `connect`, `upsert_items` (Task 1).
- Produces:
  - `ONGOING = ("clock", "disk", "suspended", "outage")`.
  - `open_gap(conn, source: str, reason: str, start: str, detail: str = "") -> int` — idempotent; it returns the existing open row for the same `(source, reason)`.
  - `close_gap(conn, source: str, reason: str, end: str) -> bool`.
  - `record_closed_gap(conn, source: str, reason: str, start: str, end: str, detail: str)` — used for `restart` and `overflow`.
  - `has_open_ongoing_gap(conn, source: str) -> bool`.
  - `open_gaps(conn) -> list[sqlite3.Row]`.
  - `pit_valid(conn, source: str, received_at: str) -> bool` — `False` if the record's `after_gap = 1` or `received_at` falls inside any gap interval for that source; open intervals extend to now.
  - `upsert_items(...)` ORs `has_open_ongoing_gap` into `after_gap`.

- [ ] **Step 1: Write the failing tests**

```python
def test_open_gap_is_idempotent(tmp_path):                 # two opens -> one row
def test_items_during_open_ongoing_gap_are_tainted(tmp_path):  # open "clock", upsert -> after_gap == 1
def test_closed_overflow_gap_does_not_taint_later_items(tmp_path):
    # record_closed_gap(overflow, t1, t2, "unrecovered"); upsert at t3 > t2 -> after_gap == 0
def test_pit_valid_rejects_inside_gap_and_flagged(tmp_path):
    # inside [t1,t2] -> False; after t2 with after_gap=0 -> True; after_gap=1 -> False
```

- [ ] **Step 2:** Run `python -m pytest tests/test_news_archive_store.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the functions above in `na_store.py`.
- [ ] **Step 4:** Run the same command. Expected: 10 passed.
- [ ] **Step 5:** Commit: `git commit -am "news-archive: gaps and pit_valid (#229)"`.

### Task 3: Source parsers

**Files:**
- Create: `research/news_archive/na_sources.py`, plus `tests/fixtures/news_archive/` with one trimmed sample per source (2–3 items each):
  - `tree.json`, `binance_cms_48.json`, `binance_cms_161.json`, `upbit.json`, `okx_listings.json`;
  - `rss_coindesk.xml` (RSS 2.0), `atom_sample.xml`;
  - `ff_calendar.json`, `fear_greed.json`, `hl_meta_a.json`, `hl_meta_b.json`.
- Test: `tests/test_news_archive_sources.py`

**Interfaces:**
- Consumes: `na_store.Item`.
- Produces:
  - `SourceSpec` — a frozen dataclass: `key: str`, `method: str`, `url: str`, `body: bytes | None`, `headers: dict`, `interval_s: int`, `list_feed: bool`, `binance: bool`, `parse: Callable[[bytes], list[Item]]`, `backfill: Callable[[], list["SourceSpec"]] | None`.
  - `SOURCES: dict[str, SourceSpec]` — every key in spec §4.2, with the §4.2 URLs and intervals. Binance specs set `binance=True`; their interval is ignored, since the limiter paces them.
  - `binance_monitoring` is added only if the fixture capture shows that monitoring-tag notices live in a catalog other than 48 or 161. Record the finding in the README either way.
  - `to_utc(value, kind: str) -> str | None`, where `kind` is one of `"ms"`, `"s"`, `"kst"`, `"rfc822"`, `"iso"`.
  - `diff_universe(prev: set[str] | None, cur: set[str], seq: int) -> list[Item]` — items `add:<NAME>:<seq>` and `remove:<NAME>:<seq>`. It returns `[]` when `prev is None`; the first snapshot is stored only as `universe:<seq>`.
- Capturing fixtures: on the VPS, `curl -s` each URL from spec §4.2 once. For Binance, use the `listing_short_forward/monitor.py` browser UA, and make at most 2 requests, more than 180 s apart. Trim each payload to 2–3 items and commit the trimmed files only.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("key,fixture,n", [("tree","tree.json",2), ("binance_delisting","binance_cms_161.json",2), ...])
def test_parser_yields_items_with_ids_and_utc(key, fixture, n):
    # every item: non-empty source_item_id; published_at None or endswith "+00:00"
def test_upbit_kst_converted_to_utc():          # "2026-10-27T16:30:00+09:00" -> "2026-10-27T07:30:00.000000+00:00"
def test_rss_and_atom_ids_use_guid_else_link():
def test_tree_symbols_come_from_suggestions():   # Item.symbols == fixture's suggestions list
def test_ff_calendar_id_is_sha1_title_country_date():
def test_diff_universe_relisting_gets_new_ids():  # A->B->A->B: remove/add ids carry seq 2, 3, 4; none collide
def test_timestamp_edge_cases():                 # None, "", 1730000000 (s) vs 1730000000000 (ms), naive iso -> None or UTC, never raises
```

- [ ] **Step 2:** Run `python -m pytest tests/test_news_archive_sources.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement the parsers, `to_utc`, `diff_universe` and `SOURCES`. Use `xml.etree.ElementTree` for RSS and Atom. Tree's backfill spec uses `limit=2000`. Other list feeds back off by up to 3 extra pages through `page` or `after` params; Binance never backfills.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5:** Commit: `git add research/news_archive/na_sources.py tests/fixtures/news_archive tests/test_news_archive_sources.py`, then `git commit -m "news-archive: v1 source parsers (#229)"`.

### Task 4: Bounded fetch and the shared Binance limiter

**Files:**
- Create: `research/news_archive/na_fetch.py`
- Test: `tests/test_news_archive_fetch.py`

**Interfaces:**
- Produces:
  - `Response` — a dataclass: `status: int`, `body: bytes`, `headers: dict`.
  - `fetch(spec, timeout_s=10, max_bytes=5_000_000, opener=urllib.request.urlopen) -> Response` — raises `FetchError` on oversize or transport failure; HTTP errors come back as a `Response`.
  - `is_block_signal(resp: Response) -> bool` — status in {403, 418, 429} or a body that is not JSON.
  - `BinanceLimiter(state_path: str)` with three methods, each under one `fcntl.flock` on the state file:
    - `try_acquire(now: float) -> bool`;
    - `suspend(now: float, hours: float = 6) -> None`;
    - `suspended_until(now: float) -> float | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_oversize_body_raises(): ...                      # fake opener yields 5_000_001 bytes
def test_html_body_is_block_signal():                    # Response(200, b"<html>captcha</html>") -> True
def test_limiter_one_request_per_180s_across_instances(tmp_path):
    # two BinanceLimiter objects on the same file: t=0 A True, t=10 B False, t=181 B True
def test_suspension_persists_across_instances(tmp_path):  # A.suspend(0); new instance: try_acquire(3600) False, (6*3600+1) True
```

- [ ] **Step 2:** Run `python -m pytest tests/test_news_archive_fetch.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Read with `resp.read(max_bytes + 1)`. The state file holds JSON `{"last_request": float, "suspended_until": float|null}`.
- [ ] **Step 4:** Run the same command. Expected: 4 passed.
- [ ] **Step 5:** Commit: `git commit -m "news-archive: bounded fetch and shared Binance limiter (#229)"` (add both files first).

### Task 5: Scheduler — polling, backoff, gaps, guards

**Files:**
- Create: `research/news_archive/news_archive.py`, the `Archive` class only, no CLI yet.
- Test: `tests/test_news_archive_service.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `Archive(conn, sources: dict, limiter, fetcher, wall: Callable[[], float], mono: Callable[[], float], free_bytes: Callable[[], int], clock_probe: Callable[[], bool | None])` with these methods:
  - `startup() -> None` — writes `sources`. Records one closed `restart` gap per source, from the last OK poll to now. Closes open `disk`/`suspended`/`clock` gaps whose condition has cleared.
  - `poll(key: str) -> bool` — one source, with the full rules below.
  - `tick() -> None` — runs every due source, then the hourly clock check and the daily `prune_polls`.
- Rules for `poll(key)`:
  - **after_gap:** set on the first OK poll since startup, or when the previous OK poll is older than `2 × interval_s`. That case also gets a closed `outage` gap.
  - **Backoff:** `interval × 2^failures`, capped at 1,800 s, or `Retry-After` on a 429.
  - **Binance:** a Binance poll goes ahead only if `limiter.try_acquire()` succeeds. `is_block_signal` → `limiter.suspend()` and an `open_gap(..., "suspended")` for every Binance source.
  - **Overflow:** for a list feed, a page with zero ids already in `known_ids` (when the source has prior items) → one backfill. Then `record_closed_gap(overflow, prev_ok, now, "recovered" | "unrecovered")`; it is `recovered` when the backfill page overlaps known ids.
  - **Disk:** `free_bytes() < 15 * 1024**3` → `open_gap(..., "disk")` and no item writes.
  - **Clock:** a wall-minus-monotonic jump above 2 s between ticks, or `clock_probe()` returning `False`, opens a `clock` gap for every source and writes a `clock_checks` row.
  - **No crash:** every exception is caught, logged and recorded as a failed poll.
  - **Deadline:** a poll, backfill included, stops issuing requests once 20 s have passed since it started.
  - **`hyperliquid_universe`:** parse the asset-name set from the response. If it differs from the latest stored `universe:<seq>` snapshot, store the new snapshot as `universe:<seq+1>` plus the `diff_universe(prev, cur, seq+1)` items. `seq` is the count of stored universe snapshots.

- [ ] **Step 1: Write the failing tests.** Use a fake fetcher keyed by URL, fake clocks and an in-memory or `tmp_path` database.

```python
def test_first_poll_after_start_marks_after_gap():
def test_outage_longer_than_two_intervals_marks_after_gap_and_closed_outage_gap():
def test_backoff_doubles_and_caps_at_1800_and_honours_retry_after():
def test_binance_block_suspends_all_binance_sources_and_opens_gaps():
def test_overflow_triggers_one_backfill_and_closed_gap():   # recovered vs unrecovered cases
def test_no_overflow_check_for_fear_greed():
def test_disk_guard_stops_writes_and_opens_disk_gap():
def test_clock_jump_opens_clock_gap_for_all_sources():
def test_html_200_records_failed_poll():
def test_restart_closes_cleared_gaps_and_records_downtime():
```

- [ ] **Step 2:** Run `python -m pytest tests/test_news_archive_service.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `Archive`. Keep per-source state (`failures`, `next_due`, `last_ok`) in memory, rebuilt from `polls` at `startup()`.
- [ ] **Step 4:** Run the same command. Expected: 10 passed.
- [ ] **Step 5:** Commit: `git commit -m "news-archive: scheduler with gaps, backoff and guards (#229)"` (add both files first).

### Task 6: CLI, status, logging and ops files

**Files:**
- Modify: `research/news_archive/news_archive.py`, adding `main(argv)` and the `run`/`once`/`status` subcommands.
- Create: `research/news_archive/news-archive.service`, `research/news_archive/README.md`
- Test: `tests/test_news_archive_service.py`

**Interfaces:**
- Consumes: `Archive` (Task 5), `na_fetch.fetch`, `BinanceLimiter`.
- Produces:
  - `status_lines(conn, now: str) -> list[str]` — one line per source: last OK poll, consecutive failures, 24 h OK ratio, items in 24 h / 7 d / total, newest `published_at`. Plus one line per open gap. Part B reuses the same queries.
  - `main(argv: list[str]) -> int`.
  - **`once [--source KEY]`:** polls the named sources, or all of them, then exits. Binance sources still go through the limiter, so a full `once` takes about 6 min for them.
- **Logging:** `logging.handlers.TimedRotatingFileHandler("monitor.log", when="midnight", backupCount=14, utc=True)`, with `namer`/`rotator` gzipping rotated files. Each line is prefixed `[news-archive]` and also goes to stdout.
- **Unit file:** `[Service]` with `WorkingDirectory=/home/ubuntu/master-trader/research/news_archive`, `ExecStart=/usr/bin/python3 /home/ubuntu/master-trader/research/news_archive/news_archive.py run` and the limits below. `[Unit]` sets `StartLimitIntervalSec=600` and `StartLimitBurst=5`.

  | directive | value |
  |---|---|
  | `MemoryMax` | `256M` |
  | `CPUQuota` | `25%` |
  | `Nice` | `10` |
  | `IOSchedulingClass` | `idle` |
  | `Restart` | `always` |
  | `RestartSec` | `30` |

- **README:** what the service does, the source table, the §8 install and rollback steps, the PIT rule and `pit_valid`, and an install log table: date, commit SHA, who.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_lines_report_each_source_and_open_gaps(tmp_path):
def test_unit_file_has_resource_limits():   # parse the .service text; assert each directive above present with exact value
def test_once_single_source_exits_zero(tmp_path, monkeypatch):  # fake fetcher, main(["once","--source","fear_greed"]) == 0
```

- [ ] **Step 2:** Run `python -m pytest tests/test_news_archive_service.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement `status_lines`, `main` and logging, and write the unit file and README.
- [ ] **Step 4:** Run `python -m pytest tests/ -q`. Expected: the whole root suite passes, with no new skips.
- [ ] **Step 5:** Commit: `git commit -m "news-archive: CLI, status, logging and systemd unit (#229)"` (add the new files first).

### Task 7: PR, then VPS install after the operator's go-ahead

Not a code task.

- [ ] **Step 1:** Open a PR to `main` titled `news-archive: Part A PIT news archive (#229)` with `Refs #229`. Record the test counts and the limitations: install not done, endpoints not verified beyond fixture capture.
- [ ] **Step 2:** Run a focused Codex Sol/high review of the diff, per `~/.claude/codex-usage.md`. Fix the valid findings, then merge when authorized.
- [ ] **Step 3: Only after an explicit operator go-ahead to install.** Follow spec §8 steps 1–5 exactly:
  1. Copy from the merged `main` SHA.
  2. Run `once`.
  3. Install and enable the user unit.
  4. Record the SHA on #229.
  5. Record `status` on #229 at 24 h and at 7 days.
  6. Confirm the limits with `systemctl --user show news-archive -p MemoryMax -p CPUQuotaPerSecUSec -p Nice -p IOSchedulingClass`.
