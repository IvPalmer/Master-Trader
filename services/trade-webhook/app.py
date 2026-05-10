"""Trade-webhook receiver — VPS-side always-on alert plane.

Single FastAPI service. Receives freqtrade webhook events on
POST /freqtrade/event, appends one JSONL event per request to
/srv/lake/raw/trades/<bot>.jsonl atomically, and forwards a one-line
summary to Telegram via the elder-brain ops bot.

Closes the gap that Anthropic Channels can't fill: real-time alerts
when Mac is asleep / no Claude Code session is running.

NEXT.md Phase 3 Part B.1.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import logging
import os
import pathlib
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("trade-webhook")

# Suppress httpx's default INFO-level "HTTP Request: POST <url>" log lines.
# Telegram's sendMessage URL embeds the bot token in the path, so unfiltered
# logs leak the token to anyone who can read container stdout (Dokploy logs,
# log forwarders, image exports, etc.). WARNING+ still surfaces real errors.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TRADES_DIR = pathlib.Path(os.environ.get("TRADES_DIR", "/srv/lake/raw/trades"))
OPS_BOT_TOKEN = os.environ.get("OPS_BOT_TOKEN", "").strip()
OPS_BOT_CHAT_ID = os.environ.get("OPS_BOT_CHAT_ID", "").strip()
TELEGRAM_TIMEOUT = float(os.environ.get("TELEGRAM_TIMEOUT", "10"))

app = FastAPI(title="elder-brain trade-webhook")


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_event(bot: str, event: dict[str, Any]) -> None:
    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    target = TRADES_DIR / f"{bot}.jsonl"
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _check_pair_drift(bot: str, pair: str, window_days: int = 30) -> dict[str, Any] | None:
    """Read recent exit_fill events for `bot` from JSONL, scoped to `pair`,
    flag concerning loss patterns. Returns dict of flags, or None if clean.

    Triggers:
      - 3+ losses on this pair in last `window_days`
      - 3-trade trailing loss streak on this pair (latest 3 closes all losses)

    Lightweight: reads only last ~5000 lines of the bot's JSONL (effectively
    last 30-90 days of activity at our cadence) and filters in-memory.
    """
    target = TRADES_DIR / f"{bot}.jsonl"
    if not target.exists():
        return None
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=window_days)

    pair_exits: list[dict[str, Any]] = []
    try:
        # Read last 5000 lines - cheap on these JSONL files
        with open(target, "rb") as f:
            f.seek(0, 2)  # end
            size = f.tell()
            chunk = min(size, 1024 * 256)  # ~256KB tail
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="replace")
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") != "exit_fill":
                continue
            if ev.get("pair") != pair:
                continue
            try:
                ts = _dt.datetime.fromisoformat(ev["ts"].replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                continue
            pair_exits.append(ev)
    except Exception:
        log.exception("pair drift JSONL read failed")
        return None

    if len(pair_exits) < 2:
        return None  # Too few to flag

    # Sort newest first
    pair_exits.sort(key=lambda e: e.get("ts", ""), reverse=True)

    losses = [e for e in pair_exits if (_safe_float(e.get("profit_amount")) or 0) <= 0]
    streak = 0
    for e in pair_exits:
        if (_safe_float(e.get("profit_amount")) or 0) <= 0:
            streak += 1
        else:
            break

    flags: list[str] = []
    if len(losses) >= 3:
        flags.append(f"{len(losses)} losses on {pair} in last {window_days}d")
    if streak >= 3:
        flags.append(f"loss streak = {streak} on {pair}")
    if not flags:
        return None

    return {
        "pair": pair,
        "trades_in_window": len(pair_exits),
        "losses": len(losses),
        "loss_streak": streak,
        "flags": flags,
    }


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def summarize(event: dict[str, Any]) -> str:
    """One-line human-friendly summary of a freqtrade event for Telegram."""
    typ = event.get("type") or "unknown"
    pair = event.get("pair") or ""
    bot = event.get("bot_name") or event.get("strategy") or "?"

    parts: list[str] = []
    if typ == "entry":
        amount = event.get("amount") or event.get("stake_amount") or "?"
        parts.append(f"ENTRY {pair} amount={amount}")
    elif typ == "exit":
        ratio = event.get("profit_ratio")
        amount = event.get("profit_amount")
        reason = event.get("exit_reason") or ""
        ratio_s = f"{ratio*100:.2f}%" if isinstance(ratio, (int, float)) else "?"
        amount_s = f"{amount:+.4f}" if isinstance(amount, (int, float)) else "?"
        parts.append(f"EXIT {pair} {ratio_s} ({amount_s}) {reason}")
    elif typ == "entry_fill":
        rate = event.get("open_rate") or "?"
        parts.append(f"FILLED ENTRY {pair} @ {rate}")
    elif typ == "exit_fill":
        rate = event.get("close_rate") or "?"
        parts.append(f"FILLED EXIT {pair} @ {rate}")
    elif typ == "status":
        msg = event.get("status") or event.get("message") or ""
        parts.append(f"STATUS {msg}"[:200])
    elif typ == "warning":
        msg = event.get("status") or event.get("message") or ""
        parts.append(f"WARN {msg}"[:200])
    else:
        keys = sorted(k for k in event.keys() if k not in {"type", "bot_name", "strategy"})[:4]
        parts.append(f"{typ.upper()} " + " ".join(f"{k}={event.get(k)}" for k in keys))

    return f"[{bot}] " + " ".join(parts)


async def telegram_send(text: str) -> bool:
    if not OPS_BOT_TOKEN or not OPS_BOT_CHAT_ID:
        log.warning("telegram credentials missing — skipping send")
        return False
    url = f"https://api.telegram.org/bot{OPS_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": OPS_BOT_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=TELEGRAM_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            log.error(f"telegram send failed http={resp.status_code} body={resp.text[:200]}")
            return False
        return True
    except httpx.HTTPError as e:
        log.error(f"telegram send error: {e}")
        return False


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "ts": now_iso(),
        "telegram_configured": bool(OPS_BOT_TOKEN and OPS_BOT_CHAT_ID),
        "trades_dir": str(TRADES_DIR),
    }


@app.post("/freqtrade/event")
async def freqtrade_event(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    bot = (payload.get("bot_name") or payload.get("strategy") or "unknown").strip()
    bot = "".join(c if c.isalnum() or c in "-_" else "_" for c in bot)[:64] or "unknown"

    enriched = {
        "ts": now_iso(),
        "received_from": request.client.host if request.client else None,
        **payload,
    }
    try:
        append_event(bot, enriched)
    except Exception as e:
        log.exception("append_event failed")
        raise HTTPException(status_code=500, detail=f"append failed: {e}")

    summary = summarize(enriched)
    sent = await telegram_send(summary)

    # Real-time pair-drift detector. Fires only on losing exit_fill events.
    # Catches structural pair weakness (e.g. ARB-style "informed shorts" on
    # FundingFade) the moment it crosses the threshold, not 24h later via
    # the daily strategy-health-report cron.
    pair_alert: dict[str, Any] | None = None
    profit_amount = _safe_float(enriched.get("profit_amount"))
    if (
        enriched.get("type") == "exit_fill"
        and profit_amount is not None
        and profit_amount <= 0
        and enriched.get("pair")
    ):
        try:
            pair_alert = _check_pair_drift(bot, enriched["pair"])
        except Exception:
            log.exception("pair drift check failed")
        if pair_alert:
            alert_lines = [f"⚠ PAIR DRIFT [{bot}] {pair_alert['pair']}"]
            for f in pair_alert["flags"]:
                alert_lines.append(f"  · {f}")
            alert_lines.append("  → review FF universe / consider whitelist trim")
            await telegram_send("\n".join(alert_lines))

    return {"ok": True, "summary": summary, "telegram_sent": sent, "pair_alert": pair_alert}


@app.post("/test/notify")
async def test_notify(request: Request) -> dict[str, Any]:
    """Manual smoke-test endpoint: sends a Telegram message directly."""
    try:
        body = await request.json()
        text = body.get("text", "synthetic test from trade-webhook")
    except Exception:
        text = "synthetic test from trade-webhook"
    sent = await telegram_send(text)
    return {"ok": True, "telegram_sent": sent}
