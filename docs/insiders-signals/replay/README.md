# Insiders Scalp replay artifacts

`classifications.jsonl` — 428 messages from `last_month_messages.json` classified
by Claude Haiku 4.5 via 6 parallel subagents. One JSON object per line.

This is a frozen artifact so the LLM pipeline is reproducible without re-running
inference. To reproduce the replay numbers (LLM: +$230.80 / 23.08%) without
API access:

```bash
cd ft_userdata/insiders_bridge
mkdir -p out
cp ../../docs/insiders-signals/replay/classifications.jsonl out/classifications.jsonl

# You also need _local/ populated with Eduardo's prototype files:
#   simulator.py, weex.py, parser.py, reader.py, last_month_messages.json

python3 llm_simulator.py
python3 render_report.py
open out/report.html
```

The simulator's open-merge rule reduces the 91 `kind=open` classifications to
70 trades; 16 of those are market-entry rescues filled via WEEX
`get_price_at(signal_timestamp)`.

See [../replay-results.md](../replay-results.md) for the full write-up.
