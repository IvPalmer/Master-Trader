"""Step 2 of non-interactive Telegram auth.

Completes sign-in using the code received in the user's Telegram app.

Usage:
    python3 auth_step2_sign_in.py <phone> <phone_code_hash> <code> [2fa_password]
"""
import asyncio
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


async def main():
    if len(sys.argv) < 4:
        print("usage: python3 auth_step2_sign_in.py <phone> <phone_code_hash> <code> [2fa_password]")
        sys.exit(2)
    phone = sys.argv[1]
    phone_code_hash = sys.argv[2]
    code = sys.argv[3]
    password = sys.argv[4] if len(sys.argv) > 4 else None

    load_env()
    api_id = int(os.environ["KILLERS_TG_API_ID"])
    api_hash = os.environ["KILLERS_TG_API_HASH"]
    session_path = Path(__file__).parent / "killers"

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()

    try:
        me = await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        if not password:
            print("PASSWORD_NEEDED — re-run with 2FA password as 4th arg")
            await client.disconnect()
            sys.exit(3)
        me = await client.sign_in(password=password)

    print(f"AUTH_OK first_name={me.first_name} id={me.id} phone={me.phone}")
    if me.username:
        print(f"username=@{me.username}")
    print(f"session_file={session_path}.session")

    # Quick channel sanity check
    try:
        ent = await client.get_entity("BinanceKillersHub")
    except Exception:
        ent = None
    if ent is None:
        try:
            ent = await client.get_entity("BinanceKillers_FreeSignal")
        except Exception as e:
            print(f"channel_resolve_failed: {e}")

    if ent is not None:
        title = getattr(ent, "title", None) or getattr(ent, "first_name", None)
        print(f"channel_resolved id={ent.id} title={title!r}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
