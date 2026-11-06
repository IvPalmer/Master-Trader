#!/usr/bin/env bash
# VPS half of go-live.sh (#252, GO-LIVE.md Part 3). Do not run it by hand: go-live.sh
# copies it to the VPS, checks its hash and runs one phase at a time, detached, so a
# dropped ssh session never stops a phase halfway. Phases:
#   preflight  read-only checks; changes nothing
#   gateway    "Gateway deploy" steps 1-7: pilot trigger paused first, Killers entries
#              held, open trades checked PROTECTED before and after the recreate
#   bot        recreate ft-upbit-fade-hl live, verify it, restart the exporter, verify it
#   resume     remove the trigger's KILL file
# The first failed check stops the phase with FAIL. GO-LIVE.md says why each check holds.
set -Eeuo pipefail
PHASE=${1:?phase}
T=${2:?run id}
P=compose-bypass-mobile-port-fbk1m6
CODE=${UPBIT_GO_LIVE_CODE:-/etc/dokploy/compose/$P/code}  # override for tests only
FT=$CODE/ft_userdata
LIVE=$HOME/master-trader/research/upbit_fade_live
FWD=$HOME/master-trader/research/upbit_fade_forward
B=$HOME/backups/go-live-$T
K=http://127.0.0.1:8099/api/v1
U=http://127.0.0.1:8105/api/v1
GW=http://127.0.0.1:8104
STAGE=start
mkdir -p "$B"
cd "$B"

say() { printf '%s\n' "$*"; }
ok() { say "  ok    $*"; }
fail() { say "  FAIL  $*"; exit 1; }
dc() { (cd "$FT" && sudo -n docker compose -p "$P" -f docker-compose.prod.yml "$@"); }
hl() { curl -sf -m 20 https://api.hyperliquid.xyz/info -H 'Content-Type: application/json' -d "$1"; }
envval() { sudo -n grep -E "^$1=" "$FT/.env" | tail -1 | cut -d= -f2-; }
envcount() { sudo -n grep -cE "^$1=" "$FT/.env" || true; }
breaker() { sudo -n docker exec ft-metrics-exporter cat /state/portfolio_peak.json | jq -r .triggered; }
killers_creds() {
  KU=$(sudo -n docker exec ft-killers-scalp printenv FREQTRADE__API_SERVER__USERNAME)
  KP=$(sudo -n docker exec ft-killers-scalp printenv FREQTRADE__API_SERVER__PASSWORD)
  KW=$(sudo -n docker exec ft-killers-scalp printenv FREQTRADE__EXCHANGE__WALLET_ADDRESS)
}
k() { curl -s -m 30 -u "$KU:$KP" "$K/$1"; }
kpost() { curl -s -m 30 -u "$KU:$KP" -X POST "$K/$1"; }
pilot_creds() {
  UU=$(sudo -n docker exec ft-upbit-fade-hl printenv FREQTRADE__API_SERVER__USERNAME) &&
  UP=$(sudo -n docker exec ft-upbit-fade-hl printenv FREQTRADE__API_SERVER__PASSWORD)
}
u() { curl -sf -m 30 -u "$UU:$UP" "$U/$1"; }

# GO-LIVE.md "Gateway deploy" step 4's check, verbatim (tests/test_upbit_go_live.py keeps
# the two copies identical). Args: Killers /status, HL positions, HL orders, HL meta.
protected() {
python3 - "$@" <<'PY'
import json, math, sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
trades, positions, orders, meta = (json.load(open(p)) for p in sys.argv[1:5])
szd = {u["name"]: u["szDecimals"] for u in meta["universe"]}
mark = {p["position"]["coin"]: float(p["position"]["positionValue"]) / abs(float(p["position"]["szi"]))
        for p in positions}
def coarse(x, coin, up):
    # The coarsest price grid Freqtrade can round to near here: 5 significant figures one
    # decade above max(stop, mark), or Hyperliquid's decimal cap, whichever is coarser.
    e = max(math.floor(math.log10(max(x, mark.get(coin, x)))) - 3, -(6 - szd[coin]))
    # Exact decimal of the float's shortest repr (as ccxt's decimal_to_precision reads it),
    # rounded outward, no tolerance.
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(e), rounding=ROUND_CEILING if up else ROUND_FLOOR))
held = {p["position"]["coin"]: float(p["position"]["szi"]) for p in positions}
hl = {str(o["oid"]): o for o in orders}
known, ok = set(), len(held) == len(trades)
for t in trades:
    coin, short = t["pair"].split("/")[0], t["is_short"]
    close, exit_side = ("B", "buy") if short else ("A", "sell")
    liq = t.get("liquidation_price")
    stop = (min if short else max)(t["stop_loss_abs"], liq) if liq else t["stop_loss_abs"]
    open_ = [o for o in t["orders"] if o["status"] == "open"]
    sl = [o for o in open_ if o["ft_order_side"] == "stoploss"]
    hs = hl.get(str(sl[0]["order_id"])) if len(sl) == 1 else None
    trig = float(hs["triggerPx"]) if hs and hs.get("isTrigger") else None
    good = (held.get(coin, 0) * (-1 if short else 1) > 0 and abs(abs(held[coin]) - t["amount"]) < 1e-9
            and trig is not None and hs["coin"] == coin and hs["reduceOnly"] and hs["side"] == close
            and float(hs["sz"]) >= t["amount"] - 1e-9
            and (trig <= coarse(stop, coin, False) if short else trig >= coarse(stop, coin, True)))
    for o in open_:
        h = hl.get(str(o["order_id"]))
        known.add(str(o["order_id"]))
        good = good and (h is not None and h["coin"] == coin and h["reduceOnly"] and h["side"] == close
                         and o["ft_order_side"] in ("stoploss", exit_side))
    ok = ok and good
    print(coin, "OK" if good else "NOT PROTECTED", t["amount"], stop, trig)
