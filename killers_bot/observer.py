"""Main orchestrator: Telethon listener → classifier → paper simulator → log.

No exchange connection. No real orders. Observe-only.

Run via the Docker entrypoint, or locally:
  python3 -m killers_bot.observer
"""
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import classifier, simulator, strict_open

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────


def _load_dotenv():
    """Load killers_bot/.env into os.environ if present.

    Hand-rolled (no python-dotenv dep) to keep the image minimal. Strips
    surrounding double-quotes so multi-word values like
    `KILLERS_CLAUDE_BINARY="docker exec elder-brain-bot claude"` round-trip.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


class Config:
    def __init__(self):
        _load_dotenv()
        self.api_id = int(_required("KILLERS_TG_API_ID"))
        self.api_hash = _required("KILLERS_TG_API_HASH")
        self.session_path = _required("KILLERS_TG_SESSION")
        self.channel_username = os.getenv(
            "KILLERS_TG_CHANNEL_USERNAME", "BinanceKillers_FreeSignal"
        )
        self.channel_id_override = os.getenv("KILLERS_TG_CHANNEL_ID")
        self.db_path = os.getenv("KILLERS_DB", "/var/lib/killers/state.sqlite")
        self.claude_binary = os.getenv("KILLERS_CLAUDE_BINARY", "claude")
        self.claude_model = os.getenv("KILLERS_CLAUDE_MODEL") or None
        self.claude_timeout = float(os.getenv("KILLERS_CLAUDE_TIMEOUT_SEC", "12"))
        self.heartbeat_sec = int(os.getenv("KILLERS_HEARTBEAT_SEC", "60"))
        # Receiver endpoint — when set, observer POSTs each classification.
        # Receiver translates to Freqtrade Futures REST. Leave unset to run
        # in pure observe-mode (Phase 1).
        self.receiver_url = os.getenv("KILLERS_RECEIVER_URL", "")


def _required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise SystemExit(f"missing required env var: {name}")
    return val


# ── DB ─────────────────────────────────────────────────────────────────────


def init_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).parent / "schema.sql").read_text()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    return conn


def last_msg_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT MAX(msg_id) FROM raw_messages").fetchone()
    return row[0] if row and row[0] else None


def persist_raw(conn: sqlite3.Connection, msg: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO raw_messages "
        "(msg_id, received_at, posted_at, edited_at, reply_to_msg_id, text, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            msg["id"],
            datetime.now(timezone.utc).isoformat(),
            str(msg.get("date")) if msg.get("date") else None,
            str(msg.get("edit_date")) if msg.get("edit_date") else None,
            msg.get("reply_to_msg_id"),
            msg.get("message") or msg.get("text"),
            json.dumps(msg, default=str),
        ),
    )
    conn.commit()


def persist_classification(conn: sqlite3.Connection, classification: dict) -> None:
    entry_range = classification.get("entry_range") or [None, None]
    if not isinstance(entry_range, list) or len(entry_range) != 2:
        entry_range = [None, None]
    sl_val = classification.get("sl")
    sl_num = sl_val if isinstance(sl_val, (int, float)) else None
    sl_str = sl_val if isinstance(sl_val, str) else None

    conn.execute(
        "INSERT OR REPLACE INTO classifications "
        "(msg_id, classified_at, kind, signal_id, symbol, direction, "
        " entry_lo, entry_hi, sl, sl_str, tp, pct, confidence, notes, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            classification["id"],
            datetime.now(timezone.utc).isoformat(),
            classification.get("kind"),
            classification.get("signal_id"),
            classification.get("symbol"),
            classification.get("direction"),
            entry_range[0], entry_range[1],
            sl_num, sl_str,
            classification.get("tp"),
            classification.get("pct"),
            classification.get("confidence"),
            (classification.get("notes") or "")[:1000],
            json.dumps(classification, default=str),
        ),
    )
    conn.commit()


# ── Reply chain (small, in-memory cache + DB fallback) ─────────────────────


async def build_reply_chain(client, channel_id, conn, msg_dict: dict, depth: int = 3) -> list[dict]:
    chain = []
    current = msg_dict
    for _ in range(depth):
        parent_id = current.get("reply_to_msg_id")
        if not parent_id:
            break
        row = conn.execute(
            "SELECT msg_id, posted_at, reply_to_msg_id, text FROM raw_messages WHERE msg_id = ?",
            (parent_id,),
        ).fetchone()
        if row:
            current = {"id": row["msg_id"], "date": row["posted_at"],
                       "reply_to_msg_id": row["reply_to_msg_id"], "text": row["text"] or ""}
        else:
            try:
                msg = await client.get_messages(channel_id, ids=parent_id)
                if msg is None:
                    break
                d = msg.to_dict() if hasattr(msg, "to_dict") else dict(msg)
                persist_raw(conn, d)
                current = {"id": d.get("id"), "date": str(d.get("date")),
                           "reply_to_msg_id": d.get("reply_to_msg_id"),
                           "text": d.get("message") or d.get("text") or ""}
            except Exception as e:
                logger.warning("reply chain fetch failed parent=%d: %s", parent_id, e)
                break
        chain.append(current)
    return chain


# ── Process one message end-to-end ─────────────────────────────────────────


async def process_message(client, channel_id, conn, config, msg_dict: dict, source: str) -> None:
    # Telethon's to_dict() puts message content in the 'message' key, not 'text'.
    # Mirror it onto 'text' for downstream callers (classifier prompt, snippet).
    if not msg_dict.get("text") and msg_dict.get("message"):
        msg_dict["text"] = msg_dict["message"]
    persist_raw(conn, msg_dict)
    snippet = (msg_dict.get("text") or "")[:80].replace("\n", " ⏎ ")
    logger.info("[MSG %s] id=%d %r", source.upper(), msg_dict["id"], snippet)

    chain = await build_reply_chain(client, channel_id, conn, msg_dict)

    # FAST-PATH: try the rule parser first. Saves ~7s of Claude latency on
    # clean OPEN signals. Strict checks inside the parser reject anything
    # that isn't a complete single-coin open. Claude still runs in shadow
    # after the receiver POST so any disagreement is visible.
    text = msg_dict.get("text") or msg_dict.get("message") or ""
    classification = strict_open.is_strict_killers_open(text, msg_dict["id"])
    used_fast_path = classification is not None
    if used_fast_path:
        logger.info(
            "[FAST-PATH] id=%d kind=open signal=#%s sym=%s — bypassing Claude",
            msg_dict["id"], classification["signal_id"], classification["symbol"],
        )
    else:
        classification = await classifier.classify(
            msg_dict, chain,
            binary=config.claude_binary,
            model=config.claude_model,
            timeout_sec=config.claude_timeout,
        )
    if classification is None:
        logger.warning("[CLASSIFY FAIL] id=%d skipping downstream", msg_dict["id"])
        return

    persist_classification(conn, classification)
    kind = classification.get("kind")
    sym = classification.get("symbol")
    sid = classification.get("signal_id")
    conf = classification.get("confidence", 0)
    logger.info("[CLASSIFY] id=%d kind=%s signal=#%s sym=%s conf=%.2f source=%s",
                msg_dict["id"], kind, sid, sym, conf,
                "rule" if used_fast_path else "claude")

    # Route into paper simulator (local audit trail)
    if kind == "open":
        simulator.open_paper_position(conn, msg_dict, classification)
    elif kind in ("close_partial", "close_full", "move_sl"):
        simulator.update_paper_position(conn, msg_dict, classification)
    elif kind == "increase":
        logger.info("[INCREASE] not modeled in paper sim yet")
    # else: chat — already logged via [CLASSIFY], nothing to do

    # Forward to receiver for real Freqtrade Futures dry-run execution.
    # Receiver is the source of truth for actual trades; paper sim stays
    # for audit + offline comparison.
    if config.receiver_url:
        await _post_to_receiver(config.receiver_url, msg_dict, classification)

    # Shadow Claude after the fast-path decision is already in flight. Logs
    # disagreement but never blocks the receiver POST. Skip if Claude was
    # already the primary classifier (no shadow needed).
    if used_fast_path:
        asyncio.create_task(
            _shadow_classify(msg_dict, chain, classification, config),
            name=f"shadow-classify-{msg_dict['id']}",
        )


async def _shadow_classify(msg_dict: dict, chain: list, fast_path: dict,
                           config) -> None:
    """Run Claude in the background after a fast-path open, log any
    disagreement. Best-effort — never raises out of the task."""
    try:
        cls = await classifier.classify(
            msg_dict, chain,
            binary=config.claude_binary,
            model=config.claude_model,
            timeout_sec=config.claude_timeout,
        )
        if cls is None:
            return
        # Compare critical fields. Disagreement = different kind, symbol,
        # direction, or sl off by >0.5%.
        disagree_fields: list[str] = []
        for f in ("kind", "symbol", "direction"):
            if cls.get(f) != fast_path.get(f):
                disagree_fields.append(f)
        fp_sl = fast_path.get("sl")
        cl_sl = cls.get("sl")
        if (isinstance(fp_sl, (int, float)) and isinstance(cl_sl, (int, float))
                and fp_sl > 0 and abs(fp_sl - cl_sl) / fp_sl > 0.005):
            disagree_fields.append("sl")
        if disagree_fields:
            logger.warning(
                "[FAST-PATH DISAGREE] id=%d fields=%s rule=%s claude=%s — "
                "fast-path already committed (audit only)",
                msg_dict.get("id"), disagree_fields,
                {f: fast_path.get(f) for f in disagree_fields},
                {f: cls.get(f) for f in disagree_fields},
            )
    except Exception as e:
        logger.warning("shadow classify failed id=%d: %s",
                       msg_dict.get("id"), e)


async def _post_to_receiver(url: str, msg: dict, classification: dict) -> None:
    """POST classified event to killers-receiver. Best-effort, never blocks.

    Telethon's to_dict() leaves datetime objects + bytes inline; pre-serialize
    via json.dumps(default=str) and post as raw data so aiohttp doesn't trip
    on its own json encoder.
    """
    import aiohttp
    payload = {"msg": msg, "classification": classification}
    try:
        body_json = json.dumps(payload, default=str)
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=body_json,
                              headers={"Content-Type": "application/json"},
                              timeout=aiohttp.ClientTimeout(total=8)) as r:
                body = await r.text()
                logger.info("[RECV] %d msg_id=%d kind=%s body=%s",
                            r.status, msg.get("id"), classification.get("kind"),
                            body[:200])
    except Exception as e:
        logger.warning("[RECV] post failed msg_id=%d: %s", msg.get("id"), e)


# ── Main loop ──────────────────────────────────────────────────────────────


async def run(config: Config, conn: sqlite3.Connection) -> None:
    from telethon import TelegramClient, events

    client = TelegramClient(config.session_path, config.api_id, config.api_hash)
    await client.start()
    me = await client.get_me()
    logger.info("auth OK as %s (id=%d phone=%s)", me.first_name, me.id, getattr(me, "phone", "?"))

    # Resolve channel
    if config.channel_id_override:
        channel = int(config.channel_id_override)
    else:
        ent = await client.get_entity(config.channel_username)
        channel = ent.id
        logger.info("resolved channel @%s → id=%d title=%r",
                    config.channel_username, channel, getattr(ent, "title", "?"))

    # Backfill on startup
    last_id = last_msg_id(conn)
    if last_id:
        logger.info("backfilling msgs > %d (last seen)", last_id)
        async for msg in client.iter_messages(channel, min_id=last_id, limit=100):
            d = msg.to_dict()
            await process_message(client, channel, conn, config, d, source="backfill")

    @client.on(events.NewMessage(chats=[channel]))
    async def _on_new(event):
        d = event.message.to_dict()
        await process_message(client, channel, conn, config, d, source="new")

    @client.on(events.MessageEdited(chats=[channel]))
    async def _on_edit(event):
        d = event.message.to_dict()
        await process_message(client, channel, conn, config, d, source="edited")

    # Heartbeat
    async def heartbeat():
        while True:
            try:
                await asyncio.wait_for(client.get_me(), timeout=5.0)
                logger.info("[HB] alive — last_msg_id=%s", last_msg_id(conn))
            except Exception as e:
                logger.error("[HB] auth check failed: %s", e)
            await asyncio.sleep(config.heartbeat_sec)

    hb = asyncio.create_task(heartbeat())
    try:
        await client.run_until_disconnected()
    finally:
        hb.cancel()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )
    config = Config()
    conn = init_db(config.db_path)
    asyncio.run(run(config, conn))


if __name__ == "__main__":
    main()
