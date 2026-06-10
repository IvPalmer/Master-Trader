# Killers copy-trader: posted-SL vs channel-driven exits (shadow replay)

**Question:** should the KillersScalp copy-trader hard-stop at the signal's posted
SL, or ride until the channel posts a close (current behaviour)?

**Method:** replay 278 usable signals from the 2yr classified corpus → 230 filled,
on real Binance USDⓈ-M 15m klines. Both policies share a limit-in-zone entry (near
edge, 72h window) + the posted TP ladder (equal-weight partial exits). They differ
only on the residual:
- `channel_only` — no stop; residual closes at the channel's `close_full` (only
  75/278 had one) else mark-to-last at the horizon; models 5x **isolated
  liquidation** (~−1/LEV adverse move wipes the residual).
- `posted_plan` — residual exits at the posted SL on touch.

5x leverage, taker fee 0.04%/side. Returns in **margin units** (1.0 = +100% of one
position's margin). Conservative same-candle handling (adverse event first).

## Results (horizon sensitivity)

| Hold | channel_only | liq | win | posted_plan | liq | win | SL helps |
|------|-------------:|----:|----:|------------:|----:|----:|---------:|
| 45d  | −25.1 | **91** | 41% | −10.8 | **0** | 28% | +14.4 |
| 14d  | −15.3 | **48** | 45% | −8.7  | **0** | 30% | +6.6  |
| 7d   | −10.7 | **22** | 47% | −7.2  | **0** | 34% | +3.5  |

Case matrix (45d, of 196 SL-breached trades): `co_liquidated` 91 (hard SL saved a
wipeout), `co_recovered` 78 (channel rode back better → SL was locally wrong),
`co_worse` 27 (SL beat riding, no liq), `no_sl_breach` 34.

## Findings

1. **Both policies LOSE at every horizon** — confirms the do-not-fund verdict; a
   hard SL does not create alpha, it loses less.
2. **A hard SL at the posted level reduces the loss and eliminates ALL liquidations**
   in every tested horizon. The benefit is pure tail-risk control and grows with
   hold length.
3. **It's "locally wrong" ~1/3 of the time** (`co_recovered`): the channel often
   rides a breach back. Avoiding the 22–91 liquidations outweighs those give-ups in
   aggregate, but at short holds the margin is thinner (7d: +12.8 from liq-saves
   −16.0 from recoveries +6.8 from SL-better = +3.5 net).
4. Win rate drops ~15pp (it takes small stops on would-be recoveries).

## Caveats (the SL benefit is an UPPER bound)

- **Missing channel closes**: only 75/278 trades have a logged `close_full`, so for
  most trades `channel_only` rides to liquidation/horizon when the real channel may
  have bailed earlier. This makes `channel_only` look worse than reality.
- **Liquidation modeled on 15m trade-candle wicks**, not Binance mark price — real
  isolated liq is mark-price + maintenance-margin driven, so wick-liquidations may
  be overstated. Rerunning liq detection on `markPriceKlines` would tighten it
  (would shrink the magnitude, not flip the sign — even the conservative 7d run
  favours the SL).
- Entry filled at the zone near edge; same for both policies (delta is robust, though
  not perfectly common-mode since SL/TP/liq distances scale with fill).

## Verdict

Posted-SL **dominates channel-only across all tested horizons, by capping tail
risk** — but both remain losing and the exact benefit is uncertain (missing channel
exits + approximate liquidation). **Don't fund either.** If we keep running the
dry-run measurement bot, a hard SL at the posted level is the safer policy — but it
materially changes behaviour (lower win rate, visibly exits trades the channel later
appears to recover), so ship it as an **explicit mode** (`channel_only` vs
`posted_plan`), not a silent change.

Artifacts: `extract_signals.py`, `replay.py`, `killers_signals.json`,
`replay_results.json`. Codex-reviewed (gpt-5.2).

---

# v2 (tightened): mark-price liq, 5m, de-biased residual, strategy sweep

Per codex review, v1 had two opposite biases on the **unobservable residual exit**
(the part of a position left after TPs, when the channel never logs a close).
v2 (`replay_v2.py`) tightens it: 5m candles, **mark-price** liquidation, and the
residual modelled three ways to bracket the truth:
- `last_event` (optimistic) — close residual at the channel's last logged event;
  biases channel_only HIGH because that event is usually a TP-hit announcement at a
  favourable price.
- `close_full_only` (de-biased) — only a real `close_full` closes the residual.
- `none` (pessimistic) — ride to horizon, no channel events.
Also fixed a bug (codex): dynamic stops (breakeven/trailing) were activating on the
SAME candle their TP filled; now they activate next candle.

## channel_only vs best hard stop (5x, 14d), across residual models

| residual model | channel_only | best stop (~fixed −8%) | SL edge | liq (none→stop) | maxDD |
|----------------|-------------:|-----------------------:|--------:|----------------:|------:|
| last_event (optimistic) | +12.0 | +15.1 | +3.0 | 21→0 | −5.4 → −2.4 |
| **close_full_only (de-biased)** | **−15.3** | **−6.0** | **+9.3** | 48→0 | −22 → −14 |
| none (pessimistic) | −22.6 | −7.9 | +14.6 | 64→0 | −29 → −16 |

## Strategy ranking (de-biased close_full_only, 5x)

| strategy | total | win% | liq | maxDD |
|----------|------:|-----:|----:|------:|
| fixed_8pct          | −6.0 | 39 | 0 | −14.3 |
| trailing_after_tp   | −7.5 | 58 | 0 | −10.2 |
| posted_sl           | −7.6 | 31 | 1 | −14.8 |
| breakeven_after_tp1 | −8.6 | 58 | 0 | −11.4 |
| posted_sl+time7d    | −8.8 | 34 | 0 | −14.4 |
| posted_sl_buf2%     | −9.4 | 37 | 1 | −16.9 |
| channel_only        | −15.3 | 46 | 48 | −22.4 |

## Tightened findings

1. **The channel LOSES** — de-biased and pessimistic models are both deeply negative
   (consistent with the dedicated −$511…−$1536/2yr validation). v1/v2's positive
   numbers were the TP-announcement-close artifact (confirmed: `channel_close` exits
   contributed +24.6 of v2's +11.9 at a favourable +14.7% mean). Do-not-fund holds.
2. **A hard stop beats no stop in ALL THREE residual models and both leverages** —
   cuts the loss (de-biased: −15.3 → −6/−8), eliminates liquidations (48–64 → 0–1),
   and roughly halves max drawdown. This is robust risk control, not alpha.
3. **A fixed stop near the posted level is best** — a mechanical ~−8% ≈ the posted SL
   (the posted SLs average ~−8–10%); they perform similarly and lead the table.
4. **Buffer-beyond-SL and time-stops do NOT help** (the buffer's v1 edge was the bias).
   Breakeven/trailing are fine once the same-candle bug is fixed, but don't beat the
   simple stops.
5. Hard stops trade ~15pp of win rate (31–41% vs 46–58%) for far better totals + no
   liquidations — the classic cut-losers tradeoff.

## Verdict (tightened)

Unchanged and now better-supported: **don't fund either policy.** If we keep running
the dry-run measurement bot, a **hard stop at the posted SL (≈ a fixed −8%) is the
safer exit** — it removes the liquidation tail and halves drawdown across every tested
residual model. Ship as an explicit mode (`channel_only` vs `posted_plan`), not a
silent change. Absolute profitability is unproven and most-likely negative.

Artifacts (v2): `replay_v2.py`, `v2_results_*.json`. Codex-reviewed twice (caught the
same-candle-stop bug + the TP-announcement-close bias; both fixed).
