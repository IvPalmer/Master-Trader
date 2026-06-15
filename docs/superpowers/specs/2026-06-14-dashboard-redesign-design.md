# Master-Trader Dashboard Redesign — Design Spec

**Date:** 2026-06-14
**Status:** Approved direction (visual mockups signed off); spec under review
**Author:** Claude (with Palmer)
**Mockups:** `.superpowers/brainstorm/79813-1781484326/content/{ladder-treatments,fleet-overview}.html`

---

## 1. Problem

Two complaints about the `ft-dashboard` fleet-ops UI (served at master-trader.grooveops.dev):

1. **"Everything looks open."** The KillersScalp card shows 8 positions riding for days at large unrealized P&L (TAO +156%, SOL +43%…) with no sign that exits are firing. Root cause: the open-trade rows are driven by Freqtrade REST `/status`, which only knows **whole-position unrealized P&L**. The copy-trader actually takes profit in a cascading TP ladder (TAO has booked 5 of 7 TPs = 71% of the position closed), but that partial-exit reality is **not surfaced anywhere** on the card.
2. **"It feels very cheap."** Good color bones, but flat: no type scale, monospace overused so numbers read like code, near-zero elevation so every card weighs the same, cramped 11.5px tables, faint zebra/hover, and unstyled/generic ECharts.

## 2. Goals

- A cohesive **premium design system** applied across **every tab**: Live, Dry-run, Trades, and per-bot detail (sections A–E).
- Surface partial exits via **Treatment B — "booked vs riding"**: each open trade renders a split bar (profit already taken vs the runner still open) plus a TP-ladder pill, with graceful fallback for single-exit bots.
- **No functional regressions.** Alpine.js bindings and ECharts wiring stay intact.

## 3. Non-Goals (YAGNI)

- No framework swap (no Tailwind/React). No DOM/component re-architecture.
- No new tabs, routes, or features beyond Treatment B.
- No fix to the underlying `positions.pct_open` drift in the receiver (separate flagged follow-up) — Treatment B sidesteps it by computing `booked_pct` from Freqtrade, not from `pct_open`.
- No change to any bot's trading behavior. This is presentation only. **Do-not-fund verdict on KillersScalp is unchanged.**

## 4. Approach

**A CSS design-system layer, not a rebuild.** Rewrite `static/styles.css` around design tokens and restyle each component. HTML changes limited to: (a) small class/markup additions for Treatment B, (b) the tab nowrap fix. JS changes limited to: (a) a shared ECharts theme, (b) computing Treatment-B fields in the existing reactive helpers. Backend changes limited to: (a) `booked_pct`/`riding_pct` per open trade, (b) an optional TP-ladder enrichment for killers.

Rejected alternatives: DOM restructure (risks breaking live Alpine bindings for zero visual gain); Tailwind/component-lib swap (large blast radius, no benefit for a restyle).

## 5. Architecture & Components

### 5.1 Design tokens (`styles.css` `:root`)
Locked from the approved mockups:

- **Palette:** `--bg:#efede4`, `--surface:#fffefb`, `--surface2:#f7f5ed`, `--surface3:#f1eee3`; ink ramp `#12171f / #56606e / #9098a4 / #b6bcc5`; semantics `--green:#0a8f5b (+soft #e2f3ea)`, `--teal:#0e87a3 (+soft #dff0f4, ink #0a6276)`, `--red:#d2473a (+soft #fbe8e6)`, `--amber:#b07a16 (+soft #f7eed8)`; hairlines `#e7e3d6 / #efece1`.
- **Elevation (3 tiers):** `--el1` (base cards/inputs), `--el2` (standard cards/vitals), `--el3` (hover / prominent / command bar).
- **Type scale:** base 14px; display/metric 21–25px @700; section/card titles 11–13px @650–680 with `.04–.13em` uppercase tracking on labels; ledger/body min 12px.
- **Numbers:** `font-variant-numeric: tabular-nums` + `letter-spacing:-.01em` on a `.num` utility. **Monospace reserved for entry/exit prices, order ids, and timestamps only** — not for headline metrics.
- **Radius:** `--r:14px` cards; 7–9px controls.

### 5.2 Restyle inventory (all tabs)
- **Chrome:** header (brand logo w/ gradient + el2, status pill w/ heartbeat), **tab bar** (segmented pills, active = surface + el1, badges, LIVE/DRY chips; **`white-space:nowrap` + horizontal-scroll container** to fix wrapping), command/incident bar (el2, amber/red accent, refined rows), vitals strip (7 cells, tabular metrics, accented p&l cell).
- **Cards:** bot summary cards (identity strip + 4-metric mini-grid), equity, drawdown, per-pair, expectancy, last-trade-trace, recent-trades ledger (12px body, accent-tinted zebra `rgba(8,145,178,.02)`, hover `rgba(8,145,178,.06)`).
- **States:** `.empty` (boost icon opacity 0.6, 14px text), reason pills, tags.

