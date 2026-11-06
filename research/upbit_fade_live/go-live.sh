#!/usr/bin/env bash
# Upbit fade pilot: go live in one command, from this Mac (#252, GO-LIVE.md Part 3).
#
#   research/upbit_fade_live/go-live.sh
#
# Read-only checks first, then one YES, then in order: pause the pilot trigger; deploy
# hl-gateway with the upbit client (Killers entries held a few minutes, its open trades
# checked PROTECTED before and after); set the two live flags in the VPS .env; recreate
# ft-upbit-fade-hl live and verify it and the exporter; resume the trigger. It stops at
# the first failed check and says what state it left. Each VPS phase runs detached and
# logs to ~/backups/go-live-<run>/ on the VPS, so a dropped connection never stops one
# halfway. The agent never runs this; the operator does.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
VPS=${VPS:-main-instance}
T=$(date -u +%Y%m%dT%H%M%SZ)
REMOTE=/tmp/upbit-go-live-$T.sh
# shellcheck disable=SC2088  # expanded by the VPS shell, in the ssh commands
LOGS="~/backups/go-live-$T"
die() { printf '\n%s\n' "$*" >&2; exit 1; }

# Run one VPS phase detached, follow its log, return its exit code.
phase() {
  local name=$1 pid rc
  pid=$(ssh "$VPS" "mkdir -p $LOGS && setsid nohup bash $REMOTE $name $T > $LOGS/$name.log 2>&1 < /dev/null & echo \$!") ||
    die "Could not start the $name phase on the VPS."
  ssh "$VPS" "tail -n +1 --pid=$pid -f $LOGS/$name.log" || true
  rc=$(ssh "$VPS" "cat $LOGS/$name.rc 2>/dev/null") || rc=
  [ -n "$rc" ] || die "Lost track of the $name phase; it keeps running on the VPS. Follow it with:
  ssh $VPS tail -f $LOGS/$name.log"
  return "$rc"
}

echo "Upbit fade pilot go-live, run $T"
scp -q "$HERE/go_live_remote.sh" "$VPS:$REMOTE" || die "Could not copy the VPS script. Nothing changed."
[ "$(ssh "$VPS" sha256sum "$REMOTE" | cut -d' ' -f1)" = "$(shasum -a 256 "$HERE/go_live_remote.sh" | cut -d' ' -f1)" ] ||
  die "The VPS copy failed its hash check. Nothing changed."

echo; echo "== Checks (read-only)"
phase preflight || die "A check failed. Nothing changed."
GW=$(ssh "$VPS" "grep -o '^GATEWAY=[a-z]*' $LOGS/preflight.log | tail -1")

cat <<'TXT'

Going live will:
  1. pause the pilot trigger (KILL file);
  2. deploy the new hl-gateway: Killers entries paused for a few minutes, its open
     trades and their stops/TPs stay on Hyperliquid and are checked before and after;
  3. set HL_UPBIT_GATEWAY_CLIENT=upbit and HYPERLIQUID_UPBIT_FADE_DRY_RUN=false in the VPS .env;
  4. recreate ft-upbit-fade-hl LIVE on the pilot account, check it, restart the exporter;
  5. resume the trigger. From then on a qualifying Upbit KRW listing opens a real $50 short.
TXT
[ "$GW" = GATEWAY=deployed ] && echo "  (hl-gateway already has the upbit client: step 2 is skipped)"
printf '\nType YES to go live: '
read -r answer </dev/tty
[ "$answer" = YES ] || die "Cancelled. Nothing changed."

if [ "$GW" != GATEWAY=deployed ]; then
  echo; echo "== Gateway deploy"
  phase gateway || die "Stopped in the gateway deploy; the log above says what state it left.
The pilot is still dry-run and its trigger paused."
fi

echo; echo "== Live flags in the VPS .env"
python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import hl_agent as h; h.apply_env(h.env_pairs(sys.argv[2:]))' \
  "$HERE/../../scripts/hyperliquid" HL_UPBIT_GATEWAY_CLIENT=upbit HYPERLIQUID_UPBIT_FADE_DRY_RUN=false ||
  die "The .env edit did not confirm (see above). The bot was not recreated; the trigger stays paused.
Run this script again."

echo; echo "== Bot live"
phase bot || die "Stopped at the bot step; the trigger stays paused, so the pilot enters nothing.
To return to dry-run: GO-LIVE.md, Kill switch and rollback, Back to dry-run."

echo; echo "== Resume the trigger"
phase resume || die "The bot is live but the trigger is not armed (see above)."

echo
ssh "$VPS" "cat $LOGS/epoch.txt"
echo "Done: the pilot is live. Send Claude the two lines above for the prereg epoch amendment and #252."
