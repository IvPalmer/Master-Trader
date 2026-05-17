#!/usr/bin/env python3
"""Render the side-by-side LLM vs regex HTML report.

Reads out/trades_regex.json and out/trades_llm.json. Produces report.html with:
  - Headline metrics side-by-side (LLM vs regex)
  - Overlaid equity curves
  - Diff column: which trades differ between the two pipelines
  - Full trade log for the LLM pipeline (since it's the recommended path)

    python3 render_report.py
"""
import html
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"


def fmt_money(x):
    if x is None:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}${x:.2f}"


def fmt_num(x):
    if x is None or x == "":
        return "—"
    if isinstance(x, str):
        return x
    try:
        return f"{x:,.6g}"
    except (TypeError, ValueError):
        return str(x)


def summarize(data):
    trades = data.get("trades", [])
    sized = [t for t in trades if t.get("scaled_pnl") is not None]
    realized = [t for t in sized if t.get("exit_reason") in {"tp", "sl", "manual", "open"}]
    pnl = data.get("total_pnl_usd", 0.0)
    tp = sum(1 for t in realized if t["exit_reason"] == "tp")
    sl = sum(1 for t in realized if t["exit_reason"] == "sl")
    manual = sum(1 for t in realized if t["exit_reason"] == "manual")
    still = sum(1 for t in realized if t["exit_reason"] == "open")
    wins = [t for t in sized if (t["scaled_pnl"] or 0) > 0]
    losses = [t for t in sized if (t["scaled_pnl"] or 0) < 0]
    win_pnl = sum((t["scaled_pnl"] or 0) for t in wins)
    loss_pnl = sum((t["scaled_pnl"] or 0) for t in losses)
    pf = (win_pnl / abs(loss_pnl)) if loss_pnl else float("inf")
    wr = (len(wins) / len(sized) * 100) if sized else 0
    return {
        "pnl": pnl,
        "return_pct": data.get("account_return_pct", 0),
        "n_parsed": data.get("n_trades_parsed", len(trades)),
        "n_sized": data.get("n_trades_sized", len(sized)),
        "n_skipped": data.get("n_skipped", 0),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": wr,
        "profit_factor": pf,
        "tp": tp, "sl": sl, "manual": manual, "open": still,
        "avg_leverage": data.get("avg_leverage"),
    }


def equity_series(trades):
    """Return [(t, cum_pnl), ...] across resolved trades sorted by date."""
    series = []
    cum = 0.0
    for t in sorted(trades, key=lambda x: x["date"]):
        v = t.get("scaled_pnl")
        if v is None:
            continue
        cum += v
        series.append((t["date"], cum))
    return series


def equity_svg_dual(llm_series, regex_series, width=960, height=240):
    """Two equity curves overlaid on the same x-axis (by event index)."""
    if not llm_series and not regex_series:
        return ""
    all_vals = [v for _, v in llm_series] + [v for _, v in regex_series] + [0]
    y_min, y_max = min(all_vals), max(all_vals)
    if y_max == y_min:
        y_max = y_min + 1
    n_max = max(len(llm_series), len(regex_series), 1)
    pad_x, pad_y = 48, 24
    w = width - 2 * pad_x
    h = height - 2 * pad_y

    def px(i):
        return pad_x + (i / max(1, n_max - 1)) * w

    def py(v):
        return pad_y + (1 - (v - y_min) / (y_max - y_min)) * h

    def path_for(series, color):
        if not series:
            return ""
        d = " ".join(
            f"{'M' if i == 0 else 'L'} {px(i):.1f} {py(v):.1f}"
            for i, (_, v) in enumerate(series)
        )
        return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2"/>'

    ticks = []
    for frac in (0, 0.25, 0.5, 0.75, 1):
        v = y_min + frac * (y_max - y_min)
        y = py(v)
        ticks.append(
            f'<line x1="{pad_x}" y1="{y:.1f}" x2="{width - pad_x}" y2="{y:.1f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
            f'<text x="6" y="{y + 4:.1f}" fill="#6b7280" font-size="11">${v:.0f}</text>'
        )

    zero_y = py(0)
    final_llm = llm_series[-1][1] if llm_series else 0
    final_regex = regex_series[-1][1] if regex_series else 0

    return f"""<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet">
  {' '.join(ticks)}
  <line x1="{pad_x}" y1="{zero_y:.1f}" x2="{width - pad_x}" y2="{zero_y:.1f}"
        stroke="#9ca3af" stroke-width="1" stroke-dasharray="2,3"/>
  {path_for(regex_series, '#f59e0b')}
  {path_for(llm_series, '#2563eb')}
  <g font-size="12" font-weight="600">
    <text x="{width - pad_x - 200:.0f}" y="{pad_y - 6:.0f}" fill="#2563eb">
      LLM {fmt_money(final_llm)}
    </text>
    <text x="{width - pad_x - 80:.0f}" y="{pad_y - 6:.0f}" fill="#f59e0b">
      Regex {fmt_money(final_regex)}
    </text>
  </g>
</svg>"""


