# News Archive Part C — Preregistered Event Studies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preregister three retrospective event studies. Build an outcome-blind event manifest and freeze its SHA-256 before any price is loaded. Then compute each study's mechanical verdict from that manifest alone.

**Architecture:** Eight stdlib modules in `research/news_event_studies/`, split by phase.

- **Phase 1, no prices:**
  - `nes_util.py` — paths, window constants, canonical JSON, disk guard;
  - `nes_harvest.py` — the full Binance CMS harvest (VPS, through Part A's shared limiter) and the Upbit harvest (operator's Mac);
  - `nes_classify.py` — pure title and body rules;
  - `nes_venues.py` — Hyperliquid evidence and Binance kline-file existence (HEAD only);
  - `nes_manifest.py` — events, exclusions, per-study status, the canonical manifest.
- **Phase 2:**
  - `nes_klines.py` — daily-zip download and row extraction;
  - `nes_returns.py` — pure returns, halts, leak flag, costs, aggregation, criteria and verdict;
  - `nes_report.py` — CLI, reports, the mechanical resolution.

All network access goes through `na_fetch.fetch` behind injectable fetchers, so every test is network-free.

**Tech Stack:** Python stdlib only (`json`, `zipfile`, `csv`, `decimal`, `statistics`, `random`, `hashlib`), plus Part A's `na_fetch`, `na_sources` and `na_store`. Python 3.12 on the VPS, 3.13 in CI. pytest.

**Spec:** [`docs/superpowers/specs/2026-11-03-news-archive-design.md`](../specs/2026-11-03-news-archive-design.md) at `980236a`: §6 as amended by PR #231, §9 row C, §10, and §11 calls 2–5, 9, 10 and 13. The spec wins on any conflict, except where the Task 1 PR amends it (call C1 below).

**Sequence:**

1. Task 1, the preregistration PR, merges before any Phase 1 code touches real data.
2. Tasks 2–9 are network-free code, shipped as two PRs: Phase 1 (Tasks 2–6) and Phase 2 (Tasks 7–9).
3. Task 10 runs Phase 1 and freezes the manifest SHA-256 by amendment.
4. Task 11 runs Phase 2, and only after that amendment merges.

## Global Constraints

- Stdlib only. No new dependency in any requirements file.
- **Imports:**
  - every module name starts with `nes_`;
  - tests `sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))`;
  - importing `nes_util` puts `research/news_archive` on `sys.path`, which makes `na_fetch`, `na_sources` and `na_store` importable.
- **Tests:**
  - they live in `tests/test_news_event_studies_*.py`, with fixtures in `tests/fixtures/news_event_studies/`;
  - fixtures are hand-written or trimmed public payloads, and kline fixtures are hand-computed;
  - no network access.
  - Runner: `PY=/Users/palmer/Work/Groove/Finance/Trading/master-trader/.worktrees/178-widget-metrics/.venv/bin/python`, then `$PY -m pytest tests/ -q`.
- `research/news_event_studies/.gitignore` holds one line, `data/`. Raw pages, manifests, klines and results live only on the VPS, in `/home/ubuntu/master-trader/research/news_event_studies/data/`.
- **Times:** internally, integer epoch milliseconds. Stored ISO strings use `na_store.iso` / `iso_from_epoch`: UTC with microseconds.
- **Window:** `1672531200000 <= t0_ms < 1793491200000`, i.e. 2023-01-01T00:00Z up to and including 2026-10-31T23:59:59.999Z.
- **Binance CMS:**
  - only through `na_fetch.BinanceLimiter` on the archive's own state file, `/home/ubuntu/master-trader/research/news_archive/data/binance_cms_state.json`;
  - the harvester also keeps 540 s between its own requests;
  - single attempt; `na_fetch.is_block_signal` → `limiter.suspend()`;
  - a second suspension during the harvest, or 72 h without completing, aborts it.
- **Upbit:**
  - only from the operator's Mac, because Cloudflare answers the VPS IP with 403;
  - at least 10 s between requests, with no automatic retry;
  - a block signal stops the run.
- **Hyperliquid** `info` from the VPS: at most 1 request per 20 s, about 60 weight/min of the 1,200/min per-IP budget that the live `hl-gateway` shares. HTTP 429 → one 600 s pause; a second 429 aborts.
- **`data.binance.vision`:**
  - Phase 1 sends HEAD requests only;
  - Phase 2 GETs zips only for the frozen proxy series and for BTCUSDT;
  - at most 2 requests/s;
  - each zip is deleted after its rows are extracted.
- **VPS jobs:**
  - run as transient user units with `MemoryMax=1G`, `CPUQuota=50%`, `Nice=10` and `IOSchedulingClass=idle`;
  - every download batch first needs ≥ 15 GiB free (`15 * 1024**3`).
- **Blindness:**
  - until Task 10's amendment merges, nothing reads a price for any `t0` in the window;
  - nothing under VPS `research/news_exploratory_2026-11/` is read, imported or copied, and its 2018–2022 numbers set no parameter.
- **`ft_userdata/preregistrations.json` is append-only:**
  - existing entries stay byte-identical, `listing-reaction-study-2026-07` and `listing-short-forward-2026-07` above all;
  - the file is hand-formatted, so edit it as text and never re-dump it with `json.dump`.
- Nothing here touches `research/listing_short_forward/`, `/etc/dokploy`, any container, bot config or allocation.

## Review Focus

1. **Pagination shift during a multi-hour harvest.** A notice published mid-harvest must not count as a shortfall, and a short harvest must. Pinned in Task 2: `test_new_article_mid_harvest_is_not_a_shortfall` and `test_short_harvest_is_a_shortfall`.
2. **A transient HTTP error** (5xx, timeout) during existence or eligibility checks must abort the build, never be read as "absent". Otherwise events would silently become `not_on_binance` or `ineligible`. Pinned in Task 5: `test_transient_error_is_not_absence` and `test_hl_429_pauses_once_then_aborts`.
3. **Exact boundaries:**
   - leak drift of exactly 2.00% (in floats, `102/100 - 1 > 0.02` is `True`);
   - overlap of exactly 24 h;
   - resumption at exactly 72 h;
   - `t0` at the window end.
   Pinned in Task 6 (`test_overlap_keeps_first_and_measures_from_last_kept`, `test_window_end_exclusive`) and Task 8 (`test_leak_strictly_above_two_percent`, `test_halt_exit_first_candle_within_72h`).
