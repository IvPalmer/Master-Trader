# Copy-trader validation — Binance Killers & Dennis/Insiders

Independent, reproducible validation of one question:

> **Can you make money copy-trading two paid crypto Telegram signal channels —
> "Binance Killers" and "Dennis / Insiders Scalp"?**

**Short answer: no — not for a mechanical copier, and not via the obvious fixes.**
The signals carry real directional information, but a follower's *edge dies at the
fill* (you systematically get the losers and miss the winners), and every execution
variant we tested is net-negative after fees. Full numbers + method below. Everything
here is offline, deterministic, and runs on **public Binance data** (no API key) plus
a few small committed input files — so you can re-run it yourself and check.

---

## TL;DR conclusions (all reproduced in this directory)

**Binance Killers** (278 signals, 2yr, real entry/SL/TP, `killers/`)
| execution tried | result (risk-sized R, net of fee) |
|---|---|
| limit-in-zone + ladder | −38 R |
| limit-in-zone + T1-exit | −30 R |
| **market entry + T1-exit** | **−24 R** (least-bad, still negative) |
| risk-based sizing (Luc's "size from SL") | sign-invariant (same R at 2× & 5×) |
| long-only / short-only / SL-distance buckets | every segment negative |
| momentum-confirmation entry | negative in-sample, fails OOS |
| BTC-regime gate | makes it *worse* |
| reachable-entry subset | **−0.28 R/trade** (worst) |
| swing / let-winners-run | −2.4 %/trade |
| pure hold 14/30/45d | −3 to −6 %/trade |
| channel-mentions as a Keltner mean-reversion filter | makes the validated edge *worse* |

**Why:** the channel's posted entry price is structurally unreachable — winners run to
target *before* the entry fills (48 % of Killers signals hit T1 pre-entry), while losers
reliably come back and fill you (loser fill-rate 99 % vs winner 74 %). So the "+62 R if
you magically got every entry" inverts to **−25 R** for a real copier. No exit rule,
sizing rule, filter, or hold horizon fixes a fill-adversely-selected trade population.

**Dennis / Insiders Scalp** (`insiders/`)
- A smart LLM agent *reads* his actively-managed book correctly (87/87 intent, the hard
  part) — see `insiders/causal_replay/`.
- But profitability does **not** follow: multi-month out-of-sample (Feb–May) market+T1 ≈
  **+0.003 R/trade aggregate (flat), negative after costs**, and **ex-top R/trade is
  negative in all four months** → every month's positive is one-trade tail luck. Only May
  (his self-advertised month) looks good = survivorship flag.

Neither channel justifies capital. Detailed write-ups: see the `RESULTS` / `STRATEGY_SEARCH`
docs listed below.

---

## Layout

```
copier-validation/
├── README.md            ← you are here
├── requirements.txt     ← pytest only (scripts are stdlib + Binance public API)
├── killers/             ← Binance Killers validation (fully reproducible from public data)
│   ├── killers_signals.json        the 278 parsed signals (committed input)
│   ├── replay_v2.py                core engine (limit-in-zone + TP ladder + mark-price liq)
│   ├── t1_exit_killers.py          T1-exit + risk-sizing test
│   ├── market_entry_killers.py     market vs limit + long/short/SL segments
│   ├── momentum_killers.py         momentum-confirmation entry (pre-registered, OOS)
│   ├── btc_regime_killers.py       BTC-regime gate (pre-registered, OOS)
│   ├── reachable_killers.py        reachable-entry subset (the decisive test)
│   ├── winner_forensics.py         what drove the big movers (MFE forensics)
│   ├── trend_overlay_killers.py    swing / let-winners-run
│   ├── hold_test.py                pure-hold 14/30/45d
│   ├── keltner_overlay.py          channel-mentions as a Keltner MR filter
│   ├── fetch_keltner_data.py       fetch 1h klines for the overlay test
│   └── RESULTS.md, STRATEGY_SEARCH_RESULTS.md, T1_EXIT_RESULTS.md
└── insiders/            ← Dennis/Insiders validation
    ├── harness.py                  event-driven backtester (entry × exit models)
    ├── t1_exit_test.py             T1-exit on April + May ledgers
    ├── oos_runner.py               cross-month out-of-sample runner
    ├── adverse_selection_audit.py  the fill-adverse-selection audit (both channels)
    ├── dennis_executability.py     net-of-fee executability gate
    ├── parse_signals.py            parse openers from the paid export (needs private export)
    ├── fetch_prices_oos.py         fetch Feb/Mar 1m klines (Binance, public)
    ├── trades.json, trades_may.json, signals_parsed_2026_0*.json   committed inputs
    ├── causal_replay/              the smart-agent reading substrate + unit tests
    └── RESULTS.md, RESULTS_MAY.md, ADVERSE_SELECTION_RESULTS.md, T1_EXIT_RESULTS.md, SPEC.md
```

Price caches are **not** committed (they total ~900 MB and are 100 % regenerable from
Binance). The scripts fetch + cache them on first run. See "Data policy" below.

---

## How to reproduce

Requires **Python 3.9+**. Internet (Binance public REST, `fapi.binance.com`) for the
data-fetching tiers. No API key, no account.

### Tier 1 — causality unit tests (instant, no data, no network)
The smart-agent reading substrate enforces "no look-ahead" by construction. 11 deterministic
tests (a `MockInterpreter`, no LLM):

```bash
pip install -r requirements.txt
python3 -m pytest insiders/causal_replay/tests/ -q
# expect: 11 passed
```

### Tier 2 — Binance Killers strategy search (public data, ~minutes first run)
Each script auto-fetches the klines it needs from Binance and caches them locally (first
run is slow while it downloads; later runs are instant). Run from inside `killers/`:

```bash
cd killers
python3 t1_exit_killers.py        # T1-exit + risk-sizing  → ~ -30 R (negative, robust)
python3 market_entry_killers.py   # market vs limit + segments → all negative
python3 reachable_killers.py      # reachable-entry subset → ~ -0.28 R/trade (the kill)
python3 winner_forensics.py       # what drove the big movers (MFE vs realized)
python3 momentum_killers.py       # momentum entry → fails OOS hurdle
python3 trend_overlay_killers.py  # swing/let-run → ~ -2.4 %/trade
python3 hold_test.py              # pure hold → -3..-6 %/trade
python3 fetch_keltner_data.py && python3 keltner_overlay.py   # MR overlay → negative
```
Numbers should match the tables in `killers/STRATEGY_SEARCH_RESULTS.md`. They're
deterministic (no randomness); only thing that can drift is Binance revising old klines.

### Tier 3 — Dennis multi-month OOS (public data for the OOS months)
The parsed signal ledgers are committed, so you can reproduce the out-of-sample test
without the private export:

```bash
cd insiders
python3 fetch_prices_oos.py       # fetch Feb+Mar 1m klines (Binance)
PRICES_DIR="$(pwd)/prices_feb" python3 oos_runner.py "$(pwd)/signals_parsed_2026_02.json" "FEB"
PRICES_DIR="$(pwd)/prices_mar" python3 oos_runner.py "$(pwd)/signals_parsed_2026_03.json" "MAR"
```
Matches `insiders/T1_EXIT_RESULTS.md` / the OOS table. **Note:** *re-parsing* signals from
raw chat (`parse_signals.py`) and the April/May adverse-selection audit need the **private
paid-channel export** (`insiders/paid_export/`, intentionally gitignored — it's a paid
subscriber's data). The committed `signals_parsed_*.json` / `trades*.json` let you skip that
step and still reproduce the OOS verdict.

---

## Data policy / privacy

- **Bulk price caches are gitignored** (`klines_cache*/`, `prices*/`, `keltner_1h/`, etc.,
  ~900 MB). They are public Binance data; the scripts regenerate them. Keeping them out of
  git keeps the repo cloneable.
- **The raw paid-channel export is gitignored and not shared** (`insiders/paid_export/`,
  `raw_free_messages.json`). The committed, derived `*_signals.json` / `trades*.json` /
  `signals_parsed_*.json` are enough to reproduce the headline results.
- This repo contains paid-channel-derived signal data — **keep it private.**

## Method notes (so the numbers are interpretable)
- **Risk-sized R** = PnL ÷ |entry − stop|, so a full stop = −1 R; leverage-independent.
- **Conservative same-candle handling:** within a candle the adverse move / stop is checked
  *before* the take-profit.
- **Net of fees** where stated (Binance taker 0.04 %/side, in R).
- **Out-of-sample = chronological** (train on the earlier fraction, test on the later),
  never random — and headline claims are checked with a **drop-the-best-trade** robustness
  test, because this market overfits easily (a prior 4940-combo sweep is why we're strict).
- Same code path is used for every variant, so modelling approximations cancel in the
  comparisons.

Verdict, in one line: **the channels are real attention/direction detectors but not
monetizable by a mechanical copier — the edge is consumed at the entry/fill stage, which no
exit, sizing, filter, regime, or hold strategy we tested can recover.**
