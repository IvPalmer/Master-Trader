# weex_probe/ — WEEX integration + Dennis signal validation

Built 2026-05-28 to decide whether to pay Dennis (Insiders/Alpha Scalp) and
trade his signals on WEEX. **Verdict: don't pay** — see
`../docs/SESSION-2026-05-28.md` and the canonical memory file
`~/.claude/projects/-Users-palmer-Work-Dev-master-trader/memory/project_insiders_weex_validation_2026-05-28.md`.

This dir is a prototype/research sandbox. If WEEX is ever productionized, port
`weex_client.py` into `services/insiders-receiver/app/`.

## Headline findings

- Dennis's real edge = **~+9.77%/83d** (proper event-driven backtest on clean
  Binance 1m), NOT the +76% the old sim claimed (that was a phantom-exit bug).
- WEEX ≈ Binance prices (within $0.64/83d). No venue tax.
- WEEX integration fully works (atomic bracket, one-way mandatory, custody $5
  round-trip passed) but WEEX freezes profitable bots (explicit policy).
- Dennis isn't a fraud (14/16 win-claims verified) but markets the edge 5-10×.

## Files

### Integration (reusable)
- **`weex_client.py`** — WEEX USDT-M REST client. OKX-style HMAC sign
  (key+secret+passphrase), 19 endpoints. One-way (COMBINED) mode required for
  management endpoints; hedge mode is broken. Creds loaded from `.env.weex`.

### Backtesting (reusable — vet any signaler)
- **`proper_backtest.py`** — THE correct event-driven backtester. Models
  partial closes, trailing SL moves, and increases at event-time prices, walks
  real 1m OHLCV for SL/TP between events. Fetches clean data on-demand (cached
  in `backtest_klines/`). `python3 proper_backtest.py binance` (weex leg fails
  on old history — use cached comparison). The +9.77% authoritative number.
- **`honesty_audit.py`** — cross-checks a signaler's posted win-claims + entry
  fills against real OHLCV. Catches fabricated TPs / fake fills.
- **`replay_on_weex.py`** — agent's venue-parity walk on cached WEEX klines
  (initial-SL/TP-only model — superseded by proper_backtest, kept for the
  WEEX-vs-Binance parity comparison).

### Live probes (reference — they executed real $ trades)
- `probe_signed.py` — first signed trade-lifecycle smoke test (hedge mode).
- `probe_final.py` — atomic-bracket lifecycle (the production pattern).
- `probe_partial_resize.py` — proved SL/TP algos don't auto-resize after
  partial close (but reduceOnly keeps it safe).
- `probe_idempotency_burst.py` — proved COID dedup + rate-limit headroom.
- `probe_tpsl_variants*.py` — discovered hedge-mode -1054 break.
- `probe_public.py` — no-auth endpoint/coverage probe (28/29 Dennis pairs listed).

### Data
- `historical_klines/` — cached 1m OHLCV, 22 symbols, both venues, Feb-Apr 2026.
- `backtest_klines/` — per-window clean fetches from proper_backtest.
- `.env.weex` — WEEX API creds. chmod 600, gitignored. **Withdraw permission
  OFF** on the key. IP allowlist: Mac 187.89.221.175 + VPS 159.112.191.120.

## Reproduce the core finding

```bash
cd weex_probe
python3 proper_backtest.py binance     # -> ~+9.77% (the honest number)
python3 honesty_audit.py               # -> 14/16 win-claims favorable, no fraud
# inspect the phantom-exit bug in the old sim:
#   trades_llm_2026-05-26.json msg 79 claims BTC exit 76,095 (+$77);
#   real BTC max that window was 69,958 and SL hit at 65,081.
```