4. **A harvester on a limiter file other than the archive's** would double the Binance budget. Pinned in Task 2: `test_refuses_when_archive_limiter_dir_missing`.
5. **Ticker mismatches** (renames, `1000`/`1M` prefixes, Hyperliquid's `k` prefix, Upbit vs Binance tickers) must show in the build report, not vanish as exclusions. Pinned in Task 6: `test_build_report_lists_unmatched_tokens`.

## Calls made in this plan (operator to check)

The full rule text is the O1–O17 list in Task 1. These are the calls worth checking:

- **C1 (blocks Task 1): Hyperliquid eligibility evidence.**
  - **The problem:** spec §6.2 requires Hyperliquid *candles* in [t0−24 h, t0). `candleSnapshot` serves only the most recent ~5,000 candles (`docs/hyperliquid_short_validation_2026-05-29.md`). At 1 h that reaches back to about 2026-04-09. Verbatim, nearly every event before then is `unknown`, and C2 sends all three studies to INCONCLUSIVE-by-data on the coverage gate.
  - **Option A (recommended if Task 1's probe confirms):** hourly funding records via `fundingHistory`, with the same 24 h / 1 h rule, through a spec amendment in the Task 1 PR.
  - **Option B:** keep the rule verbatim.
- **C2: `unknown` Hyperliquid status.** It excludes the event from all three studies. The long does not fall back to Binance spot (spec: "Unknown events are excluded and counted").
- **C3: the Upbit "trading began before the notice" rule** reads the start time from the notice body, fetched from the detail endpoint that Task 1's probe verifies. A body with no parseable time makes the event `unknown`. "Already on Upbit KRW" is decided by replaying the harvested addition and end notices (O9).
- **C4: Binance classification uses titles only.**
  - The list endpoint returns no body, and ~446 detail fetches would take at least 22 h of the shared limiter.
  - Classification from current CMS versions is a recorded limitation.
  - An in-window title that matches no rule stops the build until a rule and a fixture are added. This is outcome-blind: titles carry no prices.
- **C5: the harvester's share of the limiter.**
  - The running archive already uses every slot: two catalogs, each due every 360 s.
  - So the harvester takes at most one slot in three (its own gap is 540 s). That keeps the archive's Binance polls under its 720 s outage threshold.
  - Catalogs 161 + 48 take ≈ 9 h, plus the C6 scan. The spec's "≈ 3 h" assumed the whole budget.
  - The 2026-07 cached catalog-48 pages are not reused: count = total needs one consistent harvest.
- **C6: monitoring tags elsewhere.** Catalog 49 (Latest Binance News) is scanned back to 2023-01-01. Any monitoring-tag title found there stops Phase 1 for an operator decision, because the spec would then require a full harvest of 49.
- **C7: exit-candle gaps are never `missing`.** The halt rule makes them `halted` or `unresolved`. An event unresolved at any horizon is unresolved, so the study is INCONCLUSIVE.
- **C8: coverage-gate denominator.** Token-events not excluded by a verified rule, plus the harvest shortfall.
- **C9: prices.** Every price is the close of the 1m candle containing the instant (O2). The leak test uses exact decimals.
- **C10: proxy and Binance presence.** The proxy is USDⓈ-M futures when its daily files exist for every date from date(t0−1 d) to date(t0+2 d), else spot. "Trading on Binance" means a file for the UTC day before t0's date.
- **C11: catalog-48 overlap.** Any catalog-48 title naming the token within ±24 h, inclusive.
- **C12: transient units, not `systemd-run --scope`.** VPS jobs run as transient user units with the §6.2 limits, because a scope dies with the SSH session.

---

### Task 1: Preregistration PR

**Files:**
- Modify: `ft_userdata/preregistrations.json`. Append three entries after the last one (`killers-entry-policy-replay-2026-10-13`), formatted like it: 2-space indent, keys at 6 spaces, `ensure_ascii=False`.
- Modify, under C1 option A only: `docs/superpowers/specs/2026-11-03-news-archive-design.md`, the §6.2 eligibility bullet plus a new §11 call 14.
- Test: `tests/test_news_event_studies_prereg.py`
- Branch: `claude/229-part-c-prereg`.

**Interfaces:**
- Produces: three entries, each with:
  - a `frozen` dict, which Tasks 5, 8 and 9 test their constants against;
  - an `operationalization` list O1–O17, which later tasks implement.

- [ ] **Step 1: Feasibility probes.**
  - Read-only. No study event is looked up. Print counts and timestamps only, never a price.
  - **VPS:** four `POST https://api.hyperliquid.xyz/info` requests, 20 s apart:
    - (a) `{"type":"meta"}` → the number of universe entries with `isDelisted: true`, and the first such name alphabetically, `D`;
    - (b) `candleSnapshot` for `BTC`, interval `1h`, from 1672531200000 to now → the earliest `t`;
    - (c) `fundingHistory` for `BTC` from 1672531200000 → the earliest `time`;
    - (d) the same for `D` → record count, earliest and latest `time`.
  - **Mac:** one `GET https://api-manager.upbit.com/api/v1/announcements/6714` with `na_sources.JSON_HEADERS`. Record `success`, the key names under `data`, and the body line containing `거래지원 개시` or `거래 지원 개시`. If the response is not JSON with a body text, retry once 10 s later with `?os=web` appended.
  - Post all results on #229.
  - Expected:
    - (a) > 0;
    - (b) ≈ 2026-04-09;
    - (c) a 2023 date, Hyperliquid's BTC perp launch, not a retention floor like (b);
    - (d) > 0 records;
    - Upbit: a body key and a start line.
- [ ] **Step 2: Operator decision on C1, recorded on #229.**
  - If (b) already reaches 2023-01-01, use option B and skip the spec edit.
  - If (c) is later than 2023-12-31, or (d) returns no records, option A is unavailable; say so.
  - If neither Upbit form returns a body, stop: O10 needs another evidence source, and the operator picks it before this PR opens.
  - **Option A edits:**
    - Replace the first two sentences of the §6.2 bullet "Hyperliquid eligibility needs positive pre-entry evidence" with:
      > A token qualifies only if Hyperliquid hourly funding records (`fundingHistory`, by coin name) exist for it in the 24 h before t0, including at least one in the last hour before t0. Candles cannot serve: `candleSnapshot` returns only the most recent ~5,000 candles, which at 1 h reach back to about 2026-04 (probe on #229).
    - Replace "looked up by name through `candleSnapshot`" with "looked up by name through `fundingHistory`".
    - Add §11 call 14 recording the change and the probe result.
- [ ] **Step 3: Write the failing tests**

```python
IDS = ("binance-delisting-reaction-2026-11", "upbit-krw-listing-reaction-2026-11",
       "upbit-krw-listing-fade-2026-11")
COMMON = {  # identical in all three entries' "frozen"
    "window_utc": ["2023-01-01T00:00:00Z", "2026-11-01T00:00:00Z"],   # end exclusive
    "unit": "announcement", "entry_offset_s": 300, "descriptive_entry_offset_s": 60,
    "horizons_s": [1800, 14400, 86400], "primary_horizon_s": 14400,
    "fee_bps_per_side": {"hyperliquid": 4.5, "binance_spot": 7.5},
    "slippage_bps_per_side": 10, "stress_slippage_bps_per_side": 25,
    "leak_window_s": [-600, -120], "leak_abs_drift_gt": "0.02",
    "halt_resume_window_s": 259200, "min_announcements": 20,
    "top_decile_share_lt": 0.6, "coverage_gate_gt": 0.2,
    "bootstrap_resamples": 10000, "bootstrap_seed": 229,
    "hl_eligibility_window_s": [86400, 3600],
    "proxy_preference": ["binance_um_futures", "binance_spot"],
    "proxy_dates_d": [-1, 2], "kline_download_dates_d": [-1, 5],
}
def test_entries_open_and_research_only():
    # each: status "open", bot None, issue "#229", review_by "2027-02-01", triggers == [],
    # amendments == [], resolution None, "allocation" in json.dumps(entry).lower()
def test_frozen_common_block():        # {k: e["frozen"][k] for k in COMMON} == COMMON, all three
def test_frozen_study_blocks():
    # delisting: direction "short", venues ["hyperliquid"], t0_field "binance_cms.releaseDate",
    #   event_catalogs [161], kinds ["full_delist", "monitoring_add"], same_token_overlap_s 86400,
    #   manifest "delisting-manifest.json"
    # long: direction "long", venues ["hyperliquid", "binance_spot"], t0_field "upbit.first_listed_at",
    #   binance48_overlap_s 86400, exclude_title_words ["종료","유의","제거","변경","중단","연기","재개"],
    #   manifest "upbit-manifest.json"
    # fade: the long's block except direction "short", venues ["hyperliquid"],
    #   plus shares_manifest_with "upbit-krw-listing-reaction-2026-11"
def test_hl_evidence_identical_and_known():  # one value in all three, in {"fundingHistory", "candleSnapshot_1h"}
def test_rules_verbatim_are_spec_text():
    # every string in rules_verbatim["phase1"] + rules_verbatim["phase2"] occurs in the spec
    # after removing "**" and collapsing whitespace in both
```

- [ ] **Step 4:** Run `$PY -m pytest tests/test_news_event_studies_prereg.py -q`. Expected: FAIL (`StopIteration`: the ids are absent).
- [ ] **Step 5: Append the three entries.** Keys in this order:
  - `id`, `bot: null`, `status: "open"`, `registered` (the merge date), `review_by: "2027-02-01"`, `issue: "#229"`;
  - `spec`: `"docs/superpowers/specs/2026-11-03-news-archive-design.md §6 @980236a"`, plus the C1-A commit if used;
  - `hypothesis`: the §6.1 table row's "why" cell, verbatim;
  - `frozen`: `COMMON` plus the study block from Step 3, plus `hl_evidence`;
  - `rules_verbatim`: `{"phase1": [...], "phase2": [...]}`. Copy every §6.2 bullet and sub-bullet as its own string, verbatim. The Upbit entries take the Upbit event bullets; the delisting entry takes the delisting ones. Each takes only its own venue line. The fade also gets the §6.1 "Why the fade was added" text, its bullets, and the two paragraphs that follow them;
  - `operationalization`: O1–O17 below, verbatim, each prefixed with its number;
  - `pass_criteria`: the four §6.2 "Pass" bullets, verbatim;
  - `kill` and `inconclusive`: the §6.2 "Kill" and "Too few announcements" bullets and §11 call 5, verbatim;
  - `rules`, exactly these three strings:
    - "Research only: no deploy, config, sizing or allocation change follows from any result; a PASS authorizes only a separately preregistered paper forward monitor."
    - "Phase 1 builds an outcome-blind manifest; its SHA-256 is recorded in an amendment merged before any return is computed."
    - "The 2018–2022 exploratory check (#229 comment 6617239337) is the hypothesis source only; it never counts as validation and sets no parameter."
  - `triggers: []`, `amendments: []`, `resolution: null`.

  The operationalization list (one string each):

  - **O1** t0: Binance `releaseDate` (ms); Upbit `first_listed_at` (KST→UTC). `listed_at` moves when a notice is edited (Part A: id 6687, 21:50 vs 20:00 KST).
  - **O2** price_at(X) = the close of the Binance 1m candle whose open is floor_minute(X).
    - Entry = price_at(t0+300 s); exit_H = price_at(t0+300 s+H).
    - Leak drift = price_at(t0−120 s) / price_at(t0−600 s) − 1, in exact decimals; leaked if |drift| > 0.02.
  - **O3** Gross long = exit/entry − 1; gross short = −(exit/entry − 1); net = gross − 2 × (fee + slippage) / 10,000.
  - **O4** Missing candles:
    - a missing exit candle → the close of the first candle opening in (scheduled, scheduled + 72 h] = `halted`; none → `unresolved`;
    - a missing leak or entry candle → `missing`;
    - an event unresolved at any horizon is `unresolved`.
  - **O5** Hyperliquid eligibility: `<hl_evidence>` by coin name, with candidates [T, "k"+T] and names containing ":" skipped. Queries cover [t0−24 h, t0−1 ms].
    - **eligible:** ≥ 1 evidence time in [t0−24 h, t0) and ≥ 1 in [t0−1 h, t0). Evidence times are candle close `T` for candles and `time` for funding records;
    - **ineligible:** no such evidence. A name absent from today's `meta` that also returns none is ineligible (`never_in_meta`);
    - **unknown:** the evidence cannot be fetched or lies beyond retention (candle mode: t0−24 h earlier than BTC's earliest 1h candle);
    - an unknown status excludes the event from all three studies.
  - **O6** Binance presence: a daily 1m file on `data.binance.vision` for the UTC day before date(t0), for some candidate symbol. Candidates: UM futures `T`, `1000T`, `1000000T`, `1MT` + `USDT`; spot `T`, `1000T`, `1MT` + `USDT`. The Binance-spot venue needs a spot file for that day.
  - **O7** Proxy: the first candidate, all UM futures before spot, with files for every UTC date from date(t0−1 d) to date(t0+2 d); none → `missing`.
  - **O8** Upbit KRW addition: a title with a KRW marker (`KRW` or `원화`) and an addition marker (`디지털 자산 추가`, `신규 상장` or `신규 거래지원`), containing none of 종료/유의/제거/변경/중단/연기/재개.
  - **O9** Already on Upbit KRW: an earlier harvested KRW-addition notice for the token, with no KRW trading-end notice (`거래지원 종료`, `상장폐지` or `상장 폐지`, not limited to BTC/USDT markets) between it and t0.
  - **O10** Upbit trading began before the notice: the trading-start time stated in the notice body is earlier than t0. A body with no parseable start time makes the event `unknown`.
  - **O11** Catalog-48 overlap: any catalog-48 title naming the token within ±24 h of t0, inclusive.
  - **O12** Delisting events come from harvested titles only.
    - Overlap is computed over the full harvest before the window filter.
    - A notice ≤ 24 h after the token's last kept notice is dropped.
  - **O13** Coverage = (unknown + missing + unresolved + harvest shortfall) / (token-events not excluded by a verified rule + harvest shortfall).
    - Above 0.20 → INCONCLUSIVE-by-data.
    - A catalog-48 shortfall counts for both Upbit studies.
  - **O14** Statistics:
    - halves: announcements sorted by (t0, id), the first floor(n/2) against the rest;
    - top decile: the ceil(n/10) largest announcement returns;
    - median: `statistics.median`.
  - **O15** Reported only: the bootstrap uses 10,000 resamples with `random.Random(229)`, 2.5/97.5 percentiles of the median. BTC adjustment uses BTCUSDT UM futures with β = 1.
  - **O16** Harvest completeness:
    - a full Binance catalog = pages 1..ceil(total/50), plus a closing page-1 fetch;
    - complete when unique ids ≥ the closing `total`;
    - two limiter suspensions, or 72 h without completing, mean the harvest cannot complete → INCONCLUSIVE-by-data;
    - Upbit is harvested from the operator's Mac, and the manifest records the host.
  - **O17** Monitoring-tag notices come from catalog 161. Catalog 49 is scanned back to 2023-01-01, and a monitoring-tag title found there stops Phase 1 for an operator decision.

- [ ] **Step 6: Run the tests.** Run `$PY -m pytest tests/test_news_event_studies_prereg.py -q`. Expected: 5 passed. Then run the append-only check. Tasks 10 and 11 reuse it with `OWN` set to `IDS`:

```bash
$PY - <<'EOF'
import json, subprocess
OWN = set()
old = json.loads(subprocess.check_output(["git", "show", "origin/main:ft_userdata/preregistrations.json"]))
new = json.load(open("ft_userdata/preregistrations.json", encoding="utf-8"))
o = {e["id"]: e for e in old["preregistrations"]}; n = {e["id"]: e for e in new["preregistrations"]}
assert new["_doc"] == old["_doc"] and [e["id"] for e in new["preregistrations"]][:len(o)] == list(o)
assert all(n[i] == o[i] for i in o if i not in OWN); print("append-only OK", sorted(set(n) - set(o)))
EOF
git diff origin/main -- ft_userdata/preregistrations.json | grep -c '^-[^-]'
```

  Expected: `append-only OK` with the three ids, then `1`. The only removed line is the previous last entry's `    }`, which gains a comma.
- [ ] **Step 7: Commit, open the PR and merge.**
  - Commit: `git add ft_userdata/preregistrations.json tests/test_news_event_studies_prereg.py` (plus the spec under option A), then `git commit -m "prereg: Part C event studies, three entries (#229)"`.
  - Open a PR to `main` titled `prereg: Part C event studies (#229)` with `Refs #229`. The body carries the probe results and the C1 decision.
  - Run a focused Codex Sol/high review per `~/.claude/codex-usage.md`.
  - Merge only when authorized. **No Phase 1 code runs on real data before this merges.**

### Task 2: `nes_util` and the Binance CMS harvester

**Files:**
- Create: `research/news_event_studies/.gitignore`, `research/news_event_studies/nes_util.py`, `research/news_event_studies/nes_harvest.py`
- Test: `tests/test_news_event_studies_harvest.py`, plus a CMS page builder fixture, `tests/fixtures/news_event_studies/cms_page.json`. It has the shape of Part A's `binance_cms_161.json`, with 3 articles.
- Branch: `claude/229-part-c-phase1`, which holds Tasks 2–6.

**Interfaces:**
- Consumes: `na_fetch.fetch`, `na_fetch.is_block_signal`, `na_fetch.BinanceLimiter`, `na_sources.CMS_URL`, `na_sources.BINANCE_HEADERS`, `na_store.iso_from_epoch`.
- Produces, in `nes_util`:
  - path constants: `HERE`, `DATA_DIR`, `ARCHIVE_DIR`, `ARCHIVE_LIMITER_STATE = ARCHIVE_DIR / "data" / "binance_cms_state.json"`;
  - time and size constants: `WINDOW_START_MS = 1672531200000`, `WINDOW_END_MS = 1793491200000`, `MINUTE_MS`, `HOUR_MS`, `DAY_MS`, `MIN_FREE_BYTES = 15 * 1024**3`;
  - `Req` — a frozen dataclass: `method`, `url`, `body: bytes | None`, `headers: dict`. Accepted by `na_fetch.fetch`;
  - `canonical_bytes(obj) -> bytes` — `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8, plus `b"\n"`;
  - hashing: `sha256_bytes(b: bytes) -> str`, `sha256_file(path) -> str`;
  - time conversion: `iso_ms(ms: int) -> str`, `ms_from_iso(s: str) -> int`, `utc_date(ms: int) -> str` (`"YYYY-MM-DD"`);
  - `disk_ok(path) -> bool`.
- Produces, in `nes_harvest`:
  - constants: `CMS_PAGE_SIZE = 50`, `OWN_GAP_S = 540`, `MAX_HARVEST_S = 72 * 3600`;
  - `CmsPage` — a dataclass: `catalog_id: int`, `catalog_name: str | None`, `total: int | None`, `articles: list[dict]`;
  - `cms_url(catalog_id: int, page_no: int) -> str` → `CMS_URL + "?type=1&pageNo=%d&pageSize=50&catalogId=%d"`;
  - `parse_cms_page(body: bytes) -> CmsPage` — raises `ValueError` when `success` is not true;
  - `merge_articles(pages: list[CmsPage]) -> dict[str, dict]` — keyed by `str(id)`, first occurrence kept;
  - `completeness(merged: dict, closing: CmsPage) -> dict` → `{"unique": int, "total": int | None, "total_reported": bool, "shortfall": int}`, where `shortfall = max(0, total - unique)` and 0 when there is no total;
  - `class HarvestAborted(Exception)`;
  - `CmsHarvester(limiter, fetcher, wall, sleep, out_dir: Path)` with two methods:
    - `harvest(catalog_id: int) -> dict`;
    - `scan(catalog_id: int, stop_before_ms: int) -> dict`.
    Both write raw bodies to `out_dir/cat<ID>/page-<NNNN>.json` and `closing.json`. They also update `out_dir/harvest_meta.json`, per catalog: `catalog_name`, pages, completeness, request times, suspensions, `aborted`, and each file's sha256;
  - `main(argv) -> int` — `binance --harvest 161,48 --scan 49 --out DIR [--limiter-state PATH]`. The limiter state defaults to `ARCHIVE_LIMITER_STATE`. Exit 2 if the state file's directory does not exist; exit 4 on `HarvestAborted`.
- **Request rule:**
  - wait until ≥ `OWN_GAP_S` have passed since the harvester's own last request;
  - then call `limiter.try_acquire(wall())` every 1 s until it is granted;
  - when `limiter.suspended_until(wall())` is set, count one suspension per distinct `suspended_until` value and sleep past it. The second suspension raises `HarvestAborted`. A block signal on the harvester's own response calls `limiter.suspend(wall())`, then counts the same way;
  - `MAX_HARVEST_S` since the first request also raises.
- **`harvest`:**
  - page 1's `total` sets `ceil(total/50)` pages;
  - it keeps paging while the last page is full;
  - then the closing page-1 fetch, which is always fresh;
  - page files already on disk are not requested again, so a run can resume.
- **`scan`:** stops after the first page whose oldest `releaseDate` is before `stop_before_ms`. It computes no completeness.

- [ ] **Step 1: Write the failing tests.** Use a real `BinanceLimiter(tmp_path / "state.json", boot_id=None, mono=fake)`, a fake wall clock that `sleep` advances, and a fake fetcher that serves pages from an in-test catalog list.

```python
def test_full_harvest_requests_pages_then_closing(tmp_path):    # total 120 -> pageNo 1,2,3 then 1; unique 120, shortfall 0
def test_new_article_mid_harvest_is_not_a_shortfall(tmp_path):  # new top article after page 1: boundary dup deduped,
                                                                 # closing total 121, unique 121, shortfall 0
def test_short_harvest_is_a_shortfall(tmp_path):                # total 120 but page 3 returns 19 -> shortfall 1
def test_no_total_reported(tmp_path):                           # total absent -> total_reported False
def test_requests_spaced_540s_and_each_acquired(tmp_path):      # consecutive request times differ by >= 540
def test_block_signal_suspends_shared_limiter_and_second_aborts(tmp_path):
    # HTML 200 -> state file suspended_until set, harvest waits; a second suspension -> HarvestAborted,
    # meta "aborted" == "second suspension"
def test_resume_skips_saved_pages(tmp_path):
def test_scan_stops_at_window_start(tmp_path):                  # stops after the first page with oldest < WINDOW_START_MS
def test_refuses_when_archive_limiter_dir_missing(tmp_path):    # main([... "--limiter-state", str(tmp_path/"no"/"s.json")]) == 2;
                                                                 # fetcher never called
def test_canonical_bytes_sorted_compact_utf8():                 # {"b":1,"a":"é"} -> b'{"a":"\xc3\xa9","b":1}\n'
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_harvest.py -q`. Expected: FAIL (`ModuleNotFoundError: nes_harvest`).
- [ ] **Step 3:** Implement `nes_util.py`, the `.gitignore` and the Binance half of `nes_harvest.py` as specified. Fetch through `na_fetch.fetch(Req("GET", cms_url(...), None, na_sources.BINANCE_HEADERS))`.
- [ ] **Step 4:** Run the same command. Expected: 10 passed.
- [ ] **Step 5:** Commit: `git add research/news_event_studies tests/test_news_event_studies_harvest.py tests/fixtures/news_event_studies`, then `git commit -m "news-event-studies: Binance CMS full-catalog harvester (#229)"`.

### Task 3: Upbit harvester (runs on the operator's Mac)

**Files:**
- Modify: `research/news_event_studies/nes_harvest.py`
- Test: `tests/test_news_event_studies_harvest.py`, plus fixtures `upbit_list_page.json` (trimmed like Part A's `upbit.json`) and `upbit_detail.json` (synthetic, with one start line).

**Interfaces:**
- Consumes: `nes_util` (Task 2), `na_sources.UPBIT_URL`, `na_sources.JSON_HEADERS`.
- Produces:
  - constants: `UPBIT_GAP_S = 10.0`, plus `UPBIT_DETAIL_URL` and `UPBIT_BODY_KEY`, both set to the form and key that Task 1's probe found;
  - `UpbitPage` — `total_count: int | None`, `total_pages: int | None`, `notices: list[dict]`;
  - `parse_upbit_page(body: bytes) -> UpbitPage` — raises `ValueError` when `success` is not true. `fixed_notices` are ignored;
  - `parse_upbit_detail(body: bytes) -> dict` → `{"id", "title", "body", "first_listed_at", "listed_at"}`;
  - `class HarvestBlocked(Exception)`;
  - `UpbitHarvester(fetcher, wall, sleep, out_dir: Path, host_label: str)` with `run(detail_from_ms: int, detail_to_ms: int) -> dict`. It writes `list/page-<NN>.json`, `list/closing.json`, `detail/<id>.json` and `harvest_meta.json`. The meta holds `host_label`, start and finish times, list completeness (unique ids vs the closing `total_count`), `detail_ids` and each file's sha256;
  - CLI: `upbit --out DIR --host-label LABEL`. It fetches details for notices whose `first_listed_at` falls in [`WINDOW_START_MS − DAY_MS`, `WINDOW_END_MS + DAY_MS`), and exits 3 on `HarvestBlocked`.
- **Request rules:**
  - requests are ≥ 10 s apart;
  - `na_fetch.is_block_signal` (403/418/429 or a non-JSON body, which covers Cloudflare 1015 pages) → write the meta and raise `HarvestBlocked`, with no retry;
  - saved files are skipped on rerun;
  - the list covers pages 1..`total_pages`, then a closing page-1 fetch.

- [ ] **Step 1: Write the failing tests**

```python
def test_upbit_pages_spaced_10s_then_closing(tmp_path):
def test_upbit_block_stops_after_one_request_no_retry(tmp_path):  # 429 + b"error code: 1015" -> HarvestBlocked,
                                                                   # exactly 1 fetch, meta "blocked" set
def test_upbit_details_only_inside_window_margin(tmp_path):
    # first_listed_at 2022-12-30T23:59+00:00 no; 2022-12-31T00:00+00:00 yes; 2026-11-01T23:59+00:00 yes;
    # 2026-11-02T00:00+00:00 no
def test_upbit_meta_has_host_label_and_hashes(tmp_path):
def test_upbit_completeness_ignores_fixed_notices(tmp_path):
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_harvest.py -q`. Expected: the 5 new tests FAIL.
- [ ] **Step 3:** Implement the Upbit half of `nes_harvest.py`.
- [ ] **Step 4:** Run the same command. Expected: 15 passed.
- [ ] **Step 5:** Commit: `git commit -am "news-event-studies: Upbit list and detail harvester for the Mac run (#229)"`. Add the new fixtures first.

### Task 4: Title and body classifiers

**Files:**
- Create: `research/news_event_studies/nes_classify.py`
- Test: `tests/test_news_event_studies_classify.py`

**Interfaces:**
- Produces:
  - `EXCLUDE_WORDS = ("종료", "유의", "제거", "변경", "중단", "연기", "재개")`;
  - `BinanceClass` — a NamedTuple: `kind: str`, `tokens: tuple[str, ...]`. `kind` is one of:
    - `"full_delist"`, `"monitoring_add"`, `"unclassified"`;
    - `"excluded:<reason>"`, with reason in {`pair_removal`, `margin`, `futures`, `leveraged`, `options`, `vote`, `tag_removal`, `retraction`, `other_product`};
  - `classify_binance(title: str) -> BinanceClass`;
  - `mentions_token(title: str, token: str) -> bool`;
  - `upbit_addition(title: str) -> tuple[str, ...] | None`;
  - `upbit_end(title: str) -> tuple[str, ...] | None`;
  - `upbit_needs_review(title: str) -> bool`;
  - `upbit_trading_start_ms(body: str) -> int | None`.
- **Rules:**
  - A ticker is ASCII `[A-Z0-9]{1,15}`.
  - **Binance:**
    - **`full_delist`:** the title starts `Binance Will Delist` and contains none of `Trading Pair`, `/`, `Margin`, `Futures`, `Perpetual`, `Leveraged`. Tokens are the text between `Delist ` and ` on <date>` (or the end of the title), split on `,`, `&` and ` and `. Any piece that is not a ticker makes the title `unclassified`.
    - **`monitoring_add`:** the title contains `Monitoring Tag` and `Include` or `Add`. Tokens come from that clause, up to ` and Remove` or ` on <date>`. A title that only removes a tag is `excluded:tag_removal`.
    - **`mentions_token`:** matches `(?<![A-Z0-9])(?:1000000|1000|1M)?T(?:USDT|USDC|FDUSD|BTC)?(?![A-Z0-9])`, case-sensitive.
  - **Upbit:**
    - **Additions follow O8.** Tickers come from `Name(TICKER)` groups. Failing that, from the items of the last parenthesized group that is not a market group, taking each item's last ASCII word. A market group is parenthesized text ending in `마켓`.
    - **Ends follow O9.**
    - **`upbit_needs_review`:** a KRW marker, no exclude word, and neither an addition nor an end.
    - **Start time:** read from the line containing `거래지원 개시`, `거래 지원 개시` or `거래 오픈`. Accepted formats are `YYYY년 M월 D일 HH:MM`, `YYYY-MM-DD HH:MM` and `YYYY.MM.DD HH:MM`, all KST.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("title,tokens", [
    ("원화 마켓 신규 상장 (이오스 EOS)", ("EOS",)),
    ("원화 마켓 디지털 자산 추가 (AXS, STX, FLOW, DAWN)", ("AXS", "STX", "FLOW", "DAWN")),
    ("KRW, BTC 마켓 디지털 자산 추가 (SOL, MATIC, NU)", ("SOL", "MATIC", "NU")),
    ("닐리온(NIL) KRW 마켓 디지털 자산 추가", ("NIL",)),
    ("콘크리트(CT) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)", ("CT",)),
    ("액시스로보틱스(AXIS) 신규 거래지원 안내 (KRW, BTC, USDT 마켓) (매도 최저가 기준 가격 안내)", ("AXIS",)),
    ("BTC, USDT 마켓 디지털 자산 추가 (ABC)", None),
])
def test_upbit_addition_formats(title, tokens):
@pytest.mark.parametrize("word", ["종료", "유의", "제거", "변경", "중단", "연기", "재개"])
def test_upbit_exclude_words(word):          # upbit_addition(f"닐리온(NIL) KRW 마켓 디지털 자산 추가 {word}") is None
def test_upbit_end_and_market_specific_end():
    # "닐리온(NIL) 거래지원 종료 안내" -> ("NIL",); "닐리온(NIL) BTC 마켓 거래지원 종료 안내" -> None;
    # "닐리온(NIL) 거래지원 종료 연기 안내" -> None
def test_upbit_needs_review():                # "닐리온(NIL) KRW 마켓 입금 안내" -> True; additions and ends -> False
def test_upbit_trading_start_formats():
    # "거래지원 개시 시점 : 2026년 10월 27일 17:30 KST" and "- 거래 지원 개시 시점: 2026-10-27 17:30"
    # -> 1793089800000 (2026-10-27T08:30Z); a body with no such line -> None
@pytest.mark.parametrize("title,kind,tokens", [
    ("Binance Will Delist EPIC, QUICK on 2026-10-28", "full_delist", ("EPIC", "QUICK")),
    ("Binance Will Extend the Monitoring Tag to Include ACT, BLUR, PIVX & QKC on 2026-06-18",
     "monitoring_add", ("ACT", "BLUR", "PIVX", "QKC")),
    ("Binance Will Extend the Monitoring Tag to Include ABC and Remove the Monitoring Tag on XYZ on 2026-01-02",
     "monitoring_add", ("ABC",)),
    ("Binance Will Remove the Monitoring Tag on XYZ on 2026-01-02", "excluded:tag_removal", ()),
    ("Notice of Removal of Spot Trading Pairs - 2026-10-31", "excluded:pair_removal", ()),
    ("Binance Margin Will Delist ABC/USDT Cross Margin Pair", "excluded:margin", ()),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", "excluded:futures", ()),
    ("Vote to Delist Results - 2026-03", "excluded:vote", ()),
    ("Binance Updates Its Tokenomics Guidelines", "unclassified", ()),
])
def test_classify_binance(title, kind, tokens):
def test_mentions_token():
    # ("Binance Will List Pepe (PEPE)","PEPE") True; ("Binance Futures Will Launch USDⓈ-M 1000PEPE Perpetual Contract","PEPE") True;
    # ("Binance Will Add APE on Earn","PE") False; ("Binance Will List ARKMUSDT Perpetual","ARKM") True
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_classify.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `nes_classify.py`.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5:** Commit: `git add research/news_event_studies/nes_classify.py tests/test_news_event_studies_classify.py`, then `git commit -m "news-event-studies: title and body classifiers (#229)"`.

### Task 5: Venue evidence (Hyperliquid, Binance file existence)

**Files:**
- Create: `research/news_event_studies/nes_venues.py`
- Test: `tests/test_news_event_studies_venues.py`, plus fixtures:
  - `hl_meta.json`: 3 names, one `isDelisted`, one `xyz:ABC`;
  - `hl_funding.json` and `hl_candles_1h.json`: 2 records each, prices replaced by `"0"`.

**Interfaces:**
- Consumes: `nes_util.Req`, `na_fetch.fetch`.
- Produces:
  - constants: `HL_EVIDENCE` (the frozen value, `"fundingHistory"` or `"candleSnapshot_1h"`), `HL_GAP_S = 20.0`, `HL_429_PAUSE_S = 600.0`;
  - `ALIASES: dict[str, dict] = {}`. Each future entry is `{"binance": str | None, "hl": str | None, "from": "YYYY-MM-DD", "source": "<harvested notice id>"}`;
  - `hl_meta_index(body: bytes) -> dict[str, dict]` — upper-cased name → `{"name", "delisted"}`; skips names containing ":";
  - `hl_names(token: str, index: dict) -> list[str]` — those of [T, "k"+T] present in `index`, plus `ALIASES[T]["hl"]`;
  - `hl_evidence_request(coin: str, t0_ms: int, mode: str) -> Req` — startTime `t0−86_400_000`, endTime `t0−1`;
  - `hl_evidence_times(body: bytes, mode: str) -> list[int]` — candle `T` or funding `time` only; prices are discarded;
  - `hl_status(times: list[int] | None, t0_ms: int) -> str` — `"eligible"`, `"ineligible"` or `"unknown"`, per O5;
  - `retention_floor_ms(btc_candles_body: bytes) -> int` — candle mode only;
  - `HlClient(fetcher, sleep, wall)` with `meta() -> bytes` and `evidence(coin, t0_ms, mode) -> list[int]`. It applies the pacing and 429 rules and raises `VenueAborted`;
  - `hl_facts(token, t0_ms, index, client, floor_ms: int | None, mode) -> dict` → `{"status", "coin", "reason"}`:
    - with no name in `meta`, query `T` by name anyway (spec §6.2): evidence → evaluate it; none → `ineligible`/`never_in_meta`;
    - in candle mode, `t0 − 24 h < floor_ms` → `unknown`/`beyond_retention`, without any request;
    - across several names, the first `eligible` wins; else `unknown` if any name is unknown; else `ineligible`;
  - `binance_candidates(token: str, t0_ms: int) -> list[tuple[str, str]]` — the O6 order, `("um", sym)` before `("spot", sym)`. An alias base replaces `T` from its `from` date on;
  - `kline_url(market: str, symbol: str, date: str) -> str` → `https://data.binance.vision/data/futures/um/daily/klines/{S}/1m/{S}-1m-{D}.zip`, or `/data/spot/daily/klines/...` for spot;
  - `FileProbe(fetcher, sleep)` with `exists(url) -> bool`:
    - sends HEAD; 200 → `True`; 403/404 → `False`;
    - anything else gets 3 attempts 5 s apart, then raises `ProbeError`;
    - results are cached per URL, at most 2 requests/s;
  - `binance_facts(token, t0_ms, probe) -> dict` → `{"on_binance_pre_t0": bool, "spot_symbol_pre_t0": str | None, "proxy": {"market", "symbol"} | None}`, per O6 and O7.

- [ ] **Step 1: Write the failing tests**

```python
T0 = 1709294430000  # 2024-03-01T12:00:30Z
def test_hl_status_rule():           # [T0-1_800_000, T0-18_000_000] eligible; [T0-10_800_000] ineligible (no last hour);
                                     # [T0+60_000] ineligible (after t0 ignored); None unknown
def test_hl_status_half_open_boundaries():  # T0-3_600_000 counts as last hour; T0-86_400_000 counts; T0 itself ignored
def test_hl_request_never_reaches_t0():     # body startTime == T0-86_400_000, endTime == T0-1, for both modes
def test_hl_names_k_prefix_and_skips_hip3():
def test_beyond_retention_is_unknown_without_request():   # candle mode; fake fetcher asserts no call
def test_not_in_meta_queries_by_name_then_never_in_meta():
def test_hl_429_pauses_once_then_aborts():   # 429 -> sleep(600) recorded; second 429 -> VenueAborted
def test_evidence_times_drop_prices():       # returns list[int]; no float or str
def test_file_probe_sends_head_only():
def test_transient_error_is_not_absence():   # 503, 503, 503 -> ProbeError, never False
def test_binance_facts_prefers_um_then_spot_and_needs_every_date():
    # UM file missing on date(T0)+2 d -> spot chosen; neither complete -> proxy None
def test_on_binance_pre_t0_uses_previous_utc_date():  # only 2024-02-29 checked for presence
def test_hl_evidence_constant_matches_prereg():       # HL_EVIDENCE == frozen["hl_evidence"] of all three entries
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_venues.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `nes_venues.py`. HL POSTs use `{**na_sources.JSON_HEADERS, "Content-Type": "application/json"}`.
- [ ] **Step 4:** Run the same command. Expected: 13 passed.
- [ ] **Step 5:** Commit: `git commit -m "news-event-studies: Hyperliquid evidence and Binance file existence (#229)"`. Add the files first.

### Task 6: Phase 1 manifest builder

**Files:**
- Create: `research/news_event_studies/nes_manifest.py`
- Test: `tests/test_news_event_studies_manifest.py`. Raw harvest directories are written to `tmp_path` by helper functions in the test.

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - `STUDIES` — the three ids from Task 1;
  - `class NeedsReview(Exception)` with `.items: list[dict]`;
  - **Loaders**, both of which verify every file against the sha256 in `harvest_meta.json` and raise `ValueError` on a mismatch:
    - `load_cms(raw_dir: Path) -> dict` — merged articles and completeness per catalog;
    - `load_upbit(raw_dir: Path) -> dict` — notices, details, completeness, `host_label`;
  - `delisting_events(articles161: list[dict], scan49: list[dict]) -> list[dict]`:
    - classifies everything, applies O12, then the window;
    - an in-window `unclassified` title, or any in-window monitoring-tag title in `scan49` (O17), goes into `NeedsReview`;
  - `upbit_events(notices: list[dict], details: dict[str, dict], cms48: list[dict]) -> list[dict]`:
    - applies O8 and O9 over the full history, then the window, O11 and O10;
    - an in-window `upbit_needs_review` title goes into `NeedsReview`;
  - **Event dict:** `announcement_id` (`"binance:<id>"` / `"upbit:<id>"`), `t0_ms`, `t0`, `title`, `kind` (`full_delist` | `monitoring_add` | `krw_addition`), `token`, `exclusion` (reason or `None`), `exclusion_ref`, `trading_start_ms`, `hl` (from `hl_facts`, or `None` when skipped), `binance` (from `binance_facts`, or `None` when skipped);
  - `study_status(event: dict, study: str) -> str` — the first rule that applies, in this order:
    1. a rule exclusion → `excluded:<reason>`;
    2. Upbit with no parseable start → `unknown`;
    3. Upbit not on Binance before t0 → `excluded:not_on_binance`;
    4. Hyperliquid status unknown → `unknown`;
    5. the venue:
       - delisting: Hyperliquid eligible, else `excluded:no_hl`;
       - fade: Hyperliquid eligible, else `excluded:spot_only` when a spot symbol exists, else `excluded:no_hl`;
       - long: Hyperliquid eligible, else spot if a spot symbol exists, else `excluded:futures_only`;
    6. no proxy → `missing`;
    7. `candidate:hyperliquid` or `candidate:binance_spot`;
  - `build(cms_dir, upbit_dir, hl_client, probe, code_commit: str) -> tuple[dict, dict]` — the delisting and Upbit manifests. Hyperliquid and Binance facts are fetched only for events that reach step 3;
  - `manifest_counts(manifest: dict, study: str) -> dict` → `{"candidates", "unknown", "missing", "excluded": {reason: n}, "harvest_shortfall", "harvest_complete"}`;
  - `main(argv) -> int` — `build --cms DIR --upbit DIR --out DIR --code-commit SHA`:
    - writes `delisting-manifest.json` and `upbit-manifest.json` with `canonical_bytes`, plus `build-report.txt`;
    - prints both SHA-256s;
    - exit 5 on `NeedsReview`, printing each item.
- **Manifest keys:**
  - `manifest_version: 1`, `studies`, `window_utc`, `code_commit`, `hl_evidence`, `hl_retention_floor` (candle mode only);
  - `inputs`: raw-file sha256s, the `meta` response's sha256, per-catalog completeness, Upbit `host_label`;
  - `harvest_complete` — false when any required catalog reports no `total` or a harvest aborted;
  - `events`, sorted by (`t0_ms`, `announcement_id`, `token`).
  - No key anywhere is named `open`, `high`, `low`, `close`, `price` or `return`.
- **`build-report.txt`:** per-study counts, plus every `never_in_meta`, `not_on_binance`, `already_on_krw`, `binance48_overlap` and `missing` token with its title and reference.

- [ ] **Step 1: Write the failing tests**

```python
def test_overlap_keeps_first_and_measures_from_last_kept():
    # same token at +0 h, +20 h, +24 h, +30 h, +40 h -> kept +0 h and +30 h
def test_overlap_runs_before_window():        # 2022-12-31T12:00Z then 2023-01-01T06:00Z -> no in-window event
def test_window_end_exclusive():              # t0 1793491199999 in; 1793491200000 out
def test_in_window_unclassified_raises_needs_review():   # the same title out of window does not
def test_monitoring_title_in_scan49_raises_needs_review():
def test_upbit_replay_already_on_krw():
    # add 2023-03-01 then add 2023-05-01 -> second excluded already_on_krw with prior id;
    # add, end 2024-01-10, re-add 2024-06-01 -> re-add kept
def test_upbit_binance48_overlap_inclusive_24h():  # mention at t0+24 h excluded; t0+24 h+1 ms kept; other token kept
def test_upbit_trading_start_rules():         # start < t0 excluded began_before_notice; start == t0 kept; no line -> unknown
def test_upbit_t0_is_first_listed_at():
@pytest.mark.parametrize("facts,delisting,long,fade", STATUS_ROWS)
def test_study_status_table(facts, delisting, long, fade):
    # STATUS_ROWS: one row per study_status rule 1-7, e.g. rule 5 with HL ineligible and a spot symbol
    # -> ("excluded:no_hl", "candidate:binance_spot", "excluded:spot_only"); rule 4 -> ("unknown",)*3
def test_manifest_deterministic_and_price_free(tmp_path):    # two builds -> identical bytes; recursive key scan clean
def test_shortfall_and_missing_total_in_counts(tmp_path):
    # cat161 shortfall 2 -> delisting harvest_shortfall 2; cat48 shortfall 1 -> both Upbit studies 1;
    # cat161 total absent -> harvest_complete False
def test_upbit_hash_mismatch_refuses(tmp_path):
def test_build_report_lists_unmatched_tokens(tmp_path):
def test_excluded_events_get_no_venue_requests(tmp_path):
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_manifest.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `nes_manifest.py`.
- [ ] **Step 4:** Run `$PY -m pytest tests/ -q`. Expected: the whole root suite passes, with no new skips.
- [ ] **Step 5:** Commit: `git commit -m "news-event-studies: outcome-blind Phase 1 manifest builder (#229)"`. Add the files first.
- [ ] **Step 6: Open the Phase 1 PR.**
  - Title: `news-event-studies: Part C Phase 1 harvest and manifest (#229)`, with `Refs #229`.
  - Record the test counts and limitations: no real data processed yet, and O16's count check cannot see an article deleted mid-harvest.
  - Run a Codex Sol/high review, fix the valid findings, and merge when authorized.

### Task 7: Phase 2 kline layer

**Files:**
- Create: `research/news_event_studies/nes_klines.py`
- Test: `tests/test_news_event_studies_klines.py`. The tests build their zips with `zipfile` from hand-written rows.
- Branch: `claude/229-part-c-phase2`, which holds Tasks 7–9.

**Interfaces:**
- Consumes: `nes_util`, `nes_venues.kline_url`, `na_fetch.fetch`.
- Produces:
  - `parse_kline_csv(text: str) -> dict[int, list[str]]` — open ms → `[open, high, low, close]`, kept as strings:
    - a first line whose first field is not an integer is a header and is skipped;
    - an open time ≥ `10**14` is in microseconds and is floor-divided by 1,000;
  - `download_dates(t0_ms: int) -> list[str]` — the 7 UTC dates from date(t0−1 d) to date(t0+5 d);
  - `span(t0_ms: int) -> tuple[int, int]` → `(t0 − 15 min, t0 + 5 min + 24 h + 72 h + 1 min)`;
  - `class DiskGuard(Exception)`;
  - `fetch_series(market, symbol, t0_ms, fetcher, work_dir: Path, disk_ok: Callable[[], bool]) -> dict` → `{"rows": {...within span}, "absent_dates": [...]}`:
    - a GET per date, with `max_bytes=20_000_000`;
    - 404 → that date is absent;
    - any other non-200 gets 3 attempts, then raises;
    - each zip is written to `work_dir`, extracted, then deleted;
    - `disk_ok()` is checked before each download, and `False` raises `DiskGuard`;
  - `store_series(path, series)` and `load_series(path)`, in canonical JSON.

- [ ] **Step 1: Write the failing tests**

```python
def test_ms_and_us_open_times_normalize():   # "1704067200000,..." and "1735689600000000,..." -> keys 1704067200000, 1735689600000
def test_header_row_skipped():               # "open_time,open,high,low,close,..." first line ignored
def test_rows_limited_to_span_and_zip_deleted(tmp_path):
def test_404_day_is_absent_not_error(tmp_path):
def test_disk_guard_raises_before_any_download(tmp_path):    # fetcher never called
def test_server_error_retries_then_raises(tmp_path):         # 500 x3 -> raises; 3 calls
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_klines.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `nes_klines.py`.
- [ ] **Step 4:** Run the same command. Expected: 6 passed.
- [ ] **Step 5:** Commit: `git commit -m "news-event-studies: data.binance.vision kline layer (#229)"`. Add the files first.

### Task 8: Returns, criteria and verdict (pure)

**Files:**
- Create: `research/news_event_studies/nes_returns.py`
- Test: `tests/test_news_event_studies_returns.py`. Series are built by a helper `rows({minute_offset: close})`, with high = low = close unless given.

**Interfaces:**
- Consumes: `nes_util`, plus series in the `nes_klines` row format.
- Produces:
  - **Constants**, each equal to the Task 1 `frozen` value:
    - `ENTRY_OFFSET_MS = 300_000`, `T60_OFFSET_MS = 60_000`;
    - `HORIZONS_MS = {"30m": 1_800_000, "4h": 14_400_000, "24h": 86_400_000}`, `PRIMARY = "4h"`;
    - `FEE_BPS = {"hyperliquid": 4.5, "binance_spot": 7.5}`, `SLIP_BPS = 10`, `STRESS_SLIP_BPS = 25`;
    - `LEAK_GT = Decimal("0.02")`, `LEAK_FROM_MS = -600_000`, `LEAK_TO_MS = -120_000`, `HALT_WINDOW_MS = 259_200_000`;
    - `MIN_ANN = 20`, `TOP_DECILE_LT = 0.6`, `COVERAGE_GT = 0.2`, `BOOT_N = 10_000`, `BOOT_SEED = 229`;
  - `price_at(rows, instant_ms: int) -> str | None`;
  - `leaked(rows, t0_ms: int) -> bool | None` — `None` when either leak candle is missing;
  - `exit_at(rows, scheduled_ms: int) -> tuple[str, str | None, int | None]` → (`"ok"` | `"halted"` | `"unresolved"`, close, candle open ms);
  - `net(entry: str, exit: str, direction: str, venue: str, slip_bps: float) -> float`;
  - `mae_short(rows, entry_ms: int, exit_candle_ms: int, entry: str) -> float | None` — max(high)/entry − 1 over the candles after the entry candle, up to and including the exit candle; `None` if any of them is missing;
  - `evaluate(event: dict, rows: dict, btc_rows: dict, direction: str, venue: str) -> dict`, where `venue` is the suffix of the event's `candidate:<venue>` status → `{"status", "leaked", "horizons": {h: {"exit_status", "gross", "net", "net_stress", "btc_adj_net", "mae"}}, "t60": {h: net}}`:
    - `status` is `"missing"` or `"unresolved"` per O4, else `"halted"` if any exit halted, else `"ok"`;
    - `btc_adj_net = sign × ((exit/entry − 1) − (btc_exit/btc_entry − 1)) − round-trip cost`, with `sign` +1 for long and −1 for short; `None` when a BTC candle is missing;
  - `announcements(results: list[dict], horizon: str, include_leaked: bool = False, key: str = "net") -> list[tuple[int, str, float]]` — (t0, announcement id, mean over its usable tokens);
  - `criteria(anns) -> dict` → `{"n", "median", "half_medians", "sum", "top_decile_share", "passes": {"n", "median", "halves", "concentration"}}`;
  - `coverage(counts: dict, results: list[dict]) -> float` — O13;
  - `verdict(counts: dict, results: list[dict]) -> tuple[str, list[str]]` — collects every applicable reason; the first applicable rule below wins:
    1. `harvest_complete` false → `"INCONCLUSIVE-by-data"`;
    2. any unresolved → `"INCONCLUSIVE"`;
    3. coverage > 0.2 → `"INCONCLUSIVE-by-data"`;
    4. n < 20 → `"INCONCLUSIVE-by-data"`;
    5. all four criteria pass → `"PASS"`, else `"FAIL"`;
  - `bootstrap_median_ci(values: list[float], n: int = BOOT_N, seed: int = BOOT_SEED) -> tuple[float, float]`.

- [ ] **Step 1: Write the failing tests** (hand-computed; `T0 = 1709294430000`)

```python
def test_price_at_uses_close_of_containing_minute():    # candle open 12:05:00 close "100" -> price_at(T0+300_000) == "100"
def test_net_long_short_and_costs():
    assert net("100", "98", "long", "hyperliquid", 10) == pytest.approx(-0.0229, abs=1e-12)
    assert net("100", "98", "short", "hyperliquid", 10) == pytest.approx(0.0171, abs=1e-12)
    assert net("100", "98", "long", "binance_spot", 10) == pytest.approx(-0.0235, abs=1e-12)
    assert net("100", "98", "short", "hyperliquid", 25) == pytest.approx(0.0141, abs=1e-12)
def test_fade_is_negated_long_gross_minus_costs():      # same rows: short net == -(long gross) - 0.0029
def test_leak_strictly_above_two_percent():  # c(-10m) "100": "102" False, "102.01" True, "98" False, "97.99" True, gap None
def test_halt_exit_first_candle_within_72h():
    # +4 h candle missing, next candle at +5 h close "97" -> ("halted", "97", ...);
    # next candle exactly at +72 h -> halted; at +72 h +1 min -> ("unresolved", None, None)
def test_missing_leak_or_entry_candle_makes_event_missing():
def test_unresolved_at_any_horizon_makes_event_unresolved():   # +30m and +4h ok, +24h unresolved
def test_announcement_is_mean_of_its_tokens():          # nets 0.01 and -0.03 -> one announcement, -0.01
def test_leaked_dropped_from_primary_kept_in_sensitivity():
def test_halves_by_date_order():                        # 5 announcements -> halves of 2 and 3, sorted by (t0, id)
def test_top_decile_ceil_and_nonpositive_sum():
    # n=20, [0.05, 0.04] + 18*[0.001] -> share 0.09/0.108 = 0.8333 -> concentration fails;
    # 20*[0.01] -> share 0.1 passes; any set with sum <= 0 -> fails
def test_coverage_counts_shortfall_in_both_terms():     # 40 cand, 5 unknown, 3 missing, 2 shortfall, 1 Phase 2 missing -> 11/50
@pytest.mark.parametrize("case,verdict", [("harvest_incomplete", "INCONCLUSIVE-by-data"), ("one_unresolved", "INCONCLUSIVE"),
    ("coverage_0.22", "INCONCLUSIVE-by-data"), ("n_19", "INCONCLUSIVE-by-data"), ("all_pass", "PASS"), ("halves_fail", "FAIL")])
def test_verdict_order(case, verdict):
def test_mae_short_from_highs_none_on_gap():            # highs "101","104" after entry "100" -> 0.04; a gap -> None
def test_btc_adjusted_net():                            # token 100->98, BTC 100->99, long HL -> -0.0129
def test_bootstrap_deterministic():                     # two calls, same values -> identical tuples
def test_constants_match_prereg():                      # every constant above == the frozen value in all three entries
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_returns.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `nes_returns.py`. Leak arithmetic uses `Decimal` on the CSV strings; returns use `float`.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "news-event-studies: Phase 2 returns, criteria and verdict (#229)"`. Add the files first.

### Task 9: Phase 2 CLI, reports, resolution and README

**Files:**
- Create: `research/news_event_studies/nes_report.py`, `research/news_event_studies/README.md`
- Test: `tests/test_news_event_studies_report.py`

**Interfaces:**
- Consumes: Tasks 6–8.
- Produces:
  - `compute(manifest_path: Path, expect_sha256: str, out_dir: Path, fetcher, work_dir: Path, disk_ok) -> dict[str, dict]`:
    - on a SHA-256 mismatch it raises `ValueError` before any request;
    - the delisting manifest yields one study; the Upbit manifest yields the long and the fade from the same series;
    - it downloads only `candidate:*` events' proxies, plus BTCUSDT UM futures;
    - it writes `results-<study>.json` and `report-<study>.md`;
  - `resolution(results: dict) -> dict` → `{"verdict", "reasons", "label": "proxy result", "primary_4h": {"n", "median", "half_medians", "top_decile_share"}, "manifest_sha256", "code_commit", "computed_at"}`;
  - `verify_resolution(prereg_path: Path, results_dir: Path) -> list[str]` — mismatches; an empty list means OK;
  - `main(argv) -> int` with three subcommands:
    - `compute --manifest PATH --expect-sha256 HEX --out DIR` — exit 2 on a mismatch;
    - `resolution --results DIR` — prints the three JSON fragments;
    - `verify-resolution --prereg PATH --results DIR` — exit 1 on a mismatch.
- **Each report contains:**
  - the verdict and its reasons, under the heading label "proxy result";
  - counts: excluded by reason, unknown, missing, unresolved, halted, leaked;
  - each of the 3 horizons by all events, by half, and by venue (Upbit long) or notice kind (delisting);
  - the leak-included and 25 bps sensitivities;
  - the bootstrap CI and BTC-adjusted medians;
  - MAE p50/p90/max, for the two short studies only;
  - the t+60 s descriptive entry;
  - limitations: titles only and current CMS versions; Hyperliquid funding not modelled; Binance proxy prices; Upbit harvested from the operator's Mac;
  - in the two Upbit reports, the §6.2 note that the long and the fade share their Hyperliquid events, so a failed long plus a passed fade is one finding.
- **README:**
  - what the studies are, with a link to the spec;
  - the Task 1 probe results, including whether the delisted-coin lookup by name works (spec §6.2 asks the builder to document it);
  - the quarantine rule;
  - the Mac Upbit step as the one network exception to the Mac checkout's network-free rule (no Docker, no servers);
  - every Task 10–11 command;
  - an install log table: date, commit, by.

- [ ] **Step 1: Write the failing tests**

```python
def test_compute_refuses_sha_mismatch(tmp_path):      # raises/exit 2; fetcher never called; no results file
def test_compute_end_to_end_fixture(tmp_path):
    # fixture delisting manifest: 2 announcements (2 tokens, 1 token), fake fetcher serving hand-made zips;
    # nets equal hand-computed values; verdict "INCONCLUSIVE-by-data" with reason n < 20;
    # every fetched URL is a kline_url of a manifest proxy or BTCUSDT um
def test_upbit_manifest_yields_long_and_fade_from_same_rows(tmp_path):  # per HL token: fade net == -long gross - 0.0029
def test_report_says_proxy_result_and_mae_only_for_shorts(tmp_path):
def test_resolution_from_results_only_and_verify_detects_edit(tmp_path):
```

- [ ] **Step 2:** Run `$PY -m pytest tests/test_news_event_studies_report.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `nes_report.py` and write the README.
- [ ] **Step 4:** Run `$PY -m pytest tests/ -q`. Expected: the whole root suite passes, with no new skips.
- [ ] **Step 5:** Commit: `git commit -m "news-event-studies: Phase 2 CLI, reports and resolution (#229)"`. Add the files first.
- [ ] **Step 6: Open the Phase 2 PR.**
  - Title: `news-event-studies: Part C Phase 2 returns and verdicts (#229)`.
  - Run a Codex Sol/high review, then merge when authorized.
  - This code must merge before Task 10's freeze, so the amendment can pin it.

### Task 10: Phase 1 run and manifest freeze (ops)

Not a code task. It needs Tasks 1–9 merged, with the merged commit called `SHA`.

- [ ] **Step 1: Install on the VPS.**
  - Run `git -C /Users/palmer/Work/Groove/Finance/Trading/master-trader archive SHA research/news_event_studies | ssh main-instance 'tar -x -C /home/ubuntu/master-trader'`.
  - Confirm that `/home/ubuntu/master-trader/research/news_archive/data/binance_cms_state.json` exists.
  - Add the install to the README log in the next PR.
- [ ] **Step 2: Upbit harvest on the Mac**, from a detached worktree at `SHA`:
  - Run `git -C /Users/palmer/Work/Groove/Finance/Trading/master-trader worktree add --detach .worktrees/229-part-c-run SHA`.
  - Run `$PY /Users/palmer/Work/Groove/Finance/Trading/master-trader/.worktrees/229-part-c-run/research/news_event_studies/nes_harvest.py upbit --out "$HOME/master-trader-harvest/upbit-2026-11" --host-label operator-mac`.
  - Expected: exit 0, meta shortfall 0, about 1 h.
  - On exit 3, wait at least 1 h and rerun; it resumes. A second block → stop and post on #229.
  - Then `scp -r "$HOME/master-trader-harvest/upbit-2026-11" main-instance:/home/ubuntu/master-trader/research/news_event_studies/data/upbit_raw`, and remove the worktree.
- [ ] **Step 3: Binance harvest on the VPS.**

```bash
cd /home/ubuntu/master-trader/research/news_event_studies
systemd-run --user --unit=nes-harvest --collect -p MemoryMax=1G -p CPUQuota=50% -p Nice=10 \
  -p IOSchedulingClass=idle --working-directory="$PWD" \
  /usr/bin/python3 nes_harvest.py binance --harvest 161,48 --scan 49 --out data/binance_raw
```

  - Watch `journalctl --user -u nes-harvest -f`. Expected: 15–21 h, exit 0.
  - Exit 4 (aborted) is never rerun: build anyway. The manifest then records `harvest_complete: false`, and Phase 2 resolves the affected studies as INCONCLUSIVE-by-data.
  - During the run, `news_archive.py status` shows no new `outage` gap for `binance_listing` or `binance_delisting`.
  - In `harvest_meta.json`:
    - catalog 49's `catalog_name` must be `Latest Binance News`. If it is not, stop and post on #229;
    - catalogs 161 and 48 must show `total_reported: true`.
- [ ] **Step 4: Build the manifests**, as `nes-build` with the same unit flags:
  - Run `/usr/bin/python3 nes_manifest.py build --cms data/binance_raw --upbit data/upbit_raw --out data/manifests --code-commit SHA`.
  - **Exit 5:** the build needs new rules. Add the classifier rules, each with one fixture per new title or body format, in a small PR. This is outcome-blind: only titles and bodies are read. Then merge, reinstall and rebuild.
  - Aliases are added only with a cited harvested notice id.
  - An O17 hit stops here for the operator.
- [ ] **Step 5: Read `build-report.txt`.** It holds counts only; no return exists yet. A study whose coverage already exceeds 0.20 is still frozen; Phase 2 records it mechanically.
- [ ] **Step 6: Freeze PR** on `claude/229-part-c-freeze`.
  - Append to each of the three entries' `amendments`:

```json
{"id": "A1-manifest-freeze", "date": "YYYY-MM-DD", "frozen_before_results": true,
 "manifest": "upbit-manifest.json", "manifest_sha256": "<hex>", "code_commit": "<SHA>",
 "counts": {"...": "manifest_counts(manifest, study)"},
 "harvest": {"binance_from": "vps", "upbit_from": "operator-mac", "catalog_49_monitoring_titles": 0},
 "note": "Phase 1 complete; no return computed."}
```

  - The delisting entry uses `delisting-manifest.json` and its hash; the long and the fade carry the same Upbit hash.
  - Run the Task 1 Step 6 check with `OWN = set(IDS)`, and the Task 1 tests.
  - Merge when authorized. **Phase 2 does not start before this merges.**

### Task 11: Phase 2 run and resolution (ops)

- [ ] **Step 1:** Read both `manifest_sha256` values from the merged `main`. Confirm that the VPS install is the amendment's `code_commit`.
- [ ] **Step 2: Compute both manifests.** For each, run as `nes-phase2-<name>` with the Task 10 unit flags:
  - Run `/usr/bin/python3 nes_report.py compute --manifest data/manifests/<file> --expect-sha256 <hex> --out data/results`.
  - Expected: exit 0, and `results-*.json` plus `report-*.md` for all three studies.
- [ ] **Step 3: Write the resolutions.**
  - `nes_report.py resolution --results data/results` prints the fragments.
  - Paste each into its entry's `resolution`, and set `status` to `"closed"` and `closed` to today.
  - Run `nes_report.py verify-resolution --prereg ft_userdata/preregistrations.json --results <copied results dir>`. Expected: exit 0.
  - Then run the Task 1 Step 6 check with `OWN = set(IDS)`.
- [ ] **Step 4: Resolution PR** on `claude/229-part-c-resolution`.
  - The body carries the three report texts (aggregates only, no raw data). Post them on #229.
  - A PASS authorizes only a separately preregistered paper forward monitor, which is not in this plan.
  - A FAIL closes that lane for this configuration.
  - An INCONCLUSIVE authorizes nothing, and any re-test is forward-only.
