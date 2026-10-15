"""GROA-309 entry-policy replay harness: synthetic 1m candles, no network."""
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "epr", pathlib.Path(__file__).resolve().parents[1]
    / "research/copier-validation/killers/entry_policy_replay.py")
epr = importlib.util.module_from_spec(spec)
sys.modules["epr"] = epr
spec.loader.exec_module(epr)

T0 = epr.ms("2026-01-01T00:00:00+00:00")
MIN, HOUR = epr.MIN, epr.HOUR


def sig(**kw):
    s = {"signal_id": 1, "symbol": "X", "direction": "long", "entry_lo": 9.5, "entry_hi": 10.0,
         "sl_initial": 9.0, "tp_ladder": [10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14],
         "open_date": "2026-01-01T00:00:00+00:00", "channel_close_date": None}
    s.update(kw)
    return s


def series(prices, start=T0):
    """one candle per minute from (o,h,l,c) tuples; flat candles for a bare float."""
    out = []
    for i, p in enumerate(prices):
        o, h, l, c = (p, p, p, p) if isinstance(p, (int, float)) else p
        out.append([start + i * MIN, o, h, l, c])
    return out


def flat(px, n):
    return [px] * n


def test_chase_cap_boundaries():
    s = sig()
    c = series(flat(10.15, 30))                       # 1.5% above zone top
    assert "pnl" not in epr.run_signal(s, c, {"kind": "chase", "cap": 0.01}, 0) \
        and epr.run_signal(s, c, {"kind": "chase", "cap": 0.01}, 0)["skip"] == "beyond_cap"
    assert "skip" not in epr.run_signal(s, c, {"kind": "chase", "cap": 0.02}, 0)
    assert "skip" not in epr.run_signal(s, c, {"kind": "chase", "cap": 0.05}, 0)


def test_chase_fills_next_candle_open_after_latency():
    s = sig()
    c = series(flat(10.0, 10))
    c[1][1] = 10.2                                    # t0+60s candle opens higher; t0 candle ignored
    r = epr.run_signal(s, c, {"kind": "chase", "cap": 0.05}, 0)
    assert abs(r["dev"] - 0.02) < 1e-9


def test_chase_skips_past_stop_and_targets():
    s = sig()
    assert epr.run_signal(s, series(flat(8.9, 10)), {"kind": "chase", "cap": 0.5}, 0)["skip"] == "past_stop"
    assert epr.run_signal(s, series(flat(15, 10)), {"kind": "chase", "cap": 9}, 0)["skip"] == "past_all_targets"


def test_limit_fills_only_on_pullback_within_wait():
    s = sig()
    prices = flat(10.5, 120) + [(10.5, 10.5, 9.99, 10.2)] + flat(10.6, 60)
    c = series(prices)
    lim1 = {"kind": "limit", "wait_h": 1}
    lim4 = {"kind": "limit", "wait_h": 4}
    assert epr.run_signal(s, c, lim1, 0)["skip"] == "no_fill"      # touch is at minute 120 > 1h
    r = epr.run_signal(s, c, lim4, 0)
    assert r["dev"] == 0.0 and abs(r["t_fill_h"] - 2.0) < 1e-9


def test_limit_gap_through_fills_at_open_not_bound():
    s = sig()
    c = series(flat(10.5, 5) + [(9.9, 9.95, 9.8, 9.9)] + flat(10.0, 20))
    is_long, bound, sl, tps = epr.prep(s)
    e = epr.find_entry({"kind": "limit", "wait_h": 1}, is_long, bound, sl, tps, c, T0)
    assert e["px"] == 9.9 and e["taker"] is False


def test_limit_skips_when_stop_trades_before_fill_edge():
    s = sig(entry_hi=10.0, sl_initial=9.0)
    c = series(flat(10.5, 5) + [(10.5, 10.5, 8.9, 9.0)] + flat(9.5, 20))
    r = epr.run_signal(s, c, {"kind": "limit", "wait_h": 1}, 0)
    # candle trades through the limit AND the stop; fill would be at the open <= sl? open 10.5 > bound
    # so the limit fills at bound first, then the same candle stops it out (adverse-first walk)
    assert r.get("reason") == "stop" and r["pnl"] < 0


def test_wait_then_chase_uses_price_at_deadline_and_cap():
    s = sig()
    far = series(flat(10.5, 80))                      # never pulls back; 5% above at the 1h deadline
    assert epr.run_signal(s, far, {"kind": "wait_chase", "wait_h": 1, "cap": 0.02}, 0)["skip"] == "beyond_cap"
    near = series(flat(10.1, 80))
    r = epr.run_signal(s, near, {"kind": "wait_chase", "wait_h": 1, "cap": 0.02}, 0)
    assert abs(r["t_fill_h"] - 1.0) < 1e-9 and abs(r["dev"] - 0.01) < 1e-9


