# Runtime — VPS-only

**This project runs on the elder-brain VPS, not your Mac.**

This Mac dir is a **source clone for editing context only**. Local Docker
is disabled here. Never run:

- `docker compose up` / `make dev` / anything that boots a local DB or API.
- A previous "local dev" stack used to live here — it's been torn down and
  the named volumes nuked. Do not reanimate it.

## Where it actually runs

- **VPS deploy type:** Dokploy compose
- **VPS source path:** `/etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code`
- **Public URL:** https://master-trader.grooveops.dev
- **Logs:** `ssh main-instance "docker logs ft-dashboard"`

## How to debug or query prod

- SSH: `ssh main-instance` then operate at the VPS path above. Production
  DB lives only there.
- Telegram: `@elder_brain_bot` has rw on `/home/ubuntu`, `/etc/dokploy`,
  the docker socket, and `claude` CLI. It can grep code, run `psql`,
  restart containers, push commits, etc.

## How to ship a code change

1. Track the work in an issue, edit on an issue-linked branch, and open a PR.
2. Review and test the PR, then merge to main when authorized. See CONTRIBUTING.md.
3. When production rollout is authorized, open a release PR from main to the
   project's deployment branch (`vps-deploy` here). Review the complete release
   diff; merging may trigger Dokploy. Record the deployed commit and verify the
   affected services. Do not push changes directly to a deployment branch.
4. For services deployed manually, follow their runbook after the release PR.
   A merge alone is not evidence that production is updated or healthy.

## Why this exists

A separate Claude session (or a stale memory) tried to spin this project
up locally, hit a Postgres without the prod data, and started proposing
"how do we sync state from prod?" The answer is: don't. Work on prod
directly via SSH or the bot. This file is the canonical reminder.
