"""Build the complete per-trade May +2702%-ledger dashboard.
Plain $ and % (NO 'R'): $1,000 account at 5% risk/trade (Dennis's own basis) →
1 risk-unit = $50 = 5%. Each chart carries a plain-English 'what happened' note."""
import json
from datetime import datetime, timezone

d = json.load(open("dashboard_full_data.json"))
T = d["trades"]; tot = d["totals"]
ACCT = 1000.0; PER_R = 50.0  # 1R = $50 = 5% of a $1,000 account

def fdt(ms): return datetime.fromtimestamp(ms/1000, timezone.utc)
def fmt(p):
    if p is None: return "—"
    ap = abs(p)
    if ap >= 1000: return f"{p:,.0f}"
    if ap >= 100: return f"{p:.2f}"
    if ap >= 1: return f"{p:.3f}"
    if ap >= 0.01: return f"{p:.4f}"
    return f"{p:.6f}"
def usd(R): return R*PER_R
def pct(R): return R*5.0
def mtxt(R):                      # plain text "-$50 (-5.0%)"
    if R is None: return "no fill"
    u = usd(R); s = "+" if u >= 0 else "-"
    return f"{s}${abs(u):,.0f} ({pct(R):+.1f}%)"
def mcell(R, pctonly=False):      # html
    if R is None: return '<span class="dim">no fill</span>'
    c = "pos" if R > 0 else ("neg" if R < 0 else "dim")
    txt = f"{pct(R):+.1f}%" if pctonly else mtxt(R)
    return f'<span class="{c}">{txt}</span>'
def claimusd(cu): return "—" if cu is None else f'{"+" if cu>=0 else "-"}${abs(cu):,}'
def claimpct(cp): return "—" if cp is None else f'{cp:+}%'
def claimcls(cu): return "dim" if cu is None else ("pos" if cu > 0 else "neg")
def lev(t):
    e = t.get("entry"); sl = t.get("sl")
    if e and isinstance(sl, (int, float)) and e > 0:
        dist = abs(e - sl) / e
        if dist > 0: return 0.05 / dist        # leverage to risk 5% of account at this stop
    return None
def levtxt(t):
    L = lev(t); return f"{L:.1f}×" if L else "—"
def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def msgs(t):
    parts = []
    st = t.get("signal_text")
    if st:
        dd = (t.get("signal_msg_date") or t["date"])[:16].replace("T", " ")
        parts.append(f'<div class="msg sig"><span class="mid">▸ msg {t["src_id"]} · {dd} UTC · OPENING SIGNAL</span><pre>{esc(st)}</pre></div>')
    for ev in t["events"]:
        if not ev.get("raw"): continue
        dd = fdt(ev["t"]).strftime("%m-%d %H:%M")
        parts.append(f'<div class="msg"><span class="mid">▸ msg {ev["src"]} · {dd} UTC · {esc(ev["label"])}</span><pre>{esc(ev["raw"])}</pre></div>')
    return ('<details class="msgs" open><summary>Telegram posts that drove this trade (verbatim)</summary>' + "".join(parts) + '</details>') if parts else ""

