"""Probe zero-shot de um encoder schema-conditioned (GLiNER2) contra o corpus
de producao do killers_bot — issue #62.

NAO e um experimento go/no-go. Mede compatibilidade de schema, latencia no
hardware alvo e taxonomia de erro. Concordancia aqui e fidelidade de
destilacao ao Claude, nao correcao.

Uso:
    pip install "gliner2[local]"
    python -m killers_bot.tools.encoder_probe corpus.json

`corpus.json` e um dump de `SELECT c.*, r.text FROM classifications c
JOIN raw_messages r USING(msg_id)`. NAO versione o dump: e conteudo de canal
privado.

Resultado medido em 2026-09-22 (537 msgs, Mac Studio M1 Max, CPU):

    extracao    direction 314/315 = 99.7%   symbol 356/397 = 89.7%
    latencia    p50 99ms   p90 116ms
    kind        rotulos nus        26/537 =  4.8%   (pior que o acaso, 14%)
                rotulos+descricao 127/537 = 23.6%   (colapsa em `open`)
    confianca   acerto p50 = 1.00 | erro p50 = 1.00  -> sem poder discriminante

Conclusao: zero-shot nao substitui o classificador. A metade de extracao ja e
melhor resolvida por regex (symbol 97.7% com regex, 0ms, gratis). O encoder so
volta a ser candidato APOS fine-tuning, que hoje esta bloqueado pela cobertura
de rotulo (3 das 7 classes com zero exemplos; `close_full` com n=20).
"""
import json
import sys
import time
from collections import Counter, defaultdict

from gliner2 import GLiNER2

MODEL = "fastino/gliner2-base-v1"

# Rotulo -> descricao. Rotulos NUS pontuam abaixo do acaso: o modelo casa
# "increase" com o aumento de lucro de uma mensagem de alvo atingido.
KINDS = {
    "open": "a NEW trade setup is being opened: gives entry price or zone, "
            "stop loss, and targets",
    "close_full": "the whole position is closed or exited now, or the stop "
                  "loss was hit",
    "close_partial": "a profit target was reached and part of the position is "
                     "taken off; reports profit percent already earned",
    "move_sl": "only the stop loss is moved to a new price or to breakeven",
    "increase": "adding more size to an existing position, scaling in, DCA",
    "signal_update": "the plan of an already open trade is changed by an "
                     "instruction",
    "chat": "market commentary, analysis, promotion or member discussion with "
            "no order to act on",
}


def run(corpus_path: str, describe: bool = True) -> None:
    model = GLiNER2.from_pretrained(MODEL)
    labels = KINDS if describe else list(KINDS)
    schema = (
        model.create_schema()
        .classification("kind", labels)
        .classification("direction", ["long", "short", "none"])
        .entities({"symbol": "crypto ticker symbol of the coin being traded"})
    )

    rows = [r for r in json.load(open(corpus_path)) if r.get("text")]
    cm = defaultdict(Counter)
    confs, lat = [], []
    sym_hit = sym_tot = dir_hit = dir_tot = 0

    for r in rows:
        t0 = time.perf_counter()
        out = model.extract(r["text"], schema, include_confidence=True)
        lat.append((time.perf_counter() - t0) * 1000)

        kind = out.get("kind") or {}
        pred = kind.get("label") if isinstance(kind, dict) else None
        cm[r["kind"]][pred] += 1
        confs.append((pred == r["kind"], kind.get("confidence")
                      if isinstance(kind, dict) else None))

        if r.get("direction"):
            dir_tot += 1
            d = out.get("direction") or {}
            if (d.get("label") or "").lower() == r["direction"].lower():
                dir_hit += 1

        if r.get("symbol"):
            sym_tot += 1
            got = (out.get("entities") or {}).get("symbol") or []
            got = [g.get("text", g) if isinstance(g, dict) else g for g in got]
            if any(r["symbol"].upper() in str(g).upper() for g in got):
                sym_hit += 1

    lat.sort()
    print(f"mensagens {len(rows)}   latencia p50={lat[len(lat) // 2]:.0f}ms "
          f"p90={lat[int(len(lat) * 0.9)]:.0f}ms")
    if sym_tot:
        print(f"symbol    {sym_hit}/{sym_tot} = {sym_hit / sym_tot * 100:.1f}%")
    if dir_tot:
        print(f"direction {dir_hit}/{dir_tot} = {dir_hit / dir_tot * 100:.1f}%")

    print("\nkind: Claude (linha) -> encoder (coluna)")
    tot = hit = 0
    for truth in KINDS:
        row = cm.get(truth)
        if not row:
            continue
        n = sum(row.values())
        tot += n
        hit += row.get(truth, 0)
        top = ", ".join(f"{k}={v}" for k, v in row.most_common(3))
        print(f"  {truth:<14} n={n:<4} acerto={row.get(truth, 0):<4} | {top}")
    if tot:
        print(f"\nconcordancia kind: {hit}/{tot} = {hit / tot * 100:.1f}%")

    ok = sorted(c for h, c in confs if h and c is not None)
    bad = sorted(c for h, c in confs if not h and c is not None)
    if ok and bad:
        print(f"confianca  acerto p50={ok[len(ok) // 2]:.2f} n={len(ok)} | "
              f"erro p50={bad[len(bad) // 2]:.2f} n={len(bad)}")
        for th in (0.7, 0.9, 0.95):
            ko = sum(1 for c in ok if c >= th)
            kb = sum(1 for c in bad if c >= th)
            t = ko + kb
            print(f"  gate>={th}: cobertura={t / len(confs) * 100:5.1f}% "
                  f"precisao={ko / t * 100 if t else 0:5.1f}% "
                  f"erros_passando={kb}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run(sys.argv[1], describe="--bare-labels" not in sys.argv)
