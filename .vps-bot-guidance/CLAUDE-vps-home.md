# /home/ubuntu — VPS operator notes for elder-brain-bot

You (Claude inside elder-brain-bot) are running on the Elder Brain VPS. The Telegram user (Palmer) reaches you via `@elder_brain_bot`.

`APPROVED_DIRECTORY=/home/ubuntu`. You have shell access via Bash, plus host filesystem mounts at `/home/ubuntu` and `/srv/lake`.

## Apps reachable on the docker network

Your container is attached to every per-app docker network. DNS resolves the container names directly.

| Project | Service | URL from inside this container |
|---------|---------|--------------------------------|
| master-trader | Freqtrade FundingFade (LIVE Binance) | `http://ft-funding-fade:8080` |
| master-trader | Freqtrade Keltner (dry-run) | `http://ft-keltner-bounce:8080` |
| master-trader | Grafana | `http://ft-grafana:3000` |
| master-trader | Prometheus | `http://ft-prometheus:9090` |
| master-trader | trade-webhook | `http://trade-webhook:8080` |
| veludo | web | `http://compose-bypass-virtual-feed-wghpqf-web-1` |
| dsrptv | web | `http://compose-hack-1080p-array-fcyr5i-web-1` |
| crate-mate | backend | `http://crate-mate-backend-1` |
| ocdj | backend | `http://ocdj-backend-1` |

When the user mentions a specific app and you need live state, prefer hitting these directly over guessing or saying "I don't have access".

## Querying the trading fleet

Project home: `/home/ubuntu/master-trader/` (read [master-trader/CLAUDE.md](master-trader/CLAUDE.md) when the user asks about bots, P&L, trades).

Creds + URLs live at `/home/ubuntu/master-trader/.bot-secrets/freqtrade.env` (chmod 600). Source it then curl:

```bash
set -a; . /home/ubuntu/master-trader/.bot-secrets/freqtrade.env; set +a
curl -s -u "$FT_API_USER:$FT_API_PASS" "$FT_FUNDING_FADE_URL/api/v1/profit"
```

Both bots share the same creds.
