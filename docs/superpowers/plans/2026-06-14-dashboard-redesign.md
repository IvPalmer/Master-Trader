# Master-Trader Dashboard Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the `ft-dashboard` fleet UI into a premium design system across all tabs, and surface partial take-profit exits per open trade as a "booked vs riding" split bar (+ killers TP-ladder pill).

**Architecture:** CSS-layer redesign (rewrite `static/styles.css` around tokens; small markup edits) keeping Alpine.js + ECharts intact. Treatment B computes `booked_pct` from Freqtrade `/status` (`amount_requested` vs `amount`) in `app.py`, plus an optional killers TP-ladder read from a read-only mount of the live `receiver.sqlite`.

**Tech Stack:** Python (FastAPI, httpx, sqlite3), Alpine.js, ECharts 5, vanilla CSS, Docker Compose. Tests: pytest.

**Spec:** [docs/superpowers/specs/2026-06-14-dashboard-redesign-design.md](../specs/2026-06-14-dashboard-redesign-design.md)
**Visual reference (on disk, gitignored):** `.superpowers/brainstorm/79813-1781484326/content/{ladder-treatments,fleet-overview}.html`
**Branch:** `dashboard-redesign` (already created).

---

## File Structure

- `ft_userdata/ft_dashboard/app.py` — add `compute_booked_pct()`, `killers_tp_ladder()`, `KILLERS_RECEIVER_DB`; enrich `open_trades_out` in `_poll_bot()`.
- `ft_userdata/ft_dashboard/tests/test_treatment_b.py` — **Create.** Unit tests for the two helpers.
- `ft_userdata/ft_dashboard/static/styles.css` — token block + component restyle + `.splitbar`/`.pill`.
- `ft_userdata/ft_dashboard/static/dashboard.js` — update `COLORS`/`ECHART_COMMON` (theme); add fields in `openTradesAll`.
- `ft_userdata/ft_dashboard/templates/index.html` — replace the three open-trade render blocks with the split-bar markup; tab-bar markup unchanged (CSS-only fix).
- `ft_userdata/docker-compose.prod.yml` — mount `killers_receiver_state` read-only into `ft-dashboard` + `KILLERS_RECEIVER_DB` env.

Confirmed facts: killers bot key is `killers-ft`. Receiver schema: `target_orders(idx, price, state, ft_order_id, …)` joined to `positions(pos_id, ft_trade_id, state)`. Live receiver DB is the named volume `killers_receiver_state` at `/var/lib/killers/receiver.sqlite`. Dashboard internal port 8000.

---

## Phase 0 — Pre-build probe

### Task 0: Verify `amount_requested` semantics live

**Files:** none (verification only).

- [ ] **Step 1: Probe the live fleet `/status` for the fields Treatment B depends on**

Run (Mac, via VPS):
```bash
ssh ubuntu@100.96.225.124 'U=$(docker exec ft-killers-scalp printenv FREQTRADE__API_SERVER__USERNAME); P=$(docker exec ft-killers-scalp printenv FREQTRADE__API_SERVER__PASSWORD); docker exec ft-killers-scalp curl -s -u "$U:$P" http://127.0.0.1:8080/api/v1/status | python3 -c "import sys,json;[print(t[\"trade_id\"],t[\"pair\"],t.get(\"amount\"),t.get(\"amount_requested\")) for t in json.load(sys.stdin)]"'
```
Expected: every open trade prints a numeric `trade_id`, `amount`, and `amount_requested`; for partially-exited trades `amount < amount_requested` (TAO ≈ 0.143 / 0.488). If `amount_requested` is absent or equals `amount` for a known-partial trade, STOP and revisit the spec's denominator assumption before continuing.

---

## Phase 1 — Backend: Treatment B data (TDD)

### Task 1: `compute_booked_pct()` helper + wire into `_poll_bot`

**Files:**
- Modify: `ft_userdata/ft_dashboard/app.py` (add helper near other pure helpers; edit `open_trades_out` at lines 590-605)
- Test: `ft_userdata/ft_dashboard/tests/test_treatment_b.py` (Create)

- [ ] **Step 1: Write the failing test**

