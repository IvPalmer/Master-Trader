# Track A — can we FILL like Dennis if we read every message right? (2026-06-03)

Follow-up to the reading validation. The operator's question: *we proved the agent reads
his messages at 87/87 — so why can't it fill like him?* This answers it with a measured fill
model, not an assertion. Codex-reviewed (two rounds; the model was corrected after the first).

## Answer

**At 87/87 reading fidelity, we still cannot fill like him from the May messages — not
because the reader fails, but because the fill information is absent from the text.** The
messages provide entry *zones* and *exits*, but not the discretionary add/loading behaviour
that determines his actual average entry. In the validated May window he posts zones + manages
exits, but the curated trade ledger contains **0 executable add events** (his loading/averaging
posts cluster in early May, before the validated set).

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

## The mechanism (why reading ≠ filling)

His posted signal is a *zone* (`Entry 81300-83500`), not the price he got. Where inside a
2,200-point zone he actually filled, and how he laddered across it, is **never stated**. His
edge is execution discretion — watching the book, timing the adds — which exists only on his
screen, never in the text. Perfect text-reading cannot recover a number that was never typed.
So: **reading is not the remaining bottleneck; the missing variable is unposted fill
discretion.**

## Honest caveats (codex)

- 1-minute candle simulation, SL-first within a candle — not tick-level intrabar sequencing.
- `ex-top` is a quick concentration diagnostic (subtracts the largest gross winner from
  aggregate net), not an exactly-recomputed net-without-that-trade.
- 32 trades / one month / one signaler. Underpowered for a universal claim; sufficient to
  answer "can we fill like him *from these messages*" — no.
- Exit basis = curated posted-management ("if we interpret all his management correctly"),
  the entry-fidelity diagnostic — not the live-bot end-to-end number.

## Bottom line

The session's two-part question is fully answered:
- **Read/track his book: YES** (87/87, validated at scale — the hard, novel part).
- **Fill like him: NO** — the May messages contain zones + exits but not the fill discretion
  that produces his average entry; the honest copyable entry (market starter + posted
  management) loses (−6.20R gross / −40% net), reproducing the original mechanical finding.

Reading was always the open question worth proving, and it's proven. Filling was never a
reading problem — it's a missing-data problem, and the data isn't in the channel.

Artifacts: `track_a_fills_v2.py` (corrected model), `track_a_pnl.py` (live-ledger PnL),
`track_a_staged_fill.py` (first-pass, superseded).
