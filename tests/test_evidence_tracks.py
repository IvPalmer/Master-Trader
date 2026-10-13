"""GH #28 evidence tracks: FundingFade controls, Keltner frequency, Insiders epochs,
Short Keltner breakdown. Synthetic data only."""
import ast
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

ROOT = Path(__file__).parents[1]
ET = ROOT / "research/evidence_tracks"
sys.path.insert(0, str(ET))

import common  # noqa: E402
import ff_controls as ffc  # noqa: E402
import insiders_fresh_sample as ins  # noqa: E402
import keltner_setup_frequency as ksf  # noqa: E402
import short_keltner_breakdown as skb  # noqa: E402


# ── common ────────────────────────────────────────────────────────────────
def test_epoch_assignment_uses_start_and_never_relabels():
    ep = [("a", "2026-01-01T00:00:00Z"), ("b", "2026-02-01T00:00:00Z")]
    assert common.assign_epoch("2025-12-31T23:59:59Z", ep) is None
    assert common.assign_epoch("2026-01-31 23:59:59", ep) == "a"
    assert common.assign_epoch("2026-02-01T00:00:00Z", ep) == "b"


def test_block_bootstrap_detects_dominance_and_is_deterministic():
    a = {f"d{i:02d}": 1.0 for i in range(30)}
    b = {f"d{i:02d}": 0.0 for i in range(30)}
    assert common.block_bootstrap_p_better(a, b) == 1.0
    assert common.block_bootstrap_p_better(b, a) == 0.0
    assert common.block_bootstrap_p_better(a, a) == 0.0
    assert common.block_bootstrap_p_better({}, {}) is None


def _variant(pf, net):
    part = {"profit_factor": pf, "net": net}
    return {"half1": part, "half2": part}


def test_reading_rule_requires_beating_control_and_placebo_p90_in_every_half():
    s = {"gate": _variant(2.0, 5.0), "ctrl": _variant(1.0, 1.0)}
    for i in range(10):
        s[f"pl{i:02d}"] = _variant(1.0 + i * 0.05, i * 0.1)
    assert common.control_reading_rule(s, "gate", "ctrl", "pl")["discriminative_power"] == "demonstrated"
    s["gate"]["half2"] = {"profit_factor": 2.0, "net": 0.1}   # loses on net in one half
    assert common.control_reading_rule(s, "gate", "ctrl", "pl")["discriminative_power"] == "not demonstrated"
    s["gate"] = _variant("inf", 5.0)
    assert common.control_reading_rule(s, "gate", "ctrl", "pl")["discriminative_power"] == "demonstrated"


# ── FundingFade controls ──────────────────────────────────────────────────
def test_lookback_constants_match_deployed_strategy():
    src = (ROOT / "ft_userdata/user_data/strategies/FundingFadeV1.py").read_text()
    assert f"funding_lookback = {ffc.FUNDING_LOOKBACK}" in src


def _funding(n=1500, seed=3):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0001, 0.00005, n))


def test_funding_term_never_looks_ahead():
    f = _funding()
    base = ffc.funding_term(f)
    tampered = f.copy()
    tampered.iloc[1000:] = 9.0
    assert (ffc.funding_term(tampered).iloc[:1000] == base.iloc[:1000]).all()


def test_lagged_term_is_causal_and_fails_closed_at_start():
    f = _funding()
    lag = ffc.lagged_funding_term(f)
    assert (lag.iloc[:ffc.LAG_BARS + ffc.MIN_PERIODS - 1] == 0).all()
    tampered = f.copy()
    tampered.iloc[1000:] = -9.0
    assert (ffc.lagged_funding_term(tampered).iloc[:1000 + ffc.LAG_BARS] == lag.iloc[:1000 + ffc.LAG_BARS]).all()


def test_placebo_matches_pass_rate_and_is_deterministic_per_pair_seed():
    real = ffc.funding_term(_funding(5000))
    p1, p2 = ffc.placebo_term(real, "ADA/USDT", 1), ffc.placebo_term(real, "ADA/USDT", 1)
    assert p1.equals(p2)
    assert not p1.equals(ffc.placebo_term(real, "ADA/USDT", 2))
    assert not p1.equals(ffc.placebo_term(real, "XRP/USDT", 1))
    assert abs(p1.mean() - real.mean()) < 0.03
    assert (ffc.price_only_term(real.index) == 1).all()


