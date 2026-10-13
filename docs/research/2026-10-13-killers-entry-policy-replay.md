# Killers entry-policy replay (GROA-309) — harness ready, data run pending

Research only. Preregistered as `killers-entry-policy-replay-2026-10-13` in
`ft_userdata/preregistrations.json` (committed before any result existed).

## What is built
`research/copier-validation/killers/entry_policy_replay.py` replays the usable
Killers signals (`killers_signals.json`) under 11 entry policies — chase ≤5/2/1%,
limit-at-zone-top for 1/4/12/24h, wait 1/4/12/24h then chase ≤2% — with the live
posted stop, 8-rung equal ladder (live $10-leg collapse), $12 risk sizing and HL
fees. It reports per policy and per slippage (0%, 0.5%): fill rate, missed-signal
counterfactual (uncapped market entry on the signals the policy skipped), expectancy
in R and $, PF, max DD, earliest-70%/latest-30% split, and a Deflated Sharpe
(N=11 trials). Tests: `tests/test_killers_entry_policy_replay.py` (synthetic candles).

## Run (needs 1m candles; the agent sandbox has no route to Binance/HL)
```
python research/copier-validation/killers/entry_policy_replay.py \
  --cache <dir of 1m json> [--fetch] --out entry_policy_result.json
```
Cache files are `<SYMBOL>_<signal_open_ms>.json`, `[[ts_ms,o,h,l,c],...]` covering
signal time −1m … +14d. `--fetch` downloads Binance USDT-M 1m into the cache.

## Known simplifications (frozen in the preregistration)
No max-open (5) cap and no portfolio interaction; ladder collapse ignores lot-size
rounding; limit fills on touch (optimistic for limit policies); Binance proxy prices.

## Result
Not yet run — see the issue thread.
