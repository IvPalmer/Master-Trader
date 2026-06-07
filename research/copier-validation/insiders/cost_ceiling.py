"""Ceiling test — the cheapest go/no-go before building the agentic copier.

Question it answers: under the MOST GENEROUS plausible *conservative* execution
of Dennis's May signals, does the strategy clear realistic costs — or does even
an oracle lose? If the oracle loses, no LLM agent approximating his judgment can
win, and the agent build should not be funded.

It extends the validated `harness.py` with the one thing RESULTS_MAY.md caveat #7
says is missing — "Fees / funding / slippage not modeled" — and adds two
conservative-manager rules the plan demands:

  1. BINANCE prices only (the bot executes on Binance, not WEEX). harness.py
     defaults to WEEX-primary; we force binance-first here.
  2. A real per-trade cost model (taker/maker fees + slippage + funding).
  3. A per-trade UPSIDE CAP (Rcap): no single trade may contribute more than
     +Rcap. This is the principled enforcement of the plan's hard-fail rule
     "profit comes from one uncapped winner" — it neutralizes the two
     documented artifacts (HYPE's +32R unmanaged tail, BTC-1609's +6R
     edge-late-fill tail) WITHOUT hand-deleting any trade. Losses stay at the
     posted SL (~ -1R); only the upside is capped, exactly as a manager with a
     max-take / trailing rule would behave.

Cost model (Binance USDT-M futures, conservative-realistic):
  - taker fee 0.05% / maker fee 0.02% per side (VIP0).
  - slippage 0.05% per MARKET fill (entry if market; every exit is market).
  - total exit turnover = 1.0 notional regardless of how many partials the
    `manage` model books (partials split one notional), so exit cost is charged
    once on 1.0 notional — number of partials does NOT inflate fees, only the
    one extra slippage already folded in.
  - funding: flat per-trade estimate (holds are short; funding is second-order
    and sign-dependent). Reported as a separate sensitivity, not the base.

  cost is computed in R: a cost of c (fraction of notional) = c / sl_dist_pct R,
  because notional per 1.0 unit = entry price and 1R = |entry - sl|. Tight stops
  (small sl_dist) amplify cost in R — that is real, not a modelling artifact.

Configs reported:
  - market+manage  = WHAT OUR BOT ACTUALLY DOES (market entry, follow posted mgmt)
  - market+ladder  = mechanical follower (ignores chat)
  - posted+manage  = patient limit copier
  - edge+manage    = the OPTIMISTIC CEILING (best-touched limit fill + his mgmt)

Kill-gate (printed at the end):
  KILL if the oracle-conservative ceiling (edge+manage, capped, net of costs) is
  not MEANINGFULLY positive, OR if it survives only by one un-stripped winner
  (concentration test = strip the single biggest net trade and re-check sign).
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import harness  # the validated engine

HERE = Path(__file__).parent

# ── force Binance-first (the bot executes on Binance, not WEEX) ──────────────
_orig_candles = harness.candles
def _binance_first(sym: str, prefer: str = "binance"):
    cs = harness.load(sym, "binance")
    if cs:
        return cs, "binance"
    return _orig_candles(sym, "weex")
harness.candles = _binance_first

# ── cost model knobs ─────────────────────────────────────────────────────────
TAKER = 0.0005      # 0.05% per side
MAKER = 0.0002      # 0.02% per side
SLIP  = 0.0005      # 0.05% per market fill
FUND  = 0.0000      # base = no funding; flip on for sensitivity

RISK_PCT = 5.0      # same linear translation the doc uses (R x 5%)


def entry_cost_frac(entry_model: str) -> float:
    """Cost fraction on the ENTRY side."""
    if entry_model == "market":
        return TAKER + SLIP          # market entry: taker + slippage
    return MAKER                      # posted/edge = resting limit = maker, no slip


def exit_cost_frac() -> float:
    """Cost fraction on the EXIT side. Every exit (full or partial) is a market
    order in the live bot. Summed over partials the notional turnover is 1.0, so
    charge taker+slip once on 1.0 notional."""
    return TAKER + SLIP


def trade_cost_R(entry_model: str, entry_price: float, sl: float,
                 funding: float = 0.0) -> float:
    """Round-trip cost expressed in R for one trade."""
    sl_dist = abs(entry_price - sl) / entry_price
    if sl_dist <= 0:
        return 0.0
    roundtrip = entry_cost_frac(entry_model) + exit_cost_frac() + funding
    return roundtrip / sl_dist


def run_config(trades, entry_model, exit_model, *, rcap=None, funding=0.0,
               drop_symbol=None):
    """Return dict with gross R, net R, cost R, per-trade rows."""
    rows = []
    gross = net = cost_tot = 0.0
    capped_hits = 0
    for t in trades:
        if drop_symbol and t["symbol"].upper() == drop_symbol.upper():
            continue
        r = harness.simulate(t, entry_model, exit_model)
        if r.realized_R is None:
            rows.append((t["symbol"], t["direction"], None, None, None, r.exit_kind))
            continue
        raw_R = r.realized_R
        # conservative upside cap (no uncapped winner); losses untouched
        capped_R = raw_R
        if rcap is not None and raw_R > rcap:
            capped_R = rcap
            capped_hits += 1
        c = trade_cost_R(entry_model, r.entry_price, t["sl"], funding=funding)
        n = capped_R - c
        gross += capped_R
        cost_tot += c
        net += n
        rows.append((t["symbol"], t["direction"], round(raw_R, 2),
                     round(capped_R, 2), round(n, 2), r.exit_kind))
    sized = [x for x in rows if x[4] is not None]
    wins = [x for x in sized if x[4] > 0]
    return {
        "entry": entry_model, "exit": exit_model, "rcap": rcap,
        "funding": funding, "drop": drop_symbol,
        "gross_R": round(gross, 2), "cost_R": round(cost_tot, 2),
        "net_R": round(net, 2), "n_sized": len(sized), "n_win": len(wins),
        "rows": rows, "capped_hits": capped_hits,
    }


def top_net_symbol(rows):
    """Symbol of the single biggest NET-positive trade (concentration test)."""
    best = None
    for sym, _d, _raw, _cap, net, _k in rows:
        if net is None:
            continue
        if best is None or net > best[1]:
            best = (sym, net)
    return best


def fmt(cfg, label=""):
    acct = cfg["net_R"] * RISK_PCT
    gross_acct = cfg["gross_R"] * RISK_PCT
    cap = f"cap+{cfg['rcap']}R" if cfg["rcap"] is not None else "uncapped"
    drop = f" ex-{cfg['drop']}" if cfg["drop"] else ""
    return (f"{label:36} {cfg['entry']:6}+{cfg['exit']:6} {cap:9}{drop:10} "
            f"gross={cfg['gross_R']:+6.2f}R  cost={cfg['cost_R']:5.2f}R  "
            f"NET={cfg['net_R']:+6.2f}R ({acct:+5.1f}% @5%)  "
            f"WR={cfg['n_win']}/{cfg['n_sized']}")


if __name__ == "__main__":
    tf = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "trades_may.json")
    if not os.environ.get("PRICES_DIR"):
        os.environ["PRICES_DIR"] = str(HERE / "prices_may")
        # re-point harness PRICES (it read the env at import)
        harness.PRICES = Path(os.environ["PRICES_DIR"])
        harness._cache.clear()
    trades = json.load(open(tf))
    print(f"\nCEILING TEST — {len(trades)} May signals, BINANCE prices, net of costs")
    print(f"cost model: taker {TAKER*100:.3f}% maker {MAKER*100:.3f}% slip {SLIP*100:.3f}%/market-fill\n")

    # ── 1. parity check: gross on Binance vs the WEEX-based published table ──
    print("="*78)
    print("1) GROSS on Binance (should match RESULTS_MAY.md WEEX table within parity)")
    print("="*78)
    for em, xm, want in [("market","manage","-6.20"),("market","ladder","+2.56"),
                          ("posted","manage","+18.28"),("edge","manage","+44.67")]:
        c = run_config(trades, em, xm)
        print(f"   {em:6}+{xm:6}  gross={c['gross_R']:+7.2f}R  (WEEX published: {want}R)")

    # ── 2. net of costs, uncapped ──
    print("\n" + "="*78)
    print("2) NET OF COSTS (uncapped — artifacts HYPE/1609 still in)")
    print("="*78)
    for em, xm in [("market","manage"),("market","ladder"),("posted","manage"),("edge","manage")]:
        print("   " + fmt(run_config(trades, em, xm)))

    # ── 3. THE CEILING: oracle-conservative = edge+manage, capped, net ──
    print("\n" + "="*78)
    print("3) ORACLE-CONSERVATIVE CEILING (edge entry + his mgmt + upside cap + costs)")
    print("    edge = best-touched limit fill (generous); cap = no uncapped winner")
    print("="*78)
    for rcap in (None, 5, 4, 3):
        print("   " + fmt(run_config(trades, "edge", "manage", rcap=rcap), "ceiling(edge)"))
    print("   --- realistic copier (market entry instead of optimistic edge): ---")
    for rcap in (None, 5, 4, 3):
        print("   " + fmt(run_config(trades, "market", "manage", rcap=rcap), "realistic(market)"))

    # ── 4. concentration test on the capped ceiling ──
    print("\n" + "="*78)
    print("4) CONCENTRATION TEST (cap +4R) — strip the single biggest NET trade")
    print("="*78)
    base = run_config(trades, "edge", "manage", rcap=4)
    top = top_net_symbol(base["rows"])
    print("   " + fmt(base, "ceiling cap+4R (all)"))
    if top:
        stripped = run_config(trades, "edge", "manage", rcap=4, drop_symbol=top[0])
        print(f"   biggest net trade = {top[0]} ({top[1]:+.2f}R net)")
        print("   " + fmt(stripped, f"ceiling cap+4R ex-{top[0]}"))

    # ── 5. funding sensitivity ──
    print("\n" + "="*78)
    print("5) FUNDING + HIGHER-SLIP SENSITIVITY on the ceiling (edge+manage cap+4R)")
    print("="*78)
    print("   " + fmt(run_config(trades, "edge", "manage", rcap=4, funding=0.0003),
                      "ceiling +funding 0.03%"))
    SLIP_HI = 0.0010
    globals()['SLIP'] = SLIP_HI
    print("   " + fmt(run_config(trades, "edge", "manage", rcap=4),
                      f"ceiling slip {SLIP_HI*100:.2f}%"))
    globals()['SLIP'] = 0.0005

    # ── 6. KILL-GATE ──
    # The ceiling must be the best ACHIEVABLE conservative execution, not the
    # fantasy `edge` fill (best-touched price in range — the doc itself labels
    # it "not copyable"). A real copier either takes the market (always fills,
    # no waiting) or rests a limit (fills 18/32, MISSES the runaways = adverse
    # selection). So the achievable ceiling = max(market, posted) + his
    # management + cap + costs. We also strip the TWO documented artifacts
    # (HYPE's 100%-unmanaged tail, BTC-1609's edge-late-fill that resurrects
    # the +6R the P0 correction killed) because a conservative capped manager
    # would never have held either.
    print("\n" + "="*78)
    print("6) KILL-GATE  (ceiling = best ACHIEVABLE conservative exec, not fantasy edge)")
    print("="*78)
    ex_artifacts = [t for t in trades
                    if t["symbol"] != "HYPE"
                    and not (t["symbol"] == "BTC" and t["direction"] == "SHORT"
                             and t["date"][:10] == "2026-05-21")]

    bot     = run_config(trades, "market", "manage", rcap=4)
    limit   = run_config(trades, "posted", "manage", rcap=4)
    limit_x = run_config(ex_artifacts, "posted", "manage", rcap=4)
    edge_x  = run_config(ex_artifacts, "edge",   "manage", rcap=4)  # diagnostic upper bound

    achievable = max(bot["net_R"], limit["net_R"])
    achievable_x = max(bot["net_R"], limit_x["net_R"])
    print(f"   bot reality   (market+manage, net):            {bot['net_R']:+7.2f}R ({bot['net_R']*RISK_PCT:+6.1f}% @5%)")
    print(f"   limit copier  (posted+manage, net, fills 18):  {limit['net_R']:+7.2f}R ({limit['net_R']*RISK_PCT:+6.1f}% @5%)")
    print(f"   limit, ex documented artifacts:                {limit_x['net_R']:+7.2f}R ({limit_x['net_R']*RISK_PCT:+6.1f}% @5%)")
    print(f"   [diagnostic only] edge fantasy ex-artifacts:   {edge_x['net_R']:+7.2f}R ({edge_x['net_R']*RISK_PCT:+6.1f}% @5%)")
    print(f"   --> best ACHIEVABLE ceiling (ex-artifacts):    {achievable_x:+7.2f}R ({achievable_x*RISK_PCT:+6.1f}% @5%)")
    print(f"   Dennis footnote claim: +120-130% acct;  plan target = capture 30-50% = +6 to +13R")

    kill = achievable_x <= 1.0
    verdict = ("KILL — best achievable conservative execution does NOT clear costs; "
               "the only positive numbers require unachievable 'edge' fills or keeping "
               "documented artifacts. Do not fund the agent build."
               if kill else
               "CLEARS — best achievable ceiling is meaningfully positive net of costs.")
    print(f"\n   >>> VERDICT: {verdict}\n")
