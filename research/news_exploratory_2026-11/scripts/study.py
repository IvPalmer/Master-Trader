"""Shared event-study helpers + charts (exploratory, pre-2023 only)."""
import bisect, math
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
M5 = 300_000; H = 3_600_000
SURF, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
BLUE, ORANGE, RED, LIGHT = '#2a78d6', '#eb6834', '#e34948', '#b9b8b2'
COST = 2 * (0.0010 + 0.00045)   # 10 bps slippage + 4.5 bps HL taker, per side
plt.rcParams.update({'figure.facecolor': SURF, 'axes.facecolor': SURF, 'axes.edgecolor': GRID,
    'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2, 'text.color': INK,
    'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6, 'font.size': 9,
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.titlesize': 9})

class Series:
    def __init__(self, rows):           # rows: (open_ms, o, h, l, c, v)
        rows = sorted({r[0]: r for r in rows}.values())
        self.t = [r[0] for r in rows]; self.o = [r[1] for r in rows]; self.c = [r[4] for r in rows]
    def open_at(self, t):               # open of first candle opening at/after t (tradeable price at t)
        i = bisect.bisect_left(self.t, t)
        return (self.t[i], self.o[i]) if i < len(self.t) and self.t[i] - t < 30 * 60_000 else (None, None)
    def close_before(self, t):          # close of last candle fully closed by t
        i = bisect.bisect_right(self.t, t - M5) - 1
        return self.c[i] if i >= 0 and t - self.t[i] < 60 * 60_000 else None

def usd(tok, quote, btc):
    if quote != 'BTC': return tok
    rows = []
    for t, o, c in zip(tok.t, tok.o, tok.c):
        _, bo = btc.open_at(t); bc = btc.close_before(t + M5)
        if bo and bc: rows.append((t, o * bo, 0, 0, c * bc, 0))
    return Series(rows)

def path(s, btc, t0, offs):
    ref, bref = s.close_before(t0), btc.close_before(t0)
    raw, ab = [], []
    for off in offs:
        _, p = s.open_at(t0 + off); _, b = btc.open_at(t0 + off)
        if ref and bref and p and b:
            r = math.log(p / ref); raw.append(r); ab.append(r - math.log(b / bref))
        else: raw.append(np.nan); ab.append(np.nan)
    return np.array(raw), np.array(ab)

def trade(s, btc, t0, horizons, side):
    """side=+1 long, -1 short. Entry at t0+5m. Returns dict h -> (net, hedged_net)."""
    _, e = s.open_at(t0 + M5); _, be = btc.open_at(t0 + M5); out = {}
    for name, h in horizons.items():
        _, x = s.open_at(t0 + h); _, bx = btc.open_at(t0 + h)
        if e and x and be and bx:
            r = x / e - 1; br = bx / be - 1
            out[name] = (side * r - COST, side * (r - br) - COST)
        else: out[name] = (None, None)
    return out

def multiples(items, t0key, title, fname, ncol=6, hours=(-24, 120)):
    n = len(items); nrow = math.ceil(n / ncol)
    fig, axs = plt.subplots(nrow, ncol, figsize=(2.3 * ncol, 1.75 * nrow + 0.6), squeeze=False)
    offs = np.arange(hours[0] * H, hours[1] * H + 1, M5)
    for ax, it in zip(axs.flat, items):
        raw, ab = path(it['s'], it['btc'], it[t0key], offs)
        x = offs / H
        ax.plot(x, 100 * np.exp(raw), color=BLUE, lw=1.2)
        braw, _ = path(it['btc'], it['btc'], it[t0key], offs)
        ax.plot(x, 100 * np.exp(braw), color=ORANGE, lw=0.9, alpha=0.8)
        ax.axvline(0, color=INK2, lw=0.8, ls='--'); ax.axhline(100, color=LIGHT, lw=0.6)
        ax.set_title(it['label'], loc='left', fontsize=8, color=INK)
        ax.tick_params(labelsize=7)
    for ax in list(axs.flat)[n:]: ax.axis('off')
    fig.suptitle(title, x=0.01, ha='left', fontsize=11, color=INK)
    fig.text(0.01, 0.005, 'azul = token (100 = preço no anúncio)   laranja = BTC   linha tracejada = hora do anúncio   eixo x = horas',
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.97)); fig.savefig(fname, dpi=130); plt.close(fig)

def aggregate(items, t0key, title, fname, horizons, side, hours=(-24, 120)):
    offs = np.arange(hours[0] * H, hours[1] * H + 1, M5); x = offs / H
    P = np.array([path(it['s'], it['btc'], it[t0key], offs)[1] for it in items]) * 100
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={'width_ratios': [1.6, 1]})
    for row in P: a1.plot(x, row, color=LIGHT, lw=0.6, alpha=0.7)
    med = np.nanmedian(P, axis=0); q1, q3 = np.nanpercentile(P, 25, axis=0), np.nanpercentile(P, 75, axis=0)
    a1.fill_between(x, q1, q3, color=BLUE, alpha=0.15, lw=0)
    a1.plot(x, med, color=BLUE, lw=2, label='mediana')
    a1.axvline(0, color=INK2, lw=0.8, ls='--'); a1.axhline(0, color=INK2, lw=0.6)
    a1.set_xlabel('horas desde o anúncio'); a1.set_ylabel('retorno anormal vs BTC (%)')
    a1.set_title('Caminho de cada evento (cinza), mediana (azul) e faixa 25–75%', loc='left')
    lo, hi = np.nanpercentile(P, 3), np.nanpercentile(P, 97); a1.set_ylim(lo - 5, hi + 5)
    T = [trade(it['s'], it['btc'], it[t0key], horizons, side) for it in items]
    names = list(horizons)
    for i, nm in enumerate(names):
        v = np.array([t[nm][1] for t in T if t[nm][1] is not None]) * 100
        jit = (np.random.default_rng(i).random(len(v)) - 0.5) * 0.35
        a2.scatter(np.full(len(v), i) + jit, v, s=14, color=BLUE, alpha=0.55, lw=0)
        m = np.median(v); a2.plot([i - 0.3, i + 0.3], [m, m], color=INK, lw=2)
        a2.text(i + 0.33, m, f'{m:+.1f}%\n{(v > 0).mean() * 100:.0f}% >0', fontsize=8, va='center', color=INK)
    a2.axhline(0, color=INK2, lw=0.6); a2.set_xticks(range(len(names))); a2.set_xticklabels(names)
    a2.set_xlim(-0.5, len(names) - 0.2)
    lo2, hi2 = np.nanpercentile([t[nm][1] * 100 for t in T for nm in names if t[nm][1] is not None], [2, 98])
    a2.set_ylim(lo2 - 5, hi2 + 5)
    a2.set_title(('Short' if side < 0 else 'Long') + ' entrando 5 min depois, líquido de custos, hedge BTC', loc='left')
    a2.set_ylabel('retorno líquido por evento (%)')
    fig.suptitle(title, x=0.01, ha='left', fontsize=11); fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(fname, dpi=130); plt.close(fig)
    return T
