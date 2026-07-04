---
goal: Grow crypto trading capital through evidence-gated Freqtrade bots without blowing up.
owner: operator
lead: master-trader-lead
status: draft
next: Run a read-only live gate audit from the VPS DB/dashboard and record FundingFade trade count, FF gate-v2 status, Cascade gate status, Keltner activation gates, and backup receipts in docs/.
decisions_needed:
  - "Classifier cost path: model downgrade, dedup/cache, local 7B structured classifier, Gemini fallback, and whether Claude remains audit-only."
  - "FundingFade gate-v2 outcome: continue, rollback, or demote at >=30 closed trades or the 2026-08-17 review."
  - "Keltner live promotion: require all activation gates green for 3 consecutive days plus operator acknowledgement; no auto-flip."
  - "Hyperliquid ShortKeltner path: testnet-only plumbing versus one forced $20 mainnet micro-trade with operator-owned keys and stop-fill verification."
blocked_by:
  - "Operator approval for any strategy promotion, live-bot deployment, key change, or fund movement."
---

## Open tasks

- [ ] Run the read-only live gate audit: FundingFade closed-trade count, PF, drawdown, whitelist freshness, open trades, Cascade count/PF/WR, Keltner activation gates, and dashboard/backup receipts [T-001] #autonomous-safe
- [ ] Draft the trader classifier cost memo covering model downgrade, normalized-input dedup/cache, local 7B structured classification, fallback sampling, and estimated monthly burn from the current Claude path [T-002] #autonomous-safe
- [ ] Decide the trader classifier cost path, then implement only the approved path with audit logs and rollback; do not let classifier changes alter live money behavior without operator review [T-003]
- [ ] Keep FundingFade under the `ff-gate-v2-review` preregistration and make the continue/rollback/demote decision at >=30 closed trades or by 2026-08-17 [T-004]
- [ ] Re-check Keltner activation and anti-gates; only prepare a live flip if all required gates are green for 3 consecutive days and the operator acknowledges the abort policy [T-005]
- [ ] Evaluate the `cascade-dry-run-gate-v2` preregistration by 2026-09-30, using PF >= 1.0 and WR >= 60% at >=20 closed trades or a signal-rate investigation if <10 trades [T-006]
- [ ] Verify nightly WAL-safe SQLite backup, off-site copy, restore-drill receipts, and `master-trader.grooveops.dev` CF Access behavior; record results without changing services [T-007] #autonomous-safe
- [ ] Confirm trade-webhook keeps appending Freqtrade events to the lake and alerting Telegram, using a bounded smoke test or the next organic FundingFade event [T-008] #autonomous-safe
- [ ] Update README/deploy docs so the documented fleet matches the VPS reality: FundingFade live real money, 19-pair whitelist, dry-run measurement bots, Grafana behind CF Access, and backup/restore state [T-009] #autonomous-safe
- [ ] Keep Hyperliquid ShortKeltner in testnet or explicitly approved micro-plumbing mode; no autonomous mainnet launch, no extra capital, and no promotion without stop-fill evidence [T-010]

## Evidence base

README frames the system around Freqtrade bots, monitoring, portfolio protections, and the principle that optimizations are never auto-deployed.
The VPS docs place the live stack under `/home/ubuntu/master-trader/`, with `ft-funding-fade`, support containers, and the live SQLite in a Docker volume.
Fleet records say `ft-funding-fade` is live with real money and a 19-pair static whitelist; `trade-webhook` feeds `/srv/lake/raw/trades/` and Telegram; Grafana is gated at `master-trader.grooveops.dev`.
The 2026-07-03 restore drill restored the master-trader SQLite artifact with `integrity_check: ok`; the drill noted 17 trades and did not prove a full scratch-VM rebuild.
Recent git history is mostly dashboard and receiver work, including open-trade display, TP-ladder enrichment, and receiver bot-label fixes.

## Path forward

Do the read-only gate audit first because it updates the actual live decision surface without touching money.
Use preregistered gates for FundingFade, Cascade, and Keltner; do not invent discretionary promotion rules mid-sample.
Treat classifier cost work as a spend-control track until the operator approves any runtime change.
Keep backups, dashboard access, and trade-webhook receipts current before adding strategy complexity.
No bot deployment, strategy promotion, key rotation, or fund movement is autonomous-safe.
