"""Build a self-contained HTML dashboard from dashboard_data.json (no external deps)."""
import json
from datetime import datetime, timezone

d = json.load(open("dashboard_data.json"))
sol = d["sol"]; path = sol["path"]; res = sol["res"]; mt = d["may_trades"]; tot = d["may_totals"]

def fdt(ms): return datetime.fromtimestamp(ms/1000, timezone.utc)
def ms(s): return int(datetime.fromisoformat(s).timestamp()*1000)

# ---- SVG price chart for the SOL trade ----
W, H, PL, PR, PT, PB = 980, 340, 48, 16, 18, 28
t0, t1 = path[0][0], path[-1][0]
ymin, ymax = 83.4, 90.2
def X(t): return PL + (t - t0)/(t1 - t0)*(W-PL-PR)
def Y(p): return PT + (ymax - p)/(ymax - ymin)*(H-PT-PB)
poly = " ".join(f"{X(c[0]):.1f},{Y(c[1]):.1f}" for c in path)
def near(tms):
    best = min(path, key=lambda c: abs(c[0]-tms)); return best
svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet" font-family="ui-monospace,monospace">']
# grid + y labels
for p in (84,85,86,87,88,89,90):
    y=Y(p); svg.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" stroke="#222637" stroke-width="1"/>')
    svg.append(f'<text x="{PL-6}" y="{y+3:.1f}" fill="#5a6488" font-size="10" text-anchor="end">{p}</text>')
