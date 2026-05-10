# Bot Graduation Criteria v3 — Probe / Pilot / Scale

> **Core principle**: at sub-$200 deployed capital this is a **paid learning loop**, not portfolio capital allocation. Optimize for **controlled learning velocity**, not capital protection. Protect the operator's understanding, not the dollars (the dollars are intentionally trivial).

> **Revised 2026-05-10** after codex-5.5 review of v2. v2 was "anxiety-calibrated, not strategy-calibrated" — its demotion triggers fired on every normal stoploss, every backtest-band drawdown, and every $2.50 loss; its stake ladder was fiction relative to actual flip practice ($15 not $50); it referenced infrastructure that was never built (10% portfolio circuit breaker) and contradicted live config (stoploss_on_exchange).

---

## What changed from v2

| Concept | v2 | v3 |
|---|---|---|
| Permission model | Hard gates (must clear N before live) | Tiered (Probe → Pilot → Scale) |
| Sample size | Universal 30 trades / 14 days / 5 pairs | Strategy-aware minimums |
| Calibration | Exact ±25%/±20% match | "Within expected envelope" with dollar floor |
| Stake ladder | $50 → $100 → $250 → full | Per-tier band; tier-up = explicit operator decision |
| Demotion | Universal triggers | Per-bot, calibrated to that bot's DD/SL envelope |
| Dollar floor | None — $2.50 loss could "kill" a bot | All auto-triggers ignored under $5/$10 thresholds |
| Removed | `stoploss_on_exchange: true` mandate, "10% circuit breaker" | Both removed (incompatible with FF / never built) |

---

## Tiers

### Probe (current default for new bot live flips)
- **Stake**: $10–$20/trade
- **Max exposure**: $20–$50 (stake × max_open)
- **Purpose**: plumbing test — exchange fills, telegram alerts, sqlite persistence, position-tracker handoff, live/dry drift detection
- **Real expectation**: zero alpha resolved at this scale; we're verifying mechanics, not earnings

This tier matches **what FundingFadeV1 actually flipped at** (2026-04-21): $15 stake × 2 max_open = $30 exposure on $50 wallet. v2's "$50 starting stake" was retroactive fiction.

### Pilot
- **Stake**: $25–$50/trade
- **Max exposure**: $50–$150
- **Purpose**: meaningful calibration sample
- **Tier-up trigger** (Probe → Pilot): operator review confirms (a) no operational failures, (b) live behavior tracks backtest within envelope, (c) min runtime hit (see below)

### Scale
- **Stake**: $50+ per trade or `unlimited` for proportional compounding
- **Max exposure**: per-bot allocation (no shared cap unless fleet-wide DD breach)
- **Purpose**: real allocation
- **Tier-up trigger** (Pilot → Scale): explicit operator review with at least 30 closed trades AND ≥1 calendar regime transition observed AND no kill-trigger events

---

## Promotion gates (Probe → Pilot)

Replace v2's universal "30 trades / 14 days / 5 pairs" with **strategy-aware minimums**:

| Strategy class | Min runtime | Min closed trades | Min pairs |
|---|---|---|---|
| Active (>100 trades/yr backtest) | 14 days | 15 | 4 |
| Sparse (40–100/yr backtest) | 30 days | 8 | 3 |
| Very sparse (<40/yr backtest) | 45 days | 5 | 2 |

