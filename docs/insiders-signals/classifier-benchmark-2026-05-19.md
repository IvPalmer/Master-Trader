# Classifier Benchmark — rule (classifier.py) vs Claude (Haiku 4.5)

Run 2026-05-19. Same 428 messages, identical simulator, identical WEEX walker.
Codex-blessed architecture verdict at the bottom.

## Headline

The rule classifier (`classifier.py`, 467 lines of curated Python) agrees with
Claude on **90.2% (386/428) of message kinds**. Sounds great. But the PnL
detail uncovers a phantom-PnL bug class that disqualifies rule-only execution.

## PnL by exit reason (1 day, 428 msgs, $1k account, Eduardo's risk-budget sizing)

| | Claude | Rule classifier |
|---|---|---|
| Total trades parsed | 70 | 78 |
| Total **reported** PnL | **+$516.99** | **+$877.44** |
| ⤷ realized (sl/tp/manual) | +$356 | +$261 |
| ⤷ "open" (still-open phantoms) | +$161 | **+$616** |

**On realized closed trades, Claude beats rule by +$95.** The rule's apparent
+$360 edge is entirely phantom PnL on positions that never closed in the
data window, driven mostly by symbol-parse bugs (e.g. an ETH SHORT trade
with `entry=77100` — that's a BTC price; WEEX then "computed" massive
unrealized profit because ETH at $2300 is far below 77100).

## Disagreement matrix (kind label)

|             | LLM=chat | close_full | close_partial | increase | move_sl | open |
|-------------|---------:|-----------:|--------------:|---------:|--------:|-----:|
| rule=chat   |   182    |     13     |       2       |    0     |    4    |   1  |
| rule=close_full |  4    |     34     |       0       |    0     |    0    |   3  |
| rule=close_partial | 2  |      0     |      59       |    0     |    0    |   3  |
| rule=increase |  0      |      0     |       0       |    4     |    1    |   0  |
| rule=move_sl  |  3      |      0     |       0       |    0     |   21    |   0  |
| rule=open     |  0      |      0     |       0       |    0     |    5    |  86  |

Diagonal = agreement (386 / 428 = 90.2%).

## Disagreement categorized by safety impact

**Rule MISSES real closes (4 cases) — WORST class of bug:**
- "Close PUMP" — rule classifies as chat → PUMP position stays open
- "Closing full position in small loss" — chat → stays open
- "Remaining position got stopp at breakeven" (typo) — chat → stays open
- "Closing BTC short around breakeven" — chat → stays open

**Rule MISSES real SL moves (3):**
- "SL for hedge long to breakeven"
- "Move SL in both trades to breakeven"
- "moving the stop loss back to 0.001991"

**Rule MISSES detail-fill opens (5):**
- Orphan SL/TP replies to a header in another message. Rule sees only SL/TP
  and classifies as move_sl, missing that this completes a pending open.

**Rule FALSE-POSITIVE closes (13):** chat mentions of "stopped"/"got stopped out"
in narrative trigger close_full when the message is actually discussion.

**Rule FALSE-POSITIVE opens (3):**
- "BTC and ETH Shorts ⏎ Closing 50%" — rule mis-classifies header as a new open.
- "BTC ⏎ Close long" — rule parses "CLOSE" as a coin (bug).

## Architecture verdict (codex-blessed)

**Rule-only execution is NOT viable.** Missing real closes is the worst-class
bug — opportunity loss on missed opens but uncontrolled exposure on missed
closes.

**Production policy:**

1. **Rule fast-path ONLY for strict complete opens.** Allow only messages
   with unambiguous `symbol`, `side`, `entry`, `sl`, AND at least one `tp`
   in the SAME message. Reject multi-coin, replies, partial fills, "around"
   / "maybe", any management context.
2. **LLM primary for everything else.** `close`, `close_partial`, `move_sl`,
   `increase`, hedge management, replies, breakeven messages, ambiguous
   operator chatter — all go to Haiku first.
3. **LLM shadow validates rule opens.** If rule says `open` and LLM disagrees
   on `kind`, `symbol`, `side`, or materially different price levels →
   forceexit / no trade.
4. **Hard market sanity checks** before simulate or live execute. A parsed
   ETH entry at BTC prices must be impossible to execute. Symbol-relative
   price bands using live mark price or recent kline range — catches the
   `ETH SHORT entry=77100` failure even if both classifiers miss it.
5. **Optimize for missed-close prevention.** Close/SL-move handling stays
   LLM-led until much stronger evidence.

## Reproduce

```bash
ssh ubuntu@100.96.225.124
cd ~/master-trader/ft_userdata/insiders_bridge

# Eduardo's data must be in _local/ (gitignored). Required files:
#   last_month_messages.json, parser.py, simulator.py, weex.py

# Rule classifier
python3 classifier.py
# → out/classifications.jsonl (rule)

# Run simulator with rule classifications
rm -f out/classifications_*.jsonl
cp out/classifications.jsonl out/classifications_rule.jsonl
python3 llm_simulator.py
mv out/trades_llm.json out/trades_rule.json

# Run simulator with Claude classifications
rm -f out/classifications_*.jsonl
cp ../../docs/insiders-signals/replay/classifications.jsonl out/classifications_claude.jsonl
python3 llm_simulator.py
mv out/trades_llm.json out/trades_claude.json

# Diff (script: scripts/diff_classifiers.py — TBD)
```

## Latency context

Rule classifier: pure Python regex, ~10ms per message. Sub-50ms even for
batches.
Claude Haiku 4.5 via API: ~1-3s per message with prompt cache hit.

So the fast-path saves ~1-3s on strict-complete opens, which is the
production performance win.
