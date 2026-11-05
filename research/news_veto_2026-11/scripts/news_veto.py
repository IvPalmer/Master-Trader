#!/usr/bin/env python3
"""News-veto measurement on existing Master Trader trade lists (EXPLORATORY, not preregistered).

Question: would blocking NEW entries around bad news have improved the existing bots?

Vetoes
  V1_24h : block entries in token X during [t0, t0+24h) after every Binance delisting or
           monitoring-tag notice naming X (all 267 manifest events, candidates or not).
  V1_7d  : same, [t0, t0+7d).
  V2_macro: block ALL entries during [T-2h, T+2h) around each US CPI release (08:30 ET)
           and each FOMC statement (14:00 ET), 2023-01..2026-10, DST-aware.

Per strategy x veto: n, n vetoed, vetoed vs kept mean/sum/win rate, first-order P&L change
= -(sum of vetoed P&L) (ignores freed slots), calendar-month block-bootstrap 95% CI for the
vetoed mean (n_vetoed >= 5), placebo percentile (all windows shifted by one common random
offset of +/-1..30 whole days, 500 draws), yearly split.

Stdlib only. Reads trade lists in place; writes only to ../results/.
"""
import collections
import csv
import datetime as dt
import json
import os
import random
import sys
import zipfile
from zoneinfo import ZoneInfo

R = "/home/ubuntu/master-trader/research"
OUT = os.path.join(R, "news_veto_2026-11", "results")
MANIFEST = os.path.join(R, "news_event_studies/data/manifests/delisting-manifest.json")
H = 3600 * 1000
D = 24 * H
SEED = 20261105
N_PLACEBO = 500
N_BOOT = 5000
ET = ZoneInfo("America/New_York")

# ---- US macro calendar (official sources, fetched 2026-11-05) -------------------------------
# CPI: BLS CPI news-release archive https://www.bls.gov/bls/news-release/cpi.htm (dates from the
# archive file names cpi_MMDDYYYY). October 2025 CPI was not published (2025 appropriations lapse).
# Release time 08:30 ET (BLS standard CPI release time).
CPI = [  # (reference month, release date)
    ("2022-12", "2023-01-12"), ("2023-01", "2023-02-14"), ("2023-02", "2023-03-14"),
    ("2023-03", "2023-04-12"), ("2023-04", "2023-05-10"), ("2023-05", "2023-06-13"),
    ("2023-06", "2023-07-12"), ("2023-07", "2023-08-10"), ("2023-08", "2023-09-13"),
    ("2023-09", "2023-10-12"), ("2023-10", "2023-11-14"), ("2023-11", "2023-12-12"),
    ("2023-12", "2024-01-11"), ("2024-01", "2024-02-13"), ("2024-02", "2024-03-12"),
    ("2024-03", "2024-04-10"), ("2024-04", "2024-05-15"), ("2024-05", "2024-06-12"),
    ("2024-06", "2024-07-11"), ("2024-07", "2024-08-14"), ("2024-08", "2024-09-11"),
    ("2024-09", "2024-10-10"), ("2024-10", "2024-11-13"), ("2024-11", "2024-12-11"),
    ("2024-12", "2025-01-15"), ("2025-01", "2025-02-12"), ("2025-02", "2025-03-12"),
    ("2025-03", "2025-04-10"), ("2025-04", "2025-05-13"), ("2025-05", "2025-06-11"),
    ("2025-06", "2025-07-15"), ("2025-07", "2025-08-12"), ("2025-08", "2025-09-11"),
    ("2025-09", "2025-10-24"), ("2025-11", "2025-12-18"), ("2025-12", "2026-01-13"),
    ("2026-01", "2026-02-13"), ("2026-02", "2026-03-11"), ("2026-03", "2026-04-10"),
    ("2026-04", "2026-05-12"), ("2026-05", "2026-06-10"), ("2026-06", "2026-07-14"),
    ("2026-07", "2026-08-12"), ("2026-08", "2026-09-11"), ("2026-09", "2026-10-14"),
]
# FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm. Statement released
# 14:00 ET on the final day of each scheduled meeting. The 2025-08-22 notation vote is not a
# 14:00 policy statement and is excluded. No unscheduled meetings in 2023-01..2026-10.
FOMC = [  # (meeting days as printed, statement date)
    ("Jan/Feb 31-1 2023", "2023-02-01"), ("Mar 21-22 2023", "2023-03-22"),
    ("May 2-3 2023", "2023-05-03"), ("Jun 13-14 2023", "2023-06-14"),
    ("Jul 25-26 2023", "2023-07-26"), ("Sep 19-20 2023", "2023-09-20"),
    ("Oct/Nov 31-1 2023", "2023-11-01"), ("Dec 12-13 2023", "2023-12-13"),
    ("Jan 30-31 2024", "2024-01-31"), ("Mar 19-20 2024", "2024-03-20"),
    ("Apr/May 30-1 2024", "2024-05-01"), ("Jun 11-12 2024", "2024-06-12"),
    ("Jul 30-31 2024", "2024-07-31"), ("Sep 17-18 2024", "2024-09-18"),
    ("Nov 6-7 2024", "2024-11-07"), ("Dec 17-18 2024", "2024-12-18"),
    ("Jan 28-29 2025", "2025-01-29"), ("Mar 18-19 2025", "2025-03-19"),
    ("May 6-7 2025", "2025-05-07"), ("Jun 17-18 2025", "2025-06-18"),
    ("Jul 29-30 2025", "2025-07-30"), ("Sep 16-17 2025", "2025-09-17"),
    ("Oct 28-29 2025", "2025-10-29"), ("Dec 9-10 2025", "2025-12-10"),
    ("Jan 27-28 2026", "2026-01-28"), ("Mar 17-18 2026", "2026-03-18"),
    ("Apr 28-29 2026", "2026-04-29"), ("Jun 16-17 2026", "2026-06-17"),
    ("Jul 28-29 2026", "2026-07-29"), ("Sep 15-16 2026", "2026-09-16"),
    ("Oct 27-28 2026", "2026-10-28"),
]


