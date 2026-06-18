"""Unit tests for the killers target-guard helpers — parser + direction
filter. Both are pure functions; the live mark-price fetch is exercised
only in integration (Binance API).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import (  # noqa: E402
    extract_targets_from_text, filter_remaining_targets,
    to_binance_perp_symbol,
)


# ── extract_targets_from_text ─────────────────────────────────────────────


def test_extract_hype_signal_real():
    text = """📍SIGNAL ID: #2144📍
COIN: $HYPE/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
ENTRY: 56.80 - 57.00

TARGETS: 59.50 - 62.00 - 65.00 - 68.00 -72.00 - 77.00 - 83.00 - 90.00

STOP LOSS: 52.00
"""
    assert extract_targets_from_text(text) == [59.50, 62.00, 65.00, 68.00,
                                                72.00, 77.00, 83.00, 90.00]


def test_extract_pol_signal_real():
    text = "TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300 - 0.1400 - 0.1500"
    assert extract_targets_from_text(text) == [0.0945, 0.0990, 0.1050, 0.1125,
                                                0.1200, 0.1300, 0.1400, 0.1500]


def test_extract_lowercase_targets():
    text = "targets: 1.0 - 2.0 - 3.0"
    assert extract_targets_from_text(text) == [1.0, 2.0, 3.0]


def test_extract_with_extra_whitespace():
    text = "   TARGETS  :   1.5   -   2.5   -   3.5   "
    assert extract_targets_from_text(text) == [1.5, 2.5, 3.5]


def test_extract_no_targets_line():
    text = "ENTRY: 100 - 110\nSTOP LOSS: 90\nNo targets here."
    assert extract_targets_from_text(text) == []


def test_extract_empty_text():
    assert extract_targets_from_text("") == []
    assert extract_targets_from_text(None) == []  # type: ignore


def test_extract_non_string_returns_empty():
    assert extract_targets_from_text(12345) == []  # type: ignore


def test_extract_targets_line_present_but_empty():
    text = "TARGETS: \nSTOP LOSS: 50"
    assert extract_targets_from_text(text) == []


def test_extract_skips_zero():
    """Zero filtered (positivity guard). Negative-looking tokens become
    positive because the number regex is unsigned (the `-` is treated as
    the channel's separator, not a sign — needed because real signals use
    `68.00 -72.00` without space)."""
    text = "TARGETS: 0 - 5.0 - 10.0"
    assert extract_targets_from_text(text) == [5.0, 10.0]


def test_extract_with_comma_decimal():
    """Some locales use comma as decimal separator. Tolerate it."""
    text = "TARGETS: 1,5 - 2,5 - 3,5"
    assert extract_targets_from_text(text) == [1.5, 2.5, 3.5]


def test_extract_TARGET_singular():
    """Channel sometimes uses 'TARGET' singular for the line."""
    text = "TARGET: 5.0 - 10.0 - 15.0"
    assert extract_targets_from_text(text) == [5.0, 10.0, 15.0]


# ── filter_remaining_targets ──────────────────────────────────────────────


def test_filter_long_some_crossed():
    """LONG mark=65 with targets ascending: keep > 65."""
    targets = [59.50, 62.00, 65.00, 68.00, 72.00, 77.00, 83.00, 90.00]
    assert filter_remaining_targets(targets, 65.0, "long") == [
        68.00, 72.00, 77.00, 83.00, 90.00
    ]


def test_filter_long_all_crossed():
    """LONG mark above all targets → []."""
    targets = [1.0, 2.0, 3.0]
    assert filter_remaining_targets(targets, 10.0, "long") == []


def test_filter_long_none_crossed():
    """LONG mark at entry, targets all above → keep all."""
    targets = [10.0, 20.0, 30.0]
    assert filter_remaining_targets(targets, 9.0, "long") == [10.0, 20.0, 30.0]


def test_filter_long_exact_target_excluded():
    """LONG mark exactly at a target → that target is no longer 'ahead'."""
    targets = [10.0, 20.0, 30.0]
    assert filter_remaining_targets(targets, 20.0, "long") == [30.0]


def test_filter_short_some_crossed():
    """SHORT mark=2.0 with descending targets (lower=better): keep < 2.0,
    sorted descending (nearest first)."""
    targets = [3.0, 2.5, 2.0, 1.5, 1.0, 0.5]  # SHORT targets descend
    assert filter_remaining_targets(targets, 2.0, "short") == [1.5, 1.0, 0.5]


def test_filter_short_all_crossed():
    """SHORT mark below all targets → []."""
    targets = [3.0, 2.0, 1.0]
    assert filter_remaining_targets(targets, 0.5, "short") == []


def test_filter_short_none_crossed():
    """SHORT mark above all targets → keep all (nearest = highest)."""
    targets = [3.0, 2.0, 1.0]
    assert filter_remaining_targets(targets, 5.0, "short") == [3.0, 2.0, 1.0]


def test_filter_short_exact_target_excluded():
    targets = [3.0, 2.0, 1.0]
    assert filter_remaining_targets(targets, 2.0, "short") == [1.0]


def test_filter_unknown_direction():
    """Unknown direction → [] (caller treats as guard-failure)."""
    assert filter_remaining_targets([1.0, 2.0], 1.5, "sideways") == []
    assert filter_remaining_targets([1.0, 2.0], 1.5, "") == []
    assert filter_remaining_targets([1.0, 2.0], 1.5, None) == []  # type: ignore


def test_filter_case_insensitive_direction():
    assert filter_remaining_targets([10, 20], 5, "LONG") == [10, 20]
    assert filter_remaining_targets([10, 20], 25, "SHORT") == [20, 10]
    assert filter_remaining_targets([10, 20], 5, "Long") == [10, 20]


def test_filter_empty_targets():
    assert filter_remaining_targets([], 100.0, "long") == []
    assert filter_remaining_targets([], 100.0, "short") == []


def test_filter_invalid_price():
    """Zero/negative price → [] (guard fails safe)."""
    assert filter_remaining_targets([1.0, 2.0], 0, "long") == []
    assert filter_remaining_targets([1.0, 2.0], -5, "long") == []
    assert filter_remaining_targets([1.0, 2.0], None, "long") == []  # type: ignore


def test_filter_long_sorts_nearest_first():
    """Unsorted target input → returned sorted asc (nearest-to-mark first)."""
    targets = [10.0, 5.0, 8.0, 3.0]
    assert filter_remaining_targets(targets, 4.0, "long") == [5.0, 8.0, 10.0]


def test_filter_short_sorts_nearest_first():
    """SHORT: returned sorted desc (nearest-to-mark first)."""
    targets = [1.0, 0.5, 0.8, 0.3]
    assert filter_remaining_targets(targets, 0.9, "short") == [0.8, 0.5, 0.3]


# ── End-to-end: real HYPE signal + plausible mark scenarios ───────────────


def test_end_to_end_hype_mark_below_first_target():
    """HYPE entry 56.80-57.00, targets up to 90. Mark at 57.50 (just inside
    range): all 8 targets remain."""
    text = "TARGETS: 59.50 - 62.00 - 65.00 - 68.00 - 72.00 - 77.00 - 83.00 - 90.00"
    targets = extract_targets_from_text(text)
    remaining = filter_remaining_targets(targets, 57.50, "long")
    assert remaining == [59.50, 62.00, 65.00, 68.00, 72.00, 77.00, 83.00, 90.00]


def test_end_to_end_hype_mark_past_TP3():
    """HYPE mark at 67 → TP1 (59.5), TP2 (62), TP3 (65) all crossed."""
    text = "TARGETS: 59.50 - 62.00 - 65.00 - 68.00 - 72.00 - 77.00 - 83.00 - 90.00"
    targets = extract_targets_from_text(text)
    remaining = filter_remaining_targets(targets, 67.0, "long")
    assert remaining == [68.00, 72.00, 77.00, 83.00, 90.00]


def test_end_to_end_hype_mark_past_all_TPs():
    """HYPE pumped to 95, past max target 90 → skip open."""
    text = "TARGETS: 59.50 - 62.00 - 65.00 - 68.00 - 72.00 - 77.00 - 83.00 - 90.00"
    targets = extract_targets_from_text(text)
    remaining = filter_remaining_targets(targets, 95.0, "long")
    assert remaining == []


# ── to_binance_perp_symbol ────────────────────────────────────────────────


def test_binance_symbol_basic():
    assert to_binance_perp_symbol("BTC") == "BTCUSDT"
    assert to_binance_perp_symbol("eth") == "ETHUSDT"


def test_binance_symbol_aliased():
    assert to_binance_perp_symbol("PEPE") == "1000PEPEUSDT"
    assert to_binance_perp_symbol("SHIB") == "1000SHIBUSDT"


def test_binance_symbol_empty():
    assert to_binance_perp_symbol("") is None
    assert to_binance_perp_symbol(None) is None  # type: ignore


# ── Telegram alert formatter (operator-facing strings) ────────────────────


from app.main import _format_event_summary  # noqa: E402


class _StubPayload:
    """Mimics EventPayload — _format_event_summary only reads .classification."""
    def __init__(self, classification):
        self.classification = classification


class _StubCfg:
    """_format_event_summary only reads cfg.bot_label."""
    bot_label = "killers-scalp"


_CFG = _StubCfg()


def _open_cls():
    return {"kind": "open", "symbol": "HYPE", "direction": "LONG",
            "signal_id": 2144}


def test_alert_open_no_tps_crossed():
    payload = _StubPayload(_open_cls())
    result = {
        "action": "force_enter", "pos_id": 1,
        "ft": {"status": 200},
        "signal_targets": [59.5, 62.0, 65.0, 68.0],
        "remaining_targets": [59.5, 62.0, 65.0, 68.0],
    }
    s = _format_event_summary(_CFG, payload, result)
    assert "📈" in s
    assert "OPEN" in s
    assert "HYPE" in s
    assert "LONG" in s
    assert "4 TPs ahead" in s
    assert "next=59.5" in s


def test_alert_open_some_tps_crossed():
    payload = _StubPayload(_open_cls())
    result = {
        "action": "force_enter", "pos_id": 1,
        "ft": {"status": 200},
        "signal_targets": [59.5, 62.0, 65.0, 68.0, 72.0, 77.0, 83.0, 90.0],
        "remaining_targets": [68.0, 72.0, 77.0, 83.0, 90.0],
    }
    s = _format_event_summary(_CFG, payload, result)
    assert "3/8 TPs crossed" in s
    assert "next=68" in s


def test_alert_open_no_targets_parsed():
    """Parser miss → signal_targets empty → alert has no target tail."""
    payload = _StubPayload(_open_cls())
    result = {"action": "force_enter", "pos_id": 1,
              "ft": {"status": 200},
              "signal_targets": [], "remaining_targets": []}
    s = _format_event_summary(_CFG, payload, result)
    assert "TPs" not in s
    assert "📈" in s and "OPEN" in s


def test_alert_all_targets_crossed_skip():
    payload = _StubPayload(_open_cls())
    result = {"action": "skipped", "reason": "all_targets_crossed",
              "mark": 95.0,
              "signal_targets": [59.5, 90.0]}
    s = _format_event_summary(_CFG, payload, result)
    assert "🚫" in s
    assert "SKIPPED" in s
    assert "all TPs already crossed" in s
    assert "mark=95.0" in s


def test_alert_mark_fetch_failed_skip_uses_generic_format():
    """Mark fetch failure → action=skipped reason=mark_fetch_failed... →
    falls through to the generic skipped formatter (not the special all-TPs
    one)."""
    payload = _StubPayload(_open_cls())
    result = {"action": "skipped",
              "reason": "mark_fetch_failed (target guard fail-closed)",
              "signal_targets": [59.5, 90.0]}
    s = _format_event_summary(_CFG, payload, result)
    assert "⏭" in s  # generic skipped emoji
    assert "mark_fetch_failed" in s


def test_alert_prefix_uses_default_bot_label():
    """Unset KILLERS_BOT_LABEL → alerts keep the legacy [killers-scalp] tag."""
    payload = _StubPayload(_open_cls())
    result = {"action": "skipped", "reason": "entry_bounds_missing",
              "max_slippage_pct": 3.0}
    s = _format_event_summary(_StubCfg(), payload, result)
    assert "[killers-scalp]" in s
    assert "[insiders-scalp]" not in s


def test_alert_prefix_follows_bot_label_override():
    """Insiders instance sets bot_label=insiders-scalp → alerts must NOT
    masquerade as the live Killers bot (the mislabel bug)."""
    class _InsidersCfg:
        bot_label = "insiders-scalp"
    payload = _StubPayload(_open_cls())
    result = {"action": "skipped", "reason": "entry_bounds_missing",
              "max_slippage_pct": 3.0}
    s = _format_event_summary(_InsidersCfg(), payload, result)
    assert "[insiders-scalp]" in s
    assert "[killers-scalp]" not in s


def test_config_bot_label_env_driven():
    """Config.bot_label reads KILLERS_BOT_LABEL, defaulting to killers-scalp."""
    import os
    from app.main import Config
    saved = os.environ.get("KILLERS_BOT_LABEL")
    try:
        os.environ.pop("KILLERS_BOT_LABEL", None)
        assert Config().bot_label == "killers-scalp"
        os.environ["KILLERS_BOT_LABEL"] = "insiders-scalp"
        assert Config().bot_label == "insiders-scalp"
        os.environ["KILLERS_BOT_LABEL"] = ""  # empty → falls back, no "[]" tag
        assert Config().bot_label == "killers-scalp"
    finally:
        if saved is None:
            os.environ.pop("KILLERS_BOT_LABEL", None)
        else:
            os.environ["KILLERS_BOT_LABEL"] = saved


if __name__ == "__main__":
    funcs = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS  {f.__name__}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"FAIL  {f.__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
