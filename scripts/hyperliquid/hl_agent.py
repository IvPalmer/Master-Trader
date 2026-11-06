#!/usr/bin/env python3
"""Create or renew a fleet bot's Hyperliquid API (agent) wallet (#252). Operator-run.

An API wallet trades for its master account but cannot withdraw. Hyperliquid caps its
validity at 180 days, so every bot's wallet needs renewing. `approve` checks the master key
from the Keychain first (see hl_funds.py), generates the new agent key, writes it straight
into the VPS stack env (over ssh stdin, never printed or stored on this Mac), then approves
it. Running containers keep their old values until they are recreated.

    hl-agent.sh status
    hl-agent.sh approve insiders upbit-fade-live HYPERLIQUID_UPBIT_FADE --drop HYPERLIQUID_INSIDERS
    hl-agent.sh env-set HL_UPBIT_GATEWAY_CLIENT=upbit HYPERLIQUID_UPBIT_FADE_DRY_RUN=false

`approve <label> <name> <PREFIX> [--drop <PREFIX>]... [--days N] [--replace]` sets
<PREFIX>_WALLET_ADDRESS (the master address) and <PREFIX>_PRIVATE_KEY (the new agent key)
and removes every line starting with each --drop prefix. Approving a name that already
exists replaces that wallet at once, which cuts off a bot still signing with it, so it is
refused unless --replace is given; renew a running bot under a new name, then recreate it.
`env-set` writes non-secret NAME=VALUE pairs. Both edit the env file in one locked step
(backup first, mode 600, atomic replace) and ask the terminal for a literal YES.
"""
import hashlib
import re
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
MAX_NAMED = 3  # Hyperliquid: one unnamed and up to three named API wallets per account
DAY_MS = 86_400_000
MARGIN_MS = 3_600_000  # stay an hour inside Hyperliquid's 180-day limit
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/-]*$")


def agent_name(name, now_ms, days):
    """`<name> valid_until <ms>`, the documented way to set an API wallet's expiry."""
    if not name or "valid_until" in name or name != name.strip():
        sys.exit(f"bad agent name {name!r}")
    if not 1 <= days <= MAX_DAYS:
        sys.exit(f"days must be 1..{MAX_DAYS}, got {days}")
    until = now_ms + days * DAY_MS - (MARGIN_MS if days == MAX_DAYS else 0)
    return f"{name} valid_until {until}", until


def env_prefix(prefix):
    if not NAME_RE.match(prefix) or not prefix.startswith("HYPERLIQUID_"):
        sys.exit(f"bad env prefix {prefix!r}: expected HYPERLIQUID_<NAME>")
    return prefix


def env_pairs(pairs):
    """Non-secret NAME=VALUE pairs for env-set; secrets only go through `approve`."""
    out = []
    for p in pairs:
        name, sep, value = p.partition("=")
        if not sep or not NAME_RE.match(name) or not VALUE_RE.match(value):
            sys.exit(f"bad pair {p!r}: expected NAME=VALUE with a plain value")
        if name.endswith(("PRIVATE_KEY", "SECRET", "PASSWORD", "TOKEN")):
            sys.exit(f"{name} looks like a secret; set keys only with `approve`")
        out.append((name, value))
    return out


