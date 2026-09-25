"""Capital basis of the daily health report (#60).

The report used to print `portfolio_value = 528.0 + P&L` and divide P&L by
528.0: the paper budget of a retired six-bot R$3,000 fleet, about 3x the real
live base, with dry-run P&L mixed in. The basis is now read from the exchange
the way the exporter's circuit breaker reads it: each LIVE capital_account
valued once through its capital_owner's /balance, dry-run bots excluded, and
no fallback constant when a balance is missing.

    python3 -m pytest tests/test_health_report_capital_basis.py -q
"""

import re
import sys
from pathlib import Path

import pytest

FT_DIR = Path(__file__).resolve().parent.parent / "ft_userdata"
sys.path.insert(0, str(FT_DIR))

import strategy_health_report as shr  # noqa: E402

# Two live bots on one Binance wallet (FundingFade owns it), one live bot on
# its own account, one dry-run bot that also names the shared wallet.
BOTS = {
    "FundingFadeV1": {"port": 8096, "capital_account": "binance-spot", "capital_owner": True,
                      "timeframe": "1h", "type": "funding-divergence"},
    "KeltnerBounceV1": {"port": 8095, "capital_account": "binance-spot",
                        "timeframe": "1h", "type": "mean-reversion"},
    "SoloLive": {"port": 8200, "timeframe": "1h", "type": "trend-follower"},
    "PaperBot": {"port": 8300, "capital_account": "binance-spot",
                 "timeframe": "1h", "type": "mean-reversion"},
}

DRY_RUN = {8096: False, 8095: False, 8200: False, 8300: True}
# Keltner's /balance reads the same wallet; if it were counted too the value
# would double. PaperBot's simulated wallet must never enter the basis.
BALANCES = {
    8096: {"total": 174.0, "starting_capital": 160.0},
    8095: {"total": 174.0, "starting_capital": 150.0},
    8200: {"total": 50.0, "starting_capital": 40.0},
    8300: {"total": 1000.0, "starting_capital": 1000.0},
}
# closed profit_abs per bot; open profit_abs per bot
CLOSED = {8096: [3.0, -1.0], 8095: [2.0], 8200: [-1.0], 8300: [500.0]}
OPEN = {8096: [0.5], 8095: [], 8200: [1.5], 8300: [-100.0]}


def _trades(port):
    return [{"pair": "BTC/USDT", "profit_abs": p, "profit_ratio": p / 100,
             "close_date": "2026-09-20 10:00:00", "exit_reason": "roi"}
            for p in CLOSED[port]]


def _open(port):
    return [{"pair": f"P{i}/USDT", "profit_abs": p, "open_date": "2026-09-25 00:00:00"}
            for i, p in enumerate(OPEN[port])]


def make_fetch(balances=None, dry_run=None, down=()):
    balances = BALANCES if balances is None else balances
    dry_run = DRY_RUN if dry_run is None else dry_run

    def fetch(port, endpoint, timeout=10):
        if port in down:
            return None
        if endpoint.startswith("trades"):
            return {"trades": _trades(port)}
        if endpoint == "status":
            return _open(port)
        if endpoint == "profit":
            return {"max_drawdown": 0.01, "profit_closed_percent_sum": 1.0}
        if endpoint == "show_config":
            return {"dry_run": dry_run[port]}
        if endpoint == "balance":
            return balances.get(port)
        raise AssertionError(endpoint)
    return fetch


def run_report(monkeypatch, **kw):
    monkeypatch.setattr(shr, "BOTS", BOTS)
    monkeypatch.setattr(shr, "fetch_json", make_fetch(**kw))
    metrics = [shr.compute_bot_metrics(s, i) for s, i in BOTS.items()]
    portfolio = shr.compute_portfolio_metrics(metrics)
    return metrics, portfolio


def test_basis_counts_shared_account_once_and_excludes_dry_run(monkeypatch):
    _, p = run_report(monkeypatch)

    # binance-spot once via its owner (174) + SoloLive's own account (50).
    assert p["portfolio_value"] == pytest.approx(224.0)
    assert p["live_starting_capital"] == pytest.approx(200.0)
    assert set(p["live_accounts"]) == {"binance-spot", "SoloLive"}
    assert p["live_accounts"]["binance-spot"]["owner"] == "FundingFadeV1"
    # live P&L: FF 3-1+0.5 = 2.5, Keltner 2, Solo -1+1.5 = 0.5 -> 5.0
    assert p["live_true_pnl"] == pytest.approx(5.0)
    assert p["return_pct"] == pytest.approx(2.5)  # 5 / 200
    # dry-run P&L (500 - 100) is reported apart, never divided by live capital
    assert p["dry_run_true_pnl"] == pytest.approx(400.0)
    assert p["dry_run_bots"] == ["PaperBot"]
    # the all-bots totals are still there, and differ from the live figure
    assert p["true_pnl"] == pytest.approx(405.0)
    assert p["capital_basis_errors"] == []


def test_formatter_prints_live_equity_and_separate_dry_run(monkeypatch):
    metrics, p = run_report(monkeypatch)
    text = shr.format_telegram_report(metrics, p, {})
    assert "Value: $224.00 strategy-fleet live equity (+2.50% on ~$200.00 starting capital)" in text
    assert "Live P&L: $+5.00" in text
    assert "Dry-run P&L (simulated, excluded from return): $+400.00" in text


