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

# Read each bot's EFFECTIVE credentials from its own container and export them
# under that bot's slug. api_utils resolves the slug from the published
# loopback port, so the report authenticates correctly whether a bot is on the
# shared pair or has been moved to its own.
#
# Reading one container and calling the result "shared" was wrong: the moment
# any single bot is rotated, that bot's pair would be presented to every other
# bot and the whole report would 401.
export_bot_creds() {
  local slug="$1" container="$2" user pass
  user="$(docker exec "$container" printenv FREQTRADE__API_SERVER__USERNAME 2>/dev/null || true)"
  pass="$(docker exec "$container" printenv FREQTRADE__API_SERVER__PASSWORD 2>/dev/null || true)"
  if [ -n "$user" ] && [ -n "$pass" ]; then
    export "FT_API_USER_${slug}=$user" "FT_API_PASS_${slug}=$pass"
  else
    echo "warn: could not read credentials from $container" >&2
  fi
}

export_bot_creds KELTNER      ft-keltner-bounce
export_bot_creds FUNDINGFADE  ft-funding-fade
export_bot_creds OITREND      ft-oi-trend-pullback
export_bot_creds KILLERS      ft-killers-scalp
export_bot_creds INSIDERS     ft-insiders-scalp
export_bot_creds SHORTKELTNER ft-short-keltner-hl-live

# Shared pair as the fallback for anything not covered above.
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
