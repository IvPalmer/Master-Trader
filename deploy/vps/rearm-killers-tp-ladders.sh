#!/usr/bin/env bash
# Re-arm stuck Killers TP ladders on the VPS.
#
# For each given receiver pos_id this script backs up the receiver database,
# verifies the ladder is in the stuck shape (no 'active'/'filled'/'placing'/
# 'unknown' rows, no exchange order ids, position still open) and DELETES its
# target_orders rows. The receiver's delayed-fill reconciler (reconcile_loop,
# 60 s cadence) then treats the position as unarmed and rebuilds the ladder
# with tp_plan.executable_targets, submitting ONLY the first executable group
# as a reduce-only limit exit through Freqtrade /forceexit.
#
# This is an order-placing action once the receiver picks it up. Run it
# yourself, with the dashboard open. Usage:
#
#   sudo deploy/vps/rearm-killers-tp-ladders.sh --yes 3 8 9
#
# Without --yes it only prints the current rows and the backup path.
set -euo pipefail

DB=/var/lib/docker/volumes/compose-bypass-mobile-port-fbk1m6_killers_receiver_state/_data/receiver-hyperliquid.sqlite
BACKUP_DIR=/home/ubuntu/master-trader/state/backups

CONFIRM=0
if [ "${1:-}" = "--yes" ]; then CONFIRM=1; shift; fi
if [ $# -lt 1 ]; then
  echo "usage: $0 [--yes] POS_ID [POS_ID...]" >&2
  exit 64
fi
for id in "$@"; do
  case "$id" in ''|*[!0-9]*) echo "pos_id must be an integer: $id" >&2; exit 64;; esac
done

mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_DIR/receiver-hyperliquid.$STAMP.sqlite"
python3 - "$DB" "$BACKUP" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
print(f"backup written: {sys.argv[2]}")
EOF

IDS=$(IFS=,; echo "$*")
python3 - "$DB" "$CONFIRM" "$IDS" <<'EOF'
import sqlite3, sys
db, confirm, ids = sys.argv[1], sys.argv[2] == "1", [int(x) for x in sys.argv[3].split(",")]
conn = sqlite3.connect(db, isolation_level=None); conn.row_factory = sqlite3.Row
problems = []
for pos_id in ids:
    pos = conn.execute("SELECT pos_id, pair, state, ft_trade_id, targets_remaining FROM positions WHERE pos_id=?", (pos_id,)).fetchone()
    rows = conn.execute("SELECT idx, price, amount, state, ft_order_id, notes FROM target_orders WHERE pos_id=? ORDER BY idx", (pos_id,)).fetchall()
    print(f"\npos_id={pos_id}: {dict(pos) if pos else 'MISSING'}")
    for r in rows:
        print("   ", dict(r))
    if pos is None or pos["state"] != "open" or pos["ft_trade_id"] is None:
        problems.append(f"pos_id={pos_id} is not an open position with a Freqtrade trade")
    elif not pos["targets_remaining"]:
        problems.append(f"pos_id={pos_id} has no targets_remaining; the reconciler could never re-arm it")
    states = {r["state"] for r in rows}
    if not rows:
        problems.append(f"pos_id={pos_id} has no ladder rows (already unarmed)")
    if states & {"active", "filled", "placing", "unknown"}:
        problems.append(f"pos_id={pos_id} has live/uncertain rows {sorted(states)}; reconcile manually instead")
    if any(r["ft_order_id"] for r in rows):
        problems.append(f"pos_id={pos_id} has rows with exchange order ids; do not delete")
if problems:
    print("\nREFUSING:"); [print("  -", p) for p in problems]; sys.exit(1)
if not confirm:
    print("\nDry run only. Re-run with --yes to delete these rows and let the receiver re-arm.")
    sys.exit(0)
conn.execute("BEGIN IMMEDIATE")
n = 0
for pos_id in ids:
    n += conn.execute("DELETE FROM target_orders WHERE pos_id=?", (pos_id,)).rowcount
conn.execute("COMMIT")
print(f"\ndeleted {n} target_orders rows; the receiver re-arms within ~60 s (reconcile_loop)")
EOF

if [ "$CONFIRM" = "1" ]; then
  echo
  echo "Watching killers-receiver for the re-arm (Ctrl-C to stop):"
  docker logs -f --since 5s killers-receiver 2>&1 | grep --line-buffered -E "RECONCILE\] armed|PHASE2" || true
fi
