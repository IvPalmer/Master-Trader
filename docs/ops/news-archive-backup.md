# News-archive backup

This runbook covers the backup of the PIT news archive (#229 Part B, spec
§5.2). The archive is irreplaceable by design: no vendor sells the same
point-in-time history, so a disk loss would reset its data clock to zero.

The job is `deploy/vps/backup_news_archive.py`. It is separate from the live-DB
backup (`backup_live_dbs.py`, [live-db-backups-google-drive.md](live-db-backups-google-drive.md)).
That job is all-or-nothing, so an archive failure inside it could break the
live trade-DB backup. The archive job imports that module's snapshot and prune
helpers and never modifies it.

## Contract

- **What:** `/home/ubuntu/master-trader/research/news_archive/data/archive.sqlite`,
  opened read-only and copied with SQLite's online backup API while the
  `news-archive` service keeps writing. Committed WAL frames are included. The
  copy is switched to `journal_mode=DELETE`, must pass `PRAGMA integrity_check`,
  and is gzipped.
- **Where:** one run is `/home/ubuntu/backups/news-archive/<UTC stamp>/`, holding
  `archive.sqlite.gz` and `MANIFEST.json`. The manifest records the source, the
  uncompressed size and sha256, the integrity result and a row count for every
  table. A run is staged in `.partial-<stamp>` and renamed only when complete; a
  failed run removes its staging.
- **Disjoint from the live backup:** the live job uses
  `/home/ubuntu/backups/master-trader` and `operator-drive:Master-Trader/backups`.
  The archive job never writes there, and the live `prune()` and the 03:45
  interim copy never see archive runs.
- **Retention:** every run of the last 7 days, the newest run of each ISO week
  for 8 weeks, and never fewer than the 7 newest. Unparseable directory names
  are never removed. Local retention runs after every successful snapshot,
  whatever the upload result, so a failing upload cannot grow the disk without
  bound.
- **Free space:** before a snapshot or a drill the job needs
  `15 GiB + 2 × (size(archive.sqlite) + size(archive.sqlite-wal))` free. The WAL
  counts because a long reader can hold back checkpoints, which makes the copy
  larger than `archive.sqlite` alone. Otherwise the run is `skipped`, exits 1,
  and writes nothing but `STATUS.json`.
- **Lock:** a non-blocking `flock` on `/home/ubuntu/backups/news-archive/.lock`,
  separate from the live job's lock. If it is held, the run prints `SKIP`, exits
  0 and leaves `STATUS.json` alone.
- **Priority:** `nice 10` and `ionice -c3` (idle), best effort.
- **Permissions:** the destination is 0755, each run 0700 (root only) and
  `STATUS.json` 0644, so the nightly health report, which runs as `ubuntu`,
  can read the status but not the data.
- **No immediate alert.** The nightly health report's `NEWS ARCHIVE` block is
  the channel: a failure is visible within a day.

`STATUS.json` keys (an absent key reads as `null`):

| key | value |
|---|---|
| `last_run_at` | ISO UTC time of the last snapshot run |
| `last_run_result` | `ok`, `failed` (the local snapshot failed), `skipped` (free space) or `upload_failed` |
| `last_run_error` | the error, or `null` |
| `latest_snapshot` | newest complete local stamp after the run, or `null` |
| `upload` | `{at, ok, error, stamp}` of the last upload attempt, or `null` |
| `local_drill`, `offhost_drill` | `{at, stamp, ok, error}` of the last drill, or `null` |

## Install (local leg, operator go-ahead)

Run on the VPS, from the root-owned Dokploy checkout. Never schedule through the
`ubuntu`-controlled `runtime` symlink: the job runs as root.

```bash
C=/etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code
sudo crontab -l > /home/ubuntu/backups/root-crontab.pre-229b
sudo install -d -o root -g root -m 0755 /home/ubuntu/backups/news-archive
sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py
sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --drill local
```

The first run must print an `OK` line and the drill must exit 0. Then add the
root crontab line, after the 03:15 live run and the 03:45 interim copy:

```cron
30 4 * * * /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_news_archive.py >> /var/log/master-trader-news-archive-backup.log 2>&1
```

Never pipe `sudo crontab -l` straight into `sudo crontab -`: if the read fails,
the pipe installs an empty crontab and the live-DB backup schedule is gone. Use
this function, which reads root's crontab into a file first, refuses to continue
unless the live backup line is there before and after the edit, shows the diff,
and only then installs:

```bash
set_archive_cron() {  # $1 = the new cron line, or '' to remove the job
  local now new
  now=$(mktemp) && new=$(mktemp) || return 1
  sudo crontab -l > "$now" || { echo "crontab -l failed; nothing changed"; return 1; }
  grep -q 'backup_live_dbs.py' "$now" || { echo "live backup line not read; nothing changed"; return 1; }
  grep -v 'deploy/vps/backup_news_archive.py' "$now" > "$new"
  [ -z "$1" ] || printf '%s\n' "$1" >> "$new"
  grep -q 'backup_live_dbs.py' "$new" || { echo "live backup line would be lost; nothing changed"; return 1; }
  diff "$now" "$new"
  sudo crontab "$new" && sudo crontab -l | grep -E 'backup_live_dbs|backup_news_archive'
  rm -f "$now" "$new"
}
set_archive_cron '30 4 * * * /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_news_archive.py >> /var/log/master-trader-news-archive-backup.log 2>&1'
```

