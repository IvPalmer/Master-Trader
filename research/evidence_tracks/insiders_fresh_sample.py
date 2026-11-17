"""Insiders fresh-sample report under the current bounded executor (GH #28).

Splits closed dry-run trades by the frozen epoch table so the fresh sample is never
mixed with prior leverage/venue regimes, and applies the preregistered bar
(>=30 admitted signals AND PF >= 1.3 on the fresh epoch alone). The bot stays dry-run
whatever this prints: the report never recommends an allocation.

    python3 insiders_fresh_sample.py trades.json [epochs.json]
    # trades.json: [{"open_date","close_date","profit_abs","leverage","is_dry"?: bool}, ...]
    # --admitted N: receiver-admitted signal count in the fresh epoch (else closed-trade count)
"""
import json
import sys
from pathlib import Path

from common import assign_epoch, metrics

MIN_ADMITTED = 30
MIN_PF = 1.3


def report(trades, epochs_spec, admitted=None):
    epochs = [tuple(e) for e in epochs_spec["epochs"]]
    fresh = epochs_spec["fresh_epoch"]
    by_epoch, excluded = {name: [] for name, _ in epochs}, []
    for t in trades:
        if t.get("is_open") or not t.get("close_date"):
            excluded.append({"reason": "open"})
            continue
        if t.get("is_dry") is False:
            excluded.append({"reason": "live_trade_not_dry_sample"})
            continue
        label = assign_epoch(t["open_date"], epochs)   # epoch of ENTRY, not of exit
        by_epoch[label].append(t)
    out = {"epochs": {}, "excluded": excluded, "fresh_epoch": fresh}
    for name, ts in by_epoch.items():
        out["epochs"][name] = {**metrics([x["profit_abs"] for x in ts]),
                               "leverages": sorted({x.get("leverage") for x in ts if x.get("leverage") is not None}),
                               "first_open": min((x["open_date"] for x in ts), default=None)}
    f = out["epochs"][fresh]
    n = admitted if admitted is not None else f["trades"]
    pf = f["profit_factor"]
    pf_num = float("inf") if pf == "inf" else pf
    out["fresh_bar"] = {"admitted_signals": n, "required_admitted": MIN_ADMITTED, "closed_fresh_trades": f["trades"],
                        "profit_factor": pf, "required_pf": MIN_PF,
                        "status": ("insufficient_evidence" if n < MIN_ADMITTED or f["trades"] < MIN_ADMITTED
                                   else ("bar_met" if pf_num is not None and pf_num >= MIN_PF else "bar_not_met"))}
    out["allocation_recommendation"] = "none: stays dry-run; promotion needs a separate operator decision"
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    admitted = None
    if "--admitted" in args:
        i = args.index("--admitted")
        admitted = int(args[i + 1])
        del args[i:i + 2]
    here = Path(__file__).parent
    spec = json.load(open(args[1] if len(args) > 1 else here / "insiders_epochs.json"))
    print(json.dumps(report(json.load(open(args[0])), spec, admitted), indent=2))
