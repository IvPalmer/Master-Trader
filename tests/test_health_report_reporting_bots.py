"""Reporting-only bots in the daily health report (#219).

`main()` reports every bot in REPORTING_BOTS, which adds `monitor` and
`production_live` bots (ShortKeltnerV2HL, KillersScalpV1) to the `active`
strategy bots in BOTS. Two lookups still went to BOTS only:

- the pair-concentration loop in `compute_portfolio_metrics` raised
  `KeyError: 'ShortKeltnerV2HL'` the first time that bot answered, and the
  2026-10-28 report was never sent;
- `check_preregistrations` found no port for KillersScalpV1, so the
  `killers-ladder-maxdd-25` trigger printed "no trade data" every night
  instead of being evaluated.

The cron wrapper must also hand the report each bot's own API pair, otherwise
every bot but one answers 401 and looks offline.

    python3 -m pytest tests/test_health_report_reporting_bots.py -q
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ft_userdata"))

import api_utils  # noqa: E402
import strategy_health_report as shr  # noqa: E402

BOTS = {
    "KeltnerBounceV1": {"port": 8095, "capital_account": "binance-spot",
                        "timeframe": "1h", "type": "mean-reversion"},
}
REPORTING_BOTS = {
    **BOTS,
    "ShortKeltnerV2HL": {"port": 8103, "monitor": True,
                         "timeframe": "1h", "type": "short"},
    "KillersScalpV1": {"port": 8099, "production_live": True,
                       "capital_account": "hyperliquid-killers",
                       "timeframe": "5m", "type": "copy-trader"},
}
OPEN_PAIR = {8095: "LINK/USDT", 8103: "LINK/USDT", 8099: "HYPE/USDC:USDC"}


def _fetch(port, endpoint, timeout=10):
    if endpoint.startswith("trades"):
        return {"trades": [{"pair": "BTC/USDT", "profit_abs": 1.0, "profit_ratio": 0.01,
                            "close_date": "2026-10-20 10:00:00", "exit_reason": "roi"}]}
    if endpoint == "status":
        return [{"pair": OPEN_PAIR[port], "profit_abs": 0.1,
                 "open_date": "2026-11-01 00:00:00"}]
    if endpoint == "profit":
        return {"max_drawdown": 0.01, "profit_closed_percent_sum": 1.0}
    if endpoint == "show_config":
        return {"dry_run": port != 8095}
    if endpoint == "balance":
        return {"total": 200.0, "starting_capital": 200.0}
    raise AssertionError(endpoint)


def test_portfolio_metrics_survive_online_reporting_only_bots(monkeypatch):
    monkeypatch.setattr(shr, "BOTS", BOTS)
    monkeypatch.setattr(shr, "REPORTING_BOTS", REPORTING_BOTS)
    monkeypatch.setattr(shr, "fetch_json", _fetch)
    metrics = [shr.compute_bot_metrics(s, i) for s, i in REPORTING_BOTS.items()]
    assert all(m["online"] for m in metrics)

    portfolio = shr.compute_portfolio_metrics(metrics)

    # The monitor bot's open trade is part of the overlap check, not skipped.
    assert portfolio["overlapping_pairs"] == {
        "LINK/USDT": ["KeltnerBounceV1", "ShortKeltnerV2HL"]
    }
    # "Bots: N/M online" counts the same set the report polls.
    assert portfolio["bots_online"] == 3
    assert portfolio["bots_total"] == 3


def test_prereg_triggers_evaluate_for_a_production_live_bot(monkeypatch, tmp_path):
    registry = {"preregistrations": [{
        "id": "killers-equal-ladder", "bot": "KillersScalpV1", "status": "open",
        "registered": "2026-09-30",
        "triggers": [{"id": "killers-ladder-maxdd-25", "metric": "max_drawdown_pct",
                      "basis": "since_registered", "op": ">", "threshold": 25.0,
                      "action": "Pause new Killers entries and review"}],
    }]}
    reg_file = tmp_path / "preregistrations.json"
    reg_file.write_text(json.dumps(registry))
    trades = [
        {"close_date": "2026-10-01 00:00:00", "profit_abs": 10.0, "is_open": False},
        {"close_date": "2026-10-08 00:00:00", "profit_abs": -80.0, "is_open": False},
    ]
    monkeypatch.setattr(shr, "PREREG_FILE", reg_file)
    monkeypatch.setattr(shr, "BOTS", BOTS)
    monkeypatch.setattr(shr, "REPORTING_BOTS", REPORTING_BOTS)
    monkeypatch.setattr(shr, "get_trades_from_api",
                        lambda port, **kw: trades if port == 8099 else None)
    monkeypatch.setattr(shr, "fetch_json",
                        lambda port, endpoint, **kw: {"starting_capital": 300.0}
                        if endpoint == "balance" and port == 8099 else None)

    blob = "\n".join(shr.check_preregistrations())

    # Peak 310 -> 230 is 25.8%, over the 25% limit.
    assert "TRIGGER killers-ladder-maxdd-25: BREACHED" in blob, blob
    assert "no trade data" not in blob, blob


def test_cron_wrapper_exports_every_bots_own_pair():
    wrapper = (ROOT / "deploy" / "vps" / "run-health-report.sh").read_text()
    exported = set(re.findall(r"^export_bot_creds\s+([A-Z]+)\s+\S+", wrapper, re.M))
    assert exported == set(api_utils.PORT_API_SLUGS.values())


def test_cron_wrapper_is_executable_in_git():
    """The host cron runs the wrapper through a symlink into the deploy
    checkout, so the file mode git writes there is the mode cron sees."""
    import subprocess
    mode = subprocess.run(
        ["git", "ls-files", "-s", "deploy/vps/run-health-report.sh"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()[0]
    assert mode == "100755", mode
