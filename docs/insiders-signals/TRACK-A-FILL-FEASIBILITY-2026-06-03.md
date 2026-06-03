# Track A — can a member who reads his signals profit by copying? (2026-06-03)

Follow-up to the reading validation. The operator's question evolved across the session:
first *"why can't we fill like him?"*, then the sharper *"members profit, so a correct reader
should at least match a typical member — test every way to achieve his gains, we're missing
something."* He was right. Codex-reviewed (four rounds; the conclusion was **corrected twice**
as the methodology improved).

## ⚠️ Correction notice

An earlier version of this doc concluded "copying him loses (−40%)." **That was a methodology
error** — it tested the wrong member behaviour: MARKET entry at signal-arrival (often already
past his zone) + his DISCRETIONARY message-closes (which bank winners tiny). It ignored (a)
limit-in-zone entry and (b) his POSTED TP ladder (30/32 signals carry TPs). A real profitable
member rests a limit in the zone and follows the posted TPs. Correcting both **flips the result
to positive.** The −40% figure is retained below only as the "what-our-bot-naively-did" baseline.

## Answer (corrected)

**Copying him the way members actually do — rest a limit inside the posted zone, then follow
his posted TP ladder — was POSITIVE in the May sample.** The magnitude depends on how patiently
you place the limit, and it is concentrated, so it is "promising, not proven":

| Entry × exit (32 May trades, WEEX, no lookahead) | Gross | Net | Note |
|---|---|---|---|
| market + manage *(our naive bot — the old −40% claim)* | −6.20R | −31% | wrong member behaviour |
| limit near-edge + posted-TP ladder (fills 31/32) | +2.81R | **+6%** | conservative, easy fills |
| **limit mid-zone + posted-TP ladder (fills 18/32)** | +7.49R | **+33%** | realistic, survives ex-top |
| posted-mid + manage | +18.28R | +91% | one HYPE artifact (ex-top −2.25R) |
| edge + ladder *(best-touch fill — optimistic ceiling)* | +25.96R | +130% | NOT achievable; proves zone opportunity |

**Verified real, not survivorship:** codex checked the 14 trades the mid-limit *missed* — they
averaged only +0.14R (not avoided losers), so the +33% comes from better entry prices on the 18
filled trades, not from dodging losers. The winners are distributed (BTC-1609, HYPE, BTC-1644,
BTC-1634), not one artifact — though it survives ex-top but **NOT ex-top-2** (thin tail).

## Honest hedge (codex)

The defensible claim is **"there is copyable edge under patient limit execution + posted TPs"**
— NOT "a typical member reliably makes +33%." It is placement-sensitive (+6% near → +33% mid →
+1% far), concentrated (top-2 trades carry it), and **one month / 31 trades**. The next test
that would settle it is a **multi-month** limit-in-zone + posted-TP run, out of sample.

## Measured result (32 May trades, WEEX, his posted management as exit, net of 0.20% market roundtrip, 5%/trade, no lookahead)

| Entry model | Gross | Net | WR | ex-top (diag.) |
|---|---|---|---|---|
| **Starter-only** (market, full risk — the honest copyable entry) | **−6.20R** | **−7.94R (−39.7%)** | 10/32 | −8.76R |
| **Event-driven** (starter + only *posted* adds) | −6.20R | −7.94R | 10/32 | −8.76R |
| Generic 20/30/50 ladder (*assumed* policy — sensitivity only) | +4.21R | +3.08R | 14/32 | −5.67R |

- **Event-driven ≡ starter-only** because there are no executable posted adds to act on in the
  curated May ledger. Reading more carefully adds nothing — there is nothing to read.
- **Starter-only −6.20R gross exactly reproduces** the published `market+manage` figure in
  `RESULTS_MAY.md` (the −31% market copier) — confirming the model is correct, not a new artifact.