def env_edit_script(path, remove):
    """POSIX sh run as root on the VPS. Under a lock, with umask 077: back up `path` to a
    unique file, copy it without the lines whose names match `remove` (regex alternatives),
    append stdin (the new lines), and atomically replace `path` (mode 600). Any read or
    write error aborts before the replace. Prints BACKUP=<path> and NAMES=<HYPERLIQUID_*
    names left>. No secret is in the script; new lines arrive on stdin."""
    pattern = "^(" + "|".join(remove) + ")="
    return "\n".join([
        "set -eu",
        "umask 077",
        f"F={shlex.quote(path)}",
        'test -f "$F"',
        'exec 9>"$F.lock"',
        'flock -w 30 9 || { echo "another env edit holds $F.lock" >&2; exit 1; }',
        'D=$(dirname "$F")',
        'T=$(mktemp "$D/.env.new.XXXXXX")',
        "trap 'rm -f \"$T\"' EXIT",
        'B=$(mktemp "$F.bak-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")',
        'cp -p "$F" "$B"',
        f'if grep -v -E {shlex.quote(pattern)} "$F" > "$T"; then :; else rc=$?; [ "$rc" -eq 1 ] || exit "$rc"; fi',
        'if [ -s "$T" ] && [ -n "$(tail -c1 "$T")" ]; then echo >> "$T"; fi',
        'cat >> "$T"',
        'chmod 600 "$T"',
        'mv "$T" "$F"',
        "trap - EXIT",
        'echo "BACKUP=$B"',
        "printf 'NAMES='; grep -oE '^HYPERLIQUID_[A-Z0-9_]+' \"$F\" | tr '\\n' ' '; echo",
    ])


def parse_edit_output(stdout):
    out = dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)
    return out.get("BACKUP", "?"), out.get("NAMES", "").strip()


def write_env(remove, lines):
    remote = "sudo -n sh -c " + shlex.quote(env_edit_script(ENV_FILE, remove))
    done = subprocess.run(["ssh", VPS, remote], input=lines, text=True, capture_output=True)
    if done.returncode != 0:
        sys.exit(f"Writing the VPS env failed; it is unchanged: {done.stderr.strip()}")
    return parse_edit_output(done.stdout)


def stored_line_digest(name):
    """sha256 of the `name=` line in the VPS env, computed there (the value never leaves)."""
    cmd = f"sudo -n grep -E {shlex.quote('^' + name + '=')} {shlex.quote(ENV_FILE)} | sha256sum"
    out = subprocess.run(["ssh", VPS, cmd], text=True, capture_output=True)
    return out.stdout.split()[0] if out.returncode == 0 and out.stdout else None


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
    return rows


def take(args, flag, has_value=True):
    """Remove every `flag [value]` from args; return the values (or a count for switches)."""
    vals = []
    while flag in args:
        i = args.index(flag)
        if has_value:
            if i + 1 >= len(args):
                sys.exit(f"{flag} needs a value")
            vals.append(args[i + 1])
            del args[i:i + 2]
        else:
            vals.append(True)
            del args[i]
    return vals


