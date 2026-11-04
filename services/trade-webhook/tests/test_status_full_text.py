"""The nightly health report reaches Telegram in full (#234).

A `status` event used to become `f"STATUS {msg}"[:200]`, so the ~5-7k-char
health report reached the chat cut inside its PORTFOLIO block. A `status`
event from `health-report` is now sent whole, split on line breaks into
messages that fit Telegram's 4096 UTF-16-unit limit. Other senders keep the
200-char line.
"""
import importlib
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

TELEGRAM_LIMIT = 4096


def _utf16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


TOKEN = "notify-token-for-tests-0123456789abcdef"


def _load(monkeypatch, tmp_path, token=None):
    monkeypatch.setenv("TRADES_DIR", str(tmp_path))
    monkeypatch.delenv("OPS_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPS_BOT_CHAT_ID", raising=False)
    if token is None:
        monkeypatch.delenv("TRADE_WEBHOOK_NOTIFY_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", token)
    monkeypatch.delenv("TRADE_WEBHOOK_EVENT_AUTH", raising=False)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    monkeypatch.setattr(module, "telegram_send", fake_send)
    return module, TestClient(module.app), sent


@pytest.fixture(autouse=True)
def _drop_module():
    yield
    sys.modules.pop("app", None)


def _report(n_lines: int, width: int = 70, glyph: str = "") -> str:
    return "\n".join(f"{glyph}line {i:04d} " + "x" * width for i in range(n_lines))


def _post(client, bot, text, typ="status", headers=None):
    resp = client.post("/freqtrade/event", json={"type": typ, "bot_name": bot, "status": text},
                       headers=headers or {})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _strip_part_prefix(part: str) -> str:
    head, sep, rest = part.partition(" ")
    assert sep and head.startswith("(") and head.endswith(")"), part[:20]
    return rest


def _rebuilt(sent) -> str:
    """The parts with their "(i/n) " prefixes removed, concatenated."""
    if len(sent) == 1:
        return sent[0]
    return "".join(_strip_part_prefix(p) for p in sent)


def test_long_health_report_arrives_whole_in_order(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    report = _report(120)  # ~9.4k chars, like a busy night
    body = _post(client, "health-report", report)

    assert len(sent) >= 3
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    n = len(sent)
    assert [p.split(" ", 1)[0] for p in sent] == [f"({i}/{n})" for i in range(1, n + 1)]
    assert _rebuilt(sent) == f"[health-report] STATUS {report}"
    assert body["telegram_sent"] is True


def test_parts_split_on_line_breaks(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, "health-report", _report(120))
    for part in sent[:-1]:
        assert part.endswith("x" * 70 + "\n")


def test_short_health_report_is_one_unprefixed_message(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, "health-report", "ok\nall green")
    assert sent == ["[health-report] STATUS ok\nall green"]


def test_astral_glyphs_counted_as_two_units(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    report = _report(80, width=20, glyph="\U0001F534" * 20)  # 40 extra UTF-16 units a line
    _post(client, "health-report", report)
    assert len(sent) > 1
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    assert _rebuilt(sent) == f"[health-report] STATUS {report}"


def test_line_longer_than_a_message_is_cut_not_dropped(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    report = "head\n" + "y" * 9000 + "\ntail"
    _post(client, "health-report", report)
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    assert _rebuilt(sent) == f"[health-report] STATUS {report}"


def test_runaway_report_is_capped_with_a_pointer(monkeypatch, tmp_path):
    module, client, sent = _load(monkeypatch, tmp_path)
    _post(client, "health-report", _report(3000))  # ~230k chars
    assert len(sent) == module.MAX_STATUS_PARTS
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    assert "health-report.jsonl" in sent[-1].splitlines()[-1]


@pytest.mark.parametrize("bot, typ, prefix", [
    ("walk-forward", "status", "STATUS"),
    ("KeltnerBounceV1", "status", "STATUS"),
    ("health-report", "warning", "WARN"),
])
def test_other_senders_keep_the_short_line(monkeypatch, tmp_path, bot, typ, prefix):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, bot, _report(120), typ=typ)
    assert len(sent) == 1
    assert sent[0].startswith(f"[{bot}] {prefix} line 0000")
    assert len(sent[0]) == len(f"[{bot}] ") + 200


def test_lake_keeps_the_full_text(monkeypatch, tmp_path):
    _, client, _ = _load(monkeypatch, tmp_path)
    report = _report(120)
    _post(client, "health-report", report)
    assert report in (tmp_path / "health-report.jsonl").read_text().replace("\\n", "\n")


def test_failed_part_reports_not_sent(monkeypatch, tmp_path):
    module, client, _ = _load(monkeypatch, tmp_path)
    calls = []

    async def flaky(text):
        calls.append(text)
        return len(calls) != 2

    monkeypatch.setattr(module, "telegram_send", flaky)
    body = _post(client, "health-report", _report(120))
    assert len(calls) >= 3  # later parts are still attempted
    assert body["telegram_sent"] is False


@pytest.mark.parametrize("report", [
    "a" * 3877 + "\n\nTAIL",          # blank line right at a part boundary
    "\n\n\nlead" + "b" * 5000,        # leading newlines, then a hard cut
    "c" * 3878 + "\n" + "d" * 4000 + "\n\n",
    "x\r\ny\r\n" * 900,               # CRLF
])
def test_exact_reconstruction_at_every_boundary(monkeypatch, tmp_path, report):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, "health-report", report)
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    assert _rebuilt(sent) == f"[health-report] STATUS {report}"


def test_only_newlines_never_sends_a_blank_part(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, "health-report", "\n" * 9000)
    assert sent and all(p.strip() for p in sent)
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)


def test_huge_single_line_is_linear_and_capped(monkeypatch, tmp_path):
    module, client, sent = _load(monkeypatch, tmp_path)
    t = time.monotonic()
    _post(client, "health-report", "x" * 1_000_000)
    assert time.monotonic() - t < 5
    assert len(sent) == module.MAX_STATUS_PARTS
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)


def test_lone_surrogate_does_not_crash_the_split(monkeypatch, tmp_path):
    # A JSON body can carry a lone surrogate as an escape; the UTF-16 count
    # must not try to encode it. (The route's own JSON response already
    # fails on one for every event type; that is out of scope here.)
    module, _, _ = _load(monkeypatch, tmp_path)
    text = "bad \ud800 char\n" * 400
    parts, cut = module.split_for_telegram(text)
    assert not cut and len(parts) > 1 and "".join(parts) == text


def test_split_rejects_a_limit_below_two(monkeypatch, tmp_path):
    module, _, _ = _load(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        module.split_for_telegram("abc", limit=1)


@pytest.mark.parametrize("name", [" health-report ", "health-report\n", "Health-Report"])
def test_full_text_needs_the_exact_sender_name(monkeypatch, tmp_path, name):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, name, _report(120))
    assert len(sent) == 1 and len(sent[0].split("] ", 1)[1]) == 200


def test_with_a_token_configured_full_text_needs_it(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path, token=TOKEN)
    _post(client, "health-report", _report(120))  # monitor mode: accepted, kept short
    assert len(sent) == 1
    sent.clear()
    _post(client, "health-report", _report(120), headers={"X-Notify-Token": TOKEN})
    assert len(sent) >= 3
