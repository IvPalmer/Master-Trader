"""go-live.sh / go_live_remote.sh (#252): the one-command go-live for the Upbit pilot.

The gateway phase runs against fake docker/curl/sudo on PATH: it must restore Killers
entries when it stops before the recreate, keep them paused when it stops after, and
leave the pilot trigger paused either way.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "research" / "upbit_fade_live"
REMOTE = LIVE / "go_live_remote.sh"
pytestmark = pytest.mark.skipif(not shutil.which("jq") or not shutil.which("bash"),
                                reason="needs bash and jq")


def _python_block(text, opener, indent):
    """The lines of the `<<'PY'` heredoc opened on the line containing `opener`."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if opener in line)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PY")
    return [line[indent:] for line in lines[start + 1:end]]


def test_protected_check_matches_the_runbook_verbatim():
    runbook = _python_block((LIVE / "GO-LIVE.md").read_text(), "python3 - killers-status-before.json", 2)
    script = _python_block(REMOTE.read_text(), 'python3 - "$@" <<', 0)
    assert script == runbook and len(script) > 30


def test_scripts_parse_and_lint():
    for path in (LIVE / "go-live.sh", REMOTE):
        subprocess.run(["bash", "-n", str(path)], check=True)
        assert os.access(path, os.X_OK)
    if shutil.which("shellcheck"):
        subprocess.run(["shellcheck", "-S", "warning", str(LIVE / "go-live.sh"), str(REMOTE)], check=True)


# ── fake VPS ─────────────────────────────────────────────────────────────────
FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
st_path = os.environ["FAKE_STATE"]
st = json.load(open(st_path))
args = sys.argv[1:]
method = args[args.index("-X") + 1] if "-X" in args else "GET"
data = args[args.index("-d") + 1] if "-d" in args else None
url = next(a for a in args if a.startswith("http"))
out = None
if url.startswith("http://127.0.0.1:8099/api/v1/"):
    ep = url.rsplit("/api/v1/", 1)[1]
    if ep == "show_config":
        out = {"state": st["killers"]}
    elif ep in ("stopentry", "start") and method == "POST":
        st["killers"] = "paused" if ep == "stopentry" else "running"
        st["posts"].append(ep)
        out = {"status": ep}
    elif ep == "trades/0/open-order" and method == "DELETE":
        out = {"error": "Error querying /api/v1/trades/0/open-order: Invalid trade_id."}
    elif ep == "status":
        out = []
elif url == "http://127.0.0.1:8104/healthz":
    clients = ["accounting", "killers", "short"] + (["upbit"] if st["gateway_new"] and st["new_has_upbit"] else [])
    out = {"status": "ok", "faults": 0, "observed_at": 1, "queued": 0,
           "weight_last_minute": st["weight"],
           "clients": {c: {"ok": 5, "cached": 0, "rate_limited": 0, "queue_timeout": 0,
                           "upstream_error": 0, "transport_error": 0} for c in clients}}
    if "upbit" in clients:
        out["slice_weight_last_minute"] = {"upbit": 0}
elif url == "https://api.hyperliquid.xyz/info":
    kind = json.loads(data)["type"]
    out = {"clearinghouseState": {"assetPositions": []}, "frontendOpenOrders": [],
           "meta": {"universe": []}}[kind]
json.dump(st, open(st_path, "w"))
if out is None:
    sys.exit(f"fake curl: unexpected {method} {url}")
print(json.dumps(out))
'''

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
st_path = os.environ["FAKE_STATE"]
st = json.load(open(st_path))
a = sys.argv[1:]
st["docker"].append(" ".join(a))
out = ""
if a[0] == "inspect":
    out = {"{{.Config.Image}}": "ft_userdata-hl-gateway:latest", "{{.Image}}": "sha256:old",
           "{{.State.StartedAt}}": "2026-11-06T22:00:00Z"}[a[2]]
elif a[0] == "compose":
    if a[-1] == "hl-gateway" and "up" in a:
        st["gateway_new"] = True
elif a[0] == "exec":
    rest = a[2:]
    if rest[0] == "printenv":
        out = {"FREQTRADE__API_SERVER__USERNAME": "u", "FREQTRADE__API_SERVER__PASSWORD": "p",
               "FREQTRADE__EXCHANGE__WALLET_ADDRESS": "0xkillers"}[rest[1]]
    elif rest[:2] == ["cat", "/state/portfolio_peak.json"]:
        out = json.dumps({"triggered": False})
    elif rest[0] == "python":
        out = "0"
json.dump(st, open(st_path, "w"))
if out:
    print(out)
'''

