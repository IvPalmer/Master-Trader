# Part C event studies (#229)

Three preregistered, retrospective event studies over announcements dated
2023-01-01 to 2026-10-31 UTC. The design is in
[the news-archive spec §6](../../docs/superpowers/specs/2026-11-03-news-archive-design.md).
The frozen rules are the entries in `ft_userdata/preregistrations.json`:

- `binance-delisting-reaction-2026-11`: Binance delisting and monitoring-tag notices, short, Hyperliquid only.
- `upbit-krw-listing-reaction-2026-11`: Upbit KRW-market additions, long, Hyperliquid or Binance spot.
- `upbit-krw-listing-fade-2026-11`: the same Upbit events, short, Hyperliquid only. It shares the long's manifest.

A PASS authorizes only a separately preregistered paper forward monitor. Nothing here
deploys, sizes or allocates anything. Every result is a **proxy result**: returns come
from Binance 1m prices, not venue fills.

## Phases

1. **Phase 1, outcome-blind.** `nes_harvest.py` collects the notices. `nes_manifest.py`
   turns them into two manifests, using Hyperliquid funding-record timestamps and
   data.binance.vision file existence as venue evidence. No price is read. Each
   manifest's SHA-256 is frozen by a prereg amendment before Phase 2.
2. **Phase 2.** `nes_report.py compute` downloads only the candidate events' 1m files.
   It writes `results-<study>.json` and `report-<study>.md`, and the resolution is
   written into the prereg mechanically from the results.

Modules: `nes_util` (constants, hashing), `nes_classify` (titles and bodies),
`nes_venues` (Hyperliquid `fundingHistory`, Binance file probes), `nes_klines`,
`nes_returns` (O2–O4, criteria, verdict), `nes_report`.

## Probe results (Task 1, posted on #229)

- Hyperliquid `candleSnapshot` returns only the most recent ~5,000 candles (1 h back to about 2026-04). Eligibility therefore uses hourly `fundingHistory` by coin name (C1 option A, spec §11 call 14).
- **Delisted coins:** `fundingHistory` by name works for coins no longer in today's `meta`. For a name Hyperliquid never listed, it answers HTTP 500 with body `null`, which counts as no records only for such a name (O5).
- Upbit's notice detail returns the body under `data.body`. The trading start is usually a table cell without a year (`10월 27일 16시 40분 예정`), hence O10's table and nearest-year rules.
- Binance catalog 161 reports a `total`. Upbit's Cloudflare blocks the VPS IP (HTTP 403) and rate-limits fast page requests (error 1015 at 1.5 s), so the Upbit harvest runs from the operator's Mac at 10 s per page.
- data.binance.vision answers a missing daily file with 404. A 403 is a denial and stops the run; it never counts as absence.

## O17 decision (2026-11-04)

The first build (main 3c77081) stopped on O17: catalog 49 ("Latest Binance News")
held 27 monitoring-tag titles in the window, none of them in catalog 161. The operator
chose option A (amendment `A1-o17-catalog-49` on the delisting entry). Catalog 49 is now
harvested in full like 161 and 48, and its titles that contain "Monitoring Tag" are
delisting-study notices. The delisting harvest is complete only when 161 and 49 both
are, and their shortfalls add up (O13). Title rulings made before the freeze are
amendments `A2-phase1-title-rules` (delisting) and `A1-phase1-title-rules` (Upbit).

## O10 hour-only clock (2026-11-05)

The build from 89dfe17, after catalog 49 was harvested in full (4481 of 4481 articles), left
86 Upbit additions with no parseable trading start. 80 of their start cells read
`M월 D일 H시 예정`, an hour with no minutes, which O10's clock list did not cover. Those
manifests were discarded before any freeze. Amendment `A2-o10-hour-clock` on both Upbit
entries reads `H시` alone as minute 00; on the corpus it leaves 5 events with no start.

## Quarantine

The 2018–2022 exploratory results on the VPS (`research/news_exploratory_2026-11/`)
are the hypothesis source only. None of their numbers is used, compared or reported here.

## Network exception on the Mac

The Mac checkout is otherwise for source edits and network-free tests: no Docker, no
servers. The one exception is the Upbit harvest, which must run from the operator's Mac.

## Commands

Binance harvest (VPS, shared Binance CMS limiter of the running archive):

```bash
cd /home/ubuntu/master-trader/research/news_event_studies
systemd-run --user --unit=nes-harvest --collect -p MemoryMax=1G -p CPUQuota=50% -p Nice=10 \
  -p IOSchedulingClass=idle --working-directory="$PWD" \
  /usr/bin/python3 nes_harvest.py binance --harvest 161,48,49 --out data/binance_raw
```

The 2026-11-04 run harvested 161 and 48 and scanned 49 (`nes-harvest`); catalog 49 was
then harvested in full into the same directory (`nes-harvest-49`, `--harvest 49`).

Upbit harvest (operator's Mac, from a detached worktree at the merged commit), then copy:

```bash
python3 research/news_event_studies/nes_harvest.py upbit --out "$HOME/master-trader-harvest/upbit-2026-11" --host-label operator-mac
scp -r "$HOME/master-trader-harvest/upbit-2026-11" main-instance:/home/ubuntu/master-trader/research/news_event_studies/data/upbit_raw
```

Phase 1 manifests (VPS; exit 5 = titles need a decision, exit 6 = a venue source stopped the build):

```bash
systemd-run --user --unit=nes-build --collect -p MemoryMax=1G -p CPUQuota=50% -p Nice=10 \
  -p IOSchedulingClass=idle --working-directory="$PWD" \
  /usr/bin/python3 nes_manifest.py build --cms data/binance_raw --upbit data/upbit_raw --out data/manifests --code-commit SHA
```

Phase 2, one unit per manifest, only after the freeze amendment is merged (exit 2 = SHA
mismatch, exit 3 = files not yet published):

```bash
systemd-run --user --unit=nes-phase2-delisting --collect -p MemoryMax=1G -p CPUQuota=50% -p Nice=10 \
  -p IOSchedulingClass=idle --working-directory="$PWD" \
  /usr/bin/python3 nes_report.py compute --manifest data/manifests/delisting-manifest.json \
  --expect-sha256 HEX --out data/results --code-commit SHA
/usr/bin/python3 nes_report.py resolution --results data/results
/usr/bin/python3 nes_report.py verify-resolution --prereg ../../ft_userdata/preregistrations.json --results data/results
```

Raw harvests, manifests' inputs, klines and results stay on the VPS under `data/`
(gitignored). Only manifest SHA-256s and the resolutions are committed.

## Install log

| date | commit | by |
|---|---|---|
| 2026-11-04 | 0f29d85 (harvesters) | Claude (Part C session) |
| 2026-11-04 | 3c77081 (main: first build, stopped by O17) | Claude (Part C session) |
| 2026-11-05 | 89dfe17 (main: option A build, discarded for the O10 clock gap) | Claude (Part C session) |
