# .vps-bot-guidance/

Source-of-truth copies of the `CLAUDE.md` files deployed onto the VPS so the
`elder-brain-bot` Telegram bot's embedded Claude knows how to query the trading
fleet. Versioned here so edits are tracked and reproducible.

## Files + deployment targets

| Local | VPS path | Purpose |
|-------|----------|---------|
| `CLAUDE-vps-home.md` | `/home/ubuntu/CLAUDE.md` | App map — every container the bot can reach by service name |
| `CLAUDE-master-trader.md` | `/home/ubuntu/master-trader/CLAUDE.md` | Trading-fleet runbook: which Freqtrade endpoint for which question, how to interpret dry-run vs live, read-only rule |

## Deployment

```bash
scp .vps-bot-guidance/CLAUDE-vps-home.md       ubuntu@100.96.225.124:/home/ubuntu/CLAUDE.md
scp .vps-bot-guidance/CLAUDE-master-trader.md  ubuntu@100.96.225.124:/home/ubuntu/master-trader/CLAUDE.md
```

Bot's `APPROVED_DIRECTORY=/home/ubuntu` so the embedded Claude reads
`/home/ubuntu/CLAUDE.md` always; `/home/ubuntu/master-trader/CLAUDE.md`
activates when the user's question routes work into that directory.

## Background

`elder-brain-bot` was missing network reachability to all VPS app stacks
(only attached to `dokploy-network`). The bot can now reach:

- `compose-bypass-mobile-port-fbk1m6_default` — Freqtrade fleet (`ft-funding-fade`, `ft-keltner-bounce`, `ft-grafana`, `ft-prometheus`, `trade-webhook`)
- `compose-bypass-virtual-feed-wghpqf_default` — veludo
- `compose-hack-1080p-array-fcyr5i_default` — dsrptv
- `crate-mate_internal` — crate-mate
- `ocdj_internal` — ocdj

Persisted via the bot's `docker-compose.yml` at
`/home/ubuntu/elder-brain-bot/docker-compose.yml` (5 external networks
declared so a redeploy keeps the wiring).

Freqtrade REST creds for the bot to use are at
`/home/ubuntu/master-trader/.bot-secrets/freqtrade.env` (chmod 600). NOT
in this repo.
