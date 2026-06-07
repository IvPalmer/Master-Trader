# Killers — exhaustive "can we make it profitable?" search (codex-collaborated)

Operator asked: find ANY way to make Binance Killers signals net-positive (intelligent /
discretionary logic allowed, not just mechanical copy). Two codex rounds + 6 experiments.
All risk-sized R = PnL/|entry−SL|, fees 0.04%/side in R, conservative same-candle SL-first,
chronological 70/30 OOS where a choice was fitted. **Every lane is negative.**

## What was tested (all on cached Binance 5m/1h, 230–263 signals)
| Lane | Result (R, full sample) | OOS / robustness | Verdict |
|---|---|---|---|
| Limit-in-zone + ladder | −37.7R | — | dead |
| Limit-in-zone + T1-exit | −30.4R, win 60% | drop-top worse | dead |
| **Market** entry + T1-exit | −24.4R, win 71% | — | less-bad, still dead |
| Risk-sizing (size from SL) | sign-invariant (−30R at 2x=5x) | — | changes risk not sign |
| Segments: long/short | long −0.10R, short −0.09R/trade | all neg | no pocket |
| Segments: SL tight/mid/wide | −0.12 / −0.08 / −0.08 R/trade | all neg | no pocket |
| Momentum-confirmation entry (k∈.15/.25/.35) | in-sample −0.04…−0.005R | OOS 6 trades, fails all hurdles | dead |
| BTC-regime gate (1h>EMA800 & 12h ret) | gated −0.114R < ungated −0.087R | OOS 10 trades −0.028R | makes it worse |
| **Reachable-at-signal subset** (posted price actually fillable) | **−0.28R/trade (n54)** | train −0.287 / OOS −0.276 | **decisive kill** |

## The mechanism (why nothing works)
- **always-fill-at-posted-entry = +62R** — but that price is unreachable. The reachable test
  proves it: only **54/278** signals still have price in the posted zone at signal time; the
  other **209 have already left it** — those are the runners (winners) you can't fill at posted.
  The reachable subset is the **duds** (−0.28R: they sit in-zone and reverse).
- So the edge lives **before the actionable fill**: winners leave the zone before you fill
  (48% hit T1 pre-entry); losers come back and fill you (loser-fill 99% vs winner-fill 74%).
  This is an **execution/latency tax**, not an exit, sizing, filter, or regime problem — which
  is why exits/sizing/segments/momentum/regime all leave it negative.
- High win rate (60–71% on T1-exit) **feels** like winning but is negative expectancy: avg T1
  win ≈ +0.46R vs −1R stop.

## Verdict (codex round-2, locked)
1. **Killers contains real directional info at the posted prices, but it is execution-dead
   for a copier**: the edge is gone by the actionable fill, and the latency/entry tax keeps it
   negative across market entry, exits, sizing, segment, momentum, regime, and reachable-subset
   tests. Easy parsing/access is real but irrelevant — parsing was never the bottleneck.
2. **The only remaining path is NOT "copy the channel better"** — it's a new *forward*
   agentic/discretionary SELECTION strategy that decides in real time which calls are still
   executable and worth taking, validated live (past data is contaminated/lookahead), with a
   hard risk core. That research is **better aimed at Dennis/Insiders** (where unobserved live
   management is the actual edge) than at Killers (where the public posts ARE the strategy and
   they're execution-taxed).
3. **Capital: do not allocate copier capital to Killers.** At most small *research* capital to
   forward-only selection experiments with hard kill criteria. Otherwise preserve capital for
   strategies whose executable edge is demonstrably present after fees + latency.

Artifacts: `t1_exit_killers.py`, `market_entry_killers.py`, `momentum_killers.py`,
`btc_regime_killers.py`, `reachable_killers.py`, `sensitivity_samecandle.py`. Codex-reviewed
(2 rounds: experiment design + pre-registered hurdles + verdict).

## ADDENDUM 2026-06-06 — "learn from the winners, build our OWN bot" (codex round 3) → also DEAD

Operator: stop copying, instead LEARN what drove the huge winners + build our own. Did it as
forensics (descriptive, not feature-mining), then tested the implied fix.

**Forensic (`winner_forensics.py`, MFE = max favorable excursion in R):**
- The channel DOES flag big movers: top signals reached +18R to **+52R** (SUI +52, DOGE +34,
  WLD +24, XRP +21, ETH +18) ≈ +50-150% underlying moves, almost all LONGS.
- But they **peak 8-14 days later** (t_peak 160-330h), after a drawdown that hits the scalp
  stop first — the biggest eventual winners were copier **losses** (SUI/DOGE/XRP/ETH all −1R).
- Of 50 huge movers (MFE≥5R), market+T1 mean realized **−0.05R** (~10R left on the table each).
- mean MFE 3.2R vs mean **MAE 3.6R** (avg signal hurts more than helps). ⇒ weak-positive
  UNIVERSE/direction skill, strongly-negative EXECUTION skill.

**Implied fix #1 — swing/let-run (`trend_overlay_killers.py`, pre-registered: market entry,
−20% cat stop, trail 25% giveback armed +10%, 45d):** mean **−2.4%/trade**, train −2.8% / OOS
−1.7%, win 56%, **median +7.6%** but fat LEFT tail (96/263 cat-stopped); trail shaken out (top
winners only +15-19%, not the +50% — moves pull back >25% en route).

