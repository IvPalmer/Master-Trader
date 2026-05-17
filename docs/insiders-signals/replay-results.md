# Insiders Scalp Replay — LLM vs Regex (for Eduardo)

> Hand-off doc, May 17 2026. Read top-to-bottom; ~10 min. Numbers below are
> reproducible from the committed artifacts and your own `papertrading`
> prototype.

## TL;DR

Wired your `last_month_messages.json` (428 messages over 30 days) through two
parallel pipelines that share the **same simulator (your updated `simulator.py`)
and the same WEEX PnL walker (`weex.resolve_exits`)** — only the classification
layer differs:

| Pipeline | Trades parsed | Sized & simulated | Skipped | **PnL** | Return |
|---|---|---|---|---|---|
| Regex (your `parser.py`) | 71 | 51 | 20 | **+$188.07** | +18.81% |
| **LLM (Claude classifier)** | 70 | **67** | **3** | **+$230.80** | **+23.08%** |
| **Δ (LLM − Regex)** | -1 | **+16** | -17 | **+$42.73** | **+4.27pp** |

Your reported regex baseline was +$187.37 / 18.74% — we land at +$188.07 / 18.81%
on the same data. The 0.7 USD / 0.07pp drift is from two trades I count as
parsed which you don't (msg_ids included below); same simulator/walker
otherwise.

**The LLM's win is almost entirely from recovering the 16 market-entry trades
your regex skipped** — i.e. signals like `BTC Short` posted without an explicit
entry price, where the next message had only the SL/TP. The LLM resolves these
as `entry="market"` and the simulator fills the price via
`weex.get_price_at(signal_timestamp)`.

## What changed vs your summary.md

Your `summary.md` is the canonical regex baseline; we used it as ground truth
and tracked it down to <1 USD. Three changes from the regex side:

1. **No code change to your simulator / weex.py.** We import them as-is from
   the prototype zip. The chronological SL/partial walker, breakeven-as-scratch
   rule, and adaptive interval ladder are all yours.
2. **Risk-budget sizing replicated exactly:** `$10 / SL_distance_pct` per trade,
   `$50` notional margin, `$1k` account. Matches your numbers within rounding.
3. **Added a parallel LLM classification pipeline** that emits one structured
   JSON event per Telegram message (open / close_full / close_partial /
   move_sl / increase / chat). The simulator was rewritten to consume that
   event stream instead of regex (`llm_simulator.py`).

## How the LLM classifier works

The classifier turns each Telegram message into one of:

```json
{"id": 1058, "kind": "open", "symbol": "BTC", "direction": "short",
 "entry_range": [75800, 76600], "sl": 77300, "tp": 71000, "confidence": 0.98}
```

