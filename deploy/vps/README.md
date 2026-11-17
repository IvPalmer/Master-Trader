# VPS deployment — Elder Brain (Oracle Cloud, sa-saopaulo-1)

Host: `ubuntu@100.96.225.124` (tailnet) / `159.112.191.120` (public).
Single canonical project root: `/home/ubuntu/master-trader/`.

## Layout

```
/home/ubuntu/master-trader/
├── README.md                       # written at bootstrap, see below
├── runtime -> /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code
│                                   # Dokploy-managed git checkout (vps-deploy branch)
├── research/                       # 9 GB OHLCV + backtest outputs (rsynced from Mac)
│   ├── data/, logs/, models/, hyperopt_results/, backtest_results/
│   ├── databases/, notebooks/, fear_greed_history.json
│   └── analysis/, meta_labeling/, engine_results/, evolution/
├── state/                          # health-report state + logs (writable, persistent)
│   ├── user_data/                  # FT_DIR/user_data (DB_DIR placeholder; unused on VPS)
│   ├── logs/                       # FT_DIR/logs
│   └── health_report_state.json
└── run-health-report.sh            # cron wrapper, source: deploy/vps/run-health-report.sh
```

Live runtime is owned by Dokploy (UI: `compose-bypass-mobile-port-fbk1m6`).
The 11 services of `ft_userdata/docker-compose.prod.yml`: bots `ft-keltner-bounce` (8095),
`ft-funding-fade` (8096), `ft-oi-trend-pullback` (8102), `ft-killers-scalp` (8099),
`ft-short-keltner-hl-live` (8103); receiver `killers-receiver` (8089); `ft-hl-gateway`,
`ft-funding-refresh`, `ft-metrics-exporter` (9090), `ft-prometheus` (9091), and `ft-dashboard`. The dashboard is
served by Traefik at the public URL; every published port binds `127.0.0.1`. trade-webhook
(`127.0.0.1:8088`) runs from its own compose file, `services/trade-webhook/`.

Host scheduled jobs (`crontab -l` as `ubuntu`, checked 2026-10-02):

```
0 23 * * * /home/ubuntu/master-trader/run-health-report.sh
*/5 * * * * docker exec killers-receiver python3 /app/warden/risk_warden.py >> /home/ubuntu/killers-warden.log 2>&1
```

