#!/bin/bash
# Preflight for the fleet's API credentials and receiver ingress tokens.
# Run on the VPS BEFORE `docker compose up`, from the directory holding the
# stack .env. Read-only: it inspects configuration and running containers and
# changes nothing.
#
#   ./preflight-credentials.sh
#
# Exits non-zero on any blocking problem.
set -uo pipefail

ENV_FILE="${1:-.env}"
FAIL=0
WARN=0

err()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL + 1)); }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; WARN=$((WARN + 1)); }
ok()   { printf '  \033[32m ok \033[0m  %s\n' "$1"; }

if [ ! -f "$ENV_FILE" ]; then
  echo "no env file at $ENV_FILE (pass its path as \$1)" >&2
  exit 2
fi

# Read without sourcing: the file holds secrets and arbitrary shell would run.
get() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }

SLUGS="KELTNER FUNDINGFADE OITREND KILLERS INSIDERS SHORTKELTNER"

echo "== receiver ingress tokens =="
K_TOKEN="$(get KILLERS_INGRESS_TOKEN)"
I_TOKEN="$(get INSIDERS_INGRESS_TOKEN)"

for pair in "KILLERS_INGRESS_TOKEN:$K_TOKEN" "INSIDERS_INGRESS_TOKEN:$I_TOKEN"; do
  name="${pair%%:*}"; value="${pair#*:}"
  if [ -z "$value" ]; then
    err "$name is unset — the receiver will refuse to start"
  elif [ "${#value}" -lt 24 ]; then
    err "$name is ${#value} chars, minimum 24 (openssl rand -hex 24)"
  else
    ok "$name set (${#value} chars)"
  fi
done

if [ -n "$K_TOKEN" ] && [ "$K_TOKEN" = "$I_TOKEN" ]; then
  err "both receivers share one token — they drive separately funded accounts"
elif [ -n "$K_TOKEN" ] && [ -n "$I_TOKEN" ]; then
  ok "the two receiver tokens differ"
fi

echo
echo "== per-bot API credentials (optional, but all-or-nothing per bot) =="
for slug in $SLUGS; do
  u="$(get "FT_API_USER_$slug")"
  p="$(get "FT_API_PASS_$slug")"
  j="$(get "FT_API_JWT_$slug")"
  set_count=0
  [ -n "$u" ] && set_count=$((set_count + 1))
  [ -n "$p" ] && set_count=$((set_count + 1))
  [ -n "$j" ] && set_count=$((set_count + 1))

  if [ "$set_count" -eq 0 ]; then
    ok "$slug on the shared fleet credentials"
  elif [ "$set_count" -eq 3 ]; then
    if [ "${#j}" -lt 32 ]; then
      err "FT_API_JWT_$slug is ${#j} chars; freqtrade requires at least 32"
    else
      ok "$slug fully on its own credentials"
    fi
  else
    # Compose resolves USER and PASS independently, so a half-set bot starts
    # on a mismatched pair while the dashboard, exporter and health report all
    # fall back to the shared one and get 401.
    err "$slug is half-configured (${set_count}/3 set) — set all three or none"
  fi
done

echo
echo "== observer (host, outside compose) =="
OBS_ENV="${OBSERVER_ENV:-/home/ubuntu/killers-bot/.env}"
if [ ! -f "$OBS_ENV" ]; then
  warn "no observer env at $OBS_ENV — set OBSERVER_ENV to check it"
else
  for pair in "KILLERS_RECEIVER_TOKEN:$K_TOKEN" "INSIDERS_RECEIVER_TOKEN:$I_TOKEN"; do
    name="${pair%%:*}"; expected="${pair#*:}"
    actual="$(sed -n "s/^$name=//p" "$OBS_ENV" | tail -n1 | tr -d '"'"'"'')"
    if [ -z "$actual" ]; then
      err "$name missing from $OBS_ENV — every signal it posts will 401"
    elif [ "$actual" != "$expected" ]; then
      err "$name in $OBS_ENV does not match the stack value"
    else
      ok "$name matches the receiver"
    fi
  done
fi

echo
echo "== images must be rebuilt, not reused =="
# killers-receiver and ft-dashboard are build: services pinned to a tag. A
# plain `up -d` recreates the container from the OLD image, which would look
# like a successful deploy while running unauthenticated code.
warn "deploy the receivers and dashboard with --build (see 2026-08-30-hardening-deploy.md)"

echo
if [ "$FAIL" -gt 0 ]; then
  echo "$FAIL blocking problem(s), $WARN warning(s) — do not deploy yet."
  exit 1
fi
echo "no blocking problems ($WARN warning(s))."
