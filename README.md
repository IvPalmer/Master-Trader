# Master Trader — Multi-Bot Algorithmic Trading System

A self-improving multi-strategy crypto trading system built on [Freqtrade](https://www.freqtrade.io/). Runs 7 concurrent bots with automated health monitoring, backtesting validation, parameter optimization, and capital rebalancing.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                       │
│                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ClucHAnix │ │ NASOSv5  │ │ElliotV5  │ │ SupertrendStrat  │ │
│  │  :8080   │ │  :8082   │ │  :8083   │ │     :8084        │ │
│  │  5m dip  │ │  5m dip  │ │  5m dip  │ │   1h trend       │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐              │
│  │MasterV1  │ │MasterAI  │ │ NFI X6           │              │
│  │  :8086   │ │  :8087   │ │  :8089           │              │
│  │ 1h hybrid│ │ 1h ML    │ │ 5m multi-signal  │              │
│  └──────────┘ └──────────┘ └──────────────────┘              │
│                                                               │
│  ┌─────────────┐  ┌────────────┐  ┌───────────┐              │
│  │ Metrics     │→ │ Prometheus │→ │  Grafana  │              │
│  │ Exporter    │  │   :9091    │  │   :3000   │              │
│  │  :9090      │  │  90d ret.  │  │ Dashboard │              │
│  └─────────────┘  └────────────┘  └───────────┘              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   Automation Layer (cron)                     │
│                                                               │
│  Daily   23:00  strategy_health_report.py  → Telegram        │
│  Weekly  Sun    backtest_gate.py           → Telegram        │
│  Weekly  Sun    tournament_manager.py      → Rebalance       │
│  Weekly  Sun    hyperopt_optimizer.py      → Proposals       │
│  Monthly 1st    walk_forward.py            → Validation      │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ with `requests`, `prometheus_client`, `numpy`
- A Binance account (API keys optional for dry-run)

### 1. Set Up Freqtrade Directory

```bash
mkdir -p ~/ft_userdata/user_data/{strategies,configs,data,backtest_results,logs}
mkdir -p ~/ft_userdata/grafana/{provisioning/datasources,provisioning/dashboards,dashboards}
mkdir -p ~/ft_userdata/exporter
```

### 2. Copy Files from This Repo

```bash
# Docker & infra
cp deploy/docker-compose.yml ~/ft_userdata/
cp deploy/Dockerfile.nfi ~/ft_userdata/
cp deploy/monitoring/prometheus.yml ~/ft_userdata/
cp deploy/monitoring/exporter/Dockerfile ~/ft_userdata/exporter/
cp deploy/monitoring/grafana/provisioning/datasources/datasource.yml ~/ft_userdata/grafana/provisioning/datasources/
cp deploy/monitoring/grafana/provisioning/dashboards/dashboard.yml ~/ft_userdata/grafana/provisioning/dashboards/
cp deploy/monitoring/grafana/dashboards/freqtrade.json ~/ft_userdata/grafana/dashboards/

# Automation scripts
cp deploy/automation/*.py ~/ft_userdata/
cp deploy/automation/automation_scheduler.sh ~/ft_userdata/

# Backtest config
cp deploy/configs/config-backtest.json ~/ft_userdata/user_data/

# Strategy configs (customize from template)
cp deploy/configs/strategy-template.json ~/ft_userdata/user_data/configs/MyStrategy.json
```

### 3. Copy Strategies & Configs

```bash
# All 9 strategies included — copy them all
cp deploy/strategies/*.py ~/ft_userdata/user_data/strategies/

# Copy all strategy configs (already sanitized — update credentials)
cp deploy/configs/*.json ~/ft_userdata/user_data/configs/
```

Then edit each config in `~/ft_userdata/user_data/configs/`:
- Change `api_server.jwt_secret_key` and `password` (search for `CHANGE-ME`)
- Set `exchange.key` and `exchange.secret` for live trading (leave empty for dry-run)
- Adjust `dry_run_wallet`, `max_open_trades` as needed

### 5. Add a Bot to docker-compose.yml

```yaml
mybot:
  image: freqtradeorg/freqtrade:stable
  restart: unless-stopped
  container_name: ft-mybot
  volumes:
    - "./user_data:/freqtrade/user_data"
  ports:
    - "127.0.0.1:8080:8080"  # Use unique host port per bot
  command: >
    trade
    --logfile /freqtrade/user_data/logs/MyStrategy.log
    --config /freqtrade/user_data/configs/MyStrategy.json
    --strategy MyStrategy
```

### 6. Start Everything

```bash
cd ~/ft_userdata
docker compose up -d

# Verify bots are healthy:
for port in 8080 8082 8083; do
  echo -n "Port $port: "
  curl -s -u freqtrader:yourpassword http://localhost:$port/api/v1/ping
  echo
done
```

### 7. Install Automation

Edit the scripts in `~/ft_userdata/` to match your bot configuration (ports, strategy names, credentials), then:

```bash
# Update BOTS dict in each script to match your setup
# Update API_USER/API_PASS, WEBHOOK_URL, INITIAL_CAPITAL

# Install cron jobs
bash ~/ft_userdata/automation_scheduler.sh

# Test health report
python3 ~/ft_userdata/strategy_health_report.py --stdout
```

## Automation Scripts

| Script | Schedule | Purpose |
|--------|----------|---------|
| `strategy_health_report.py` | Daily 23:00 UTC | Health scores (0-100), flags, recommendations |
| `backtest_gate.py` | Weekly Sun 04:00 | Validate strategies via backtesting |
| `hyperopt_optimizer.py` | Weekly Sun 06:00 | Parameter optimization with OOS validation |
| `tournament_manager.py` | Weekly Sun 05:00 | Rank strategies, rebalance capital |
| `walk_forward.py` | Monthly 1st 07:00 | Rolling train/test to prevent overfitting |
| `metrics_exporter.py` | Always-on (Docker) | Prometheus metrics + portfolio circuit breaker |

All scripts can be run manually: `python3 script.py --help`

## Risk Management

Multi-layered defense system:

1. **Per-trade**: Stoploss (-8% for 5m, -10% for 1h), trailing stops
2. **Per-bot**: Protections (StoplossGuard, MaxDrawdown, CooldownPeriod, LowProfitPairs)
3. **Time-based**: Force-close stale trades (2h → tighten, 4h → -3% max, 8h → force exit)
4. **Anti-correlation**: OffsetFilter splits pairlists so dip-buyers don't overlap
5. **Portfolio**: Circuit breaker stops ALL bots at 10% portfolio drawdown
6. **Automated**: Health scores auto-pause strategies scoring <30 for 3+ days

See `research/risk-implementation-plan.md` for the full implementation plan.

## Monitoring

- **Grafana**: http://localhost:3000 — Master Dashboard with portfolio summary, per-bot P&L, charts
- **FreqUI**: http://localhost:{port} per bot — native Freqtrade web UI
- **Prometheus**: http://localhost:9091 — raw metrics (90-day retention)

## External Integrations (Optional)

### Telegram Notifications

The system sends reports via HTTP webhook. If you have a Telegram bot:
1. Set `WEBHOOK_URL` in each automation script to your bot's webhook endpoint
2. The webhook receives `POST` with `{"type": "status", "status": "message text"}`
3. Or set `telegram.enabled: true` in strategy configs for native Freqtrade Telegram

### Claude Assistant (Palmer's Setup)

Palmer uses a custom Telegram bot (`claude-assistant`) that:
- Receives webhooks from Freqtrade and forwards formatted trade notifications
- Runs scheduled jobs (morning/evening status, daily health report) via APScheduler
- Source: separate repo, not required for the trading system to work

To replicate: set up any webhook receiver that accepts the payload format above, or just enable Freqtrade's native Telegram integration.

## Repository Structure

```
research/                        # Strategy research & evidence
  REPORT.md                      # Start here — synthesized findings
  risk-implementation-plan.md    # Master risk management plan
  automation-system.md           # Automation layer documentation
  trade-data-analysis.md         # Actual MAE/trade data analysis
  ...                            # 15+ research files

deploy/                          # Everything needed to deploy
  docker-compose.yml             # Full stack: 7 bots + monitoring
  Dockerfile.nfi                 # Custom image for NFI strategy
  configs/
    strategy-template.json       # Template for new strategy configs
    config-backtest.json         # Backtesting config (static pairlist)
  automation/
    strategy_health_report.py    # Daily health scoring
    backtest_gate.py             # Backtesting validation gate
    hyperopt_optimizer.py        # Parameter optimization loop
    tournament_manager.py        # Capital rebalancing
    walk_forward.py              # Walk-forward validation
    metrics_exporter.py          # Prometheus metrics + circuit breaker
    automation_scheduler.sh      # Cron job installer
  monitoring/
    prometheus.yml               # Prometheus scrape config
    exporter/Dockerfile          # Metrics exporter Docker image
    grafana/
      dashboards/freqtrade.json  # Pre-built Grafana dashboard
      provisioning/              # Grafana auto-provisioning configs
```

## Key Principles

1. **Be obsessive about not losing money** — prefer missing a trade over taking a bad one
2. **No arbitrary numbers** — every parameter backed by evidence (MAE analysis, backtests)
3. **Portfolio-level protection** — not just per-bot
4. **No auto-deploy of optimizations** — human approval required
5. **Out-of-sample validation** — never trust in-sample results alone
