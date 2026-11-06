#!/usr/bin/env python3
"""Create or renew a fleet bot's Hyperliquid API (agent) wallet (#252). Operator-run.

An API wallet trades for its master account but cannot withdraw. Hyperliquid caps its
validity at 180 days, so every bot's wallet needs renewing. This script generates the new
agent key, writes it straight into the VPS stack env (over ssh stdin, never printed or
stored on this Mac), then approves it with the master key read from the Keychain (see
hl_funds.py). Running containers keep their old values until they are recreated.

    hl-agent.sh status
    hl-agent.sh approve insiders upbit-fade-live HYPERLIQUID_UPBIT_FADE --drop HYPERLIQUID_INSIDERS

`approve` sets <PREFIX>_WALLET_ADDRESS (the master address) and <PREFIX>_PRIVATE_KEY (the
new agent key) and removes every line starting with each --drop prefix. It backs up the env
file on the VPS first and asks the terminal for a literal YES.
"""
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hl_funds import LABELS, address, confirm  # noqa: E402

VPS = "main-instance"
ENV_FILE = "/etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata/.env"
MAX_DAYS = 180
DAY_MS = 86_400_000
MARGIN_MS = 3_600_000  # stay an hour inside Hyperliquid's 180-day limit


def agent_name(name, now_ms, days):
    """`<name> valid_until <ms>`, the documented way to set an API wallet's expiry."""
    if not name or "valid_until" in name or name != name.strip():
        sys.exit(f"bad agent name {name!r}")
    if not 1 <= days <= MAX_DAYS:
        sys.exit(f"days must be 1..{MAX_DAYS}, got {days}")
    until = now_ms + days * DAY_MS - (MARGIN_MS if days == MAX_DAYS else 0)
    return f"{name} valid_until {until}", until


def env_prefix(prefix):
    if not prefix.replace("_", "").isalnum() or not prefix.isupper() or not prefix.startswith("HYPERLIQUID_"):
        sys.exit(f"bad env prefix {prefix!r}: expected HYPERLIQUID_<NAME>")
    return prefix


def env_edit_script(path, prefix, drops):
    """POSIX sh run as root on the VPS: back up `path`, drop the prefix's two keys and every
    `--drop` prefix line, append stdin (the new lines), keep mode 600, print the
    HYPERLIQUID_* names left. No secret is in the script; the new lines arrive on stdin."""
    names = [f"{prefix}_WALLET_ADDRESS", f"{prefix}_PRIVATE_KEY"] + [f"{d}_[A-Z0-9_]*" for d in drops]
    pattern = "^(" + "|".join(names) + ")="
    p = shlex.quote(path)
    return "\n".join([
        "set -eu",
        f"F={p}",
        'test -f "$F"',
        'cp -p "$F" "$F.bak-$(date -u +%Y%m%dT%H%M%SZ)"',
        f'{{ grep -v -E {shlex.quote(pattern)} "$F" || true; }} > "$F.new"',
        'if [ -s "$F.new" ] && [ -n "$(tail -c1 "$F.new")" ]; then echo >> "$F.new"; fi',
        'cat >> "$F.new"',
        'chmod 600 "$F.new"',
        'mv "$F.new" "$F"',
        "grep -oE '^HYPERLIQUID_[A-Z0-9_]+' \"$F\" | tr '\\n' ' '; echo",
    ])


def agents(info, addr):
    return info.post("/info", {"type": "extraAgents", "user": addr})


def show(info, label, addr):
    now = time.time() * 1000
    rows = agents(info, addr)
    print(label, addr, "no API wallets" if not rows else "")
    for a in rows:
        left = (a["validUntil"] - now) / DAY_MS
        print(f"  {a['name']!r} {a['address']} valid until "
              f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(a['validUntil'] / 1000))} "
              f"({left:.1f} days left)")


def main(argv):
    if not argv or argv[0] not in ("status", "approve"):
        sys.exit(__doc__)
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    if argv[0] == "status":
        for label in LABELS:
            show(info, label, address(label))
        return

    args, drops, days = list(argv[1:]), [], MAX_DAYS
    while "--drop" in args:
        i = args.index("--drop")
        drops.append(env_prefix(args[i + 1]))
        del args[i:i + 2]
    if "--days" in args:
        i = args.index("--days")
        days = int(args[i + 1])
        del args[i:i + 2]
    if len(args) != 3:
        sys.exit(__doc__)
    label, name, prefix = args[0], args[1], env_prefix(args[2])
    if label not in LABELS:
        sys.exit(f"unknown account label {label!r}; expected one of {', '.join(LABELS)}")
    addr = address(label)
    full_name, until = agent_name(name, int(time.time() * 1000), days)
    show(info, label, addr)
    print(f"\nNew API wallet {name!r} for {label} ({addr}), valid until "
          f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(until / 1000))}.")
    print(f"VPS {ENV_FILE}: set {prefix}_WALLET_ADDRESS and {prefix}_PRIVATE_KEY"
          + (f", remove {', '.join(d + '_*' for d in drops)}" if drops else "") + " (backup first).")
    if not confirm("Go ahead?"):
        sys.exit("Cancelled, nothing changed.")

    from eth_account import Account
    agent = Account.create()
    k = agent.key.hex()
    lines = f"{prefix}_WALLET_ADDRESS={addr}\n{prefix}_PRIVATE_KEY={k if k.startswith('0x') else '0x' + k}\n"
    del k
    remote = "sudo -n sh -c " + shlex.quote(env_edit_script(ENV_FILE, prefix, drops))
    done = subprocess.run(["ssh", VPS, remote], input=lines, text=True, capture_output=True)
    del lines
    if done.returncode != 0:
        sys.exit(f"Writing the VPS env failed, nothing approved: {done.stderr.strip()}")
    print("VPS env now has:", done.stdout.strip())

    from hyperliquid.exchange import Exchange
    from hyperliquid.utils.signing import get_timestamp_ms, sign_agent
    key = subprocess.run(["security", "find-generic-password", "-s",
                          f"master-trader.hyperliquid.{label}.master", "-w"],
                         capture_output=True, text=True, check=True).stdout.strip()
    master = Account.from_key(key)
    del key
    if master.address.lower() != addr.lower():
        sys.exit(f"Keychain key for {label} does not match {addr}; the VPS env holds an "
                 "unapproved key now; re-run after fixing the Keychain item.")
    ex = Exchange(master, constants.MAINNET_API_URL, account_address=addr)
    nonce = get_timestamp_ms()
    action = {"type": "approveAgent", "agentAddress": agent.address, "agentName": full_name,
              "nonce": nonce}
    result = ex._post_action(action, sign_agent(master, action, True), nonce)
    print("Approve result:", result)
    time.sleep(2)
    found = [a for a in agents(info, addr) if a["address"].lower() == agent.address.lower()]
    if not found:
        sys.exit("The new API wallet is not listed yet; check `hl-agent.sh status` before "
                 "recreating any bot.")
    show(info, label, addr)
    print("\nDone. The running bot keeps its old env until it is recreated (see its runbook).")


if __name__ == "__main__":
    main(sys.argv[1:])
