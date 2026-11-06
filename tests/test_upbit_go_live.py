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
FAKE_CURL = r"""#!/usr/bin/env python3
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
        out = st["trades"]
elif url == "http://127.0.0.1:8104/healthz":
    new = st["gateway_new"]
    clients = ["accounting", "killers", "short"] + (["upbit"] if new and st["new_has_upbit"] else [])
    status = st["new_status"] if new else "ok"
    out = {"status": status, "faults": 0 if status == "ok" else 3, "observed_at": 1, "queued": 0,
           "weight_last_minute": st["weight"],
           "clients": {c: {"ok": 5, "cached": 0, "rate_limited": 0, "queue_timeout": 0,
                           "upstream_error": 0, "transport_error": 0 if status == "ok" else 3}
                       for c in clients}}
    if "upbit" in clients:
        out["slice_weight_last_minute"] = {"upbit": 0}
elif url == "https://api.hyperliquid.xyz/info":
    kind = json.loads(data)["type"]
    out = {"clearinghouseState": {"assetPositions": st["positions"]}, "frontendOpenOrders": st["orders"],
           "meta": {"universe": [{"name": "HYPE", "szDecimals": 2}]}}[kind]
json.dump(st, open(st_path, "w"))
if out is None:
    sys.exit(f"fake curl: unexpected {method} {url}")
print(json.dumps(out))
"""

FAKE_DOCKER = r"""#!/usr/bin/env python3
import json, os, sys
st_path = os.environ["FAKE_STATE"]
st = json.load(open(st_path))
a = sys.argv[1:]
st["docker"].append(" ".join(a))
out, rc = "", 0
if a[0] == "inspect":
    out = {"{{.Config.Image}}": "ft_userdata-hl-gateway:latest", "{{.Image}}": "sha256:old",
           "{{.State.StartedAt}}": "2026-11-06T22:00:00Z"}[a[2]]
elif a[0] == "compose":
    if a[-1] == "hl-gateway" and "up" in a:
        st["gateway_new"] = True
elif a[0] == "logs":
    if a[1] in st["logs_fail"]:
        rc = 1
    out = st["logs"].get(a[1], "")
elif a[0] == "exec":
    rest = a[2:]
    if rest[0] == "printenv":
        out = {"FREQTRADE__API_SERVER__USERNAME": "u", "FREQTRADE__API_SERVER__PASSWORD": "p",
               "FREQTRADE__EXCHANGE__WALLET_ADDRESS": "0xkillers"}[rest[1]]
    elif rest[:2] == ["cat", "/state/portfolio_peak.json"]:
        out = json.dumps({"triggered": st["killers"] == "paused" and st["trip_after_pause"]})
    elif rest[0] == "python":
        out = "0"
json.dump(st, open(st_path, "w"))
if out:
    print(out)
sys.exit(rc)
"""

FAKE_DATE = r"""#!/bin/sh
f="$FAKE_CLOCK"
case "$*" in
  *+%s*) n=$(cat "$f"); echo $((n + 20)) > "$f"; echo "$n" ;;
  *+%H%M*) echo "${FAKE_HHMM:-1000}" ;;
  *) /bin/date "$@" ;;
esac
"""

FAKE_STATE_FIELD = r"""#!/usr/bin/env python3
import json, os, sys
st = json.load(open(os.environ["FAKE_STATE"]))
sys.exit(0 if st[sys.argv[0].rsplit("/", 1)[1]] else 1)
"""

# One open long, its stop resting on Hyperliquid at Freqtrade's own trigger.
TRADE = {"pair": "HYPE/USDC:USDC", "is_short": False, "amount": 0.44, "stop_loss_abs": 72.0,
         "liquidation_price": None,
         "orders": [{"status": "open", "ft_order_side": "stoploss", "order_id": "111"}]}
POSITION = {"position": {"coin": "HYPE", "szi": "0.44", "positionValue": "17.6"}}
STOP = {"oid": 111, "coin": "HYPE", "side": "A", "reduceOnly": True, "isTrigger": True,
        "triggerPx": "72.0", "sz": "0.44"}