The health-report line runs `/home/ubuntu/master-trader/run-health-report.sh`, a symlink to
`runtime/deploy/vps/run-health-report.sh`, so the wrapper ships with each `vps-deploy` release.
It used to be a copied file: the copy was older than the repo on 2026-10-02, and again by
2026-11-03, when it still sent one bot's API pair to every bot and all but one answered 401 (#219). The warden line is documented in
`services/killers-receiver/warden/README.md`.
Two systemd timers (`master-trader-retention-shadow`, `master-trader-retention-accounting`, units
in `research/profit_retention/systemd/`) run the read-only profit-retention collectors.
`ft_userdata/automation_scheduler.sh` is not installed and refuses to run (#100).
Separately, root's crontab has run `deploy/vps/backup_live_dbs.py` daily at
03:15 UTC since 2026-10-09. It was checked on 2026-10-13: the local backup had
25 files and reported `OK`. This confirms the local schedule only; it does not
show that the rclone/off-host version from `main` has been released or configured.

Live trade DB lives in docker volume
`compose-bypass-mobile-port-fbk1m6_ft_user_data` (NOT in `runtime/`).

## Bootstrap a fresh VPS

After Dokploy is up and the master-trader compose deployed:

```bash
ssh ubuntu@<host>
mkdir -p /home/ubuntu/master-trader/{research,state}
ln -sfn /etc/dokploy/compose/<compose-id>/code /home/ubuntu/master-trader/runtime

# Drop wrapper + cron
ln -sfn /home/ubuntu/master-trader/runtime/deploy/vps/run-health-report.sh \
   /home/ubuntu/master-trader/run-health-report.sh
( crontab -l 2>/dev/null | grep -v master-trader/run-health-report
  echo '0 23 * * * /home/ubuntu/master-trader/run-health-report.sh'
) | crontab -

# Rsync research data from prior host (skip if starting fresh)
# rsync -a old-host:/home/ubuntu/master-trader/research/ /home/ubuntu/master-trader/research/
```

## Health report

`run-health-report.sh` runs `strategy_health_report.py` from `runtime/ft_userdata/`
(Dokploy-managed code, auto-updates on git push). It reads each bot's own REST
pair from that bot's container via `docker exec` and exports it as `FT_API_USER_<SLUG>` /
`FT_API_PASS_<SLUG>`, which `api_utils` picks by loopback port. It posts to trade-webhook on
the host loopback, `WEBHOOK_URL=http://localhost:8088/freqtrade/event`. That is also the
default of every report script that posts to Telegram: they all go through
`ft_userdata/webhook_notify.py`, which reads `WEBHOOK_URL` and sends JSON.

Test on demand:
```bash
/home/ubuntu/master-trader/run-health-report.sh --stdout
```

The report's last block, `NEWS ARCHIVE` (#229), reads the PIT news archive read-only:
source freshness, coverage gaps and the archive backup's `STATUS.json`. Paths come from
`NEWS_ARCHIVE_DB` and `NEWS_ARCHIVE_BACKUP_STATUS` (defaults under `/home/ubuntu`). The
section never changes the report's exit status. `--stdout` also saves the trend state
(`health_report_state.json` under `FT_DIR`), so back it up and restore it around a manual run.
Note: trade-webhook truncates `status` events to 200 characters before Telegram, so the
full report is read in `research/logs/health_report.log`.

## Mac side

`~/Dev/finance/trading/master-trader/` holds code + tracked configs/strategies only (~20 MB).
All bulk research data lives only on VPS; backtests run on VPS.

## Backups

`backup_live_dbs.py` (#99) backs up every `tradesv3.live.*.sqlite` in the
`ft_user_data` volume and every `*.sqlite` in `killers_receiver_state`, plus
`/home/ubuntu/killers-bot/state.sqlite` when it exists. The retired
`insiders_receiver_state` volume (#216) is no longer backed up; its last
snapshots stay in the backup history. The receiver databases tie each open position to its source signal,
posted stop and targets and cannot be rebuilt from the exchange. The ended-epoch
records in `ft_user_data/epoch-records/` (#277) are copied as they are. Dry-run
databases and unrelated state are intentionally excluded.

Each database is opened read-only and copied with SQLite's online backup API,
which takes a consistent snapshot without stopping the bots. The copy has to
pass `PRAGMA integrity_check` and is then gzipped. One run produces
`/home/ubuntu/backups/master-trader/<UTC stamp>/` with a `MANIFEST.json`
(source, size, sha256 and integrity result). It then copies that run to the
operator's Google Drive with rclone, checks the remote files against the local
copy, and applies the same retention to both locations: every run for 30 days,
the newest run of each ISO week for 8 weeks, and a floor of 7 runs. A failure
exits non-zero and posts a `[db-backup] WARN` line through trade-webhook.

Before 2026-10-09 there was no scheduled backup of this state. Dokploy had no
backup, volume backup or destination configured when checked on 2026-10-02.
`ft_userdata/automation_scheduler.sh`'s 02:00 line reads `~/ft_userdata`, which
holds no live database, and is not installed. A cloud-level boot-volume backup
policy cannot be seen from the host and remains unverified.

Off-host setup, operator-owned Google OAuth, cron replacement, verification and
the non-destructive restore drill are in
[live-db-backups-google-drive.md](../../docs/ops/live-db-backups-google-drive.md).
Releasing the rclone version and authorizing Drive require separate operator
approval; merging this code does not change the running VPS.

The PIT news archive has its own job, `backup_news_archive.py` (#229), so an archive
failure can never break this one: root cron at 04:30 UTC, destination
`/home/ubuntu/backups/news-archive/`, 7 daily plus 8 weekly copies, its own lock and a
15 GiB free-space floor. Its off-host leg is opt-in and counts only after a remote
restore drill passes. See [news-archive-backup.md](../../docs/ops/news-archive-backup.md).

## Archive before changing a bot's mode or deleting it

Freqtrade opens one SQLite per mode, and its API serves only the current one. A
bot moved to dry-run, retired or deleted therefore stops serving its live
trades, and the dashboard would drop its realized P&L, drawdown and trade count
from the fleet totals (#277). `archive_bot_epoch.py` freezes the ended epoch
into `epoch-records/<record id>.json` on the `ft_user_data` volume. The
dashboard shows it as a stopped bot and keeps counting it; it never recomputes
a record.

1. Let the bot go flat. The script refuses a database with an open trade.
2. Change the bot's mode (or stop its container) so that it no longer writes the
   live database. The script refuses a `tradesv3.*` source that is still the
   container's `FREQTRADE__DB_URL`. Until the record exists, the dashboard shows
   an amber warning that the live database has closed trades nobody owns.
3. As root, from the Dokploy checkout, run the script with the epoch's half-open
   window `[--start-ms, --end-ms)`. The example is in its docstring. It takes a
   verified `archive-<record id>.sqlite` backup first, serializes the trades with
   Freqtrade's own `Trade.to_json()`, and builds the record inside `ft-dashboard`.
   Hyperliquid fills are reconciled there, once. If that backup file already
   exists, the script reuses it and takes no new one (see below).
4. Check the printed totals. The Freqtrade raw P&L must already match SQLite; the
   corrected total is the one the dashboard shows.
5. Only then remove the bot from the dashboard's `BOTS`. A bot that is no longer
   there needs `--bot-config`, and a deleted container needs any running FT
   container as `--ft-container`.

Records are written once, mode 0444, and never replaced. A record that is
malformed, or that claims a trade another record owns, is rejected whole and
shown as a warning. To correct one, move the file out of `epoch-records/` and
archive the epoch again.

**After an aborted run.** A run that stopped after step 3 leaves
`archive-<record id>.sqlite` on the volume, and the next run reuses that snapshot
instead of taking a new one. If the bot traded or went flat since, the record
would be built from the old state: the script refuses a snapshot with an open
trade, and trades closed after it would belong to no epoch (the dashboard's amber
warning). Before you run the script again, delete that file as root, unless it is
a backup you made on purpose.

**An earlier epoch of a bot that keeps running live** (as for
`fundingfade.live-v1`). When the bot still writes the database the epoch is in,
step 2 cannot hold. Make the backup yourself while the bot is flat (the script
refuses a backup with an open trade), with the SQLite backup API the script uses:

```bash
sudo python3 -c 'import sys; sys.path.insert(0, "deploy/vps"); from pathlib import Path; from backup_live_dbs import backup_sqlite; backup_sqlite(Path(sys.argv[1]), Path(sys.argv[2]))' \
    /var/lib/docker/volumes/compose-bypass-mobile-port-fbk1m6_ft_user_data/_data/tradesv3.live.<strategy>.sqlite \
    /var/lib/docker/volumes/compose-bypass-mobile-port-fbk1m6_ft_user_data/_data/archive-<record id>.sqlite
```

Pass that file name as `--source-db`. An `archive-*` source is treated as a
backup already, so the script skips its "bot is off this DB" check, and nothing
else enforces it. Two things are then up to you: end the window (`--end-ms`)
where the running epoch starts, so the record takes none of the running bot's
trades, and keep the bot in `BOTS` (skip step 5).

## Funded accounts with no live bot (`RETAINED_ACCOUNTS`)

Demoting the last live bot on an account leaves its money there. Accounts in
`RETAINED_ACCOUNTS` (`ft_userdata/metrics_exporter.py`) stay valued, in the
dashboard's account equity and in the fleet breaker's scope with no live bot
(#277). Today that is `hyperliquid-killers`, read through the gateway's
`/account/killers`.

**A valuation failure suspends the breaker for every live bot.** If the exporter
cannot value a retained account (the request fails, or the mark is older than
90 s), the breaker's equity is incomplete and it is not evaluated at all, for the
Binance bots too: a partial total would look like a drawdown. This fails closed
and is the same behaviour as when Killers was live. After 15 minutes
`fleet-breaker-watch` pages "Circuit breaker not evaluated"; fix the valuation
(gateway, Hyperliquid API) rather than removing the account to get the breaker
back.

**Only an account valued without a bot can be retained.** `binance-spot` reads
its balance through a bot's API, and `hyperliquid-upbit-fade` needs a bot's
wallet. With no live bot their equity cannot be read. The exporter refuses to
start when `RETAINED_ACCOUNTS` holds an account outside `VALUED_WITHOUT_A_BOT`
(#280). Supporting another account means writing and testing an adapter that
needs no member bot first.

**Removing an account once its funds have moved:**

1. Move the funds and record each leg in `ft_userdata/account_transfers.json`
   (see [HYPERLIQUID-REQUESTS-AND-RECOVERY.md](../../docs/ops/HYPERLIQUID-REQUESTS-AND-RECOVERY.md)).
   A recorded withdrawal shifts the peak by the cash flow, so it is not a loss.
2. Check that the account is empty: its equity in `account_health.json` or on the
   dashboard's Portfolio tab.
3. Check the breaker is evaluating (`fleet-breaker-watch` is not firing). The
   leaving account's equity is the one from the last evaluated cycle.
4. Remove the account from `RETAINED_ACCOUNTS` in a PR and deploy the exporter
   with `--no-deps`.
5. On its first cycle the exporter logs `Breaker scope changed (left
   hyperliquid-killers ...)` and lowers the peak by the account's last equity.
   The dollar drawdown is unchanged. The percentage rises, because the same
   dollars are measured against a smaller peak: $10 is 2.4% of $410 but 3.2% of
   $310. Check it against the 10% threshold before you deploy. Money still in the
   account would leave the breaker and the account equity with it.

The account then drops out of the dashboard's account equity. The stopped
epoch's record keeps counting in realized P&L.
