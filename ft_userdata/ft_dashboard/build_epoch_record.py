"""Build one stopped epoch's record from frozen inputs and print it (#277).

deploy/vps/archive_bot_epoch.py runs it inside the ft-dashboard container:

    docker exec -i ft-dashboard python /app/build_epoch_record.py < spec.json

The spec holds the epoch's metadata and its raw trades, serialized by
Freqtrade's own Trade.to_json(). The snapshot is app._poll_bot's, computed once
with frozen inputs; Hyperliquid reconciliation runs here and never again.
Importing app only registers routes: polling starts in the server lifespan,
which this script never enters.
"""

import asyncio
import json
import sys

import httpx

import app
import epoch_records


async def build(spec: dict) -> dict:
    bot = {**(app._bot_meta(spec["bot_key"]) or {}), **(spec.get("bot_config") or {}),
           **(spec.get("display") or {})}
    bot.update(key=spec["bot_key"], epoch_start_ts_ms=spec["start_ms"],
               performance_starting_capital=spec["starting_capital"])
    if not bot.get("name") or not bot.get("label"):
        raise ValueError(f"{spec['bot_key']} is not in BOTS: pass its bot config")
    bot.setdefault("epoch_label", f"{spec['mode']} epoch")
    start, end = spec["start_ms"], spec["end_ms"]
    trades = [t for t in spec["trades"]
              if t.get("is_open") is False and start <= int(t.get("close_timestamp") or 0) < end]
    frozen = {
        "record_id": spec["record_id"], "end_ms": end, "reason": spec["reason"],
        "issue": spec["issue"], "profit": {}, "status": [], "whitelist": None,
        "balance": {"starting_capital": spec["starting_capital"]},
        "show_config": {"dry_run": spec["mode"] == "paper"}, "trades": trades,
    }
    async with httpx.AsyncClient() as client:
        snapshot = await app._poll_bot(client, bot, frozen=frozen)
    reconciliation = snapshot["fill_reconciliation"]["status"]
    if reconciliation not in {"ok", "not_applicable"}:
        raise ValueError(f"Hyperliquid reconciliation {reconciliation}: "
                         f"{snapshot['fill_reconciliation'].get('detail')}")
    ledger = snapshot.pop("epoch_trades")
    # A fill mismatch without an exchange price keeps Freqtrade's raw P&L; a
    # record would freeze that figure for good.
    unpriced = [t.get("trade_id") for t in ledger
                if (t.get("hyperliquid_fill_reconciliation") or {}).get("profit_correction_complete") is False]
    if unpriced:
        raise ValueError(f"P&L correction incomplete for trade(s) {unpriced}: "
                         "fills mismatch and the exchange price is unavailable")
    record = {
        "schema": epoch_records.SCHEMA, "record_id": spec["record_id"],
        "bot_key": spec["bot_key"], "mode": spec["mode"], "venue": snapshot["venue"],
        "account_group": snapshot["account_group"], "start_ms": start, "end_ms": end,
        "starting_capital": spec["starting_capital"], "reason": spec["reason"],
        "issue": spec["issue"], "source_backup": spec["source_backup"],
        "source_sha256": spec["source_sha256"],
        "totals": {
            "closed_trades": len(ledger),
            # Freqtrade's own figure; reconciliation keeps it as freqtrade_profit_abs.
            "raw_profit_abs": sum(float(t.get("freqtrade_profit_abs", t.get("profit_abs")) or 0)
                                  for t in ledger),
            "corrected_profit_abs": sum(float(t.get("profit_abs") or 0) for t in ledger),
            "reconciled_trades": sum(bool(t.get("hyperliquid_fill_mismatch")) for t in ledger),
            "fill_reconciliation": reconciliation,
        },
        "calc_version": epoch_records.CALC_VERSION, "trades": ledger, "snapshot": snapshot,
    }
    epoch_records.validate_record(record, spec["record_id"])
    return record


if __name__ == "__main__":
    try:
        result = asyncio.run(build(json.load(sys.stdin)))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"record not built: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    json.dump(result, sys.stdout, allow_nan=False)
