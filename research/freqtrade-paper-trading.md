# Freqtrade Paper Trading - Zero Risk Setup Guide

## TL;DR

Freqtrade's **dry-run mode** = real market data, fake money, no API keys needed. You can fully test strategies without spending a cent.

---

## How Dry-Run Works

- Connects to real Binance orderbook and candles (read-only operations only)
- Simulates a wallet locally (default 1000 USDT, configurable via `dry_run_wallet`)
- Tracks all trades in a local SQLite database
- Runs in real-time — results accumulate at market speed
- Full FreqUI web dashboard works

### Order Fill Simulation

| Order Type | Behavior |
|---|---|
| Market orders | Fill based on real orderbook volume, max 5% simulated slippage |
| Limit orders | Fill once price reaches level, or time out via `unfilledtimeout` |
| Limit orders crossing >1% | Auto-converted to market orders |

### What It Does NOT Simulate
- Partial fills (all-or-nothing)
- Network latency / execution delays
- Your orders' market impact
- Real API errors under load

### Accuracy Warning
Community reports gaps between dry-run and live. One user saw +262 USDT dry-run vs -94 USDT live. Main causes: slippage on low-volume pairs, limit orders filling in sim but not reality. **Treat dry-run as optimistic.** Stick to high-volume pairs.

---

## Dry-Run vs Binance Testnet

| Feature | Freqtrade Dry-Run | Binance Testnet |
|---|---|---|
| Data source | Real production orderbook | Separate testnet (fake data) |
| Liquidity | Real market conditions | Very thin, wide spreads |
| API keys | Not needed | Yes (testnet.binance.vision) |
| Order execution | Simulated locally | Posted to testnet exchange |
| Data resets | Never | Binance periodically wipes everything |
| Realism | **Much better** | Good only for API integration testing |

**Use dry-run for strategy validation. Use testnet only to test API code.**

---

## Setup on macOS (Apple Silicon)

### Docker Path (Recommended)

```bash
# 1. Install Docker Desktop for Mac (Apple Silicon version) first

# 2. Create project directory
mkdir ~/ft_userdata && cd ~/ft_userdata

# 3. Download docker-compose
curl https://raw.githubusercontent.com/freqtrade/freqtrade/stable/docker-compose.yml \
  -o docker-compose.yml

# 4. Pull image
docker compose pull

# 5. Create user directory structure
docker compose run --rm freqtrade create-userdir --userdir user_data

# 6. Generate config interactively
docker compose run --rm freqtrade new-config --config user_data/config.json
# → Say YES to dry-run
# → Pick Binance
# → Stake currency: USDT
# → Leave API keys blank
```

### Native Install (Alternative)

```bash
git clone https://github.com/freqtrade/freqtrade.git
cd freqtrade
./setup.sh -i
# Requires Python 3.11+
```

### System Requirements
- Docker Desktop: 4 GB RAM minimum allocated
- Python 3.11+ (for native)
- Git
- System clock must be NTP-synchronized
- Disk: a few GB for historical data
- RAM: 2-4 GB for Freqtrade, more for Hyperopt

---

## Minimal Dry-Run Config

No API keys needed:

```json
{
    "dry_run": true,
    "dry_run_wallet": 1000,
    "trading_mode": "spot",
    "stake_currency": "USDT",
    "stake_amount": "unlimited",
    "tradable_balance_ratio": 0.99,
    "max_open_trades": 5,
    "exchange": {
        "name": "binance",
        "key": "",
        "secret": "",
        "pair_whitelist": [
            "BTC/USDT",
            "ETH/USDT",
            "SOL/USDT"
        ]
    },
    "db_url": "sqlite:///tradesv3.dryrun.sqlite",
    "api_server": {
        "enabled": true,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "username": "freqtrader",
        "password": "your_password"
    }
}
```

---

## Complete Workflow

### Step 1: Create a Strategy

```bash
# Generate sample strategy
freqtrade new-strategy --strategy MyFirstStrategy --userdir user_data
```

Edit `user_data/strategies/MyFirstStrategy.py`.

### Step 2: Download Historical Data

```bash
freqtrade download-data \
  --config user_data/config.json \
  --timeframe 5m 1h \
  --days 90
```

### Step 3: Backtest

```bash
freqtrade backtesting \
  --config user_data/config.json \
  --strategy MyFirstStrategy \
  --timeframe 1h
```

### Step 4: Optimize (Optional)

```bash
freqtrade hyperopt \
  --config user_data/config.json \
  --strategy MyFirstStrategy \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --epochs 500
```

### Step 5: Paper Trade (Dry-Run)

```bash
freqtrade trade \
  --config user_data/config.json \
  --strategy MyFirstStrategy
```

FreqUI dashboard at http://127.0.0.1:8080

### Step 6: Go Live (Eventually)

- Change `"dry_run": false`
- Add real Binance API keys
- Use separate database: `"db_url": "sqlite:///tradesv3.live.sqlite"`
- Start with minimal capital
- Monitor closely

---

## Running Multiple Strategies

Two approaches:

**A) Separate instances** (simple, recommended for paper trading):
Run multiple Freqtrade processes, each with own config, strategy, and database on different ports.

**B) Multi-strategy template** (newer):
Run multiple strategies in a single instance. Saves resources and API rate limit.

---

## Timeline

| Week | Activity |
|------|---------|
| 1-2 | Install, learn framework, backtest strategies on historical data |
| 3-4+ | Dry-run with real market data, monitor via FreqUI |
| 5+ | Only go live after dry-run confirms backtest expectations |

**Minimum 2-4 weeks dry-run** before considering live. If your strategy trades infrequently, run longer.

---

## Sources

- [Freqtrade Bot Basics](https://www.freqtrade.io/en/stable/bot-basics/)
- [Freqtrade Configuration](https://www.freqtrade.io/en/stable/configuration/)
- [Freqtrade Docker Quickstart](https://www.freqtrade.io/en/stable/docker_quickstart/)
- [Freqtrade FreqUI](https://www.freqtrade.io/en/stable/freq-ui/)
- [Freqtrade Backtesting](https://www.freqtrade.io/en/stable/backtesting/)
- [Freqtrade Sandbox Testing](https://www.freqtrade.io/en/2021.8/sandbox-testing/)
- [Dry-Run Accuracy - GitHub #3685](https://github.com/freqtrade/freqtrade/issues/3685)
- [Dry-Run vs Live - GitHub #3902](https://github.com/freqtrade/freqtrade/issues/3902)
