# Eduardo onboarding — generate your `.session` file and hand it over

This is everything you need to do to enable the copy-trader to receive
signals from the Insiders Scalp Telegram group through your account.

You'll do this ONCE. After it's done you can forget about it — the session
persists for months as long as the listener keeps receiving updates.

**Time required: ~15 minutes**

## What this does

Your Telegram account is a member of the Insiders Scalp private group.
Our bot needs to read messages from that group, but it can't be added as
a member (private channel + the signaler doesn't add bots). So we use
your user-account session to read on your behalf.

This is a one-way read flow:
- Your session reads messages from the group.
- Our listener pulls those messages over Telegram's API using your session.
- We never post messages, never DM anyone, never modify your account.

Your session file is the equivalent of being logged in on a device. Treat
it like a password.

## Prerequisites

- Your Telegram account, logged in on your phone with 2FA already enabled
- Python 3 on your laptop (or you can use ours over a video call)
- The Telethon library — `pip install telethon`

## Step 1 — Get app credentials at my.telegram.org

You need an `api_id` and `api_hash`. These identify the LISTENER APP, not
your user.

1. Go to https://my.telegram.org and log in with your phone number.
2. Click "API development tools".
3. Fill in the form:
   - App title: `MT-Listener`
   - Short name: `mt-listener`
   - Platform: Desktop
   - Description: (anything)
4. You'll get `App api_id` and `App api_hash`. Copy them.

(If you already have api_id/api_hash from your prototype, reuse them.)

## Step 2 — Generate the session file

Save this script as `gen_session.py`:

```python
from telethon.sync import TelegramClient

API_ID = 12345        # paste yours
API_HASH = "..."       # paste yours
SESSION_NAME = "mt-listener"  # output file = mt-listener.session

with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
    # Telethon prompts for phone number + login code + 2FA password.
    print("Logged in as:", client.get_me().username)
```

Run it once:

```bash
pip install telethon
python3 gen_session.py
```

You'll be prompted for:
1. Phone number (include country code, e.g. `+5511...`)
2. Login code (sent to your Telegram app)
3. 2FA password (if you have it set)

After successful login, it creates a file `mt-listener.session` in the
current directory. That's the session file. Keep your terminal open and
**do not delete the file**.

## Step 3 — Rename the session in your Telegram app

So you don't kill it by accident later:

1. Open Telegram on your phone.
2. Settings → Devices (or Active Sessions).
3. Find the new session you just created (will be named "Telethon" or
   similar, marked Desktop, recent activity).
4. Tap it → rename it to **"MT-Listener"**.
5. Leave it. Don't tap "Terminate session" on this one.

This way if you ever clean up sessions in the future, you'll see
"MT-Listener" in the list and know to leave it alone.

## Step 4 — Hand over the session file

The session file = full read access to your Telegram. Treat it carefully.

Encrypt it before sending:

```bash
# macOS/Linux: install age (https://github.com/FiloSottile/age)
brew install age      # or: apt install age

# Encrypt with a one-time password Palmer will give you over a secure channel
age -p mt-listener.session > mt-listener.session.age
```

Send `mt-listener.session.age` via:
- Email is OK (it's encrypted)
- Telegram self-DM is OK (encrypted-at-rest by Telegram for ~24h)
- WhatsApp / Signal is OK

Palmer will decrypt on the receiving VPS and put it in the read-only
secrets path of the listener container. He will NOT commit it to git,
ever.

## Step 5 — Send the credentials too

Send `api_id` and `api_hash` separately. Plain text is fine for these.

Send the group ID:
- In your `last_month_messages.json` from the prototype, look for the
  channel id at the top of the file (should be a large negative number,
  like `-1003881583689`)
- Just send the number — confirms we're pointing at the right group.

## Step 6 — Confirmation

Once Palmer has:
- `mt-listener.session.age` (decrypted to `mt-listener.session` on the VPS)
- `api_id` (your numeric ID)
- `api_hash` (your 32-char string)
- Group ID (the negative number)

He spins up the listener, dry-run for ~1 week. He'll send you a Telegram DM
when it's running and again if anything looks wrong.

## What can go wrong

- **You hit "Terminate session" on "MT-Listener" in your Telegram Settings.**
  This will kill the bot's access. We'll see the heartbeat fail and alert.
  Just re-run gen_session.py and send the new file.
- **You log into Telegram from a new device and Telegram auto-cleans old
  sessions.** Rare, usually only happens after long inactivity. Same fix.
- **You log out everywhere on purpose.** Same fix.
- **You change your Telegram password / 2FA.** May or may not invalidate
  sessions; if heartbeat dies, regenerate.

The session can run unattended for **months** as long as Telegram keeps
seeing it receive updates (it does — the listener is constantly reading
the group, so the session counts as "active").

## What we do with this

We run a small Python service ("the listener") in a Docker container on
our VPS. It uses your session to subscribe to the Insiders Scalp group
via Telegram's API. Every message it sees, we:

1. Persist to a local audit database (private to our VPS)
2. Classify (open/close/SL-move/chat) using either Python rules or Claude
3. If it's an actionable trading signal, place an order on OUR Binance
   Futures account (initially $200, dry-run for a week first, then small
   live)

You do NOT see any of this in your Telegram. Your account is unchanged
from your perspective. We don't read your DMs, we don't read other
groups, we don't post anything. The Telegram API permissions of a user
session are broad (we technically could read anything in your account),
but our listener is hard-coded to only subscribe to the one group ID
you give us.

If you want to verify this, the listener code is in our public-ish repo:
https://github.com/IvPalmer/Master-Trader/blob/main/ft_userdata/insiders_bridge/listener.py

## Phase 2

If this works for a few weeks, the plan is to:

1. Get our own membership in the group (you introduce / vouch).
2. Switch the listener to our own session — your account stops being
   the proxy, you can do whatever with it.
3. We help YOU build your own copy bot from the same code — your own
   Binance account, your own stake size, your own listener using your
   session. Same Docker image, different env file.

You will not be carrying our middleware risk forever. This is a phase-1
arrangement.

## Questions

DM Palmer with anything. There's no rush — this isn't time-critical for
us. Better to do it carefully than fast.
