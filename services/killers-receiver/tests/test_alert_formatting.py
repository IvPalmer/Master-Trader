"""Telegram alert formatting: an entry the executor rejected must never be
announced as an open position.

2026-08-25 incident: signal #2213 UNI long was rejected by Freqtrade's
custom_stake_amount risk backstop (stake $8.47 < venue minimum $11.29, 502),
but the alert read "📈 OPEN · ... ft_status=502" — the operator read it as a
filled position and went looking for it on the dashboard.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402


def _payload(kind="open", symbol="UNI", direction="long", signal_id=2213):
    return receiver_main.EventPayload(
        msg={"id": 1, "date": "2026-08-25T03:58:00+00:00", "text": "x"},
        classification={
            "id": 1, "kind": kind, "signal_id": signal_id, "symbol": symbol,
            "direction": direction, "entry": None, "entry_range": None,
            "sl": None, "tp": None, "pct": None, "applies_to": None,
            "confidence": 1.0, "notes": "test",
        },
    )


def _cfg():
    return receiver_main.Config()


def test_failed_force_enter_is_announced_as_entry_failed_not_open():
    result = {"action": "force_enter", "pos_id": 2,
              "ft": {"status": 502, "body": "..."}}
    text = receiver_main._format_event_summary(_cfg(), _payload(), result)
    assert "ENTRY FAILED" in text
    assert "no position opened" in text
    assert "OPEN " not in text
    assert "502" in text


def test_successful_force_enter_still_announced_as_open():
    result = {"action": "force_enter", "pos_id": 3,
              "ft": {"status": 200, "body": "..."}}
    text = receiver_main._format_event_summary(_cfg(), _payload(), result)
    assert "OPEN" in text
    assert "ENTRY FAILED" not in text


def test_missing_ft_status_is_treated_as_failure():
    # Synthetic "?" status (no parseable Freqtrade response) is not a fill.
    result = {"action": "force_enter", "pos_id": 4, "ft": {}}
    text = receiver_main._format_event_summary(_cfg(), _payload(), result)
    assert "ENTRY FAILED" in text


def test_below_venue_min_notional_skip_has_dedicated_alert():
    result = {"action": "skipped", "reason": "below_venue_min_notional",
              "notional_usd": 8.24, "min_notional_usd": 11.3}
    text = receiver_main._format_event_summary(_cfg(), _payload(), result)
    assert "SKIPPED" in text
    assert "venue min" in text
    assert "$1-risk cap preserved" in text
