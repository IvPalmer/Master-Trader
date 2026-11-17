# GH #28 remaining evidence tracks

Research only. No live order, config, allocation or deployed strategy changes; the
four preregistrations in `ft_userdata/preregistrations.json` (all `2026-10-12`) freeze
each design before any result exists. Existing preregistrations and epoch labels are
untouched. **No result here is evidence yet**: this PR adds the frozen protocols, the
tested harnesses and the control strategies; the runs need VPS data (funding feathers,
1m OHLCV, the dry-run DB) and are the next step.

| Track | Prereg id | Harness |
|---|---|---|
| FundingFade causal-funding / price-only control | `ff-causal-funding-control-2026-10-12` | `ff_controls.py`, `FFCausalResearch.py`, `common.control_reading_rule` |
| KeltnerBounce exit stack + universe, setup frequency | `keltner-exit-universe-validation-2026-10-12` | `keltner_setup_frequency.py`, `KeltnerExitResearch.py` |
| Insiders fresh sample, separate epochs | `insiders-fresh-sample-2026-10-12` | `insiders_epochs.json`, `insiders_fresh_sample.py` |
| Short Keltner bear-breakdown redesign (separate from V2HL) | `shortkeltner-breakdown-eval-2026-10-12` | `short_keltner_breakdown.py` |

Run order and commands live in each preregistration's `method`/`tool` field. Variants
(`FFCausalResearch.py`, `KeltnerExitResearch.py`) are copied next to the deployed
strategy in a throwaway research `user_data`, refuse to run live/dry, and inherit
everything except the one term/exit under test. The OI track (#18/#152) is already
done and not repeated. Tests: `python3 -m pytest tests/test_evidence_tracks.py`.

Known limits: the Insiders fresh-epoch start (2026-09-12T00:46Z) is the latest
executor boundary recorded in the repo, to be confirmed/amended before counting; the
Short Keltner scorer is an hourly first-touch screen on Binance proxy data, to be
re-run at 1m detail on Hyperliquid data before any dry bot is proposed.
