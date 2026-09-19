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

Existing-position migration is a separate operator operation (see the migration runbook below): inspect current
fills/orders, create a per-position proposal, account for already crossed targets,
preserve native stops, and reconcile cancellation/replacement before further
submission. The policy configuration deliberately does not bulk-rearm current positions.
Rollback of the environment affects future entries only; retain the new code to
honor already frozen policies. Rolling back to old code with new-policy positions
still pending arming is unsafe because old code would ignore their snapshots.

## Nearest-source fallback

`KILLERS_TP_MODE=nearest_source` (with empty `KILLERS_TP_ALLOCATIONS`) opts new
positions into the size-aware fallback. It freezes the nearest two eligible
original source targets at entry. Once entry fills, the planner finds the
executable quantity interval at the first target and chooses the valid split
closest to half. Both exits must clear the minimum, and the first must leave
Freqtrade's required residual. If no split works, **100% exits at the first
candidate**, never at a farther target. Prices are unchanged source prices.

A missing/crossed first candidate at arming blocks the plan for review instead
of posting an immediately marketable exit or moving to a later price. A
whole position too small at the first target is rejected rather than increased.
This is not a proven optimal TP strategy. The mode defaults to `legacy`; no
existing position is migrated, no research epoch is edited, and implementation
or deployment alone does not activate this policy. Prospective activation is
an operator decision, with a new measurement epoch.

## Existing legacy positions: operator migration

The receiver now supplies a **manual** two-step migration. Installing this code
never replaces existing orders. It requires the receiver already running
`nearest_source`, active TP limits, and a non-default Freqtrade password.

Run on the VPS, after the receiver image has been rebuilt from the reviewed release:

```bash
docker exec killers-receiver python -m app.tp_migrate preview --all
# Or one trade:
docker exec killers-receiver python -m app.tp_migrate preview --trade-id TRADE_ID
```

Each preview prints the market, current mark, original source target numbers,
prices, quantities and an **individual apply command** with a request UUID. Read
that proposal and run its printed SSH command from your Mac within five minutes. No bulk apply is
provided. Credentials stay inside the receiver container; do not paste them into
commands. Preview stores a private approval record but makes no exchange writes.

The proposal uses original source targets ahead of both current price and entry;
it does not move an exit behind entry, invent a price or increase size. It checks
remaining filled inventory, exact quantity/price precision, minimum notional,
residual requirements, a known resting exit and an active native stop reported
by Freqtrade. Partially filled exits, unknown orders, incomplete entries, dust
and uncertain ledger states require reconciliation before preview succeeds.

Apply shares the receiver's phase-2 lock with TP reconciliation and source close
updates. It rechecks the preview, archives the complete old target ledger in
`tp_migrations`, and commits blocked rows before requesting cancellation of the
normal open order. Native stop orders are excluded. It requires an acknowledged
cancel **and** a fresh snapshot showing no normal open exit and unchanged exit accounting.
Freqtrade omits cancelled zero-fill orders from its trade JSON; that absence is
expected after acknowledged cancellation. If the old order remains in the JSON,
it must explicitly be cancelled with zero fill. The snapshot must also show
unchanged remaining inventory/stop and no other normal open order. Only then does
it commit the frozen replacement policy and use the existing idempotent adopter
to place the first exit. Later exits remain sequential. The old ledger stays in
the private journal; research tapes and historical epochs are not rewritten.

`active` means Freqtrade reported exactly the proposed first resting exit and an
unchanged native stop. It is not a fill, an independent exchange audit or proof
of future profitability. Exchange movement and external/manual actions cannot be
made atomic with receiver database transactions. A concurrent fill or stop change
therefore ends the operation as `needs_review`, without another replacement.

### Interrupted or refused operations

- Before cancellation, a stale/expired preview refuses without touching orders.
- A cancellation timeout or crash leaves the old ledger blocked. A TP may still
  be resting or may have been cancelled; inspect it. The native stop is not
  cancelled by this tool. Do not assume there is an active TP.
- Repeating the **same request ID** returns its recorded state and never repeats
  cancellation or submission. `cancelling`/`armed` after a crash requires checking
  the journal and `target_orders`; it is not a success response.
- A crash after the new plan is committed may resume through the normal
  reconciler. Before submitting its first exit, it checks that the approved price
  is still ahead of the fresh mark. A crossed/missing mark blocks submission.
- A newly generated preview can recover a legacy cancellation hold after fresh
  inspection and another explicit approval. It cannot overwrite an already
  frozen migrated policy or an unknown/rejected submission.
- Never manually delete active rows or replay an uncertain submission under a
  new request ID. Do not restore a database backup over live orders: reconcile
  the actual executor/exchange state first.

The operator routes require the existing ingress bearer **plus** the operator
password and a loopback peer. Source-event clients cannot use their bearer alone
to migrate positions. The CLI talks to localhost from `docker exec`; nothing is
exposed through the public dashboard.

