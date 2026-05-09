# CascadeFaderV1 — Live-Flip Checklist

**Date:** 2026-05-09
**Status:** PENDING — checklist to clear before flipping `ft-cascade-fader` from dry-run to live.
**Companion to:** `docs/cascade_fader_v1_validation_2026-05-09.md`
**Live config:** `ft_userdata/user_data/configs/CascadeFaderV1.live.json`

---

## Why this exists

CascadeFaderV1 cleared the same backtest bar that approved FundingFadeV1 for live
(actually stronger: PF 1.76 vs 1.29, max DD 0.51% vs ~12%, 5/6 walk-forward windows
positive). The only remaining unknowns are operational: live exchange execution,
Telegram alert path, sqlite persistence, position-tracker handoff. None of these
needed re-validating from scratch since FundingFadeV1 already proved them — but
they need to be observed at least once on Cascade before $50 of real money goes
in.

The flip frame is **Path 1½** (same as FundingFade): tiny capital, plumbing test,
not profit expectation.

---

## Section A · Lab/backtest evidence (already cleared 2026-05-09)

- [x] Lab path-aware sim: PF 1.62, WR 77.8%, +132.8% over 37 months
- [x] Freqtrade native backtest: PF 1.76, WR 84%, max DD 0.51%
- [x] Calibration: 93% match between engines
- [x] Walk-forward: 5/6 calendar halves positive (only 2024-H2 loses, same as Keltner)
- [x] Year-by-year: 3/4 years positive (2025 was −13.7% — known weakness year)
- [x] Methodology bug caught + fixed (path-aware vs forward-extrema)
- [x] Per-pair edge analysis → 13 curated pairs, weak pairs blacklisted

---

## Section B · Pre-flip dry-run plumbing test

Started 2026-05-09 ~05:09 UTC. Earliest flip eligibility: any time after
**3 closed trades** (lowered from FF's bar because cascade signature is rarer
and we just need plumbing confirmation, not expectancy resolution at this point).

- [ ] **B1 — At least 3 closed dry-run trades.** Cadence ~46/yr × 13 pairs / 2
      max_open ≈ 5–10 trades/30d. 3 trades likely within 1–2 weeks.
- [ ] **B2 — At least 1 cascade event detected on chart.** Verify the entry
      condition fires only on real wicks (not noise) by hand-checking the
      open/low/close/volume at trigger time vs the strategy params (≥8% drop,
      ≥40% wick recovery, ≥2× vol).
- [ ] **B3 — At least 1 ROI exit observed.** Confirms the 3% TP fires as
      expected and limit-order close-fills work.
- [ ] **B4 — At least 1 stop-loss exit observed.** OR confirm none fired in
      the dry-run sample (acceptable; ~14% of backtest trades hit SL — small N
      may not see one).
- [ ] **B5 — Telegram alert path verified.** Check that an entry alert posted
      to `@elder_brain_bot` via the trade-webhook → bot_name=CascadeFaderV1.
- [ ] **B6 — Position tracker handoff confirmed.** Cascade shouldn't take a
      trade on a pair that another bot already holds. Simulate with a manual
      open trade in the shared positions file and verify Cascade skips.
- [ ] **B7 — Dashboard tile reflects live data.** `ft-dashboard` shows Cascade
      with non-zero closed_trade_count and a live equity line.

**Expected timeline: 7–14 days from 2026-05-09.** Earliest flip date if all
plumbing fires cleanly: **2026-05-16**. Realistic flip: **2026-05-19 to
2026-05-23**.

---

## Section C · Pre-flip operations

Apply these BEFORE switching the docker-compose entrypoint to the live config.

- [ ] **C1 — Capital sourced.** $50 USDT funded on the same Binance main account
      that hosts FundingFadeV1's $50. (Total deployed capital after flip: $100
      across 2 live bots + $200 BTC ≈ ~$420 blast radius. Same risk envelope
      as FF; do not re-litigate.)
- [ ] **C2 — Binance API key scopes verified.** Reading TRUE, Spot Trading TRUE,
      Withdrawals FALSE, Futures FALSE, all Transfers FALSE, IP restriction
      ENABLED. Same key as FundingFade — single key shared across both live bots.
- [ ] **C3 — Server-time drift check.** Run `ntpdate -q` or check Binance
      server time vs VPS clock; drift must be ≤1s.
- [ ] **C4 — `.env` synchronized.** `FREQTRADE__EXCHANGE__KEY` and
      `FREQTRADE__EXCHANGE__SECRET` populated. (Per the FundingFade
      sync-script-or-collapse fix from 2026-04-21, both BINANCE_* and
      FREQTRADE__EXCHANGE__* sets must hold the same values.)
- [ ] **C5 — REST creds rotated.** Pull current `FREQTRADE__API_SERVER__USERNAME`
      and `_PASSWORD` from the running `ft-cascade-fader` container; confirm
      these match the `.env` values that Dokploy injects.
- [ ] **C6 — Live config reviewed.** Read
      `ft_userdata/user_data/configs/CascadeFaderV1.live.json`:
      `dry_run: false`, `stake_amount: 15`, `max_open_trades: 2`,
      `pairlists: [{"method": "StaticPairList"}]` with the 13 curated pairs,
      `db_url: tradesv3.live.CascadeFaderV1.sqlite`,
      `bot_name: CascadeFaderLive`. Confirm BCH/DOGE/XRP/LINK/TRX are in
      blacklist.
