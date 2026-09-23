"""Existe sinal de curto prazo no livro? Varre horizontes e faixas de profundidade
sobre estados gravados pelo recorder do jev-trader (ver oss-model.patch).

Uso: python scan_imbalance.py run.jsonl

Para cada horizonte (em blocos, ~300ms cada) e faixa de desequilibrio, mede o
acerto de "o mid vai na direcao do desequilibrio" em janelas independentes,
separado por metade da rodada. Um sinal confiavel precisa manter a direcao nas
duas metades E entre faixas vizinhas.
"""
import bisect, json, math, sys

rs = sorted((json.loads(l) for l in open(sys.argv[1])), key=lambda r: r["block"])
blocks = [r["block"] for r in rs]; mids = [r["mid"] for r in rs]
N = len(rs); half = N // 2

def imb(s, band):
    if band == "1%":
        return s["bookImbalance"]
    d = s["depth"].get(band)
    if not d: return 0.0
    t = d["bid"] + d["ask"]
    return (d["bid"] - d["ask"]) / t if t else 0.0

def test(h, band, lo, hi, thr):
    k = n = 0; last = -10**12
    for i in range(lo, hi):
        r = rs[i]
        if r["block"] < last + h: continue
        j = bisect.bisect_left(blocks, r["block"] + h)
        if j >= N or mids[j] == r["mid"]: continue
        last = r["block"]; v = imb(r["state"], band)
        if abs(v) <= thr: continue
        n += 1; k += (v > 0) == (mids[j] > r["mid"])
    return k, n

fmt = lambda kn: (f"{kn[0]}/{kn[1]}={kn[0]/kn[1]*100:4.1f}% z{(kn[0]/kn[1]-.5)/math.sqrt(.25/kn[1]):+.1f}"
                  if kn[1] else "-")
bands = list(rs[0]["state"]["depth"].keys()) + ["1%"]
for thr in (0.0, 0.3):
    print(f"\n|desequilibrio| > {thr}")
    print(f"{'faixa':>6} {'h':>4} | {'1a metade':>20} | {'2a metade':>20}")
    for band in bands:
        for h in (6, 12, 30, 100):
            print(f"{band:>6} {h:>4} | {fmt(test(h, band, 0, half, thr)):>20} | {fmt(test(h, band, half, N, thr)):>20}")
