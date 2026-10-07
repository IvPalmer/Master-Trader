# Killers observer: Telegram delivery latency

Issue #164. Research and design only. Nothing in production was changed or restarted for this analysis.

## Summary

The Killers channel (@BinanceKillers_FreeSignal, about 26.7K subscribers on the public preview) posts reach our observer with a median delay of **14.4 s** (p90 40.9 s, max 60.7 s). This regime has held since 2026-06-18. Before then the same channel arrived in about 1.2 s.

The data shows Telegram **holding** this channel's updates for our session and **releasing them when our client sends a request**. Today we send two kinds of request: Telethon's keepalive ping every 60 s and the observer's heartbeat `get_me` every 120 s. These two cadences set the delay ceiling.

The proposed fix is to send an MTProto `ping` every 5 s. A ping is a transport keepalive, not an API method. Official TDLib clients in the foreground ping every ~2 s. If every ping releases held updates the way `get_me` does, we expect p50 ≈ 3 s and max ≈ 6 s. That expectation is a hypothesis until it is measured.

## Data and method

Sources (read-only, on the VPS):

- `/home/ubuntu/killers-bot/observer.log`, 2026-05-25 → 2026-10-03, which contains:
  - `[MSG NEW|EDITED|BACKFILL]` lines, logged right after `persist_raw`
  - `[HB]` lines, logged after `get_me()` returns
  - Telethon `Got difference ...` and connection lines
- Observer DBs `killers-bot/state.sqlite` and `insiders-bot/state.sqlite`, table `raw_messages`:
  - `posted_at` = Telegram `msg.date` (server time, truncated to whole seconds, which adds about +0.5 s of bias)
  - `edited_at`
- Receiver DB `ingress_events` and `ft-killers-scalp` docker logs, used for the execution leg.

Each log line is attributed to a feed by matching the msg id plus the logged text snippet against the DB of each feed. The two feeds' message ids overlap.

**Lag** is the `[MSG NEW]` log time minus `posted_at`.

Ruled out: VPS clock (NTP synced, offset −28 µs, root distance 0.8 ms).

## Measurements

| Feed / window | n | p25 | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|---|---|
| Killers, last 6 weeks (08-22 → 10-03) | 318 | 7.0 | **14.4** | 24.7 | 40.9 | 46.5 | 60.7 |
| Killers, all since 06-18 | 551 | 6.7 | 14.0 | 25.1 | 37.7 | 44.8 | 60.7 |
| Killers, 05-25 → 06-17 | 85 | 0.9 | 1.2 | 1.4 | 1.6 | 1.7 | 1.9 |
| Insiders group, last 6 weeks (same session) | 1209 | 0.8 | 1.0 | 1.3 | 1.4 | 1.6 | 3.8 |

All values are in seconds. The 05-25 → 06-17 window also had two gap recoveries (1 h and 39 min), and both were delivered by `getChannelDifference`.

### When the regime changed

The last fast post was 2026-06-17 18:18 (1.2 s). The first slow post was 2026-06-19 03:20 (37 s). Weekly p50 has stayed at 7–17 s ever since. The slow regime survived 9+ observer restarts.

The window also contains a connection incident on 2026-06-17:

- 21:29: Telethon logged "Server replied with a wrong session ID". The FAQ cause for this is the same session being used concurrently.
- About 15 minutes of connect timeouts followed.
- 22:46: the observer restarted.

A causal link to the incident is **unproven**.

### Message properties

Lag does not depend on message kind:

- open: p50 16.4 s
- close_partial: 12.6 s
- chat: 13.9 s

It does not depend on media (photo 14.1 s, text 13.4 s) or on time of day (p50 10–17 s in every 4 h UTC bucket with n≥37).

The `views` field in the payload is 1 even when lag is 40 s. The update object was therefore built at post time and delivered late. It was not fetched late.

### Batching

Killers posts arrive in batches: 10 pairs were delivered within 100 ms of each other. In 8 of those pairs the posts were made 1–38 s apart; for example msgs 3819 and 3820 were posted 38 s apart and arrived together. Only 13 killers `getChannelDifference` calls appear in 4 months, so these batches are released pushes. They are not gap catch-up.