Create `ft_userdata/ft_dashboard/tests/test_treatment_b.py`:
```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import compute_booked_pct


def test_partial_exit_booked_pct():
    assert compute_booked_pct(0.143, 0.488) == 70.7  # TAO live: ~71%

def test_single_exit_is_zero():
    assert compute_booked_pct(1.0, 1.0) == 0.0

def test_missing_denominator_is_none():
    assert compute_booked_pct(1.0, None) is None
    assert compute_booked_pct(1.0, 0) is None

def test_pending_entry_amount_zero_is_none():
    assert compute_booked_pct(0, 1.0) is None

def test_string_numerics_coerced():
    assert compute_booked_pct("0.143", "0.488") == 70.7

def test_fee_dust_floored_to_zero():
    assert compute_booked_pct(0.999, 1.0) == 0.0  # 0.1% shrink < dust threshold

def test_amount_exceeds_requested_clamps_zero():
    assert compute_booked_pct(1.2, 1.0) == 0.0

def test_garbage_is_none():
    assert compute_booked_pct("x", "y") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ft_userdata/ft_dashboard && python -m pytest tests/test_treatment_b.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_booked_pct'`.

- [ ] **Step 3: Implement the helper**

In `app.py`, near the top-level constants (after line 144 `STALE_THRESHOLD_S = 60`), add:
```python
# Treatment B: a TP fill below this fraction of the position is treated as
# fee-dust shrinkage, not a real partial exit.
FEE_DUST_PCT = 0.5


def compute_booked_pct(amount, amount_requested):
    """Fraction of an open position already closed, as a percent (0..100).

    Derived from Freqtrade /status: original filled size (`amount_requested`)
    vs. what remains (`amount`). Correct ONLY for trades without position
    adjustment (the Killers copy-trader blocks adjustment; other fleet bots
    are single-exit). Returns None when the denominator is unknown or the
    entry hasn't filled — the frontend renders a plain "open" bar then.
    """
    try:
        ar = float(amount_requested) if amount_requested is not None else 0.0
        a = float(amount) if amount is not None else 0.0
    except (TypeError, ValueError):
        return None
    if ar <= 0 or a <= 0:
        return None
    pct = (ar - a) / ar * 100.0
    if pct < 0:
        pct = 0.0
    elif pct > 100:
        pct = 100.0
    if pct < FEE_DUST_PCT:
        pct = 0.0
    return round(pct, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ft_userdata/ft_dashboard && python -m pytest tests/test_treatment_b.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Wire `trade_id`, `amount_requested`, `booked_pct`, `riding_pct` into `open_trades_out`**

In `app.py`, replace the `open_trades_out = [ ... ]` comprehension (lines 590-605) with:
```python
    open_trades_out = []
    for t in open_trades:
        bp = compute_booked_pct(t.get("amount"), t.get("amount_requested"))
        open_trades_out.append({
            "trade_id": t.get("trade_id"),
            "pair": t.get("pair"),
            "open_rate": t.get("open_rate"),
            "current_rate": t.get("current_rate"),
            "profit_pct": t.get("profit_pct"),
            "profit_abs": t.get("profit_abs"),
            "stake_amount": t.get("stake_amount"),
            "open_date": t.get("open_date"),
            "open_timestamp": t.get("open_timestamp"),
            "stop_loss_abs": t.get("stop_loss_abs"),
            "stop_loss_pct": t.get("stop_loss_pct"),
            "amount": t.get("amount"),
            "amount_requested": t.get("amount_requested"),
            "booked_pct": bp,
            "riding_pct": (None if bp is None else round(100.0 - bp, 1)),
        })
```

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/ft_dashboard/app.py ft_userdata/ft_dashboard/tests/test_treatment_b.py
git commit -m "feat(dashboard): booked_pct per open trade from Freqtrade amount_requested"
```

### Task 2: `killers_tp_ladder()` helper + enrich killers open trades

