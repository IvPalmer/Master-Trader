"""#112: a fresh state volume must be writable by the receiver's uid 1000.

Docker seeds a new, empty named volume from the image's directory at the
mount point, ownership included. The image used to declare VOLUME before the
directory existed, so the mount point came up root:root 755 and both
receivers crash-looped on `unable to open database file`. Static checks only:
no Docker in this checkout or CI.
"""
import re
from pathlib import Path

import yaml

SERVICE = Path(__file__).resolve().parent.parent
REPO = SERVICE.parent.parent
STATE_DIR = "/var/lib/killers"


def _instructions():
    """Dockerfile instructions with line continuations joined."""
    text = (SERVICE / "Dockerfile").read_text()
    text = re.sub(r"\\\n", " ", text)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keyword, _, rest = line.partition(" ")
            out.append((keyword.upper(), rest.strip()))
    return out


def _index(instructions, predicate):
    for i, (keyword, rest) in enumerate(instructions):
        if predicate(keyword, rest):
            return i
    return None


def test_state_dir_is_created_and_owned_by_the_runtime_user_before_volume():
    ins = _instructions()
    volume = _index(ins, lambda k, r: k == "VOLUME" and STATE_DIR in r)
    assert volume is not None, "state directory is no longer a declared volume"
    owned = _index(ins, lambda k, r: k == "RUN"
                   and re.search(rf"mkdir -p {re.escape(STATE_DIR)}\b", r)
                   and re.search(rf"chown (receiver|1000)(:(receiver|1000))? {re.escape(STATE_DIR)}\b", r))
    assert owned is not None, f"no RUN creates and chowns {STATE_DIR}"
    assert owned < volume, "the directory must exist with its owner BEFORE VOLUME"
    user_created = _index(ins, lambda k, r: k == "RUN" and "useradd -u 1000" in r
                          and " receiver" in r)
    assert user_created is not None and user_created <= owned


def test_container_runs_as_the_user_that_owns_the_state_dir():
    ins = _instructions()
    users = [rest for keyword, rest in ins if keyword == "USER"]
    assert users and users[-1] in ("receiver", "1000")


def test_the_receiver_keeps_its_db_inside_the_seeded_volume():
    services = yaml.safe_load(
        (REPO / "ft_userdata" / "docker-compose.prod.yml").read_text())["services"]
    for name in ("killers-receiver",):
        svc = services[name]
        assert svc["build"] == "../services/killers-receiver"
        mounts = [v for v in svc["volumes"] if v.endswith(f":{STATE_DIR}")]
        assert len(mounts) == 1, f"{name} must mount a named volume at {STATE_DIR}"
        assert not mounts[0].startswith(("/", ".")), f"{name}: expected a named volume"
        assert svc["environment"]["KILLERS_DB"].startswith(STATE_DIR + "/")
