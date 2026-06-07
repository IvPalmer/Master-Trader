# Dennis MAY ledger (May 10–29) — copier replication & verdict

**Scope.** 32 signals from the *paid* channel (Insiders Scalp), May 10–29, with posted
entry ranges + hard SL + TP(s), plus the per-trade management posts that follow each
opener. Same validated offline engine as the April run (`harness.py`), run against the
May 1-minute cache (`prices_may/`, WEEX primary + Binance parity, May 8 23:01 → **May 30
20:00 UTC = data end / "today"**).

Dennis's claim for this window: **"+2702% / +$64,394"** headline, footnoted as
**"+120–130% on the account at 5% risk per trade."**

> **Bottom line (REVISED after correctness review).** Under the objective copyable rule
> (posted SL honored, only posted management replayed, no invisible discretion), **the
> realistic-copier figure for the May book is NET NEGATIVE.** Our bot's actual behavior —
> **market entry, posted management** — captures **−31% on the account at 5% risk**, not
> the **+6%** an earlier version of this file reported. The flip is caused by a single
> over-credited line: **BTC-short-1609** was booked as a +5.75 to +7.65R seven-day ladder
> win even though Dennis posted a **breakeven close 24 minutes after entry** (the SL was
> never hit and his TP wasn't reached for 7 more days). Correcting 1609 to the breakeven
> close he actually posted, plus restoring a dropped same-window posted loser (SOL-1483,
> −1R), removes the entire positive result from both market-entry (bot-relevant) models.
> The only models still near Dennis's "+120–130%" are the **patient limit / optimistic
> "edge"** models, which an automated copier does not get, and even those lean almost
> entirely on the uncapturable **HYPE** runaway.

---

## CODEX FINAL GATE (independent senior review) — verdict ROBUST, not cherry-picked

Codex scrutinized the load-bearing BTC-1609 breakeven correction (the line that flipped
the old +6% to negative) and confirmed it is **faithful, not motivated**: msgs 1611/1612/1613
are sequential BTC-context ("Closing around be" at 22:20:53, 24 min after entry), SL 78400
never traded (max high 78,056), TP 73000 first hit 7 days later (05-28 04:02). Crediting it
as a 7-day TP win was the *motivated* choice; booking his posted breakeven is correct.

**The negative verdict does NOT depend on 1609** (independently re-verified):

| market + manage (our bot) | total R | acct @5% (linear) | WR |
|---|---|---|---|
| all 32 trades | **−6.20R** | **−31.0%** | 10/32 |
| **delete BTC-1609 entirely** (cherry-pick test) | **−6.35R** | −31.8% | 9/31 |
| **≤ May 24 only** (fully price-resolved, no late-May tail-caps) | **−4.80R** | −24.0% | 8/24 |
| ex-HYPE (strip the artifact) | −6.17R | −30.9% | 10/31 |

It survives deleting the load-bearing line, restricting to fully-resolved trades, and
removing the HYPE artifact. A skeptic cannot rescue it by attacking 1609.

**Reporting discipline (per codex):** report **R first** (−6.20R), with the % as an explicit
*linear 5%-risk-per-trade translation* (−6.20R × 5% = −31%) — **not a compounded account
return** (naive serial compounding ≈ −27.5%; and 5% on the frequently-concurrent open book
can exceed 100% exposure, so any single account-% is approximate). The `edge` columns are
**diagnostic only** (HYPE unmanaged tail + 1609 late-fill artifacts), never a copier result.

---

## CORRECTIONS APPLIED THIS REVIEW (what changed and why)

Four blocking issues from the correctness review were fixed in `trades_may.json` /
documented here. **No entry/exit model was retuned**; the only data changes are encoding
management Dennis actually posted and restoring a dropped signal.

### [P0] BTC-short-1609 was riding a hold Dennis explicitly disclaimed — FIXED
The opener (src_id 1609, BTC SHORT, 2026-05-21 21:56, Entry 77300–77900, SL 78400,
Target 73000) was coded with **`events:[]`**, so the engine rode it through the mechanical
ladder all the way to **TP 73000**, which BTC only reached on **2026-05-28** (7 days later,
verified in `prices_may/BTC.weex.jsonl`, first low ≤ 73000 at 05-28 04:02). It booked
**+5.75R (posted/manage-fallback), +7.65R (edge), +6.54R (market)**.

But the paid export shows Dennis **closed at breakeven 24 minutes after entry**:
- **msg 1611 (22:20:53):** "Closing around be"
- **msg 1612 (22:21:09):** "If we will fell below 77200 we will open by market"
- **msg 1613 (22:24:32):** "I'll wait for the Asia open"
- by **05-23 04:47** he had flipped to a **BTC LONG** (opener 1634).

Verified in cache: at 22:20 BTC was **~77,575** (≈ entry); the posted **SL 78400 was never
touched** (max high after entry = **78,056**). He was flat at breakeven, not holding.

**Fix:** added a `close_full` event at **2026-05-21T22:20** (mirrors msg 1611) to src_id 1609.
Under the management models the line now books **≈0R** (market+manage +0.15R, posted+manage
+0.03R). This single correction flips both market-entry models from positive to negative
(see §3). The earlier file even admitted in its own `_note` that 1609 was "immediately
hedged in chat (closing around BE)" yet left `events` empty — the management existed and
simply was not extracted. The opposite of the disclosed-and-stripped HYPE artifact: 1609
was *buried* and presented as the bot's cleanest winner.

### [P1] Dropped posted loser SOL-1483 — RESTORED as −1R
An openers scan finds ~40 candidate openers in the May 10–29 window; the original set used
31 src_ids. Among the genuine in-window openers excluded was **src_id 1483 (SOL Short,
2026-05-10 13:28, Entry 94.3–95.7, SL 96.7, Target 89.3)** — a complete signal with
entry + SL + TP — while the **near-identical 1490 SOL short the next day (also −1R) was
kept**. Verified in `prices_may/SOL.weex.jsonl`: at signal SOL was **93.61** (already below
the entry range), rose into the range and **hit SL 96.7 at 18:21 the same day**; TP 89.3
was only reached on **05-15** (5 days later). Under every honest entry model it resolves
**−1R**. Keeping a near-identical losing SOL short while silently dropping this one inflates
the book.

**Fix:** added 1483 to `trades_may.json` (`events:[]`, resolves −1R via the mechanical
SL). The other excluded lines (1722 TON, 1723) are legitimately **post-window** (May 29
23:43 / 23:46) and stay out.

### [P1] HYPE rides 100% UNMANAGED, not "80% with a breakeven stop" — DOCUMENTED
The earlier prose described HYPE as "rides 80% to cache end … close 20%, SL to breakeven."
That is **factually wrong** about what the model does. HYPE's single posted management note
(src_id 1532, 05-14 02:50, "Close 20%, SL to breakeven, avg entry 38.372") is **silently
dropped by the look-ahead guard** under the posted/edge models, because the limit fill does
not occur until **after** the instruction:
- posted fill (38.5) fills at **03:20**; edge fill (38.157) at **03:55** — both later than
  the 02:50 management post.
- the guard (`ms(event) >= fill_ts`) correctly refuses to act on management that predates
  the position — but the consequence is that HYPE then rides **100% fully unmanaged with no
  breakeven stop ever set**, to the MAX_TAIL_HOURS cap. `parts=0`, `exit=tail`.

I verified the breakeven level **38.5 WAS touched at 03:20 (low 38.461)**: under faithful
80%-residual-with-BE management the line would have stopped ≈flat, **not** ridden to +20.53R
(posted) / +32.47R (edge). The reported HYPE win is the 12-day tail cap (59.0 at the 05-26
cap, 67.9 at true cache end), **not** the 80%-ride the prose claimed. The ex-HYPE columns
correctly strip it, so the verdict survives — but the *description* of HOW HYPE behaves is
now corrected here.

---

## (1) TOKEN / SCALE INTEGRITY — PASS (no symbol dropped)

Ran `scale_check.py`: for every trade the cached WEEX close at the signal minute was
compared to the posted entry midpoint, and WEEX↔Binance parity was checked.

| Result | Finding |
|---|---|
| **Largest WEEX-vs-posted deviation** | FIDA **+4.3%**, ETH-1552 **+4.2%**, PUMP-1546 **+3.0%** — all explained by the candle being minutes after the signal, well within a posted *range*. SOL-1483 at signal (93.61) sits below its 94.3–95.7 range — that is a real entry-timing fact, not a scale error. |
| **WEEX vs Binance parity** | within **±0.1%** on **every** symbol. |
| **10×/100×/1000× scale errors** | **none** detected on any symbol. |
| **New alts at risk (FF, VIRTUAL, EIGEN, USELESS, FIDA, NEAR, ETC, LTC, HYPE)** | all priced correctly; no `cmt_<sym>usdt` redenomination failure. |

The earlier red flag (identical 31500/31441 candle counts for every symbol) was a coincidence
of the fetch window, **not** placeholder data. **No line dropped for token/scale.** TON and
SKY exist in the cache but are **not** signals in this window (posted May 29–30, after the
claim window) — unused, harmless.

---

## (2) MANAGEMENT EVENTS — extracted into `trades_may.json` (`events[]`)

Walked every paid-channel post in the May window and attached each "close X%", "SL to
breakeven", numeric "SL to N", "full close", and "got stopped" to its opener by **symbol +
temporal window** (opener → next same-symbol opener, or an explicit full close). Notes on
the hard cases:

- **BTC-1609 breakeven close** is now encoded (the P0 fix above). Without it the engine
  credited a 7-day hold Dennis disclaimed 24 minutes in.
- **BTC is a continuously-averaged swing**, not clean single positions. Dennis adds/trims
  against a moving *average entry* (e.g. "avg 77,240"), so his "BTC close 30%" posts don't
  map cleanly to one signal's fill. Closes were attributed to the open BTC signal in-window
  and the residual rides to the next BTC opener / tail. **This over-credits Dennis** (a real
  single-signal copier can't average like he does) and is flagged per-line.
- **Posts that named a *different* symbol** inside a shared window were **excluded**.
- **Numeric SL moves** (75250, 80350, 73800, 0.00161, etc.) are honored by the engine
  (`sl_to` accepts a number). Faithful engine behavior, not tuning — it can hurt or help.
- The NEAR-1502 and ETC-1587 **inline TP ladders** in the opener are captured by `tps[]`.
- **Look-ahead guard:** under `manage`, an event is applied only if its timestamp is at/after
  the actual fill. This is what makes HYPE (posted/edge fills *after* its lone management note)
  ride unmanaged, and what makes the **edge** fill of 1609 (which doesn't fill until 05-22
  03:50, after the 22:20 close) ride to tail. Both are correct copier physics: you cannot
  close a position you don't yet hold.

---

## (3) HARNESS RUN — three entry × two exit models (32 trades)

`PRICES_DIR=…/prices_may python3 harness.py …/trades_may.json`. Coverage and totals
(R = PnL/risk at the posted SL; account-% = R × 5% risk-per-trade):

| Entry | Exit | Sized | total R | **acct @5%** | WR | total R **ex-HYPE-tail** | acct ex-HYPE |
|---|---|---|---|---|---|---|---|
| posted | ladder  | 18/32 | +7.52  | **+37.6%**  | 7/18  | +3.92  | +19.6% |
| edge   | ladder  | 32/32 | +25.96 | **+129.8%** | 15/32 | +19.96 | +99.8% |
| market | ladder  | 32/32 | +2.56  | **+12.8%**  | 14/32 | +0.29  | +1.5%  |
| posted | manage  | 18/32 | +18.28 | **+91.4%**  | 10/18 | −2.25  | −11.3% |
| **edge** | **manage** | **32/32** | **+44.67** | **+223.4%** | 22/32 | +12.20 | +61.0% |
| **market** | **manage** | **32/32** | **−6.20** | **−31.0%** | 10/32 | −6.17 | −30.9% |

> **Read this before quoting any number.** The two **market**-entry rows are what *our bot*
> actually does (take the market, no waiting for a limit). Both are now **negative**. The
> only rows near Dennis's "+120–130%" are **edge** (optimistic best-touched limit, not
> copyable) and **posted+manage** (+91%), and that +91% is itself **−11% once the
> uncapturable HYPE tail is stripped**. There is no honest model in which a mechanical
> follower clears the claim.

### Effect of the corrections (before → after)

| Model | before (events:[] on 1609, no SOL-1483) | after corrections |
|---|---|---|
| market + manage ("what our bot does") | **+6.0%** | **−31.0%** |
| market + ladder | +17.8% | +12.8% \* |
| posted + manage | +125.0% | +91.4% |
| posted + ladder | +42.6% | +37.6% \* |
| edge + manage | +236.2% | +223.4% |

\* The **ladder** model is purely mechanical (posted numeric TP/SL only; it ignores
discretionary `events[]`). It therefore still rides 1609 to TP 73000 and books the win —
that is the correct meaning of "what a copier gets if it blindly follows the posted numbers
and never reads chat." The breakeven-close correction only changes the **manage** models
(which replay Dennis's posted management), which are the bot-relevant ones. The SOL-1483
−1R lands in every model.

### Per-trade detail (R)

| # | Sym | Dir | Date | claim $ | posted+ladder | **market+manage** | edge+manage | exit (mkt+mng) |
|---|---|---|---|---|---|---|---|---|
| 1 | BTC | S | 05-10 | +11,495 | no_fill | +0.04 | +0.28 | managed_full (avg-swing) |
| 2 | **SOL** | **S** | **05-10** | **n/a (restored)** | **−1.00** | **−1.00** | **−1.00** | **sl (dropped loser, now in)** |
| 3 | ETH | S | 05-11 | +14,381 | no_fill | +0.81 | +0.88 | managed_then_tail |
| 4 | SOL | S | 05-11 | −8,413 | −1.00 | −0.03 | −1.00 | managed_full |
| 5 | ETH | L | 05-12 | +3,593 | +1.50 | −0.17 | +1.26 | managed_full |
| 6 | NEAR | S | 05-12 | −8,011 | −1.00 | −1.00 | −1.00 | sl |
| 7 | FIDA | L | 05-13 | +1,232 | +0.49 | −0.73 | +0.24 | managed_then_sl |
| 8 | PUMP | L | 05-13 | −119 | −1.00 | +0.03 | +0.51 | managed_then_sl |
| 9 | **HYPE** | L | 05-13 | +5,940 | **+3.60** | **−0.03** | **+32.47** ⚠ | **tail (rides 100% UNMANAGED, edge/posted)** |
| 10 | PUMP | L | 05-15 | −1,756 | −1.00 | −1.00 | −1.00 | sl |
| 11 | ETH | L | 05-16 | +2,301 | no_fill | −0.09 | +0.16 | managed_then_sl |
| 12 | BTC | L | 05-18 | +3,951 | −1.00 | −1.40 | −1.00 | sl |
| 13 | FARTCOIN | L | 05-18 | +1,190 | no_fill | +0.06 | +0.33 | managed_full |
| 14 | ETC | S | 05-20 | +579 | no_fill | +0.06 | +0.86 | managed_then_sl |
| 15 | FARTCOIN | L | 05-21 | +3,001 | −1.00 | −0.28 | +0.95 | managed_then_sl |
| 16 | **BTC** | **S** | **05-21** | **−352** | **+5.75** \* | **+0.15** | **+6.08** ⚠ | **managed_full (breakeven close, FIXED)** |
| 17 | FF | S | 05-22 | −2,190 | no_fill | −0.26 | +0.06 | managed_full |
| 18 | ETH | S | 05-22 | +8,253 | no_fill | +0.79 | +0.91 | managed_full |
| 19 | VIRTUAL | S | 05-22 | −3,104 | −1.00 | −1.00 | −1.00 | sl (no mgmt) |
| 20 | PUMP | S | 05-22 | +3,947 | no_fill | +0.75 | +1.12 | managed_full |
| 21 | BTC | L | 05-23 | +11,099 | +3.00 | −0.17 | +3.00 | managed_then_sl |
| 22 | ETH | L | 05-23 | +6,112 | no_fill | −0.13 | +0.91 | managed_then_sl |
| 23 | BTC | S | 05-23 | +3,029 | +3.24 | −0.19 | +1.16 | managed_then_tail (avg-swing) |
| 24 | FARTCOIN | S | 05-24 | +3,408 | no_fill | −0.01 | +0.10 | managed_then_sl |
| 25 | NEAR | S | 05-25 | −3,932 | −1.00 | −0.08 | −1.00 | managed_full |
| 26 | EIGEN | L | 05-25 | +6,722 | no_fill | +0.08 | +0.10 | managed_then_sl (residual→tail) |
| 27 | LTC | S | 05-26 | +311 | no_fill | +0.23 | +0.51 | managed_full |
| 28 | BTC | L | 05-27 | −8,415* | no_fill | −0.51 | −0.31 | managed_full (stopped) |
| 29 | FARTCOIN | L | 05-27 | −3,022 | −1.00 | −0.78 | −0.67 | managed_full (stopped) |
| 30 | PUMP | L | 05-28 | +1,499 | −1.00 | −0.26 | −1.00 | managed_then_sl |
| 31 | FARTCOIN | L | 05-28 | +1,560 | +0.93 | −0.04 | +1.76 | managed_then_sl |
| 32 | USELESS | L | 05-29 | +3,205 | no_fill | −0.04 | +0.01 | managed_then_sl (residual→tail) |

\* Line 16, posted+ladder still shows +5.75R because the **ladder** model is mechanical and
ignores the discretionary breakeven close; the management-aware columns (market+manage +0.15,
edge+manage rides to tail because the edge fill postdates the 22:20 close) reflect the actual
breakeven exit. Trade 27: Dennis's ledger is internally inconsistent (claim_pct +111 but
claim_usd −8,415); post 1696 says "BTC (Long) … got stopped out" — treated as the loss the
chat describes.

**Late-May / not-fully-resolved (cache ends May 30):** trades 25–32 (May 25–29) cannot
forward-walk to their true close; they resolve via posted management or a tail-cap at data
end. **EIGEN (26)** — Dennis's "trade of the month" candidate; only two partials posted,
residual 35% rode to data-end ≈ breakeven (ended 0.221 vs entry 0.2275, never near the 0.31
target in cache). Sim ≈ +0.08R, **not** the +$6,722 claim.

---

## (4) VERDICT — copier capture vs Dennis's "+120–130% / +$64,394"

**Claim arithmetic.** Sum of Dennis's posted per-trade $ = **+$57,494** (his headline +$64,394
is ~12% higher). His per-trade **%** column sums to ~**+2,450%** ≈ the "+2702%" headline —
which, as in April, is a **sum of per-trade percentages on isolated 5–7× leveraged sizing**,
not an account return. The coherent target is the footnote: **+120–130% on the account at 5%
risk** = the `acct @5%` column.

