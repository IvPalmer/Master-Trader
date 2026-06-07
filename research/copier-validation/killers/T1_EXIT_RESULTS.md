# Lane B — T1-exit-100% + risk-based sizing (Luc's recipe) on Binance Killers

**Question:** Luc's recipe = exit ~100% at first TP + size from the SL distance (per-coin
leverage). `replay_v2` only tested an equal-weight ladder under a stop sweep. Does T1-exit
and/or risk-sizing flip the Killers copier positive?

Harness: `t1_exit_killers.py` (reuses `replay_v2` cached klines + mark-price liquidation,
offline). 278 usable signals → **230 filled** (33 no_fill, 12 incomplete, 3 no_klines).
Returns shown in margin units (leverage view) and in **R** (risk-sized = realized /
SL-distance, fee in R, leverage-independent). Drop-largest on R.

## T1-exit vs ladder (de-biased residual = close_full_only)
| lev / horizon | ladder margin | t1 margin | ladder totR | **t1 totR** | t1 win% | t1 liq |
|---|---|---|---|---|---|---|
| 5x / 14d | −7.57 | −5.11 | −37.68R | **−30.35R** | 59.6% | 0 |
| 5x / 45d | −9.68 | −5.11 | −41.23R | **−30.35R** | 59.6% | 0 |
| 2x / 14d | −3.05 | −2.04 | −37.73R | **−30.35R** | 59.6% | 0 |
| 2x / 45d | −3.89 | −2.04 | −41.27R | **−30.35R** | 59.6% | 0 |

Pessimistic residual (none): t1 = **−32.67R**, win% 59.1% (ladder −43.6R…−47.1R). Worse.

## Robustness (risk-sized R, drop the single largest-|R| trade)
- t1: −30.35R → **−33.52R** (drop IMX +3.16R) — i.e. dropping the best trade makes it MORE
  negative. NOT carried by an outlier.
- ladder: −37.68R → −41.94R (drop SOL).

## Findings
1. **T1-exit does NOT flip Killers positive.** Robustly **≈ −30R over 230 trades**
   (≈ −0.13R/trade) in the de-biased model; pessimistic −32.7R. Drop-largest worsens it.
2. **Risk-sizing is leverage-independent** — same −30.35R at 2x and 5x (margin numbers
   scale with leverage, the R bleed doesn't). Sizing-from-SL changes risk-per-trade, not
   the sign. Luc's "size from the SL" tweak cannot manufacture expectancy.
3. **T1-exit IS the better mechanical exit** (vs laddering): less negative (−30R vs −38…−47R),
   **eliminates liquidations** (1 → 0), halves max-DD. Same risk-control story as the v2
   stop sweep — not alpha.
4. **High win rate, negative expectancy.** T1-exit wins **~60%** of trades (T1 is the
   nearest target, hit often) yet still loses — the average −1R stop exceeds the average
   small T1 win. This is exactly why a copier "feels" like it's winning while bleeding.

## Verdict
**No.** Luc's recipe (T1-exit + risk-sizing) is the *least-bad* mechanical configuration
but still loses ~−30R/230-trades, robustly, before fees beyond taker and before funding/sub.
Consistent with the dedicated −$511…−$1536/2yr Killers validation. **Do-not-fund unchanged.**
