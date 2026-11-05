import pickle, sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from study import plt, SURF, INK, INK2, GRID, BLUE, ORANGE, RED, LIGHT
V = pickle.load(open('data/veto.pkl', 'rb')); G = V['G']; R = V['res']['BTCUSDT']
K = pickle.load(open('data/majors_1h.pkl', 'rb'))
c = pd.DataFrame(K['BTCUSDT'], columns=list('tohlcv')); c.index = pd.to_datetime(c.t, unit='ms')
day = c.c.resample('1D').last()[pd.Timestamp('2017-12-31'):pd.Timestamp('2022-12-31')]
# Fig 1: price with storm days, and the news series (two stacked panels, never dual-axis)
fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 5.6), sharex=True, gridspec_kw={'height_ratios': [1.4, 1]})
a1.semilogy(day.index, day.values, color=INK2, lw=1)
st = R[R.news].index
a1.scatter(st, day.reindex(st).values, s=12, color=RED, zorder=3, lw=0, label='dia de tempestade de notícias de crash')
a1.set_ylabel('BTC (USDT, log)'); a1.legend(loc='upper left', frameon=False, fontsize=8)
a1.set_title('BTC e os dias em que as notícias de crash dispararam (≥ 2× a mediana dos 30 dias anteriores)', loc='left')
s = G.share[pd.Timestamp('2018-01-01'):pd.Timestamp('2022-12-31')] * 1e4
a2.plot(s.index, s.values, color=BLUE, lw=0.8)
a2.set_ylabel('artigos de crash cripto\npor 10 mil artigos (GDELT)')
for ev, lab in ((pd.Timestamp('2020-03-12'), 'COVID'), (pd.Timestamp('2021-05-19'), 'mai/21'), (pd.Timestamp('2022-05-09'), 'LUNA'), (pd.Timestamp('2022-11-08'), 'FTX')):
    a2.annotate(lab, (ev, s.get(ev, np.nan)), xytext=(4, 4), textcoords='offset points', fontsize=8, color=INK2)
fig.tight_layout(); fig.savefig('out/veto_timeline.png', dpi=130); plt.close(fig)
# Fig 2: what happens after: return vs volatility, by condition (BTC and ETH)
groups = [('todos os dias', lambda R: R.index == R.index), ('após tempestade\nde notícias', lambda R: R.news), ('após queda de\npreço ≥ 5%', lambda R: R.price)]
fig, axs = plt.subplots(1, 3, figsize=(12, 3.8))
for ax, (col, ttl, fmt) in zip(axs, (('r3', 'Retorno nos 3 dias seguintes (mediana)', '{:+.1f}%'), ('vol3', 'Volatilidade nos 3 dias seguintes (anualizada)', '{:.0f}%'), ('mdd3', 'Pior queda nos 3 dias seguintes (mediana)', '{:.1f}%'))):
    for j, (sym, color) in enumerate((('BTCUSDT', BLUE), ('ETHUSDT', ORANGE))):
        RR = V['res'][sym]; vals = [RR[f(RR)][col].median() * 100 for _, f in groups]
        xs = np.arange(len(groups)) + (j - 0.5) * 0.36
        ax.bar(xs, vals, width=0.34, color=color, label=sym.replace('USDT', ''))
        for x, v in zip(xs, vals): ax.text(x, v, fmt.format(v), ha='center', va='bottom' if v >= 0 else 'top', fontsize=7.5, color=INK)
    ax.set_xticks(range(len(groups))); ax.set_xticklabels([g for g, _ in groups], fontsize=8); ax.axhline(0, color=INK2, lw=0.6)
    ax.set_title(ttl, loc='left'); ax.grid(axis='x', visible=False)
axs[0].legend(frameon=False, fontsize=8)
fig.suptitle('2018–2022: notícias de crash preveem volatilidade, não direção', x=0.01, ha='left', fontsize=11)
fig.tight_layout(rect=(0, 0, 1, 0.94)); fig.savefig('out/veto_after.png', dpi=130); plt.close(fig)
# Fig 3: a long-BTC position with and without a 3-day veto
r = day.pct_change().dropna()[pd.Timestamp('2018-01-01'):]
def vetoed(flags):
    f = flags.reindex(r.index).fillna(False).astype(bool)
    off = f.shift(1, fill_value=False) | f.shift(2, fill_value=False) | f.shift(3, fill_value=False)
    return r.where(~off, 0.0), off.mean()
curves = {'sempre comprado': (r, 0.0)}
curves['veto por notícias (fora 3 dias)'] = vetoed(R.news)
curves['veto por queda de preço (fora 3 dias)'] = vetoed(R.price)
fig, ax = plt.subplots(figsize=(12, 4.2))
for (nm, (x, off)), color, lw in zip(curves.items(), (INK2, RED, BLUE), (1.0, 1.6, 1.2)):
    eq = (1 + x).cumprod(); dd = (eq / eq.cummax() - 1).min()
    ax.semilogy(eq.index, eq.values, color=color, lw=lw, label=f'{nm}: ×{eq.iloc[-1]:.2f}, pior DD {dd*100:.0f}%, fora {off*100:.0f}% dos dias')
    print(nm, round(eq.iloc[-1], 3), round(dd * 100, 1), round(off * 100, 1), 'vol', round(x.std() * np.sqrt(365) * 100, 1))
ax.legend(frameon=False, fontsize=8, loc='upper left'); ax.set_ylabel('patrimônio (1 = início, log)')
ax.set_title('Comprado em BTC 2018–2022, com e sem veto de 3 dias', loc='left')
fig.tight_layout(); fig.savefig('out/veto_equity.png', dpi=130); plt.close(fig)
