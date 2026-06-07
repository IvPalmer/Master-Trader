# Lane C — Adverse-selection / uncapturable-edge audit (both channels)

**Question:** The RENDER #2147 case showed a copier can't capture a channel's headline
because the clean win happens BEFORE the entry fills, and the trades that DO fill skew
toward losers. How much of each channel's apparent edge is structurally uncapturable by
ANY mechanical copier (regardless of exit policy)?

Harness: `adverse_selection_audit.py` (offline; own jsonl loader for Insiders, reuses
killers `replay_v2.fetch` cache). For each signal with entry+SL+TP: classify pre-entry-T1,
fill-in-window, and compare "always-fill" (pretend you got the posted entry) vs "real-fill"
(only if the limit actually traded) total R. Winner/loser buckets by the always-fill outcome.

## Results
| channel | usable | pre-entry T1 | never-filled | winner fill-rate | loser fill-rate | always-fill R | **real-fill R** | edge surviving |
|---|---|---|---|---|---|---|---|---|
| Insiders April | 4 ⚠ | 0% | 75% | 33% | 0% | +3.7R | +1.1R | 30% |
| Insiders May | 30 | 3% | 43% | 67% | 67% | +19.5R | +9.5R | 49% |
| **Binance Killers** | **263** | **48%** | 19% | **74%** | **99%** | **+62.0R** | **−25.0R** | **−40%** |

⚠ April N=4 (most April lines lack a clean entry+SL) — directional only, don't lean on it.

## Findings
1. **Binance Killers — the edge INVERTS on real fills.** A magic always-fill copier would
   make +62R; a real limit-copier makes **−25R**. Mechanism is structural, not exit-policy:
   - **48% of signals hit T1 BEFORE the entry would fill** — the channel claims these wins;
     a copier can't get the clean entry.
   - **Losers fill 99% of the time vs winners 74%** — textbook adverse selection: price
     comes back to your entry mostly when the trade is going against you; winners run away
     first. No exit rule fixes a bad fill population.
2. **Insiders May — about half the headline evaporates.** Driven by 43% never-filling
   (not by differential adverse selection — winner/loser fill-rates are both 67% here).
   +19.5R always-fill → +9.5R real-fill (49% survives), still before fees/sub.
3. **Insiders April** points the same direction (loser-fill 0% < winner-fill 33%, 30%
   surviving) but N=4 is too small to weight.
4. **This is the unifying explanation** for why BOTH our validation AND Luc's bot lose,
   and why "a simpler tool" can't escape it: the loss isn't from unsophisticated exits, it's
   from copying RANGE-entry signals where the copyable subset is adversely selected. The
   channel's directional calls can be "real" (high always-fill R) while the *copyable* P&L
   is flat-to-negative.

## Sensitivity (codex-requested, run) — entry mapping: midpoint vs near-edge
Near-edge = the edge price hit FIRST entering the zone (ehi long / elo short) — the most
permissive, earliest-filling assumption.

| channel | metric | midpoint | near-edge |
|---|---|---|---|
| **Killers** | pre-entry T1 | 48% | 40% |
| | winner / loser fill-rate | 74% / 99% | 83% / **99%** |
| | always-fill → real-fill | +62R → **−25R** | +64R → **−22.7R** |
| Insiders May | never-filled | 43% | **3%** |
| | winner / loser fill-rate | 67% / 67% | **100% / 93%** |
| | always-fill → real-fill | +19.5R → +9.5R | +4.1R → **+5.3R** |

Same-candle ordering (Killers T1-exit): only **2/230 (1%)** trades touch SL & T1 in one
candle; flipping to optimistic TP-first recovers just +3.1R of −32.7R (still −29.5R).

## Corrected reading (the sensitivity changed one claim)
- **Killers = robust adverse selection.** The +62R→−25R inversion HOLDS under near-edge
  (+64R→−22.7R) and is not a same-candle artifact. Loser-fill 99% vs winner-fill 74–83%
  regardless of entry mapping. Decisive and mechanism-confirmed.
- **Insiders May ≠ clean adverse selection.** Under midpoint the loss looked like ~half the
  edge evaporating, but it's really a NEVER-FILL problem (43%) that a near-edge limit mostly
  SOLVES (3% never-fill, edge survives at a thin +5.3R). So Insiders May is **fill-assumption-
  dependent and thin**, NOT structurally inverted. Don't overclaim adverse selection here.

## Caveats
- Insiders fill window 6h, Killers 72h (matches each harness). Small Insiders N (April 4,
  May 30); Killers N=263 is robust. Always-fill R uses SL-first vs T1 (structural proxy).

## Verdict
Binance Killers' edge is **structurally uncapturable** for a mechanical copier — the
hypothetical always-fill edge (+62R) becomes −22…−25R on the realistically fillable subset,
robust to entry mapping and same-candle ordering (loser-fill 99% vs winner-fill 74–83%). For
Insiders the picture is thinner/fill-dependent, not a clean inversion. **Exit-only fixes
(T1-exit incl.) cannot repair a fill-adversely-selected trade population** — but this rejects
Luc's recipe and makes an exit-only rescue very unlikely; it does not prove no entry/fill
redesign could ever work. **Do-not-fund stands, mechanism quantified.**
