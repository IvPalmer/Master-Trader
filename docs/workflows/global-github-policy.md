## GitHub workflow — operator-wide rule (2026-09-14)

For all of Palmer's software projects, GitHub is the durable record of bugs,
improvements, implementation, review and release status. This is the operator's
standing preference; carry out routine repository tracking within the requested
work without asking for repeated permission.

- Before implementation, inspect the working tree, remote/default branch and
  existing issues/PRs. Reuse the relevant issue; create one for substantive new
  work with the problem, acceptance criteria, scope and known dependencies.
  Small related edits may share an issue/PR; do not create activity for its own sake.
- Work on a focused branch from the current default branch, preferably
  `codex/<issue>-<description>` for Codex or `claude/<issue>-<description>` for
  Claude. Use an isolated worktree when concurrent work would interfere.
- Route code, configuration, documentation and infrastructure changes through a
  PR. Do not push directly to main/master or bypass protection. If urgent incident
  recovery requires an explicitly authorized exception, record the exact deployed
  change, reason and validation, then reconcile it promptly through an issue/PR.
- Preserve others' uncommitted work, authorship and open PRs. Never mix unrelated
  pending changes into a PR or force-push another person's branch.
- Keep commits focused. PRs explain the actual problem and resulting behavior,
  link the issue (`Closes #N` only if fully resolved), and record validation,
  material limitations and deployment/rollback considerations where relevant.
- Review the actual diff and relevant callers. Test meaningful behaviors and
  realistic fixtures; green CI alone is not evidence of correctness. Post specific,
  reproducible findings and distinguish pre-existing issues from new defects.
- Run relevant checks and CI before merging. Honor merge authorization already
  provided by the user; when authorized, merge ready work without asking again.
  Do not claim self-review was independent review or bypass unresolved blockers.
- Keep issues/PRs organized using the repository's labels, priorities, milestones
  and dependency links. Update progress when it changes; close only genuinely
  completed scope. Pending work must not exist only in a chat or memory file.
- Merging and deployment are different states. Follow the project's deployment
  authorization and runbook; record commit SHA, environment and post-deployment
  verification. Never imply a merged PR is deployed without checking.
- Finish with links to issues/PRs, validation, merged/deployed state and remaining
  blockers. Keep the default branch clean and synchronized when safe; clean up
  only task-owned temporary worktrees/branches.
- Never publish secrets, private messages, credentials, account identifiers or
  raw production data in issues, commits, logs or CI. For projects without a GitHub
  remote/access, keep a local change record and report the missing access; do not
  silently create or publish a repository. A new explicit operator instruction can
  override this default for a particular task.
