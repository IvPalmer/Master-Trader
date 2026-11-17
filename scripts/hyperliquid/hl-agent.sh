#!/bin/sh
# Operator-run wrapper for hl_agent.py (#252). Same SDK and Python runtime as hl-funds.sh;
# override with HL_SDK / HL_PY.
HERE=$(cd "$(dirname "$0")" && pwd)
HL_PY=${HL_PY:-/Users/palmer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}
HL_SDK=${HL_SDK:-/Users/palmer/.cache/master-trader/hl-sdk}
PYTHONPATH="$HL_SDK" exec "$HL_PY" "$HERE/hl_agent.py" "$@"
