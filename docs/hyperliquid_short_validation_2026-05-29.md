# Hyperliquid short-bot validation — self-custody DEX perp path (2026-05-29)

## Why this exists
Operator (Brazil) wants an automated crypto **futures short** bot but:
- **Binance futures are CVM-banned for BR residents** (derivatives = securities; `/futures` redirects to homepage).
- **WEEX** (offshore CEX) was validated and **rejected** — documented profit-freeze/confiscation on small profitable accounts.

The cleanest "free of exchanges" path is a **self-custody DEX perpetual venue** (Hyperliquid): funds in the operator's own wallet, no KYC/residency gate, no custodial company that can freeze. Freqtrade supports Hyperliquid natively via ccxt (unlike WEEX, which ccxt/Freqtrade never supported).

## The candidate: ShortKeltnerV2 (→ ShortKeltnerV2HL)
Inverse-Keltner short-side **mean-reversion** (fade an upper-Keltner-band rejection + volume surge + RSI-was-overbought), gated to **BTC daily close < 200-day MA** (only shorts a confirmed macro bear). 1h, 2x isolated futures, −5% stop, fast ROI ladder (6%→0 over 36h), 36h time-exit, regime-flip/RSI<30 exit, 20 alt-perps.

**Validation status (Binance data):** survives 1m-detail path-aware test (2024→now +27.86%, PF 1.73, MaxDD 9.66%; 2025 & 2026 bit-identical 1h vs 1m), positive 3/3 years, robust to MA-period sweep. **BUT fails Deflated Sharpe at N≥4** (annualized SR 0.855, ~22 trades/yr), in-sample (gate fit to 2024-26 data), 0 live trades. Standing verdict: **dry-run as MEASUREMENT, no capital.** Full detail: memory `project_short_keltner_v2_2026-05-28.md`.

## Key finding — Hyperliquid cannot be backtested
`freqtrade download-data --exchange hyperliquid` → **"Hyperliquid does not support downloading trades or ohlcv data."** HL's live candle endpoint serves only ~5000 candles (≈ days of 1m / months of 1h). **There is no way to backtest on HL-native history.** The Binance backtest does NOT transfer (HL funding is oracle/premium-based; prior research found funding *inverts* vs Binance). Therefore the ONLY HL-native evidence is a **forward dry-run** — which is exactly the bar codex set.

## Pre-registration (codex requirement — fixed before any capital)
| Item | Value |
|---|---|
| Strategy | ShortKeltnerV2HL (logic identical to V2; BTC/USDC:USDC macro-gate informatives) |
| Venue | Hyperliquid perps (USDC-margined), via Freqtrade/ccxt |
| Pairs | 20 alt-perps, all confirmed listed on HL as `X/USDC:USDC` |
| Direction | short-only (longs not enabled) |
| Leverage | 2x isolated |
| Order types | **limit only** (HL has no market orders; ccxt sims market as 5%-slippage limit — we use limit to avoid that) |
| Stop | −5% strategy stop, `stoploss_on_exchange: false` (bot-managed); 36h time-exit; regime-flip/RSI<30 exit |
| Sizing | $100 stake, max 2 concurrent, $200 dry wallet (USDC) |
| Fees/funding | measured from live HL fills + hourly funding (NOT modeled from Binance) |
| Success bar | **positive expectancy after real HL fees + spread + failed fills + funding + stop slippage**, over enough forward trades to matter (~22 tr/yr → many months) |
| Kill rules | pause new entries if reconciler/health detects drift; this is dry-run so no capital at risk |

## Codex verdict (2026-05-29, thread 019e741f, HIGH confidence)
- HL is **safer than WEEX** for freeze/confiscation, but **not "free of exchanges"** — swaps custodial-freeze risk for hot-key, bridge/validator, USDC-collateral, oracle/funding, and BR tax/legal risk. "Research venue, not a solved risk problem."
- Moving the bot to a DEX = **"a freer way to deploy an unproven edge."** Doesn't fix DSR-fail / in-sample / tiny sample / zero live fills.
- For this operator: **don't prioritize futures-short access.** Keep dry-run as measurement; prefer lower-operational-risk edges (spot-only, long/flat, non-levered) where venue failure can't liquidate/gap-stop.
- **NO live capital now.** Single insistence: the pre-registered HL-native forward test above.

### Landmines (track these)
- **BR legal/tax:** perps ARE derivatives → CVM scope + Receita reporting. Self-custody ≠ invisible/tax-free. Get BR tax/legal advice before any capital.
- **Hot key:** when (if) live, use a Hyperliquid **API/sub-wallet** only — NEVER the master wallet key on the VPS. Assume even the API key can trade the account to zero (it can place bad orders, just not withdraw).
- **USDC collateral:** depeg / issuer-freeze / bridge-path risk.
- **HL protocol:** bridge needs 2/3 stake-weighted validator approval for withdrawals; audits ≠ insurance. Oracle/mark-based stop triggers (not Binance last-trade).
- **No market orders:** thin-alt fills + stop execution under stress are the execution unknowns the forward test must quantify.

## Status / next
- ✅ HL supported in Freqtrade image; all 20 pairs listed on HL (USDC-margined).
- ✅ `ShortKeltnerV2HL.py` + `ShortKeltnerV2HL.json` (dry-run, no keys) created.
- ▶ Smoke-test boot in a one-off container, then deploy as a persistent **dry-run** measurement bot (no keys, no capital) to accumulate forward HL fills/funding.
- ⏳ Review forward results against the success bar before even discussing capital.
