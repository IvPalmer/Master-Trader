# News Archive (Part B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PIT news archive visible in the nightly health report and give it its own backup job. Neither can affect the report, the live-DB backup or a bot.

**Architecture:** Two new stdlib modules and a small hook:

- `ft_userdata/news_archive_report.py` is the read-only report section: freshness, gaps and backup state. It runs its own SQL against the spec §4.3 schema and imports no Part A code, so the Dokploy checkout the report runs from needs nothing under `research/`.
- `deploy/vps/backup_news_archive.py` is a root cron job. It takes a consistent snapshot, applies its own retention, and optionally makes a verified rclone upload and a restore drill. It writes `STATUS.json`, which the report reads. It imports helpers from `backup_live_dbs.py` and never modifies that file.
- `strategy_health_report.py` gains `news_archive_section()`, which does the import and the call inside one `try`, and a last block, `NEWS ARCHIVE`.

**Tech Stack:** Python stdlib (`sqlite3`, `json`, `fcntl`, `gzip`, `hashlib`, `subprocess`, `tempfile`), rclone v1.73.0 on the VPS, pytest. The VPS host runs Python 3.12, CI runs 3.13.

**Spec:** [`docs/superpowers/specs/2026-11-03-news-archive-design.md`](../specs/2026-11-03-news-archive-design.md): §5, §9 row B, and the schema and robustness rules in §4.3–4.4. The spec wins over this plan on any conflict. Part A is merged (`beccbb0`) and was installed on 2026-11-04.

**Runtime facts (read-only check on the VPS, 2026-11-04 02:00 UTC):**

- **The report:** ubuntu's crontab runs `/home/ubuntu/master-trader/run-health-report.sh` at 23:00 UTC. That wrapper is a symlink into the Dokploy checkout. It runs `/usr/bin/python3 strategy_health_report.py` **on the host**, as `ubuntu`, from `runtime/ft_userdata`, and appends all output to `research/logs/health_report.log`. So it reads the archive at its host path; there is no container mount to cross.
- **The archive:** `/home/ubuntu/master-trader/research/news_archive/data/archive.sqlite` is owned by `ubuntu`, mode 0644, WAL, 2.8 MB including the WAL. The `sources` table holds `upbit` with `enabled = 0` (set by `NEWS_ARCHIVE_DISABLE=upbit`) and 14 enabled sources, all fresh. There are 0 open gaps and 14 closed `restart` gaps from the install.
- **Root's crontab:**
  - `15 3 * * *` runs `backup_live_dbs.py` from the root-owned Dokploy path. Its log shows a daily `OK` with an `rclone check` against Drive.
  - `45 3 * * *` runs an interim `rclone copy /home/ubuntu/backups/master-trader operator-drive:Master-Trader/backups` ("until GROA-266 deploy").
  - The `operator-drive` remote is configured in `/etc/master-trader-backup/rclone.conf` (root, 0600).
- **The Dokploy checkout** is root-owned, at `b5ed915` on `vps-deploy`, clean apart from one known untracked `.env.before-tp-*` file. Dokploy `autoDeploy` is `f`.
- **Disk:** 31 GB free (85% used).

## Global Constraints

- **Stdlib only** in both new modules. No requirements file changes. Host `/usr/bin/python3` is 3.12; CI is 3.13.
- **Files nothing in this plan may change:**
  - any bot, container, compose file or `/etc/dokploy` config;
  - `research/news_archive/*.py` and `research/listing_short_forward/`;
  - `deploy/vps/backup_live_dbs.py`. It is imported, never edited, so the live job's next run is the same code.