**What a mechanical copier actually captures (posted SL, posted management only):**

| Copier reality | acct @5% | acct @5% (ex-HYPE artifact) |
|---|---|---|
| **Our bot — market entry, manage** (the number that matters for us) | **−31.0%** | **−30.9%** |
| **Our bot — market entry, mechanical ladder** | +12.8% | +1.5% |
| Limit copier, posted entry, manage | +91.4% | −11.3% |
| Optimistic limit ("edge"), manage | +223.4% | +61.0% |

- **For our bot (market entry, posted management) the May book LOSES money: −31% on the
  account.** The earlier "+6%" was an artifact of one over-credited line (BTC-short-1609
  riding a 7-day hold to TP that Dennis closed at breakeven in 24 minutes) plus one dropped
  posted loser (SOL-1483). Correct both and the bot is net negative. The headline "our bot
  makes +6%, the number that matters for us" **does not survive review.**
- Even the **posted+manage** +91% is **−11% once the uncapturable HYPE runaway is stripped**.
  Dennis's "+120–130%" is only reachable under the **edge** (optimistic best-touched limit)
  model, which is not what an automated copier gets, and even that is +61% ex-HYPE.
- **HYPE is the dominant distortion** and (per the documentation fix above) rides **100%
  fully unmanaged** under the limit models, not the 80%-with-breakeven the prose used to
  claim. Its breakeven level was touched; faithful management would have it ≈flat.