def et_ms(date_str, hh, mm):
    y, m, d = map(int, date_str.split("-"))
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def macro_calendar():
    rows = []
    for ref, d in CPI:
        t = et_ms(d, 8, 30)
        rows.append(("CPI", ref, d, "08:30", t))
    for mtg, d in FOMC:
        t = et_ms(d, 14, 0)
        rows.append(("FOMC", mtg, d, "14:00", t))
    rows.sort(key=lambda r: r[4])
    return rows


# ---- token normalisation --------------------------------------------------------------------
def norm(sym):
    base = sym.split("/")[0].split(":")[0]
    if len(base) > 1 and base[0] == "k" and base[1:].isupper():  # Hyperliquid kPEPE -> PEPE
        base = base[1:]
    base = base.upper()
    for p in ("1000000", "1000", "1M"):
        if base.startswith(p) and len(base) > len(p) and not base[len(p):].isdigit():
            base = base[len(p):]
            break
    return base


# ---- trade loaders: each returns list of dict(token, pair, entry_ms, ratio, abs) -------------
def load_ft_zip(path, strat):
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist() if n.endswith(".json") and "_config" not in n
                and "market_change" not in n][0]
        data = json.loads(z.read(name))
    s = data["strategy"][strat]
    out = []
    for t in s["trades"]:
        out.append(dict(token=norm(t["pair"]), pair=t["pair"], entry_ms=int(t["open_timestamp"]),
                        ratio=float(t["profit_ratio"]), abs=float(t["profit_abs"]),
                        is_short=bool(t.get("is_short"))))
    meta = dict(start=s.get("backtest_start"), end=s.get("backtest_end"),
                max_open_trades=s.get("max_open_trades"), stake=s.get("stake_amount"),
                pairs=len({t["pair"] for t in s["trades"]}))
    return out, meta


