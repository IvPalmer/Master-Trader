"""List all Telegram dialogs (channels + groups) the authed user is in.

Helps pick the right channel id when there are multiple matching names.
"""
import asyncio
import os
from pathlib import Path

from telethon import TelegramClient


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


async def main():
    load_env()
    api_id = int(os.environ["KILLERS_TG_API_ID"])
    api_hash = os.environ["KILLERS_TG_API_HASH"]
    session_path = Path(__file__).parent / "killers"

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()

    me = await client.get_me()
    print(f"# logged in as @{me.username or me.id} ({me.first_name})")
    print()
    print(f"{'id':>14}  {'username':<32}  title")
    print("-" * 90)

    async for dialog in client.iter_dialogs():
        ent = dialog.entity
        if hasattr(ent, "broadcast") or hasattr(ent, "megagroup"):
            # Channel or supergroup
            uname = getattr(ent, "username", None) or "—"
            kind = "ch" if getattr(ent, "broadcast", False) else "sg"
            title = dialog.name or "?"
            if "killer" in title.lower() or "killer" in (uname or "").lower():
                marker = "  ← MATCH"
            else:
                marker = ""
            print(f"{ent.id:>14}  @{uname:<31}  [{kind}] {title}{marker}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