@pytest.fixture
def vps(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    fakes = {"curl": FAKE_CURL, "docker": FAKE_DOCKER, "date": FAKE_DATE,
             "flock": FAKE_STATE_FIELD.replace('st[sys.argv[0].rsplit("/", 1)[1]]',
                                               '"-u" in sys.argv or not st["lock_busy"]'),
             "systemctl": FAKE_STATE_FIELD.replace('st[sys.argv[0].rsplit("/", 1)[1]]',
                                                   'st["trigger_active"]'),
             "sudo": '#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n',
             "sleep": "#!/bin/sh\nexit 0\n"}
    for name, body in fakes.items():
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
    trigger_log = home / "master-trader/research/upbit_fade_live/data/trigger.log"
    trigger_log.write_text("start\n")
    (tmp_path / "code/ft_userdata").mkdir(parents=True)
    state = tmp_path / "state.json"
    clock = tmp_path / "clock"
    clock.write_text("1800000000")
    kill = home / "master-trader/research/upbit_fade_live/data/KILL"
    owner = home / "backups/go-live.owner"
    owner.parent.mkdir()

    def run(phase="gateway", owned_by="T", hhmm="1000", **overrides):
        if owned_by is not None:
            owner.write_text(owned_by + "\n")
        st = {"killers": "running", "posts": [], "docker": [], "weight": 100,
              "gateway_new": False, "new_has_upbit": True, "new_status": "ok",
              "trades": [], "positions": [], "orders": [], "logs": {}, "logs_fail": [],
              "trip_after_pause": False, "lock_busy": False, "trigger_active": True}
        st.update(overrides)
        state.write_text(json.dumps(st))
        env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(home),
               "FAKE_STATE": str(state), "FAKE_CLOCK": str(clock),
               "UPBIT_GO_LIVE_CODE": str(tmp_path / "code"), "FAKE_HHMM": hhmm}
        done = subprocess.run(["bash", str(REMOTE), phase, "T"], env=env, text=True,
                              capture_output=True, timeout=60)
        rc = int((home / f"backups/go-live-T/{phase}.rc").read_text().strip())
        return done, rc, json.loads(state.read_text())

    run.kill = kill
    run.owner = owner
    return run


def _recreated(st):
    return any("up -d --no-deps hl-gateway" in c for c in st["docker"])


def test_gateway_phase_deploys_and_restores_entries(vps):
    done, rc, st = vps()
    assert rc == 0 == done.returncode, done.stdout + done.stderr
    assert _recreated(st)
    assert st["posts"] == ["stopentry", "start"]
    assert st["killers"] == "running"
    assert vps.kill.exists(), "the trigger stays paused until the bot phase is done"
    assert vps.owner.read_text().strip() == "T", "the run keeps its claim until resume"


def test_open_protected_trade_is_checked_before_and_after(vps):
    done, rc, st = vps(trades=[TRADE], positions=[POSITION], orders=[STOP])
    assert rc == 0, done.stdout
    assert done.stdout.count("HYPE OK") == 2
    assert st["posts"] == ["stopentry", "start"]


@pytest.mark.parametrize("why, overrides", [
    ("gateway busy", {"weight": 450}),
    ("stop not at Freqtrade's trigger", {"trades": [TRADE], "positions": [POSITION],
                                         "orders": [{**STOP, "triggerPx": "71.0"}]}),
    ("position without a trade", {"positions": [POSITION], "orders": [STOP]}),
    ("receiver handling a signal", {"logs": {"killers-receiver": 'INFO: x - "POST /event HTTP/1.1" 200 OK'}}),
    ("receiver log unreadable", {"logs_fail": ["killers-receiver"]}),
    ("the US open began during the checks", {"hhmm": "1320"}),
])
def test_stop_before_the_recreate_restores_killers_entries(vps, why, overrides):
    done, rc, st = vps(**overrides)
    assert rc == 1, why
    assert not _recreated(st), why
    assert st["posts"] == ["stopentry", "start"], why
    assert st["killers"] == "running", why
    assert vps.kill.exists()
    assert "Stopped BEFORE the recreate" in done.stdout
    assert not vps.owner.exists(), "a clean stop releases the run's claim"


