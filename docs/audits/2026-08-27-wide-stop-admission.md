# Wide-stop admission + 24h zone patience (round 5)

Status: deployed 2026-08-27T18:19Z; first organic fleet trade opened 2026-08-28.

## Why zero trades in the first 4 live days was structural

Counterfactual audit (Binance 15m klines) of every actionable signal since the
2026-08-23 cutover:

| Signal | Outcome without us | Binding gate |
|---|---|---|
| ONDO #2212 long | Zone 0.347–0.35 never reachable — price was already 6.5% above at broadcast; limit never filled. Chase would have made ~+3% to TP2, but chasing is the price-verified channel killer | none (channel latency) |
| UNI #2213 long | Zone 21% below broadcast price; limit unfillable. The forceenter 502 cost nothing | none (channel latency) |
| ETC #2215 long | **Real miss**: zone filled 11h after broadcast (7h after the 4h expiry cancelled our limit) and ran +4.7% to TP1 without touching the stop | 4h `unfilledtimeout` |
| BTR #2216 short | +5.4% so far, but BTR is not listed on Hyperliquid | venue listing (unfixable) |
| Insiders BTC short | No SL posted; −1.25% under water since | `posted_sl_required` (correct) |

Structural math: loss-at-stop = notional × stop-distance, and the $11.3
venue-minimum notional therefore caps the admissible stop distance at
8.8% × (risk / $1). The channel posts 11.8–13% stops — with $1 risk, 3 of the
first 4 signals were ineligible before any market judgment was applied.

## Changes (commits `6a2bf58`, `33e35e1`)

- `unfilledtimeout.entry` 240 → **1440 minutes** on both copy-traders. The
  channel's retracement zones routinely fill 8–24h after broadcast; a limit
  crossing toward the SL fills first, so loss stays bounded by the posted-SL
  warden + native stop.
- `KILLERS_RISK_USD` 1 → **2** (killers, admits stops ≤17.7%, ~2% of equity
  per trade) and 1 → **1.5** (insiders, ≤13.3%, ~3% of the 50 USDC account).
- Round-5 measurement epochs stamped at the exact executable-ready timestamps
  (killers 2026-08-27T18:19:08.304Z, insiders 18:19:12.005Z; both DBs empty at
  cutover). Amendment recorded in `preregistrations.json`.

Unchanged, deliberately: `posted_sl_required`, 3% slippage cap, limit-in-zone
entry discipline, venue-minimum-notional skip, and **all autonomous-quant
parameters** (4 days at zero is within their base rates: FF ≈ 11 trades/mo
pre-V2-filter, Keltner ≈ 4/mo).

## First organic trade + exchange-stop verification (2026-08-28)

FundingFadeV1 V2 opened SOL/USDT long 15:00:04Z — $14.98 @ 106.27, epoch DB
`tradesv3.live.FundingFadeV1.v2.sqlite`. Verified in the orders table and the
bot log: the entry limit filled and a **stoploss limit order is resting on
Binance** (stop 101.49, limit 99.47). The "confirm the exchange-resident stop
on the first organic fill" checklist item is closed for the Binance-spot side;
the Hyperliquid side still awaits its first fill (dashboard `native_stop`
tracks it per position).

## Known residual (not yet changed)

Insiders skipped an ETH short (2026-08-28 12:36Z) that *did* post an SL (2550)
because the entry was "market" with no zone → `entry_bounds_missing`
(slippage fail-closed needs entry bounds). A future relaxation could admit
market-entry-with-SL signals by validating the SL side against the live mark
instead of the signal zone. Not applied — recorded for the next review.

## Verification

- 39 dashboard + 155 killers-receiver + 11 remediation tests passing after the
  epoch restamp; receivers log `risk=$2.00` / `risk=$1.50`; both bots load
  `entry: 1440`; dashboard serves the round-5 epoch labels with day counters
  reset.
- Codex was unavailable (usage limit until 2026-08-30); rounds 5–8 are
  Claude-reviewed with the tests and on-venue checks above as evidence.