def load_killers_channel(path):
    """Channel-reported outcome, same rule as killers_bot/simulator.py: channel_final_pct on a
    logged close_full, else the largest-magnitude reported partial (max_pct), else 0.
    Units: margin units (1.0 = +100% of one position's margin at the channel's leverage)."""
    sigs = json.load(open(path))
    out = []
    for s in sigs:
        pct = s["channel_final_pct"] if s["channel_final_pct"] is not None else (s["max_pct"] or 0.0)
        ms = int(dt.datetime.fromisoformat(s["open_date"]).timestamp() * 1000)
        out.append(dict(token=norm(s["symbol"]), pair=s["symbol"], entry_ms=ms, ratio=pct / 100.0,
                        abs=pct / 100.0, is_short=s["direction"] == "short", id=s["signal_id"]))
    od = sorted(o["entry_ms"] for o in out)
    meta = dict(start=iso(od[0]), end=iso(od[-1]), pairs=len({o["token"] for o in out}),
                outcome="channel-reported, not real-price")
    return out, meta


def load_killers_dry(path):
    d = json.load(open(path))
    out = []
    for t in d["trades"]:
        out.append(dict(token=norm(t["pair"]), pair=t["pair"], entry_ms=int(t["open_timestamp"]),
                        ratio=float(t["profit_ratio"]), abs=float(t["profit_abs"]),
                        is_short=bool(t.get("is_short"))))
    od = sorted(o["entry_ms"] for o in out)
    meta = dict(start=iso(od[0]), end=iso(od[-1]), pairs=len({o["token"] for o in out}))
    return out, meta


STRATS = [
    ("FF_V2_current", "ff_roi_2026-09-30/user_data/backtest_results/backtest-result-2026-09-30_23-45-13.zip",
     "FFX_V0_current", "zip", "USDT"),
    ("FF_PreV2_sens", "ff_entry_ablation_2026-10-01/user_data/backtest_results/backtest-result-2026-10-01_03-28-54.zip",
     "FFA_PreV2", "zip", "USDT"),
    ("Keltner_R4_live18", "oos_retest_2026-07/results/R4.zip", "KeltnerBounceV1", "zip", "USDT"),
    ("Keltner_R5_wl60", "oos_retest_2026-07/results/R5.zip", "KeltnerBounceV1", "zip", "USDT"),
    ("OITrend_CausalOI", "oi_trend_causal_2026-10-02/user_data/backtest_results/backtest-result-2026-10-03_00-25-01.zip",
     "OITrendPullbackV1CausalOI", "zip", "USDT"),
    ("OITrend_PriceOnly", "oi_trend_causal_2026-10-02/user_data/backtest_results/backtest-result-2026-10-03_00-25-01.zip",
     "OITrendPullbackV1PriceOnly", "zip", "USDT"),
    ("Killers_channel", "copier-validation/killers/killers_signals.json", None, "kchan", "margin units"),
    ("Killers_dry", "tg_bots_audit_2026-07/killers_trades_full.json", None, "kdry", "USDT"),
]


# ---- windows --------------------------------------------------------------------------------
def build_windows():
    m = json.load(open(MANIFEST))
    ev = m["events"]
    v1_24, v1_7 = collections.defaultdict(list), collections.defaultdict(list)
    for e in ev:
        tok = norm(e["token"])
        info = (e["announcement_id"], e["kind"])
        v1_24[tok].append((e["t0_ms"], e["t0_ms"] + D, info))
        v1_7[tok].append((e["t0_ms"], e["t0_ms"] + 7 * D, info))
    cal = macro_calendar()
    v2 = [(t - 2 * H, t + 2 * H, (kind + ":" + d, kind)) for kind, _, d, _, t in cal]
    return ev, {"V1_24h": ("token", v1_24), "V1_7d": ("token", v1_7), "V2_macro": ("global", v2)}, cal


def hit(trade, veto, shift=0):
    mode, w = veto
    wins = w.get(trade["token"], ()) if mode == "token" else w
    t = trade["entry_ms"] - shift  # shifting windows by +s == shifting entry by -s
    for a, b, info in wins:
        if a <= t < b:
            return info
    return None