def trade_row(t, kind_label=""):
    pnl = t.get("scaled_pnl")
    pnl_class = "pos" if pnl is not None and pnl > 0 else ("neg" if pnl is not None and pnl < 0 else "")
    exit_reason = t.get("exit_reason") or "—"
    reason_icon = {"tp": "✓", "sl": "✗", "manual": "○", "open": "·"}.get(exit_reason, "")
    events_summary = ", ".join(e["kind"] for e in t.get("events", [])) or "—"
    entry = t.get("entry")
    lev = t.get("leverage")
    sl_pct = t.get("sl_distance_pct")
    market_tag = ' <span class="me-tag">M</span>' if t.get("market_entry") else ""
    return f"""<tr data-pnl="{pnl if pnl is not None else 0}" data-date="{t['date']}">
  <td class="mono">{t['date'][:10]}</td>
  <td class="sym">{html.escape(t['symbol'])}{market_tag}</td>
  <td class="dir-{t['direction'].lower()}">{t['direction']}</td>
  <td class="mono">{fmt_num(entry)}</td>
  <td class="mono">{fmt_num(t.get('sl'))}</td>
  <td class="mono">{fmt_num(t.get('tp'))}</td>
  <td class="mono">{fmt_num(t.get('exit_price'))}</td>
  <td>{reason_icon} {exit_reason}</td>
  <td class="mono">{f'{lev:.1f}x' if lev else '—'}</td>
  <td class="mono">{f'{sl_pct * 100:.2f}%' if sl_pct else '—'}</td>
  <td class="mono {pnl_class}">{fmt_money(pnl)}</td>
  <td class="events">{html.escape(events_summary[:100])}</td>
  <td class="msg">#{t['msg_id']}</td>
</tr>"""


def compute_diff(regex_data, llm_data):
    """Find trades present in LLM but not regex (and vice versa) by msg_id."""
    regex_by_id = {t["msg_id"]: t for t in regex_data["trades"]}
    llm_by_id = {t["msg_id"]: t for t in llm_data["trades"]}
    only_llm = [t for mid, t in llm_by_id.items() if mid not in regex_by_id]
    only_regex = [t for mid, t in regex_by_id.items() if mid not in llm_by_id]

    # Trades present in both — flag where LLM rescued by filling market entry
    rescued = []
    for mid, lt in llm_by_id.items():
        rt = regex_by_id.get(mid)
        if not rt:
            continue
        if lt.get("market_entry") and rt.get("entry") is None and lt.get("entry"):
            rescued.append({
                "msg_id": mid, "symbol": lt["symbol"], "date": lt["date"][:10],
                "direction": lt["direction"],
                "llm_pnl": lt.get("scaled_pnl"),
                "regex_pnl": rt.get("scaled_pnl"),
            })
    return only_llm, only_regex, rescued