orphans = [o["coin"] + ":" + str(o["oid"]) for o in orders if str(o["oid"]) not in known]
ok = ok and not orphans
print("orphan orders:", orphans)
print("PROTECTED" if ok else "DO NOT RECREATE")
PY
}

# Fresh Killers and Hyperliquid snapshots under prefix $1, then the check on them.
check_protected() {
  local out
  k status > "$1-status.json"
  hl "{\"type\":\"clearinghouseState\",\"user\":\"$KW\"}" | jq '.assetPositions' > "$1-positions.json" || return 1
  hl "{\"type\":\"frontendOpenOrders\",\"user\":\"$KW\"}" > "$1-orders.json" || return 1
  hl '{"type":"meta"}' > "$1-meta.json" || return 1
  jq -e 'type == "array"' "$1-status.json" "$1-positions.json" "$1-orders.json" >/dev/null || return 1
  out=$(protected "$1-status.json" "$1-positions.json" "$1-orders.json" "$1-meta.json") || return 1
  printf '%s\n' "$out" | sed 's/^/        /'
  [ "$(printf '%s\n' "$out" | tail -1)" = PROTECTED ]
}

monitor_quiet() { [ -z "$(find "$FWD/data/monitor.log" -mmin -15)" ]; }

restore_killers() {  # GO-LIVE step 7; a bot paused before, or a triggered breaker, stays paused
  local b s
  b=$(breaker)
  if [ "$(cat killers-state-before.txt)" = running ] && [ "$b" = false ]; then kpost start >/dev/null; fi
  s=$(k show_config | jq -r .state)
  say "  Killers state now: $s (before: $(cat killers-state-before.txt); breaker triggered: $b)"
  [ "$s" = "$(cat killers-state-before.txt)" ]
}

