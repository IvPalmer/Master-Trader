# News veto study (issue #229, exploratory)

Read `RESULTS.md`. Published here: `RESULTS.md`, `scripts/`, `results/tables.md`, `results/macro_calendar.csv`.

Not committed (they stay on the VPS in `~/master-trader/research/news_veto_2026-11/results/`):
`vetoed_trades.json`, `veto_results.json`, `run.log`, `run.err`. They hold per-trade rows
(pair, entry time, absolute P&L) built from the bots' trade lists. `RESULTS.md` carries a reduced
"vetoed trades" table (counts and public trigger dates only). The aggregate tables are identical
to those posted on #229 comment 6664557105.

`scripts/news_veto.py` reads trade lists and manifests under `/home/ubuntu/master-trader/research`
(`R` at the top of the file); it has no credentials. It reads trade lists that are not in the repo, so
it only reruns on the VPS.