### Edits

Edits are too few to conclude anything. There are 4 killers edits in the slow regime, at 1.5, 2.6, 5.5 and 6.9 s. Insiders edits have p50 0.8 s.

## Root cause

### Evidence

1. **Release coincides with our requests.**
   - **Heartbeat.** 78 of 551 slow-regime receipts fall within 0.1 s *before* the `[HB]` log line, which is printed right after the `get_me` response. A uniform distribution predicts 0.5. The fast-regime killers data has 0 in that bin, and the insiders control has 1.
   - **Keepalive ping.** For non-heartbeat receipts less than 30 min apart, 40 of 155 pairs are spaced within 1 s of a multiple of 60 s. Chance predicts about 5, and the insiders control is flat. Telethon 1.43.2 sends `PingRequest` every 60 s (`client/updates.py`, `_keepalive_loop`: `wait_for(disconnected, timeout=60)` → `_keepalive_ping`).
   - **Ceiling.** The maximum lag is 60.7 s across 551 posts, which matches the ping interval. A server-side fan-out delay would not stop exactly at our ping period.
   - **No wall-clock alignment.** Receipts are not clustered by second-of-minute, so there is no server timer aligned to the clock.
   - **Server pushes don't release them.** Only 1 of 452 killers receipts came within 1 s after an insiders push.
2. **The client is not the bottleneck.** The insiders group runs on the same client, connection and event loop and gets p50 1.0 s.
   - Handlers are dispatched concurrently (`sequential_updates=False`).
   - Locks are per message id.
   - Classification and the receiver POST are async.
   - The process used 1.4 s of CPU in 3 h.
   - The log contains no FloodWait.
   - The RTT to the session DC (149.154.175.57) is 107 ms.
3. **Telegram documents this behavior** (core.telegram.org/api/updates): "in some cases the API may stop sending updates (or send fewer updates) for some channels/supergroups". User clients are expected to call `updates.getChannelDifference` for chats the user is viewing, re-invoking it after the `timeout` the server returns. The TDLib maintainer has said users "aren't supposed to receive all updates in supergroups/channels" unless the chat is opened. Telethon issues #652 and #3150 report 20–45 s delays on large channels, falling to 1–5 s when the account is active on mobile.

### Hypotheses (not verified)

- **Why the session became passive.** Telegram classified this session as passive for this channel around 2026-06-18. It may have been because of subscriber count, account activity or the session incident. The operator can check one cheap thing in the app with no API calls: whether the channel was muted or archived around that date.
- **Whether a bare ping releases updates.** A bare MTProto `ping` probably releases held updates the same way `get_me` does. The statistical evidence supports it, but only a controlled run can confirm it.
- **The unexplained remainder.** About 40% of receipts align with neither trigger. They may be spontaneous or delayed pushes.

### Client-library notes

Telethon (1.43.2, the repository was archived 2026-02-21) has the following behavior:

- It fetches channel difference only on a pts gap or after 15 min without updates.
- It ignores `ChannelDifference.timeout`; it honors the field only for `TooLong`.
- `catch_up`, `sequential_updates` and `flood_sleep_threshold` would not help.

## Options

Options are ranked by expected latency gain and account risk. The personal account is the reader, so account risk is the binding constraint.