- **Coverage / fill honesty:** under the strict **posted-limit** rule only **18 of 32** fill;
  14 limit orders never trade within the 6-hour window. The favorable totals lean on the
  **edge** back-fill (optimistic, not literally copyable).
- **Concentration:** the favorable result rests on HYPE (artifact) and BTC-long-1634; with
  BTC-short-1609 corrected to its real breakeven exit, there is no large clean winner left on
  the bot-relevant side. The median trade is small or negative.

**Plain-language conclusion (hedged).** Under the objective copyable rule — honor the posted
stop, replay only posted management (including the breakeven close Dennis posted on BTC-1609),
no invisible averaging — **the May ledger is net negative for a realistic market-entry copier
(≈ −31%)** and only "directionally profitable" under optimistic patient-limit assumptions that
lean on an uncapturable HYPE runaway. Dennis's +120–130% requires (i) perfect limit fills a
follower can't guarantee, (ii) holding an unclosed HYPE runaway he never told followers to exit,
and (iii) continuous BTC averaging a single-signal copier can't reproduce. As in April: **not
outright fabrication** (most signs and most management posts are real and reconcile), but the
headline is **inflated several-fold to many-fold**, and once you constrain to what *our bot*
executes the result is a **loss**. **Do not fund or size to the claim.**

