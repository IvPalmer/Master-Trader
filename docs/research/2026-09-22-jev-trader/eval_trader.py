"""Avalia previsoes de direcao (mid mais alto depois de H blocos?) sobre estados gravados.

Uso: python eval_trader.py run.jsonl [laya_scores.jsonl]
Rotulo: mid do primeiro registro com bloco >= b+H. Movimentos exatamente zero sao descartados.
Janelas independentes: decisoes espacadas >= H blocos (as de 30s se sobrepoem e inflam a amostra).
"""
import json, math, sys

rows = [json.loads(l) for l in open(sys.argv[1])]
rows.sort(key=lambda r: r["block"])
laya = {}
if len(sys.argv) > 2:
    for l in open(sys.argv[2]):
        d = json.loads(l); laya[d["block"]] = d["pBuy"]

blocks = [r["block"] for r in rows]
import bisect
def future_mid(i):
    H = rows[i]["state"]["horizonBlocks"]
    j = bisect.bisect_left(blocks, rows[i]["block"] + H)
    return rows[j]["mid"] if j < len(rows) else None

def mock_pbuy(s, block):
    flow = s["trades"]["cvdMon"] / (s["trades"]["buyMon"] + s["trades"]["sellMon"]) if (s["trades"]["buyMon"] + s["trades"]["sellMon"]) else 0
    h = (block * 2654435761) & 0xFFFFFFFF
    h ^= h >> 15; h = (h * 2246822519) & 0xFFFFFFFF; h ^= h >> 13
    noise = ((h % 1000) / 1000 - 0.5) * 3
    sig = s["returnsBps"]["last20"] / 8 + s["bookImbalance"] * 1.5 + flow * 2 + noise
    return 1 / (1 + math.exp(-sig))

sgn = lambda x: 1.0 if x > 0 else (0.0 if x < 0 else 0.5)
preds = {
    "oss qwen3-4b (ao vivo)": lambda r: r["pBuy"],
    "laya typed-decisions": lambda r: laya.get(r["block"]),
    "mock do jev-trader": lambda r: mock_pbuy(r["state"], r["block"]),
    "momentum (ret 20 blocos)": lambda r: sgn(r["state"]["returnsBps"]["last20"]),
    "desequilibrio do livro": lambda r: sgn(r["state"]["bookImbalance"]),
    "fluxo de taker (cvd)": lambda r: sgn(r["state"]["trades"]["cvdMon"]),
    "sempre sobe": lambda r: 1.0,
    "sempre cai": lambda r: 0.0,
}

ev = []
for i, r in enumerate(rows):
    fm = future_mid(i)
    if fm is None: continue
    mv = (fm - r["mid"]) / r["mid"] * 1e4
    if mv == 0: continue
    ev.append((r, mv))

# janelas independentes
ind, last = [], -10**12
for r, mv in ev:
    if r["block"] >= last + r["state"]["horizonBlocks"]:
        ind.append((r, mv)); last = r["block"]

def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); m = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c - m) / d, (c + m) / d)

def score(sample, f):
    k = n = 0; brier = 0.0; nb = 0; edge = 0.0; sig_k = sig_n = 0
    for r, mv in sample:
        p = f(r)
        if p is None: continue
        if p == 0.5: continue
        up = mv > 0
        n += 1; k += (p > 0.5) == up
        brier += (p - (1.0 if up else 0.0)) ** 2; nb += 1
        edge += mv if p > 0.5 else -mv
        if abs(mv) > r["spreadBps"]:
            sig_n += 1; sig_k += (p > 0.5) == up
    return k, n, (brier / nb if nb else None), (edge / n if n else None), sig_k, sig_n

dur = (rows[-1]["t"] - rows[0]["t"]) / 60000 if rows else 0
print(f"decisoes gravadas {len(rows)} em {dur:.0f} min | com rotulo e movimento != 0: {len(ev)} | janelas independentes: {len(ind)}")
up = sum(mv > 0 for _, mv in ind); print(f"nas independentes: {up} subiram, {len(ind)-up} cairam | spread mediano {sorted(r['spreadBps'] for r,_ in ind)[len(ind)//2]:.1f} bps | |movimento| mediano {sorted(abs(m) for _,m in ind)[len(ind)//2]:.1f} bps")
lat = sorted(r["latencyMs"] for r in rows); print(f"latencia do modelo oss: p50 {lat[len(lat)//2]} ms, p90 {lat[int(len(lat)*.9)]} ms")
print(f"\n{'preditor':<26} {'acerto (indep.)':>18} {'IC 95%':>14} {'acerto (>spread)':>17} {'edge bps/trade':>15} {'brier':>6}")
for name, f in preds.items():
    k, n, b, e, sk, sn = score(ind, f)
    if n == 0: print(f"{name:<26} {'sem dados':>18}"); continue
    lo, hi = wilson(k, n)
    print(f"{name:<26} {f'{k}/{n} = {k/n*100:4.1f}%':>18} {f'{lo*100:4.1f}-{hi*100:4.1f}%':>14} "
          f"{(f'{sk}/{sn} = {sk/sn*100:4.1f}%' if sn else '-'):>17} {e:>15.2f} {b:>6.3f}")