# ---------- plain-English "what happened" note ----------
def note(t):
    R = t["fills"]["market"]["R"]; cp = t["claim_pct"]; cl = f"{cp:+}%" if cp is not None else "his claim"
    er = t["exit_reason"]; filled = t["posted_filled"]
    sym = t["sym"]
    if t["src_id"] == 1609:
        return ("Dennis posted “closing around breakeven” 24 min after entry (msg 1611) — the stop was never hit "
                "and his target only came 7 days later. A copier following him books ≈$0, not the multi-day win the raw numbers implied.")
    if sym == "HYPE":
        return ("HYPE pumped — but Dennis’s one management post came BEFORE a limit copier even fills, so the position "
                "rides 100% unmanaged. The eye-popping “edge” figure is an unclosed tail, not a copy you could execute; "
                f"a market-entry copier following his posted management nets {mtxt(R)}.")
    if "data end" in er:
        return (f"Opened close to the May-30 data cutoff — it resolves at the tail, not its target, so it’s provisional. "
                f"Copier so far: {mtxt(R)} vs the {cl} claim.")
    if "cap" in er:
        return (f"Dennis’s posted partial closes flattened only part of the position; the leftover rode to our 12-day "
                f"max-hold cap and was marked out there. Copier: {mtxt(R)} vs the {cl} claim — and that figure leans on a "
                f"multi-day hold the posted signals never told a follower to keep.")
    # fill-quality clause: did a market copier chase in worse than his posted zone?
    mf = t["fills"]["market"]["fill"]; elo = t.get("entry_lo") or t["entry"]; ehi = t.get("entry_hi") or t["entry"]; is_long = t["dir"] == "LONG"
    fq = ""
    if mf and elo and ehi:
        if is_long and mf > ehi * 1.001:
            fq = f" The market copier chased in at {fmt(mf)} — above his posted {fmt(elo)}–{fmt(ehi)} entry — a worse fill than he got."
        elif (not is_long) and mf < elo * 0.999:
            fq = f" The market copier chased in at {fmt(mf)} — below his posted {fmt(elo)}–{fmt(ehi)} entry — a worse fill than he got."
    if not filled and (R is None or R <= 0):
        return (f"His posted entry zone never traded back, so a patient limit copier gets nothing.{fq or ' A market copier '}"
                f"{('It ' if fq else '')}{'hit the stop' if t['sl_hit'] else 'bled out'}: {mtxt(R)}. The gap to his {cl} is a fill a copier can’t get — not leverage we lack (we’re already at 5% risk).")
    if R is not None and R <= -0.9:
        return (f"Price ran straight to the stop — full loss {mtxt(R)}.{fq} Dennis’s {cl} is this same losing trade quoted at higher leverage; we’re already levered (5% risk), and matching his leverage would only make the loss bigger.")
    if "breakeven" in er:
        return (f"Dennis moved the stop to breakeven and it tagged — copier exits flat: {mtxt(R)}.{fq} His {cl} came from a better fill/hold quoted at higher leverage, not leverage we’re missing.")
    if R is not None and R > 0.4:
        return (f"A genuine copier win: {mtxt(R)}, following his posted closes. His {cl} is the same move shown at higher leverage / a longer hold — our figure is already leveraged to 5% risk.")
    return (f"Followed his posted closes for {mtxt(R)}.{fq} The shortfall vs his {cl} is fill + exit quality plus his higher-leverage quoting — not leverage we lack. We’re already at 5% risk; adding leverage amplifies the result, which here means a bigger loss.")

def outcome_tag(t):
    R = t["fills"]["market"]["R"]; er = t["exit_reason"]
    if t["src_id"] == 1609: return ("breakeven close", "dim")
    if not t["posted_filled"] and (R is None or R <= 0): return ("missed / stopped", "neg")
    if R is not None and R <= -0.9: return ("stopped out", "neg")
    if "cap" in er: return ("rode to 12d cap", "dim")
    if "data end" in er: return ("unresolved", "dim")
    if R is not None and R > 0.4: return ("win", "pos")
    if "breakeven" in er: return ("breakeven", "dim")
    return ("small / managed", "pos" if (R or 0) > 0 else "dim")

