# Contributing

GitHub issues and PRs are the durable work record. Search existing issues before
opening a duplicate. For a substantive change, document the problem, evidence,
acceptance criteria and dependencies; select an area and priority label.

## Development and review

1. Fetch main and create a focused issue-linked branch. Agents use
   `codex/<issue>-<description>` or `claude/<issue>-<description>`.
2. Make a cohesive change. Keep unrelated edits and other contributors' work intact.
3. Run relevant tests. Add regressions for behavior defects using representative
   production data shapes, with synthetic or sanitized data.
4. Open a PR describing the final behavior, link the issue, and record validation
   and material limitations. Use `Closes #N` only for fully resolved scope.
5. Address actionable review findings and wait for CI. Squash merge when authorized;
   preserve contributor attribution. Do not merge unresolved change requests or
   use admin bypass as a routine workflow.
6. Update the issue and record deployed state separately. A merge closes implementation
   scope; rollout work still outstanding needs a linked issue/checklist.

This project runs on the VPS. Local Docker/application startup is prohibited in
this operator checkout; see [RUNTIME.md](RUNTIME.md). Local unit tests are supported:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```

CI uses Python 3.13 and separately runs the root, both receiver, dashboard, gateway
and strict copier parsing suites. Its checks have no production credentials,
exchange access or Docker runtime. VPS integration tests are explicit opt-in and
must never be enabled in PR CI. Skipped Freqtrade-specific tests do not validate
live trading behavior.

## Organization

Reuse the existing area labels and milestones:
- M1: reproducible contributor setup and CI.
- M2: validation and promotion correctness.
- M3: documentation matches enforcement.

Priorities: `priority:P1` affects correctness or blocks trustworthy decisions;
`priority:P2` is normal planned work; `priority:P3` is exploratory/later work.
`status:needs-changes` marks a PR awaiting specific review fixes. `needs-info` is
for missing evidence, not a substitute for an actionable acceptance criterion.
Keep parent issues linked to children and update progress without rewriting others'
findings. Research proposals must distinguish evidence from hypotheses.

## Deployment

The main branch is the reviewed source of truth. Production currently tracks
`vps-deploy`; promote reviewed changes through a release PR only when deployment
is in scope. Record the source commit, environment, affected services, rollback
and post-deploy verification. Never mix an unrelated live strategy change into a
workflow or infrastructure release. See the project runbooks for exact commands.

Global agent policy and installation targets are documented in
[global-github-policy.md](docs/workflows/global-github-policy.md) and
[github-workflow-rollout.md](docs/workflows/github-workflow-rollout.md).
