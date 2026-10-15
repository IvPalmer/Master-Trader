"""Cross-month OOS runner: same rules every month (no fitting). Net of Binance fee.
Run once per month with PRICES_DIR set to that month's cache:
  PRICES_DIR=<abs prices_feb> python3 oos_runner.py <abs signals_parsed_2026_02.json> Feb
"""
import sys, json
import harness as h
import t1_exit_test as t1x

FEE = 0.0004


def fee_R(entry, sl):
    risk = abs(entry - sl)
    return (2 * FEE * entry / risk) if risk > 0 else 0.0


def t1_net(trades, entry_model):
    out = []
    for t in trades:
        r = t1x.simulate_t1(t, entry_model)
        if r["realized_R"] is None or r["fill"] is None:
            continue
        out.append(r["realized_R"] - fee_R(r["fill"], t["sl"]))
    return out


def line(tag, Rs):
    n = len(Rs)
    if not n:
        return f"  {tag:<16} n=0"
    tot = sum(Rs); wins = sum(1 for x in Rs if x > 0); srt = sorted(Rs)
    d1 = (tot - srt[-1]) / (n - 1) if n > 1 else 0.0
    return f"  {tag:<16} n={n:<3} totR={tot:>+6.2f}  R/trade={tot/n:>+6.3f}  win={wins}/{n}  ex-top R/trade={d1:>+6.3f}"


def main():
    tf, label = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "?")
    trades = json.load(open(tf))
    print(f"\n===== {label}  ({tf.split('/')[-1]}, {len(trades)} signals) — net of {FEE*100:.2f}%/side =====")
    for em in ("posted", "market", "edge"):
        print(line(f"{em}+t1", t1_net(trades, em)))


if __name__ == "__main__":
    main()
