"""baseline.py — naive-regex baseline interpreter (SPEC §5/§7).

A deterministic parser that pulls direction/entry/sl/tp/close-X% by regex with NO state
inference and NO causal price-confirm. It cannot distinguish "Closing around be" (close) from
"SL to be" (stop move), cannot do %-of-remaining compounding, and rides the empty-events trap on
the BTC-1609 breakeven case. Used by grade.py to quantify the causal-LLM-vs-regex delta.

Implements the Interpreter protocol (interpret(BoundedPrompt) -> Intent). Imports `interpreter`.
"""

from __future__ import annotations

import re

from interpreter import Intent, Evidence, BoundedPrompt


_RE_SHORT = re.compile(r"\bshort\b", re.I)
_RE_LONG = re.compile(r"\blong\b", re.I)
_RE_CLOSE_PCT = re.compile(r"close\s+(\d+)\s*%", re.I)
_RE_FULL_CLOSE = re.compile(r"\b(full close|close.*fully|fully close)\b", re.I)
_RE_SL = re.compile(r"\bsl\b|\bstop\b|breakeven|\bbe\b", re.I)


class RegexBaselineInterpreter:
    """Stateless, no causal confirmation. The deliberately-dumb comparator."""

    def interpret(self, prompt: BoundedPrompt) -> Intent:
        if not prompt.messages:
            return self._abstain(prompt, "no messages")
        last = prompt.messages[-1]
        text = last["text"]
        mid = last["id"]
        sym = self._guess_symbol(text)

        # naive: a bare "be"/SL token => treat as stop move (the trap WF#1/regex falls into)
        if _RE_FULL_CLOSE.search(text):
            return Intent("close_full", sym, None, "close_full", "regex: full close phrase",
                          "inferred-unconfirmed", 0.3, "regex matched full-close phrase",
                          Evidence([mid], []))
        m = _RE_CLOSE_PCT.search(text)
        if m:
            return Intent("close_partial", sym, None, "close_partial", "regex: close N%",
                          "inferred-unconfirmed", 0.3, f"regex matched close {m.group(1)}%",
                          Evidence([mid], []),
                          close_mode="frac", close_frac=float(m.group(1)) / 100.0)
        # "Closing around be": regex sees 'be'/'breakeven' -> mis-reads as SL move, NOT a close.
        if _RE_SL.search(text):
            return Intent("sl_to", sym, None, "sl_move", "regex: SL/be token -> stop move",
                          "inferred-unconfirmed", 0.3, "regex matched SL/breakeven token (mis-read)",
                          Evidence([mid], []), sl_to="breakeven")
        if _RE_SHORT.search(text) or _RE_LONG.search(text):
            side = "short" if _RE_SHORT.search(text) else "long"
            return Intent("open", sym, side, "open", "regex: opener", "inferred-unconfirmed",
                          0.3, "regex matched a direction word", Evidence([mid], []))
        return self._abstain(prompt, "no regex match")

    @staticmethod
    def _guess_symbol(text: str):
        for sym in ("BTC", "ETH", "SOL", "FARTCOIN", "NEAR", "PUMP", "AAVE", "APT", "TON", "LTC"):
            if re.search(rf"\b{sym}\b", text, re.I):
                return sym
        return None

    def _abstain(self, prompt: BoundedPrompt, why: str) -> Intent:
        mid = prompt.messages[-1]["id"] if prompt.messages else 0
        return Intent("abstain", None, None, "abstain-hold", f"regex: {why}",
                      "commentary-no-position-change", 0.1, why, Evidence([mid], []))
