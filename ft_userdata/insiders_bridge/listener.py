"""Telethon listener — ingests Telegram channel messages, persists raw msg
to event store, hands off to receiver for classification + execution.

Phase 1: piggybacks on Eduardo's user session (he's a group member; we're
not in the group directly). Phase 2: switch to our own session via the
same env var, drop the Eduardo-hop.

Multi-deployment design: ALL account-specific config via env vars so the
same image can be run for our deployment and (later) Eduardo's own.

Env vars (all required unless marked optional):
  INSIDERS_TG_API_ID      — Telethon API ID
  INSIDERS_TG_API_HASH    — Telethon API hash
  INSIDERS_TG_SESSION     — path to .session file (mounted as secret)
  INSIDERS_TG_CHANNEL_ID  — Telegram channel/group id (negative for supergroup)
  INSIDERS_RECEIVER_URL   — receiver POST endpoint (default http://insiders-receiver:8089/event)
  INSIDERS_EVENT_STORE    — sqlite path for raw event persistence
  INSIDERS_HEARTBEAT_SEC  — heartbeat interval (default 60)
  INSIDERS_INSTANCE_ID    — tag for logs/alerts/orders (e.g. "palmer-prod", "eduardo")
  INSIDERS_DEDUPE_SQL     — sqlite path for msg_id dedupe cursor (default same as event store)

NOT in env: rate limiting, classifier choice — those live in the receiver.

Design notes:
  - Two-part thread buffer: header messages without entry/SL/TP buffered
    ~8s before emit, to merge with reply that carries numbers. Bypassed
    when message is complete (has all of symbol+side+entry+SL+TP).
  - Edits: events.MessageEdited triggers a 'edit' kind event. Receiver
    decides whether to re-process or ignore.
  - On startup: iter_messages(min_id=last_id, limit=200) backfills any
    outage gap.
  - Session loss: pause new entries (signal to receiver), keep position
    management via exchange-side SL/TP. Alert immediately.
  - Persist EVERY raw msg before forwarding — never lose evidence.

Run:
  python3 -m insiders_bridge.listener
"""
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise SystemExit(f"missing required env var: {name}")
    return val


class Config:
    def __init__(self):
        self.api_id = int(_required_env("INSIDERS_TG_API_ID"))
        self.api_hash = _required_env("INSIDERS_TG_API_HASH")
        self.session_path = _required_env("INSIDERS_TG_SESSION")
        self.channel_id = int(_required_env("INSIDERS_TG_CHANNEL_ID"))
        self.receiver_url = os.getenv(
            "INSIDERS_RECEIVER_URL", "http://insiders-receiver:8089/event"
        )
        self.event_store = os.getenv(
            "INSIDERS_EVENT_STORE", "/var/lib/insiders/events.sqlite"
        )
        self.heartbeat_sec = int(os.getenv("INSIDERS_HEARTBEAT_SEC", "60"))
        self.instance_id = os.getenv("INSIDERS_INSTANCE_ID", "unknown")
        self.dedupe_sql = os.getenv("INSIDERS_DEDUPE_SQL", self.event_store)


# ── Event store: persistent audit spine ───────────────────────────────────
# Every raw Telegram message lands here BEFORE any forwarding. Codex's
# "core product" insight: the message stream + position graph is the actual
# state. Treat it as first-class, not as a log file.

