# Hyperliquid partial-TP stop-fill audit (GH #184)

Date: 2026-10-12
Scope: source-only investigation and sanitized offline replay; no production
write, deployment, order, or allocation change.

## Finding

The incorrect quantity originates in CCXT's Hyperliquid order-status parsing,
then passes through Freqtrade unchanged.

Hyperliquid's final order-status shape retains the requested `origSz` and reports
no remaining order size (`sz = 0`). CCXT 4.5.4 computes the unified fill as
`origSz - sz`. That is normally valid, but a reduce-only order can be capped by
the smaller live position. In the AVAX case the original stop request was 8.33,
the position after TP1 was 7.29, and the exchange executed 7.29. The terminal
status therefore became a synthetic 8.33 fill even though the order-specific
execution history contained only 7.29.

Freqtrade 2026.7's `Hyperliquid._adjust_hyperliquid_order` already fetches those
order-specific executions when a terminal order has no average price. It uses
them to set the volume-weighted average and final fill timestamp, but it does not
replace CCXT's `filled` field. `Trade.update_trade` subsequently accepts the
8.33 stop and closes/recalculates the trade from that quantity. Current
Freqtrade `develop` retains the same adapter behavior at the date of this audit.

Primary source locations inspected:

- [CCXT 4.5.4 Hyperliquid parser](https://github.com/ccxt/ccxt/blob/b1425c7c333cabb44215b68c6b4e295892bfd3d9/python/ccxt/hyperliquid.py#L2438-L2485)
- [Freqtrade 2026.7 Hyperliquid adjustment](https://github.com/freqtrade/freqtrade/blob/52bc96f4480b1a0da6a9b455bd00b17fbb6786a5/freqtrade/exchange/hyperliquid.py#L327-L375)
- [Freqtrade 2026.7 trade update](https://github.com/freqtrade/freqtrade/blob/52bc96f4480b1a0da6a9b455bd00b17fbb6786a5/freqtrade/persistence/trade_model.py#L905-L955)

## Reproduction and preserved history

The committed fixture contains only the quantities, prices, fees, timestamps,
and synthetic order identifier already needed to reproduce the public GH #184
case. It contains no account identifier, credential, wallet, or raw production
payload.

Run:

```sh
python scripts/audit_hyperliquid_stop_fill.py \
  tests/fixtures/hyperliquid_partial_tp_stop.json
```

The command intentionally exits 1 when it detects overbooking, so it can serve
as an audit gate. The regression test invokes the same audit function and
asserts the corrected replay.

| Record | Original Freqtrade history | Exchange-fill replay | Preserved interpretation |
|---|---:|---:|---|
| AVAX trade 16 stop quantity | 8.33 | 7.29 | TP1 had already closed 1.04; the 1.04 excess is phantom stop volume. |
| AVAX trade 16 `profit_abs` | -10.040746 | -8.729417 | Original is retained here; corrected replay is 1.311330 less negative. |
| JUP trade 15 stop quantity (open observation) | 307 requested | 192 position remaining | At the issue observation this was exposure to the same defect, not a historical correction; annotate only if the stop later fills. |
| FET trade 17 | 370 recorded | 371 exchange position | Separate one-coin drift noted in GH #184; not attributed to this parser path. |

The replay values include the observed TP1 funding adjustment of -0.0094 and
mirror Freqtrade's per-exit open/close fee valuation. The exchange-net figure in
GH #184 was stated as approximately -8.7; the replay's -8.729417 agrees at that
precision.

## Remediation boundary

The narrow technical correction is to replace a terminal Hyperliquid order's
reported `filled` quantity (and derived `remaining`) with the sum of its
order-specific executions when those executions are available. The same data is
already fetched by Freqtrade for average-price repair. That belongs upstream in
CCXT or Freqtrade's Hyperliquid adapter; applying an unreviewed runtime monkey
patch in a strategy would make execution behavior depend on strategy import
order.

This PR supplies the reproducible case, source location, regression oracle, and
historical annotation requested by the triage comment. It does not silently
rewrite the live SQLite history. Choosing an upstream contribution versus a
pinned local image patch remains an explicit operator/reviewer decision before
runtime remediation.
