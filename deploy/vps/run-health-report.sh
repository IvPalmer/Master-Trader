#!/bin/bash
# Master Trader health report — VPS edition.
# Runs strategy_health_report.py from the Dokploy-managed code checkout,
# pulls REST creds from a running Freqtrade container, posts to the
# VPS-side trade-webhook service (which forwards to Telegram).
#
# Installed at /home/ubuntu/master-trader/run-health-report.sh on Elder Brain.
# Cron: 0 23 * * * (daily 23:00 UTC = 20:00 São Paulo).
set -euo pipefail

CODE_DIR="/home/ubuntu/master-trader/runtime/ft_userdata"
STATE_DIR="/home/ubuntu/master-trader/state"
LOG_DIR="/home/ubuntu/master-trader/research/logs"
mkdir -p "$STATE_DIR/user_data" "$STATE_DIR/logs" "$LOG_DIR"

CREDS_CONTAINER="ft-keltner-bounce"
FREQTRADE__API_SERVER__USERNAME="$(docker exec "$CREDS_CONTAINER" printenv FREQTRADE__API_SERVER__USERNAME)"
FREQTRADE__API_SERVER__PASSWORD="$(docker exec "$CREDS_CONTAINER" printenv FREQTRADE__API_SERVER__PASSWORD)"
export FREQTRADE__API_SERVER__USERNAME FREQTRADE__API_SERVER__PASSWORD

export FT_DIR="$STATE_DIR"
# trade-webhook lives in services/trade-webhook/, bound to 127.0.0.1:8088 on
# the VPS host. Path is /freqtrade/event (not /webhooks/freqtrade — that was
# the Mac claude-assistant convention before the migration).
export WEBHOOK_URL="http://localhost:8088/freqtrade/event"

cd "$CODE_DIR"
exec /usr/bin/python3 strategy_health_report.py "$@" >> "$LOG_DIR/health_report.log" 2>&1