**Implied fix #2 — pure HOLD (`hold_test.py`, no trail, 14/30/45d, ±cat stop):** WORST —
mean **−3% to −6.3%/trade** every horizon, win 28-37%, **median negative** (−5% to −20%). The
coins pump then give it all back over days.

**Verdict (codex round 3): close the bot-build lane.** The +50R MFEs are transient spikes,
mechanically unharvestable (scalp stops out; trail shakes out; hold round-trips). Tuning a
stop/trail/sizing rule on 263 points to fix the left tail = textbook false discovery (project
already DSR-killed a 1092-combo trend scan). The channel is a weak attention/volatility
*detector*, not a monetizable signal. **Only sanctioned follow-up:** test channel-mentions as a
*pre-registered binary volatility/attention overlay* on the ALREADY-validated Keltner mean-
reversion edge (include/exclude or signal-age buckets ONLY — no entry/exit/band/sizing tuning).
Artifacts: `winner_forensics.py`, `trend_overlay_killers.py`, `hold_test.py`.

## FINAL SANCTIONED TEST 2026-06-06 — channel-as-overlay on validated Keltner edge → FAILS

The one avenue codex green-lit: use channel mentions as a PRE-REGISTERED binary/age overlay on
the ALREADY-VALIDATED KeltnerBounceV1 mean-reversion edge (no Keltner param tuning). Ran the
EXACT Keltner logic (lower-band cross + vol>1.75x + BTC>SMA50; ROI ladder + trailing + −7%;
1h) on all 172 channel coins' continuous 2yr 1h series (`fetch_keltner_data.py` → `keltner_1h/`,
`keltner_overlay.py`); tagged each Keltner trade in-attention (within N days after a mention)
vs baseline (>30d from any mention). Same code both buckets (exit-approx cancels).

| bucket | mean/trade | win% | PF | n |
|---|---|---|---|---|
| baseline (>30d from mention) | +0.16% | 73% | 1.08 | 1081 |
| within 7d of mention | −0.32% | 69% | 0.86 | 35 |
| within 14d of mention | −0.77% | 65% | 0.69 | 77 |
| within 30d of mention | −0.42% | 67% | 0.82 | 165 |

**Channel-attention makes Keltner mean-reversion WORSE** (consistent across windows) — the channel
pumps momentum/euphoria names, exactly Keltner's documented weak regime. Overlay FAILS its
success criterion. Caveats (codex): baseline PF 1.08 ≠ the validated 1.58 (this is 172 small alts
+ approximate exit model, NOT the curated 18-pair stack — do NOT read it as "the Keltner edge");
in-attention is a different coin/regime mix, but the practical conclusion (don't trade Keltner on
channel-proximate names) holds regardless.

## ARC CLOSED. Every use of the channels is now tested and non-positive:
copy (limit/market) · exits (ladder/manage/T1) · sizing · momentum · BTC-regime · reachable-subset
· swing/trail · pure-hold · Keltner-overlay. **Channels add no tradable edge** (and route capital
toward regimes where our validated MR edge is weakest). Bank the lessons; keep capital on the
already-validated fleet. Remaining work = archival only, not another rescue attempt.