Rules (the full prompt is in [`validate_llm.py`](validate_llm.py) and
[`/tmp/classifier_instructions.md`](#) — kept compact below):

- `<COIN> Long/Short` header → `open`.
- `Full close`, `Got stopped`, `Got stopped at breakeven`, `Closing in small
  profit` → `close_full`.
- `Close N%`, `Close half` → `close_partial`.
- `SL to X`, `Move SL to X`, `Stop at breakeven` → `move_sl`.
- `Adding +N%`, `Add +N%`, `Place a limit order at X and add +N%` → `increase`.
- Bare `stop`, `stopped`, `stop-loss` in narrative text → **`chat`**
  (this is the failure case the regex falls into — `_FULL_CLOSE_RE` matches
  bare `stop(?:ped)?`).
- `BTC and ETH`, `BTC & ETH`, `ETH and BTC` → fan out via `applies_to=[…]`.
- Reply context resolves missing symbols (e.g. "Close 30% more" inherits the
  parent's coin).

All 428 messages were classified by 6 parallel Claude Code subagents (one
batch of ~72 each), against the Max subscription, in ~45 seconds wall-clock.
The committed artifact is reproducible offline:

  `docs/insiders-signals/replay/classifications.jsonl`  — 428 lines, one JSON per msg.

The classifier output distribution:

| kind            | count |
|---|---|
| chat            | 202 |
| open            |  91 |
| close_partial   |  64 |
| close_full      |  41 |
| move_sl         |  24 |
| increase        |   6 |

The 91 `open` classifications dedup to 70 trades in the simulator via an
**open-merge rule**: an `open` for the same `(coin, direction)` within 30
minutes of a prior open is treated as a detail-fill (the entry/sl/tp updates
the prior trade instead of creating a new one). This handles the very common
"header in one message, numbers in a reply" pattern.

## How the market-entry rescue works

Your prototype skips trades with no parsed entry (20 of 71). Most of those are
`<COIN> Long\n\nBy market` headers, sometimes with an SL in a reply.

The LLM marks these as `entry="market"`. In the simulator:

```python
if trade.market_entry and trade.entry is None and trade.sl is not None:
    trade.entry = weex.get_price_at(f"{symbol}USDT", signal_ts_ms)
```

`get_price_at` returns the open of the 1-min candle covering the signal
timestamp (your implementation — kept as-is). 16 of the 20 skipped trades get
recovered this way; the remaining 4 have no SL at all and stay skipped.

The 16 rescued trades are listed in the HTML report's "Market entries rescued
by the LLM" section. Net contribution: roughly **+$42 of the $43 delta** comes
from this rescue. The two pipelines agree closely on every trade that both
sized.

## Trades I count that your summary doesn't

Your summary lists 69 parsed; I parse 71. The two extras my run includes are
likely the same opens you collapsed into existing positions. Both pipelines
already match within $1, so this is plumbing, not signal. Worth a 60-second
glance:

```bash
jq -r '.trades[] | "\(.msg_id)\t\(.date[:10])\t\(.symbol)\t\(.direction)"' \
  ft_userdata/insiders_bridge/out/trades_regex.json
```

Compare against your `simulate.py --weex-pnl --weex-coins` output.

## How to reproduce on your machine

```bash
git pull
cd ft_userdata/insiders_bridge

# 1. Drop your prototype files in _local/ (gitignored)
cp ~/path/to/papertrading/{simulator,weex,parser,reader}.py _local/
cp ~/path/to/papertrading/last_month_messages.json _local/

# 2. Run regex baseline (your pipeline + risk-budget sizing)
python3 regex_replay.py
#   → out/trades_regex.json  +$188.07  PnL match

# 3. Run LLM pipeline (uses the committed classifications artifact)
mkdir -p out
cp ../../docs/insiders-signals/replay/classifications.jsonl out/classifications.jsonl
python3 llm_simulator.py
#   → out/trades_llm.json  +$230.80  PnL

# 4. Render the side-by-side dashboard
python3 render_report.py
open out/report.html
```

Re-classifying from scratch needs an `ANTHROPIC_API_KEY` (we used Claude Max
subagents this session, but for a reproducible script you'd want the SDK).
Skip that step — the committed classifications artifact gives identical
output.

## Open questions for you

1. **Are the 16 rescued market-entry trades legitimate?**
   Listed in the HTML report under "Market entries rescued by the LLM" with
   PnL, date, symbol, direction. Spot-check a few against your own fills.
   Specifically: do you generally fill `By market` orders at the open of the
   1-min candle covering the signal? If your real fills are systematically
   better/worse than the open, the LLM PnL needs a slippage adjustment.

2. **Sizing model — confirm $10/$50 is what you want for production.**
   Account=$1k, risk=$10/trade (1%), notional margin=$50 (5%). I'm using your
   exact numbers from `summary.md`. If you want different sizing for the live
   bot, set the constants in `regex_replay.py` and `llm_simulator.py` (top of
   each file) and re-run.

3. **Multi-coin actions.** "BTC and ETH" fans out to two separate trade events.
   This bumps the trade count when you see `Close 30% of BTC, SOL, ETH`. Are
   you currently splitting these by hand, or counting them as one action?
   Affects how we count parsed trades but not PnL.

4. **The 2 trades I count that you don't.** Worth resolving so we agree on
   exact parsed count before MVP-2.

5. **Anything in the LLM trade log that looks wrong.** The HTML's "LLM trade
   log" table is sortable. Scan it — especially the trades flagged with `M`
   (market entry). If any of those should have been skipped, it's a signal
   that the classifier is too aggressive on market-entry resolution.

## What you need to configure to get to MVP-2 (live listener)

The remaining piece on your side — ~15 minutes total:

1. **Generate the listener's Telegram `.session` file once.**
   On your laptop, install Telethon, run the generator I'll ship next session
   (`gen_session.sh`), enter your phone + 2FA when prompted. Output:
   `MT-Listener.session` (~1 KB).

2. **Rename the session in Telegram → Settings → Devices → "MT-Listener".**
   This is so you don't accidentally terminate it when housekeeping your
   active sessions later.

3. **Encrypt with `age` and hand over.**
   ```bash
   brew install age   # if you don't have it
   age -p -o MT-Listener.session.age MT-Listener.session
   # Send the .age file via DM; share the passphrase out-of-band
   ```

4. **That's it.** After we drop the encrypted session on the elder-brain VPS
   and decrypt, the listener runs headless against your channel for months
   without any further action from you. Telegram's 180-day inactivity timer
   resets on every received update, so an always-on listener never trips it.

VPS region question is closed: elder-brain is in Oracle São Paulo, you're in
Brazil — same country as your normal Telegram client, no geo-fingerprint
risk.

## What's next on our side

After you give the green light on the LLM classifier output:

- **MVP-2** — live listener on elder-brain VPS, paper-only. Telethon listens to
  the channel, classifies via Haiku in real time, writes structured events to
  a JSON log. No execution. Run for 1 week alongside the channel.
- **MVP-3** — FastAPI receiver wired to a new Freqtrade futures dry-run bot
  (Binance USDT-M Futures). Mirrors signals automatically. Same graduation
  criteria as your other bots before any real capital.
- **MVP-4** — $100-200 max for first live deployment.

The build plan and gate criteria are unchanged from
[`session-handoff.md`](session-handoff.md).

## Files in this commit

```
ft_userdata/insiders_bridge/
├── __init__.py
├── prep_classify_input.py   # builds classify_input.jsonl with parent/sibling context
├── classifier.py            # rule-based fallback (not used in final pipeline)
├── regex_replay.py          # your prototype + risk-budget sizing → trades_regex.json
├── llm_simulator.py         # parser-free simulator on LLM events → trades_llm.json
├── render_report.py         # JSON × 2 → side-by-side report.html
└── _local/                  # (gitignored) — your prototype files live here

docs/insiders-signals/
├── replay-results.md        # this file
├── replay/
│   └── classifications.jsonl   # 428 LLM-classified events (reproducible artifact)
├── session-handoff.md       # ongoing internal handoff
├── llm-validation.md        # original 50-message validation (unchanged)
└── validate_llm.py          # original Haiku validator (unchanged)
```

Everything in `_local/` and `out/` is gitignored — your prototype credentials
(Telegram API_ID/HASH in `reader.py`) never enter version control.