def test_short_is_mirrored():
    s = sig(direction="short", entry_lo=10.0, entry_hi=10.5, sl_initial=11.0,
            tp_ladder=[9.5, 9, 8.5, 8, 7.5, 7, 6.5, 6])
    c = series(flat(9.8, 30))                         # 2% below zone bottom (bad side for a short)
    assert epr.run_signal(s, c, {"kind": "chase", "cap": 0.01}, 0)["skip"] == "beyond_cap"
    assert abs(epr.run_signal(s, c, {"kind": "chase", "cap": 0.02}, 0)["dev"] - 0.02) < 1e-9


def test_stop_hit_loses_about_planned_risk_and_slippage_hurts():
    s = sig()
    c = series(flat(10.0, 5) + [(10.0, 10.0, 8.9, 9.0)] + flat(9.0, 5))
    r0 = epr.run_signal(s, c, {"kind": "chase", "cap": 0.05}, 0.0)
    r5 = epr.run_signal(s, c, {"kind": "chase", "cap": 0.05}, 0.005)
    assert r0["reason"] == "stop" and -1.3 < r0["R"] < -0.95
    assert r5["pnl"] < r0["pnl"]


def test_full_ladder_win_is_positive_and_all_tp():
    s = sig()
    c = series(flat(10.0, 5) + [(10.0, 14.5, 10.0, 14.5)] + flat(14.5, 3))
    r = epr.run_signal(s, c, {"kind": "chase", "cap": 0.05}, 0)
    assert r["reason"] == "all_tp" and r["R"] > 0


def test_same_candle_stop_beats_target():
    s = sig()
    c = series(flat(10.0, 5) + [(10.0, 14.5, 8.9, 9.0)] + flat(9.0, 3))
    assert epr.run_signal(s, c, {"kind": "chase", "cap": 0.05}, 0)["reason"] == "stop"


def test_ladder_collapses_small_slices_under_ten_dollars():
    tps = [10.5 + i * 0.5 for i in range(8)]
    big = epr.ladder_plan(120.0, 10.0, tps, 0.1)
    small = epr.ladder_plan(40.0, 10.0, tps, 0.1)
    assert len(big) == 8 and len(small) < 8
    for plan in (big, small):
        assert abs(sum(f for _, f in plan) - 1.0) < 1e-9
    assert all(f * 40.0 / 10.0 * px >= 10 - 1e-9 for px, f in small)


def test_size_matches_live_risk_model_and_min_notional_skip():
    n, lev, d = epr.size(True, 10.0, 9.0)
    assert lev <= 3 and n * d <= 12 + 1e-6 and n >= 11.3
    assert epr.size(True, 10.0, 9.99) is None or epr.size(True, 10.0, 9.99)[0] * 1 >= 11.3


def test_dsr_penalises_more_trials_and_is_a_probability():
    p_few, _ = epr.deflated_sharpe(0.2, 200, 0, 3, 2, 0.001)
    p_many, _ = epr.deflated_sharpe(0.2, 200, 0, 3, 50, 0.001)
    assert 0 < p_many < p_few < 1


def test_evaluate_end_to_end_split_and_missed():
    sigs = []
    data = {}
    for i in range(10):
        s = sig(signal_id=i, open_date=f"2026-01-{i+1:02d}T00:00:00+00:00", symbol=f"S{i}")
        t0 = epr.ms(s["open_date"])
        # even: price 3% above zone, then pulls back and runs up; odd: at zone, runs to stop
        if i % 2 == 0:
            c = series(flat(10.3, 120) + flat(10.0, 5) + [(10.0, 14.5, 10.0, 14.5)] * 3, start=t0)
        else:
            c = series(flat(10.0, 5) + [(10.0, 10.0, 8.9, 9.0)] * 3 + flat(9.0, 10), start=t0)
        sigs.append(s); data[s["signal_id"]] = c
    res = epr.evaluate(sigs, lambda s: data[s["signal_id"]])
    p = res["policies"]
    assert len(p) == 11
    ch1 = p["chase<=1%"]["slip0.0"]
    assert ch1["all"]["n"] == 5 and abs(ch1["fill_rate"] - 0.5) < 1e-9     # evens skipped
    assert ch1["missed_n"] == 5 and ch1["missed_if_uncapped"]["exp_R"] > 0   # missed ones were winners
    lim = p["limit_4h"]["slip0.0"]
    assert lim["fill_rate"] == 1.0 and lim["early70"]["n"] + lim["late30"]["n"] == lim["all"]["n"]
    assert "chase<=5%" in epr.report(res)


# ── exit arm (amendment 1) ──────────────────────────────────────────────────
H4 = epr.BAR_MS