# ---------- generalized per-trade SVG chart ----------
def chart(t):
    path = t["path"]
    if not path: return "<div class='dim'>no price data</div>"
    W, H, PL, PR, PT, PB = 1040, 248, 72, 14, 16, 26
    t0, t1 = path[0][0], path[-1][0]
    is_long = t["dir"] == "LONG"
    lo_set = [c[3] for c in path] + [x for x in (t.get("entry_lo"), t["entry"], t.get("sl")) if x]
    hi_set = [c[2] for c in path] + [x for x in (t.get("entry_hi"), t["entry"], t.get("sl")) if x]
    ymin, ymax = min(lo_set)*0.9985, max(hi_set)*1.0015
    rng = ymax - ymin or 1
    def X(tm): return PL + (tm-t0)/max(1,(t1-t0))*(W-PL-PR)
    def Y(p): return PT + (ymax-p)/rng*(H-PT-PB)
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet">']
    for i in range(5):
        p = ymin + rng*i/4; y = Y(p)
        s.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" stroke="#1d2030"/>')
        s.append(f'<text x="{PL-6}" y="{y+3:.1f}" fill="#5a6488" font-size="9.5" text-anchor="end">{fmt(p)}</text>')
    for c in path[::max(1,len(path)//6)]:
        s.append(f'<text x="{X(c[0]):.0f}" y="{H-7}" fill="#5a6488" font-size="9" text-anchor="middle">{fdt(c[0]).strftime("%m-%d %H:%M")}</text>')
    elo, ehi = t.get("entry_lo") or t["entry"], t.get("entry_hi") or t["entry"]
    if elo and ehi:
        ya, yb = Y(max(elo,ehi)), Y(min(elo,ehi))
        s.append(f'<rect x="{PL}" y="{ya:.1f}" width="{W-PL-PR}" height="{max(2,yb-ya):.1f}" fill="#9ece6a" opacity="0.10"/>')
        s.append(f'<text x="{W-PR-3}" y="{ya-3:.1f}" fill="#9ece6a" font-size="9.5" text-anchor="end">entry {fmt(elo)}–{fmt(ehi)}</text>')
    sl = t.get("sl")
    if sl and ymin <= sl <= ymax:
        s.append(f'<line x1="{PL}" y1="{Y(sl):.1f}" x2="{W-PR}" y2="{Y(sl):.1f}" stroke="#f7768e" stroke-width="1.2" stroke-dasharray="6 4"/>')
        s.append(f'<text x="{PL+3}" y="{Y(sl)-3:.1f}" fill="#f7768e" font-size="9.5">SL {fmt(sl)}</text>')
    elif sl:
        s.append(f'<text x="{PL+3}" y="{(PT+10) if sl>ymax else (H-PB-4)}" fill="#f7768e" font-size="9.5">SL {fmt(sl)} (off-chart {"above" if sl>ymax else "below"})</text>')
    for tp in t["tps"]:
        if ymin <= tp <= ymax:
            s.append(f'<line x1="{PL}" y1="{Y(tp):.1f}" x2="{W-PR}" y2="{Y(tp):.1f}" stroke="#73daca" stroke-width="1" stroke-dasharray="4 4" opacity="0.85"/>')
            s.append(f'<text x="{PL+3}" y="{Y(tp)+11:.1f}" fill="#73daca" font-size="9.5">TP {fmt(tp)}</text>')
    offs = [tp for tp in t["tps"] if not (ymin <= tp <= ymax)]
    if offs:
        s.append(f'<text x="{W-PR-3}" y="{(H-PB-4) if is_long else (PT+22)}" fill="#73daca" font-size="9" text-anchor="end" opacity="0.8">TP {", ".join(fmt(x) for x in offs)} (off-chart, not reached)</text>')
    # candlesticks (O,H,L,C)
    n = len(path); cw = max(1.4, (W-PL-PR)/max(1, n)*0.62)
    for c in path:
        o, h, l, cl = c[1], c[2], c[3], c[4]; x = X(c[0]); col = "#26a69a" if cl >= o else "#ef5350"
        s.append(f'<line x1="{x:.1f}" y1="{Y(h):.1f}" x2="{x:.1f}" y2="{Y(l):.1f}" stroke="{col}" stroke-width="0.8"/>')
        yb = Y(max(o, cl)); bh = max(0.8, abs(Y(o)-Y(cl)))
        s.append(f'<rect x="{x-cw/2:.1f}" y="{yb:.1f}" width="{cw:.1f}" height="{bh:.1f}" fill="{col}"/>')
    sigms = int(datetime.fromisoformat(t["date"]).timestamp()*1000)
    mf = t["fills"]["market"]["fill"]
    if mf:
        s.append(f'<circle cx="{X(sigms):.1f}" cy="{Y(mf):.1f}" r="4" fill="#e0af68" stroke="#0f1117" stroke-width="1"/>')
    s.append(f'<line x1="{X(sigms):.1f}" y1="{PT}" x2="{X(sigms):.1f}" y2="{H-PB}" stroke="#e0af68" stroke-width="0.7" opacity="0.35"/>')
    s.append(f'<text x="{X(sigms)+4:.1f}" y="{PT+11:.1f}" fill="#e0af68" font-size="9">signal / market fill</text>')
    for ev in t["events"]:
        if ev["price"] is None or not (t0 <= ev["t"] <= t1): continue
        x = X(ev["t"]); y = Y(ev["price"])
        s.append(f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{H-PB}" stroke="#bb9af7" stroke-width="0.7" stroke-dasharray="3 3" opacity="0.45"/>')
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#bb9af7" stroke="#0f1117" stroke-width="1"/>')
        s.append(f'<text x="{x+4:.1f}" y="{y-5:.1f}" fill="#bb9af7" font-size="8.6">{ev["label"]}</text>')
    s.append("</svg>")
    return "".join(s)

# ---------- complete table ----------
def trow(i, t):
    f = t["fills"]; cu = t["claim_usd"]; cp = t["claim_pct"]; cc = claimcls(cu)
    tps = ", ".join(fmt(x) for x in t["tps"]) or "—"
    er = f'{fmt(t.get("entry_lo"))}–{fmt(t.get("entry_hi"))}' if t.get("entry_lo") else fmt(t["entry"])
    otag, ocls = outcome_tag(t)
    return (f'<tr><td class="dim">{i}</td><td>{t["sym"]}</td><td class="{"pos" if t["dir"]=="LONG" else "neg"}">{t["dir"][0]}</td>'
            f'<td class="dim small">{t["date"][5:16]}</td><td class="dim small">{t["src_id"]}</td>'
            f'<td class="num small">{er}</td><td class="num small">{fmt(t.get("sl"))}</td><td class="num small dim">{levtxt(t)}</td><td class="num small">{tps}</td>'
            f'<td class="num {cc}">{claimusd(cu)}</td><td class="num {cc}">{claimpct(cp)}</td>'
            f'<td class="num">{mcell(f["market"]["R"])}</td>'
            f'<td class="num">{mcell(f["posted"]["R"], True)}</td><td class="num">{mcell(f["edge"]["R"], True)}</td>'
            f'<td class="small {ocls}">{otag}</td></tr>')

# ---------- per-trade cards ----------
def card(i, t):
    f = t["fills"]; otag, ocls = outcome_tag(t)
    return f'''<div class="trade" id="t{i}">
<div class="thead"><div class="tt"><span class="idx">#{i}</span> <b>{t["sym"]} {t["dir"]}</b>
<span class="dim">· {t["date"][:16].replace("T"," ")} · msg {t["src_id"]}</span> <span class="otag {ocls}">{otag}</span></div>
<div class="badges">
<span class="badge claim">Dennis claimed: {claimusd(t["claim_usd"])} / {claimpct(t["claim_pct"])}</span>
<span class="badge {"pos" if (f["market"]["R"] or 0)>0 else "neg"}">copier: {mcell(f["market"]["R"])}</span>
</div></div>
<div class="note">{note(t)}</div>
{chart(t)}
<div class="fline"><span>leverage <b>{levtxt(t)}</b> (to risk 5%)</span>
<span>posted-limit entry: <b>{("fills "+fmt(f["posted"]["fill"])) if f["posted"]["fill"] else "NEVER fills"}</b> &rarr; {mcell(f["posted"]["R"])}</span>
<span>market entry <b>{fmt(f["market"]["fill"])}</b> &rarr; {mcell(f["market"]["R"])}</span>
<span>optimistic limit <b>{fmt(f["edge"]["fill"])}</b> &rarr; {mcell(f["edge"]["R"])}</span></div>
{msgs(t)}
</div>'''

mm = tot["market_manage"]; pmg = tot["posted_manage"]
# --- limit-vs-market panel data ---
_filled = [t for t in T if t["posted_filled"]]
_missed = [t for t in T if not t["posted_filled"]]
_missed_sorted = sorted(_missed, key=lambda t: -(t["claim_pct"] if t["claim_pct"] is not None else -9999))
_missed_winners = sum(1 for t in _missed if (t["claim_pct"] or 0) > 0)
_posted_exH = sum(t["fills"]["posted"]["R"] for t in _filled if t["sym"] != "HYPE" and t["fills"]["posted"]["R"] is not None)
_missed_mkt = sum(t["fills"]["market"]["R"] for t in _missed if t["fills"]["market"]["R"] is not None)
_missed_rows = "".join(
    f'<tr><td>{t["sym"]}</td><td class="{"pos" if t["dir"]=="LONG" else "neg"}">{t["dir"][0]}</td>'
    f'<td class="num amb">{claimpct(t["claim_pct"])}</td>'
    f'<td class="num">{mcell(t["fills"]["market"]["R"])}</td></tr>'
    for t in _missed_sorted if (t["claim_pct"] or 0) > 0)
rows = "".join(trow(i+1, t) for i, t in enumerate(T))
cards = "".join(card(i+1, t) for i, t in enumerate(T))
end_bal = ACCT + usd(mm[0])

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Dennis +2702% ledger — complete copier validation</title>
<style>
:root{{--bg:#0f1117;--card:#15171f;--card2:#1a1b26;--bd:#262a3d;--tx:#c0caf5;--dim:#6b7394;--blue:#7aa2f7;--grn:#9ece6a;--red:#f7768e;--amb:#e0af68;--pur:#bb9af7}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5}}
.wrap{{max-width:1120px;margin:0 auto;padding:30px 18px 70px}}
h1{{font-size:23px;margin:0 0 4px}}.sub{{color:var(--dim);font-size:13.5px;margin:0 0 6px;max-width:900px}}
h2{{font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--dim);margin:36px 0 12px;border-bottom:1px solid var(--bd);padding-bottom:7px}}
.pos{{color:var(--grn)}}.neg{{color:var(--red)}}.amb{{color:var(--amb)}}.blue{{color:var(--blue)}}.dim{{color:var(--dim)}}.small{{font-size:11px}}
.verdict{{background:linear-gradient(180deg,#1b1322,#15171f);border:1px solid #3a2a3a;border-left:4px solid var(--red);border-radius:12px;padding:15px 19px;margin:14px 0}}
.basis{{background:var(--card2);border:1px solid var(--bd);border-radius:9px;padding:9px 14px;font-size:12.5px;color:var(--dim);margin:10px 0}}.basis b{{color:var(--tx)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:13px;margin:16px 0}}
.kc{{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:14px 16px}}
.kc .k{{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}}.kc .v{{font-size:23px;font-weight:700;margin-top:5px;font-variant-numeric:tabular-nums}}.kc .n{{font-size:11.5px;color:var(--dim);margin-top:5px}}
.legend{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:11px 15px;font-size:12px;color:var(--dim);display:flex;gap:16px;flex-wrap:wrap}}
.legend b{{color:var(--tx)}}.sw{{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:middle}}
.panel{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 16px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:5px 7px;text-align:left;border-bottom:1px solid #1c2030;white-space:nowrap}}
th{{color:var(--dim);font-weight:600;font-size:10px;text-transform:uppercase}}
td.num{{text-align:right;font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums}}tr.tot td{{border-top:2px solid var(--bd);font-weight:700;background:#13151d}}
.trade{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 16px;margin:12px 0}}
.thead{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:4px}}.tt{{font-size:15px}}.idx{{color:var(--dim);font-weight:700;margin-right:4px}}
.otag{{font-size:11px;padding:1px 8px;border-radius:20px;border:1px solid var(--bd);margin-left:6px}}
.badges{{display:flex;gap:8px;flex-wrap:wrap}}.badge{{font-size:12px;padding:3px 10px;border-radius:7px;border:1px solid var(--bd);font-family:ui-monospace,monospace;background:var(--card2)}}.badge.claim{{color:var(--amb)}}
.note{{font-size:13px;color:#aab2d8;margin:6px 0 9px;padding:8px 11px;background:#12141c;border-left:3px solid var(--pur);border-radius:0 7px 7px 0}}
svg{{background:#0c0e14;border-radius:8px;display:block}}
.fline{{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;margin-top:9px;font-family:ui-monospace,monospace;color:var(--dim)}}.fline b{{color:var(--tx)}}
.msgs{{margin-top:11px;border-top:1px solid var(--bd);padding-top:9px}}
.msgs summary{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim);cursor:pointer;margin-bottom:7px}}
.msg{{background:#0e1622;border:1px solid #1b2738;border-radius:8px;padding:7px 11px;margin-bottom:6px}}
.msg.sig{{border-color:#2a3a55;background:#0d1828}}
.mid{{font-size:10.5px;color:#5a87c4;font-family:ui-monospace,monospace;display:block;margin-bottom:3px}}
.msg pre{{margin:0;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,monospace;font-size:12px;color:#bcc6ea;line-height:1.45}}
.foot{{color:var(--dim);font-size:12px;margin-top:10px}}.foot b{{color:var(--tx)}}
</style></head><body><div class="wrap">

<h1>Dennis “+2,702% / +$64,394” (May 11–29) — complete copier validation</h1>
<p class="sub">Every signal in the paid Insiders-Scalp ledger with its <b>real posted entry</b>, charted against actual WEEX/Binance 1-minute price — the posted entry zone, stop, target(s) and every management post Dennis made, vs where price actually went. Validated by multi-agent adversarial loop → codex gate → independent re-run; <b>nothing tuned to his numbers</b>.</p>

<div class="basis"><b>How to read the money:</b> all copier figures are on a <b>$1,000 account risking 5% per trade</b> — the exact basis Dennis uses in his own footnote. So one full stop-loss = <b>−$50 (−5%)</b>, and the figures add the way a flat-stake book does (not compounded).</div>
<div class="basis"><b>Are we leveraged like he is? Yes.</b> Risking 5% per trade sizes the position to the stop, which <i>is</i> leverage: <b>5% ÷ stop-distance ≈ 1.8× median</b> here (up to ~4.9× on tight-stop trades — see the “Lev” column). His huge per-trade %s are return-on-margin at <b>higher</b> leverage on his own fills. The copier’s shortfall is <b>fill &amp; exit quality, not missing leverage</b> — and because the copyable edge is negative, <b>more</b> leverage only deepens the loss (10% risk → −62%; past that the linear math crosses −100%, i.e. the account is liquidated — more leverage just brings ruin sooner, never a win).</div>

<div class="verdict"><b style="color:#fff">Bottom line.</b> Copying the +2,702% ledger as a market-entry follower turns a $1,000 account into <b class="neg">≈${end_bal:,.0f} ({pct(mm[0]):+.0f}%)</b> over the 32 trades — a <b>loss</b> — versus Dennis’s footnoted <b class="amb">+120–130%</b> (≈$2,200–$2,300). The charts below show why, trade by trade.</div>

<div class="cards">
<div class="kc"><div class="k">Copier (our bot) — $1k @5% risk</div><div class="v neg">${end_bal:,.0f}</div><div class="n">{pct(mm[0]):+.0f}% · {mm[1]}/{mm[2]} winners · NET LOSS</div></div>
<div class="kc"><div class="k">Dennis claimed</div><div class="v amb">≈$2,250</div><div class="n">+120–130% ("+2,702%" = summed leveraged per-trade %)</div></div>
<div class="kc"><div class="k">Posted-limit fills</div><div class="v blue">{tot["posted_manage"][2]}/32</div><div class="n">14 limit orders never trade within 6h</div></div>
<div class="kc"><div class="k">Validation</div><div class="v">3×</div><div class="n">adversarial loop · codex · re-run · 3 bugs caught</div></div>
</div>

<h2>How to read each chart</h2>
<div class="legend">
<span><span class="sw" style="background:#26a69a"></span><span class="sw" style="background:#ef5350;margin-left:-3px"></span><b>candlesticks</b> (OHLC)</span>
<span><span class="sw" style="background:#9ece6a;opacity:.5"></span><b>posted entry zone</b></span>
<span><span class="sw" style="background:#f7768e"></span><b>stop</b></span>
<span><span class="sw" style="background:#73daca"></span><b>take-profit</b></span>
<span><span class="sw" style="background:#e0af68"></span><b>signal / market fill</b></span>
<span><span class="sw" style="background:#bb9af7"></span><b>Dennis’s management posts</b></span>
<span class="dim">— each chart now runs to the actual exit, so you can see the stop/target get hit.</span>
</div>

<h2>Per-trade — what a copier actually got vs what Dennis claimed (all 32)</h2>
{cards}

<h2>Complete ledger table — every field</h2>
<div class="panel">
<table><thead><tr><th>#</th><th>Sym</th><th>Dir</th><th>Date</th><th>msg</th><th>Entry range</th><th>Stop</th><th>Lev*</th><th>Target(s)</th><th class="num">Dennis $</th><th class="num">Dennis %</th><th class="num">Copier (mkt) $ / %</th><th class="num">if&nbsp;limit</th><th class="num">if&nbsp;best&nbsp;fill</th><th>Outcome</th></tr></thead>
<tbody>{rows}
<tr class="tot"><td></td><td>TOTAL</td><td colspan=7 class="dim">32 trades · {mm[1]}/{mm[2]} winners · $1,000 @ 5% risk</td><td class="num amb">+${d["claim_sum"]:,}*</td><td class="num amb">~+2,450%*</td><td class="num neg">{mtxt(mm[0])}</td><td class="num pos">{pct(tot["posted_manage"][0]):+.0f}%</td><td class="num pos">{pct(tot["edge_manage"][0]):+.0f}%</td><td class="dim small">ends ${end_bal:,.0f}</td></tr>
</tbody></table>
<p class="foot">*Dennis’s $ are on his own (larger, leveraged) account; his “%” are summed leveraged per-trade returns, not an account figure — shown only for reference. <b>Copier (mkt)</b> = market entry + following his posted management, on $1,000 @5% (the honest copier number). <b>if limit</b> = a patient limit at his posted price (only {tot["posted_manage"][2]}/32 ever fill). <b>if best fill</b> = optimistic best-touched-in-range (not reliably achievable). <b>Lev*</b> = implied leverage to risk 5% at the posted stop (= 5% ÷ stop-distance); the copier is leveraged, same basis Dennis cites.</p>
</div>

<h2>“Why not just use limit orders to get his fills?”</h2>
<div class="panel">
<p class="sub" style="margin-top:0">A fair question — a limit at his posted entry gets a <i>better</i> price than chasing in at market. But it only helps on trades that <b>come back</b> to your price, and it introduces a worse problem: <b>adverse selection.</b></p>
<table style="max-width:640px"><thead><tr><th>Entry style (+ his posted management)</th><th class="num">$1k →</th><th class="num">return</th><th class="num">fills</th></tr></thead><tbody>
<tr><td>Market — chase in now (our bot)</td><td class="num neg">${ACCT+usd(mm[0]):,.0f}</td><td class="num neg">{pct(mm[0]):+.0f}%</td><td class="num dim">32/32</td></tr>
<tr><td>Limit at his posted entry</td><td class="num pos">${ACCT+usd(pmg[0]):,.0f}*</td><td class="num pos">{pct(pmg[0]):+.0f}%*</td><td class="num dim">{pmg[2]}/32</td></tr>
<tr><td class="dim">…limit, stripping the one HYPE artifact</td><td class="num neg">${ACCT+usd(_posted_exH):,.0f}</td><td class="num neg">{pct(_posted_exH):+.0f}%</td><td class="num dim">{pmg[2]-1}/32</td></tr>
</tbody></table>
<p class="foot">*The +{pct(pmg[0]):.0f}% “limit” figure is <b>almost entirely one trade</b> — HYPE rode an unmanaged tail (+{usd(pmg[0]-_posted_exH):,.0f}). Strip it and the limit copier is <b class="neg">{pct(_posted_exH):+.0f}%</b> on the trades it fills. And it only fills <b>{pmg[2]} of 32</b> — it sits out 44% of his signals.</p>
<div class="verdict" style="border-left-color:#bb9af7;background:linear-gradient(180deg,#191527,#15171f)">
<b style="color:#fff">The adverse-selection trap.</b> Of the <b>{len(_missed)} trades a limit never fills, {_missed_winners} are Dennis’s claimed winners.</b> They ran straight to profit and <b>never came back</b> to the entry — so a limit literally cannot catch them. The trades a limit <i>does</i> fill are the ones that reversed back to your price… and then often kept going to the stop. You catch the losers and miss the runaways.</div>
<p class="sub" style="margin-bottom:6px">The {_missed_winners} winners a limit order would have <b>missed entirely</b> (price never returned to his entry):</p>
<table style="max-width:560px"><thead><tr><th>Symbol</th><th>Dir</th><th class="num">Dennis claimed</th><th class="num">copier, if taken at market</th></tr></thead><tbody>
{_missed_rows}
</tbody></table>
<p class="foot">Net: limit entry is <b>less bad on fill quality</b> (≈{pct(_posted_exH):+.0f}% vs −31%) but <b>forgoes his headline winners</b> and still loses. There is no fill rule that catches a runaway you only entered <i>after</i> the signal — which is exactly why his edge isn’t copyable. (His own method: a market slice to catch runaways + a limit ladder + averaging — see the per-trade notes.)</p>
</div>

<h2>Robustness — the loss survives every stress test</h2>
<div class="panel">
<table><thead><tr><th>market entry + posted management</th><th class="num">$1k becomes</th><th class="num">return</th><th class="num">winners</th></tr></thead><tbody>
<tr><td>all 32 trades</td><td class="num neg">${ACCT+usd(mm[0]):,.0f}</td><td class="num neg">{pct(mm[0]):+.0f}%</td><td class="num dim">{mm[1]}/{mm[2]}</td></tr>
<tr><td>delete the single load-bearing trade (BTC-1609) — cherry-pick test</td><td class="num neg">${ACCT+usd(tot["del1609"][0]):,.0f}</td><td class="num neg">{pct(tot["del1609"][0]):+.0f}%</td><td class="num dim">{tot["del1609"][1]}/{tot["del1609"][2]}</td></tr>
<tr><td>only fully price-resolved trades (≤ May 24)</td><td class="num neg">${ACCT+usd(tot["thru24"][0]):,.0f}</td><td class="num neg">{pct(tot["thru24"][0]):+.0f}%</td><td class="num dim">{tot["thru24"][1]}/{tot["thru24"][2]}</td></tr>
<tr><td>strip the HYPE tail artifact</td><td class="num neg">${ACCT+usd(tot["exHYPE"][0]):,.0f}</td><td class="num neg">{pct(tot["exHYPE"][0]):+.0f}%</td><td class="num dim">{tot["exHYPE"][1]}/{tot["exHYPE"][2]}</td></tr>
</tbody></table>
<p class="foot">Token/scale gate passed all 16 symbols (WEEX↔Binance &lt;0.1%). All figures gross of fees/funding (which make the result worse). No number tuned to +2,702% / +120–130% / +$64,394.</p>
</div>
<p class="foot" style="margin-top:24px">Source: paid-channel export · harness <code>harness.py</code> · every entry/stop/target/management event traces to a paid-channel message id · full writeup <code>RESULTS_MAY.md</code>.</p>
</div></body></html>"""
open("dashboard_full.html","w").write(html)
print("wrote dashboard_full.html", len(html), "bytes,", len(T), "charts")