**Plus** all of:
- Net P&L > 0 OR live drift within calibration envelope (see below)
- No kill-trigger events fired (see Demotion section)
- At least one full ROI exit OBSERVED in live (verifies exit plumbing)
- At least one stoploss exit OR 30 days without one (verifies SL plumbing OR confirmed regime didn't need it)

### Calibration envelope (replaces v2 hard ±25% match)

For metric M (profit, PF, WR), compute scaled-by-trade-count expectation `M_expected`:

- **Green**: live |M − M_expected| / |M_expected| ≤ 30%, OR absolute drift < $5 dollar floor
- **Yellow**: 30–50% drift — operator review at next session, no auto-action
- **Red**: >50% drift OR drift > $20 — pause for investigation

Direction matters less than magnitude. **Upward drift is just as suspect as downward** — MasterTraderV1 showed live PF 2.36 vs backtest 0.50 and was rightly killed. Unrecognized behavior breaks in the next regime.

---

## Per-bot calibration table (current fleet)

This replaces the abstract "calibrate against backtest" with concrete numbers per bot.

| Bot | Backtest PF | Backtest WR | Backtest max DD | Strategy SL | Realistic worst trade | Cadence (trades/yr) |
|---|---|---|---|---|---|---|
| **FundingFadeV1** | 1.29 | 65.7% | 19.6% | −5% | −5.5% (with slippage) | ~130 (active) |
| **KeltnerBounceV1** | 1.58 (FT native) | 80.5% | 12.88% | −7% | −8% (with slippage) | ~46 (sparse) |
| **CascadeFaderV1** | 1.76 (FT native) | 84% | 0.51% (very tight) | −8% | −10% (with slippage) | ~46 (sparse) |

### Per-bot demotion triggers (replaces universal v2)

**FundingFadeV1**:
- Pause: any single closed trade < −7% (= 1.4× strategy SL with slippage band)
- Pause: live DD > 30% (= 1.5× backtest 19.6%) AND |DD| > $10 dollar floor
- Review: trailing 20-trade PF < 1.0 (NOT 1.2 like v2 — backtest PF is 1.29, can't gate at 1.2)
- Kill: live DD > 40% OR profit < −20% capital (= −$10 on $50, NOT −$2.50)
- Kill: 3 consecutive emergency exits (operational failure)

**KeltnerBounceV1**:
- Pause: any single closed trade < −10% (= 1.4× strategy SL with slippage)
- Pause: live DD > 19% (= 1.5× backtest 12.88%) AND |DD| > $10 floor
- Review: trailing 20-trade PF < 1.0
- Kill: live DD > 26% OR profit < −20% capital
- Kill: 6 consecutive losses (= 2× backtest worst of 3)

**CascadeFaderV1**:
- Pause: any single closed trade < −12% (= 1.5× strategy SL of −8%)
  - **NOT v2's universal "−8% pauses"** — that was broken; Cascade hits −8% on every SL
- Pause: live DD > 5% AND |DD| > $5 floor (Cascade backtest DD is 0.51%, so 5% is already 10×)
- Review: trailing 20-trade PF < 1.2
- Kill: live DD > 10% OR profit < −20% capital
- Kill: 7 consecutive losses (= 1.4× backtest worst of 5)

### Fleet-wide kill triggers (apply regardless of per-bot)

- Live wallet balance < expected balance from trade ledger by >$5 (key compromise alarm)
- Any bot fires `force_exit` or `emergency_exit` 3 times in 24h (broken behavior)
- 3 of 3 bots in pause/kill state simultaneously (regime catastrophe — re-evaluate everything)

---

## Live-readiness checklist (Gate 4 replacement)

Strip v2's outdated items. Keep what actually matters.

- [ ] `dry_run: false` in live config
- [ ] `stoploss_on_exchange`: per-bot operator choice (FF=false accepted; doc no longer mandates)
- [ ] `cancel_open_orders_on_exit: true`
- [ ] API keys configured (key + secret) via `.env`
- [ ] Wallet funded with allocated USDT
- [ ] `max_open_trades` × `stake_amount` ≤ wallet × 0.99
- [ ] Webhook templates use explicit `bot_name` for elder_brain_bot routing
- [ ] One restart-recovery test: container restart → clean reboot, no orphan trades
- [ ] One manual smoke trade observed (entry alert + exit alert end-to-end)
- [ ] Per-bot demotion triggers (above) acknowledged by operator

**Removed from v2:**
- `stoploss_on_exchange: true` mandate (FF Path 1½ accepts software-side SL)
- "Circuit breaker active (10% portfolio drawdown kills all bots)" — never built; if needed, build first then re-add
- "Telegram notifications enabled" — replaced with explicit webhook test (alerts route through elder_brain_bot, not native Telegram)
- VPN bypass extra_hosts (handled by Dokploy compose, not graduation concern)

---

## Operator-judgment overrides

v3 explicitly acknowledges the operator (Palmer) has final authority. The criteria are guardrails, not policy. Specific authorities:

1. **Probe-tier flips can override "no calibration sample" rule** if backtest evidence is strong AND operator accepts Path 1½ blast radius. (This is what happened with FF on 2026-04-21 and is the proposed plan for Cascade.)

2. **Tier-up requires operator decision**, not auto-promotion. The criteria provide evidence; the operator decides.

3. **Kill triggers fire automatically only via Telegram alert**. Container shutdown is operator action, not automated. Exception: kill triggers tagged "operational failure" (3 emergency exits, key compromise alarm) — these auto-pause via stop-buy, full kill still requires operator confirm.

4. **Dollar floors are absolute**. Any auto-action that would fire on a wallet movement < $5 is suppressed regardless of percentage. This kills the v2 "$2.50 = death" failure mode.

---

## Stake ladder (replaces v2's $50 → $100 → $250 fiction)

Per-tier band. Operator picks within band based on confidence.

| Tier | Stake/trade | Max exposure | When |
|---|---|---|---|
| Probe | $10–$20 | $20–$50 | First live flip, plumbing test |
| Pilot | $25–$50 | $50–$150 | After Probe gates cleared + operator review |
| Scale | $50+ or `unlimited` | per-bot allocation | After Pilot proven across at least one regime transition |

Bumping within a tier (e.g., Probe $15 → $20) does NOT require new gates. Tier transitions DO.

---

## Demotion = pause vs kill (semantics)

- **Pause** = `stopbuy` via Freqtrade API (existing positions ride out, no new entries). Operator investigates, decides to resume or escalate.
- **Kill** = container stop + revert to dry-run config + post-mortem doc required.
- **Review** = no auto-action, but flag for next operator session. Does not block live operation.

---

## How this maps to current fleet (2026-05-10)

| Bot | Current tier | v3 status | Next decision |
|---|---|---|---|
| FundingFadeV1 | Probe ($15 × 2) | Active, 16 days, 10 trades, +7.28%, within green envelope | Continue Probe. Pilot tier-up review at trade ~30 (~mid-June). |
| KeltnerBounceV1 | Dry-run | 17 days, 2 ROI wins, on backtest pace | 13-day verdict gate 2026-05-22. Pass = stay dry-run as regime-rotation candidate. Fail = kill. |
| CascadeFaderV1 | Dry-run | 1 day, 0 trades | Plumbing-test clear at first 3 trades + ROI + SL observed. Probe flip 2026-05-19+. |

---

## Why v3 over v2

- v2 was conceptually right (calibration > absolutes) but practically wrong (numbers calibrated to anxiety, not strategy)
- v2 contradicted live config (stoploss_on_exchange) and referenced unbuilt infra (circuit breaker)
- v2's stake ladder was fiction relative to actual practice
- v2's dollar-blind triggers turned $2.50 noise into kill events at sub-$100 capital
- v2 used universal demotion triggers that broke specifically on Cascade's normal stoploss

v3 keeps v2's central insight (calibration-match > unicorn absolutes) but re-grounds the numbers in:
1. Actual deployed capital scale ($50, not $50K)
2. Per-bot strategy envelopes (not universal)
3. Dollar floors so noise can't trigger kills
4. Three tiers matching actual flip practice
5. Explicit operator override authority

---

## Migration path

This doc supersedes v2. v2 is archived inline at the bottom of this file by date.
Memory pointer: `project_graduation_criteria.md` (Mac, persists across sessions).
Codex review trail: `docs/cascade_fader_v1_validation_2026-05-09.md` + this file's revision history.

---

## v2 archive (2026-04-20 to 2026-05-10)

v2 was a calibration-match revision of v1's absolute-threshold approach (PF ≥ 2.0
floor, WR ≥ 55%, etc.). v1 was provably unreachable; v2 fixed that conceptually but
miscalibrated the numbers for $50 deployments. Specific v2 failure modes documented
in this v3's "What changed" table. v2 file content available via:
`git show 73ed0f1:ft_userdata/GRADUATION_CRITERIA.md` (or earlier).

## v1 archive (pre-2026-04-20)

v1 used hard absolute floors (PF ≥ 2.0, WR ≥ 55%, Max Loss <5%, Max DD <15%, consec
losses ≤4). No realistic strategy from the Strategy Lab passed all simultaneously.
The gate killed graduation itself. Discarded 2026-04-20.
