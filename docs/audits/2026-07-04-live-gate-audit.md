# Live gate audit — 2026-07-04

**Task:** ROADMAP.md T-001, read-only. Preflight: `~/.local/bin/eb-agent-preflight worker/mt-gate-audit` → `OK 2026-07-04T15:47:41Z surface=worker/mt-gate-audit billing=claude-max` (exit 0).

**Scope discipline (D1):** No live switches, no strategy promotion, no fund movement, no config/key changes. Every command below is a read (`docker ps`, `docker exec ... cat`/`sqlite3 SELECT`/`PRAGMA`, `curl -I`, `ls`/`tar -t`). Nothing was restarted, deployed, or edited on the VPS. No secret values are reproduced (API keys, wallet keys, tokens all redacted or simply not read).

---

## 1. FundingFade live state (T-004 / `ff-gate-v2-review`)

Source: `docker exec ft-funding-fade sqlite3 /freqtrade/user_data/tradesv3.live.FundingFadeV1.sqlite`.

| Metric | Value |
|---|---|
| Closed trades (all-time, live) | 17 |
| Open trades | 0 |
| First open (all-time) | 2026-04-22 20:00:05 |
| Most recent close (all-time) | 2026-05-16 10:08:31 |
| Net realized P&L (all-time) | +$1.94 (wins $7.35 / losses $5.41) |

**Gate-v2 status — this is the number that matters, and it is NOT "17 of 30".**

Per `/etc/dokploy/.../ft_userdata/preregistrations.json` (`ff-gate-v2-review`, registered **2026-05-19**, review by **2026-08-17**, needs **≥30 closed trades counted from 2026-05-19 onward**): the bot's most recent close of any kind is **2026-05-16**, three days *before* the gate-v2 counting window opened. The 2026-07-03 daily health report (`/srv/lake/raw/trades/health-report.jsonl`) confirms this explicitly: `"[ff-gate-v2-review] review in 45d · 0/30 closed trades since 2026-05-19 — rules not yet evaluable"`.

