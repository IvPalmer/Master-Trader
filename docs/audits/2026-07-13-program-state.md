# Program state — 2026-07-13 (end of session)

One-day arc: from "why did FF lose two trades" to a validated yield mechanism, a live
risk system, two honest strategy kills, a fixed copy-trader, and three autonomous
evidence monitors. ~20 commits; every experiment preregistered before data; every
substantive conclusion codex-reviewed.

## The thesis (operator-endorsed)
Retail-scale profit from automated trading does not come from price prediction — every
prediction-flavored idea tested today died under honest measurement (fills, fees, OOS,
regime splits). It comes from: (1) a structural yield engine, (2) a cheap passive beta
sleeve, (3) opportunistic event edges on infrastructure advantages, (4) a kill machine
that executes fake edges before they touch capital. All four now exist in this repo.

## What is running tonight

| System | State | Verdict clock |
|---|---|---|
| **HL carry shadow** (`hl-shadow`, 40 coins) | validating execution realism of the day's headline result | 2026-08-17 review |
| **Carry evidence** | **6/6 criteria, both tiers, 194 episodes / 3.17yr: majors 17.5%/yr, midcap 26.6%/yr, market-neutral** | shadow gates dry-run |
| **Risk warden** (live, 5-min cron) | first run banked AAVE/SKY/SOL profits → killers realized flipped +$2.62; trims until ≤10% stop-at-risk cap | continuous |
| **Listing-short monitor** (`listing-monitor`) | paper-shorts each new Binance futures-listing on HL; −7%/24h retro effect, forward-only validation | unblind at ≥8 events (~Sep) |
| **FundingFade** (LIVE $200) | signal-starved but healthy; hourly funding refresh fixed | 2026-08-17 |
| **Keltner** (dry) | clean validated-18-pair epoch since 07-13 04:48Z | 2026-08-17 |
| **Killers copier** (dry) | signal_update fidelity fix deployed (KITE-class misses now executed); banked-P&L is the only headline metric | riders resolve / 08-17 |
| **Insiders** (dry) | measuring, −6.5%, do-not-fund | 08-17 |
| **Auto-invest R$300/mo** (operator, BTC 70/ETH 30) | awaiting operator's confirm click at binance.com/en/auto-invest | immediate |

Killed today with evidence (never re-litigate without new data): CascadeFader (fill
stress: PF 0.98 @0.5% slip), TSMOM weekly (DD 89.6%, 2021 carried sample), listing-LONG
reaction (median −2.1%@4h), HL extreme-fade (PF 0.96), killers tuning (WR 6.2% closed;
only fidelity + risk engineering authorized).

## Next steps

**Operator (once, ~5 min):**
1. Confirm the Auto-Invest plan (R$300/mo, BTC 70/ETH 30, binance.com/en/auto-invest).

**Autonomous (no action needed):**
2. Shadow accumulates carry episodes on 40 coins; weekly summaries in
   `research/hl_carry_2026-07/shadow/data/weekly_summary.jsonl`.
3. Listing-monitor records each futures-listing event as it happens.
4. Warden keeps stop-at-risk ≤10%; killers riders resolve into banked P&L.
5. F2 (FF per-pair freshness guard) rides along at FF's next natural restart.

**2026-08-17 review (pre-committed criteria, all in preregistrations.json):**
6. Carry: if shadow confirms yield + execution realism → design + fund the dry-run bot
   pair; this becomes the core sleeve that scales with contributed capital.
7. FF: gate-open-time fallback binds (PF rule not evaluable at expected N).
8. Keltner: first clean-epoch data judged.
9. Killers/Insiders: banked-P&L-through-regime-flip standard; do-not-fund stands unless met.

**~2026-09-15:**
10. Listing-short unblind at ≥8 forward events (BBO-conservative accounting) → if it
    passes, a reaction-bot design study opens (the TG infra's first real alpha use).

**If carry fails the shadow:** the implementation closes (not the lane), listing-short
and the remaining pre-ranked lanes (VPIN veto, weekend momentum) queue next under the
same prereg discipline. No month is ever bet on a single clock.
