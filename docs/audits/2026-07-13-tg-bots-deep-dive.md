# Telegram copy-trader deep dive + fleet profitability — 2026-07-13

Operator asked: killers shows ~+20% with extreme WR/DD — can we tune it? Plus overall
profitability status. Verdict rule frozen BEFORE re-pricing (killers-fill-realism-2026-07).
Codex-reviewed (2 rounds on synthesis + subagent's own review of the audit mechanics).

## The +20%, decomposed (STRICT executable-fill re-pricing)

| Component | USDT | % of $200 |
|---|--:|--:|
| Closed trades realized (16 trades, WR 6.2%) | **−55.55** | −27.8% |
| Booked partial-TPs on the 9 open positions | +61.85 | +30.9% |
| **BANKED total** | **+6.30** | **+3.15%** |
| Floating on the 9 open leveraged runners | +35.91 | +17.95% |
| Headline "total" | +42.21 | +21.1% |
| **If all 9 runners hit their posted SLs** | **−48.43** | **−24.2%** |

The strategy is not "+21%". It is a leveraged rider book with **+3.15% banked and
−24.2% stop-at-risk**, marked during one six-week bull tape. Headline metrics for this
bot are now, permanently: banked + floating + stop-at-risk.

## What the audit cleared and what it found

**Cleared:** the dry engine's fills are faithful to trade-through mechanics — 0 phantom,
0 touch-only across all 88 fills; every TP fill tick-verified against Binance futures 1m
prints. The profit picture is NOT a dry-run fill fantasy. (Faithful ≠ live-copyable:
queue position, latency, and size remain untested.)

**Found — copy-fidelity defect:** channel message 2026-06-09 "SIGNAL ID #2154 KITE —
adjusting the setup to close at first target" was classified `chat` by the observer and
ignored. The channel exited KITE in profit; our copy held to a **−$9.42 force-exit**
(2nd-largest closed loss, ~17% of closed damage). The classifier lacks a
`signal-update` kind. Fix spawned as a follow-up task (fidelity, not tuning); the full
historical corpus must be reprocessed with the new class before claiming net benefit —
an update-follower may also cut runners early. KITE is a sensitivity example; it is NOT
credited back into any headline number.

**Structure insight:** closed WR 6.2% with big booked partials means the payoff design
is "rare runners must pay for many realized losses" — workable only if runner
management is copied exactly. The KITE miss attacks exactly that assumption.

## Frozen-rule outcome
Success branch (STRICT ≥+10% AND WR ≥55%) did not fire — WR 6.2%. No branch covered
"high floating / terrible closed WR": recorded as a prereg design defect, patched
prospectively (banked-only promotion metrics; floating always reported with
stop-at-risk; WR on closed/completed campaigns only).
**VERDICT: NO PROMOTION / NO TUNING AUTHORIZED / CONTINUE MEASUREMENT UNDER GAP.**
Do-not-fund unchanged. Judgment when the riders resolve or at the 2026-08-17 review.

## Insiders (informational)
STRICT −6.48% (−$12.96), WR closed 25% (1/4), 2 entries in-window from 2,156 processed
messages. Nothing to tune at N=4. Do-not-fund trivially stands. One open BTC short
+$5 floating.

## Fleet profitability, as of 2026-07-13T17:54Z

| Bot | Mode | Record | Honest read |
|---|---|---|---|
| FundingFade | **LIVE** $200 | +$0.41, 19 closed, 3mo | Breakeven; signal-starved (1 signal/8wk) |
| Keltner | dry | +$1.62 closed, 1 open | Clean 18-pair epoch started 07-13 |
| Killers | dry futures | banked +$6.30, floating +$35.91, stop-risk −$48 | Rider book, unbanked; fidelity fix pending |
| Insiders | dry futures | −$12.96 | Barely trades; measuring |
| ShortKeltnerHL | dry HL | +$6.54, PF 2.81, N=4 | Promising, unproven (N=4) |
| Cascade | **retired 07-13** | −$3.29 at retirement | Fill-stress verdict |
| HL carry | shadow | 0 candidates (funding below gate) | Best active edge candidate; needs episodes |

Live capital P&L to date: **+$0.41 on $200 over ~3 months.**

## Recommendations (the "how do people actually profit from AI auto trading" answer)
1. **Fix the copier before judging the channel** — the signal-update classifier defect
   is the one concrete, evidence-backed improvement available today (spawned task).
2. **Bank or it didn't happen.** Promotion/funding decisions use banked P&L through at
   least one regime flip. Floating rider P&L is exposure, not edge.
3. **Evidence ranking for future capital:** HL carry is the highest-ranked ACTIVE edge
   candidate (only cross-validated positive mechanism; shadow must produce episodes);
   passive beta remains the cleaner deployable baseline; everything else is a
   measurement instrument until proven.
4. **Kill discipline prevents allocating to disproven systems** — Cascade retired today
   on evidence; that is how the account stays alive long enough for a real edge to
   compound.
5. The people who durably profit at retail scale do it on structural/execution edges
   and disciplined risk — not public-data chart signals or channel marketing (+278%
   NEAR brags vs our −27.8% closed reality from the same signals, at real prints).
   The machinery built this cycle (prereg, fill realism, OOS, shadow) is precisely
   what separates that population; the next 4–6 weeks of evidence (riders resolving,
   carry episodes, clean epochs) decide where capital goes.
