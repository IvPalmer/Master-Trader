# Dennis April-ledger replication — SPEC & review brief

**Goal:** produce a *trustworthy* backtest of Dennis's "April 17 – May 6" public
ledger and answer two questions, with numbers we can defend to a sharp, hostile
counterparty (Eduardo, a paid member who has already caught 2 of our errors):

1. How closely can the ledger be **replicated** from the signals actually
   available, and how much of it is **unverifiable** (entry never posted)?
2. What would a **mechanical copier** — honoring the *posted* SL, no invisible
   discretion — actually capture, vs Dennis's claimed result?

## Dennis's claim (the target)
April 17–May 6 STATS post (free channel): 23 trades, **+$22,119**, 18W/5L,
~80% WR; footnote: "at 5% risk/trade, +120–130%... here +88% on $1k → $1,882."
The `claim_usd`/`claim_pct` on each trade in `trades.json` are his per-line numbers.
NOTE: the % column has **inconsistent units across trades** (ASTER "+4%" ≈ spot;
SOL "+409%" needs ~40×). Do NOT treat the % column as a single metric. The $ column
and the +88% account figure are the only coherent targets.

## Inputs (all local, offline)
- `raw_free_messages.json` — 219 Dennis/admin posts + signals, Apr 15–May 7 (free channel 3501314840).
- `trades.json` — 23 ledger lines, structured. Entries/SL/TPs filled where the FREE
  channel posted them; `null` + `entry_source=NO_FREE_SIGNAL_needs_export` where it didn't.
- `prices/<SYM>.weex.jsonl` + `.binance.jsonl` — 1m OHLCV, Apr16–May18.
  WEEX is primary (has the alts). Endpoint: `/capi/v2/market/historyCandles`,
  symbol `cmt_<sym>usdt`, granularity 1m (VERIFIED serves April). Binance = majors/parity.
- `harness.py` — offline event-driven sim. Entry models: posted / edge / market.
  TP-ladder scale-out (equal fractions, SL→breakeven after TP1). Reports R + account-%.

## HARD FACTS established this session (do not relitigate)
- WEEX **does** serve historical 1m for all alts (TRADOOR/LYN/ZEC/PIPPIN/BIO/NAORIS/LAB).
  The earlier "no data" claim was WRONG (used V3 klines, which ignores startTime).
- The free channel posts **most big trades without an entry price** (TRADOOR +$4500,
  ZEC +$6074, LYN −$4448 have NO posted entry). This is the real replication gap —
  not parsing, not data. Confirmed by reading every mention of each symbol.
- Dennis **scales out** across multiple TPs and moves SL to breakeven after TP1.
  A single entry→TP/SL model understates his managed exits.
- On the Binance-testable subset, **AAVE & APT — both claimed WINS — hit Dennis's
  posted SL before any favorable move**; a copier honoring the stop takes −1R. His
  "win" required holding through his own posted stop = discretion, uncopyable.

## The "trustable" bar (when the loop stops)
A result is trustable when independent reviewers (codex + ≥2 skeptic subagents) find
**no unresolved correctness issue** across these dimensions, AND the run is reproducible:
- **Data integrity:** right symbol→`cmt_` map, right price scale (no 1000× errors),
  candles cover each trade's window, WEEX vs Binance agree where both exist (±0.5%).
- **Sim logic:** SL-first sequencing within a candle is conservative & correct;
  TP-ladder fractions sum to 1; SL→breakeven applied after TP1; tail/no-fill/no-sl
  handled; no look-ahead (entry fill only from candles at/after signal minute).
- **Entry-model honesty:** posted/edge/market are pre-declared and FIXED. We do NOT
  tune assumptions to hit +$22,119 (that is the overfitting / fit-to-scoreboard trap
  Eduardo's "iterate until 95% match" idea would fall into). Report all 3 models.
- **Coverage honesty:** explicitly state how many of 23 are sized vs `needs_export`,
  and that the biggest P&L lines are unverifiable from the free channel.
- **Conclusions hedged:** "under the objective copyable rule (posted entry/SL, no
  invisible management)" — never absolute.

## Deliverable
`RESULTS.md`: per-trade table (sim R + $ vs claim) under each entry model; totals;
coverage; the copier-capture number; and a plain-language verdict with explicit
caveats. This becomes the basis for the (codex-reviewed) reply to Eduardo and the
template to re-run the instant Eduardo's paid-channel export (real entries) lands.
