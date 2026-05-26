"""Classifier dispatcher — split codex's "regex fast-path + Claude for rest."

Hot path for complete-open signals: deterministic rule classifier (sub-50ms).
Cold path for everything else (close, move_sl, increase, multi-coin, replies,
ambiguous chatter): Claude agent classification via Max subscription.

Hard timeout + deterministic fallback: if Claude is slow or unavailable,
fall back to rule classifier for everything. Log the fallback aggressively.

This module does NOT execute anything — it returns a structured event the
receiver then routes through sanity bands + position graph + freqtrade.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Strict-rule open detector ────────────────────────────────────────────

# Allowlist: only fast-path messages where ALL of these are present in the
# same message and unambiguous. Anything else falls to the Claude/rule
# management classifier.
STRICT_OPEN_REQUIRED = {"symbol", "direction", "sl"}
STRICT_OPEN_FORBIDDEN_FLAGS = {"applies_to"}  # multi-coin headers excluded


_VALID_DIRECTIONS = {"long", "short", "LONG", "SHORT"}


def is_strict_open(classification: dict) -> bool:
    """True if classification looks like a clean single-coin open with all
    the fields needed to fast-path.

    Tight: type + value checks on every actionable field. A bug-shaped
    classification (e.g. rule mis-parse `entry=77100` for ETH SHORT) MUST
    fall through to Claude rather than fast-path into sizing.
    """
    if classification.get("kind") != "open":
        return False
    if any(f in classification for f in STRICT_OPEN_FORBIDDEN_FLAGS):
        return False
    if not all(k in classification for k in STRICT_OPEN_REQUIRED):
        return False

    # symbol must be a non-empty string, not a known classifier-bug sentinel
    sym = classification.get("symbol")
    if not sym or not isinstance(sym, str) or sym in {"CLOSE", "MNT"}:
        return False

    # direction must be one of the canonical strings
    direction = classification.get("direction")
    if direction not in _VALID_DIRECTIONS:
        return False

    # sl must be a positive number
    sl = classification.get("sl")
    if not isinstance(sl, (int, float)) or isinstance(sl, bool) or sl <= 0:
        return False

    # entry: either single positive number, or entry_range of two positive numbers
    entry = classification.get("entry")
    entry_range = classification.get("entry_range")
    if entry is not None:
        if not isinstance(entry, (int, float)) or isinstance(entry, bool) or entry <= 0:
            return False
        ref_entry = float(entry)
    elif entry_range is not None:
        if (not isinstance(entry_range, (list, tuple))
                or len(entry_range) != 2):
            return False
        e0, e1 = entry_range
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0
                   for x in (e0, e1)):
            return False
        ref_entry = (float(e0) + float(e1)) / 2.0
    else:
        return False

    # SL must be on the correct side of entry for the direction
    direction_lc = direction.lower()
    if direction_lc == "long" and sl >= ref_entry:
        return False
    if direction_lc == "short" and sl <= ref_entry:
        return False

    return True


# ── Rule classifier wrapper ──────────────────────────────────────────────

# Reuses the curated `classifier.py` from the master-trader repo. Imports
# are deferred so this module can run in environments where the master-
# trader code isn't on the path.

_rule_classifier_module = None


def _load_rule_classifier():
    global _rule_classifier_module
    if _rule_classifier_module is None:
        import importlib.util
        path = Path("/app/insiders_bridge/classifier.py")
        if not path.exists():
            # Dev fallback — running from the master-trader repo directly
            path = Path(__file__).resolve().parents[3] / "ft_userdata" / "insiders_bridge" / "classifier.py"
        if not path.exists():
            raise SystemExit(f"rule classifier not found at {path}")
        spec = importlib.util.spec_from_file_location("rule_classifier", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _rule_classifier_module = mod
    return _rule_classifier_module


def classify_rule(msg_dict: dict, by_id: dict[int, dict]) -> dict:
    """Run the rule classifier on a single message. msg_dict matches the
    Telegram message shape from the listener.

    by_id is a lookup of {msg_id: msg_dict} for reply-chain resolution.
    """
    rc = _load_rule_classifier()
    return rc.classify(msg_dict, by_id)


# ── Claude agent classifier (stub for now) ────────────────────────────────

# TODO: integrate with Claude Code agent runtime (subscription, not API).
# The elder-brain-bot pattern on the VPS is the reference. Until that's
# wired, this stub returns None and the dispatcher falls back to rule
# classification for ALL messages. That's fine for initial scaffolding
# and dry-run shakedown.


class ClaudeAgentClassifier:
    """Stub — returns None until real agent integration lands."""

    def __init__(self, timeout_sec: float = 5.0):
        self.timeout_sec = timeout_sec
        self.enabled = False  # flip to True when agent wiring lands

    async def classify(self, msg_dict: dict, by_id: dict[int, dict],
                       position_context: list[dict]) -> Optional[dict]:
        """Returns None on stub. When integrated, returns same schema as
        the rule classifier but with Claude's reasoning over the position
        graph context.

        `position_context` is a list of open-position dicts from the graph,
        so the agent can resolve "close 30%" to a specific position.
        """
        if not self.enabled:
            return None
        # TODO: invoke Claude Code agent, parse JSON, validate schema
        raise NotImplementedError("Claude agent integration pending")


# ── Dispatcher ───────────────────────────────────────────────────────────


@dataclass
class ClassificationResult:
    classification: dict
    classifier_used: str       # 'rule-fast-open' | 'rule' | 'claude' | 'rule-fallback'
    rule_classification: Optional[dict] = None   # for shadow comparison
    claude_classification: Optional[dict] = None
    elapsed_ms: float = 0.0
    disagreement: bool = False


async def classify(
    msg_dict: dict,
    by_id: dict[int, dict],
    position_context: list[dict],
    claude: ClaudeAgentClassifier,
) -> ClassificationResult:
    """Main entry. Routes to fast-path or full classification.

    Strategy:
      1. Always compute rule classification (cheap, ~10ms).
      2. If rule says STRICT OPEN → fast-path. Claude validates in shadow
         (log disagreement, don't override).
      3. Otherwise → ask Claude. On timeout/error, fall back to rule.
    """
    t0 = time.time()

    rule_cls = classify_rule(msg_dict, by_id)

    if is_strict_open(rule_cls):
        # FAST-PATH: rule open is clean enough to act on. Claude shadow
        # validates in parallel (logs only — codex: do not forceexit on
        # disagreement).
        if claude.enabled:
            try:
                claude_cls = await asyncio.wait_for(
                    claude.classify(msg_dict, by_id, position_context),
                    timeout=claude.timeout_sec,
                )
                disagreement = False
                if claude_cls:
                    disagreement = (
                        claude_cls.get("kind") != rule_cls.get("kind")
                        or claude_cls.get("symbol") != rule_cls.get("symbol")
                        or claude_cls.get("direction") != rule_cls.get("direction")
                    )
                    if disagreement:
                        logger.warning(
                            "FAST-PATH SHADOW DISAGREE msg=%s rule=%s claude=%s — fast-path proceeds (log only)",
                            msg_dict.get("id"), rule_cls.get("kind"),
                            claude_cls.get("kind"),
                        )
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning("claude shadow failed for msg %s: %s",
                               msg_dict.get("id"), e)
                claude_cls = None
                disagreement = False
        else:
            claude_cls = None
            disagreement = False

        return ClassificationResult(
            classification=rule_cls,
            classifier_used="rule-fast-open",
            rule_classification=rule_cls,
            claude_classification=claude_cls,
            elapsed_ms=(time.time() - t0) * 1000,
            disagreement=disagreement,
        )

    # COLD PATH: not a strict-open. Use Claude for the nuanced semantics.
    if claude.enabled:
        try:
            claude_cls = await asyncio.wait_for(
                claude.classify(msg_dict, by_id, position_context),
                timeout=claude.timeout_sec,
            )
            if claude_cls:
                return ClassificationResult(
                    classification=claude_cls,
                    classifier_used="claude",
                    rule_classification=rule_cls,
                    claude_classification=claude_cls,
                    elapsed_ms=(time.time() - t0) * 1000,
                    disagreement=(
                        claude_cls.get("kind") != rule_cls.get("kind")
                        or claude_cls.get("symbol") != rule_cls.get("symbol")
                    ),
                )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("claude cold-path failed for msg %s: %s, falling back to rule",
                           msg_dict.get("id"), e)

    # Fallback: use rule even for non-strict-open. Codex called this out
    # as the dominant failure path for missed closes. Log loudly.
    if rule_cls.get("kind") not in ("open", "chat"):
        logger.warning(
            "RULE FALLBACK on non-open msg %s kind=%s — Claude unavailable, rule may miss this",
            msg_dict.get("id"), rule_cls.get("kind"),
        )

    return ClassificationResult(
        classification=rule_cls,
        classifier_used="rule-fallback",
        rule_classification=rule_cls,
        elapsed_ms=(time.time() - t0) * 1000,
    )
