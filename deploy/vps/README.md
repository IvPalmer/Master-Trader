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

The health-report line runs an installed copy of `deploy/vps/run-health-report.sh`, not the file
in `runtime/`. Re-copy it after that script changes; the copy on the host was older than the repo
version on 2026-10-02. The warden line is documented in `services/killers-receiver/warden/README.md`.
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
cp ~/Work/Dev/master-trader/deploy/vps/run-health-report.sh \
   /home/ubuntu/master-trader/run-health-report.sh
chmod +x /home/ubuntu/master-trader/run-health-report.sh
( crontab -l 2>/dev/null | grep -v master-trader/run-health-report
  echo '0 23 * * * /home/ubuntu/master-trader/run-health-report.sh'
) | crontab -

# Rsync research data from prior host (skip if starting fresh)
# rsync -a old-host:/home/ubuntu/master-trader/research/ /home/ubuntu/master-trader/research/
```

## Health report

`run-health-report.sh` runs `strategy_health_report.py` from `runtime/ft_userdata/`
(Dokploy-managed code, auto-updates on git push). It pulls rotated REST creds
from `ft-keltner-bounce` via `docker exec`. It posts to trade-webhook on the host
loopback, `WEBHOOK_URL=http://localhost:8088/freqtrade/event`. That is also the
default of every report script that posts to Telegram: they all go through
`ft_userdata/webhook_notify.py`, which reads `WEBHOOK_URL` and sends JSON.

Test on demand:
```bash
/home/ubuntu/master-trader/run-health-report.sh --stdout
```

## Mac side

`~/Work/Dev/master-trader/` holds code + tracked configs/strategies only (~20 MB).
All bulk research data lives only on VPS; backtests run on VPS.

## Backups

`backup_live_dbs.py` (#99) backs up every `tradesv3.live.*.sqlite` in the
`ft_user_data` volume and every `*.sqlite` in `killers_receiver_state`, plus
`/home/ubuntu/killers-bot/state.sqlite` when it exists. The retired
`insiders_receiver_state` volume (#216) is no longer backed up; its last
snapshots stay in the backup history. The receiver databases tie each open position to its source signal,
posted stop and targets and cannot be rebuilt from the exchange. Dry-run
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