- **The generic ladder is a footnote, not a result.** It turns positive only by *imposing* a
  20/30/50 policy he did not post in this window; it is carried by one HYPE trade (ex-top
  −5.67R); and by construction it underfills winners — for a short, the higher add-legs only
  complete when price rises *against* the starter, so a winning short stays ~20% sized while a
  losing short fills ~100%. Averaging into a zone adverse-selects for a mechanical copier.

## Two sub-findings (both still valid, but NOT the headline)

1. **His *averaging/adds* aren't copyable from the May text** — the curated ledger has 0
   executable add events (his loading posts cluster in early May, before the validated set).
   So we can't reconstruct his *blended average entry*. BUT — and this is the correction — a
   member doesn't need to; resting a single limit in the zone + taking posted TPs is the
   copyable strategy, and it's positive (above). The averaging is his *enhancement*, not the
   *requirement*.
2. **Market entry is the wrong model** — filling at signal-arrival (often already past his
   zone) is what a latency-bound bot does, not what a patient member does. That single choice
   was most of the earlier −31%.

## Honest caveats (codex)

- 1-minute candle simulation, SL-first within a candle — not tick-level intrabar sequencing.
- Concentration: the mid-limit +33% survives ex-top but **NOT ex-top-2** — top-2 trades carry it.
- **31 trades / one month / one signaler.** Enough to say "limit + posted-TP copying was
  positive in May and our −40% was wrong," NOT enough to claim a durable edge.
- Fill rate is in the number (mid-limit fills 18/32) — but live relay latency could lower it.

## OUT-OF-SAMPLE TEST (April) — the May edge does NOT replicate → NO-GO

The +6–33% above was **in-sample only, and the in-sample month is the one Dennis advertised
(+2702%)** — i.e. selection/regime-contaminated. The honest test is a *normal* month. Parsed
April's structured signals (`parse_signals.py`), back-filled the price cache to 04-01 for full
coverage (`backfill_april.py`), ran the **identical** model:

| Month | near-edge limit + posted TP | mid | Note |
|---|---|---|---|
| **May** (Dennis's *advertised* +2702% month) | **+6%** | +33% | in-sample |
| **April** (normal month, full data, 0 dropped) | **−31%** (13/13 filled, **8/13 full stop-outs**) | −11% | out-of-sample |

Same execution rules, same near-edge placement that was +6% in May → **−31% in April.** Codex
verdict: *the May edge did not replicate; in the only non-advertised month tested it was
materially negative.* Pooled (32 May + 13 April = 45 trades): **no demonstrated durable edge.**

## Bottom line (FINAL)

The session's two-part question is fully answered:
- **Read/track his book: YES** (87/87, validated at scale — the genuine, novel, reusable result).
- **Profitably copy him: NO durable edge.** His advertised month (May) reconstructs positive
  under limit+TP, but a clean normal month (April) is −31% under identical rules. The reader
  works; the *signals* don't carry a durable executable edge once you leave the marketed month.

My intermediate "promising / reopens Track B" was **in-sample-only optimism on the advertised
month** — corrected by the OOS test. The full chain of corrections (−40% market-error → +33%
in-sample → −31% OOS) is itself the lesson: the answer was sensitive to method and to *which
month*, and only the out-of-sample, full-data test is trustworthy.

**Status: NO-GO for live deployment. Research-only pending more clean months under frozen
rules. Do not allocate capital.** Honest hedge: 2 months / 45 trades / single trader — enough
to *reject as a demonstrated edge*, not enough to prove structurally unprofitable forever.

The reading substrate remains a reusable asset (claim-auditing — it just debunked his
advertised edge — and trade journaling), independent of the copy-trade verdict.

Artifacts: `track_a_matrix.py` (the full entry×exit matrix + realistic-member model — the
correct one), `track_a_fills_v2.py` (staged-fill sub-finding), `track_a_pnl.py` (live-ledger
PnL), `track_a_staged_fill.py` (first pass, superseded).