### Release verification and rollback

Rebuild/recreate **killers-receiver** from the release checkout, preserving its
current environment and volume. Verify healthy startup and use preview only to
validate compatibility before the operator applies a trade. A successful build
or preview does not mean an existing trade was migrated. Record actual order
verification separately; see the dated rollout record below.

The schema addition is additive. Before any apply, reverting this release does
not require deleting its journal. After an apply, retain code that understands
frozen policies and migration holds; an old image can omit the first-target
restart guard. Never roll back private ledger history to force a retry.

### Interactive operator command

From the Mac, use a terminal with a TTY:

```bash
ssh -t main-instance 'docker exec -it killers-receiver python -m app.tp_migrate review'
```

This generates a fresh proposal for each legacy position and immediately asks
for the literal `APPLY`. Enter skips it. It never confirms on the operator's
behalf, and does not require copying UUIDs between commands. The same five-minute
expiry, stale-state checks, shared lock and idempotency still apply. A legacy
cancellation hold with no remaining open TP can be reviewed this way; it posts
the approved replacement without trying to cancel an absent order again.

## Verified rollout record — 2026-09-19

Issue [#45](https://github.com/IvPalmer/Master-Trader/issues/45) tracks the
implementation and operational verification. This is a dated release record,
not a live position report.

| Stage | Source / release | Verified outcome |
|---|---|---|
| Size-aware source policy | [#48](https://github.com/IvPalmer/Master-Trader/pull/48) | Nearest eligible source candidates, feasible split or full exit at the first candidate; deploying the code did not activate the receiver. |
| Operator activation | Existing reviewed release | Operator rebuilt/recreated the receiver with `nearest_source`; active TP limits confirmed. Existing legacy positions remained unchanged. |
| Existing-position migration | [#51](https://github.com/IvPalmer/Master-Trader/pull/51), release [#52](https://github.com/IvPalmer/Master-Trader/pull/52) | Preview/apply workflow and private journal deployed. Initial cancellation verification was incompatible with Freqtrade's omitted zero-fill cancelled orders. |
| Cancellation compatibility and interactive recovery | [#55](https://github.com/IvPalmer/Master-Trader/pull/55), release [#56](https://github.com/IvPalmer/Master-Trader/pull/56) | Corrected serializer handling; interactive operator confirmation added; receiver rebuilt and health verified. |
| Operator application and verification | [Verification record](https://github.com/IvPalmer/Master-Trader/issues/45#issuecomment-5745161492) | Both legacy migrations recorded `active`. Receiver and executor matched; a separate Hyperliquid open-order read confirmed the replacement first TPs were resting reduce-only orders with native stop-limit orders present. A new position also used `nearest_source` and had its first TP and stop verified. |

Final execution release: `e791a0c018d227e9f0e66cfb762f8204e7f43bac` on
`vps-deploy`, containing main source `60fd38c`. Receiver image:
`sha256:99b89a88b5b5fa6d2a1345fb0611239eab43b36d5cded1d99dda939a0a0d4423`.
The operator submitted the migration applications; agent verification was
read-only. No account identifiers, order IDs, approval UUIDs or raw production
tapes belong in this record. Private backups and the migration journal remain
on the VPS.

Validation for #55/#56: **277 receiver tests passed**, including omitted
cancelled-order records, changed exit accounting, crash/timeout handling,
interactive confirmation versus skip, and simulated second-leg cascade. Both
PR and release CI passed all checks. Live preview compatibility and service
health were checked after deployment; live replacement orders were verified
separately after operator application.

### Failures and recovery recorded

- An initial apply arrived 1,368 seconds after preview creation and correctly
  failed the 300-second validity check without changing orders.
- Later applies cancelled the old TPs but stopped because the tool required
  cancelled zero-fill records that Freqtrade intentionally omits. Native stops
  remained present; no replacement TP was submitted until operator recovery.
- The fix accepts omission only after acknowledged cancellation, no normal open
  exit, unchanged inventory/stop and unchanged exit accounting. If the old order
  is present, it must prove cancellation with zero fill. Ambiguous responses
  still block rather than retry blindly.
- `review` requires the literal `APPLY`; Enter or any other text skips the
  position. Preview generation is not order placement.

### What remains market evidence

The second target of a split is pending until the first fills; it is **not** a
second resting exchange order. Its future live fill/cascade was not observed
in this verification, although cascade behavior passed automated tests.
Profitability, net profit retention, execution costs and missed winners remain
research questions under [#28](https://github.com/IvPalmer/Master-Trader/issues/28).
Migration does not convert older entries into fresh forward pairs. Preserve
original entry epochs, record the policy transition separately, and do not
rewrite existing preregistrations or tapes. No monitoring automation was enabled
by this rollout.