@pytest.mark.parametrize("why, overrides", [
    ("no upbit client", {"new_has_upbit": False}),
    ("request failures persist", {"new_status": "warning"}),
    ("forced exit logged", {"logs": {"ft-killers-scalp": "Exiting the trade forcefully"}}),
    ("Killers log unreadable", {"logs_fail": ["ft-killers-scalp"]}),
])
def test_stop_after_the_recreate_keeps_killers_paused(vps, why, overrides):
    done, rc, st = vps(**overrides)
    assert rc == 1, why
    assert _recreated(st), why
    assert st["posts"] == ["stopentry"], f"{why}: never resume entries on an unverified gateway"
    assert st["killers"] == "paused"
    assert vps.kill.exists()
    assert "Killers entries stay PAUSED" in done.stdout
    assert vps.owner.exists(), "no new run until someone has looked"


def test_breaker_triggered_since_the_pause_keeps_killers_paused(vps):
    done, rc, st = vps(trip_after_pause=True)
    assert rc == 1
    assert st["posts"] == ["stopentry"]
    assert "Restoring Killers entries did not confirm" in done.stdout


def test_a_paused_killers_is_never_resumed(vps):
    done, rc, st = vps(killers="paused")
    assert rc == 1
    assert st["posts"] == [] and not _recreated(st)


def test_a_running_go_live_phase_blocks_another(vps):
    done, rc, st = vps(lock_busy=True)
    assert rc == 1
    assert st["posts"] == [] and st["docker"] == []
    assert not vps.kill.exists()


def test_failed_resume_puts_the_kill_file_back(vps):
    vps.kill.touch()
    done, rc, st = vps("resume", trigger_active=False)
    assert rc == 1
    assert vps.kill.exists()
    assert "the KILL file is back" in done.stdout


def test_resume_arms_the_trigger(vps):
    vps.kill.touch()
    done, rc, st = vps("resume")
    assert rc == 0, done.stdout
    assert not vps.kill.exists()


def test_a_phase_of_another_run_touches_nothing(vps):
    """Codex R2: run B must not act inside run A's go-live, nor A resume after B intervened."""
    for phase in ("gateway", "bot", "resume"):
        for kill in (False, True):
            vps.kill.unlink(missing_ok=True)
            if kill:
                vps.kill.touch()
            done, rc, st = vps(phase, owned_by="OTHER")
            assert rc == 1, phase
            assert st["posts"] == [] and st["docker"] == [], phase
            assert vps.kill.exists() is kill, f"{phase}: a rejected phase leaves KILL as it was"
            assert vps.owner.read_text().strip() == "OTHER"
            assert "does not own the go-live" in done.stdout


def test_run_ids_are_unique_per_invocation():
    script = (LIVE / "go-live.sh").read_text()
    line = next(line for line in script.splitlines() if line.startswith("T="))
    ids = {subprocess.run(["bash", "-c", line + '; printf %s "$T"'], capture_output=True, text=True,
                          check=True).stdout for _ in range(5)}
    assert len(ids) == 5, "two runs started in the same second must not share an id"


def test_pause_claims_the_run_once(vps):
    done, rc, st = vps("pause", owned_by=None)
    assert rc == 0 and vps.kill.exists()
    assert vps.owner.read_text().strip() == "T"
    vps.kill.unlink()
    vps.owner.write_text("OTHER\n")
    done, rc, st = vps("pause", owned_by=None)
    assert rc == 1 and not vps.kill.exists()
    assert "holds" in done.stdout


def test_complete_resume_releases_the_claim(vps):
    vps.kill.touch()
    done, rc, st = vps("resume")
    assert rc == 0 and not vps.owner.exists()
