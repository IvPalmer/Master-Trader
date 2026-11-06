"""Pure helpers of the operator API-wallet script (#252); no SDK, Keychain or network."""
import importlib.util
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[1] / "scripts" / "hyperliquid"
SPEC = importlib.util.spec_from_file_location("hl_agent", DIR / "hl_agent.py")
hl_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hl_agent)

NOW = 1_793_900_000_000


def test_agent_name_carries_the_expiry_and_stays_inside_180_days():
    name, until = hl_agent.agent_name("upbit-fade-live", NOW, 180)
    assert name == f"upbit-fade-live valid_until {until}"
    assert until == NOW + 180 * 86_400_000 - 3_600_000
    assert hl_agent.agent_name("x", NOW, 30)[1] == NOW + 30 * 86_400_000


@pytest.mark.parametrize("name, days", [
    ("", 30), ("a valid_until 1", 30), (" pad", 30), ("ok", 0), ("ok", 181),
])
def test_agent_name_refuses_bad_input(name, days):
    with pytest.raises(SystemExit):
        hl_agent.agent_name(name, NOW, days)


@pytest.mark.parametrize("prefix", ["HYPERLIQUID_UPBIT_FADE", "HYPERLIQUID_INSIDERS"])
def test_env_prefix_accepts_fleet_prefixes(prefix):
    assert hl_agent.env_prefix(prefix) == prefix


@pytest.mark.parametrize("prefix", ["hyperliquid_x", "KILLERS", "HYPERLIQUID_X;rm", "HYPERLIQUID_X Y"])
def test_env_prefix_refuses_anything_else(prefix):
    with pytest.raises(SystemExit):
        hl_agent.env_prefix(prefix)


REAL_GREP = shutil.which("grep")