**Files:**
- Modify: `ft_userdata/ft_dashboard/app.py` (add helper + `KILLERS_RECEIVER_DB` const + enrich in `_poll_bot`)
- Test: `ft_userdata/ft_dashboard/tests/test_treatment_b.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_treatment_b.py`:
```python
import sqlite3
from app import killers_tp_ladder


def _make_receiver_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE positions (pos_id INTEGER PRIMARY KEY, ft_trade_id INTEGER, state TEXT);
        CREATE TABLE target_orders (target_id INTEGER PRIMARY KEY, pos_id INTEGER,
            idx INTEGER, price REAL, state TEXT);
    """)
    # pos 10 -> ft_trade_id 11 (TAO): 5 filled, idx5 active @295, idx6 pending
    conn.execute("INSERT INTO positions VALUES (10, 11, 'open')")
    rungs = [(0,210,'filled'),(1,220,'filled'),(2,235,'filled'),(3,250,'filled'),
             (4,270,'filled'),(5,295,'active'),(6,320,'pending')]
    for i,(idx,price,st) in enumerate(rungs):
        conn.execute("INSERT INTO target_orders VALUES (?,?,?,?,?)", (i, 10, idx, price, st))
    # a closed position must be ignored
    conn.execute("INSERT INTO positions VALUES (99, 5, 'closed')")
    conn.execute("INSERT INTO target_orders VALUES (100, 99, 0, 1.0, 'pending')")
    conn.commit(); conn.close()


def test_tp_ladder_counts_and_next(tmp_path):
    db = tmp_path / "receiver.sqlite"; _make_receiver_db(str(db))
    out = killers_tp_ladder(str(db))
    assert out[11] == {"tps_total": 7, "tps_hit": 5, "next_tp": 295.0}

def test_tp_ladder_ignores_closed_positions(tmp_path):
    db = tmp_path / "receiver.sqlite"; _make_receiver_db(str(db))
    assert 5 not in killers_tp_ladder(str(db))

def test_tp_ladder_missing_db_returns_empty(tmp_path):
    assert killers_tp_ladder(str(tmp_path / "nope.sqlite")) == {}

def test_tp_ladder_next_falls_back_to_pending(tmp_path):
    db = tmp_path / "r2.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript("CREATE TABLE positions (pos_id INTEGER, ft_trade_id INTEGER, state TEXT);"
                       "CREATE TABLE target_orders (target_id INTEGER PRIMARY KEY, pos_id INTEGER, idx INTEGER, price REAL, state TEXT);")
    conn.execute("INSERT INTO positions VALUES (1, 7, 'open')")
    conn.execute("INSERT INTO target_orders VALUES (1,1,0,5.0,'pending')")
    conn.execute("INSERT INTO target_orders VALUES (2,1,1,6.0,'pending')")
    conn.commit(); conn.close()
    assert killers_tp_ladder(str(db))[7] == {"tps_total": 2, "tps_hit": 0, "next_tp": 5.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ft_userdata/ft_dashboard && python -m pytest tests/test_treatment_b.py -k tp_ladder -v`
Expected: FAIL — `ImportError: cannot import name 'killers_tp_ladder'`.

- [ ] **Step 3: Implement helper + const**