# ---- stats ----------------------------------------------------------------------------------
def month(ms):
    return iso(ms)[:7]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def block_boot_mean(trades, rng):
    by_m = collections.defaultdict(list)
    for t in trades:
        by_m[month(t["entry_ms"])].append(t["ratio"])
    keys = list(by_m)
    res = []
    for _ in range(N_BOOT):
        xs = []
        for _ in keys:
            xs.extend(by_m[rng.choice(keys)])
        res.append(mean(xs))
    return pct(res, 0.025), pct(res, 0.975), len(keys)


def block_boot_diff(all_trades, flags, rng):
    by_m = collections.defaultdict(lambda: ([], []))
    for t, f in zip(all_trades, flags):
        by_m[month(t["entry_ms"])][0 if f else 1].append(t["ratio"])
    keys = list(by_m)
    res, skipped = [], 0
    for _ in range(N_BOOT):
        v, k = [], []
        for _ in keys:
            a, b = by_m[rng.choice(keys)]
            v.extend(a)
            k.extend(b)
        if not v or not k:
            skipped += 1
            continue
        res.append(mean(v) - mean(k))
    return pct(res, 0.025), pct(res, 0.975), skipped


def summarize(trades, flags):
    v = [t for t, f in zip(trades, flags) if f]
    k = [t for t, f in zip(trades, flags) if not f]
    def s(g):
        return dict(n=len(g), mean_ratio=mean([t["ratio"] for t in g]),
                    sum_abs=sum(t["abs"] for t in g),
                    win=(sum(1 for t in g if t["ratio"] > 0) / len(g)) if g else None)
    return s(v), s(k)


