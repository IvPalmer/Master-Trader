#!/bin/bash
# ============================================================================
# Master Trader Automation Scheduler
# ============================================================================
#
# Installs cron jobs for all automation scripts.
# Run this once: bash automation_scheduler.sh
#
# Schedule overview (all times UTC):
#   Every 4h (0,4,8,12,16,20 UTC)  — Funding Rate Refresh (live bot dependency)
#   Daily  02:00                    — SQLite live-DB backup (rolling 14 days)
#   Daily  23:00 (20:00 São Paulo) — Strategy Health Report
#   Weekly Sun 03:00               — Data Download (fresh data for backtesting)
#   Weekly Sun 04:00               — Backtest Gate (validate all strategies)
#   Weekly Sun 05:00               — Tournament Manager (rebalance allocations)
#   Weekly Sun 06:00               — Hyperopt Optimizer (parameter optimization)
#   Monthly 1st 07:00              — Walk-Forward Validation
#
# ============================================================================

set -e

FT_DIR="$HOME/ft_userdata"
LOGS_DIR="$FT_DIR/logs"

mkdir -p "$LOGS_DIR"

# Build the crontab entries
CRON_ENTRIES=$(cat << 'CRONTAB'
# ── Master Trader Automation ──────────────────────────────────────

# Daily 02:00 UTC: Backup live SQLite DBs via sqlite3 .backup (WAL-safe,
# consistent across concurrent writes). 14-day rolling retention.
0 2 * * * cd ~/ft_userdata && mkdir -p user_data/backups && for f in user_data/tradesv3.live.*.sqlite; do [ -f "$f" ] && /usr/bin/sqlite3 "$f" ".backup user_data/backups/$(basename "$f" .sqlite).$(date -u +%Y%m%d).sqlite"; done && find user_data/backups -name "*.sqlite" -type f -mtime +14 -delete >> logs/db_backup.log 2>&1

# Every 4h: Refresh funding rate feathers — LIVE FundingFadeV1 dependency.
# Binance publishes every 8h at 00/08/16 UTC. Incremental mode fetches only
# the tail since the last stored record (with 24h rewind for safety) and merges
# atomically. Strategy watches the feather mtime and auto-reloads.
0 */4 * * * cd ~/ft_userdata && /usr/bin/python3 download_funding_rates.py --incremental >> logs/funding_refresh.log 2>&1

# Daily: Strategy Health Report (20:00 São Paulo = 23:00 UTC)
# Sources repo-root .env so rotated FREQTRADE__API_SERVER__* creds are picked up.
0 23 * * * cd ~/ft_userdata && set -a && [ -f ../.env ] && . ../.env; set +a; /usr/bin/python3 strategy_health_report.py >> logs/health_report.log 2>&1

# Weekly Sunday 03:00 UTC: Download fresh data for backtesting
0 3 * * 0 cd ~/ft_userdata && docker run --rm -v "./user_data:/freqtrade/user_data" freqtradeorg/freqtrade:stable download-data --exchange binance --pairs BTC/USDT ETH/USDT SOL/USDT XRP/USDT DOGE/USDT BNB/USDT ADA/USDT AVAX/USDT LINK/USDT NEAR/USDT --timeframes 5m 1h --timerange $(date -u -v-90d +%Y%m%d)-$(date -u +%Y%m%d) --config /freqtrade/user_data/config-backtest.json >> logs/data_download.log 2>&1

# Weekly Sunday 04:00 UTC: Backtest Gate (validate all strategies)
0 4 * * 0 cd ~/ft_userdata && /usr/bin/python3 backtest_gate.py --all --report >> logs/backtest_gate.log 2>&1

# Weekly Sunday 05:00 UTC: Tournament Manager (rank + rebalance)
0 5 * * 0 cd ~/ft_userdata && /usr/bin/python3 tournament_manager.py >> logs/tournament.log 2>&1

# Weekly Sunday 06:00 UTC: Hyperopt Optimizer
0 6 * * 0 cd ~/ft_userdata && /usr/bin/python3 hyperopt_optimizer.py --all --report >> logs/hyperopt.log 2>&1

# Monthly 1st at 07:00 UTC: Walk-Forward Validation
0 7 1 * * cd ~/ft_userdata && /usr/bin/python3 walk_forward.py --all --report >> logs/walk_forward.log 2>&1

# ── End Master Trader Automation ──────────────────────────────────
CRONTAB
)

echo "Installing Master Trader cron jobs..."
echo ""

# Check if entries already exist
if crontab -l 2>/dev/null | grep -q "Master Trader Automation"; then
    echo "Cron jobs already installed. Removing old entries first..."
    # Remove old entries between markers
    crontab -l 2>/dev/null | sed '/── Master Trader Automation/,/── End Master Trader/d' | crontab -
fi

# Append new entries
(crontab -l 2>/dev/null; echo "$CRON_ENTRIES") | crontab -

echo "Cron jobs installed successfully!"
echo ""
echo "Current crontab:"
crontab -l | grep -A1 "Master Trader\|health_report\|backtest_gate\|tournament\|hyperopt\|walk_forward\|data_download"
echo ""
echo "Schedule:"
echo "  Every 4h 0 UTC  — Funding Refresh (live bot)"
echo "  Daily  02:00 UTC — SQLite live-DB backup (14-day rolling)"
echo "  Daily  23:00 UTC — Health Report → Telegram"
echo "  Weekly Sun 03:00 — Data Download"
echo "  Weekly Sun 04:00 — Backtest Gate → Telegram"
echo "  Weekly Sun 05:00 — Tournament → Rebalance + Telegram"
echo "  Weekly Sun 06:00 — Hyperopt → Proposals + Telegram"
echo "  Monthly 1st 07:00 — Walk-Forward → Telegram"
echo ""
echo "Logs: $LOGS_DIR/"