def sh_env(tmp_path, grep_fails=False):
    """PATH for the edit script: a no-op flock where the host lacks one (macOS), and
    optionally a grep whose -v read fails (exit 2) to prove nothing is replaced."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    if shutil.which("flock") is None:
        (bin_ / "flock").write_text("#!/bin/sh\nexit 0\n")
        os.chmod(bin_ / "flock", 0o755)
    (bin_ / "grep").unlink(missing_ok=True)
    if grep_fails:
        (bin_ / "grep").write_text(f'#!/bin/sh\n[ "$1" = "-v" ] && exit 2\nexec {REAL_GREP} "$@"\n')
        os.chmod(bin_ / "grep", 0o755)
    return {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}


REMOVE = ["HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS", "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY",
          "HYPERLIQUID_INSIDERS_[A-Z0-9_]*"]


def run_edit(tmp_path, before, new_lines, remove=REMOVE, grep_fails=False, check=True):
    d = tmp_path / "stack"
    d.mkdir(exist_ok=True)
    env = d / ".env"
    env.write_text(before)
    os.chmod(env, 0o600)
    script = hl_agent.env_edit_script(str(env), remove)
    done = subprocess.run(["sh", "-c", script], input=new_lines, text=True, capture_output=True,
                          env=sh_env(tmp_path, grep_fails))
    if check:
        assert done.returncode == 0, done.stderr
    return env, done


def test_env_edit_replaces_the_prefix_drops_the_old_bot_and_keeps_the_rest(tmp_path):
    before = ("A=1\n"
              "HYPERLIQUID_KILLERS_WALLET_ADDRESS=0xk\n"
              "HYPERLIQUID_KILLERS_PRIVATE_KEY=0xkk\n"
              "HYPERLIQUID_INSIDERS_WALLET_ADDRESS=0xi\n"
              "HYPERLIQUID_INSIDERS_DRY_RUN=true\n"
              "HYPERLIQUID_INSIDERS_PRIVATE_KEY=0xii\n"
              "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xstale\n"
              "HYPERLIQUID_UPBIT_FADE_DRY_RUN=true\n")
    env, done = run_edit(tmp_path, before,
                         "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS=0xi\nHYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n")
    assert env.read_text() == (
        "A=1\n"
        "HYPERLIQUID_KILLERS_WALLET_ADDRESS=0xk\n"
        "HYPERLIQUID_KILLERS_PRIVATE_KEY=0xkk\n"
        "HYPERLIQUID_UPBIT_FADE_DRY_RUN=true\n"
        "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS=0xi\n"
        "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n")
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    backup, names = hl_agent.parse_edit_output(done.stdout)
    assert Path(backup).read_text() == before and stat.S_IMODE(Path(backup).stat().st_mode) == 0o600
    assert names.split() == ["HYPERLIQUID_KILLERS_WALLET_ADDRESS", "HYPERLIQUID_KILLERS_PRIVATE_KEY",
                             "HYPERLIQUID_UPBIT_FADE_DRY_RUN", "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS",
                             "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY"]
    assert "0x" not in done.stdout
    assert not list(env.parent.glob(".env.new.*")), "staging file left behind"


def test_env_edit_never_joins_a_line_when_the_file_lacks_a_final_newline(tmp_path):
    env, _ = run_edit(tmp_path, "A=1", "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n")
    assert env.read_text() == "A=1\nHYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n"


def test_env_edit_aborts_on_a_read_error_and_leaves_the_file_untouched(tmp_path):
    before = "HYPERLIQUID_KILLERS_PRIVATE_KEY=0xkk\nHYPERLIQUID_INSIDERS_X=1\n"
    env, done = run_edit(tmp_path, before, "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n",
                         grep_fails=True, check=False)
    assert done.returncode != 0
    assert env.read_text() == before
    assert not list(env.parent.glob(".env.new.*")), "staging file left behind"


def test_env_edit_removing_every_line_is_not_an_error(tmp_path):
    env, _ = run_edit(tmp_path, "HYPERLIQUID_INSIDERS_X=1\n", "B=2\n")
    assert env.read_text() == "B=2\n"


def test_two_edits_keep_two_distinct_backups(tmp_path):
    env, first = run_edit(tmp_path, "A=1\n", "B=2\n")
    script = hl_agent.env_edit_script(str(env), ["C"])
    second = subprocess.run(["sh", "-c", script], input="C=3\n", text=True, capture_output=True,
                            env=sh_env(tmp_path), check=True)
    b1, _ = hl_agent.parse_edit_output(first.stdout)
    b2, _ = hl_agent.parse_edit_output(second.stdout)
    assert b1 != b2 and Path(b1).read_text() == "A=1\n" and Path(b2).read_text() == "A=1\nB=2\n"
    assert env.read_text() == "A=1\nB=2\nC=3\n"


def test_env_edit_script_carries_no_secret_and_fails_on_a_missing_file(tmp_path):
    script = hl_agent.env_edit_script(str(tmp_path / "missing"), REMOVE)
    assert "=0x" not in script
    assert subprocess.run(["sh", "-c", script], input="", text=True, capture_output=True,
                          env=sh_env(tmp_path)).returncode != 0


def test_env_pairs_take_plain_values_and_refuse_secrets():
    assert hl_agent.env_pairs(["HL_UPBIT_GATEWAY_CLIENT=upbit", "HYPERLIQUID_UPBIT_FADE_DRY_RUN=false"]) == [
        ("HL_UPBIT_GATEWAY_CLIENT", "upbit"), ("HYPERLIQUID_UPBIT_FADE_DRY_RUN", "false")]
    for bad in ["NOVALUE", "lower=1", "A=has space", "A=$(x)", "HYPERLIQUID_X_PRIVATE_KEY=0x1"]:
        with pytest.raises(SystemExit):
            hl_agent.env_pairs([bad])


class Done:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.mark.parametrize("rc, stdout, stderr, says", [
    (1, "", "flock: timeout\nHLAGENT_UNCHANGED\n", "unchanged"),
    (1, "", "boom", "UNKNOWN"),
    (255, "", "Connection reset", "UNKNOWN"),
    (255, "BACKUP=/x/.env.bak-1\n", "HLAGENT_UNCHANGED", "UNKNOWN"),
])
def test_write_env_claims_unchanged_only_on_the_scripts_marker(monkeypatch, rc, stdout, stderr, says):
    monkeypatch.setattr(hl_agent.subprocess, "run", lambda *a, **k: Done(rc, stdout, stderr))
    with pytest.raises(SystemExit) as e:
        hl_agent.write_env(["X"], "X=1\n")
    assert says in str(e.value)
    if says != "unchanged":
        assert "Do not recreate" in str(e.value)


def test_script_marks_unchanged_only_before_the_replace(tmp_path):
    _, failed = run_edit(tmp_path, "HYPERLIQUID_INSIDERS_X=1\n", "B=2\n", grep_fails=True, check=False)
    assert failed.returncode != 0 and "HLAGENT_UNCHANGED" in failed.stderr
    ok_env, ok = run_edit(tmp_path, "A=1\n", "B=2\n")
    assert "HLAGENT_UNCHANGED" not in ok.stderr
    # replaced, then the success marker cannot be written (stdout closed): no false marker
    script = hl_agent.env_edit_script(str(ok_env), ["C"])
    late = subprocess.run(["sh", "-c", "exec >&-\n" + script], input="C=3\n", text=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=sh_env(tmp_path))
    assert late.returncode != 0 and "HLAGENT_UNCHANGED" not in late.stderr
    assert ok_env.read_text() == "A=1\nB=2\nC=3\n"


def test_write_env_returns_backup_and_names(monkeypatch):
    monkeypatch.setattr(hl_agent.subprocess, "run",
                        lambda *a, **k: Done(0, "BACKUP=/x/b\nNAMES=HYPERLIQUID_A HYPERLIQUID_B \n"))
    assert hl_agent.write_env(["X"], "X=1\n") == ("/x/b", "HYPERLIQUID_A HYPERLIQUID_B")


@pytest.mark.parametrize("approved, listed, key_ok, done", [
    (True, True, True, True),
    (None, True, True, True),    # response lost, but the listing proves the approval
    (False, True, True, False),  # rejected
    (True, False, True, False),  # not listed yet
    (True, None, True, False),   # listing unreadable
    (True, True, False, False),  # another edit replaced the stored key
    (True, True, None, False),   # stored key unreadable
    (None, None, None, False),
])
def test_verdict_declares_done_only_on_proof(approved, listed, key_ok, done):
    msg = hl_agent.verdict(approved, listed, key_ok)
    assert (msg is None) == done
    if not done:
        assert "Do not recreate the bot" in msg and "Re-run this same command" in msg
        assert "cp -p" not in msg


def test_apply_env_is_env_set_without_its_prompt(monkeypatch, capsys):
    """go-live.sh asks its own YES once, then calls apply_env (#252)."""
    calls = []
    monkeypatch.setattr(hl_agent, "write_env", lambda names, lines: calls.append((names, lines)) or ("/b", "A B"))
    monkeypatch.setattr(hl_agent, "confirm", lambda prompt: pytest.fail("apply_env must not prompt"))
    hl_agent.apply_env(hl_agent.env_pairs(["HL_UPBIT_GATEWAY_CLIENT=upbit", "HYPERLIQUID_UPBIT_FADE_DRY_RUN=false"]))
    assert calls == [(["HL_UPBIT_GATEWAY_CLIENT", "HYPERLIQUID_UPBIT_FADE_DRY_RUN"],
                      "HL_UPBIT_GATEWAY_CLIENT=upbit\nHYPERLIQUID_UPBIT_FADE_DRY_RUN=false\n")]
    assert "Backup on the VPS: /b" in capsys.readouterr().out
