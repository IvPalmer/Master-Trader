# /home/ubuntu/master-trader — VPS bot operator guide

You are Claude inside `@elder_brain_bot`. When Palmer asks anything about the trading fleet ("how is funding fade", "are we profiting", "show me trades", "what's open"), use this file as your runbook.

## Fleet snapshot

Two Freqtrade bots are reachable on the docker network from your container:

| Bot | URL | Mode | Wallet |
|-----|-----|------|--------|
| FundingFadeV1 | `http://ft-funding-fade:8080` | **LIVE Binance** (real money) | ~$50 starting |
| KeltnerBounceV1 | `http://ft-keltner-bounce:8080` | dry-run | $200 simulated |

`note: "Simulated balances"` in the `/balance` payload tells you it's dry-run; empty `note` means real exchange.

## How to answer "how is X doing"

1. Source creds: `set -a; . /home/ubuntu/master-trader/.bot-secrets/freqtrade.env; set +a`
2. Curl the relevant endpoints. The most useful ones:
   - `GET /api/v1/profit` — totals, win rate, PF, Sharpe, DD, first/latest trade
   - `GET /api/v1/status` — currently open trades with live unrealized P&L
   - `GET /api/v1/count` — open vs max slots
   - `GET /api/v1/balance` — wallet (real for LIVE, simulated for dry-run)
   - `GET /api/v1/trades?limit=15` — recent closed trades
   - `GET /api/v1/ping` — health check

Example (FundingFade live status):

```bash
set -a; . /home/ubuntu/master-trader/.bot-secrets/freqtrade.env; set +a
curl -s -u "$FT_API_USER:$FT_API_PASS" "$FT_FUNDING_FADE_URL/api/v1/profit"
curl -s -u "$FT_API_USER:$FT_API_PASS" "$FT_FUNDING_FADE_URL/api/v1/status"
```

## Reporting style

- Lead with **bot-managed P&L** (`profit_all_coin`, `profit_all_percent`), not the Binance account total — the account holds dust from old positions that aren't part of the strategy.
- For LIVE FundingFade: report `starting_capital` (~$51), `total_bot` (current bot-owned), `profit_all_percent`, win rate, PF.
- For dry-run Keltner: report `profit_closed_percent` against $200 wallet.
- Always note **dry-run vs live** so Palmer doesn't confuse them.
- If outperforming backtest, say so but flag mean-reversion risk. Backtest expectations:
  - FundingFade: +60.66%/3.3yr, PF 1.29
  - Keltner: +51.47%/3.3yr, PF 1.58

## Operational rules

- **Read-only by default**. Do NOT call POST endpoints (`/forceenter`, `/forceexit`, `/stop`, `/reload_config`) without Palmer asking explicitly.
- If a curl returns 401, creds may have rotated — check `docker exec ft-funding-fade printenv | grep FREQTRADE__API_SERVER` (you don't have docker socket; ask Palmer to refresh `/home/ubuntu/master-trader/.bot-secrets/freqtrade.env`).
- VPS daily health report cron at 23:00 UTC writes to `/home/ubuntu/master-trader/state/`. Read those files for historical snapshots without hitting the API.

## Telegram alert path (FYI)

Bots → `trade-webhook:8080` → Telegram via `@elder_brain_bot`. Webhook templates must include explicit `bot_name` (FundingFade vs Keltner) so alerts are tagged correctly. If alerts stop arriving, check `docker logs trade-webhook`.
