#!/usr/bin/env python3
"""Quick parameter optimization - tests focused combos sequentially."""
import subprocess, json, re, shutil, sys, os
from pathlib import Path

USER_DATA = Path("user_data")
DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"

# Focused parameter combos based on what we already know
COMBOS = {
    "SupertrendStrategyHyperopt": [
        # Format: (label, stoploss, trail_pos, trail_offset, roi_dict, exit_profit_offset)
        ("current",     -0.05, 0.02, 0.03, {"0":0.05,"360":0.03,"720":0.02,"1440":0.01}, 0.01),
        ("tight_sl",    -0.03, 0.02, 0.03, {"0":0.05,"360":0.03,"720":0.02,"1440":0.01}, 0.01),
        ("wide_roi",    -0.05, 0.02, 0.03, {"0":0.08,"360":0.05,"720":0.03,"1440":0.015}, 0.01),
        ("wider_roi",   -0.05, 0.03, 0.04, {"0":0.10,"360":0.07,"720":0.04,"1440":0.02}, 0.01),
        ("tight_sl+wide", -0.03, 0.02, 0.03, {"0":0.08,"360":0.05,"720":0.03,"1440":0.015}, 0.01),
        ("tight_sl+wider",-0.03, 0.03, 0.04, {"0":0.10,"360":0.07,"720":0.04,"1440":0.02}, 0.01),
        ("v_tight_sl",  -0.02, 0.015, 0.02, {"0":0.03,"360":0.02,"720":0.015,"1440":0.008}, 0.005),
        ("balanced",    -0.04, 0.02, 0.03, {"0":0.06,"360":0.04,"720":0.025,"1440":0.012}, 0.01),
        ("wide_all",    -0.07, 0.03, 0.05, {"0":0.10,"360":0.07,"720":0.04,"1440":0.02}, 0.01),
        ("asymmetric",  -0.03, 0.015, 0.02, {"0":0.05,"360":0.03,"720":0.02,"1440":0.01}, 0.005),
        ("tight_trail", -0.04, 0.01, 0.015, {"0":0.05,"360":0.03,"720":0.02,"1440":0.01}, 0.01),
        ("wide_trail",  -0.05, 0.03, 0.05, {"0":0.08,"360":0.05,"720":0.03,"1440":0.015}, 0.01),
    ],
    "MasterTraderV1Hyperopt": [
        ("current",     -0.05, 0.01, 0.02, {"0":0.07,"360":0.04,"720":0.025,"1440":0.015}, 0.0),
        ("epo_on",      -0.05, 0.01, 0.02, {"0":0.07,"360":0.04,"720":0.025,"1440":0.015}, 0.01),
        ("tight_sl+epo",-0.03, 0.01, 0.02, {"0":0.07,"360":0.04,"720":0.025,"1440":0.015}, 0.01),
        ("wide_roi+epo",-0.05, 0.015, 0.03, {"0":0.10,"360":0.06,"720":0.035,"1440":0.02}, 0.01),
        ("wider+epo",   -0.05, 0.02, 0.03, {"0":0.12,"360":0.08,"720":0.05,"1440":0.025}, 0.01),
        ("balanced+epo",-0.04, 0.015, 0.025,{"0":0.08,"360":0.05,"720":0.03,"1440":0.015}, 0.01),
        ("tight_all",   -0.03, 0.01, 0.015,{"0":0.05,"360":0.03,"720":0.02,"1440":0.01}, 0.005),
        ("wide_all",    -0.07, 0.02, 0.04, {"0":0.12,"360":0.08,"720":0.05,"1440":0.025}, 0.01),
        ("asymmetric",  -0.03, 0.01, 0.02, {"0":0.10,"360":0.06,"720":0.035,"1440":0.02}, 0.01),
        ("tight_trail", -0.04, 0.008,0.012,{"0":0.07,"360":0.04,"720":0.025,"1440":0.015}, 0.01),
    ],
}

WINDOWS = [
    ("7m_all",    "20250901-20260331"),
    ("bull",      "20250901-20251101"),
    ("bear",      "20251101-20260201"),
    ("recent",    "20260201-20260331"),
]