### Caveats (explicit)
1. **BTC-short-1609 was the single largest favorable distortion** (it carried the entire
   positive market-entry result); corrected to the posted breakeven close, both bot-relevant
   models flip negative.
2. **HYPE +20–32R is a data-end / unmanaged-ride artifact** under the limit models, not a
   copier outcome — the second dominant distortion. The ex-HYPE columns strip it.
3. **SOL-1483 (−1R) was a dropped same-window posted loser**, now restored; the near-identical
   1490 SOL short was already in the set.
4. **BTC averaging** is mapped conservatively to single signals; it still over-credits Dennis.
5. **Edge entry is optimistic** (best touched price); posted-limit coverage is only 18/32. The
   edge model also late-fills 1609 (05-22 03:50, after the 22:20 close), so its breakeven close
   is dropped by the look-ahead guard and that line rides to tail — a known edge-model artifact.
6. **Late-May trades (May 25–29) are unresolved** — they tail-cap at the May 30 data end and do
   **not** reach their claimed targets in-cache (EIGEN especially: claim +$6,722 vs sim ≈+0.1R).
7. **Fees / funding / slippage not modeled** — every total above is gross and would erode
   further (pushing the already-negative market models more negative).
8. **No number here was tuned** to hit +2702% / +120–130% / +$64,394; the entry/exit models are
   the same pre-declared, fixed set used for April. The only data changes were encoding posted
   management (BTC-1609 breakeven close) and restoring a dropped posted signal (SOL-1483).