The diff must show only the archive line, and the last command must list both jobs.

## Off-host leg (separate operator go-ahead)

`--upload` copies the new run to `operator-drive:Master-Trader/news-archive/.partial-<stamp>`
with `rclone copy --checksum --immutable`, verifies it with
`rclone check --one-way --download`, and only then renames it to `<stamp>` with
`rclone move --delete-empty-src-dirs`. So a failed or killed upload never looks like a run: retention
and the remote drill see complete runs only. It then lists the remote, purges
the stamps outside the retention above, and removes `.partial-*` left by earlier
failed uploads. An unparseable listing purges nothing.
It reuses the live backup's root-only `/etc/master-trader-backup/rclone.conf`
and its `operator-drive` remote, so there is no second OAuth and no copied token.

A failed upload exits 1, records `upload.ok = false` and
`last_run_result = upload_failed`, and keeps the new snapshot and the local
retention. The nightly report shows it as `off-host upload FAILED …`.

**The gate.** The off-host copy counts only once the latest **remote** restore
drill has passed. Until then the report line starts
`news-archive backup: local only`, whatever the uploads did. In order:

1. Prove a failed upload is visible:
   `sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --upload --rclone-config /nonexistent`
   must exit 1, and the report section must then show `local only; off-host upload FAILED …`.
2. Real upload: the same command with `--upload` only prints `OK … remote=N`. Then
   `sudo /usr/local/bin/rclone lsf operator-drive:Master-Trader/news-archive --dirs-only --config /etc/master-trader-backup/rclone.conf`
   must list the stamp.
3. Remote drill: `sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --drill remote`
   exits 0, and the report section must then show `off-host OK`.
4. Swap in the `--upload` cron line with `set_archive_cron` (see Install):

```bash
set_archive_cron '30 4 * * * /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_news_archive.py --upload >> /var/log/master-trader-news-archive-backup.log 2>&1'
```

## Restore drill

```bash
sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --drill local
sudo /usr/bin/python3 $C/deploy/vps/backup_news_archive.py --drill remote
```

A drill takes the same lock as a run and makes no snapshot. It restores the
newest local run (or the newest remote stamp: its `MANIFEST.json` first, then
`archive.sqlite.gz`, with `rclone copyto`) into a temporary
`news-archive-drill-*` directory. It needs `15 GiB + 2 × the snapshot's size`
free there, sized from the manifest, so it also works when the live database is
gone. It gunzips the copy, stopping at the manifest's size, and requires its
sha256 to match the manifest,
`PRAGMA integrity_check` to return `ok`, and every table's row count to equal
the manifest's. It records only `local_drill` or `offhost_drill` in
`STATUS.json`; a failure names the check that failed and exits 1.

A real restore is a manual operator step: stop the service
(`systemctl --user stop news-archive`), keep the damaged database aside, gunzip
the chosen `archive.sqlite.gz` to `research/news_archive/data/archive.sqlite` as
`ubuntu`, remove any stale `-wal`/`-shm`, and start the service again. On start
it records a `restart` gap from the restored copy's last OK poll to the restart,
so the PIT rule still marks the hole.

## Rollback

Remove only this job's line with `set_archive_cron` (see Install), so any later
change to root's crontab survives:

```bash
set_archive_cron ''
sudo crontab -l | diff /home/ubuntu/backups/root-crontab.pre-229b - && echo "back to the pre-install crontab"
```

The saved `root-crontab.pre-229b` stays as the record of the pre-install state;
restore it whole only if nothing else changed since. The snapshots stay. The report then shows `no run for …` once the last run is
more than 26 h old.

## Install log

| date (UTC) | commit | what | result |
|---|---|---|---|
| 2026-11-04 02:50-02:52 | `5f70a6f` via release #236 (`2cc1e09` on `vps-deploy`) | Part B code deployed (fast-forward, no container restarted) and local backup leg installed: root cron `30 4 * * *` for `backup_news_archive.py`; first snapshot `20261104T025111Z`. | Source: #229 "Part B deployed" comment, not re-verified here. |
| 2026-11-04 03:06-03:24 | `2cc1e09` (code unchanged) | Off-host leg enabled: cron line gained `--upload`; real upload `20261104T032116Z`, `rclone check` 0 differences; remote restore drill OK. | Source: #229 "off-host leg enabled" comment, not re-verified here. |
| 2026-11-05 19:00 (verified read-only) | `3caee02` (later `vps-deploy` release, #243) | Re-check on the VPS. Root crontab has `30 4 * * * /usr/bin/python3 .../deploy/vps/backup_news_archive.py --upload >> /var/log/master-trader-news-archive-backup.log 2>&1`. Snapshots `20261104T043001Z` and `20261105T043001Z` exist; the log shows `OK` for both scheduled 04:30 UTC runs, with rclone `0 differences` on 2026-11-05. `backup_news_archive.py` and `news_archive_report.py` on the VPS are byte-identical to `5f70a6f`. `strategy_health_report.py` differs from `5f70a6f` because of the later release, so it was not compared. | Verified. No systemd timer is involved (the only user timer is `launchpadlib-cache-clean`). Not verified: the 23:00 report text. |