def modify_strategy(path, sl, tp, to, roi, epo):
    with open(path) as f: c = f.read()
    c = re.sub(r'(stoploss\s*=\s*)[-\d.]+', f'\\g<1>{sl}', c)
    c = re.sub(r'(trailing_stop_positive\s*=\s*)[\d.]+', f'\\g<1>{tp}', c)
    c = re.sub(r'(trailing_stop_positive_offset\s*=\s*)[\d.]+', f'\\g<1>{to}', c)
    if epo > 0:
        c = re.sub(r'(exit_profit_only\s*=\s*)\w+', '\\g<1>True', c)
        c = re.sub(r'(exit_profit_offset\s*=\s*)[\d.]+', f'\\g<1>{epo}', c)
    else:
        c = re.sub(r'(exit_profit_only\s*=\s*)\w+', '\\g<1>False', c)
    roi_items = ", ".join(f'"{k}": {v}' for k, v in roi.items())
    roi_str = "{" + roi_items + "}"
    c = re.sub(r'minimal_roi\s*=\s*\{[^}]+\}', f'minimal_roi = {roi_str}', c, flags=re.DOTALL)
    with open(path, 'w') as f: f.write(c)

def run_bt(config, strategy, timerange):
    r = subprocess.run([
        "docker", "run", "--rm",
        "-v", f"{USER_DATA.absolute()}:/freqtrade/user_data",
        DOCKER_IMAGE, "backtesting",
        "--strategy", strategy, "--timerange", timerange, "--timeframe", "1h",
        "--config", f"/freqtrade/user_data/configs/{config}",
        "--enable-protections", "--export", "none", "--no-color",
    ], capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    m = {}
    for line in out.split("\n"):
        if "Profit factor" in line and "│" in line:
            try: m["pf"] = float([p.strip() for p in line.split("│") if p.strip()][1])
            except: pass
        if "Absolute drawdown" in line:
            try:
                dd = [p.strip() for p in line.split("│") if p.strip()][1]
                m["dd"] = float(dd.split("(")[1].replace("%)",""))
            except: pass
        if strategy in line and "│" in line and "TOTAL" not in line:
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) >= 8:
                try:
                    m["trades"] = int(parts[1])
                    m["pnl_pct"] = float(parts[4])
                    wdl = parts[6].split()
                    m["wr"] = float(wdl[-1]) if wdl else 0
                except: pass
    return m

strategy = sys.argv[1]
config_map = {
    "SupertrendStrategyHyperopt": "backtest-SupertrendStrategy.json",
    "MasterTraderV1Hyperopt": "backtest-MasterTraderV1.json",
}
config = config_map[strategy]
combos = COMBOS[strategy]
strat_path = USER_DATA / "strategies" / f"{strategy}.py"
backup = USER_DATA / "strategies" / f"{strategy}.py.bak"
shutil.copy2(str(strat_path), str(backup))

print(f"{'Label':20s} | {'Window':10s} | {'Trades':>6} | {'WR%':>5} | {'PF':>5} | {'P&L%':>7} | {'DD%':>5} | {'Score':>7}")
print("-" * 85)

results = []
try:
    for label, sl, tp, to, roi, epo in combos:
        modify_strategy(strat_path, sl, tp, to, roi, epo)
        combo_results = {}
        total_score = 0
        for wname, tr in WINDOWS:
            m = run_bt(config, strategy, tr)
            pf = m.get("pf", 0)
            dd = m.get("dd", 100)
            pnl = m.get("pnl_pct", -100)
            trades = m.get("trades", 0)
            wr = m.get("wr", 0)
            # Score: profit/DD ratio * PF, penalize < 50 trades
            trade_mult = min(1.0, trades/50)
            score = (pnl / max(dd, 0.1)) * pf * trade_mult if pf > 0 else -99
            total_score += score
            combo_results[wname] = {**m, "score": score}
            print(f"{label:20s} | {wname:10s} | {trades:6d} | {wr:5.1f} | {pf:5.2f} | {pnl:+7.2f} | {dd:5.1f} | {score:+7.2f}")
        
        avg = total_score / len(WINDOWS)
        results.append((label, sl, tp, to, roi, epo, combo_results, avg))
        print(f"{label:20s} | {'AVG':10s} |        |       |       |         |       | {avg:+7.2f}")
        print()
finally:
    shutil.copy2(str(backup), str(strat_path))
    os.remove(str(backup))

# Sort and print summary
results.sort(key=lambda x: x[-1], reverse=True)
print("\n" + "=" * 85)
print(f" FINAL RANKING — {strategy}")
print("=" * 85)
for i, (label, sl, tp, to, roi, epo, wr, avg) in enumerate(results[:5], 1):
    roi_max = max(roi.values())
    print(f"#{i} {label:20s} SL:{sl} trail:{tp}@{to} ROI_max:{roi_max} EPO:{epo} → score:{avg:+.2f}")
    for wn, m in wr.items():
        print(f"    {wn:10s}: PF:{m.get('pf',0):5.2f} P&L:{m.get('pnl_pct',0):+6.2f}% DD:{m.get('dd',0):5.1f}% trades:{m.get('trades',0)}")
