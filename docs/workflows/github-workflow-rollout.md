# GitHub workflow rollout — 2026-09-14

Tracked by #26. The operator requested this as the default across all projects.
The reusable policy is in `global-github-policy.md`; private configurations are
not copied into Git. Existing instructions were preserved and backed up before
appending the workflow section.

Installed targets:
- Mac: `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`.
- VPS host: `/home/ubuntu/.codex/AGENTS.md`,
  `/home/ubuntu/.claude/CLAUDE.md`, and host-level `/home/ubuntu/CLAUDE.md`.
- VPS bot: `/root/.claude/CLAUDE.md` inside `elder-brain-bot`, on its persistent
  Claude-auth volume; no service restart was needed.
- Repository: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, templates and CI.

New sessions load the global files. Already-running sessions should reread them;
this change does not retroactively replace an active session's loaded context.
Other machines or isolated cloud sandboxes need the policy installed separately.

Contributor review:
- #12, #20 and #21 merged after source review and combined-suite verification.
- #14 has a change request for fresh-clone setup prerequisites and working paths.
- #25 has a change request with a reproduced `*Viability` archive-name failure.
- #22 and #23 remain correctness blockers for trustworthy promotion decisions.
- #27 tracks the carry follow-through, linked to the shared cost-model issue #1.

The existing M1/M2/M3 milestones and area labels are retained. Priority labels
make the implementation order explicit without overwriting contributors' reports.
PR CI runs six isolated unit suites with read-only repository permissions, pinned
actions, no production secrets and no deployment steps. GitHub-hosted tests are
separate from opt-in read-only VPS integration checks.

Production remains on its previously verified release. Workflow/source merges
are not reported as deployed; release promotion requires its own reviewed PR.