def test_research_variants_parse_and_refuse_live():
    for name in ("FFCausalResearch.py", "KeltnerExitResearch.py"):
        src = (ET / name).read_text()
        ast.parse(src)
        assert "never run live/dry" in src


# ── Keltner setup frequency ───────────────────────────────────────────────
def _ohlc(n, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    dates = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"date": dates, "open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": rng.uniform(1, 2, n) * 1000})


def test_keltner_funnel_is_monotone_and_gate_term_matters():
    df, btc = _ohlc(1500, 1), _ohlc(1500, 2)
    t = ksf.terms(df, btc)
    assert (t["setup"] <= (t["cross"] & t["volume"])).all()
    out = ksf.funnel({"X/USDT": t})["pairs"]["X/USDT"]
    assert out["setup"] <= out["cross_volume"] <= out["cross"]
    assert out["gate_blocked_cross_volume"] == out["cross_volume"] - out["setup"]


def test_keltner_terms_match_deployed_constants():
    src = (ROOT / "ft_userdata/user_data/strategies/KeltnerBounceV1.py").read_text()
    for needle in ("kelt_period = 25", "kelt_atr_mult = 2.5", "vol_multiplier = 1.75", "btc_sma_period = 50"):
        assert needle in src


# ── Insiders fresh sample ─────────────────────────────────────────────────
EPOCHS = json.loads((ET / "insiders_epochs.json").read_text())


def _t(open_date, pnl, **kw):
    return {"open_date": open_date, "close_date": open_date, "profit_abs": pnl, "leverage": 3, **kw}


def test_insiders_trades_split_by_entry_epoch_and_old_regime_cannot_pass_the_bar():
    old = [_t("2026-06-10T00:00:00Z", 5.0, leverage=5) for _ in range(40)]
    r = ins.report(old, EPOCHS)
    assert r["epochs"]["pre-remediation-5x-weex-hl"]["trades"] == 40
    assert r["epochs"]["grouped-target-executor"]["trades"] == 0
    assert r["fresh_bar"]["status"] == "insufficient_evidence"
    assert "stays dry-run" in r["allocation_recommendation"]


def test_insiders_bar_needs_30_and_pf():
    fresh = [_t("2026-09-20T00:00:00Z", 1.0) for _ in range(18)] + [_t("2026-09-21T00:00:00Z", -1.0) for _ in range(12)]
    assert ins.report(fresh, EPOCHS)["fresh_bar"]["status"] == "bar_met"        # PF 1.5
    weak = [_t("2026-09-20T00:00:00Z", 1.0) for _ in range(15)] + [_t("2026-09-21T00:00:00Z", -1.0) for _ in range(15)]
    assert ins.report(weak, EPOCHS)["fresh_bar"]["status"] == "bar_not_met"
    assert ins.report(fresh[:10], EPOCHS)["fresh_bar"]["status"] == "insufficient_evidence"
    # receiver-admitted count below the floor blocks the bar even with 30 closed trades
    assert ins.report(fresh, EPOCHS, admitted=12)["fresh_bar"]["status"] == "insufficient_evidence"


def test_insiders_excludes_open_and_live_trades():
    ts = [_t("2026-09-20T00:00:00Z", 1.0, is_open=True), _t("2026-09-20T00:00:00Z", 1.0, is_dry=False),
          _t("2026-09-20T00:00:00Z", 1.0)]
    r = ins.report(ts, EPOCHS)
    assert r["epochs"]["grouped-target-executor"]["trades"] == 1
    assert {e["reason"] for e in r["excluded"]} == {"open", "live_trade_not_dry_sample"}


# ── Short Keltner breakdown ───────────────────────────────────────────────
def _frame(closes, highs=None, lows=None, vol=1000.0):
    n = len(closes)
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"),
                         "open": c, "high": pd.Series(highs, dtype=float) if highs is not None else c + 0.1,
                         "low": pd.Series(lows, dtype=float) if lows is not None else c - 0.1,
                         "close": c, "volume": vol})