def render(regex_data, llm_data):
    s_llm = summarize(llm_data)
    s_regex = summarize(regex_data)
    eq_llm = equity_series(llm_data["trades"])
    eq_regex = equity_series(regex_data["trades"])

    delta_pnl = s_llm["pnl"] - s_regex["pnl"]
    delta_ret = s_llm["return_pct"] - s_regex["return_pct"]
    delta_class = "pos" if delta_pnl >= 0 else "neg"

    only_llm, only_regex, rescued = compute_diff(regex_data, llm_data)

    rescued_html = ""
    if rescued:
        rescued_html = "<ul class='notes'>" + "".join(
            f"<li><strong>#{r['msg_id']} {r['symbol']} {r['direction']}</strong> "
            f"({r['date']}): regex skipped (market entry), LLM filled via WEEX → "
            f"<span class='{'pos' if (r['llm_pnl'] or 0) >= 0 else 'neg'}'>"
            f"{fmt_money(r['llm_pnl'])}</span></li>"
            for r in rescued[:20]
        ) + "</ul>"
        if len(rescued) > 20:
            rescued_html += f"<p class='sub'>(+{len(rescued) - 20} more)</p>"
    else:
        rescued_html = "<p class='sub'>None.</p>"

    only_llm_html = ""
    if only_llm:
        only_llm_html = "<ul class='notes'>" + "".join(
            f"<li><strong>#{t['msg_id']} {t['symbol']} {t['direction']}</strong> "
            f"({t['date'][:10]}): pnl <span class='{'pos' if (t.get('scaled_pnl') or 0) >= 0 else 'neg'}'>"
            f"{fmt_money(t.get('scaled_pnl'))}</span></li>"
            for t in only_llm[:15]
        ) + "</ul>"
        if len(only_llm) > 15:
            only_llm_html += f"<p class='sub'>(+{len(only_llm) - 15} more)</p>"
    else:
        only_llm_html = "<p class='sub'>None.</p>"

    only_regex_html = ""
    if only_regex:
        only_regex_html = "<ul class='notes'>" + "".join(
            f"<li><strong>#{t['msg_id']} {t['symbol']} {t['direction']}</strong> "
            f"({t['date'][:10]}): pnl <span class='{'pos' if (t.get('scaled_pnl') or 0) >= 0 else 'neg'}'>"
            f"{fmt_money(t.get('scaled_pnl'))}</span></li>"
            for t in only_regex[:15]
        ) + "</ul>"
    else:
        only_regex_html = "<p class='sub'>None.</p>"

    rows = "\n".join(
        trade_row(t)
        for t in sorted(llm_data["trades"], key=lambda x: x["date"])
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Insiders Scalp — LLM vs Regex Replay</title>
<style>
  :root {{
    --bg: #ffffff;
    --fg: #111827;
    --muted: #6b7280;
    --border: #e5e7eb;
    --pos: #16a34a;
    --neg: #dc2626;
    --short: #dc2626;
    --long: #16a34a;
    --llm: #2563eb;
    --regex: #f59e0b;
  }}
  * {{ box-sizing: border-box }}
  body {{
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: var(--fg);
    background: var(--bg);
    margin: 0;
    padding: 24px 32px 64px;
    max-width: 1280px;
    margin-inline: auto;
  }}
  h1 {{ margin: 0 0 4px; font-size: 22px }}
  h2 {{ margin: 32px 0 12px; font-size: 16px; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em }}
  .sub {{ color: var(--muted); margin-bottom: 24px; font-size: 13px }}
  .compare {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 16px;
    margin: 24px 0;
  }}
  .col {{
    background: #f9fafb;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }}
  .col.llm   {{ border-top: 3px solid var(--llm) }}
  .col.regex {{ border-top: 3px solid var(--regex) }}
  .col.delta {{ border-top: 3px solid #6b7280 }}
  .col h3 {{ margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted) }}
  .col h3 .tag {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle }}
  .col.llm h3 .tag   {{ background: var(--llm) }}
  .col.regex h3 .tag {{ background: var(--regex) }}
  .stat {{ display: flex; justify-content: space-between; padding: 4px 0; font-variant-numeric: tabular-nums }}
  .stat .label {{ color: var(--muted); font-size: 12px }}
  .stat .value {{ font-weight: 600; font-size: 13px }}
  .stat .big {{ font-size: 26px; font-weight: 700 }}
  .pos {{ color: var(--pos) }}
  .neg {{ color: var(--neg) }}
  .equity {{
    background: #f9fafb;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: top }}
  th {{
    background: #f9fafb; color: var(--muted); font-weight: 600;
    text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em;
    cursor: pointer; user-select: none; position: sticky; top: 0;
  }}
  th:hover {{ color: var(--fg) }}
  .mono {{ font-variant-numeric: tabular-nums; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px }}
  .sym {{ font-weight: 600 }}
  .dir-long {{ color: var(--long); font-weight: 600 }}
  .dir-short {{ color: var(--short); font-weight: 600 }}
  .events {{ color: var(--muted); font-size: 11px; max-width: 320px }}
  .msg {{ color: var(--muted); font-family: ui-monospace, monospace; font-size: 11px }}
  ul.notes li {{ margin-bottom: 6px; font-size: 13px }}
  .me-tag {{
    display: inline-block; background: #dbeafe; color: var(--llm);
    padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.05em; margin-left: 4px;
    vertical-align: middle;
  }}
  code {{ background: #f3f4f6; padding: 1px 5px; border-radius: 3px; font-size: 12px }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px }}
  .legend {{
    display: flex; gap: 16px; font-size: 12px; color: var(--muted);
    margin-bottom: 8px;
  }}
  .legend .swatch {{ display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin-right: 4px }}
  .insight {{
    background: #ecfeff; border: 1px solid #67e8f9; border-radius: 6px;
    padding: 12px 16px; margin: 16px 0; font-size: 13px;
  }}
</style>
</head>
<body>
  <h1>Insiders Scalp — LLM vs Regex Paper-Trading Replay</h1>
  <p class="sub">
    {regex_data['n_messages']} messages · April 17 → May 16, 2026 · WEEX 1-min kline PnL
    · $1k account, $10 risk per trade, $50 margin
    · generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </p>

  <div class="insight">
    <strong>LLM rescued {len(rescued)} market-entry trades</strong> that the regex skipped
    (no parsed entry price). Net delta: <strong class="{delta_class}">{fmt_money(delta_pnl)} ({delta_ret:+.2f}pp account return)</strong>.
  </div>

  <h2>Headline metrics</h2>
  <div class="compare">
    <div class="col llm">
      <h3><span class="tag"></span>LLM pipeline</h3>
      <div class="stat"><span class="label">Total PnL</span><span class="value big {('pos' if s_llm['pnl'] >= 0 else 'neg')}">{fmt_money(s_llm['pnl'])}</span></div>
      <div class="stat"><span class="label">Account return</span><span class="value">{s_llm['return_pct']:+.2f}%</span></div>
      <div class="stat"><span class="label">Trades parsed</span><span class="value">{s_llm['n_parsed']}</span></div>
      <div class="stat"><span class="label">Sized &amp; simulated</span><span class="value">{s_llm['n_sized']}</span></div>
      <div class="stat"><span class="label">Skipped (no SL)</span><span class="value">{s_llm['n_skipped']}</span></div>
      <div class="stat"><span class="label">Win rate ($)</span><span class="value">{s_llm['win_rate']:.1f}%</span></div>
      <div class="stat"><span class="label">Profit factor</span><span class="value">{s_llm['profit_factor']:.2f}</span></div>
      <div class="stat"><span class="label">TP / SL / Manual</span><span class="value">{s_llm['tp']} / {s_llm['sl']} / {s_llm['manual']}</span></div>
      <div class="stat"><span class="label">Still open</span><span class="value">{s_llm['open']}</span></div>
      <div class="stat"><span class="label">Avg leverage</span><span class="value">{s_llm['avg_leverage']}x</span></div>
    </div>
    <div class="col regex">
      <h3><span class="tag"></span>Regex pipeline (Eduardo's baseline)</h3>
      <div class="stat"><span class="label">Total PnL</span><span class="value big {('pos' if s_regex['pnl'] >= 0 else 'neg')}">{fmt_money(s_regex['pnl'])}</span></div>
      <div class="stat"><span class="label">Account return</span><span class="value">{s_regex['return_pct']:+.2f}%</span></div>
      <div class="stat"><span class="label">Trades parsed</span><span class="value">{s_regex['n_parsed']}</span></div>
      <div class="stat"><span class="label">Sized &amp; simulated</span><span class="value">{s_regex['n_sized']}</span></div>
      <div class="stat"><span class="label">Skipped (no SL/entry)</span><span class="value">{s_regex['n_skipped']}</span></div>
      <div class="stat"><span class="label">Win rate ($)</span><span class="value">{s_regex['win_rate']:.1f}%</span></div>
      <div class="stat"><span class="label">Profit factor</span><span class="value">{s_regex['profit_factor']:.2f}</span></div>
      <div class="stat"><span class="label">TP / SL / Manual</span><span class="value">{s_regex['tp']} / {s_regex['sl']} / {s_regex['manual']}</span></div>
      <div class="stat"><span class="label">Still open</span><span class="value">{s_regex['open']}</span></div>
      <div class="stat"><span class="label">Avg leverage</span><span class="value">{s_regex['avg_leverage']}x</span></div>
    </div>
    <div class="col delta">
      <h3>Δ LLM − Regex</h3>
      <div class="stat"><span class="label">PnL delta</span><span class="value big {delta_class}">{fmt_money(delta_pnl)}</span></div>
      <div class="stat"><span class="label">Return delta</span><span class="value">{delta_ret:+.2f}pp</span></div>
      <div class="stat"><span class="label">Trades delta</span><span class="value">{s_llm['n_parsed'] - s_regex['n_parsed']:+d}</span></div>
      <div class="stat"><span class="label">Sized delta</span><span class="value">{s_llm['n_sized'] - s_regex['n_sized']:+d}</span></div>
      <div class="stat"><span class="label">Market entries rescued</span><span class="value">{len(rescued)}</span></div>
      <div class="stat"><span class="label">Trades only in LLM</span><span class="value">{len(only_llm)}</span></div>
      <div class="stat"><span class="label">Trades only in Regex</span><span class="value">{len(only_regex)}</span></div>
      <div class="stat"><span class="label">Win-rate delta</span><span class="value">{s_llm['win_rate'] - s_regex['win_rate']:+.1f}pp</span></div>
      <div class="stat"><span class="label">PF delta</span><span class="value">{s_llm['profit_factor'] - s_regex['profit_factor']:+.2f}</span></div>
    </div>
  </div>

  <h2>Equity curves</h2>
  <div class="legend">
    <span><span class="swatch" style="background:var(--llm)"></span> LLM</span>
    <span><span class="swatch" style="background:var(--regex)"></span> Regex</span>
  </div>
  <div class="equity">{equity_svg_dual(eq_llm, eq_regex)}</div>

  <h2>Market entries rescued by the LLM</h2>
  {rescued_html}

  <h2>Trades only in LLM pipeline</h2>
  {only_llm_html}

  <h2>Trades only in Regex pipeline</h2>
  {only_regex_html}

  <h2>LLM trade log <span style="font-weight:400;color:var(--muted);font-size:12px;text-transform:none">M = market entry (filled via WEEX) · click headers to sort</span></h2>
  <div class="table-wrap">
    <table id="trades">
      <thead><tr>
        <th data-key="date">Date</th>
        <th>Symbol</th>
        <th>Dir</th>
        <th>Entry</th>
        <th>SL</th>
        <th>TP</th>
        <th>Exit</th>
        <th>Reason</th>
        <th>Lev</th>
        <th>SL%</th>
        <th data-key="pnl">PnL</th>
        <th>Events</th>
        <th>Msg</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

<script>
document.querySelectorAll('#trades th[data-key]').forEach(th => {{
  let asc = true;
  th.addEventListener('click', () => {{
    const key = th.dataset.key;
    const tbody = document.querySelector('#trades tbody');
    const rows = [...tbody.querySelectorAll('tr')];
    rows.sort((a, b) => {{
      const av = key === 'pnl' ? parseFloat(a.dataset.pnl) : a.dataset[key];
      const bv = key === 'pnl' ? parseFloat(b.dataset.pnl) : b.dataset[key];
      if (key === 'pnl') return (asc ? 1 : -1) * (av - bv);
      return (asc ? 1 : -1) * String(av).localeCompare(String(bv));
    }});
    asc = !asc;
    rows.forEach(r => tbody.appendChild(r));
  }});
}});
</script>
</body>
</html>
"""


def main():
    regex_data = json.loads((OUT / "trades_regex.json").read_text())
    llm_data = json.loads((OUT / "trades_llm.json").read_text())
    html_out = render(regex_data, llm_data)
    op = OUT / "report.html"
    op.write_text(html_out)
    print(f"wrote {op}  ({op.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
