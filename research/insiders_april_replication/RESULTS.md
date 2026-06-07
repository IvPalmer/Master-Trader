# Dennis April-ledger replication — RESULTS

**Run:** `python3 harness.py` (offline, deterministic, WEEX-primary cache).
**Target claim:** Apr 17 – May 6 STATS post (id 8981): 23 trades, **+$22,119**, 18W/5L,
~80% WR, "+88% on $1k at 5% risk → $1,882."
**Scope discipline:** the 3 entry models (posted / edge / market) and the 2 exit models
(mechanical ladder / follow-management) are **pre-declared and FIXED**. Nothing here was
tuned to reproduce +$22,119 or +88%. Every conclusion is hedged to *the objective
copyable rule*: trade only on what Dennis posted, in the free channel, at the time he
posted it.

> **Codex final-gate note (last revision):** independent senior review after the
> multi-agent loop converged. Confirmed the headline reproduces and the manage-vs-ladder
> interpretation is correct. Two fixes applied, **neither changes any headline number**:
> (1) `_simulate_manage` now filters `events[]` to those at/after the true fill_ts — a
> latent pre-fill look-ahead guard (no pre-fill events exist in this dataset, so 0 impact
> now, but correct for future/late-limit fills); (2) relabeled the `edge` model honestly as
> "best favorable price *touched* inside the range" (optimistic limit, not literal edge) —
> `edge` is a sensitivity row, not the headline. Codex's framing guidance is adopted in §5:
> lead with "roughly flat, ~20× below +88%, sign carried by one entry-less line", not "+4.2%".
>
> **Build note (prior revision):** fixed a **look-ahead / sequencing bug** in the
> posted/edge entry models. `_entry_fill` used to return `fill_ts = signal minute` for
> every model, and `simulate()` then walked SL/TP/event management from the *signal*
> minute — not the minute the limit actually filled. For a limit/range copier whose order
> doesn't trade for hours after the signal, that meant management acting on candles
> **before the position existed**. `_entry_fill` now returns the true fill timestamp (the
> first candle whose range contains the fill price) and the walk starts there.
> **Impact: exactly one cell moves — SOL edge·manage +0.711R → +0.745R (Δ +0.034R)** — and
> only because SOL's edge limit (88.88) does not trade until **222 min** (3.7 h) after the
> signal; the previously-walked pre-fill window contained a managed-tail bias that is now
> removed. ASTER edge fills at +11 min, SEI edge at +33 min, SEI posted at +2 min, but
> their pre-fill windows breach no SL/TP/event level so their cells are unchanged. **The
> headline `market·manage` and `market·ladder` totals are NOT affected**: a market order
> fills at the signal-candle open, so its true fill_ts == signal minute (verified lag = 0,
> firstAtOrAfter = True for all 17 placeable trades). The bug was real and structural but
> latent in this dataset; it would bite if posted/edge ever became load-bearing or the
> data changed. See §2 and §3.
>
> **Prior revision (carried):** fixed a tail-exit bug — the harness walked unclosed
> positions to the *last candle in the entire cache* (2026-05-18) instead of stopping at
> the declared `MAX_TAIL_HOURS` 12-day cap. All three tail sites now honor the cap. This
> only moves **unmanaged-tail** cells (ladder model + the no-SL diagnostic); the headline
> **market·manage** total is unchanged because every managed trade closes via a posted
> event well before the cap. See §2 footnote and §4.

---

## 1. Coverage (how many of 23 are actually testable)