FAKE_DATE = r'''#!/bin/sh
f="$FAKE_CLOCK"
case "$*" in
  *+%s*) n=$(cat "$f"); echo $((n + 20)) > "$f"; echo "$n" ;;
  *+%H%M*) echo 1000 ;;
  *) /bin/date "$@" ;;
esac
'''


@pytest.fixture
def vps(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in {"curl": FAKE_CURL, "docker": FAKE_DOCKER, "date": FAKE_DATE,
                       "sudo": '#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n',
                       "sleep": "#!/bin/sh\nexit 0\n"}.items():
        path = bin_ / name
        path.write_text(body)
        path.chmod(0o755)
    home = tmp_path / "home"
    for d in ("master-trader/research/upbit_fade_live/data", "master-trader/research/upbit_fade_forward/data"):
        (home / d).mkdir(parents=True)
    monitor = home / "master-trader/research/upbit_fade_forward/data/monitor.log"
    monitor.write_text("old\n")
    old = time.time() - 3600
    os.utime(monitor, (old, old))
    (tmp_path / "code/ft_userdata").mkdir(parents=True)
    state = tmp_path / "state.json"
    clock = tmp_path / "clock"
    clock.write_text("1800000000")

    def run(**overrides):
        st = {"killers": "running", "posts": [], "docker": [], "weight": 100,
              "gateway_new": False, "new_has_upbit": True}
        st.update(overrides)
        state.write_text(json.dumps(st))
        env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(home),
               "FAKE_STATE": str(state), "FAKE_CLOCK": str(clock),
               "UPBIT_GO_LIVE_CODE": str(tmp_path / "code")}
        done = subprocess.run(["bash", str(REMOTE), "gateway", "T"], env=env, text=True,
                              capture_output=True, timeout=60)
        rc = (home / "backups/go-live-T/gateway.rc").read_text().strip()
        kill = (home / "master-trader/research/upbit_fade_live/data/KILL").exists()
        return done, int(rc), json.loads(state.read_text()), kill

    return run


def _recreated(st):
    return any("up -d --no-deps hl-gateway" in c for c in st["docker"])


def test_gateway_phase_deploys_and_restores_entries(vps):
    done, rc, st, kill = vps()
    assert rc == 0 == done.returncode, done.stdout + done.stderr
    assert _recreated(st)
    assert st["posts"] == ["stopentry", "start"]
    assert st["killers"] == "running"
    assert kill, "the trigger stays paused until the bot phase is done"
    assert "PROTECTED" in done.stdout


def test_stop_before_the_recreate_restores_killers_entries(vps):
    done, rc, st, kill = vps(weight=450)
    assert rc == 1
    assert not _recreated(st), "busy gateway: never recreate"
    assert st["posts"] == ["stopentry", "start"]
    assert st["killers"] == "running"
    assert kill
    assert "Stopped BEFORE the recreate" in done.stdout


def test_stop_after_the_recreate_keeps_killers_paused(vps):
    done, rc, st, kill = vps(new_has_upbit=False)
    assert rc == 1
    assert _recreated(st)
    assert st["posts"] == ["stopentry"], "never resume entries on an unverified gateway"
    assert st["killers"] == "paused"
    assert kill
    assert "Killers entries stay PAUSED" in done.stdout


def test_a_paused_killers_is_never_resumed(vps):
    done, rc, st, kill = vps(killers="paused")
    assert rc == 1
    assert st["posts"] == [] and not _recreated(st)
    assert st["killers"] == "paused"
