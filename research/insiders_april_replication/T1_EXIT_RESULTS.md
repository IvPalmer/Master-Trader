# Lane A — T1-exit-100% policy (Luc's style) on Insiders/Dennis

**Question:** Luc (an apparently-profitable copier) exits ~100% at the first TP rather
than laddering or following Dennis's management. Neither baseline exit model tested this.
Does exiting all at T1 flip a mechanical Dennis copier positive?

Harness: `t1_exit_test.py` (reuses `harness.py` primitives, offline, SL-first conservative,
risk = |entry−sl|, R reported, acct@5% = R×5). Run on April (`trades.json`) + May
(`trades_may.json`, `PRICES_DIR=prices_may`).

## Results (totalR / acct@5% / WR), baseline ladder & manage vs t1_exit

### April (trades.json) — small N (most lines no_entry/unplaceable; data-limited)
| entry | ladder | manage | **t1_exit** | t1 drop-largest |
|---|---|---|---|---|
| posted | +0.12R / +0.6% / 1-of-2 | +0.13R | **+0.12R / +0.6%** | −1.00R (drop SEI) |
| edge | +3.23R / +16.1% | +1.25R | **+3.23R / +16.1% / 3-of-4** | +1.48R (drop SEI) |
| market | +8.62R / +43.1% | +0.84R | **+8.83R / +44.1% / 7-of-11** | **+0.03R / +0.2% (drop ZEC)** |

### May scalp (trades_may.json) — 32 trades
| entry | ladder | manage | **t1_exit** | t1 drop-largest |
|---|---|---|---|---|
| posted (18 fill) | +7.52R / +37.6% | +18.28R / +91.4% | **+8.51R / +42.5% / 7-of-18** | +2.76R / +13.8% (drop BTC) |
| edge (32) | +25.96R / +129.8% | +44.67R / +223.4% | **+27.75R / +138.8% / 15-of-32** | +20.10R / +100.5% (drop BTC) |
| market (32) | +2.56R / +12.8% | −6.20R / −31.0% | **+2.42R / +12.1% / 14-of-32** | **−4.12R / −20.6% (drop BTC)** |

## Findings
1. **T1-exit ≈ the mechanical ladder everywhere** — it is NOT a meaningful improvement
   over equal-weight scale-out (within a few % on every entry model, both ledgers).
2. **The one real effect: T1-exit beats the "follow-Dennis-management" model on market
   entry** — May market goes from **−31% (manage) to +12% (t1_exit)**. Mechanism: Dennis's
   frequent breakeven-closes CAP a follower's winners; booking the T1 win before the
   roll-back avoids that. So if you DO copy at market, exit-at-T1 > mirroring his mgmt.
3. **Every positive is GROSS and one-trade-fragile.** April market +44% → **+0.2% ex-ZEC**
   (the entry-less line). May market +12% → **−20.6% dropping one BTC trade.** Fails the
   drop-largest robustness test on the realistic (market) path.
4. **The "good" numbers need an unrealistic fill.** `edge` (best price touched in range)
   is optimistic; `posted` (real limit) fills only **18/32** in May (adverse selection —
   see Lane C). `market` = chasing, the worst fills + full taker fees ×32 trades.
5. Net of fees/funding/$275 sub, the only survivor (May market +12% gross, fragile) does
   not clear costs.

## Verdict
T1-exit is **not the unlock.** It modestly out-performs following Dennis's management
(because his breakeven-closes cap winners), lifting May-market from −31% to +12% gross —
but it ties the dumb ladder, every positive dies on a one-trade drop or on fees, and the
realistic-fill version only fills half the signals. **Do-not-fund unchanged.**