| Bucket | Count | Notes |
|---|---|---|
| Total ledger lines | **23** | Dennis's own STATS post |
| Placeable (have a timestamp) | **18 / 23** | 5 are `UNPLACEABLE` — never posted in the free channel with a date (BTC repeat, ASTER-dup, **TRADOOR +$4500**, ETH-dup, FARTCOIN-dup) |
| Posted a hard SL (risk-sizeable) | **12 / 23** | the only lines a 5%-risk copier can size |
| Actually risk-sized in the sim | **11 / 23** | ETH-Apr15 has an SL (2350) but its signal (08:45) **predates the price cache** (first candle 23:41), so it cannot be filled offline. Honest data gap, not fixable without a network fetch. |
| No hard SL posted | **6 / 18 placeable** | LYN, TAO, PIPPIN(Apr28), B, RIVER, PIPPIN(May4) — reported in a separate no-hard-stop diagnostic (§4), never folded into the risk-sized total |

**The five biggest P&L lines are the least verifiable.** TRADOOR (+$4500) is `UNPLACEABLE`.
ZEC (+$6074) and LYN (−$4448) were posted **without an entry price**. SOL (+$5797) and
AAVE (+$1502) have entries but their claimed size implies leverage we can't confirm. So
~$13k of the +$22k headline sits on lines that are either unplaceable or entry-less.

Two corrections made to `trades.json` this build (both *improve* coverage, honestly):
NAORIS and LAB were marked `sl:null` but Dennis **did** post their stops in the free
channel (NAORIS SL 0.14333 id 8531; LAB SL 1.3486 id 8694). They are now sized.

---

## 2. Headline — copier capture under each entry × exit model

`R` = multiples of the 5%-risk unit. `acct@5%` = account-% if each sized trade risked
5%. Only the **11 risk-sized** trades are in these totals.

| Entry | Exit | sized | total R | acct@5% | WR |
|---|---|---|---|---|---|
| posted | ladder | 2/23 | +0.13 | +0.6% | 1/2 |
| posted | **manage** | 2/23 | +0.13 | +0.6% | 2/2 |
| edge | ladder | 4/23 | +3.23 | +16.1% | 3/4 |
| edge | **manage** | 4/23 | +1.25 | +6.3% | 4/4 |
| market | ladder | 11/23 | +8.62 | **+43.1%** | 7/11 |
| market | **manage** | 11/23 | +0.84 | **+4.2%** | 9/11 |

### THE headline number the task asked for
> **Market entry + follow-Dennis's-posted-management: +0.84R total ≈ +4.2% on account
> (5% risk), across the 11 sized trades, WR 9/11.**

Versus Dennis's claimed **+88% / +$22,119**. The objective copyable rule captures
**roughly 1/20th of the claimed account growth.**

### Sensitivity: the positive SIGN rests on one entry-less, inference-dependent line (ZEC)
The +0.84R / +4.2% headline is **dominated by ZEC at +0.92R.** **Remove ZEC and the other
10 sized trades net to −0.08R (−0.4%, WR 8/10)** — i.e. roughly flat. So the line that
pushes the copyable result above breakeven is exactly one of the *least verifiable* lines:
Dennis posted **no entry price** for ZEC (only "SL: 412"), so the harness fills at the
market open (422.38), and its managed exit depends on an **inferred** `frac_of_remaining =
0.50` for the "close another half" post (id 8901). This does **not** invalidate the
conclusion below (which is skeptical — small/positive, not a 2× machine); if anything the
fragility *reinforces* the skepticism. But the honest framing is: **+4.2% is barely
positive and its sign is carried by a single inferred, entry-less trade.**

### Why ladder and manage diverge by ~10× under market entry (the discretion tax)
The mechanical-ladder market number (+43.1%) is **a sim artifact, not a copyable result.**
It is almost entirely **one trade: ZEC = +8.79R of the +8.62R total.** ZEC had a posted
SL (412) but **no posted numeric TPs**, so the mechanical ladder has nothing to scale out
into and rides the full position to the 12-day cap (in-window close $513.66 on May 17,
after a run to $642). But Dennis **explicitly posted that he closed ZEC completely the same
afternoon** at ~$431 (id 8916, "ZEC closed completely"). Following his actual posted
management gives **+0.92R** for ZEC, not +8.79R.

