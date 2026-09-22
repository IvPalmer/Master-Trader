"""Extrai mensagens de um export HTML do Telegram Desktop (#62).

O corpus vivo em `classifications` cobre apenas a janela desde que o observer
subiu. O export do canal cobre o historico inteiro, e foi ele que revelou que
as regras so valiam para o formato recente: a cobertura caia de 89,6% para
69,6% quando medida contra 2024.

Uso:
    python killers_bot/tools/parse_telegram_export.py "<dir>/messages*.html" saida.json

A saida e uma lista `[{"id": int, "text": str}]`, pronta para
`tools/eval_rules.py` (que ignora a ausencia de `kind`) ou para uma medicao
de cobertura sem rotulo.

NAO versione a saida: e conteudo de canal privado.
"""
import glob
import html
import json
import re
import sys
from html.parser import HTMLParser

# Tags vazias: nao abrem escopo. Contar `<br>` como aninhamento faz a
# profundidade so crescer e o bloco de texto nunca fecha.
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}


class _Export(HTMLParser):
    def __init__(self):
        super().__init__()
        self.msgs = []
        self.cur = None
        self.in_text = False
        self.depth = 0
        self.buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "div" and "message" in classes and a.get("id", "").startswith("message"):
            self.cur = int(re.sub(r"\D", "", a["id"]) or 0)
        if tag == "div" and "text" in classes and self.cur is not None and not self.in_text:
            self.in_text, self.depth, self.buf = True, 0, []
            return
        if self.in_text:
            if tag in VOID:
                if tag == "br":
                    self.buf.append("\n")
                return
            self.depth += 1

    def handle_endtag(self, tag):
        if not self.in_text:
            return
        if self.depth == 0 and tag == "div":
            text = html.unescape("".join(self.buf)).strip()
            if self.cur is not None and text:
                self.msgs.append({"id": self.cur, "text": text})
            self.in_text = False
        else:
            self.depth -= 1

    def handle_data(self, data):
        if self.in_text:
            self.buf.append(data)


def parse(pattern: str) -> list:
    out = []
    for path in sorted(glob.glob(pattern)):
        p = _Export()
        p.feed(open(path, encoding="utf-8", errors="replace").read())
        out += p.msgs
    seen, uniq = set(), []
    for m in out:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        uniq.append(m)
    uniq.sort(key=lambda m: m["id"])
    return uniq


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    msgs = parse(sys.argv[1])
    json.dump(msgs, open(sys.argv[2], "w"), ensure_ascii=False)
    span = f"{msgs[0]['id']}..{msgs[-1]['id']}" if msgs else "vazio"
    print(f"mensagens extraidas: {len(msgs)}  (ids {span})")
