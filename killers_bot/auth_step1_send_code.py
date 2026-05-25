"""Step 1 of non-interactive Telegram auth.

Sends the login code to the phone's Telegram app, prints the
phone_code_hash so step 2 can complete the sign-in.

Usage:
    python3 auth_step1_send_code.py <phone>

Reads KILLERS_TG_API_ID / KILLERS_TG_API_HASH from env or .env.
"""
import asyncio
import os
import sys
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
    if len(sys.argv) != 2:
        print("usage: python3 auth_step1_send_code.py <phone>")
        sys.exit(2)
    phone = sys.argv[1]

    load_env()
    api_id = int(os.environ["KILLERS_TG_API_ID"])
    api_hash = os.environ["KILLERS_TG_API_HASH"]
    session_path = Path(__file__).parent / "killers"

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"ALREADY_AUTH user={me.first_name} id={me.id} phone={me.phone}")
        await client.disconnect()
        return

    sent = await client.send_code_request(phone)
    print(f"CODE_SENT phone_code_hash={sent.phone_code_hash}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