So: **the ladder's +43.1% is what you'd get by ignoring Dennis and riding an unmanaged tail
that he himself did not ride.** The honest "copy Dennis" answer is the manage model: +4.2%.
Where the two models disagree, the disagreement *is* the finding — Dennis's edge (to the
extent it exists in this window) lives in discretionary exits a mechanical copier can't see
in advance.

> **Tail-cap footnote.** Before the `MAX_TAIL_HOURS` fix this build made, the ladder ZEC
> cell read **+10.77R** (acct +53.0%) because the tail grabbed the last candle in the
> *entire* cache (534.18, May 18 — 13 days out, past the 12-day cap). At the correctly
> capped in-window close (513.66, May 17) it is **+8.79R** (acct +43.1%). The artifact was
> itself ~20% larger than the harness's own declared cap permitted; it is now correct. The
> **market·manage** headline (+0.84R / +4.2%, WR 9/11) is **unchanged** by the fix — ZEC
> under manage closes same-day via `close_full` and never reaches the tail.

---

## 3. Per-trade detail (the 12 lines with a posted SL)

R under each model. `—` = not fillable under that entry model. ETH-Apr15 = no price data.

| Symbol | Dir | Claim $ | posted·lad | posted·man | edge·lad | edge·man | market·lad | market·man |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ETH (Apr15) | SHORT | +2620 | no_data | no_data | no_data | no_data | no_data | no_data |
| ASTER | SHORT | +286 | no_fill | no_fill | +1.29 | +0.28 | +1.05 | +0.20 |
| AAVE | SHORT | +1502 | no_fill | no_fill | no_fill | no_fill | −1.00¹ | +0.04 |
| SOL | SHORT | +5797 | no_fill | no_fill | +1.18 | +0.74³ | +0.76 | +0.28 |
| SEI | SHORT | +378 | +1.12 | +0.02 | +1.75 | +0.11 | +1.14 | +0.02 |
| PENDLE | LONG | +505 | −1.00 | +0.11 | −1.00 | +0.11 | −1.00 | +0.11 |
| FARTCOIN (Apr29) | LONG | +811 | no_entry | no_entry | no_entry | no_entry | −1.00 | −1.00 |
| BIO | LONG | +454 | no_entry | no_entry | no_entry | no_entry | +0.39 | +0.52 |
| APT | SHORT | +444 | no_fill | no_fill | no_fill | no_fill | −1.00¹ | −0.72 |
| NAORIS | SHORT | +155 | no_entry | no_entry | no_entry | no_entry | +0.33 | +0.19 |
| LAB | LONG | +1217 | no_entry | no_entry | no_entry | no_entry | +0.16 | +0.29 |
| ZEC | LONG | +6074 | no_entry | no_entry | no_entry | no_entry | +8.79² | +0.92² |

¹ **AAVE & APT (both claimed WINS) hit the posted SL under the mechanical ladder.**
Nuance vs the earlier Binance-only note: on **WEEX** (where Dennis actually trades), the
*manage* model does **not** stop out — AAVE's posted "close 70%, SL→BE" event (Apr 23 06:08)
marks at 91.94 vs a 92.18 short entry (tiny +0.26 favorable), so the copier banks a
near-flat **+0.04R**, *not* the claimed +$1502/+117%. The big AAVE move to 86.57 came
**after** Dennis's posted exit. APT under manage is −0.72R (close-25% partial, then the
remainder stops out). Either way, neither delivers the claimed multi-R win to a copier.

² **ZEC is the single line that carries the headline.** Under the mechanical ladder it is
+8.79R — the unmanaged-tail artifact described in §2 (now correctly capped at the 12-day
in-window close 513.66, was +10.77R against the off-window 534.18 before the fix). Under
**manage** it is +0.92R when Dennis's posted same-day full close is honored — and that
+0.92R is what flips the whole market·manage total positive (ex-ZEC: −0.08R). ZEC is also
entry-less (no posted entry; filled at market open 422.38) and its managed exit uses an
inferred 50% partial (id 8901). Most caveated line in the sheet, and the one the headline
sign depends on.

