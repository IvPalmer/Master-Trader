# Open-position and strategy audit — 2026-09-01

## Executive finding

The FundingFade `TRX/USDT` loss shown by the dashboard was not exchange
exposure. The live process inherited an open trade created while its config was
temporarily in dry-run mode. Its entry order id starts with `dry_run_`, while
the live Binance wallet reports zero TRX. The live process consequently loops
on insufficient-funds stop and exit attempts.

The dashboard treats this as a critical position-ledger fault. It excludes the
simulated record from live exposure, unrealized P&L, capital at risk, and
equity/drawdown marks.

The operator authorized cleanup later on 2026-09-01. An online backup was
written to
`user_data/backups/tradesv3.live.FundingFadeV1.v2.pre-phantom-cleanup-20260901T2032Z.sqlite`
and passed `PRAGMA integrity_check`. Freqtrade then deleted only trade `#2`
through `DELETE /api/v1/trades/2`. FundingFade remained running, its warning
loop stopped, Binance still reported zero TRX, and the fleet returned green.

## Root cause timeline

- Commit `e2c73df` changed FundingFade from live to dry-run without changing
  its database URL.
- The dry-run process opened simulated `TRX/USDT` on 2026-08-31 at 11:00 UTC.
- Commit `1bb1c56` returned the process to live execution and enabled
  exchange-native stops while reusing that database.
- The live process then interpreted the simulated database row as exchange
  exposure even though the Binance wallet held no TRX.

## Fleet evidence at review time

| Strategy | Mode | Current epoch evidence | Audit verdict |
| --- | --- | --- | --- |
| FundingFadeV1 v2 | live | 2 closed trades, -$0.25, PF 0.64; phantom TRX row excluded | Logic/config contracts pass, but profitability is unproven and the DB must be reconciled. |
| KeltnerBounceV1 v2 | live | 0 closed trades in the current epoch | No current profitability conclusion; older 22-trade result (+$5.27, PF 1.22) is stale context only. |
| KillersScalpV1 r5 | live | 0 closed trades; one genuine DOT position was about +$0.59 with a verified native stop | Best historical evidence (42 trades, PF 1.57), but the current revision still needs closed-trade evidence. |
| OITrendPullbackV1 r4 | dry-run | 2 closed losses, -$0.13, PF 0; OI entry gate blocked | Not profitable on current evidence. Corrected calibration was PF 0.74 / -4%; keep dry-run. |
| ShortKeltner | dry-run | 0 current trades | Economically non-viable at observed signal frequency; keep dry-run. |
| Insiders | dry-run | 0 current trades | Source/identity risk and no profitable current evidence; keep dry-run. |

No strategy parameters were changed. The live samples are too small to justify
optimization, and doing so would turn observation into curve fitting.

## Dashboard contract after remediation

- Every fleet, strategy, and pair view separates **closed P&L**, **open P&L**,
  and **marked P&L**.
- Equity uses a solid line for closed-trade equity and a dashed final segment
  for the current mark on genuine open positions.
- Portfolio drawdown includes genuine open-position marks.
- A live bot containing a `dry_run_` open order is red at fleet level and gets
  a dedicated position-ledger fault panel.
- Phantom records are never counted as open positions or financial exposure.
- Every active production bot now runs `guard_db_mode.py` before Freqtrade on
  its next start. The guard blocks mismatched live/dry database names and
  refuses to start a live process when an open order id starts with `dry_run_`.

## Verification

- Dashboard tests: 41 passed.
- Strategy/config/hardening tests: 121 passed, 10 skipped when excluding two
  stale infrastructure assertions.
- The two stale assertions expect retired service names/restart policies and a
  removed Grafana dashboard directory; they do not test current strategy logic.
- JavaScript syntax, Python compilation, whitespace checks, and desktop/mobile
  rendered dashboard review passed.
