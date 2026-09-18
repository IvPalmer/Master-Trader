# Explicit source take-profit allocation (issue #45)

The legacy planner accumulated equal slices at the **last** target in each
minimum-sized group. With small positions this often meant only the final
source target. This is an execution-policy choice, not a faithful multi-exit
copy and not evidence of good profit retention.

`KILLERS_TP_ALLOCATIONS` enables a prospective, strict source allocation policy.
The syntax is one-based original source target index:percentage, in increasing
index order, with positive percentages totaling 100. Examples illustrate
configuration, not return-tested recommendations:

- `1:45,2:55`: 45% at posted TP1, remaining 55% at posted TP2.
- `1:50,2:30,3:20`: three exits, requiring substantially larger inventory.
- `1:100`: deliberately one full exit at posted TP1.

Prices come from the signal's TARGETS line. They are not invented, shifted,
renumbered after a crossed target, or replaced by ATR/ROI targets. A selected
missing/crossed target rejects the new entry. Original indices survive into
the target ledger. Multiple configured exits are sequential: Freqtrade allows
one resting exit per trade; later orders are placed after the previous fill.
They are not all exchange-resident simultaneously.

Pre-entry checking uses risk-sized notional and the conservative 1.5 Freqtrade
residual reserve. If an allocation or residual is too small, ingress returns
`tp_policy_infeasible` before forceenter. Stake, leverage and risk are never
increased. This check is necessary, not a guarantee: actual fills, amount and
price precision are available only afterwards. The final planner checks actual
filled inventory and the current trade's stop reserve; failures persist blocked
rows with reasons, without posting a fallback target. An entry still filling is
retried by the existing delayed-fill reconciler. Stops remain managed as before.

The exact source indices, prices and percentages are frozen in `positions.tp_policy`
before entry submission. Environment changes do not replan that position.
Existing target rows remain untouched. Existing positions with NULL policy keep
their legacy behavior, including delayed-fill recovery. Empty configuration
preserves the old epoch for compatibility; **deploying code alone does not fix
existing live ladders or activate the new policy**.

## Rollout boundary

This PR supplies configuration and validation, not a proven profitable policy.
Track prospective policy selection and activation under #45 and measurement
under #28. Do not rewrite historical/forward preregistrations or promote failed
retention candidates. Enable only on the Killers Hyperliquid receiver with active
TP limits; config validation rejects incompatible modes. The production compose file passes this variable only to Killers; its empty
default preserves current behavior. Live activation requires a reviewed
release/config change.

Before activation, privately evaluate the chosen split against current signal
prices, filled quantities and precision; compare early realizations with missed
winners after costs. At current small sizes many multi-exit plans will be skipped.
Do not silently substitute single exits or increase capital. Monitor infeasible
entry results and blocked target rows after activation.

Existing-position migration is a separate pending operation: inspect current
fills/orders, create a per-position proposal, account for already crossed targets,
preserve native stops, and reconcile cancellation/replacement before further
submission. This change deliberately does not bulk-rearm current positions.
Rollback of the environment affects future entries only; retain the new code to
honor already frozen policies. Rolling back to old code with new-policy positions
still pending arming is unsafe because old code would ignore their snapshots.