³ **SOL edge·manage = +0.745R (was +0.711R before the look-ahead fix).** SOL's `edge`
limit (88.88, the favorable high edge of the 88–91 short range) does not actually trade
until **222 min (3.7 h) after the signal**. The old harness walked management from the
signal minute, letting the pre-fill window bias the managed tail; the corrected walk
starts at the true fill minute, +0.034R. This is the **only** cell the fix moves, it is
in a model (`edge`) that is *not* the headline, and it does not change any sign or the
copier verdict. The headline copier number is `market·manage` (§5), which is unaffected.

**Entry-fill reality:** the `posted` model (limit at the exact posted price) fills only
2/23 — most posted entries never trade back to the exact level inside the 6h window, so a
patient limit copier mostly gets left behind. `edge` (favorable range edge) fills 4. And
when those limits *do* fill, they often fill **late**: SEI posted +2 min, ASTER edge
+11 min, SEI edge +33 min, SOL edge **+222 min** after the signal. The harness now walks
management from each trade's *true* fill minute (the look-ahead fix above), so a limit
copier is never credited with managing a position it had not yet entered. Only
`market` (take the open now, like our bots) gets meaningful coverage — and that is the
model whose honest, managed result is **+4.2%.**

---

## 4. No-hard-stop diagnostic (6 placeable lines, no SL posted)

Cannot be risk-sized (no stop → no R). Reported as PnL on the traded notional, market
entry, *not* added to any total above. Shows we are not hiding the entry-less lines —
including the one that carries the biggest claimed loss. **All tail figures here are now
capped at `MAX_TAIL_HOURS` (12 days), not the cache end.**

| Symbol | Dir | Claim $ | ladder (notional %) | manage (notional %) |
|---|---|---:|---:|---:|
| LYN | LONG | **−4448** | −21.18% | −21.18% |
| TAO | LONG | +267 | +23.16% | +0.76% (Dennis closed at BE, id 7395) |
| PIPPIN (Apr28) | LONG | +1040 | −2.25% | +0.88% |
| B | LONG | −143 | +4.22% | +0.00% (BE per id 8410) |
| RIVER | LONG | −703 | +0.27% | +0.27% |
| PIPPIN (May4) | LONG | +90 | +0.97% | +0.97% |

LYN at the **correct 12-day cap** is **−21.18%** (entry 0.08715 on Apr 16 → in-window close
0.06869 on Apr 28). Before the tail-cap fix this read −41.66% because the position was held
~31.6 days to the May-18 cache end — i.e. ~2.6× longer than the harness's own
`MAX_TAIL_HOURS`. So LYN still reproduces a real, sizeable loss in the *direction* of
Dennis's −$4448 (he posted no stop and held into a deep drawdown), but the earlier −41.66%
corroboration was overstated by the same off-window tail bug; the honest capped figure is
about half that. The claimed winners here (PIPPIN +$1040, TAO +$267) remain **not
reproducible from posted info** — PIPPIN's TPs were never posted as numbers, and TAO's
managed exit lands at breakeven (Dennis closed it flat, id 7395) even though an unmanaged
12-day hold would have shown +23%. These are unverifiable / discretionary, by construction.

---

## 5. Copier-capture verdict

**Under the objective copyable rule — fill at market when the signal posts, then do exactly
what Dennis posted to do afterward, honoring posted stops — a mechanical copier captures
about +4.2% on a 5%-risk account across the 11 sizeable trades, with 9/11 winners.** That is
directionally consistent with Dennis's *win-rate* claim (high WR) but **nowhere near his
+88% / +$22,119 account claim** — roughly a 20× gap. **And even that +4.2% is barely above
zero: strip the single entry-less ZEC line and the other 10 sized trades net to −0.4%.** The
modest positive headline is carried by one inferred, entry-less trade — which is itself the
strongest argument for skepticism, not for the claim.

