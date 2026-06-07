"""Claude CLI classifier for Binance Killers VIP signals.

Uses the Claude Max subscription via the `claude` CLI subprocess (NOT
the Anthropic API — user has Claude Max, not API billing).

Same prompt that was validated offline on 3,378 Killers messages
(see killers_analyzer.py results).
"""
import asyncio
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """\
You are classifying ONE Telegram message from the "Binance Killers VIP" trading signals channel. Return a SINGLE JSON OBJECT — no prose, no markdown, no code fences.

Schema (all fields required, use null where not applicable):
  id          : int — the msg_id below
  kind        : one of "open" | "close_full" | "close_partial" | "move_sl" | "increase" | "chat"
  signal_id   : int|null — extract from #NNNN whenever it appears in the text
  symbol      : str|null — e.g. "BTC", "ETH", "ZRX" (strip $ prefix and /USDT suffix)
  direction   : "long"|"short"|null
  entry       : number|"market"|null
  entry_range : [lo,hi]|null
  sl          : number|"breakeven"|null
  tp          : number|null
  pct         : number|null — for close_partial only, the % closed
  applies_to  : list|null — for multi-coin actions
  confidence  : number — 0.0 to 1.0
  notes       : str — free text (target hits, realized %, etc)

FORMAT — Binance Killers VIP

Signal ID format: `📍SIGNAL ID: #NNNN📍`

OPEN message (full setup):
  📍SIGNAL ID: #1453📍 | COIN: $ZRX/USDT (3-5x) | Direction: LONG📈
  ENTRY: 0.43 - 0.525
  OTE: 0.49
  TARGETS / Short Term: ... / Mid Term: ...
  STOP LOSS: 0.3823
  → kind="open", signal_id=1453, symbol="ZRX", direction="long",
    entry_range=[0.43, 0.525], sl=0.3823, tp=null, notes with targets.

CLOSE / TARGET-HIT update (cumulative):
  📍SIGNAL ID: #1453📍 | Target 1: 0.531✅ | 🔥15.85% Profit (5x)🔥
  → kind="close_partial", signal_id=1453, symbol="ZRX",
    pct=null, notes="2 targets hit, 15.85% gain at 5x".

`close_full` only for:
  - bare `CLOSE` (resolve symbol from context if possible; signal_id=null)
  - `stop loss hit` / `Stop Loss Triggered` (close_full, signal_id from context)
  - explicit final-closure language

Other:
  - `VIP MARKET/TRADES UPDATE`, `VIP UPDATE: $X` with commentary → chat.
    EXCEPTION: explicit "move stop loss to breakeven" → move_sl, sl="breakeven".
  - `IMPORTANT` boilerplate, `$BTC.D` dominance, `NEW` without entry → chat.

Reply chain (for resolving ambiguous management actions):
{chain_json}

Message to classify:
  msg_id: {msg_id}
  posted_at: {posted_at}
  reply_to_msg_id: {reply_to_msg_id}
  text:
  ----
  {text}
  ----

Emit ONLY the JSON object. No prose. No markdown."""


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def build_prompt(msg: dict, reply_chain: list[dict]) -> str:
    chain = [{
        "msg_id": m.get("id"),
        "text": (m.get("text") or "")[:200],
        "posted_at": str(m.get("date")) if m.get("date") else None,
    } for m in reply_chain]
    return PROMPT_TEMPLATE.format(
        chain_json=json.dumps(chain, separators=(",", ":")),
        msg_id=msg.get("id"),
        posted_at=str(msg.get("date")) if msg.get("date") else None,
        reply_to_msg_id=msg.get("reply_to_msg_id"),
        text=(msg.get("text") or msg.get("message") or "")[:2000],
    )


async def classify(
    msg: dict,
    reply_chain: list[dict],
    *,
    binary: str = "claude",
    model: Optional[str] = None,
    timeout_sec: float = 10.0,
) -> Optional[dict]:
    """Spawn `claude -p PROMPT --output-format json --print` subprocess.

    `binary` may be a single executable name OR a multi-word command
    prefix (e.g. "docker exec elder-brain-bot claude"). It is split on
    whitespace so we can sandwich the call through `docker exec` without
    shell injection.

    Returns parsed classification dict, or None on timeout / parse failure.
    Caller should treat None as "couldn't classify; log + skip".
    """
    prompt = build_prompt(msg, reply_chain)
    cmd = binary.split() + ["-p", prompt, "--output-format", "json", "--print"]
    if model:
        cmd += ["--model", model]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("classify timeout msg=%s after %.1fs", msg.get("id"), timeout_sec)
            return None
    except FileNotFoundError:
        logger.error("classify: `%s` binary not found in PATH", binary)
        return None

    if proc.returncode != 0:
        logger.warning("classify nonzero exit msg=%s rc=%d stderr=%s",
                       msg.get("id"), proc.returncode, stderr.decode()[:400])
        return None

    raw = stdout.decode()
    # Claude CLI with --output-format json wraps the actual response in a meta envelope.
    try:
        envelope = json.loads(raw)
        response_text = envelope.get("result") or envelope.get("response") or raw
    except json.JSONDecodeError:
        response_text = raw

    # Extract the inner JSON object
    m = _JSON_RE.search(response_text)
    if not m:
        logger.warning("classify: no JSON in response msg=%s response=%s",
                       msg.get("id"), response_text[:400])
        return None
    try:
        result = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("classify: JSON parse error msg=%s err=%s", msg.get("id"), e)
        return None

    # Sanity-check required fields
    if "kind" not in result:
        logger.warning("classify: missing 'kind' msg=%s", msg.get("id"))
        return None
    result["id"] = msg.get("id")
    return result
