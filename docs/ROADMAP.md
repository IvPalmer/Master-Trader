---
goal: Grow crypto trading capital through evidence-gated Freqtrade bots without blowing up.
owner: operator
lead: master-trader-lead
status: active
next: Observe the six-bot micro-live fleet, verify native stop placement on the first
  Hyperliquid fills, and review consolidated/per-bot expectancy and drawdown by 2026-09-30.
decisions_needed: []
blocked_by:
- Operator approval required for ANY live switch, strategy promotion, key change, or fund movement (standing
  D1).
---

## Open tasks

- [ ] Run the read-only live gate audit: FundingFade closed-trade count, PF, drawdown, whitelist freshness, open trades, Cascade count/PF/WR, Keltner activation gates, and dashboard/backup receipts [T-001] #autonomous-safe
- [ ] Draft the trader classifier cost memo covering model downgrade, normalized-input dedup/cache, local 7B structured classification, fallback sampling, and estimated monthly burn from the current Claude path [T-002] #autonomous-safe
- [ ] Decide the trader classifier cost path, then implement only the approved path with audit logs and rollback; do not let classifier changes alter live money behavior without operator review [T-003]
- [x] Close `ff-gate-v2-review` by explicit operator override and move FundingFade into the bounded micro-live fleet v2 epoch without erasing the historical evidence [T-004]
- [ ] Re-check Keltner activation and anti-gates; only prepare a live flip if all required gates are green for 3 consecutive days and the operator acknowledges the abort policy [T-005]
- [ ] Evaluate the `cascade-dry-run-gate-v2` preregistration by 2026-09-30, using PF >= 1.0 and WR >= 60% at >=20 closed trades or a signal-rate investigation if <10 trades [T-006]
- [ ] Verify nightly WAL-safe SQLite backup, off-site copy, restore-drill receipts, and `master-trader.grooveops.dev` CF Access behavior; record results without changing services [T-007] #autonomous-safe
- [ ] Confirm trade-webhook keeps appending Freqtrade events to the lake and alerting Telegram, using a bounded smoke test or the next organic FundingFade event [T-008] #autonomous-safe
- [ ] Update README/deploy docs so the documented fleet matches the VPS reality: FundingFade live real money, 19-pair whitelist, dry-run measurement bots, Grafana behind CF Access, and backup/restore state [T-009] #autonomous-safe
- [x] Superseded by explicit operator authorization on 2026-08-23: ShortKeltner is a bounded Hyperliquid micro-live strategy with native exchange stop configuration and a frozen pre-live lineage snapshot [T-010]
- [ ] Review `micro-live-fleet-v2-2026-08-23` by 2026-09-30 using per-bot and consolidated live evidence; tune, reduce, continue, or pause each bot for concrete reasons [T-011]
- [ ] Verify the first native Hyperliquid stop order for Killers, Insiders, and ShortKeltner at the exchange after each bot's next organic fill [T-012]

## Evidence base

README frames the system around Freqtrade bots, monitoring, portfolio protections, and the principle that optimizations are never auto-deployed.
The VPS docs place the live stack under `/home/ubuntu/master-trader/`, with `ft-funding-fade`, support containers, and the live SQLite in a Docker volume.
Fleet records say `ft-funding-fade` is live with real money and a 19-pair static whitelist; `trade-webhook` feeds `/srv/lake/raw/trades/` and Telegram; Grafana is gated at `master-trader.grooveops.dev`.
The 2026-07-03 restore drill restored the master-trader SQLite artifact with `integrity_check: ok`; the drill noted 17 trades and did not prove a full scratch-VM rebuild.
Recent git history is mostly dashboard and receiver work, including open-trade display, TP-ladder enrichment, and receiver bot-label fixes.

## Decisions (2026-07-04, HQ with operator veto)

- **D1 SUPERSEDED 2026-08-23 (operator):** the operator explicitly authorized bounded real-money deployment for the practical fleet, including Keltner and Hyperliquid futures. Historical gate evidence remains context, not an immutable prohibition.
- **D2 Classifier cost:** dedup-cache + downgrade to haiku first (it's pure classification with likely duplicate inputs; both changes are reversible and stack). Local-7B deferred — infra-heavy for the savings left after caching. Claude stays audit-only.
- **D3 FundingFade gate-v2:** review trigger confirmed — ≥30 closed trades or 2026-08-17, whichever first.

## Path forward

Do the read-only gate audit first because it updates the actual live decision surface without touching money.
Use preregistered gates for FundingFade, Cascade, and Keltner; do not invent discretionary promotion rules mid-sample.
Treat classifier cost work as a spend-control track until the operator approves any runtime change.
Keep backups, dashboard access, and trade-webhook receipts current before adding strategy complexity.
Further capital movement, key rotation, or materially larger allocation still requires operator authorization. Routine maintenance, observation, fail-closed safety fixes, and deployment of reviewed in-scope code remain authorized for this live epoch.
