# Exploratory news-event check, 2018-2022 (issue #229)

Exploratory only. Every event is dated on or before 2022-12-31, so the Part C confirmatory window
(2023-01-01 .. 2026-10-31) stays unseen. Nothing here changes the Part C design already frozen in
docs/superpowers/specs/2026-11-03-news-archive-design.md.

- scripts/delist_events.py, run_delist.py: Binance CMS catalog 161 "Binance Will Delist ..." 2022 (archive starts 2022-02-17), Binance spot 5m (data.binance.vision), BTC-quoted pairs converted to USD.
- scripts/upbit_events.py, run_upbit.py: Upbit KRW-market listing notices 2018-2022, first notice per token, token must already trade on Binance spot 1h before t0.
- scripts/veto.py, veto_charts.py: GDELT DOC 2.0 daily counts for (bitcoin|crypto|cryptocurrency) x (crash|plunge|collapse|selloff|hack|bankruptcy), share of all monitored articles; storm = share >= 2x trailing-30d median; outcomes from 00:00 UTC next day.
- Costs: entry t0+5m, 10 bps slippage + 4.5 bps taker per side; returns hedged against BTC.
- out/*.png: charts. Raw downloads (data/) not kept.
