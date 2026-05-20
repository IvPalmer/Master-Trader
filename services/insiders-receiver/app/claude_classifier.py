"""Claude Code agent classifier — uses Max subscription via `claude` CLI.

NOT the Anthropic API. We spawn `claude -p PROMPT --output-format json
--print` as a subprocess inside the receiver container, which is
authenticated against Palmer's Max subscription via a shared auth volume
(same volume elder-brain-bot uses at /root/.claude).

This file replaces the `ClaudeAgentClassifier` stub in classifier_dispatcher.

Design:
  - Single-shot prompt → JSON output → parsed → returned
  - Hard timeout via subprocess (no Python-side async wait_for race)
  - Gracefully falls back to None on any error (caller uses rule)
  - Prompt includes message text + reply-chain context + current open
    positions so Claude can resolve "close 30%" to a specific position

Container requirements (handled in Dockerfile + compose):
  - `claude` binary in PATH
  - `/root/.claude` mounted from claude-assistant_claude_auth volume
"""
import asyncio
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


# Schema we want Claude to emit. Keep this tight — same as the rule
# classifier's output. Validated downstream by the dispatcher.
CLAUDE_PROMPT_TEMPLATE = """\
You are classifying a Telegram message from a private trading signals group.
The group leader posts trading instructions; we mirror them to a bot.

Return a SINGLE JSON OBJECT, nothing else (no prose, no markdown).
Schema:
  id: int (the msg_id provided)
  kind: one of "open", "close_full", "close_partial", "move_sl",
        "increase", "chat"
  symbol: optional string (e.g. "BTC"). Omit for chat or multi-coin.
  applies_to: optional list of strings for multi-coin actions
  direction: "long" or "short" (required for open)
  entry: optional number or "market"
  entry_range: optional [lo, hi]
  sl: optional number (or "breakeven" for move_sl)
  tp: optional number
  pct: required percent for close_partial (0-100)
  confidence: 0.0-1.0

Strict rules:
  - Bare "stop" / "stopped" / "stop-loss" in narrative text → "chat", NOT close
  - "Got stopped", "stopped out", "fully closed", "close all" → "close_full"
  - "Close 30%", "close half" → "close_partial" with pct
  - "Move SL to X", "stop at breakeven" → "move_sl"
  - Multi-coin headers like "BTC and ETH Shorts" → "open" with applies_to=["BTC","ETH"]
  - Reply messages with just numbers (entry/SL/TP) → "open" detail-fill
    using parent symbol+direction; emit with the symbol/direction filled in

Current OPEN POSITIONS in our book (for resolving management actions):
{positions_json}

Reply chain (immediate parent + ancestors):
{chain_json}

Message to classify:
  msg_id: {msg_id}
  posted_at: {posted_at}
  reply_to_msg_id: {reply_to_msg_id}
  text:
  ----
  {text}
  ----

Emit ONLY the JSON object. No code fences. No prose."""


# Pull the structured JSON object out of Claude's output.
_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _build_prompt(msg_dict: dict, by_id: dict, position_context: list[dict]) -> str:
    """Format the classification prompt."""
    # Trim reply chain to just msg_id + text + posted_at for prompt
    chain = []
    for mid, m in by_id.items():
        if mid == msg_dict.get("id"):
            continue
        chain.append({
            "msg_id": mid,
            "text": (m.get("text") or "")[:200],
            "posted_at": m.get("date"),
            "reply_to": m.get("reply_to_msg_id"),
        })
    return CLAUDE_PROMPT_TEMPLATE.format(
        positions_json=json.dumps(position_context, separators=(",", ":")),
        chain_json=json.dumps(chain, separators=(",", ":")),
        msg_id=msg_dict.get("id"),
        posted_at=msg_dict.get("date"),
        reply_to_msg_id=msg_dict.get("reply_to_msg_id"),
        text=(msg_dict.get("text") or "")[:2000],
    )


async def claude_classify(
    msg_dict: dict, by_id: dict, position_context: list[dict],
    *, timeout_sec: float = 8.0, binary: str = "claude",
    model: Optional[str] = None,
) -> Optional[dict]:
    """Invoke `claude -p` as a subprocess. Returns parsed dict or None.

    None is returned for any of:
      - subprocess timeout
      - non-zero exit
      - JSON parse failure
      - schema validation failure (missing required fields)
    Caller falls back to rule classifier on None.
    """
    prompt = _build_prompt(msg_dict, by_id, position_context)
    cmd = [binary, "-p", prompt, "--output-format", "json", "--print"]
    if model:
        cmd += ["--model", model]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.warning("claude binary not found in PATH (%s) — falling back to rule", binary)
        return None
    except Exception as e:
        logger.warning("claude subprocess spawn failed: %s — falling back", e)
        return None

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        logger.warning("claude classify timed out after %ss for msg %s — killing + falling back",
                       timeout_sec, msg_dict.get("id"))
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return None

    if proc.returncode != 0:
        logger.warning("claude exited %d: %s — falling back",
                       proc.returncode, stderr.decode(errors="ignore")[:500])
        return None

    # `--output-format json` wraps Claude's actual response in a meta envelope.
    # Parse the envelope, then extract the actual classifier JSON from the
    # `result` field.
    raw = stdout.decode(errors="ignore").strip()
    try:
        envelope = json.loads(raw)
        inner_text = envelope.get("result") or envelope.get("content") or raw
    except json.JSONDecodeError:
        # Direct mode — no envelope wrapper
        inner_text = raw

    if isinstance(inner_text, str):
        m = _JSON_RE.search(inner_text)
        if not m:
            logger.warning("claude returned no JSON object for msg %s; raw=%r",
                           msg_dict.get("id"), inner_text[:200])
            return None
        try:
            cls = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            logger.warning("claude JSON parse failed for msg %s: %s; raw=%r",
                           msg_dict.get("id"), e, m.group(0)[:200])
            return None
    elif isinstance(inner_text, dict):
        cls = inner_text
    else:
        logger.warning("claude unexpected result type %s for msg %s",
                       type(inner_text).__name__, msg_dict.get("id"))
        return None

    # Schema validation: must have 'kind'
    if "kind" not in cls:
        logger.warning("claude classification missing 'kind' for msg %s: %r",
                       msg_dict.get("id"), cls)
        return None
    # Ensure id field is set (Claude may omit it)
    cls.setdefault("id", msg_dict.get("id"))
    return cls


# ── Real implementation of the ClaudeAgentClassifier interface ───────────


class ClaudeCliClassifier:
    """Concrete impl that the dispatcher can use in place of the stub."""

    def __init__(self, *, timeout_sec: float = 8.0,
                 binary: str = "claude",
                 model: Optional[str] = None,
                 enabled: bool = True):
        self.timeout_sec = timeout_sec
        self.binary = binary
        self.model = model
        self.enabled = enabled

    async def classify(self, msg_dict: dict, by_id: dict,
                       position_context: list[dict]) -> Optional[dict]:
        if not self.enabled:
            return None
        return await claude_classify(
            msg_dict, by_id, position_context,
            timeout_sec=self.timeout_sec, binary=self.binary, model=self.model,
        )