def approve(info, constants, args):
    drops = [env_prefix(d) for d in take(args, "--drop")]
    days = [int(d) for d in take(args, "--days")] or [MAX_DAYS]
    replace = bool(take(args, "--replace", has_value=False))
    if len(args) != 3:
        sys.exit(__doc__)
    label, name, prefix = args[0], args[1], env_prefix(args[2])
    if label not in LABELS:
        sys.exit(f"unknown account label {label!r}; expected one of {', '.join(LABELS)}")
    addr = address(label)
    full_name, until = agent_name(name, int(time.time() * 1000), days[-1])
    rows = show(info, label, addr)
    same = [a for a in rows if a["name"] == name]
    if same and not replace:
        sys.exit(f"An API wallet named {name!r} exists. Approving the same name replaces it at "
                 "once and cuts off any bot still signing with it. Use a new name (then "
                 "recreate the bot), or pass --replace if nothing uses it.")
    if not same and len([a for a in rows if a["name"]]) >= MAX_NAMED:
        sys.exit(f"{label} already has {MAX_NAMED} named API wallets; replace one with --replace.")

    # Preflight: master key and SDK before anything is written.
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils.signing import get_timestamp_ms, sign_agent
    got = subprocess.run(["security", "find-generic-password", "-s",
                          f"master-trader.hyperliquid.{label}.master", "-w"],
                         capture_output=True, text=True)
    if got.returncode != 0:
        sys.exit(f"Cannot read the {label} master key from the Keychain; nothing changed.")
    master = Account.from_key(got.stdout.strip())
    del got
    if master.address.lower() != addr.lower():
        sys.exit(f"Keychain key for {label} does not match {addr}; nothing changed.")
    ex = Exchange(master, constants.MAINNET_API_URL, account_address=addr)

    print(f"\nNew API wallet {name!r} for {label} ({addr}), valid until "
          f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(until / 1000))}"
          + (" (REPLACES the existing one)" if same else "") + ".")
    print(f"VPS {ENV_FILE}: set {prefix}_WALLET_ADDRESS and {prefix}_PRIVATE_KEY"
          + (f", remove {', '.join(d + '_*' for d in drops)}" if drops else "") + " (backup first).")
    if not confirm("Go ahead?"):
        sys.exit("Cancelled, nothing changed.")

    agent = Account.create()
    k = agent.key.hex()
    key_line = f"{prefix}_PRIVATE_KEY={k if k.startswith('0x') else '0x' + k}"
    del k
    digest = hashlib.sha256((key_line + "\n").encode()).hexdigest()
    remove = [f"{prefix}_WALLET_ADDRESS", f"{prefix}_PRIVATE_KEY"] + [f"{d}_[A-Z0-9_]*" for d in drops]
    backup, names = write_env(remove, f"{prefix}_WALLET_ADDRESS={addr}\n{key_line}\n")
    del key_line
    print("VPS env now has:", names)
    print("Backup on the VPS:", backup)
    pending = (f"The VPS env now holds a key that is NOT approved. Do not recreate the bot. "
               f"Either re-run this command, or restore the backup: "
               f"sudo cp -p {backup} {ENV_FILE}")

    nonce = get_timestamp_ms()
    action = {"type": "approveAgent", "agentAddress": agent.address, "agentName": full_name,
              "nonce": nonce}
    try:
        result = ex._post_action(action, sign_agent(master, action, True), nonce)
    except Exception as e:  # network or SDK error: the outcome is unknown
        sys.exit(f"Approval outcome UNKNOWN ({type(e).__name__}: {e}). Run `hl-agent.sh status` "
                 f"and look for {agent.address}. If it is listed, the env is correct. If not: {pending}")
    if not (isinstance(result, dict) and result.get("status") == "ok"):
        sys.exit(f"Approval REJECTED: {result}. {pending}")
    print("Approve result:", result)

    found = []
    for _ in range(5):
        time.sleep(2)
        found = [a for a in agents(info, addr) if a["address"].lower() == agent.address.lower()]
        if found:
            break
    if stored_line_digest(f"{prefix}_PRIVATE_KEY") != digest:
        sys.exit("The key stored on the VPS is not the one just approved (another edit ran?). "
                 "Do not recreate the bot; re-run this command.")
    if not found:
        sys.exit(f"Approved, but {agent.address} is not listed yet; check `hl-agent.sh status` "
                 "before recreating any bot.")
    show(info, label, addr)
    print("\nDone: the VPS env holds the approved key. The running bot keeps its old env until "
          "it is recreated (see its runbook).")


def env_set(args):
    pairs = env_pairs(args)
    if not pairs:
        sys.exit(__doc__)
    print(f"VPS {ENV_FILE}: set " + ", ".join(f"{n}={v}" for n, v in pairs) + " (backup first).")
    if not confirm("Go ahead?"):
        sys.exit("Cancelled, nothing changed.")
    backup, names = write_env([n for n, _ in pairs], "".join(f"{n}={v}\n" for n, v in pairs))
    print("VPS env now has:", names)
    print("Backup on the VPS:", backup)


def main(argv):
    if not argv or argv[0] not in ("status", "approve", "env-set"):
        sys.exit(__doc__)
    if argv[0] == "env-set":
        return env_set(argv[1:])
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    if argv[0] == "status":
        for label in LABELS:
            show(info, label, address(label))
        return
    approve(info, constants, list(argv[1:]))


if __name__ == "__main__":
    main(sys.argv[1:])