# x labels
for c in path[::len(path)//6]:
    x=X(c[0]); svg.append(f'<text x="{x:.0f}" y="{H-8}" fill="#5a6488" font-size="9.5" text-anchor="middle">{fdt(c[0]).strftime("%m-%d %H:%M")}</text>')
# entry zone band 88-91 (cap at top)
zy=Y(90.2); zh=Y(88)-zy
svg.append(f'<rect x="{PL}" y="{zy:.1f}" width="{W-PL-PR}" height="{zh:.1f}" fill="#9ece6a" opacity="0.07"/>')
svg.append(f'<text x="{W-PR-4}" y="{Y(88)-4:.1f}" fill="#9ece6a" font-size="10" text-anchor="end" opacity="0.9">posted entry 88–91 · mid 89.5 — NEVER FILLED ↑</text>')
# TP line
svg.append(f'<line x1="{PL}" y1="{Y(84):.1f}" x2="{W-PR}" y2="{Y(84):.1f}" stroke="#73daca" stroke-width="1.3" stroke-dasharray="6 4"/>')
svg.append(f'<text x="{PL+4}" y="{Y(84)-4:.1f}" fill="#73daca" font-size="10">TP 84</text>')
# SL note (off-chart at 93)
svg.append(f'<text x="{PL+4}" y="{PT+11}" fill="#f7768e" font-size="10">SL 93 — off-chart above (never hit; max high {max(c[2] for c in path):.2f})</text>')
# price line
svg.append(f'<polyline points="{poly}" fill="none" stroke="#7aa2f7" stroke-width="1.4"/>')
# entry markers at signal time
sig=ms("2026-04-22T05:28:00+00:00")
for price,col,lab,dy in [(87.88,"#e0af68","market fill 87.88",-8),(88.88,"#bb9af7","edge fill 88.88",-22)]:
    svg.append(f'<circle cx="{X(sig):.1f}" cy="{Y(price):.1f}" r="4.5" fill="{col}" stroke="#0f1117" stroke-width="1.2"/>')
svg.append(f'<text x="{X(sig)+8:.1f}" y="{Y(87.88)+4:.1f}" fill="#e0af68" font-size="10">SIGNAL 05:28 → market 87.88 / edge 88.88</text>')
# management event markers
for ev in sol["events"]:
    c=near(ms(ev["t"])); x=X(c[0]); y=Y(c[1])
    svg.append(f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{H-PB}" stroke="#e0af68" stroke-width="0.8" stroke-dasharray="3 3" opacity="0.5"/>')
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#e0af68" stroke="#0f1117" stroke-width="1.2"/>')
    svg.append(f'<text x="{x+6:.1f}" y="{y+14:.1f}" fill="#e0af68" font-size="9.5">{ev["label"]} (msg {ev["msg"]})</text>')
svg.append("</svg>")
svg="".join(svg)

# ---- May trade table rows ----
def rcell(r):
    if r is None: return '<td class="num dim">no fill</td>'
    cls="pos" if r>0 else ("neg" if r<0 else "")
    return f'<td class="num {cls}">{r:+.2f}R</td>'
def ccell(v,suf=""):
    if v is None: return '<td class="num dim">—</td>'
    cls="pos" if v>0 else "neg"
    return f'<td class="num {cls}">{v:+,}{suf}</td>'
rows=""
for t in mt:
    rows+=(f'<tr><td>{t["sym"]}</td><td class="{"pos" if t["dir"]=="LONG" else "neg"}">{t["dir"]}</td>'
           f'<td class="dim">{t["date"]}</td>{ccell(t["claim_usd"],"")}{ccell(t["claim_pct"],"%")}'
           f'{rcell(t["copierR"])}<td class="dim small">{t["exit"]}</td></tr>')
mm=tot["market_manage"]
def pct(R): return f"{R*5:+.1f}%"

html=f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dennis copier validation</title>
<style>
:root{{--bg:#0f1117;--card:#16181f;--card2:#1a1b26;--bd:#262a3d;--tx:#c0caf5;--dim:#6b7394;--blue:#7aa2f7;--grn:#9ece6a;--red:#f7768e;--amb:#e0af68;--pur:#bb9af7}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:24px;margin:0 0 4px;font-weight:700}}h2{{font-size:15px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);margin:34px 0 12px;font-weight:600}}
.sub{{color:var(--dim);font-size:13.5px;margin:0 0 8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:20px 0}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px 18px}}
.card .k{{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}}
.card .v{{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}}
.card .n{{font-size:12px;color:var(--dim);margin-top:6px}}
.pos{{color:var(--grn)}}.neg{{color:var(--red)}}.amb{{color:var(--amb)}}.blue{{color:var(--blue)}}.dim{{color:var(--dim)}}
.panel{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:18px 20px;margin:14px 0}}
svg{{background:#0d0f15;border-radius:8px;display:block;margin:6px 0}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid #1e2233}}
th{{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
td.num{{text-align:right;font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums}}
td.small{{font-size:11px}}
tr.tot td{{border-top:2px solid var(--bd);font-weight:700;background:#13151d}}
.mini{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}}
.mini .b{{background:var(--card2);border:1px solid var(--bd);border-radius:9px;padding:11px 13px}}
.mini .b .k{{font-size:11px;color:var(--dim)}}.mini .b .v{{font-size:19px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}}
.tag{{display:inline-block;background:#1e2233;border:1px solid var(--bd);border-radius:6px;padding:2px 8px;font-size:11px;color:var(--dim);margin-right:6px}}
.foot{{color:var(--dim);font-size:12px;margin-top:10px}}.foot b{{color:var(--tx)}}
.verdict{{background:linear-gradient(180deg,#1a1320,#16181f);border:1px solid #3a2a3a;border-left:4px solid var(--red);border-radius:12px;padding:16px 20px;margin:8px 0 4px}}
</style></head><body><div class="wrap">

<h1>Dennis / Insiders Scalp — copier validation</h1>
<p class="sub">What a signal-following copier would actually capture, vs Dennis's claims. Offline event-driven backtest on WEEX/Binance 1m data · validated by multi-agent adversarial loop + codex gate + independent re-run · <b>nothing tuned to his scoreboard</b>.</p>

<div class="verdict"><b style="color:#fff">Verdict.</b> Copying these signals does not reproduce the headline. The <b>April</b> "main" ledger nets ≈ <b class="dim">flat</b> for a copier; the <b>May "+2,702% / +$64,394"</b> scalp ledger — replicated here with the <b>real paid-channel entries</b> — nets <b class="neg">−6.2R ≈ −31%</b> for a market-entry copier. Not fabrication of direction; the gap is leverage, perfect-fill assumptions, and exits/averaging a copier can't get.</div>

<div class="cards">
<div class="card"><div class="k">May ledger · copier (our bot)</div><div class="v neg">−6.20R</div><div class="n">market entry + his posted management · ≈ −31% @5% risk · WR 10/32</div></div>
<div class="card"><div class="k">Dennis claimed (May)</div><div class="v amb">+2,702%</div><div class="n">= sum of leveraged per-trade %; honest footnote +120–130% account</div></div>
<div class="card"><div class="k">April ledger · copier</div><div class="v dim">≈ flat</div><div class="n">+4.2% only via one entry-less line; ex-that −0.4%</div></div>
<div class="card"><div class="k">Validation</div><div class="v blue">3×</div><div class="n">adversarial loop → codex gate → re-run · 3 bugs caught</div></div>
</div>

<h2>Eduardo's screenshot trade — SOL Short, Apr 22 (validated)</h2>
<div class="panel">
<p class="sub" style="margin-top:0">Open <span class="tag">msg 4092</span> SOL Short · entry 88–91 · SL 93 · TP 84 &nbsp;→&nbsp; manage <span class="tag">4098</span> close 30% + SL→breakeven <span class="tag">4099</span> close rest. The other screenshot rows: TRADOOR (4094) is a <i>close</i> with no posted entry → unplaceable; 4093/95/96/97 are promo/educational → correctly parsed as non-signals.</p>
{svg}
<div class="mini">
<div class="b"><div class="k">posted-limit entry</div><div class="v dim">no fill</div></div>
<div class="b"><div class="k">market entry → manage</div><div class="v pos">+0.28R</div></div>
<div class="b"><div class="k">edge entry → manage</div><div class="v pos">+0.74R</div></div>
<div class="b"><div class="k">Dennis claimed</div><div class="v amb">+409%</div></div>
</div>
<p class="foot">SOL gapped to ~88 and fell — the posted 89.5 mid <b>never traded</b> (a patient limit copier is left behind). A market copier enters at 87.88 and, following Dennis's posted closes, banks <b class="pos">+0.28R</b> (≈+1.4% @5%). His <b class="amb">+409%</b> implies ~80× leverage on the ~5% move + a fill/hold a copier doesn't get. Real, but not copyable.</p>
</div>

<h2>Every validated May signal — copier (market entry + posted management)</h2>
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th>Symbol</th><th>Dir</th><th>Date</th><th class="num">Dennis $</th><th class="num">Dennis %</th><th class="num">Copier R</th><th>Exit</th></tr></thead><tbody>
{rows}
<tr class="tot"><td>TOTAL</td><td colspan=2 class="dim">{mm[2]} trades · WR {mm[1]}/{mm[2]}</td><td class="num amb">+$57,494</td><td class="num amb">+~2,450%</td><td class="num neg">{mm[0]:+.2f}R</td><td class="dim">≈ {pct(mm[0])} @5%</td></tr>
</tbody></table>
<p class="foot"><b>R</b> = multiples of the per-trade risk unit. Account-% is a <b>linear</b> 5%-risk-per-trade translation (R×5%), <b>not</b> compounded; with frequently-concurrent positions any single %-figure is approximate. Dennis's "%" column sums to ~+2,450% (his "+2,702%") — a sum of leveraged per-trade %s, not an account return.</p>
</div>

<h2>Robustness — the negative verdict survives every stress test</h2>
<div class="panel">
<table><thead><tr><th>market entry + posted management</th><th class="num">total R</th><th class="num">≈ acct @5%</th><th class="num">WR</th></tr></thead><tbody>
<tr><td>all 32 trades</td><td class="num neg">{tot['market_manage'][0]:+.2f}R</td><td class="num neg">{pct(tot['market_manage'][0])}</td><td class="num dim">{tot['market_manage'][1]}/{tot['market_manage'][2]}</td></tr>
<tr><td>delete the load-bearing trade (BTC-1609) — cherry-pick test</td><td class="num neg">{tot['del1609'][0]:+.2f}R</td><td class="num neg">{pct(tot['del1609'][0])}</td><td class="num dim">{tot['del1609'][1]}/{tot['del1609'][2]}</td></tr>
<tr><td>only fully price-resolved trades (≤ May 24)</td><td class="num neg">{tot['thru24'][0]:+.2f}R</td><td class="num neg">{pct(tot['thru24'][0])}</td><td class="num dim">{tot['thru24'][1]}/{tot['thru24'][2]}</td></tr>
<tr><td>strip the HYPE artifact</td><td class="num neg">{tot['exHYPE'][0]:+.2f}R</td><td class="num neg">{pct(tot['exHYPE'][0])}</td><td class="num dim">{tot['exHYPE'][1]}/{tot['exHYPE'][2]}</td></tr>
<tr><td class="dim">for contrast: mechanical ladder (blind TP-follow, ignores his closes)</td><td class="num pos">{tot['market_ladder'][0]:+.2f}R</td><td class="num pos">{pct(tot['market_ladder'][0])}</td><td class="num dim">{tot['market_ladder'][1]}/{tot['market_ladder'][2]}</td></tr>
<tr><td class="dim">for contrast: patient limit fills + manage (only {tot['posted_manage'][2]}/32 ever fill)</td><td class="num pos">{tot['posted_manage'][0]:+.2f}R</td><td class="num pos">{pct(tot['posted_manage'][0])}</td><td class="num dim">{tot['posted_manage'][1]}/{tot['posted_manage'][2]}</td></tr>
</tbody></table>
<p class="foot">The bot-relevant <b>market+manage</b> verdict stays negative no matter what. The only positive rows need perfect limit fills (which only fill {tot['posted_manage'][2]}/32) or blindly riding TPs past the breakeven closes Dennis actually posted. Token/scale gate passed all symbols (WEEX↔Binance &lt;0.1%); gross of fees/funding (which would worsen the negative).</p>
</div>

<p class="foot" style="margin-top:24px">Generated from <code>dashboard_data.json</code> · harness <code>research/insiders_april_replication/harness.py</code> · full writeups: <code>RESULTS.md</code> (April), <code>RESULTS_MAY.md</code> (May).</p>
</div></body></html>"""
open("dashboard.html","w").write(html)
print("wrote dashboard.html", len(html), "bytes")
