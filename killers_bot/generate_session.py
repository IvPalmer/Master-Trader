"""One-time Telethon authentication.

Run on the machine where you have your Telegram phone handy (Mac is fine).
Prompts for api_id, api_hash, phone number, and the SMS code Telegram
sends. Writes killers.session next to this file.

The session file IS your account credential — treat it like an SSH key.
Encrypt it before transferring anywhere (age recommended).

  pip install telethon
  python3 generate_session.py
"""
from getpass import getpass
from pathlib import Path

from telethon.sync import TelegramClient


def main() -> None:
    print("Telegram session generator for killers_bot")
    print("-" * 44)
    api_id = int(input("api_id (from my.telegram.org): ").strip())
    api_hash = input("api_hash: ").strip()
    phone = input("phone (international format, e.g. +5511999999999): ").strip()

    session_path = Path(__file__).parent / "killers"
    with TelegramClient(str(session_path), api_id, api_hash) as client:
        # Telethon will prompt for SMS code interactively (and 2FA password if set)
        client.start(phone=phone, password=lambda: getpass("2FA password (Enter if none): "))
        me = client.get_me()
        print()
        print(f"✓ Authenticated as: {me.first_name} {me.last_name or ''}".rstrip())
        print(f"  username:  @{me.username}" if me.username else "  (no username)")
        print(f"  user_id:   {me.id}")
        print(f"  phone:     {me.phone}")
        print()
        print(f"Session written to: {session_path}.session")
        print()
        print("Next steps:")
        print("  1. age-encrypt the .session file before transferring it.")
        print("  2. Confirm you've joined t.me/BinanceKillers_FreeSignal in")
        print("     this Telegram account.")


if __name__ == "__main__":
    main()