### 5.3 ECharts theme (`dashboard.js`)
A shared theme object (or `echarts.registerTheme`) applied at every `echarts.init`, covering: background transparent, grid/axis line `--hair2`, axis label color `--ink3` + sans font, series colors (`--teal` primary, `--green/--red` markers, `--ink4` dashed for backtest-expected), tooltip surface/hairline/shadow. Touches: `renderEquity`, `renderDrawdown`, `renderPerPair`, `renderCandles`, `renderTradeChart`.

### 5.4 Treatment B — "booked vs riding"
Per open trade: a split bar = **booked%** (solid green) + **riding%** (hatched teal, or hatched red if the runner is underwater), plus a pill.

**Bar data — primary signal, no new infra (scoped, not "universal"):**
`booked_pct` is a correct measure of *fraction of position closed* **only for trades without position adjustment** — i.e. where `amount_requested` is the original filled size and stays stable across partial exits. The Killers bot blocks position adjustment, so this holds for the bot that needs it; other fleet bots are single-exit. It is **not** a general invariant and must be guarded, not assumed.

In `_poll_bot()` (app.py) each open trade from Freqtrade `/status` carries `amount` and `amount_requested`, but `_poll_bot()` currently **drops both `trade_id` and `amount_requested`** from the per-trade payload — **both must be added** (the receiver join needs `trade_id`; the bar + tests need `amount_requested`). Compute, with coercion + guards:
```
ar = float(amount_requested or 0); a = float(amount or 0)            # coerce string/Decimal JSON
if ar <= 0:            booked_pct = None        # unknown denominator → frontend renders plain "open · ±X%"
elif a <= 0:           booked_pct = None        # pending/resting entry not yet filled → not "100% booked"
else:                  booked_pct = clamp(0..100, (ar - a) / ar * 100)
if booked_pct is not None and booked_pct < FEE_DUST_PCT (≈0.5): booked_pct = 0   # ignore fee-dust shrinkage
riding_pct = None if booked_pct is None else 100 - booked_pct
```
Verified: TAO `amount_requested=0.488, amount=0.143` → `booked_pct≈71`. Single-exit bots have `amount==amount_requested` → `booked_pct=0` → bar renders "100% open · ±X%" (graceful fallback). `amount > amount_requested` (shouldn't occur without DCA) clamps to 0. **Before build, probe live `/status` across the fleet to confirm `amount_requested` semantics on this Freqtrade version.**

**Pill data — killers-only enrichment (optional, never load-bearing):**
The TP-count pill ("5 / 7 TPs hit · next @ 295") needs the live cascade state in the **killers-receiver `receiver.sqlite`** — a DB the dashboard does **not** currently mount. (Two distinct Killers DBs exist: the dashboard's observer `state.sqlite` bind, and the receiver's **named volume `killers_receiver_state`** holding `receiver.sqlite`. Keep them separate to avoid binding the wrong one.)
- **Infra:** mount the `killers_receiver_state` volume read-only into `ft-dashboard` at a **distinct path** (e.g. `/var/lib/killers-receiver/receiver.sqlite`); add env `KILLERS_RECEIVER_DB` pointing at it. Do not reuse the `state.sqlite` path/env.
- **Schema (verified):** `target_orders(idx, price, state, ft_order_id, ...)` joined to `positions(pos_id, ft_trade_id, state)`. There is **no `next_tp_price` column** — it is derived.
- **Helper `killers_tp_ladder()`** → `{ft_trade_id: {tps_total, tps_hit, next_tp}}` for open positions:
  - `tps_total = COUNT(*)` of the position's `target_orders` rungs (rejected/cancelled/skipped rows still count as ladder rungs; documented choice).
  - `tps_hit = COUNT(state='filled')`.
  - `next_tp = price` of the lowest-`idx` `state='active'` row, else lowest-`idx` `state='pending'`, else null.
  - Connect with `?mode=ro` + `PRAGMA busy_timeout` (e.g. 2s); wrap queries in try/except `sqlite3.OperationalError` (the receiver writes this DB → `database is locked` is possible). On any failure return `{}` so callers degrade to bar-only.
- **Join:** in `_poll_bot()` for the killers bot, match Freqtrade `trade_id` → `positions.ft_trade_id`, attach `tps_total/tps_hit/next_tp`. **Enrichment failure must never fail the bot snapshot** — wrap the whole call, default to no-pill.
- **Fallback:** `KILLERS_RECEIVER_DB` unset/unreachable/locked → omit the pill, render bar-only.

**Frontend (all open-trade render sites):** the split bar applies wherever open trades render — **dry-run detail rows (`index.html` ~617), per-bot detail rows (~850, the `col-4` open-position card), and the Trades-tab open-trade cards (`openTradesAll()`, `dashboard.js` ~586)**. The TP pill renders only for the killers bot (where `tps_total` is present); elsewhere bar-only. Drive both from the new per-trade fields via the existing reactive helpers (`openTradesForBot()`, `openTradesAll()`).

## 6. Data Flow (summary)

```
Freqtrade /status ─> _poll_bot() ─> open_trades[] (+ trade_id, amount_requested, booked_pct, riding_pct) ─┐
                                                                                                            ├─> /api/state ─> Alpine ─> split bar + pill
receiver.sqlite target_orders ─(ro, busy_timeout)─> killers_tp_ladder() ─> {ft_trade_id: tps_total/hit/next}┘  (killers only; bar-only fallback)
```

## 7. File / unit boundaries

- `static/styles.css` — token block + component sections (reorganized around tokens; the natural structure for a design system). Largest change.
- `static/dashboard.js` — ECharts theme object; Treatment-B render in open-trade helpers. No change to polling/Alpine state shape beyond reading new fields.
- `templates/index.html` — tab nowrap markup; split-bar/pill markup in open-trade rows; class renames as needed.
- `app.py` — `booked_pct`/`riding_pct` in `_poll_bot()`; `killers_tp_ladder()` helper + join; `KILLERS_RECEIVER_DB` env.
- compose (`docker-compose*.yml`) — read-only bind of `receiver.sqlite` into `ft-dashboard` + `KILLERS_RECEIVER_DB`.

## 8. Testing & Verification

- **Backend — `booked_pct` math:** string/Decimal numeric coercion; zero/missing `amount_requested` → `None`; `amount=0` pending/resting entry → `None` (not 100% booked); `amount==amount_requested` → 0 (single-exit); normal partial → correct %; fee-dust below threshold → 0; `amount > amount_requested` → clamp 0; a DCA/position-adjusted fixture → documented behavior (out-of-scope bots) not a crash.
- **Backend — `killers_tp_ladder()`:** fixture sqlite covering filled/active/pending mix (TAO-like → `tps_total=7, tps_hit=5, next=295`), all-pending (`tps_hit=0`), rejected/cancelled rows counted in total; **missing DB file → `{}`**; **locked DB (`OperationalError`) → `{}`** and snapshot still succeeds. Confirm `_poll_bot()` returns a full bot payload even when enrichment raises.
- **Frontend / no-regression:** load each tab on the live dashboard (Live, Dry-run, Trades, each per-bot detail) and confirm: charts still render (non-zero height — see Risks), Alpine bindings intact (counts, incident bar, filters, `x-for` keys), no console errors. Verify split bar + pill for killers across all three render sites, and bar-only fallback for the other bots.
- **Deploy safety:** `ft-dashboard` is independent of the bots; redeploy it with `--no-deps` so no bot container is recreated. FF (live) untouched.

## 9. Risks / Mitigations

- **Breaking Alpine bindings during restyle** → keep class hooks Alpine references; preserve element IDs, `x-*` bindings, and `x-for` keys; restyle is additive/CSS-first; verify per tab.
- **ECharts zero-height / cached-instance breakage** → the real risk isn't Alpine, it's chart containers initializing at 0 height or while `display:none`. Do **not** restyle `.chart`/`.trade-chart` into auto-height or hidden-init states; preserve explicit heights and the existing `_ensureChart()` resize handling.
- **receiver.sqlite locking/permissions** → read-only mount + `busy_timeout`; catch `OperationalError`; bar-only fallback if absent/locked so the pill is never load-bearing and never fails the bot snapshot.
- **`amount_requested` semantics** (DCA/position adjustment, partial/resting entries, fee dust) → scope the claim to no-adjustment trades; coerce + guard divide-by-zero; `None` (plain "open") rather than a wrong %; probe live `/status` before build.

## 10. Out of scope / follow-ups
- `positions.pct_open` drift fix in the receiver (existing flagged follow-up).
- Per-TP fill timeline widget (the `position_events`/`target_orders` history could power it later) — not in this pass.
