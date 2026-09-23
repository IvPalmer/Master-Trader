"""Avalia o classificador de regras contra o corpus de producao — issue #62.

Uso:
    python killers_bot/tools/eval_rules.py corpus.json

`corpus.json` e um dump de
    SELECT c.msg_id, c.kind, r.text
    FROM classifications c JOIN raw_messages r USING(msg_id) ORDER BY c.msg_id;
NAO versione o dump: e conteudo de canal privado.

Reporta cobertura (quanto a regra decide sozinha), concordancia com o Claude
onde decidiu, e a lista de discordancias para adjudicacao manual. Concordancia
aqui e fidelidade ao Claude, nao correcao — as discordancias precisam ser lidas
uma a uma, e no corpus de 2026-09-22 as tres restantes eram erro do Claude.
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rules_classifier import (  # noqa: E402
    classify, declared_target_count, signal_key, signal_symbol,
)


def main(path: str) -> int:
    rows = [r for r in json.load(open(path)) if r.get("text")]

    # Estado: alvos declarados por sinal, construido cronologicamente a partir
    # dos OPENs — exatamente o que o observer teria em producao.
    declared = {}
    for r in rows:
        if r.get("kind") == "open":
            k, n = signal_key(r["text"]), declared_target_count(r["text"])
            if k and n:
                declared[(k, signal_symbol(r["text"]))] = n

    cm = collections.defaultdict(collections.Counter)
    reasons = collections.Counter()
    disagreements = []

    for r in rows:
        # mesma chave de instancia que o observer: SIGNAL ID + simbolo
        key = (signal_key(r["text"]), signal_symbol(r["text"]))
        kind, why = classify(r["text"], declared.get(key) if key[1] else None)
        if kind is None:
            reasons[why] += 1
            cm[r["kind"]]["<CLAUDE>"] += 1
            continue
        cm[r["kind"]][kind] += 1
        if kind != r["kind"]:
            disagreements.append((r["msg_id"], r["kind"], kind, why))

    total = sum(sum(v.values()) for v in cm.values())
    fallback = sum(v["<CLAUDE>"] for v in cm.values())
    decided = total - fallback
    agreed = sum(v[k] for k, v in cm.items())

    print(f"corpus {total} | regra decidiu {decided} ({decided / total * 100:.1f}%) "
          f"| Claude {fallback} ({fallback / total * 100:.1f}%)")
    if decided:
        print(f"concordancia onde decidiu: {agreed}/{decided} "
              f"= {agreed / decided * 100:.2f}%\n")
    for truth, row in cm.items():
        got = ", ".join(f"{a}={b}" for a, b in row.most_common())
        print(f"{truth:<14} n={sum(row.values()):<4} | {got}")
    print(f"\nmotivos de fallback: {dict(reasons)}")
    print(f"\ndiscordancias ({len(disagreements)}) — adjudique uma a uma:")
    for d in disagreements:
        print("  ", d)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