**Headline: 0 of 30 closed trades since the gate-v2 window opened, ~44 days left until the 2026-08-17 date trigger (from 2026-07-04; the 2026-07-03 health report says "review in 45d" from its own timestamp).** At the live cadence observed since redeploy (zero trades in the last ~7 weeks — BTC has stayed below the strategy's SMA50/200 macro gate most of that time per the prereg notes), the 30-trade arm looks very unlikely to fire before the date trigger. The review on 2026-08-17 will most likely be a "date trigger, trade-count not evaluable" case per the pre-registered rule, same shape as the 2026-06-09 audit already flagged.

## 2. Fleet inventory — all `ft-*` and trading-adjacent containers

Source: `docker ps` (VPS) + `docker inspect --format '{{.Config.Entrypoint}}'`/`Cmd` per container + `grep dry_run` on the config file each container's own entrypoint references (not just whatever sits in the shared `configs/` directory — several strategy JSONs for bots that are NOT running also live in that directory and were excluded from this table).

| Container | Strategy | Config in use (from entrypoint) | `dry_run` | Notes |
|---|---|---|---|---|
| `ft-funding-fade` | FundingFadeV1 | `FundingFadeV1.live.json` | **false — LIVE, real money** | Confirmed 17 closed / 0 open (see §1) |
| `ft-cascade-fader` | CascadeFaderV1 | `CascadeFaderV1.json` | true (wallet $200) | Dry-run only |
| `ft-keltner-bounce` | KeltnerBounceV1 | `KeltnerBounceV1.json` | true (wallet $200) | Dry-run only |
| `ft-insiders-scalp` | KillersScalpV1 | `InsidersScalpV2.json` | true (wallet $200) | Dry-run only |
| `ft-killers-scalp` | KillersScalpV1 | `KillersScalpV1.json` | true (wallet $200) | Dry-run only |
| `ft-short-keltner-hl` | ShortKeltnerV2HL | `ShortKeltnerV2HL.json` | **true** (wallet 200) | See below — the only Hyperliquid Keltner config actually loaded by the running container |
| `ft-funding-refresh` | n/a (cron loop) | — | n/a | Not a trading bot; `download_funding_rates.py --incremental` every 4h |
| `ft-metrics-exporter` / `ft-prometheus` / `ft-dashboard` | n/a | — | n/a | Observability plumbing, no trading logic |

**ft-short-keltner-hl detail (D1 relevance):** the container's actual `Cmd` is `trade --strategy ShortKeltnerV2HL --config /freqtrade/user_data/configs/ShortKeltnerV2HL.json`, and that file has `"dry_run": true`. Two sibling files also exist on disk in the same directory — `ShortKeltnerV2HL-live.json` (`dry_run: false`, explicit `_WARNING` marking it a real-money Hyperliquid micro-test, "inert until walletAddress + privateKey are filled on the VPS copy") and `ShortKeltnerV2HL-testnet.json` (`dry_run: false` but Hyperliquid testnet/mock USDC) — but **neither is referenced by the running container's entrypoint**. Based on the inspected `Cmd` and the referenced config file's contents, the running process is configured for dry-run; this audit did not check for secondary config loads, env-var overrides, or runtime mutation not visible via `docker inspect`/`cat`, so treat it as "no live path found," not absolute proof of no live path. No cascade bot beyond `ft-cascade-fader` exists. **No additional running bot beyond FundingFade appears live with real money at the infra level checked** — consistent with D1, though this audit cannot claim to have exhausted every possible path.

## 3. Keltner activation gates (T-005)

Source: `docs/keltner_regime_activation_gates_2026-05-09.md` (rg for `gate` across `docs/` — this is the only dated gate-status table for KeltnerBounceV1 in the repo).

Last documented reading is **2026-05-09** (no newer dated re-check entry found in the repo during this audit, despite the doc's own "weekly automated check" cadence intent):

| Gate | 2026-05-09 status |
|---|---|
| G1 — BTC > daily SMA50, 14 consecutive days | ❓ unconfirmed at the time |
| G2 — BTC.D ≤0 slope OR <60% | ❌ FAIL (BTC.D 60.7%) |
| G3 — Alt Season Index ≥50 | ❌ FAIL (37) |
| G4 — F&G ≥50 for 7 consecutive days | ❌ FAIL (47) |
| G5 — 30-day clean dry-run track record from 2026-04-22 | ⏳ pending at the time |
| A3 anti-gate — abort policy committed | ❌ FAIL pending commit (companion doc `keltner_abort_gate_policy_2026-05-09.md` exists and reads as committed policy text, but no explicit "operator acknowledged" entry was found) |

**This audit did not re-derive G1–G4 from live market data** (BTC SMA/BTC.D/Alt Season/F&G are external market reads, not VPS state, and re-running that check is out of scope for a "read VPS + repo" audit). The daily health-report/prereg surface (`preregistrations.json`, §1 above) does not currently track the Keltner activation gates the way it tracks `ff-gate-v2-review`/`cascade-dry-run-gate-v2` — **gap**: Keltner gates have no automated daily surfacing, unlike the two dry-run preregistrations that were added specifically because gates "rotted silently" before. Per D1, this is moot for now regardless of gate status — Keltner does not go live.

Related, already-registered dry-run gate found in the same sweep — **`cascade-dry-run-gate-v2`** (T-006), registered 2026-06-09, review by 2026-09-30, needs ≥20 closed trades, PF≥1.0 and WR≥60% to continue:

- `ft-cascade-fader` dry-run sqlite: **2 closed trades**, PF 0.39 (wins $2.09 / losses $5.39), 1 win / 1 loss, both closed 2026-06-05.
- Per the 2026-07-03 health report: `0/20 closed trades since 2026-06-09` — the 2 trades above predate the gate-v2 registration date, same "clock reset" pattern as FundingFade's gate-v2. 89 days left to 2026-09-30 review. At this signal rate (2 candles fired fleet-wide since 2026-06-05, per `docs/cascade_gate_evaluation_2026-06-09.md`), the `<10 by review_by` frequency-anomaly clause is live risk, not a formality.

## 4. Backup receipts (T-007)

- Latest Mac-side backup: `/Users/palmer/backups/elder-brain-20260704-030001/master-trader-state.tar.gz`, **798,158 bytes**, mtime **2026-07-04 03:00:52** — i.e. covered by last night's nightly cron.
- `tar -tzv` listing confirms contents: `tradesv3.live.FundingFadeV1.online-backup.sqlite` (98,304 bytes) plus all 19 whitelist pairs' funding-rate feathers (refreshed 2026-07-04 00:14, consistent with the `ft-funding-refresh` 4h cadence) plus `shared_positions.json` and `fear_greed_history.json`.
- Nightly cadence looks intact going back through the visible backup history (`elder-brain-202606xx/master-trader-state.tar.gz` present for essentially every date checked).
- **Restore-drill receipt:** `docs/ROADMAP.md` evidence base states "the 2026-07-03 restore drill restored the master-trader SQLite artifact with `integrity_check: ok`; the drill noted 17 trades and did not prove a full scratch-VM rebuild." No standalone restore-drill doc exists under `master-trader/docs/` — this audit could not independently re-verify that drill's `PRAGMA integrity_check` output because it references a prior session's artifact, not a file left in this repo. Flagging as **unverified-by-this-audit, sourced from ROADMAP.md prose only**.

## 5. Grafana / CF Access (T-007)

```
$ curl -sI https://master-trader.grooveops.dev/
HTTP/2 302
location: https://grooveops.cloudflareaccess.com/cdn-cgi/access/login/master-trader.grooveops.dev?...
set-cookie: CF_AppSession=...
www-authenticate: Cloudflare-Access resource_metadata=...
```

Confirmed: unauthenticated request gets a 302 to the Cloudflare Access login page, exactly as expected. No anonymous access to Grafana.

## 6. Trade-webhook / lake feed (T-008, opportunistic check)

`docker logs trade-webhook` shows healthy `/healthz` 200s. `/srv/lake/raw/trades/` has per-bot JSONL files; `health-report.jsonl` updates daily (last entry 2026-07-03T23:00:02Z) and correctly reflects both bots' live state including the pre-registration countdowns quoted above — this is a stronger, more current source than the static gate docs and should be the first place future audits check.

---

## Command ledger

```
ssh main-instance docker exec ft-funding-fade sqlite3 tradesv3.live.FundingFadeV1.sqlite \
  "SELECT COUNT(*) FROM trades WHERE is_open=0;"                    # 17
  "SELECT COUNT(*) FROM trades WHERE is_open=1;"                    # 0
  "SELECT MAX(close_date) FROM trades WHERE is_open=0;"             # 2026-05-16 10:08:31.876
  "SELECT MIN(open_date) FROM trades;"                              # 2026-04-22 20:00:05.611
  "SELECT SUM(wins), SUM(abs(losses)), SUM(close_profit_abs) ..."   # 7.35 / 5.41 / +1.94

ssh main-instance docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
ssh main-instance docker inspect <container> --format '{{.Config.Cmd}}' | '{{.Config.Entrypoint}} {{.Args}}'
ssh main-instance docker exec <container> grep -i dry_run <config.json>   # per bot, see §2

ssh main-instance docker exec ft-cascade-fader sqlite3 tradesv3.dryrun.CascadeFaderV1.sqlite \
  "SELECT COUNT(*), SUM(wins), SUM(abs(losses)) FROM trades WHERE is_open=0;"

ssh main-instance cat /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata/preregistrations.json
ssh main-instance tail -c 3000 /srv/lake/raw/trades/health-report.jsonl

curl -sI https://master-trader.grooveops.dev/

ls -dt ~/backups/elder-brain-* | head -1
ls -la ~/backups/elder-brain-20260704-030001/master-trader-state.tar.gz
tar -tzvf ~/backups/elder-brain-20260704-030001/master-trader-state.tar.gz

rg -n 'gate' docs/ -i   # located keltner_regime_activation_gates_2026-05-09.md, keltner_abort_gate_policy_2026-05-09.md, cascade_gate_evaluation_2026-06-09.md

ssh main-instance docker logs trade-webhook --tail 5
ssh main-instance ls -lt /srv/lake/raw/trades/
```

Full raw receipt files (command + output pairs) captured at run time:
`/private/tmp/claude-501/-Users-palmer-Work-Dev-elder-brain/1f009005-5bb0-47d2-b589-bb3d2ea857ba/scratchpad/receipts-2026-07-04-mt-gate-audit/` and mirrored to the lake report receipts dir referenced below.

No secret values were reproduced in this report or its receipts (config files were grepped for `dry_run` only, never dumped in full; wallet/API key fields were not read). No container was restarted, redeployed, or reconfigured. D1 (no live switches) was not touched.
