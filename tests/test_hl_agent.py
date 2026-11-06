"""Pure helpers of the operator API-wallet script (#252); no SDK, Keychain or network."""
import importlib.util
import os
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


def run_edit(tmp_path, before, new_lines, drops=("HYPERLIQUID_INSIDERS",)):
    env = tmp_path / ".env"
    env.write_text(before)
    os.chmod(env, 0o600)
    script = hl_agent.env_edit_script(str(env), "HYPERLIQUID_UPBIT_FADE", list(drops))
    out = subprocess.run(["sh", "-c", script], input=new_lines, text=True,
                         capture_output=True, check=True).stdout
    return env, out


def test_env_edit_replaces_the_prefix_drops_the_old_bot_and_keeps_the_rest(tmp_path):
    before = ("A=1\n"
              "HYPERLIQUID_KILLERS_WALLET_ADDRESS=0xk\n"
              "HYPERLIQUID_KILLERS_PRIVATE_KEY=0xkk\n"
              "HYPERLIQUID_INSIDERS_WALLET_ADDRESS=0xi\n"
              "HYPERLIQUID_INSIDERS_DRY_RUN=true\n"
              "HYPERLIQUID_INSIDERS_PRIVATE_KEY=0xii\n"
              "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xstale\n"
              "HYPERLIQUID_UPBIT_FADE_DRY_RUN=true\n")
    env, out = run_edit(tmp_path, before,
                        "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS=0xi\nHYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n")
    assert env.read_text() == (
        "A=1\n"
        "HYPERLIQUID_KILLERS_WALLET_ADDRESS=0xk\n"
        "HYPERLIQUID_KILLERS_PRIVATE_KEY=0xkk\n"
        "HYPERLIQUID_UPBIT_FADE_DRY_RUN=true\n"
        "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS=0xi\n"
        "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n")
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    (backup,) = tmp_path.glob(".env.bak-*")
    assert backup.read_text() == before
    assert out.split() == ["HYPERLIQUID_KILLERS_WALLET_ADDRESS", "HYPERLIQUID_KILLERS_PRIVATE_KEY",
                           "HYPERLIQUID_UPBIT_FADE_DRY_RUN", "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS",
                           "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY"]
    assert "0x" not in out


def test_env_edit_never_joins_a_line_when_the_file_lacks_a_final_newline(tmp_path):
    env, _ = run_edit(tmp_path, "A=1", "HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n", drops=())
    assert env.read_text() == "A=1\nHYPERLIQUID_UPBIT_FADE_PRIVATE_KEY=0xnew\n"


def test_env_edit_script_carries_no_secret_and_fails_on_a_missing_file(tmp_path):
    script = hl_agent.env_edit_script(str(tmp_path / "missing"), "HYPERLIQUID_UPBIT_FADE", [])
    assert "PRIVATE_KEY=" not in script.replace("PRIVATE_KEY)=", "")
    assert subprocess.run(["sh", "-c", script], input="", text=True,
                          capture_output=True).returncode != 0