def test_unavailable_balance_gives_none_and_formatter_says_na(monkeypatch):
    balances = {**BALANCES, 8096: None}
    metrics, p = run_report(monkeypatch, balances=balances)

    assert p["portfolio_value"] is None
    assert p["return_pct"] is None
    assert p["live_starting_capital"] is None
    assert "balance unavailable: binance-spot" in p["capital_basis_errors"]
    text = shr.format_telegram_report(metrics, p, {})
    assert "Value: n/a (balance unavailable: binance-spot)" in text
    assert "528" not in text


@pytest.mark.parametrize("bad", [
    {"total": float("nan"), "starting_capital": 160.0},
    {"total": 174.0, "starting_capital": 0},
    {"total": -1.0, "starting_capital": 160.0},
    {"starting_capital": 160.0},
    ["not", "a", "dict"],
])
def test_invalid_balance_is_unavailable_not_defaulted(monkeypatch, bad):
    _, p = run_report(monkeypatch, balances={**BALANCES, 8096: bad})
    assert p["portfolio_value"] is None and p["return_pct"] is None
    assert "balance unavailable: binance-spot" in p["capital_basis_errors"]


def test_shared_account_without_live_owner_is_unavailable(monkeypatch):
    # Owner demoted to dry-run, two other live bots on the wallet: the
    # exporter refuses to guess a representative, so must the report.
    bots = {**BOTS, "OITrend": {"port": 8102, "capital_account": "binance-spot",
                                "timeframe": "1h", "type": "x"}}
    dry = {**DRY_RUN, 8096: True, 8102: False}
    CLOSED[8102], OPEN[8102] = [1.0], []
    try:
        monkeypatch.setattr(shr, "BOTS", bots)
        monkeypatch.setattr(shr, "fetch_json", make_fetch(dry_run=dry))
        metrics = [shr.compute_bot_metrics(s, i) for s, i in bots.items()]
        p = shr.compute_portfolio_metrics(metrics)
    finally:
        del CLOSED[8102], OPEN[8102]
    assert p["portfolio_value"] is None
    assert "balance unavailable: binance-spot" in p["capital_basis_errors"]


def test_unknown_run_mode_blocks_basis(monkeypatch):
    # An unreachable bot might be live; the basis is incomplete, not smaller.
    _, p = run_report(monkeypatch, down={8200})
    assert p["portfolio_value"] is None and p["return_pct"] is None
    assert "run mode unavailable: SoloLive (SoloLive)" in p["capital_basis_errors"]


def test_missing_open_marks_block_live_return(monkeypatch):
    base = make_fetch()

    def fetch(port, endpoint, timeout=10):
        if port == 8095 and endpoint == "status":
            return None
        return base(port, endpoint, timeout)

    monkeypatch.setattr(shr, "BOTS", BOTS)
    monkeypatch.setattr(shr, "fetch_json", fetch)
    metrics = [shr.compute_bot_metrics(s, i) for s, i in BOTS.items()]
    p = shr.compute_portfolio_metrics(metrics)
    assert p["portfolio_value"] == pytest.approx(224.0)  # equity still observed
    assert p["return_pct"] is None
    assert "live P&L unavailable: KeltnerBounceV1" in p["capital_basis_errors"]
    text = shr.format_telegram_report(metrics, p, {})
    assert "Value: $224.00 strategy-fleet live equity (return n/a: live P&L unavailable: KeltnerBounceV1)" in text


def test_open_pnl_counts_before_first_close(monkeypatch):
    CLOSED_BAK = dict(CLOSED)
    try:
        CLOSED[8200] = []
        _, p = run_report(monkeypatch)
    finally:
        CLOSED.clear()
        CLOSED.update(CLOSED_BAK)
    # SoloLive has only its +1.5 open position; it must still count.
    assert p["live_true_pnl"] == pytest.approx(6.0)


def test_none_basis_survives_state_round_trip(monkeypatch, tmp_path):
    metrics, p = run_report(monkeypatch, balances={**BALANCES, 8096: None})
    monkeypatch.setattr(shr, "STATE_FILE", tmp_path / "state.json")
    shr.save_state(metrics, p)
    prev = shr.load_previous_state()
    assert prev["portfolio"]["portfolio_value"] is None
    assert prev["portfolio"]["return_pct"] is None
    assert shr.compute_trends(metrics, prev)["FundingFadeV1"]["pnl_delta"] == 0


def test_no_hardcoded_capital_constant_in_health_report():
    src = (FT_DIR / "strategy_health_report.py").read_text()
    assert not re.search(r"\b528\b", src)
    assert "INITIAL_CAPITAL" not in src


def test_uncovered_live_accounts_are_named_not_implied(monkeypatch):
    """Review finding: the headline read as fleet-wide equity while the
    receiver-managed Hyperliquid accounts were never valued."""
    uncovered = shr._load_uncovered_bots()
    assert {"KillersScalpV1", "InsidersScalpV1"} <= set(uncovered)
    assert not set(uncovered) & set(shr.BOTS)
    lines = shr._format_capital_lines({
        "portfolio_value": 224.0, "return_pct": 2.5, "live_starting_capital": 200.0,
        "live_true_pnl": 5.0, "capital_basis_errors": [],
        "uncovered_live_bots": uncovered,
    })
    assert any(l.startswith("  Not covered (valued by the exporter): ") and
               "KillersScalpV1" in l for l in lines)

