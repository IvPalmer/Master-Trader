# Live SQLite backups to Google Drive

This runbook covers GH #99. The local root cron has run daily at 03:15 UTC
since 2026-10-09; a 2026-10-13 check found 25 files and an `OK` result. That
local receipt is not evidence that the rclone/off-host changes on `main` have
been released or that Google Drive uploads are configured.

## Contract

The daily job takes WAL-consistent online copies of:

- all `tradesv3.live.*.sqlite` files in the Dokploy `ft_user_data` volume;
- all `*.sqlite` files in `killers_receiver_state`;
- all `*.sqlite` files in `insiders_receiver_state`;
- `/home/ubuntu/killers-bot/state.sqlite` when the observer database exists.

It never stops or restarts a bot. Each standalone copy must pass SQLite
`PRAGMA integrity_check`, is compressed with gzip, and is recorded in a SHA-256
manifest. The completed run is copied to the dedicated
`operator-drive:Master-Trader/backups/<UTC stamp>` directory and a downloading
`rclone check` must succeed. The same tiered retention applies locally and
remotely: every run for 30 days, the newest run of each ISO week for 8 weeks,
and never fewer than the 7 newest. An unparseable remote directory name is
never removed.

The script deliberately excludes dry-run databases, exporter state,
credentials, configs and logs. A failure keeps the new local snapshot, does
not run local retention, exits non-zero and alerts through trade-webhook.

## Approval boundary

Do not perform these off-host setup steps merely because the PR is merged. The
operator must separately approve releasing/configuring the rclone version and
must personally complete Google OAuth. Do not copy an existing rclone
configuration, browser profile, refresh token or another person's Google token.
The agent does not receive or paste the OAuth result. No bot restart is part of
this procedure.

## Exact off-host setup steps (operator-approved window only)

Run on the VPS. Root is required because Docker volume directories are
root-readable. Use the root-owned Dokploy checkout path; do not schedule through
the `ubuntu`-controlled `runtime` symlink.

```bash
sudo apt-get update
sudo apt-get install --yes rclone sqlite3
sudo install -d -o root -g root -m 0700 /etc/master-trader-backup
sudo install -d -o root -g root -m 0700 /home/ubuntu/backups/master-trader
sudo /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_live_dbs.py --list
```

Confirm that `--list` contains only the expected live Freqtrade databases, the
two receiver databases and the observer database. Do not proceed if a required
volume is missing or an unexpected file is present.

### Operator-owned Google Drive authorization

The operator creates a new remote named `operator-drive`; it is dedicated to
this backup and uses the operator's own Google account. Start the interactive
configuration with the final config path from a private terminal:

```bash
sudo /usr/local/bin/rclone config --config /etc/master-trader-backup/rclone.conf
```

Rclone's shared Google client ID is retired during 2026, so create an
operator-owned client first; do not leave the ID and secret blank. In the
Google Cloud console, create a dedicated project, enable **Google Drive API**,
configure the OAuth consent screen for the operator, add
`https://www.googleapis.com/auth/drive.file` under Data Access, and create an
OAuth client of type **Desktop app**. Keep the client ID and secret in the
private terminal only. Rclone's maintained instructions are at
<https://rclone.org/drive/#making-your-own-client-id>.

In `rclone config`, choose `n` (new remote), name it `operator-drive`, choose
Google Drive, enter that dedicated client ID and secret, choose the
least-privileged `drive.file` scope, leave the root folder ID blank, leave the
service-account file blank, and do not configure a Shared Drive unless that is
the chosen destination. On a headless VPS, answer `n` to browser-based automatic
authentication and run the exact `rclone authorize` command printed by rclone
on the operator's own browser-equipped computer. This is rclone's documented
headless flow: <https://rclone.org/remote_setup/>. Paste its result directly
into the private rclone prompt. No token belongs in shell history, an issue, a
PR, a chat, or the repository.

Lock down and validate the resulting config without printing it:

```bash
sudo chown root:root /etc/master-trader-backup/rclone.conf
sudo chmod 0600 /etc/master-trader-backup/rclone.conf
sudo /usr/local/bin/rclone mkdir operator-drive:Master-Trader/backups --config /etc/master-trader-backup/rclone.conf
sudo /usr/local/bin/rclone lsd operator-drive:Master-Trader --config /etc/master-trader-backup/rclone.conf
```

The dedicated client ID avoids the retired shared client and isolates its API
quota. The refresh token stays only in the root-readable config file.

### First run and schedule

The first command below creates and uploads a real backup. Run it only after the
operator explicitly approves that action:

```bash
sudo /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_live_dbs.py --rclone /usr/local/bin/rclone
sudo find /home/ubuntu/backups/master-trader -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
sudo /usr/local/bin/rclone lsf operator-drive:Master-Trader/backups --dirs-only --config /etc/master-trader-backup/rclone.conf
```

After the first upload and restore drill succeed, replace the existing local-only
03:15 UTC cron entry with the released off-host command:

```bash
( sudo crontab -l 2>/dev/null | grep -v 'deploy/vps/backup_live_dbs.py'
  echo '15 3 * * * /usr/bin/python3 /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/deploy/vps/backup_live_dbs.py --rclone /usr/local/bin/rclone >> /var/log/master-trader-backup.log 2>&1'
) | sudo crontab -
sudo crontab -l | grep 'deploy/vps/backup_live_dbs.py'
```

Record the run stamp, script commit, successful `OK` log line, Drive directory,
restore-drill result and installed cron line on GH #99. A merged PR alone is not
deployment evidence.

## Non-destructive restore drill

This drill downloads one receiver backup from Drive to a new root-only scratch
directory. It does not touch a volume or container and does not restart bots.
Replace `<stamp>` with the newest remote run and compare the printed digest to
that file's `sha256` value in `MANIFEST.json`.

```bash
sudo install -d -o root -g root -m 0700 /home/ubuntu/backups/restore-drill
sudo /usr/local/bin/rclone copyto operator-drive:Master-Trader/backups/<stamp>/MANIFEST.json /home/ubuntu/backups/restore-drill/MANIFEST.json --config /etc/master-trader-backup/rclone.conf
sudo /usr/local/bin/rclone copyto operator-drive:Master-Trader/backups/<stamp>/killers_receiver_state/receiver-hyperliquid.sqlite.gz /home/ubuntu/backups/restore-drill/receiver-hyperliquid.sqlite.gz --config /etc/master-trader-backup/rclone.conf
sudo gzip --test /home/ubuntu/backups/restore-drill/receiver-hyperliquid.sqlite.gz
sudo sh -c 'gzip -dc /home/ubuntu/backups/restore-drill/receiver-hyperliquid.sqlite.gz > /home/ubuntu/backups/restore-drill/receiver-hyperliquid.sqlite'
sudo sha256sum /home/ubuntu/backups/restore-drill/receiver-hyperliquid.sqlite
sudo sqlite3 /home/ubuntu/backups/restore-drill/receiver-hyperliquid.sqlite 'PRAGMA integrity_check;'
```

Expected final output is exactly `ok`. Remove only this drill directory after
recording the receipt:

```bash
sudo rm -rf -- /home/ubuntu/backups/restore-drill
```

An actual restore into a Docker volume is a separate Tier 5 operation under
[UPDATING-WITHOUT-BREAKING-BOTS](UPDATING-WITHOUT-BREAKING-BOTS.md). It requires
draining open positions, stopping the owning container, removing stale
`-wal`/`-shm` files, restoring ownership, and separately authorizing the start.
Never overwrite a database that a running bot or receiver has open.