on_exit() {
  local rc=$?
  set +e
  if [ "$rc" -ne 0 ] && [ "$PHASE" = gateway ]; then
    case $STAGE in
      paused)
        say "Stopped BEFORE the recreate: restoring Killers entries (GO-LIVE step 7)."
        restore_killers || say "  Killers did not return to its previous state: check it by hand." ;;
      recreating)
        say "Stopped AFTER the recreate started: Killers entries stay PAUSED."
        say "Check the gateway and Killers. If they are fine, restore entries as in GO-LIVE step 7;"
        say "otherwise roll back to $(cat image.txt 2>/dev/null):pre-252 (GO-LIVE.md, Rollback to the old image)." ;;
    esac
  fi
  if [ "$rc" -ne 0 ] && [ -e "$LIVE/data/KILL" ]; then
    say "The pilot trigger stays paused (KILL file), so the pilot enters nothing."
  fi
  echo "$rc" > "$B/$PHASE.rc"
}
trap on_exit EXIT
# A command that fails outside a check still stops the phase; say which one.
trap 'say "  FAIL  line $LINENO: $BASH_COMMAND"' ERR

preflight() {
  local h st v n cfg dry ks gh
  say "Read-only checks; nothing changes."
  h=$((10#$(date -u +%H%M)))
  [ "$h" -lt 1315 ] || [ "$h" -gt 1350 ] || fail "13:15-13:50 UTC is the US open: run it later"
  grep -q "^CLIENTS = {.*'upbit'" "$CODE/services/hl-gateway/app/main.py" ||
    fail "the VPS checkout's gateway source has no upbit client"
  ok "VPS checkout: $(git -C "$CODE" log --oneline -1)"
  sudo -n docker exec ft-metrics-exporter grep -q OUTSIDE_BREAKER_ACCOUNTS /app/metrics_exporter.py ||
    fail "the running exporter is older than #261"
  sudo -n docker exec ft-metrics-exporter sh -c 'test -n "$HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS"' ||
    fail "the exporter lacks HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS (#261)"
  ok "exporter values the pilot account outside the breaker (#261)"
  [ "$(breaker)" = false ] || fail "the fleet circuit breaker is triggered"
  ok "fleet circuit breaker not triggered"
  sudo -n grep -qE '^HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS=0x[0-9a-fA-F]{40}$' "$FT/.env" ||
    fail "no pilot wallet address in the VPS .env"
  sudo -n grep -qE '^HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0x[0-9a-fA-F]{64}$' "$FT/.env" ||
    fail "no pilot API key in the VPS .env"
  PW=$(envval HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS)
  hl "{\"type\":\"extraAgents\",\"user\":\"$PW\"}" |
    jq -e --argjson now "$(date +%s)000" \
      'any(.[]; .name == "upbit-fade-live" and .validUntil > $now + 7 * 86400000)' >/dev/null ||
    fail "API wallet upbit-fade-live missing on the pilot account or expiring within 7 days"
  ok "pilot wallet, API key and approved API wallet upbit-fade-live"
  st=$(hl "{\"type\":\"clearinghouseState\",\"user\":\"$PW\"}") || fail "pilot account unreadable"
  [ "$(jq '.assetPositions | length' <<<"$st")" = 0 ] || fail "the pilot account has open positions"
  [ "$(hl "{\"type\":\"frontendOpenOrders\",\"user\":\"$PW\"}" | jq length)" = 0 ] ||
    fail "the pilot account has open orders"
  v=$(jq -r .marginSummary.accountValue <<<"$st")
  python3 -c 'import sys; sys.exit(not float(sys.argv[1]) >= 100)' "$v" ||
    fail "the pilot account holds $v USDC in perps (needs at least 100)"
  ok "pilot account flat, no open orders, $v USDC in perps"
  pilot_creds || fail "ft-upbit-fade-hl is not running"
  cfg=$(u show_config) || fail "ft-upbit-fade-hl API unreachable"
  [ "$(jq -r .state <<<"$cfg")" = running ] || fail "ft-upbit-fade-hl is $(jq -r .state <<<"$cfg")"
  dry=$(jq -r .dry_run <<<"$cfg")
  if [ "$dry" = false ]; then
    [ "$(u status | jq length)" = 0 ] || fail "ft-upbit-fade-hl is already live with open trades"
    ok "ft-upbit-fade-hl already live and flat (a re-run)"
  else
    ok "ft-upbit-fade-hl running in dry-run"
  fi
  systemctl --user is-active -q upbit-fade-live-trigger || fail "upbit-fade-live-trigger is not active"
  systemctl --user is-active -q upbit-fade-forward || fail "upbit-fade-forward is not active"
  monitor_quiet || fail "the paper monitor logged in the last 15 min (an event may be in progress)"
  ok "trigger and paper monitor running; no event in progress"
  killers_creds
  ks=$(k show_config | jq -r .state)
  [ "$ks" = running ] || fail "Killers is $ks, not running. If an earlier go-live left it paused, read that run's log in ~/backups/go-live-*"
  n=$(k status | jq length)
  ok "Killers running with $n open trade(s)"
  gh=$(curl -sf -m 10 "$GW/healthz") || fail "hl-gateway healthz unreachable"
  [ "$(jq -r .status <<<"$gh")" = ok ] || fail "hl-gateway reports $(jq -c '{status, faults}' <<<"$gh")"
  if jq -e '.clients | has("upbit")' <<<"$gh" >/dev/null; then
    ok "hl-gateway already has the upbit client: its deploy is skipped"
    say "GATEWAY=deployed"
  else
    ok "hl-gateway healthy, upbit client not deployed yet"
    say "GATEWAY=old"
  fi
}

gateway() {
  local img i r q w gh
  touch "$LIVE/data/KILL"
  ok "pilot trigger paused (KILL file)"
  say "1. Build the new gateway image; the running gateway is not affected"
  img=$(sudo -n docker inspect -f '{{.Config.Image}}' ft-hl-gateway)
  img=${img%%:*}
  echo "$img" > image.txt
  sudo -n docker tag "$(sudo -n docker inspect -f '{{.Image}}' ft-hl-gateway)" "$img:pre-252"
  dc build -q hl-gateway
  ok "built; the running image is kept as $img:pre-252"

  say "2. Pause Killers entries"
  killers_creds
  k show_config | jq -r .state > killers-state-before.txt
  [ "$(cat killers-state-before.txt)" = running ] || fail "Killers is $(cat killers-state-before.txt), not running"
  breaker > breaker-before.txt
  STAGE=paused
  kpost stopentry >/dev/null
  [ "$(k show_config | jq -r .state)" = paused ] || fail "Killers did not pause"
  ok "Killers entries paused (exits, stops and TPs keep working)"

  say "3. Drain any entry already in flight"
  sleep 15
  for i in 1 2; do
    r=$(curl -s -m 900 -u "$KU:$KP" -X DELETE "$K/trades/0/open-order")
    grep -q "Invalid trade_id" <<<"$r" || fail "drain probe $i answered: $r"
    sleep 5
  done
  for i in $(seq 1 24); do
    q=$(sudo -n docker exec killers-receiver python -c "import os,sqlite3; c=sqlite3.connect('file:'+os.environ['KILLERS_DB']+'?mode=ro',uri=True,timeout=10); print(c.execute(\"SELECT count(*) FROM positions WHERE state='requested'\").fetchone()[0])")
    [ "$q" = 0 ] && break
    say "  receiver has $q requested position(s); waiting 30 s ($i/24)"
    sleep 30
  done
  [ "$q" = 0 ] || fail "the receiver still has $q requested position(s) after 12 min"
  ok "no entry in flight; receiver has 0 requested"

  say "4. Final checks, immediately before the recreate"
  sudo -n docker logs killers-receiver --since 10m 2>&1 | tail -20 > receiver-log-before.txt || true
  for i in $(seq 1 10); do
    if check_protected before; then
      gh=$(curl -sf -m 10 "$GW/healthz") || fail "hl-gateway healthz unreachable"
      echo "$gh" | jq '{observed_at, weight_last_minute, queued}' > usage-before.json
      w=$(jq .weight_last_minute <<<"$gh")
      if [ "$w" -lt 300 ] && monitor_quiet; then
        ok "Killers trades PROTECTED; gateway weight $w/min (< 300); paper monitor quiet"
        break
      fi
      say "  gateway weight $w/min or paper monitor activity"
    fi
    [ "$i" -lt 10 ] || fail "the final checks did not pass in 10 tries (5 min)"
    say "  not yet; trying again in 30 s ($i/10)"
    sleep 30
  done

  say "5. Recreate hl-gateway"
  STAGE=recreating
  dc up -d --no-deps hl-gateway
  r=$(date +%s)
  echo "$r" > recreated_at
  for i in $(seq 1 60); do curl -sf -m 5 "$GW/healthz" >/dev/null && break; sleep 2; done
  curl -sf -m 5 "$GW/healthz" >/dev/null || fail "hl-gateway not healthy 120 s after the recreate"
  ok "hl-gateway recreated and answering"

  say "6. Verify, Killers entries still paused"
  jq -e '(.clients | has("upbit")) and (.slice_weight_last_minute | has("upbit"))' \
    <<<"$(curl -sf -m 10 "$GW/healthz")" >/dev/null || fail "the new gateway has no upbit client"
  [ "$(k show_config | jq -r .state)" = paused ] || fail "Killers is not paused"
  k status | jq -e 'type == "array"' >/dev/null || fail "Killers /status does not answer"
  while [ $(( $(date +%s) - r )) -lt 65 ]; do sleep 5; done
  gh=$(curl -sf -m 10 "$GW/healthz") || fail "hl-gateway healthz unreachable"
  echo "$gh" > healthz-after.json
  jq -e '([.clients[] | .rate_limited + .queue_timeout] | add) == 0
         and (.clients.killers.ok + .clients.killers.cached) > 0' <<<"$gh" >/dev/null ||
    fail "gateway since the recreate: $(jq -c '{faults, killers: .clients.killers}' <<<"$gh")"
  ok "gateway: Killers reads ok, no budget refusals ($(jq -c '{faults, weight_last_minute}' <<<"$gh"))"
  if sudo -n docker logs ft-killers-scalp --since "$((r - 30))" 2>&1 |
      grep -E "Unable to place a stoploss order|Exiting the trade forcefully" > killers-log-after.txt; then
    cat killers-log-after.txt
    fail "Killers logged a stop placement failure or a forced exit"
  fi
  ok "Killers log: no stop placement failure, no forced exit"
  for i in $(seq 1 6); do
    check_protected after && break
    [ "$i" -lt 6 ] || fail "open Killers trades are not PROTECTED after the recreate"
    say "  not PROTECTED yet (a TP or stop may have filled and not been booked); again in 30 s ($i/6)"
    sleep 30
  done
  ok "Killers trades PROTECTED after the recreate"

  say "7. Restore Killers entries"
  restore_killers || fail "Killers did not return to its previous state"
  STAGE=complete
  ok "gateway deploy complete"
}

bot() {
  local i cfg bal started commit
  [ "$(envcount HL_UPBIT_GATEWAY_CLIENT)" = 1 ] && [ "$(envval HL_UPBIT_GATEWAY_CLIENT)" = upbit ] ||
    fail "the VPS .env does not hold HL_UPBIT_GATEWAY_CLIENT=upbit exactly once"
  [ "$(envcount HYPERLIQUID_UPBIT_FADE_DRY_RUN)" = 1 ] && [ "$(envval HYPERLIQUID_UPBIT_FADE_DRY_RUN)" = false ] ||
    fail "the VPS .env does not hold HYPERLIQUID_UPBIT_FADE_DRY_RUN=false exactly once"
  jq -e '.clients | has("upbit")' <<<"$(curl -sf -m 10 "$GW/healthz")" >/dev/null ||
    fail "hl-gateway has no upbit client"
  [ -e "$LIVE/data/KILL" ] || fail "the pilot trigger is not paused"
  say "Recreate ft-upbit-fade-hl live"
  dc up -d --no-deps ft-upbit-fade-hl
  cfg=
  for i in $(seq 1 36); do
    sleep 5
    if pilot_creds && cfg=$(u show_config) && [ "$(jq -r .state <<<"$cfg")" = running ]; then break; fi
    cfg=
  done
  if [ -z "$cfg" ]; then
    sudo -n docker logs ft-upbit-fade-hl --tail 30 2>&1
    fail "ft-upbit-fade-hl did not come up running within 3 min"
  fi
  [ "$(jq -r .dry_run <<<"$cfg")" = false ] || fail "ft-upbit-fade-hl came up in dry-run"
  [ "$(jq -r .stoploss_on_exchange <<<"$cfg")" = true ] || fail "the exchange stop is off"
  ok "running live, exchange stop on"
  [ "$(sudo -n docker exec ft-upbit-fade-hl printenv FREQTRADE__EXCHANGE__CCXT_CONFIG__urls__api__private)" = \
    http://hl-gateway:8080/upbit ] || fail "the bot does not use the gateway's upbit client"
  ok "orders go through hl-gateway's upbit client"
  bal=$(u balance) || fail "/balance unreadable"
  python3 -c 'import sys, json; b = json.loads(sys.argv[1]); sys.exit(not (b["stake"] == "USDC" and float(b["total"]) >= 100))' "$bal" ||
    fail "/balance is $(jq -c '{total, stake}' <<<"$bal"), expected about 108 USDC"
  ok "balance $(jq -r .total <<<"$bal") USDC on the pilot account"
  jq -e '.profit_closed_coin == 0 and .trade_count == 0' <<<"$(u profit)" >/dev/null ||
    fail "the live database is not empty"
  [ "$(u status | jq length)" = 0 ] || fail "the live bot reports open trades"
  ok "new live database, no trades"
  started=$(sudo -n docker inspect -f '{{.State.StartedAt}}' ft-upbit-fade-hl)
  if sudo -n docker logs ft-upbit-fade-hl --since "$started" 2>&1 |
      grep -iE "AuthenticationError|PermissionDenied|Unauthorized|InvalidNonce|Could not load markets|live mode needs|dry-run needs" > bot-log.txt; then
    cat bot-log.txt
    fail "authentication or market errors in the bot log"
  fi
  ok "bot log: no authentication or market errors"
  commit=$(git -C "$CODE" rev-parse HEAD)
  printf 'EPOCH_START=%s\nDEPLOYED_COMMIT=%s\n' "$started" "$commit" | tee epoch.txt

  say "Exporter: restart so it reads the new live membership now (it values the pilot outside the breaker)"
  sudo -n docker restart ft-metrics-exporter >/dev/null
  for i in $(seq 1 24); do
    sleep 10
    if sudo -n docker exec ft-metrics-exporter cat /state/account_health.json 2>/dev/null |
        jq -e '(.accounts["hyperliquid-upbit-fade"].equity >= 0)
               and (.outside_breaker_accounts | has("hyperliquid-upbit-fade"))
               and (has("unvalued_accounts") | not) and .breaker_complete' >/dev/null; then
      ok "exporter: pilot account valued and outside the breaker; breaker evaluating"
      return 0
    fi
  done
  fail "the exporter does not show the pilot account outside the breaker after 4 min"
}

resume() {
  rm -f "$LIVE/data/KILL"
  sleep 20
  [ ! -e "$LIVE/data/KILL" ] || fail "KILL is back: the trigger re-engaged its own switch (see $LIVE/data/trigger.log)"
  systemctl --user is-active -q upbit-fade-live-trigger || fail "upbit-fade-live-trigger is not active"
  tail -3 "$LIVE/data/trigger.log"
  ok "pilot trigger armed"
}

case $PHASE in
  preflight|gateway|bot|resume) "$PHASE" ;;
  *) fail "unknown phase $PHASE" ;;
esac