- [ ] **C7 — Operator-abort policy committed.** Tier 1 −10% per-trade gap
      catcher, Tier 2 −20% portfolio circuit breaker, Tier 4 6 consecutive
      losses pause. (Cascade has NO Tier 3 duration check needed because
      backtest DD duration is short — the 240-day Keltner doc's Tier 3 doesn't
      apply.)
- [ ] **C8 — Telegram alert templates updated.** Confirm webhook templates use
      explicit `bot_name: CascadeFaderV1` so live alerts are distinguishable
      from dry-run alerts in the @elder_brain_bot stream.
- [ ] **C9 — Dashboard baseline updated.** `ft_dashboard/app.py` Cascade tile
      already has live-mode baseline values; verify after flip.

---

## Section D · Flip execution

- [ ] **D1 — Stop dry-run container.** `docker compose -f docker-compose.prod.yml stop cascadefaderv1`
- [ ] **D2 — Edit `docker-compose.prod.yml` cascadefaderv1 entrypoint.** Change
      config arg from `CascadeFaderV1.json` → `CascadeFaderV1.live.json`.
      Add `profiles: [live]` to match FundingFade's pattern.
- [ ] **D3 — Commit + push.** `feat(deploy): cascade-fader live flip`
- [ ] **D4 — Wait for Dokploy auto-pull.** Confirm via
      `sudo grep CascadeFaderV1.live.json /etc/dokploy/.../docker-compose.prod.yml`
- [ ] **D5 — Bring up live container.** `cd /etc/dokploy/.../code/ft_userdata && sudo docker compose --profile live -f docker-compose.prod.yml up -d cascadefaderv1`
- [ ] **D6 — Verify live state.** Curl `/api/v1/show_config` on 8097, confirm
      `dry_run: false`, `bot_name: CascadeFaderLive`, sqlite path is
      `tradesv3.live.CascadeFaderV1.sqlite`, balance > 0 USDT.
- [ ] **D7 — Restart-recovery test.** Restart the container once,
      confirm clean reboot and zero open trades at flip time.
- [ ] **D8 — Telegram alert smoke test.** Wait for first cascade entry signal
      live, confirm alert posts to `@elder_brain_bot` with
      `bot_name: CascadeFaderV1` and `direction: long`.

---

## Section E · Post-flip monitoring (first 30 trades)

- [ ] **E1 — First closed live trade.** Log to
      `docs/cascade_fader_v1_first_live_trade.md` with entry/exit/P&L vs
      backtest expectation.
- [ ] **E2 — First losing trade.** Log to same doc; verify SL fired at −7%
      strategy level (NOT operator abort at −10%).
- [ ] **E3 — Daily cadence check.** Track trades/day; compare vs backtest pace
      of ~1.5 trades/30d (~46/yr ÷ 365 × 13 pairs / 2 max_open).
- [ ] **E4 — Weekly P&L vs backtest expected.** First 4 weeks at minimum.
      Threshold: live P&L within ±25% of backtest expected = green; ±25–50% =
      monitor; >±50% = freeze and investigate.
- [ ] **E5 — Calibration drift check at 30 trades.** Compare WR / PF / avg-P&L
      / exit-reason mix vs backtest. If 3 of 4 metrics drift >25% → kill bot
      and revisit.

---

## Section F · Kill conditions (post-flip)

Any one of these triggers immediate kill, not pause:
- Cumulative wallet DD >20% (Tier 2 abort).
- Single trade exceeds −10% (gap event, bypass of strategy SL).
- 6 consecutive losses (2× backtest worst).
- 3 consecutive trades exit via emergency_exit (plumbing failure).
- Live wallet balance unexplained loss vs trade ledger (key compromise alarm).

Post-kill: send Telegram alert, freeze the live config, hand back to operator
for post-mortem.

---

## Capital ladder if Cascade graduates

(Per `project_graduation_criteria.md` v2 progressive scaling.)

Phase 1 (now → 30 trades): $15 stake / 2 max_open / $50 live wallet
Phase 2 (gates 1+2 cleared, drift <25%): $30 stake / 3 max_open / $100 wallet
Phase 3 (90 trades clean): $50 stake / 4 max_open / $200 wallet
Phase 4 (180 trades, full year regime sample): $100 stake / 5 max_open / $500
wallet

Demotion at any tier: drift >30% pause, single trade >8% loss pause, DD breach
1.5× backtest kill.

---

## Why FundingFade flipped without a long dry-run history

Re-litigating-prevention note: when FundingFade flipped 2026-04-21, it had
been dry-run for a few weeks but the actual flip decision was based on
backtest evidence + Path 1½ risk acceptance, not on dry-run sample size. We
are applying the same standard to Cascade. Don't ask "should we wait for 30
dry-run trades first" — that's gate 1, not flip-eligibility. Gate 1 happens
post-flip on real data.

---

## Sign-off

Operator (Palmer) acknowledges:
- [ ] All Section A boxes are checked (backtest bar cleared).
- [ ] All Section B boxes are checked (plumbing observed).
- [ ] All Section C boxes are checked (operations ready).
- [ ] Path 1½ risk frame accepted: $50 blast radius, accept that 1 lab year
      was negative, accept that current regime maps softly to Cascade's losing
      window (2024-H2), accept that 5/6 WF is the calibration target not 6/6.

Signed: ____________________  Date: __________