def main():
    rng = random.Random(SEED)
    events, vetoes, cal = build_windows()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "macro_calendar.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event", "reference", "date_et", "time_et", "utc", "utc_offset_h"])
        for kind, ref, d, tm, t in cal:
            off = (dt.datetime.fromtimestamp(t / 1000, ET).utcoffset().total_seconds()) / 3600
            w.writerow([kind, ref, d, tm, iso(t), int(off)])
    # placebo offsets: one common offset per draw, +/-1..30 whole days (keeps hour-of-day)
    offsets = [rng.choice([-1, 1]) * rng.randint(1, 30) * D for _ in range(N_PLACEBO)]

    results, vetoed_rows, inputs = [], [], []
    for name, rel, strat, kind, unit in STRATS:
        path = os.path.join(R, rel)
        if kind == "zip":
            trades, meta = load_ft_zip(path, strat)
        elif kind == "kchan":
            trades, meta = load_killers_channel(path)
        else:
            trades, meta = load_killers_dry(path)
        inputs.append(dict(name=name, file=rel, strategy=strat, unit=unit, n=len(trades), **meta))
        tokens = {t["token"] for t in trades}
        for vname, veto in vetoes.items():
            infos = [hit(t, veto) for t in trades]
            flags = [i is not None for i in infos]
            sv, sk = summarize(trades, flags)
            delta = -sv["sum_abs"]
            pl = []
            for off in offsets:
                pl.append(-sum(t["abs"] for t in trades if hit(t, veto, off) is not None))
            below = sum(1 for x in pl if x < delta)
            ties = sum(1 for x in pl if x == delta)
            ptile = 100.0 * (below + 0.5 * ties) / len(pl)
            ci = diff_ci = None
            if sv["n"] >= 5:
                lo, hi, nm = block_boot_mean([t for t, f in zip(trades, flags) if f], rng)
                ci = dict(lo=lo, hi=hi, months=nm)
                dlo, dhi, skipped = block_boot_diff(trades, flags, rng)
                diff_ci = dict(lo=dlo, hi=dhi, skipped=skipped)
            years = {}
            for y in sorted({iso(t["entry_ms"])[:4] for t in trades}):
                idx = [i for i, t in enumerate(trades) if iso(t["entry_ms"])[:4] == y]
                yv, yk = summarize([trades[i] for i in idx], [flags[i] for i in idx])
                years[y] = dict(n=len(idx), n_vetoed=yv["n"], vetoed_mean_ratio=yv["mean_ratio"],
                                kept_mean_ratio=yk["mean_ratio"], delta_abs=-yv["sum_abs"])
            n_tok_windows = (len({tok for tok in veto[1] if tok in tokens}) if veto[0] == "token" else None)
            results.append(dict(strategy=name, veto=vname, unit=unit, n=len(trades),
                                vetoed=sv, kept=sk, delta_abs=delta, vetoed_mean_ci=ci,
                                diff_mean_ci=diff_ci, placebo_pctile=ptile,
                                placebo_mean_delta=mean(pl), placebo_p05=pct(pl, 0.05),
                                placebo_p95=pct(pl, 0.95),
                                placebo_share_nonzero=sum(1 for x in pl if x != 0) / len(pl),
                                traded_tokens_with_v1_events=n_tok_windows, years=years))
            for t, i in zip(trades, infos):
                if i is not None:
                    vetoed_rows.append(dict(strategy=name, veto=vname, pair=t["pair"],
                                            entry_utc=iso(t["entry_ms"]), ratio=t["ratio"], abs=t["abs"],
                                            short=t["is_short"], trigger=i[0], trigger_kind=i[1]))
    json.dump(dict(inputs=inputs, results=results, n_manifest_events=len(events),
                   manifest_kinds=dict(collections.Counter(e["kind"] for e in events)),
                   n_macro=len(cal), seed=SEED, n_placebo=N_PLACEBO, n_boot=N_BOOT),
              open(os.path.join(OUT, "veto_results.json"), "w"), indent=1)
    json.dump(vetoed_rows, open(os.path.join(OUT, "vetoed_trades.json"), "w"), indent=1)

    # markdown tables
    L = []
    L.append("| strategy | veto | n | n vetoed | vetoed mean (95% month-block CI) | kept mean | vetoed win / kept win | P&L change | placebo pct |")
    L.append("|---|---|---:|---:|---|---:|---|---:|---:|")
    def f(x, p=2):
        return "-" if x is None else f"{x*100:+.{p}f}%"
    for r in results:
        v, k = r["vetoed"], r["kept"]
        ci = r["vetoed_mean_ci"]
        cis = f"{f(v['mean_ratio'])} [{f(ci['lo'])}, {f(ci['hi'])}]" if ci else f(v["mean_ratio"])
        wv = "-" if v["win"] is None else f"{v['win']*100:.0f}%"
        wk = "-" if k["win"] is None else f"{k['win']*100:.0f}%"
        L.append(f"| {r['strategy']} | {r['veto']} | {r['n']} | {v['n']} | {cis} | {f(k['mean_ratio'])} | {wv} / {wk} | "
                 f"{r['delta_abs']:+.2f} {r['unit']} | {r['placebo_pctile']:.0f} |")
    L.append("")
    L.append("| strategy | veto | diff vetoed-kept mean CI | placebo mean change | placebo 5-95% | placebo draws vetoing anything |")
    L.append("|---|---|---|---:|---|---:|")
    for r in results:
        d = r["diff_mean_ci"]
        ds = f"[{f(d['lo'])}, {f(d['hi'])}]" if d else "-"
        L.append(f"| {r['strategy']} | {r['veto']} | {ds} | {r['placebo_mean_delta']:+.2f} | "
                 f"{r['placebo_p05']:+.2f} .. {r['placebo_p95']:+.2f} | {r['placebo_share_nonzero']*100:.0f}% |")
    L.append("")
    L.append("Yearly split (n / vetoed / vetoed mean / kept mean / P&L change):")
    L.append("")
    for r in results:
        if r["vetoed"]["n"] == 0:
            continue
        ys = "; ".join(f"{y}: {d['n']}/{d['n_vetoed']}/{f(d['vetoed_mean_ratio'])}/{f(d['kept_mean_ratio'])}/{d['delta_abs']:+.2f}"
                       for y, d in r["years"].items())
        L.append(f"- {r['strategy']} {r['veto']}: {ys}")
    open(os.path.join(OUT, "tables.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print()
    for inp in inputs:
        print(inp)


if __name__ == "__main__":
    sys.exit(main())
