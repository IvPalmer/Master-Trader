"""The nightly health report reaches Telegram in full (#234).

A `status` event used to become `f"STATUS {msg}"[:200]`, so the ~5-7k-char
health report reached the chat cut inside its PORTFOLIO block. A `status`
event from `health-report` is now sent whole, split on line breaks into
messages that fit Telegram's 4096 UTF-16-unit limit. Other senders keep the
200-char line.
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

TELEGRAM_LIMIT = 4096


def _utf16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADES_DIR", str(tmp_path))
    monkeypatch.delenv("OPS_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPS_BOT_CHAT_ID", raising=False)
    monkeypatch.delenv("TRADE_WEBHOOK_NOTIFY_TOKEN", raising=False)
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


def _post(client, bot, text, typ="status"):
    resp = client.post("/freqtrade/event", json={"type": typ, "bot_name": bot, "status": text})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _strip_part_prefix(part: str) -> str:
    head, sep, rest = part.partition(" ")
    assert sep and head.startswith("(") and head.endswith(")"), part[:20]
    return rest


def test_long_health_report_arrives_whole_in_order(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    report = _report(120)  # ~9.4k chars, like a busy night
    body = _post(client, "health-report", report)

    assert len(sent) >= 3
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    n = len(sent)
    assert [p.split(" ", 1)[0] for p in sent] == [f"({i}/{n})" for i in range(1, n + 1)]
    joined = "\n".join(_strip_part_prefix(p) for p in sent)
    assert joined == f"[health-report] STATUS {report}"
    assert body["telegram_sent"] is True


def test_parts_split_on_line_breaks(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    _post(client, "health-report", _report(120))
    for part in sent:
        last = _strip_part_prefix(part).splitlines()[-1]
        assert last.endswith("x" * 70)


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
    assert "\n".join(_strip_part_prefix(p) for p in sent) == f"[health-report] STATUS {report}"


def test_line_longer_than_a_message_is_cut_not_dropped(monkeypatch, tmp_path):
    _, client, sent = _load(monkeypatch, tmp_path)
    report = "head\n" + "y" * 9000 + "\ntail"
    _post(client, "health-report", report)
    assert all(_utf16(p) <= TELEGRAM_LIMIT for p in sent)
    assert "".join(_strip_part_prefix(p).replace("\n", "") for p in sent) == \
        f"[health-report] STATUS {report}".replace("\n", "")


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
