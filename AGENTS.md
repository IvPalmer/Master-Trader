# Repository instructions

Read `RUNTIME.md` before runtime work. This checkout is for source edits and
network-free tests; do not start local Docker, databases or application servers.

Read `CONTRIBUTING.md` and `docs/workflows/global-github-policy.md` before changes.
Use an existing issue or create one, work on an issue-linked branch, and submit a
PR. Do not push changes directly to main or vps-deploy. Review actual behavior,
run relevant tests, and record results and remaining limitations in the PR.
Merging does not authorize live deployment or changes to trading allocations.
Preserve the research preregistrations and distinguish paper, live and historical
measurement epochs. Never commit secrets or raw private production data.

Dashboard work (`ft_userdata/ft_dashboard/`) must follow `PRODUCT.md` and `DESIGN.md`
at the repository root. They are authoritative UI policy, not tooling output: planned
targets are not exchange orders, a reported bot stop is not exchange verification,
and missing telemetry or mark-to-market history is never fabricated.