EVENT_STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    msg_id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    posted_at TEXT,
    edited_at TEXT,
    reply_to_msg_id INTEGER,
    sender_id INTEGER,
    text TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forwards (
    msg_id INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    attempted_at TEXT NOT NULL,
    status_code INTEGER,
    response_text TEXT,
    PRIMARY KEY (msg_id, attempt)
);
CREATE TABLE IF NOT EXISTS heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_seen_at TEXT NOT NULL,
    last_msg_id INTEGER
);
"""


def init_event_store(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript(EVENT_STORE_SCHEMA)
    return conn


def persist_raw(conn: sqlite3.Connection, msg) -> None:
    """Persist a Telethon message dict to raw_messages. Idempotent."""
    raw = json.dumps(msg, default=str)
    conn.execute(
        "INSERT OR REPLACE INTO raw_messages "
        "(msg_id, received_at, posted_at, edited_at, reply_to_msg_id, "
        " sender_id, text, raw_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            msg["id"],
            datetime.now(timezone.utc).isoformat(),
            msg.get("date"),
            msg.get("edit_date"),
            msg.get("reply_to_msg_id"),
            msg.get("sender_id"),
            msg.get("text"),
            raw,
        ),
    )


def last_msg_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT MAX(msg_id) FROM raw_messages").fetchone()
    return row[0] if row and row[0] else None


# ── Main loop scaffold (Telethon import deferred) ──────────────────────────
# Telethon isn't imported at module load so this file can be linted/unit-
# tested without the lib installed. Real connection happens in main().


async def run(config: Config, conn: sqlite3.Connection) -> None:
    try:
        from telethon import TelegramClient, events  # noqa: F401
    except ImportError:
        raise SystemExit(
            "telethon not installed. Container image must include it. "
            "Run `pip install telethon` inside the listener image."
        )

    client = TelegramClient(config.session_path, config.api_id, config.api_hash)
    await client.start()
    me = await client.get_me()
    logger.info(
        "instance=%s listener up. user_id=%s phone=%s channel=%s",
        config.instance_id, me.id, getattr(me, "phone", "?"), config.channel_id,
    )

    # Backfill outage gap on startup
    last_id = last_msg_id(conn)
    if last_id:
        logger.info("backfilling from msg_id > %d (last seen)", last_id)
        async for msg in client.iter_messages(config.channel_id, min_id=last_id, limit=200):
            await _ingest(client, conn, config, msg, source="backfill")

    @client.on(events.NewMessage(chats=[config.channel_id]))
    async def on_new(event):
        await _ingest(client, conn, config, event.message, source="new")

    @client.on(events.MessageEdited(chats=[config.channel_id]))
    async def on_edited(event):
        await _ingest(client, conn, config, event.message, source="edited")

    # Heartbeat task
    async def heartbeat():
        while True:
            conn.execute(
                "INSERT OR REPLACE INTO heartbeat (id, last_seen_at, last_msg_id) "
                "VALUES (1, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), last_msg_id(conn)),
            )
            await asyncio.sleep(config.heartbeat_sec)

    hb_task = asyncio.create_task(heartbeat())
    try:
        await client.run_until_disconnected()
    finally:
        hb_task.cancel()
        with suppress(asyncio.CancelledError):
            await hb_task


async def _ingest(client, conn, config, msg, source: str) -> None:
    """Persist + forward a single message."""
    d = msg.to_dict() if hasattr(msg, "to_dict") else dict(msg)
    persist_raw(conn, d)
    logger.info(
        "instance=%s source=%s msg_id=%s reply_to=%s text=%r",
        config.instance_id, source, d.get("id"), d.get("reply_to_msg_id"),
        (d.get("message") or d.get("text") or "")[:80],
    )
    # Forward to receiver. Build a small reply-chain context (last ~5 ancestors)
    # so the receiver's classifier can resolve "close 30%" against context.
    reply_chain = await _build_reply_chain(client, conn, config, d, depth=5)
    payload = {
        "msg_id": d.get("id"),
        "text": d.get("message") or d.get("text") or "",
        "posted_at": str(d.get("date")) if d.get("date") else None,
        "edited_at": str(d.get("edit_date")) if d.get("edit_date") else None,
        "reply_to_msg_id": d.get("reply_to_msg_id"),
        "reply_chain_msg_ids": [m["id"] for m in reply_chain],
        "reply_chain_msgs": {m["id"]: m for m in reply_chain},
    }
    await _post_to_receiver(conn, config, payload)


async def _build_reply_chain(client, conn, config, msg_dict, depth=5):
    """Walk up to `depth` reply-ancestors from local store; fetch from
    Telegram if missing locally."""
    chain = []
    current = msg_dict
    for _ in range(depth):
        parent_id = current.get("reply_to_msg_id")
        if not parent_id:
            break
        # Try local store first
        row = conn.execute(
            "SELECT msg_id, posted_at, reply_to_msg_id, text FROM raw_messages WHERE msg_id = ?",
            (parent_id,),
        ).fetchone()
        if row:
            current = {
                "id": row[0],
                "date": row[1],
                "reply_to_msg_id": row[2],
                "text": row[3] or "",
            }
        else:
            # Fetch from Telegram once
            try:
                msg = await client.get_messages(config.channel_id, ids=parent_id)
                if msg is None:
                    break
                d = msg.to_dict() if hasattr(msg, "to_dict") else dict(msg)
                persist_raw(conn, d)
                current = {
                    "id": d.get("id"),
                    "date": str(d.get("date")) if d.get("date") else None,
                    "reply_to_msg_id": d.get("reply_to_msg_id"),
                    "text": d.get("message") or d.get("text") or "",
                }
            except Exception as e:
                logger.warning("reply chain fetch failed for msg %d: %s", parent_id, e)
                break
        chain.append(current)
    return chain


RETRY_BACKOFFS = (1, 3, 9)  # seconds; 3 attempts total


async def _post_to_receiver(conn, config, payload):
    """POST event to receiver. Retries with exponential backoff (1s, 3s, 9s).

    Each attempt is logged in `forwards` (audit spine). On total failure,
    the event is still in raw_messages — a future replay job can pick it
    up. We never block the listener loop on a stuck receiver.
    """
    import aiohttp
    msg_id = payload["msg_id"]
    async with aiohttp.ClientSession() as session:
        for attempt_num, backoff in enumerate(RETRY_BACKOFFS, start=1):
            try:
                async with session.post(
                    config.receiver_url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    body = await r.text()
                    conn.execute(
                        "INSERT OR REPLACE INTO forwards (msg_id, attempt, attempted_at, status_code, response_text) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (msg_id, attempt_num,
                         datetime.now(timezone.utc).isoformat(),
                         r.status, body[:1000]),
                    )
                    if 200 <= r.status < 300:
                        logger.info("receiver ack msg %d (attempt %d): %s",
                                    msg_id, attempt_num, body[:200])
                        return
                    # 4xx is generally NOT retryable — bad payload won't get better
                    if 400 <= r.status < 500:
                        logger.error(
                            "receiver POST %d for msg %d (non-retryable): %s",
                            r.status, msg_id, body[:200],
                        )
                        return
                    logger.warning(
                        "receiver POST %d for msg %d (attempt %d), retrying in %ds",
                        r.status, msg_id, attempt_num, backoff,
                    )
            except Exception as e:
                conn.execute(
                    "INSERT OR REPLACE INTO forwards (msg_id, attempt, attempted_at, status_code, response_text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (msg_id, attempt_num,
                     datetime.now(timezone.utc).isoformat(),
                     -1, str(e)[:1000]),
                )
                logger.warning(
                    "receiver POST exception msg %d (attempt %d): %s, retrying in %ds",
                    msg_id, attempt_num, e, backoff,
                )

            if attempt_num < len(RETRY_BACKOFFS):
                await asyncio.sleep(backoff)

        logger.error(
            "receiver POST GIVING UP on msg %d after %d attempts. Event in raw_messages; replay manually.",
            msg_id, len(RETRY_BACKOFFS),
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    config = Config()
    conn = init_event_store(config.event_store)
    asyncio.run(run(config, conn))


if __name__ == "__main__":
    main()