| # | Option | Telegram calls added | Expected p50 / max | Account risk |
|---|---|---|---|---|
| 1 | **MTProto `ping` every 5 s** (`functions.PingRequest`) | 720 pings/h (17,280/day); these are not API methods, and FLOOD_WAIT applies to API methods | ~3 s / ~6 s, if every ping releases | Very low. TDLib foreground clients ping every max(2 s, 1.5·RTT+1 s) = 2 s here (RTT 107 ms) (`SessionConnection.h`, `ping_must_delay`), and offline clients every 30–60 s |
| 2 | Shorten heartbeat `get_me` to 15 s (`KILLERS_HEARTBEAT_SEC=15`, config only) | 240 `users.getUsers`/h (5,760/day) | ~8 s / ~16 s | Low–moderate. It is an API method at a steady rate 24/7, and its flood limits are undocumented. It has the strongest release evidence (78/551) |
| 3 | `account.updateStatus(offline=false)` like a foreground app | ~1/min | Unknown; anecdotally 1–5 s (#3150) | Moderate. The account shows "online" 24/7, and Telegram may suppress the operator's phone notifications while another session is online |
| 4 | `getChannelDifference` for this one channel at the server `timeout` ("open chat") | 360–720/h at 5–10 s; the actual server timeout is unknown | ~timeout/2 | Moderate. The TDLib maintainer warns of server flood limits; the footprint is a 24/7 "viewing" pattern; Telethon needs custom code |
| 5 | Dedicated burner account as reader (operator decision) | Same as the chosen option | No gain by itself; the same server policy likely applies | Moves the risk off the personal account. New accounts doing API use are banned often, and one needs a phone number |
| 6 | Public web preview `t.me/s/<channel>` poller (no account) | HTTP GETs, e.g. 720/h at 5 s | Unknown; preview freshness is unmeasured | No account risk; IP 429/ban risk, brittle HTML parsing, and polling the operator ruled out in spirit |
| — | Mark the channel read (`channels.readHistory`) | — | No evidence it changes push behavior | — |
| — | Cornix | — | Not a fix | The channel sells a separate paid "BK VIP Cornix" channel. Cornix is a third-party bot that auto-executes integrated channels' signals on the user's exchange via trade-only API keys (Binance, Bybit, Bitget, …; Hyperliquid is not listed). It does not speed up the free channel. It also means paying VIP/Cornix followers execute first, so our copy is structurally behind them |

## Execution leg (receiver → Freqtrade)

The breakdown comes from 7 opens since 2026-09-23 (the window where Freqtrade logs exist) and 21 receiver opens since 08-20.

| Stage | Time | Notes |
|---|---|---|
| Observer → receiver → Freqtrade "signal found" | 0.5–0.85 s | Mark-price REST fetch (HL `allMids`), sizing, and the `forceenter` POST |
| Freqtrade "signal found" → "Order … created" | **2.2–3.0 s** | Inside `execute_entry`. Probably several sequential Hyperliquid REST round trips (leverage/margin setup and order creation), but this is not instrumented |
| After the order exists | ~1.5 s | Wallet sync and RPC notification before `forceenter` returns. This does not affect fill timing |

For ENA (msg 4103): posted 15:16:03 → observer 15:16:22.17 → order created on HL 15:16:24.83 → receiver done 15:16:26.43.

Safe cuts are worth about 0.3–1 s, which is small next to the 14 s Telegram leg:

- Use a WebSocket-cached mid instead of the REST mark fetch.
- Pre-set leverage per pair.

Instrument the leg first by persisting `t_mark`, `t_ft_post` and `t_ft_return` in `ingress_events`. Do not bypass Freqtrade.

## Original recommendation (superseded by the 2026-10-04 review below): option 1 behind a flag

The change is small and lives in `killers_bot/observer.py`, inside `run()` after the handlers are set up:

```python
import random
from telethon.tl import functions
nudge = float(os.getenv("KILLERS_TG_NUDGE_SEC", "0"))   # 0 = off (default)
async def _nudge():
    while nudge > 0:
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(client(functions.PingRequest(ping_id=random.getrandbits(63))), 10)
            config._last_pong = time.monotonic()
        except Exception as e:                       # never touches the feed
            logger.warning("[NUDGE] ping failed: %s", e)
        await asyncio.sleep(max(0.0, nudge - (time.monotonic() - t0)))
```

Telethon resolves a user-invoked `PingRequest` through `_handle_pong`, which pops `_pending_state[pong.msg_id]`. It does not collide with the keepalive's own `_ping` id.

Instrumentation, added with or without the nudge: `[MSG NEW]` should also log `tg_lag=<now − msg.date>` and `since_pong=<now − last pong>`. This shows whether receipts land just after a pong without logging every ping. At 5 s, per-ping lines would add 17k lines a day.

### Measurement

There is no true shadow, because a second live connection on this session is ruled out.

1. Deploy with `KILLERS_TG_NUDGE_SEC=0`. This only adds the instrumentation. Record a few days of baseline.
2. Set the flag to 5 and restart the observer. The startup backfill (`iter_messages(min_id=last)`) covers posts missed during the restart.
3. Pass criteria:
   - At least 10 killers posts.
   - p90 `tg_lag` ≤ 7 s.
   - Most receipts with `since_pong` < 0.5 s.
   - No new FloodWait or auth warnings.
   - Insiders is unaffected.

   For scale: the baseline puts 25% of posts at or under 7 s, so 10 straight passes would occur by chance with probability ~1e-6.
4. If the run fails, pings do not release held updates. The next step is option 2 at 15 s, which needs the operator's call. Do not combine options before measuring each one.

### Rollback

Set `KILLERS_TG_NUDGE_SEC=0` in `killers_bot/.env`, then run `systemctl --user restart killers-observer`. No receiver or Freqtrade change is involved.

### Expected end-to-end effect

For opens, post → order on Hyperliquid drops from about 17 s median (14.4 + ~2.7) to about 6 s. This holds only if the release hypothesis holds.

## Review 2026-10-04: what the delay costs

The analysis above shows the delay is real. It does not show that the delay costs money. That is measured here, and the result changes the recommendation.

**Method.** The 54 Killers opens since 2026-06-18 that were delivered as pushes (lag 0–120 s) and are listed on Binance. 11 symbols with no Binance listing were skipped. For each open:

- Took the first Binance aggTrade at post time + 3 s, which is what option 1 would at best deliver.
- Took the first aggTrade at our actual receipt.
- Signed the price move in the signal's direction, so a positive move is adverse to the entry.
- Divided it by the stop distance to express it in R.

Script: scratchpad `drift.py`. Binance prices stand in for Hyperliquid marks.

| Set | n | Lag p50 | Adverse move avoided, mean | Median | p90 | Mean in R |
|---|---|---|---|---|---|---|
| Opens, slow regime | 54 | 17.8 s | +0.019% | 0.000% | +0.115% | +0.0015 R |
| Opens, fast regime (control) | 16 | 0.6 s | −0.001% | 0.000% | +0.015% | 0 R |

- **Total over 3.5 months:** 0.08 R across all 54 opens, which is about $1.00 at today's $12 risk.
- **Worst single open:** JUP, 44 s lag, +0.37%, which is 0.03 R or about $0.38.
- **Closes:** the 182 close messages moved by an absolute mean of 0.061% over the same window (p90 0.17%). That is an upper bound, because most closes only announce a target that our Hyperliquid-resident TP orders had already filled.

**Why the cost is so small.**

- The signals are 4H/8H swing setups, and price moves only a few hundredths of a percent in 15 s.
- In 53 of 54 opens the price was already past the posted zone when the channel posted, with a median of 1.66% past the edge. The limit-in-zone misses (#162) came from the channel's timing, not from ours.

**Revised recommendation: do not implement the ping.**

- The expected gain is about $0.30/month. Account risk is very low but not zero, and it falls on the operator's personal Telegram account.
- It would also add code and maintenance on an archived client library.
- Keep this document as the diagnosis. Reopen if any of these change:
  - signals become time-critical (for example market-now calls on fast movers);
  - risk per trade grows by an order of magnitude;
  - the delay worsens beyond about 60 s.
- Checked 2026-10-04 in the operator's Telegram app: the channel ("Binance Killers Vip", 26,670 subscribers) is muted and not archived. The operator says it was always muted. Posts arrived in about 1 s while it was muted before 2026-06-18, so muting does not explain the change.

## Open questions

- What triggered the regime change on 2026-06-17/19?
- Does the server-advised `timeout` exist for this channel, and what is it? Learning it costs one `getChannelDifference` call, which needs operator approval.
- Telethon has been archived since 2026-02-21. Migrating to a maintained MTProto client, for example TDLib with `openChat` semantics, is a separate decision.