def test_score_signal_stop_target_time_and_same_bar_ambiguity():
    n = 150
    df = skb.add_indicators(_frame([100.0] * n))
    df["atr"] = 1.0                                   # risk = 2.0 -> stop 102, target 96
    i = 30
    flat = df.copy()
    assert skb.score_signal(flat, i)[1] == "time" and skb.score_signal(flat, i)[0] == 0.0
    hit_t = df.copy(); hit_t.loc[35, "low"] = 95.0
    assert skb.score_signal(hit_t, i)[:2] == (2.0, "target")
    hit_s = df.copy(); hit_s.loc[35, "high"] = 103.0
    assert skb.score_signal(hit_s, i)[:2] == (-1.0, "stop")
    both = df.copy(); both.loc[35, "high"] = 103.0; both.loc[35, "low"] = 95.0
    assert skb.score_signal(both, i)[:2] == (-1.0, "stop")      # ambiguity scores as the stop


def test_score_signal_refuses_truncated_data():
    df = skb.add_indicators(_frame([100.0] * 60)); df["atr"] = 1.0
    assert skb.score_signal(df, 30) is None            # 72 bars not available
    assert skb.score_signal(df, 59) is None            # no entry bar


def test_signal_is_causal_and_requires_gate_and_volume():
    base = [100.0] * 60 + [100.0, 80.0]               # drop through lower band on the last bar
    raw = _frame(base)
    raw.loc[raw.index[-1], "volume"] = 1e6
    df = skb.add_indicators(raw)
    bear = pd.Series(True, index=df.index)
    assert skb.breakdown_signal(df, bear).iloc[-1]
    assert not skb.breakdown_signal(df, ~bear).iloc[-1]
    low_vol = raw.copy(); low_vol.loc[low_vol.index[-1], "volume"] = 1.0
    assert not skb.breakdown_signal(skb.add_indicators(low_vol), bear).iloc[-1]
    # appending future bars cannot change an earlier signal
    raw_ext = _frame(base + [50.0, 120.0])
    raw_ext.loc[raw_ext.index[61], "volume"] = 1e6
    ext = skb.add_indicators(raw_ext)
    assert skb.breakdown_signal(ext, pd.Series(True, index=ext.index)).iloc[61]


def test_costs_in_r_and_no_profit_claim_on_small_samples():
    assert skb.net_r(2.0, 0.02, 10) == pytest.approx(2.0 - 0.002 / 0.02)
    trades = [{"gross_r": 2.0, "risk_frac": 0.02, "reason": "target", "hold": 3}] * 5
    s = skb.summarize(trades)
    assert s["n"] == 5 and s["mean_net_r"] == pytest.approx(1.9) and s["profit_claim"].startswith("none")


def test_evaluate_one_position_at_a_time_and_report_shape():
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(-0.05, 1.2, 1500))
    df = _frame(close, highs=close + 0.8, lows=close - 0.8)
    df["volume"] = rng.uniform(500, 3000, len(df))
    bear = pd.Series(True, index=df.index)
    trades = skb.evaluate(df, bear)
    for a, b in zip(trades, trades[1:]):
        assert b["i"] > a["i"] + a["hold"]
    rep = skb.report(df, bear, n_placebo=20)
    assert set(rep["by_cost"]) == {5, 10, 20} and rep["signals_scored"] == len(trades)


# ── preregistration ───────────────────────────────────────────────────────
def test_preregistrations_exist_for_each_track_and_are_open_research_only():
    reg = json.loads((ROOT / "ft_userdata/preregistrations.json").read_text())["preregistrations"]
    ids = {p["id"]: p for p in reg}
    for pid in ("ff-causal-funding-control-2026-10-12", "keltner-exit-universe-validation-2026-10-12",
                "insiders-fresh-sample-2026-10-12", "shortkeltner-breakdown-eval-2026-10-12"):
        p = ids[pid]
        assert p["status"] == "open" and p["review_by"] and p["issue"] == "#28"
        assert "research only" in json.dumps(p).lower() and "allocation" in json.dumps(p).lower()
