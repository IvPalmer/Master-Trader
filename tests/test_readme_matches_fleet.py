"""The README's runnable instructions match what CI and the VPS do (#100, #102).

#93 added a seventh Python suite to CI and the README block, which said "the
same six suites CI runs", silently skipped it. Each doc kept its own copy of
what tests.yml already says. This compares the README block with the workflow
so the next added suite fails here instead of drifting.

The README also told readers to run ft_userdata/automation_scheduler.sh, the
pre-VPS cron installer, whose every line misbehaves on the current host. It
now refuses to run unless explicitly overridden.
"""

import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
SCHEDULER = ROOT / "ft_userdata" / "automation_scheduler.sh"


def _ci_suites():
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["unit-tests"]["steps"]
    suites = []
    for step in steps:
        run = step.get("run", "")
        m = re.fullmatch(r"python -m pytest (\S+) -q", run.strip())
        if m:
            suites.append((step.get("working-directory", "."), m.group(1)))
    return suites


def _readme_suites():
    text = README.read_text()
    block = text.split("### 1. Clone and run the tests", 1)[1].split("### 2.", 1)[0]
    suites = []
    for line in block.splitlines():
        line = line.strip()
        m = re.fullmatch(r"\(cd (\S+)\s+&& \$V -m pytest (\S+) -q\)", line)
        if m:
            suites.append((m.group(1), m.group(2)))
            continue
        m = re.fullmatch(r"\$V -m pytest (\S+) -q", line)
        if m:
            suites.append((".", m.group(1)))
    return suites


def test_readme_test_block_runs_every_ci_suite_in_order():
    ci = _ci_suites()
    assert len(ci) >= 6  # root, receiver, dashboard, gateway, trade-webhook, killers_bot
    assert _readme_suites() == ci


def test_docs_do_not_count_the_suites():
    """A count in prose went stale twice (#84, #93); the list is the source."""
    for doc in (README, ROOT / "CONTRIBUTING.md"):
        assert not re.search(r"\b(six|seven|eight|6|7|8) (Python )?suites\b", doc.read_text()), doc


def test_readme_no_longer_says_to_run_the_scheduler():
    text = README.read_text()
    assert "bash ft_userdata/automation_scheduler.sh" not in text
    assert "installed by `ft_userdata/automation_scheduler.sh`" not in text


def test_retired_scheduler_refuses_and_never_touches_crontab(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "crontab-calls"
    crontab = fakebin / "crontab"
    crontab.write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    crontab.chmod(0o755)
    env = {"PATH": f"{fakebin}:{os.environ['PATH']}", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(SCHEDULER)], capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "retired" in r.stderr
    assert not calls.exists()
    assert not (tmp_path / "ft_userdata").exists()