In `app.py`, after line 135 (`KILLERS_DB = Path(...)`), add:
```python
# Live killers-receiver SQLite (target_orders / positions) — separate DB from
# the observer state.sqlite above. Empty => TP-ladder pill disabled (bar-only).
KILLERS_RECEIVER_DB = os.environ.get("KILLERS_RECEIVER_DB", "")
```
Then add the helper near `compute_booked_pct`:
```python
def killers_tp_ladder(db_path):
    """Map {ft_trade_id: {tps_total, tps_hit, next_tp}} for OPEN killers
    positions, read from the live receiver.sqlite. Read-only, busy-timeout'd,
    and fully guarded: any failure (missing/locked DB, query error) returns {}
    so the caller degrades to a bar-only render and never fails the snapshot.
    """
    if not db_path or not Path(db_path).exists():
        return {}
    try:
        conn = _sqlite.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = _sqlite.Row
        conn.execute("PRAGMA busy_timeout=2000")
        rows = conn.execute(
            "SELECT p.ft_trade_id AS ftid, t.idx AS idx, t.price AS price, t.state AS state "
            "FROM target_orders t JOIN positions p ON p.pos_id = t.pos_id "
            "WHERE p.state = 'open' AND p.ft_trade_id IS NOT NULL "
            "ORDER BY p.ft_trade_id, t.idx ASC"
        ).fetchall()
    except _sqlite.Error:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    by_trade: dict[int, list] = {}
    for r in rows:
        by_trade.setdefault(int(r["ftid"]), []).append(r)
    out: dict[int, dict] = {}
    for ftid, rungs in by_trade.items():
        active = [x for x in rungs if x["state"] == "active"]
        pending = [x for x in rungs if x["state"] == "pending"]
        nxt = (active[0]["price"] if active else
               pending[0]["price"] if pending else None)
        out[ftid] = {
            "tps_total": len(rungs),
            "tps_hit": sum(1 for x in rungs if x["state"] == "filled"),
            "next_tp": nxt,
        }
    return out
```
(`_sqlite` is the module's existing alias — confirm the import line near the top reads `import sqlite3 as _sqlite`; it is used by `/api/killers/state`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ft_userdata/ft_dashboard && python -m pytest tests/test_treatment_b.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Enrich killers open trades in `_poll_bot`**

In `app.py`, replace the entire `open_trades_out` construction from Task 1 (the `for t in open_trades:` loop) with the version below — it adds a `tp_ladder` lookup before the loop and attaches the TP fields inside it:
```python
    tp_ladder = {}
    if bot.get("key") == "killers-ft" and KILLERS_RECEIVER_DB:
        try:
            tp_ladder = killers_tp_ladder(KILLERS_RECEIVER_DB)
        except Exception:
            tp_ladder = {}

    open_trades_out = []
    for t in open_trades:
        bp = compute_booked_pct(t.get("amount"), t.get("amount_requested"))
        row = {
            "trade_id": t.get("trade_id"),
            "pair": t.get("pair"),
            "open_rate": t.get("open_rate"),
            "current_rate": t.get("current_rate"),
            "profit_pct": t.get("profit_pct"),
            "profit_abs": t.get("profit_abs"),
            "stake_amount": t.get("stake_amount"),
            "open_date": t.get("open_date"),
            "open_timestamp": t.get("open_timestamp"),
            "stop_loss_abs": t.get("stop_loss_abs"),
            "stop_loss_pct": t.get("stop_loss_pct"),
            "amount": t.get("amount"),
            "amount_requested": t.get("amount_requested"),
            "booked_pct": bp,
            "riding_pct": (None if bp is None else round(100.0 - bp, 1)),
        }
        tp = tp_ladder.get(t.get("trade_id"))
        if tp:
            row["tps_total"] = tp["tps_total"]
            row["tps_hit"] = tp["tps_hit"]
            row["next_tp"] = tp["next_tp"]
        open_trades_out.append(row)
```

- [ ] **Step 6: Run tests again**

Run: `cd ft_userdata/ft_dashboard && python -m pytest tests/test_treatment_b.py -v`
Expected: PASS (12).

- [ ] **Step 7: Commit**

```bash
git add ft_userdata/ft_dashboard/app.py ft_userdata/ft_dashboard/tests/test_treatment_b.py
git commit -m "feat(dashboard): killers TP-ladder enrichment from receiver.sqlite (guarded)"
```

### Task 3: Mount the live receiver DB into ft-dashboard

**Files:**
- Modify: `ft_userdata/docker-compose.prod.yml` (ft-dashboard service, lines 306-316)

- [ ] **Step 1: Add env + read-only volume**

In `docker-compose.prod.yml`, in the `ft-dashboard` service `environment:` block (after line 311 `KILLERS_DB: /var/lib/killers/state.sqlite`) add:
```yaml
      KILLERS_RECEIVER_DB: /var/lib/killers-receiver/receiver.sqlite
```
And in its `volumes:` block (after line 316) add a SEPARATE mount path (do not reuse the state.sqlite path):
```yaml
      # live killers-receiver SQLite (target_orders) — read-only, for the
      # TP-ladder pill. Distinct path from the observer state.sqlite above.
      - killers_receiver_state:/var/lib/killers-receiver:ro
```
(The named volume `killers_receiver_state` already exists at the bottom `volumes:` block, line 347.)

- [ ] **Step 2: Validate compose syntax**

Run: `cd ft_userdata && docker compose -f docker-compose.prod.yml config >/dev/null && echo OK`
Expected: `OK` (no YAML/compose errors). If Docker is not on the Mac, run this check on the VPS.

- [ ] **Step 3: Commit**

```bash
git add ft_userdata/docker-compose.prod.yml
git commit -m "chore(dashboard): mount live receiver.sqlite (ro) for TP-ladder pill"
```

---

## Phase 2 — CSS design system

> Canonical values are in this plan; the on-disk mockups are a visual cross-check. Verify each step by loading the page (Phase 5) — CSS has no unit test.

### Task 4: Design tokens

**Files:**
- Modify: `ft_userdata/ft_dashboard/static/styles.css` (`:root`, lines 6-41)

- [ ] **Step 1: Replace the `:root` token block**

Replace lines 6-41 with:
```css
:root {
  /* surfaces — warm off-white, layered */
  --bg-0:#efede4; --bg-1:#e7e3d6; --surface:#fffefb; --surface-2:#f7f5ed; --surface-3:#f1eee3;
  --border:#e7e3d6; --border-soft:#dcd7c8; --hairline:#efece1;

  /* ink ramp — off-black, never pure */
  --text:#12171f; --text-2:#56606e; --text-3:#9098a4; --text-faint:#b6bcc5;

  /* semantic */
  --pos:#0a8f5b; --pos-soft:#e2f3ea; --neg:#d2473a; --neg-soft:#fbe8e6;
  --warn:#b07a16; --warn-soft:#f7eed8; --info:#0e87a3; --info-soft:#dff0f4;

  /* brand accent — deep teal */
  --accent:#0e87a3; --accent-soft:#dff0f4; --accent-ink:#0a6276; --accent-2:#7c3aed;

  /* elevation (3 tiers) */
  --el1:0 1px 2px rgba(18,23,31,.05);
  --el2:0 2px 5px rgba(18,23,31,.05), 0 10px 26px rgba(18,23,31,.055);
  --el3:0 3px 8px rgba(18,23,31,.07), 0 18px 44px rgba(18,23,31,.08);

  /* radius */
  --r:14px; --r-sm:9px;

  /* type */
  --font-sans:"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono:"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}

/* tabular figures for any numeric value */
.num, .vital-val, .metric-val, td.right, .trade-pnl { font-variant-numeric: tabular-nums; letter-spacing:-.01em; }
```

- [ ] **Step 2: Verify load**

Run: `cd ft_userdata/ft_dashboard && python -c "import pathlib; assert '--el2' in pathlib.Path('static/styles.css').read_text()"`
Expected: no error. (Visual check happens in Phase 5.)

- [ ] **Step 3: Commit**

```bash
git add ft_userdata/ft_dashboard/static/styles.css
git commit -m "style(dashboard): new design tokens (palette, elevation, type, tabular nums)"
```

### Task 5: Chrome — tabs (nowrap fix), header, vitals, command bar

**Files:**
- Modify: `ft_userdata/ft_dashboard/static/styles.css`

- [ ] **Step 1: Fix the wrapping tab labels (the reported bug)**

Find the `.tab` and `.tabs` rules in `styles.css`. Set the tab container to not wrap and the labels to stay on one line:
```css
.tabs { display:flex; gap:5px; flex-wrap:nowrap; overflow-x:auto; max-width:100%; scrollbar-width:thin;
        background:var(--surface-3); border:1px solid var(--border); border-radius:12px; padding:4px; }
.tab  { display:inline-flex; align-items:center; gap:7px; white-space:nowrap; flex:none;
        border:none; background:transparent; border-radius:var(--r-sm); padding:8px 14px;
        font-size:13px; font-weight:600; color:var(--text-2); cursor:pointer; transition:.15s; }
.tab:hover { color:var(--text); }
.tab.on { background:var(--surface); color:var(--text); box-shadow:var(--el1); }
```

- [ ] **Step 2: Header + status pill + brand logo + vitals + command bar**

Update/add these rules (match existing selectors; port the look from the mockup):
```css
.brand-logo { width:34px; height:34px; border-radius:10px; display:grid; place-items:center;
              background:linear-gradient(145deg,#1c2531,#0c1118); color:#fff; font-weight:750; box-shadow:var(--el2); }
.status-pill { display:inline-flex; align-items:center; gap:7px; border-radius:20px; padding:5px 11px;
               font-size:12px; font-weight:650; background:var(--pos-soft); color:var(--pos); }
.status-pill .dot { width:8px; height:8px; border-radius:50%; background:currentColor;
                    animation:beat 2.2s infinite; }
@keyframes beat { 0%{box-shadow:0 0 0 0 rgba(10,143,91,.5)} 70%{box-shadow:0 0 0 7px rgba(10,143,91,0)} 100%{box-shadow:0 0 0 0 rgba(10,143,91,0)} }

.vitals-strip { display:grid; grid-template-columns:repeat(7,1fr); gap:1px; background:var(--border);
                border:1px solid var(--border); border-radius:var(--r); overflow:hidden; box-shadow:var(--el2); }
.vital-cell { background:var(--surface); border:none; border-top:2px solid transparent; padding:14px 16px;
              text-align:left; cursor:pointer; transition:.15s; }
.vital-cell:hover { background:var(--surface-2); }
.vital-cell.accent { border-top-color:var(--accent); }
.vital-label { display:block; font-size:10.5px; font-weight:650; letter-spacing:.08em; text-transform:uppercase;
               color:var(--text-3); margin-bottom:7px; }
.vital-val { display:block; font-size:21px; font-weight:700; letter-spacing:-.025em; }

.cmd-bar { background:var(--surface); border:1px solid var(--border); border-radius:var(--r); box-shadow:var(--el2); }
.cmd-bar.has-incidents { box-shadow:var(--el3); border-color:var(--warn-soft); }
.cmd-bar-title { font-size:11px; font-weight:700; letter-spacing:.13em; text-transform:uppercase; color:var(--warn); }
.cmd-icon { width:30px; height:30px; border-radius:var(--r-sm); display:grid; place-items:center;
            background:var(--warn-soft); color:var(--warn); }
.cmd-btn { border:1px solid var(--border); background:var(--surface-2); border-radius:8px; padding:6px 11px;
           font-size:12px; font-weight:600; color:var(--text-2); cursor:pointer; }
```

- [ ] **Step 3: Visual check + commit**

Visual verification is in Phase 5. Commit:
```bash
git add ft_userdata/ft_dashboard/static/styles.css
git commit -m "style(dashboard): chrome — nowrap tabs, header, vitals, command bar"
```

### Task 6: Cards, tables, empty states

**Files:**
- Modify: `ft_userdata/ft_dashboard/static/styles.css`

- [ ] **Step 1: Card elevation + ledger readability + empty states**

Update the relevant selectors:
```css
.card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r);
        box-shadow:var(--el2); overflow:hidden; }
.card-title { font-size:13px; font-weight:680; letter-spacing:-.01em; }
.card-sub { font-size:11.5px; color:var(--text-3); margin-top:3px; }

.ledger { width:100%; border-collapse:collapse; }
.ledger th { font-size:11px; font-weight:650; letter-spacing:.04em; text-transform:uppercase;
             color:var(--text-3); padding:9px 10px; border-bottom:1px solid var(--border); }
.ledger td { font-size:12px; padding:9px 10px; border-bottom:1px solid var(--hairline); }
.ledger tbody tr:nth-child(even) { background:rgba(14,135,163,.02); }
.ledger tbody tr:hover { background:rgba(14,135,163,.06); }
.ledger td.label { font-family:var(--font-mono); font-size:11.5px; color:var(--text-2); }

.empty { display:flex; flex-direction:column; align-items:center; gap:10px; padding:34px 16px;
         color:var(--text-3); font-size:14px; }
.empty .icon { font-size:28px; opacity:.6; }
```
Reserve `--font-mono` for `.ledger td.label` (prices), entry/exit rates, timestamps, and order ids only — not headline metrics.

- [ ] **Step 2: Commit**

```bash
git add ft_userdata/ft_dashboard/static/styles.css
git commit -m "style(dashboard): cards, ledger readability, empty states"
```

---

## Phase 3 — ECharts theme

### Task 7: Re-theme all charts via `COLORS` + `ECHART_COMMON`

**Files:**
- Modify: `ft_userdata/ft_dashboard/static/dashboard.js` (lines 12-32)

- [ ] **Step 1: Update the palette + common options**

Replace lines 12-32 with:
```javascript
// Palette mirrors styles.css tokens so charts match the page.
const COLORS = {
  surface:  '#fffefb',
  surface2: '#f7f5ed',
  text:     '#12171f',
  text2:    '#56606e',
  text3:    '#9098a4',
  border:   '#e7e3d6',
  hairline: '#efece1',
  accent:   '#0e87a3',
  pos:      '#0a8f5b',
  neg:      '#d2473a',
  warn:     '#b07a16',
  info:     '#0e87a3',
};

const ECHART_COMMON = {
  textStyle: { fontFamily: '"Inter", system-ui, sans-serif', fontSize: 11, color: COLORS.text3 },
  backgroundColor: 'transparent',
  grid: { left: 50, right: 18, top: 28, bottom: 30, containLabel: false },
  axisPointer: { lineStyle: { color: COLORS.border, width: 1 } },
};
```

- [ ] **Step 2: Tokenize any hardcoded chart colors**

Run: `cd ft_userdata/ft_dashboard && grep -nE "#[0-9a-fA-F]{6}" static/dashboard.js | grep -viE "COLORS|const COLORS"`
For each chart `setOption` hit, replace literal hex with the matching `COLORS.*` (e.g. dashed backtest line → `COLORS.text3`, splitGrid lines → `COLORS.hairline`). Do NOT alter `.chart`/`.trade-chart` height rules or `_ensureChart()` resize logic (zero-height init risk — see spec Risks).

- [ ] **Step 3: Commit**

```bash
git add ft_userdata/ft_dashboard/static/dashboard.js
git commit -m "style(dashboard): ECharts theme aligned to design tokens"
```

---

## Phase 4 — Treatment B frontend

### Task 8: Split-bar + pill CSS

**Files:**
- Modify: `ft_userdata/ft_dashboard/static/styles.css`

- [ ] **Step 1: Add the component styles**

Append to `styles.css`:
```css
/* Treatment B — booked vs riding */
.ot2-row { padding:12px 4px 13px; border-top:1px solid var(--hairline); }
.ot2-row:first-child { border-top:none; }
.ot2-head { display:flex; align-items:baseline; justify-content:space-between; margin-bottom:9px; }
.ot2-pair { font-size:13.5px; font-weight:650; }
.ot2-pnl { font-size:15px; font-weight:700; }
.splitbar { height:22px; border-radius:7px; background:var(--surface-2); border:1px solid var(--border);
            display:flex; overflow:hidden; }
.booked-seg { background:linear-gradient(180deg,#15a16a,#0a8f5b); color:#fff; font-size:10px; font-weight:700;
              display:flex; align-items:center; padding:0 8px; white-space:nowrap; overflow:hidden; }
.ride-seg { flex:1; background:repeating-linear-gradient(90deg,var(--accent-soft),var(--accent-soft) 9px,#eaf4f7 9px,#eaf4f7 11px);
            color:var(--accent-ink); font-size:10px; font-weight:700; display:flex; align-items:center; padding:0 8px; white-space:nowrap; }
.ride-seg.loss { background:repeating-linear-gradient(90deg,var(--neg-soft),var(--neg-soft) 9px,#f7dad6 9px,#f7dad6 11px); color:var(--neg); }
.ot2-foot { display:flex; align-items:center; justify-content:space-between; margin-top:8px; }
.ot2-age { font-size:11px; color:var(--text-3); }
.pill { display:inline-block; font-size:9.5px; font-weight:700; padding:2px 8px; border-radius:20px;
        background:var(--pos-soft); color:var(--pos); }
.pill.zero { background:var(--neg-soft); color:var(--neg); }
```

- [ ] **Step 2: Commit**

```bash
git add ft_userdata/ft_dashboard/static/styles.css
git commit -m "style(dashboard): split-bar + TP pill components"
```

### Task 9: Render the split bar at the two detail sites

**Files:**
- Modify: `ft_userdata/ft_dashboard/templates/index.html` (per-bot detail block 850-861; dry-run detail block 617-628)

- [ ] **Step 1: Replace the per-bot detail open-trade block**

In `index.html`, replace the `<template x-for="ot in openTradesForBot(bot)" ...>` block at lines 850-861 with:
```html
                <template x-for="ot in openTradesForBot(bot)" :key="ot.pair">
                  <div class="ot2-row">
                    <div class="ot2-head">
                      <span class="ot2-pair" x-text="ot.pair">—</span>
                      <span class="ot2-pnl num" :class="(ot.profit_pct||0)>=0?'pos':'neg'" x-text="fmtPctSigned(ot.profit_pct)">—</span>
                    </div>
                    <div class="splitbar">
                      <template x-if="(ot.booked_pct ?? null) !== null && ot.booked_pct > 0">
                        <span class="booked-seg" :style="'width:'+ot.booked_pct+'%'" x-text="'booked '+Math.round(ot.booked_pct)+'%'"></span>
                      </template>
                      <span class="ride-seg" :class="(ot.profit_pct||0)<0?'loss':''"
                            x-text="(ot.booked_pct ?? null)===null ? '100% open' : 'riding '+Math.round(ot.riding_pct)+'%'"></span>
                    </div>
                    <div class="ot2-foot">
                      <template x-if="ot.tps_total">
                        <span class="pill" :class="ot.tps_hit ? '' : 'zero'"
                              x-text="ot.tps_hit+' / '+ot.tps_total+' TPs'+(ot.next_tp ? ' · next @ '+fmtRate(ot.next_tp) : '')"></span>
                      </template>
                      <span class="ot2-age" x-text="fmtMin(ot.ageMin)"></span>
                    </div>
                  </div>
                </template>
```

- [ ] **Step 2: Replace the dry-run detail open-trade block**

In `index.html`, replace the identical `<template x-for="ot in openTradesForBot(bot)" ...>` block at lines 617-628 with the SAME markup as Step 1.

- [ ] **Step 3: Verify Alpine renders (no console errors)**

Run the dashboard locally if possible (see Phase 5 Task 11), open a bot detail tab, confirm: split bars render, killers shows the TP pill, no Alpine errors in console. `openTradesForBot()` already spreads `t` so `ot.booked_pct`/`ot.tps_total` are present — no JS change needed here.

- [ ] **Step 4: Commit**

```bash
git add ft_userdata/ft_dashboard/templates/index.html
git commit -m "feat(dashboard): Treatment B split bar + TP pill on bot detail tabs"
```

### Task 9b: Trades-tab open-trade cards

**Files:**
- Modify: `ft_userdata/ft_dashboard/static/dashboard.js` (`openTradesAll` push, lines 607-617)
- Modify: `ft_userdata/ft_dashboard/templates/index.html` (trade card, after line 729)

- [ ] **Step 1: Carry the new fields through `openTradesAll`**

In `dashboard.js`, in the `out.push({ ... })` object inside `openTradesAll` (lines 607-617), add these keys before the closing `});`:
```javascript
            booked_pct: t.booked_pct ?? null,
            riding_pct: t.riding_pct ?? null,
            tps_total: t.tps_total ?? null,
            tps_hit: t.tps_hit ?? null,
            next_tp: t.next_tp ?? null,
```

- [ ] **Step 2: Add a compact split bar to the open trade card**

In `index.html`, immediately AFTER the `.trade-card-head` div closes (after line 729, before `<div class="trade-card-detail">`), insert:
```html
          <template x-if="trade.is_open && (trade.booked_pct ?? null) !== null">
            <div class="splitbar" style="margin:0 12px 6px;">
              <template x-if="trade.booked_pct > 0">
                <span class="booked-seg" :style="'width:'+trade.booked_pct+'%'" x-text="'booked '+Math.round(trade.booked_pct)+'%'"></span>
              </template>
              <span class="ride-seg" :class="(trade.profit_pct||0)<0?'loss':''" x-text="'riding '+Math.round(trade.riding_pct)+'%'"></span>
            </div>
          </template>
          <template x-if="trade.is_open && (trade.tps_total)">
            <div style="margin:0 12px 8px;">
              <span class="pill" :class="trade.tps_hit ? '' : 'zero'"
                    x-text="trade.tps_hit+' / '+trade.tps_total+' TPs'+(trade.next_tp ? ' · next @ '+fmtRate(trade.next_tp) : '')"></span>
            </div>
          </template>
```

- [ ] **Step 3: Commit**

```bash
git add ft_userdata/ft_dashboard/static/dashboard.js ft_userdata/ft_dashboard/templates/index.html
git commit -m "feat(dashboard): Treatment B split bar on Trades-tab open cards"
```

---

## Phase 5 — Verification & deploy

### Task 10: Backend test sweep + local smoke

**Files:** none (verification).

- [ ] **Step 1: Full backend test run**

Run: `cd ft_userdata/ft_dashboard && python -m pytest tests/ -v`
Expected: all PASS (12).

- [ ] **Step 2: Import smoke (no syntax/wiring errors)**

Run: `cd ft_userdata/ft_dashboard && python -c "import app; print('imports ok')"`
Expected: `imports ok`.

### Task 11: Live no-regression pass + deploy

**Files:** none (verification + deploy).

- [ ] **Step 1: Deploy ft-dashboard ONLY (do not touch bots)**

The dashboard is independent of the bots; FF is live. On the VPS, in the Dokploy compose dir:
```bash
ssh ubuntu@100.96.225.124 'cd /etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code/ft_userdata && docker compose -f docker-compose.prod.yml up -d --no-deps --build ft-dashboard'
```
Expected: only `ft-dashboard` recreated; `docker ps` shows FF/Keltner/Cascade/killers containers with unchanged uptime.

- [ ] **Step 2: Tab-by-tab regression check**

Open https://master-trader.grooveops.dev and verify on EACH of Live, Dry-run, Trades, and every per-bot detail tab:
- charts render with non-zero height (equity, drawdown, per-pair, candles, trade cards)
- counts/badges, command/incident bar, and filter pills still work (Alpine bindings intact)
- tab labels do NOT wrap; the bar scrolls if narrow
- browser console: no errors

- [ ] **Step 3: Treatment B correctness check**

On the KillersScalp detail tab: split bars render; TAO shows `booked ~71%` + `5 / 7 TPs · next @ 295`; a single-exit bot (Keltner) shows `100% open`. Cross-check TAO against the receiver DB:
```bash
ssh ubuntu@100.96.225.124 "docker exec killers-receiver python3 -c \"import sqlite3;c=sqlite3.connect('/var/lib/killers/receiver.sqlite');print([r for r in c.execute(\\\"select state,count(*) from target_orders t join positions p on p.pos_id=t.pos_id where p.ft_trade_id=11 group by state\\\")])\""
```
Expected: 5 filled, 1 active, 1 pending → pill reads 5/7. If the pill is missing fleet-wide, confirm `KILLERS_RECEIVER_DB` is set and the volume mounted (`docker exec ft-dashboard ls -la /var/lib/killers-receiver/`).

- [ ] **Step 4: Final commit / branch is ready for PR**

```bash
git status   # clean
git log --oneline main..HEAD   # review the redesign commits
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** design tokens (T4), all-tab restyle (T5/T6), ECharts theme (T7), Treatment B bar from Freqtrade (T1), TP pill from receiver.sqlite w/ guards (T2), compose mount (T3), all three render sites (T9/T9b), tests + no-regression + `--no-deps` deploy (T10/T11). ✓
- **Placeholder scan:** the only intentional marker is the `row_tp` insertion-point note in T2 Step 5, explicitly deleted in the same step. ✓
- **Type consistency:** backend emits `trade_id, amount_requested, booked_pct, riding_pct, tps_total, tps_hit, next_tp`; frontend reads the same snake_case keys via `openTradesForBot()` spread and the `openTradesAll` push. Helper names `compute_booked_pct`/`killers_tp_ladder` match across tasks and tests. ✓