The gap is explained, not hand-waved:
1. **Half the headline P&L is unverifiable.** The 5 `UNPLACEABLE` lines (incl. TRADOOR
   +$4500) and the entry-less giants (ZEC +$6074, LYN −$4448, SOL +$5797) are exactly the
   trades that move the total. A copier could not have placed them from the free channel.
2. **The biggest "win" cells survive only without management.** ZEC's +8.79R requires
   ignoring Dennis's own same-day close. Honor it and ZEC is +0.92R. The mechanical-ladder
   +43.1% is therefore an artifact of an unmanaged tail (capped at 12 days), not a copyable
   edge.
3. **Two claimed winners (AAVE, APT) do not pay a copier.** On WEEX the managed exits are
   near-flat / negative; the favorable moves arrived after Dennis's posted exits. His result
   on these required discretion that was never posted in advance.
4. **The achievable, honest result is small and positive (+4.2%), and fragile** — its sign
   hangs on one entry-less line. A modest WR edge at best, not a 2x-in-3-weeks machine.

### Caveats (explicit)
- **Entry models are fixed; nothing was fit to the scoreboard.** Reporting all three plus
  both exit models is the anti-overfitting guard the spec demands.
- **Management now walks from the true fill minute, not the signal minute** (look-ahead /
  sequencing fix this build). For limit (`posted`/`edge`) fills that trade hours after the
  signal, the old harness managed SL/TP/events across candles before the position existed.
  Only one cell moves — **SOL edge·manage +0.711R → +0.745R** — because only SOL's edge
  limit (88.88) has a pre-fill window (222 min) long enough to matter. Market fills are
  unaffected (fill_ts == signal minute, lag 0), so the **headline `market·manage` +4.2% is
  unchanged**.
- **Tail exits are capped at `MAX_TAIL_HOURS` = 12 days** (fixed a prior build). Earlier numbers
  that walked to the cache end (ZEC ladder +10.77R/+53%, LYN −41.66%, TAO +6.16%, PIPPIN
  −9.72%) were artifacts of holding past the declared cap and have been corrected.
- **Conclusions hold only for the copyable rule.** Dennis may genuinely have made more on his
  own book via leverage, sizing, and discretionary timing none of which is posted. We are not
  claiming fraud on the *direction* of trades — most signals were real and mostly won small.
  We are claiming the **+88% account figure is not reproducible by a disciplined copier from
  the free channel**, and that the headline depends on lines a copier could not place.
- **WEEX is primary** (it carries the alts and is where Dennis trades). SOL WEEX↔Binance open
  parity at signal time = 0.000%; price scales for all 18 placeable symbols match the posted
  entries/TPs (no 1000× errors). One genuine gap remains: ETH-Apr15's signal predates the
  cache start by ~15h, so it is unfilled offline.
- **Some management fractions are inferred** where Dennis said "close first TP" without a %
  (modeled as his usual 25%), the ZEC "close another half" (id 8901, modeled 50% of
  remainder), or attributing the 13:44 "TP2, SL→entry" post to B vs RIVER by proximity (id
  8418 context). These are noted per-event in `trades.json` `events[].note` with source
  message IDs, and they move the total by well under 1R each — except that the ZEC inference
  is load-bearing on the headline *sign* (see §2 sensitivity).

### When to re-run
This template re-runs unchanged the moment Eduardo's **paid-channel export** lands with the
real entries for the entry-less lines (ZEC, LYN, SOL, TRADOOR). Drop the real entries into
`trades.json`, keep the fixed entry/exit models, and the coverage row + market·manage total
update automatically. Until then: **report +4.2%, hedged — and state that ex-ZEC it is ~flat
(−0.4%)** and the 11/23 coverage up front.