def pre_bars(n_bars, t_end, lo_fn=lambda i: 9.0, hi_fn=lambda i: 10.0):
    """n_bars 4h bars ending at t_end, one 1m candle per 4h bar is enough for aggregation."""
    out = []
    for i in range(n_bars):
        ts = t_end - (n_bars - i) * H4
        out.append([ts, 9.5, hi_fn(i), lo_fn(i), 9.5])
    return out


def test_atr_constant_range():
    bars = [[i * H4, 9.5, 10.0, 9.0, 9.5] for i in range(20)]
    assert abs(epr.atr(bars) - 1.0) < 1e-9
    assert epr.atr(bars[:10]) is None


def test_bars_4h_excludes_incomplete_bar():
    t0 = T0 + H4 // 2                                  # mid-bar
    pre = [[T0 - H4 + i * MIN, 1, 2, 0.5, 1] for i in range(5)] + [[T0 + 5 * MIN, 1, 99, 0.1, 1]]
    b = epr.bars_4h(pre, t0)
    assert len(b) == 1 and b[0][2] == 2                # the open bar (high 99) is not used


def test_swing_stop_picks_recent_fractal_below_fill_with_buffer():
    lows = [9.0 + i * 0.01 for i in range(20)]
    lows[10] = 8.0                                      # confirmed fractal low
    bars = [[i * H4, 9.5, 10.0, lows[i], 9.5] for i in range(20)]
    sl = epr.swing_stop(bars, True, 9.6)
    assert abs(sl - 8.0 * (1 - epr.STRUCT_BUF)) < 1e-9
    assert epr.swing_stop(bars, True, 7.0) is None      # nothing below fill
    highs = [10.0 - i * 0.01 for i in range(20)]; highs[12] = 11.0
    bars = [[i * H4, 9.5, highs[i], 9.0, 9.5] for i in range(20)]
    assert abs(epr.swing_stop(bars, False, 9.6) - 11.0 * (1 + epr.STRUCT_BUF)) < 1e-9


def _exit_run(xs, candles, pre, **kw):
    return epr.run_exit_signal(sig(**kw), candles, pre, xs, 0)


def test_x3_posted_stop_with_1_2_3R_targets_hits_tp1_first():
    # fill 10.0, posted stop 9.0 -> 1R=1.0: targets 11,12,13
    c = series(flat(10.0, 5) + [(10.0, 11.2, 10.0, 11.1)] + flat(11.1, 20))
    r = _exit_run(epr.exit_variants()["x3_posted_R"], c, [])
    assert r["first"] == "tp1" and r["R"] > 0


def test_exit_stop_first_counts_as_stop_and_same_candle_stop_wins():
    c = series(flat(10.0, 5) + [(10.0, 11.5, 8.9, 9.0)] + flat(9.0, 20))
    r = _exit_run(epr.exit_variants()["x3_posted_R"], c, [])
    assert r["first"] == "stop" and r["reason"] == "stop" and r["R"] < 0


def test_atr_stop_uses_k_times_atr_and_skips_without_pre_history():
    xs = epr.exit_variants()["x1_atr1.5"]
    c = series(flat(10.0, 30))
    assert _exit_run(xs, c, [])["skip"] == "no_pre"
    bars = [[T0 - (21 - i) * H4, 9.5, 10.0, 9.0, 9.5] for i in range(20)]   # ATR=1.0
    pre = [b for b in bars]
    r = _exit_run(xs, c, pre)
    assert abs(r["stop_pct"] - 0.15) < 1e-6              # 1.5 * 1.0 / 10.0


def test_exit_arm_shares_entry_fills_with_live_chase():
    c = series(flat(10.6, 30))                           # 6% above zone top -> beyond live 5% cap
    assert _exit_run(epr.exit_variants()["x3_posted_R"], c, [])["skip"] == "beyond_cap"


def test_evaluate_exits_end_to_end_reports_tp1_vs_stop():
    sigs = [sig(signal_id=i, open_date=f"2026-01-{i + 1:02d}T00:00:00+00:00") for i in range(10)]

    def load(s):
        t0 = epr.ms(s["open_date"])
        return series(flat(10.0, 5) + [(10.0, 11.2, 10.0, 11.1)] + flat(11.1, 20), start=t0)
    res = epr.evaluate_exits(sigs, load, lambda s: [], n_trials=15)
    v = res["variants"]["x3_posted_R"]["slip0.0"]
    assert v["tp1_vs_stop_rate"] == 1.0 and v["all"]["n"] == 10
    assert "x1_atr1.5" in res["variants"] and res["variants"]["x1_atr1.5"]["slip0.0"]["all"].get("n", 0) == 0
    epr.report_exits(res)