- **Tests are network-free.** Archive fixtures are built with Part A's `na_store` (`connect`, `write_sources`, `record_poll`, `upsert_items`, `open_gap`, `record_closed_gap`), imported from `research/news_archive` on `sys.path`, so the fixture schema cannot drift from the real one. Fixtures hold no raw archive data.
- **Report: opening the archive.** The path comes from env `NEWS_ARCHIVE_DB`, defaulting to `/home/ubuntu/master-trader/research/news_archive/data/archive.sqlite`. It is opened with `sqlite3.connect(Path(p).absolute().as_uri() + "?mode=ro", uri=True, timeout=5)`, followed by `PRAGMA query_only=1`. Never call `na_store.connect`: it runs DDL and sets WAL.
- **Report: isolation.** The section never raises and never changes the report's exit status. Every line it emits starts with two spaces.
- **Stale rule (Claude's call).** An enabled source is stale when `now − MAX(polls.finished_at WHERE ok = 1) > 3 × interval_s + 600 s`, or when it has no OK poll at all.
  - Only liveness counts, not new items. Spec §5.1 defines staleness by the last OK poll, and `sources` carries no expected item rate.
  - Some sources are legitimately quiet for weeks. On 2026-11-04, `okx_delistings`' newest item was dated 2026-09-23 and `rss_fed`'s 2026-10-29.
  - So `rss_blockworks`, which polls OK but whose newest item is from 2026-01-07, reports OK. Whether to replace or disable that feed is a #229 decision, not a report rule.
- **Disabled sources.** A source is disabled when `sources.enabled = 0`, written at service start. It is never stale and is listed by name in the summary line.
- **Recovery verdict (Claude's call).** Only `overflow` gaps carry one: Part A writes `detail` = `recovered` or `unrecovered`.
  - For list feeds, any loss across an outage, restart or suspension shows up as an `overflow` gap on the next OK poll. So other reasons are listed without a verdict.
  - "Unrecovered 7 d" counts `overflow` gaps with `detail = 'unrecovered'` and `gap_end ≥ now − 7 d`.
  - Non-list feeds (`fear_greed`, `ff_calendar`, `hyperliquid_universe`) have no loss detector. This is a documented limitation.
- **Backup job: who runs it (Claude's call).** Root's crontab runs it at `30 4 * * *` UTC, after the 03:15 live run and the 03:45 interim copy, from the root-owned path `/etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_news_archive.py`. Never through the `ubuntu`-controlled `runtime` symlink.
  - Why root: it reuses the already-working `operator-drive` remote. That avoids a second OAuth and avoids copying a token.
- **Backup job: locations.**
  - Destination: `/home/ubuntu/backups/news-archive/`. The directory is mode 0755, each run directory 0700, and `STATUS.json` 0644, so the `ubuntu` report can read it.
  - Remote: `operator-drive:Master-Trader/news-archive`.
  - Both are disjoint from the live job's `/home/ubuntu/backups/master-trader` and `operator-drive:Master-Trader/backups`, which live `prune()` and the 03:45 copy walk.
- **Retention:** `runs_to_prune(stamps, now, keep_days=7, keep_weeks=8, min_keep=7)`, applied locally and remotely.
  - Local retention runs after **every** successful snapshot, whatever the upload result. That differs from the live job on purpose: a failing upload cannot grow the disk without bound, and the 7-newest floor still keeps restore points.
- **Free space.** Before any snapshot or drill, `shutil.disk_usage(dest).free ≥ 15 × 1024³ + 2 × (size(archive.sqlite) + size(archive.sqlite-wal))`. Otherwise the run is `skipped` and exits 1, and nothing but `STATUS.json` is written.
- **Lock.** Runs and drills take a non-blocking `fcntl.flock` on `DEST/.lock`, separate from the live job's lock. If it is held: print `SKIP`, exit 0, leave `STATUS.json` untouched.
- **Priority.** At start the job calls `os.nice(10)`, then `ionice -c3 -p <pid>` as a best effort.
- **Off-host is opt-in and gated.**
  - Uploads only run with `--upload`.
  - The off-host copy counts only once the latest **remote** restore drill has passed. Until then the report line starts `news-archive backup: local only`.
- **No immediate alert from the archive job (Claude's call).** The nightly report is its channel, which meets spec goal 2: visible within a day.
- **Release** by cherry-pick onto `vps-deploy`. Never merge `main` into it. `ft_userdata/user_data/strategies/KillersScalpV1.py` (#183, on hold per #188) must not change on `vps-deploy`.

## Review Focus

1. **Root writes `STATUS.json`, and the `ubuntu` report reads it.**
   - The live job's `umask 077` pattern would make the file unreadable to the report.
   - The job must chmod the file 0644. If it is unreadable anyway, the report must say so in one line and not crash.
   - Pinned in Task 2 (`test_status_is_world_readable_and_runs_are_private`) and Task 4 (`test_unreadable_status_is_one_line`).
2. **The archive DB deleted or moved after install.** This must not read as a benign `not installed`. If `STATUS.json` exists but the DB does not, the report prints `news-archive: DATABASE MISSING at <path>`. Pinned in Task 4 (`test_missing_db_with_backups_is_loud`).
3. **The unit gave up after 5 failed starts.** Every source is then stale, and none has a recent failed poll.
   - This gives one collapsed line, not 14.
   - A stale source with no failed poll since its last OK says so.
   - Pinned in Task 1 (`test_all_sources_stale_collapse_to_one_line`, `test_one_stale_source_line`).
4. **The report reads while the service writes.** Rows that are still only in the WAL must be counted, and the report must never write. Pinned in Task 1 (`test_reads_wal_rows_and_never_writes`).
5. **A large uncheckpointed WAL,** for example while a long reader blocks checkpoints, makes the snapshot bigger than `archive.sqlite` alone. The free-space rule counts the `-wal` file too. Pinned in Task 2 (`test_free_space_rule_counts_the_wal`).

---

### Task 1: Report section — archive freshness and gaps

**Files:**
- Create: `ft_userdata/news_archive_report.py`
- Test: `tests/test_health_report_news_archive.py`. The header puts `ft_userdata` and `research/news_archive` on `sys.path`, then imports `news_archive_report as nar` and `na_store`.

**Interfaces:**
- Produces:
  - `DEFAULT_DB: str`, the path from Global Constraints.
  - `connect_ro(path: str) -> sqlite3.Connection`.
  - `fmt_age(seconds: float) -> str`, with the same buckets as Part A's `_age`:
    - under 120 s: `"%d s"`;
    - under 7,200 s: `"%.0f min"`;
    - under 172,800 s: `"%.1f h"`;
    - otherwise: `"%.1f d"`.
  - `archive_lines(db_path: str, now: datetime) -> list[str]`, which never raises. The output is exact; every line is prefixed with two spaces:

  | when | line |
  |---|---|
  | the DB file does not exist | `news-archive: not installed` (the only line) |
  | any exception while reading (e.g. `sqlite3.DatabaseError`) | `news-archive: database unreadable ({ExcName}: {msg})` (the only line) |
  | always | `news-archive: {ok}/{n} enabled sources OK[, {k} STALE][, {d} disabled ({names, comma-separated})]; {items} items in 24 h` |
  | 0 < k < n, per stale source, sorted by name | `STALE {src}: last OK {age} ago (limit {fmt_age(3*interval+600)})`, then either `; last error {age} ago: {error[:120]}` when a failed poll is newer than the last OK, or `; no failed poll since (service not polling?)`. A source with no OK poll shows `last OK never`. |
  | k == n > 0 | `ALL {n} enabled sources STALE: newest OK poll {age} ago (service down?)`, with no per-source lines |
  | always | `open gaps: none`, or `open gaps: {n} ({reason} {count}, …); oldest {age}: {src} {reason}`, with reasons sorted |
  | always | `gaps closed 24 h: none`, or `gaps closed 24 h: {n} — {part}; {part}`, with parts sorted by reason |
  | always | `unrecovered 7 d: none`, or `unrecovered 7 d: {src} {count}, …`, sorted by count descending, then name |

  - **Closed gaps:** rows with `gap_end ≥ now − 24 h`. They form parts:
    - the `overflow` part is `overflow {n} ({src} {count} {detail}, …)`, sorted by source, then detail;
    - any other reason is `{reason} {n} ({src}[×{count}], …)` when it covers at most 4 distinct sources, else `{reason} {n} ({m} sources)`.
  - **`{items}`** counts rows in `items` with `received_at ≥ now − 24 h`, across all sources.

- [ ] **Step 1: Write the failing tests.** `NOW = datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)`. A helper `_archive(tmp_path, ...)` builds the database with `na_store` and returns its path.

```python
def test_missing_db_is_not_installed(tmp_path):      # == ["  news-archive: not installed"]
def test_all_fresh_is_one_summary_line(tmp_path):
    # tree(60) and rss_coindesk(300): OK polls finished 1 min ago; upbit(120) enabled=0 with one failed poll; 5 items at NOW-1h
    # == ["  news-archive: 2/2 enabled sources OK, 1 disabled (upbit); 5 items in 24 h",
    #     "  open gaps: none", "  gaps closed 24 h: none", "  unrecovered 7 d: none"]
def test_one_stale_source_line(tmp_path):
    # tree: last OK finished NOW-2h, failed poll NOW-5min with error "PollError: HTTP 503"; rss_coindesk fresh
    # lines[0] == "  news-archive: 1/2 enabled sources OK, 1 STALE; 0 items in 24 h"
    # lines[1] == "  STALE tree: last OK 2.0 h ago (limit 13 min); last error 5 min ago: PollError: HTTP 503"
    # same setup without the failed poll -> "  STALE tree: last OK 2.0 h ago (limit 13 min); no failed poll since (service not polling?)"
def test_quiet_feed_that_polls_ok_is_not_stale(tmp_path):
    # rss_blockworks(300): OK 3 min ago, its only item published 300 d ago -> "1/1 enabled sources OK", no "STALE"
def test_disabled_source_is_never_stale(tmp_path):     # upbit enabled=0, never OK -> no line contains "STALE upbit"
def test_all_sources_stale_collapse_to_one_line(tmp_path):
    # both enabled sources last OK NOW-6h -> "  ALL 2 enabled sources STALE: newest OK poll 6.0 h ago (service down?)"
    # and no line starts with "  STALE "
def test_open_gaps_shown_even_when_fresh(tmp_path):
    # open suspended: binance_listing NOW-3h, binance_delisting NOW-1h; open clock: tree NOW-10min; all sources fresh
    # contains "  open gaps: 3 (clock 1, suspended 2); oldest 3.0 h: binance_listing suspended"
def test_closed_gaps_24h_and_unrecovered_7d(tmp_path):
    # restart closed NOW-1h on 5 sources; overflow tree "unrecovered" closed NOW-2h; overflow rss_decrypt "recovered" NOW-3h;
    # overflow tree "unrecovered" closed NOW-3d and NOW-8d
    # contains "  gaps closed 24 h: 7 — overflow 2 (rss_decrypt 1 recovered, tree 1 unrecovered); restart 5 (5 sources)"
    # contains "  unrecovered 7 d: tree 2"
def test_corrupt_db_is_one_line(tmp_path):
    # file of b"not a database" * 100 -> == ["  news-archive: database unreadable (DatabaseError: file is not a database)"]
def test_reads_wal_rows_and_never_writes(tmp_path):
    # writer: na_store.connect + PRAGMA wal_autocheckpoint=0, 3 items at NOW-1h left only in the WAL, connection open
    # "3 items in 24 h" in lines[0]; archive.sqlite bytes identical before and after;
    # nar.connect_ro(path).execute("INSERT INTO sources VALUES ('x',1,1,'t')") raises sqlite3.OperationalError
```

- [ ] **Step 2:** Run `python -m pytest tests/test_health_report_news_archive.py -q`. Expected: FAIL (`ModuleNotFoundError: news_archive_report`).
- [ ] **Step 3:** Implement `news_archive_report.py`. Compare timestamps as ISO strings, since Part A stores one canonical format, and parse with `datetime.fromisoformat` only to compute ages. Wrap the whole body of `archive_lines` in one `try`.
- [ ] **Step 4:** Run the same command. Expected: 10 passed.
- [ ] **Step 5:** Commit with `git add ft_userdata/news_archive_report.py tests/test_health_report_news_archive.py`, then `git commit -m "news-archive: report section for freshness and gaps (#229)"`.

### Task 2: Archive backup job — local leg

**Files:**
- Create: `deploy/vps/backup_news_archive.py` and `docs/ops/news-archive-backup.md`
- Test: `tests/test_backup_news_archive.py`. It puts `deploy/vps` and `research/news_archive` on `sys.path` and imports `backup_news_archive as bna`, `backup_live_dbs as live` and `na_store`. At import it saves `REAL_LOWER_PRIORITY = bna.lower_priority`. An autouse fixture patches `bna.lower_priority` to a no-op, because a real `os.nice(10)` would renice the pytest process for the rest of the run.

**Interfaces:**
- Consumes, from `backup_live_dbs`: `BackupError`, `STAMP_FORMAT`, `backup_sqlite(src, dst)`, `runs_to_prune(stamps, now, keep_days, keep_weeks, min_keep)`, `_sha256(path) -> str`, `_gzip(path) -> Path`.
- Produces:
  - **Constants:** `ARCHIVE_DB`, `DEST` and `DRIVE_REMOTE`, with the paths from Global Constraints; `RETENTION = {"keep_days": 7, "keep_weeks": 8, "min_keep": 7}`; `RESERVE_BYTES = 15 * 1024**3`.
  - **`required_free_bytes(db: Path) -> int`:** raises `BackupError` if `db` is missing.
  - **`snapshot(db: Path, dest: Path, now: dt.datetime) -> Path`:** writes `<dest>/<stamp>/archive.sqlite.gz` and `MANIFEST.json`.
    - The manifest is `{"created_utc", "source", "bytes", "sha256", "integrity_check": "ok", "row_counts": {table: n}, "stored_as": "archive.sqlite.gz"}`, where `row_counts` comes from the copy, every non-`sqlite_` table.
    - The run is staged in `.partial-<stamp>`, which is removed on any failure.
  - **`prune_local(dest: Path, now: dt.datetime) -> list[str]`:** applies `RETENTION` and also removes `.partial-*`.
  - **`read_status(dest: Path) -> dict` and `write_status(dest: Path, status: dict) -> None`:** the write goes to a temp file in `dest`, then `os.replace`, then mode 0644.
  - **`STATUS.json` keys,** which Tasks 3 and 4 rely on. An absent key reads as `None`.

    | key | value |
    |---|---|
    | `last_run_at` | ISO UTC |
    | `last_run_result` | `"ok"`, `"failed"` (the local snapshot failed), `"skipped"` (free space) or `"upload_failed"` |
    | `last_run_error` | str or `None` |
    | `latest_snapshot` | the newest complete local stamp after the run, or `None` |
    | `upload` | `{"at", "ok", "error", "stamp"}` or `None` (Task 3) |
    | `local_drill`, `offhost_drill` | `{"at", "stamp", "ok", "error"}` or `None` (Task 3) |

  - **`lower_priority() -> None`:** `os.nice(10)`, then `subprocess.run(["ionice", "-c3", "-p", str(os.getpid())], check=False)`, ignoring `OSError`.
  - **`main(argv: list[str] | None = None) -> int`:**
    - Flags: `--db` and `--dest`.
    - Order: `os.umask(0o077)` → `mkdir` `DEST` and chmod it 0755 → lock → `lower_priority()` → free-space check → `snapshot` → `prune_local` → `write_status` in a `finally`.
    - Exit codes: 0 for OK or a held lock; 1 for `failed` or `skipped`.
    - Output: stdout gets `<iso> OK <run> (pruned local=N)` or `<iso> SKIP: another run holds the lock`; stderr gets `<iso> news-archive backup FAILED: <err>` or `SKIPPED: <err>`.

- [ ] **Step 1: Write the failing tests.** The `archive_db` fixture builds a database with `na_store.connect` and `PRAGMA wal_autocheckpoint=0`, holding 1 source and 3 items that exist only in the WAL, with the writer left open.

```python
def test_snapshot_is_consistent_while_the_service_writes(archive_db, tmp_path):
    # main(["--db", db, "--dest", dest]) == 0; exactly one run dir; MANIFEST row_counts["items"] == 3
    # sha256(gunzip(archive.sqlite.gz)) == MANIFEST sha256; restored copy: journal_mode "delete", integrity_check "ok"
    # STATUS: last_run_result "ok", latest_snapshot == run.name, last_run_error None
def test_free_space_rule_counts_the_wal(archive_db, tmp_path, monkeypatch):
    # bna.required_free_bytes(db) == 15*1024**3 + 2*(size(db) + size(db-wal)), with size(db-wal) > 0
    # disk_usage free = required-1 -> main == 1, no run dir, STATUS "skipped", "free" in last_run_error
    # free = required -> main == 0
def test_held_lock_skips_and_leaves_status_alone(archive_db, tmp_path):   # flock held -> 0, no run dir, no STATUS.json
def test_failed_run_leaves_no_staging_and_records_failure(tmp_path):    # corrupt db -> 1, no ".partial-*", STATUS "failed"
def test_retention_keeps_7_daily_and_8_weekly(tmp_path):
    # 70 daily run dirs stamped 04:30 plus "not-a-run"; prune_local(dest, now)
    # every run of the last 7 days kept; older kept runs fall in distinct ISO weeks, none older than 8 weeks;
    # len(kept runs) <= 17; "not-a-run" kept
def test_status_is_world_readable_and_runs_are_private(archive_db, tmp_path):
    # after main: STATUS.json mode 0o644, run dir 0o700, dest 0o755
def test_archive_failure_leaves_live_backup_untouched(archive_db, tmp_path):
    # live layout: volumes/proj_ft_user_data/_data/tradesv3.live.X.sqlite, volumes/proj_killers_receiver_state/_data/r.sqlite
    # archive main on a corrupt db -> 1; then live.main([... "--no-upload", "--no-alert"]) -> 0 with 2 files,
    # and no "archive.sqlite.gz" anywhere under the live dest
    # with the live dest's .lock flock held, archive main on archive_db -> 0 (separate locks)
def test_destinations_are_disjoint_from_the_live_backup():
    # neither DEST is_relative_to the other; DRIVE_REMOTEs differ and neither starts with the other + "/"
def test_lowers_cpu_and_io_priority(archive_db, tmp_path, monkeypatch):
    # with os.nice and subprocess.run patched to recorders: REAL_LOWER_PRIORITY() -> nice(10),
    # ["ionice","-c3","-p",str(os.getpid())]; and main(["--db", db, "--dest", dest]) calls bna.lower_priority exactly once
def test_script_is_stdlib_only():   # AST imports ⊆ sys.stdlib_module_names ∪ {"__future__", "backup_live_dbs"}
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backup_news_archive.py -q`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implement `backup_news_archive.py`. Write `docs/ops/news-archive-backup.md` with three sections:
  - **Contract:** what is copied, where, the retention, the free-space rule, the lock, the priority and the `STATUS.json` keys.
  - **Install (local leg, operator go-ahead):** `sudo install -d -o root -g root -m 0755 /home/ubuntu/backups/news-archive`, then a first manual run, then the root crontab line `30 4 * * * /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_news_archive.py >> /var/log/master-trader-news-archive-backup.log 2>&1`.
  - **Rollback:** restore the saved root crontab. The snapshots stay.

  End the doc with an install-log table.
- [ ] **Step 4:** Run the same command. Expected: 10 passed.
- [ ] **Step 5:** Commit with `git add deploy/vps/backup_news_archive.py docs/ops/news-archive-backup.md tests/test_backup_news_archive.py`, then `git commit -m "news-archive: separate archive backup job, local leg (#229)"`.

### Task 3: Off-host leg and restore drill

**Files:**
- Modify: `deploy/vps/backup_news_archive.py`, `docs/ops/news-archive-backup.md`
- Test: `tests/test_backup_news_archive.py`

**Interfaces:**
- Consumes: Task 2, plus `backup_live_dbs.RCLONE_CONFIG`, `resolve_rclone(requested) -> Path` and `_remote_child(remote, name) -> str`.
- Produces:
  - **`upload(run: Path, remote: str, config: Path, rclone: Path, now: dt.datetime, runner=subprocess.run) -> list[str]`:**
    - Fails with `BackupError` when the config or the binary is missing.
    - Runs `copy … --checksum --immutable`, then `check … --one-way --download`, then `lsjson <remote> --dirs-only --max-depth 1`, then `purge` on every stamp outside `RETENTION`.
    - An invalid listing raises `BackupError("invalid rclone directory listing…")` and nothing is purged.
  - **`drill(source: str, dest: Path, db: Path, remote: str, config: Path, rclone: Path | None, runner=subprocess.run) -> str`:**
    - Picks the newest stamp: from the local directory listing for `"local"`, from `lsjson` for `"remote"`.
    - Applies the Task 2 free-space rule, then restores into `tempfile.TemporaryDirectory(prefix="news-archive-drill-")`. A remote drill fetches with `rclone copy <remote>/<stamp> <tmp>/<stamp>`.
    - Gunzips the copy, then requires the sha256 to match the manifest, `integrity_check` to return `ok`, and the row counts to equal `row_counts`.
    - Returns the stamp. On any failure it raises `BackupError` naming the check that failed: `sha256`, `integrity_check` or `row count`.
  - **CLI:**
    - Flags: `--upload`, `--drive-remote` (default `DRIVE_REMOTE`), `--rclone`, `--rclone-config` (default `RCLONE_CONFIG`) and `--drill {local,remote}`.
    - A drill holds the same lock and writes only `local_drill` or `offhost_drill`.
    - A failed upload sets `upload.ok = False`, `last_run_result = "upload_failed"` and exit 1. The new snapshot and the local retention stay.
    - `main` calls `subprocess.run` through the module attribute, so tests can patch `bna.subprocess.run`.

- [ ] **Step 1: Write the failing tests**

```python
def test_upload_verifies_before_pruning_with_archive_retention(tmp_path):
    # now 2026-11-05 04:30Z; the fake runner's lsjson lists daily stamps d=0..7, plus d=9, d=20, d=70, and "README"
    # pruned == [stamp(d=70), stamp(d=9)]; verbs == ["copy","check","lsjson","purge","purge"]
    # copy argv ends ["--checksum","--immutable"]; check argv ends ["--one-way","--download"]
def test_listing_failure_never_purges(tmp_path):        # lsjson stdout "not json" -> BackupError; verbs == ["copy","check","lsjson"]
def test_failed_upload_is_recorded_and_keeps_the_snapshot(archive_db, tmp_path, monkeypatch):
    # bna.upload raises BackupError("Drive unavailable"); main([..., "--upload"]) == 1; the run dir exists
    # STATUS: upload.ok False, "Drive unavailable" in upload.error, last_run_result "upload_failed", latest_snapshot == run
def test_local_drill_passes_and_is_recorded(archive_db, tmp_path):
    # after one run: main([..., "--drill", "local"]) == 0; local_drill.ok True, stamp == latest_snapshot
def test_drill_rejects_a_tampered_snapshot(archive_db, tmp_path):
    # replace archive.sqlite.gz with a gzip of a db holding one more item -> 1; local_drill.ok False, "sha256" in error
def test_drill_rejects_a_row_count_mismatch(archive_db, tmp_path):
    # MANIFEST row_counts["items"] += 1 -> 1; "row count" in local_drill.error
def test_remote_drill_sets_the_offhost_gate(archive_db, tmp_path, monkeypatch):
    # bna.subprocess.run patched: lsjson -> [{"Name": stamp, "IsDir": True}]; copy <remote>/<stamp> <dir> copies from a local
    # stand-in remote dir; main([..., "--drill", "remote", "--rclone", f, "--rclone-config", c]) == 0; offhost_drill.ok True
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backup_news_archive.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the code. Then add two sections to the runbook:
  - **Off-host leg:** a separate operator go-ahead, the gate rule, the cron line with `--upload`, and the failed-upload demonstration in Task 6 step 13.
  - **Restore drill:** `--drill local` and `--drill remote`.
- [ ] **Step 4:** Run the same command. Expected: 17 passed.
- [ ] **Step 5:** Commit: `git commit -am "news-archive: verified off-host upload and restore drill (#229)"`.

### Task 4: Backup state in the report, wired into the health report

**Files:**
- Modify:
  - `ft_userdata/news_archive_report.py`;
  - `ft_userdata/strategy_health_report.py`: `format_telegram_report`, a new `news_archive_section`, and `main` after `check_preregistrations`;
  - `deploy/vps/README.md`, the "Health report" and "Backups" paragraphs;
  - `research/news_archive/README.md`, a short "Monitoring and backup" section pointing to both.
- Test: `tests/test_health_report_news_archive.py`, which also imports `strategy_health_report as shr`.

**Interfaces:**
- Consumes: `archive_lines` and `fmt_age` (Task 1); the `STATUS.json` keys (Task 2).
- Produces:
  - **`DEFAULT_BACKUP_STATUS = "/home/ubuntu/backups/news-archive/STATUS.json"`.**
  - **`backup_line(status_path: str, now: datetime) -> str`.** It never raises. The format is `  news-archive backup: {offhost}; {snapshot}{extras}`:
    - `offhost` depends on the remote drill:
      - if `offhost_drill.ok`: `off-host OK (last upload {age} ago)` when `upload.ok`, or `off-host upload FAILED {age} ago: {error}` when the upload failed;
      - otherwise: `local only`, followed by `; off-host upload FAILED {age} ago: {error}` if an upload failed, and `; off-host drill FAILED: {error}` if a remote drill failed.
    - `snapshot` is `latest snapshot {age} ago ({stamp})`, or `no snapshot yet`.
    - `extras`:
      - `; last run FAILED {age} ago: {error}` for `failed`, or `; last run SKIPPED {age} ago: {error}` for `skipped`;
      - `; no run for {age}` when `last_run_at` is more than 26 h old.
    - A missing file gives `  news-archive backup: local only; no snapshot yet`.
    - An unreadable file gives `  news-archive backup: local only; status unreadable ({ExcName}: {msg})`.
  - **`news_archive_lines(db_path: str | None = None, status_path: str | None = None, now: datetime | None = None) -> list[str]`.**
    - It reads env `NEWS_ARCHIVE_DB` and `NEWS_ARCHIVE_BACKUP_STATUS` at call time.
    - It returns `archive_lines` plus `backup_line`.
    - If the DB is missing and no status file exists, it returns only `["  news-archive: not installed"]`.
    - If the DB is missing but the status file exists, it returns `["  news-archive: DATABASE MISSING at {path}", backup_line]`.
  - **`shr.news_archive_section() -> list[str]`.** It runs `from news_archive_report import news_archive_lines` and the call inside one `try`. Any `Exception` gives `["  news-archive: section failed: {ExcName}: {msg}"]`.
  - **`shr.format_telegram_report(bot_metrics, portfolio, trends, prereg_lines=None, news_lines=None)`** appends `""`, `"NEWS ARCHIVE"` and the lines as the message's last block. `main` passes `news_lines=news_archive_section()`; `--json` output is unchanged.

- [ ] **Step 1: Write the failing tests.** A helper `_status(tmp_path, **keys)` writes a `STATUS.json` whose keys default to `None`. The run stamp is `20261105T043000Z`, and `NOW` is 2026-11-05 23:00 UTC, so the snapshot is 18.5 h old.

```python
def test_backup_local_only_until_the_remote_drill(tmp_path):
    # == "  news-archive backup: local only; latest snapshot 18.5 h ago (20261105T043000Z)"
def test_failed_upload_shows_before_the_gate(tmp_path):
    # upload {"ok": False, "error": "Drive unavailable", "at": run time}; last_run_result "upload_failed"
    # == "  news-archive backup: local only; off-host upload FAILED 18.5 h ago: Drive unavailable; latest snapshot 18.5 h ago (20261105T043000Z)"
def test_offhost_counts_only_after_a_passing_remote_drill(tmp_path):
    # offhost_drill ok + upload ok   -> startswith "  news-archive backup: off-host OK (last upload 18.5 h ago); latest snapshot"
    # offhost_drill ok + upload fail -> "off-host upload FAILED" in line and "off-host OK" not in line
    # offhost_drill failed           -> startswith "  news-archive backup: local only" and "off-host drill FAILED" in line
def test_local_failure_skip_and_overdue_are_shown(tmp_path):
    # last_run_result "skipped", error "free 14.2 GiB < required 15.0 GiB", last_run_at NOW-30h
    # "; last run SKIPPED 30.0 h ago: free 14.2 GiB < required 15.0 GiB" in line and "; no run for 30.0 h" in line
def test_unreadable_status_is_one_line(tmp_path):
    # file "{not json" -> startswith "  news-archive backup: local only; status unreadable (JSONDecodeError"
def test_missing_db_with_backups_is_loud(tmp_path):
    # no db, STATUS exists -> lines[0] == f"  news-archive: DATABASE MISSING at {db}"; no line says "not installed"
def test_env_paths_are_read_at_call_time(tmp_path, monkeypatch):
    # set NEWS_ARCHIVE_DB / NEWS_ARCHIVE_BACKUP_STATUS after import -> news_archive_lines() reads those files
def test_section_failure_never_breaks_the_report(monkeypatch):
    # sys.modules["news_archive_report"] = a stub whose news_archive_lines raises RuntimeError("boom")
    #   -> shr.news_archive_section() == ["  news-archive: section failed: RuntimeError: boom"]
    # sys.modules["news_archive_report"] = None -> result[0].startswith("  news-archive: section failed: ImportError")
def test_report_ends_with_the_news_archive_block():
    # minimal portfolio dict (closed_pnl, open_pnl, true_pnl, total_trades, open_positions, bots_online, avg_health_score)
    # shr.format_telegram_report([], portfolio, {}, news_lines=["  news-archive: x"]).endswith("\n\nNEWS ARCHIVE\n  news-archive: x")
```

- [ ] **Step 2:** Run `python -m pytest tests/test_health_report_news_archive.py -q`. Expected: the 9 new tests FAIL.
- [ ] **Step 3:** Implement the code, then make the README edits listed under Files.
- [ ] **Step 4:** Run `python -m pytest tests/ -q`. Expected: the whole root suite passes, with no new skips. The baseline on `main` before this work was 771 passed and 28 skipped.
- [ ] **Step 5:** Commit: `git commit -am "news-archive: backup state in the nightly health report (#229)"`.

### Task 5: PR to `main` and review

Not a code task.

- [ ] **Step 1:** Open a PR to `main` titled `news-archive: Part B report section and archive backup (#229)`, with `Refs #229`.
  - The body records the behavior and the "Claude's call" lines from Global Constraints.
  - It records the test counts.
  - It records these limitations:
    - the off-host leg is not yet verified;
    - non-list feeds have no loss detector;
    - `rss_blockworks` reports OK.
- [ ] **Step 2:** Run a focused Codex review (Sol, high) of the diff, per `~/.claude/codex-usage.md`. Fix the valid findings. Squash-merge when authorized, and record the squash SHA as `<B>`.

### Task 6: Release to `vps-deploy`, install and verify (operator go-ahead required)

Not a code task. Two separate go-aheads apply: steps 1–12 (release, report and local backup) and step 13 (off-host). In the commands below, `C=/etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code` and `S=/home/ubuntu/master-trader/state`.

- [ ] **Step 1:** Confirm the operator's explicit go-ahead for the release and the local backup leg.
- [ ] **Step 2: Cut the release branch.** Run `git fetch origin`, `git switch -c claude/229-news-archive-part-b-vps origin/vps-deploy`, then `git cherry-pick -x 576c03a af66b43 beccbb0 980236a <B>`.
  - The earlier four #229 commits are included because Part B's tests build their fixtures with Part A's `na_store`.
  - Part A is research-only and inert in the Dokploy checkout.
  - A dry run of those four on 2026-11-04 applied cleanly: 719 passed, 28 skipped.
- [ ] **Step 3: Check the paths.** `git diff --name-only origin/vps-deploy HEAD` may list only:
  - `docs/research/2026-11-03-news-sentiment/**`;
  - `docs/superpowers/specs/2026-11-03-news-archive-design.md`;
  - `docs/superpowers/plans/2026-11-03-news-archive-part-a.md` and `docs/superpowers/plans/2026-11-04-news-archive-part-b.md`;
  - `docs/ops/news-archive-backup.md`;
  - `research/news_archive/**` and `tests/fixtures/news_archive/**`;
  - `tests/test_news_archive_*.py`, `tests/test_health_report_news_archive.py` and `tests/test_backup_news_archive.py`;
  - `ft_userdata/news_archive_report.py` and `ft_userdata/strategy_health_report.py`;
  - `deploy/vps/backup_news_archive.py` and `deploy/vps/README.md`.

  `git diff --quiet origin/vps-deploy HEAD -- ft_userdata/user_data services ft_userdata/docker-compose.prod.yml deploy/vps/backup_live_dbs.py` must exit 0.
- [ ] **Step 4:** Run `python -m pytest tests/ -q` on the release branch. Expected: all pass.
- [ ] **Step 5:** Open a release PR to `vps-deploy` titled `release: news-archive Part B for vps-deploy (#229)`. Its body lists the cherry-picks and the path check, and states that no container is recreated. Merge when authorized, and record the merge SHA as `<R>`.
- [ ] **Step 6: Pre-flight on the VPS.**
  - The Dokploy `autoDeploy` query (`SELECT "autoDeploy" FROM compose WHERE "composeId" = 'gajntEdheyjvJKEVuUbbe'`) returns `f`.
  - `sudo git -C $C status --short` shows only the known untracked `.env.before-tp-*`.
  - Record `HEAD` as `<prev>`.
- [ ] **Step 7: Roll out.** Run `sudo git -C $C fetch origin vps-deploy && sudo git -C $C merge --ff-only <R>`. Then check:
  - `git -C $C diff --name-only <prev> HEAD` equals the step 3 list;
  - `docker ps` uptimes are unchanged.
- [ ] **Step 8: Read-only section check.** This leaves the cron state untouched. Run `cd $C/ft_userdata && /usr/bin/python3 -c 'import news_archive_report as n; print("\n".join(n.news_archive_lines()))'`. Expected:
  - `news-archive: 14/14 enabled sources OK, 1 disabled (upbit); … items in 24 h`;
  - the gap lines;
  - `news-archive backup: local only; no snapshot yet`.
- [ ] **Step 9: Full report, as in the #219 deploy.**
  1. Back up the cron state: `cp -p $S/health_report_state.json $S/health_report_state.json.pre-229b`.
  2. Run `/home/ubuntu/master-trader/run-health-report.sh --stdout`.
  3. Check `tail -n 15 /home/ubuntu/master-trader/research/logs/health_report.log`. The wrapper appends there, so that is where the output lands. It must end with the `NEWS ARCHIVE` block and contain no traceback.
  4. Restore the cron state: `cp -p $S/health_report_state.json.pre-229b $S/health_report_state.json`.
- [ ] **Step 10: Local backup leg.**
  1. `sudo crontab -l > /home/ubuntu/backups/root-crontab.pre-229b`
  2. `sudo install -d -o root -g root -m 0755 /home/ubuntu/backups/news-archive`
  3. `sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py`. Expected: an `OK` line.
  4. `sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --drill local`. Expected: exit 0.
  5. Repeat step 8. Expected: `local only; latest snapshot … ago`.
- [ ] **Step 11: Install the cron line.** Run `( sudo crontab -l | grep -v 'deploy/vps/backup_news_archive.py'; echo '<Task 2 cron line>' ) | sudo crontab -`, then check it with `sudo crontab -l | grep backup_news_archive`.
- [ ] **Step 12: Record the deploy.**
  - On #229: `<B>`, `<R>`, the rollout diff, the outputs of steps 8–11 and the cron line.
  - After the next 23:00 report and the next 04:30 run, record the log lines on #229 as well. Then open a docs-only PR to `main` with the install log, as #233 did for Part A.
- [ ] **Step 13: Off-host leg, only after a separate go-ahead.**
  1. **Prove a failed upload is visible:** run `sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --upload --rclone-config /nonexistent`. It must exit 1, and step 8 must then show `local only; off-host upload FAILED …`.
  2. **Real upload:** the same command with `--upload` only gives `OK`. `sudo /usr/local/bin/rclone lsf operator-drive:Master-Trader/news-archive --dirs-only --config /etc/master-trader-backup/rclone.conf` must list the stamp.
  3. **Remote drill:** the same command with `--drill remote` exits 0, and step 8 must then show `off-host OK`.
  4. **Cron:** swap in the `--upload` variant of the cron line, the same way as step 11.
  5. Record 1–4 on #229.
- [ ] **Rollback:**
  - **Backup job:** `sudo crontab /home/ubuntu/backups/root-crontab.pre-229b`. The snapshots stay.
  - **Report:** a revert PR on `vps-deploy`, then a fast-forward of the checkout. The section is isolated, so no emergency path is needed.
