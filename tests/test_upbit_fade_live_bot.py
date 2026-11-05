"""Upbit fade live pilot (#252): the Freqtrade bot ft-upbit-fade-hl, its config, its compose
service and its preregistration.

    python3 -m pytest tests/test_upbit_fade_live_bot.py -q
"""
import importlib.util
import json
import re
import subprocess
import sys
import threading
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FT = ROOT / "ft_userdata"
STRATEGY = FT / "user_data" / "strategies" / "UpbitFadeLiveV1.py"
CONFIG = FT / "user_data" / "configs" / "UpbitFadeLiveV1.json"
PROD = FT / "docker-compose.prod.yml"
SERVICE = "ft-upbit-fade-hl"
PREREG_ID = "upbit-krw-fade-live-pilot-2026-11"


@contextmanager
def _stubs():
    names = ("freqtrade", "freqtrade.strategy", "freqtrade.persistence")
    saved = {n: sys.modules.get(n) for n in names}
    ft, st, pe = (types.ModuleType(n) for n in names)
    st.IStrategy = object
    pe.Trade = None                     # replaced per test by a fake trade store
    sys.modules.update(dict(zip(names, (ft, st, pe))))
    try:
        yield
    finally:
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m


def strategy_module():
    with _stubs():
        spec = importlib.util.spec_from_file_location("upbit_fade_live_strategy", STRATEGY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def strategy():
    return strategy_module().UpbitFadeLiveV1


def config():
    return json.loads(CONFIG.read_text())


def services():
    return yaml.safe_load(PROD.read_text())["services"]


def prereg():
    reg = json.loads((FT / "preregistrations.json").read_text(encoding="utf-8"))
    (hit,) = [e for e in reg["preregistrations"] if e["id"] == PREREG_ID]
    return hit


def ft_roi_exit(minimal_roi, trade_minutes, profit):
    """Freqtrade 2026.7 IStrategy.min_roi_reached, as read in freqtrade/strategy/interface.py
    at 52bc96f: keys become ints at load (StrategyResolver); the largest key <= the trade's
    age in minutes applies; exit when profit > its value."""
    roi = {int(k): v for k, v in minimal_roi.items()}
    keys = [k for k in roi if k <= trade_minutes]
    return bool(keys) and profit > roi[max(keys)]


# --- strategy -----------------------------------------------------------------------------

def test_strategy_is_a_1x_short_pass_through_with_a_24h_time_exit():
    S = strategy()
    assert S.can_short is True and S.stoploss == -0.60
    assert S.minimal_roi == {"0": 100, "1440": -1}
    assert S.use_exit_signal is False and S.use_custom_stoploss is False
    assert S.position_adjustment_enable is False and S.trailing_stop is False
    assert "custom_exit" not in vars(S), "the time exit must not depend on custom_exit"
    s = S.__new__(S)
    for proposed in (1.0, 3.0, 10.0):
        assert s.leverage("CARDS/USDC:USDC", None, 1.0, proposed, 50.0, "short") == 1.0
    import pandas as pd
    df = s.populate_entry_trend(pd.DataFrame({"close": [1.0, 2.0]}), {})
    assert df["enter_long"].sum() == 0 and df["enter_short"].sum() == 0
    df = s.populate_exit_trend(df, {})
    assert df["exit_long"].sum() == 0 and df["exit_short"].sum() == 0


def test_roi_exits_at_24h_whatever_the_profit_and_never_before():
    roi = strategy().minimal_roi
    for profit in (-0.59, -0.2, 0.0, 0.07, 0.5):
        assert ft_roi_exit(roi, 1440, profit) and ft_roi_exit(roi, 2000, profit)
    for minutes in (0, 5, 600, 1439):
        assert not ft_roi_exit(roi, minutes, 0.9)       # +90% is still below the 100x bar


# --- the entry guard (#252 review, P1 2-4) -------------------------------------------------

EID = "upbit:1793858584730:CARDS"
T0_MS = 1_794_290_584_912
NOW = datetime.fromtimestamp((T0_MS + 5 * 60_000) / 1000, tz=timezone.utc)     # t0 + 5 min


def tag(eid=EID, deadline_ms=T0_MS + 7 * 60_000):
    return "upbit-fade:%s@%d" % (eid, deadline_ms)


class Row:
    """The fields of a Freqtrade Trade row the guard reads."""
    _n = 0

    def __init__(self, pair, enter_tag, is_open=True, close_profit_abs=None):
        Row._n += 1
        self.id, self.pair, self.enter_tag = Row._n, pair, enter_tag
        self.is_open, self.close_profit_abs = is_open, close_profit_abs


class FtForceEntry:
    """Freqtrade 2026.7's /forceenter path, reduced to its order of checks
    (freqtrade/rpc/rpc.py `_rpc_force_entry`, freqtrade/freqtradebot.py `execute_entry`):
    the same-pair and max-open checks run before `_exit_lock`; under the lock
    `execute_entry` calls `confirm_trade_entry` (IStrategy's default returns True), then
    creates the order and commits the trade row. `trades` is the bot's database."""

    def __init__(self, mod, trades=None, max_open_trades=2):
        self.mod, self.trades, self.max_open = mod, list(trades or []), max_open_trades
        self.exit_lock = threading.Lock()
        mod.Trade = types.SimpleNamespace(get_trades_proxy=lambda: list(self.trades))
        self.strategy = mod.UpbitFadeLiveV1.__new__(mod.UpbitFadeLiveV1)

    def pre_lock_checks(self, pair):
        open_trades = [t for t in self.trades if t.is_open]
        if any(t.pair == pair for t in open_trades):
            return "position for %s already open" % pair
        if len(open_trades) >= self.max_open:
            return "Maximum number of trades is reached."
        return None

    def under_lock(self, pair, entry_tag, now=NOW, side="short"):
        with self.exit_lock:
            confirm = getattr(self.strategy, "confirm_trade_entry", None)
            ok = True if confirm is None else confirm(
                pair=pair, order_type="market", amount=50.0, rate=1.0, time_in_force="GTC",
                current_time=now, entry_tag=entry_tag, side=side)
            if ok:
                self.trades.append(Row(pair, entry_tag))
            return ok

    def concurrent(self, requests):
        """Every request passes the pre-lock checks before any takes the lock (two
        API threads at once), then each runs `execute_entry` under the lock."""
        barrier, results = threading.Barrier(len(requests)), {}

        def call(i, pair, entry_tag):
            refused = self.pre_lock_checks(pair)
            barrier.wait()
            results[i] = refused or self.under_lock(pair, entry_tag)

        threads = [threading.Thread(target=call, args=(i, *r)) for i, r in enumerate(requests)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        return [results[i] for i in range(len(requests))]


def test_concurrent_forceenters_never_open_a_third_trade():
    ft = FtForceEntry(strategy_module())
    out = ft.concurrent([("AAA/USDC:USDC", tag("upbit:1:AAA")), ("BBB/USDC:USDC", tag("upbit:1:BBB")),
                         ("CCC/USDC:USDC", tag("upbit:1:CCC"))])
    assert out.count(True) == 2 and out.count(False) == 1
    assert sum(t.is_open for t in ft.trades) == 2


def test_concurrent_forceenters_on_one_pair_open_one_trade():
    ft = FtForceEntry(strategy_module())
    out = ft.concurrent([("CARDS/USDC:USDC", tag()), ("CARDS/USDC:USDC", tag("upbit:2:CARDS"))])
    assert sorted(out, key=str) == [False, True] and len(ft.trades) == 1


def test_an_event_is_never_traded_twice_even_after_its_trade_closed():
    ft = FtForceEntry(strategy_module(), [Row("CARDS/USDC:USDC", tag(), is_open=False,
                                              close_profit_abs=3.5)])
    assert ft.pre_lock_checks("CARDS/USDC:USDC") is None
    assert ft.under_lock("CARDS/USDC:USDC", tag()) is False
    assert ft.under_lock("CARDS/USDC:USDC", tag("upbit:9:CARDS")) is True


def test_the_deadline_is_checked_just_before_the_order():
    ft = FtForceEntry(strategy_module())
    late = datetime.fromtimestamp((T0_MS + 7 * 60_000 + 1) / 1000, tz=timezone.utc)
    assert ft.under_lock("CARDS/USDC:USDC", tag(), now=late) is False
    on_time = datetime.fromtimestamp((T0_MS + 7 * 60_000) / 1000, tz=timezone.utc)
    assert ft.under_lock("CARDS/USDC:USDC", tag(), now=on_time) is True


@pytest.mark.parametrize("entry_tag,side", [
    (None, "short"),
    ("force_entry", "short"),                                   # Freqtrade's default tag
    ("upbit-fade:" + EID, "short"),                             # no deadline
    ("upbit-fade:%s@%d" % (EID, T0_MS + 13 * 60_000), "short"),  # > 7 min ahead of now
    (tag(), "long"),
])
def test_entries_the_trigger_would_never_send_are_refused(entry_tag, side):
    ft = FtForceEntry(strategy_module())
    assert ft.under_lock("CARDS/USDC:USDC", entry_tag, side=side) is False
    assert ft.trades == []


def test_the_bot_refuses_entries_at_the_realized_loss_limit():
    closed = [Row("AAA/USDC:USDC", tag("upbit:1:AAA"), False, -40.0),
              Row("BBB/USDC:USDC", tag("upbit:1:BBB"), False, -35.0)]
    assert FtForceEntry(strategy_module(), closed).under_lock("CARDS/USDC:USDC", tag()) is False
    closed[1].close_profit_abs = -34.99
    assert FtForceEntry(strategy_module(), closed).under_lock("CARDS/USDC:USDC", tag()) is True


def test_the_guard_fails_closed():
    """Freqtrade's strategy_safe_wrapper returns default_retval=True when the callback
    raises: an error inside the guard must refuse, not confirm."""
    mod = strategy_module()
    ft = FtForceEntry(mod)

    def broken():
        raise RuntimeError("database is locked")

    mod.Trade = types.SimpleNamespace(get_trades_proxy=broken)
    assert ft.under_lock("CARDS/USDC:USDC", tag()) is False


def test_the_bot_parses_the_tag_the_trigger_sends():
    sys.path.insert(0, str(ROOT / "tests"))
    import importlib
    lt = importlib.import_module("test_upbit_fade_live_trigger").lt
    mod = strategy_module()
    assert mod.parse_entry_tag(lt.entry_tag(EID, T0_MS + lt.LATEST_ENTRY_MS)) == (
        EID, T0_MS + 7 * 60_000)
    assert (mod.TAG_PREFIX, mod.MAX_OPEN, mod.LATEST_ENTRY_MS, mod.KILL_REALIZED_PNL_USD) == (
        lt.TAG_PREFIX, lt.MAX_OPEN, lt.LATEST_ENTRY_MS, lt.KILL_REALIZED_PNL_USD)


# --- config -------------------------------------------------------------------------------

def test_config_is_dry_run_by_default_with_the_pilot_sizing():
    c = config()
    assert c["dry_run"] is True and c["dry_run_wallet"] == 150
    assert c["trading_mode"] == "futures" and c["margin_mode"] == "isolated"
    assert c["stake_currency"] == "USDC" and c["stake_amount"] == 50 and c["max_open_trades"] == 2
    assert c["force_entry_enable"] is True and c["initial_state"] == "running"
    assert c["order_types"]["stoploss_on_exchange"] is False
    assert c["order_types"]["force_entry"] == "market" and c["order_types"]["exit"] == "market"
    assert ".dryrun." in c["db_url"] and c["db_url"].endswith("UpbitFadeLiveV1.hyperliquid.sqlite")
    for key in ("minimal_roi", "stoploss", "trailing_stop"):
        assert key not in c, "the strategy owns %s; a config value would override it" % key
    assert c["exchange"]["name"] == "hyperliquid"
    assert c["exchange"]["ccxt_config"]["options"]["fetchMarkets"]["types"] == ["swap"]
    assert not c["exchange"].get("hip3_dexes")


def test_config_holds_no_keys_or_credentials():
    c = config()
    assert c["exchange"]["walletAddress"] == "" and c["exchange"]["privateKey"] == ""
    assert not re.search(r"0x[0-9a-fA-F]{40}", CONFIG.read_text())
    for k in ("username", "password", "jwt_secret_key"):
        assert c["api_server"][k] == "OVERRIDE_VIA_ENV"


def test_webhook_alerts_name_the_bot():
    hooks = {k: v for k, v in config()["webhook"].items() if isinstance(v, dict)}
    assert len(hooks) == 7 and {v["bot_name"] for v in hooks.values()} == {"UpbitFadeLiveV1"}
    assert config()["webhook"]["url"] == "http://trade-webhook:8088/freqtrade/event"


def test_the_db_guard_accepts_the_default_config(monkeypatch):
    spec = importlib.util.spec_from_file_location("guard", FT / "user_data/configs/guard_db_mode.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.delenv("FREQTRADE__DRY_RUN", raising=False)
    monkeypatch.delenv("FREQTRADE__DB_URL", raising=False)
    assert guard.validate(CONFIG)["dry_run"] is True


# --- compose ------------------------------------------------------------------------------

def test_service_copies_the_killers_pattern_on_its_own_account():
    svcs = services()
    svc, killers = svcs[SERVICE], svcs["ft-killers-scalp"]
    assert svc["image"] == killers["image"] and svc["restart"] == "always"
    assert svc["container_name"] == SERVICE
    env = svc["environment"]
    assert env["FREQTRADE__DRY_RUN"] == "${HYPERLIQUID_UPBIT_FADE_DRY_RUN:-true}"
    assert env["FREQTRADE__EXCHANGE__WALLET_ADDRESS"] == "${HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS:-}"
    assert env["FREQTRADE__EXCHANGE__PRIVATE_KEY"] == "${HYPERLIQUID_UPBIT_FADE_PRIVATE_KEY:-}"
    for side in ("public", "private"):
        assert env["FREQTRADE__EXCHANGE__CCXT_CONFIG__urls__api__" + side] == "http://hl-gateway:8080/upbit"
    for key in ("FREQTRADE__EXCHANGE__ENABLE_WS", "FREQTRADE__EXCHANGE__PAIR_WHITELIST",
                "FREQTRADE__EXCHANGE___FT_HAS_PARAMS__ohlcv_candle_limit_per_timeframe__5m",
                "FREQTRADE__EXCHANGE__CCXT_CONFIG__timeout", "FREQTRADE__INTERNALS__PROCESS_THROTTLE_SECS",
                "FREQTRADE__CANCEL_OPEN_ORDERS_ON_EXIT"):
        assert env[key] == killers["environment"][key], key
    assert env["FREQTRADE__API_SERVER__USERNAME"] == "${FT_API_USER_UPBITFADE:-${FREQTRADE__API_SERVER__USERNAME}}"
    assert env["FREQTRADE__API_SERVER__PASSWORD"] == "${FT_API_PASS_UPBITFADE:-${FREQTRADE__API_SERVER__PASSWORD}}"
    wallets = {s["environment"].get("FREQTRADE__EXCHANGE__WALLET_ADDRESS") for n, s in svcs.items()
               if n != SERVICE and isinstance(s.get("environment"), dict)}
    assert env["FREQTRADE__EXCHANGE__WALLET_ADDRESS"] not in wallets
    text = yaml.safe_dump(svc)
    assert not re.search(r"0x[0-9a-fA-F]{40}", text)


def test_service_is_no_deps_safe():
    """`up -d --no-deps ft-upbit-fade-hl` starts only this container: it depends on the
    running hl-gateway alone and nothing depends on it."""
    svcs = services()
    assert svcs[SERVICE]["depends_on"] == {"hl-gateway": {"condition": "service_healthy"}}
    for name, s in svcs.items():
        deps = s.get("depends_on") or []
        assert SERVICE not in deps, name


def test_loopback_port_is_unique_on_the_host():
    svcs = services()
    assert svcs[SERVICE]["ports"] == ["127.0.0.1:8105:8080"]
    hosts = [p.rsplit(":", 1)[0] for s in svcs.values() for p in s.get("ports") or []]
    assert len(hosts) == len(set(hosts)) and "127.0.0.1:8105" in hosts
    tw = yaml.safe_load((ROOT / "services/trade-webhook/docker-compose.yml").read_text())
    assert all(not p.startswith("127.0.0.1:8105") for s in tw["services"].values()
               for p in s.get("ports") or [])


def test_no_shared_volume_collisions_with_other_bots():
    """Every bot shares ft_user_data; each owns distinct database and log files in it."""
    svcs = services()
    assert svcs[SERVICE]["volumes"] == svcs["ft-killers-scalp"]["volumes"]
    files = {}
    for name, s in svcs.items():
        entry = " ".join(s.get("entrypoint") or []) if isinstance(s.get("entrypoint"), list) else ""
        for path in re.findall(r"/freqtrade/user_data/(?:tradesv3\.\S+?\.sqlite|logs/\S+?\.log)", entry):
            assert files.setdefault(path, name) == name, (path, files[path], name)
    mine = {p for p, n in files.items() if n == SERVICE}
    assert mine == {"/freqtrade/user_data/tradesv3.dryrun.UpbitFadeLiveV1.hyperliquid.sqlite",
                    "/freqtrade/user_data/tradesv3.live.UpbitFadeLiveV1.hyperliquid.sqlite",
                    "/freqtrade/user_data/logs/UpbitFadeLiveV1.log"}


def _run_entrypoint(tmp_path, env, guard_status=0):
    script = services()[SERVICE]["entrypoint"][2].replace("$$", "$")
    trader = tmp_path / "freqtrade"
    trader.write_text('#!/bin/sh\nprintf "trader %s %s\\n" "$FREQTRADE__DB_URL" '
                      '"${FREQTRADE__ORDER_TYPES__STOPLOSS_ON_EXCHANGE:-unset}"\n')
    trader.chmod(0o700)
    subs = 'python() { printf "guard\\n"; return "$GUARD_STATUS"; }\n'
    return subprocess.run(["/bin/sh", "-c", subs + script],
                          env={"PATH": str(tmp_path), "GUARD_STATUS": str(guard_status), **env},
                          capture_output=True, text=True, timeout=5, check=False)


def test_entrypoint_dry_run_turns_the_exchange_stop_off(tmp_path):
    r = _run_entrypoint(tmp_path, {"FREQTRADE__DRY_RUN": "true"})
    assert r.returncode == 0 and "guard" in r.stdout
    assert r.stdout.rstrip().endswith(
        "tradesv3.dryrun.UpbitFadeLiveV1.hyperliquid.sqlite false")


def test_entrypoint_live_turns_the_exchange_stop_on(tmp_path):
    keys = {"FREQTRADE__EXCHANGE__WALLET_ADDRESS": "0xabc", "FREQTRADE__EXCHANGE__PRIVATE_KEY": "0xdef"}
    r = _run_entrypoint(tmp_path, {"FREQTRADE__DRY_RUN": "false", **keys})
    assert r.returncode == 0
    assert r.stdout.rstrip().endswith("tradesv3.live.UpbitFadeLiveV1.hyperliquid.sqlite true")


@pytest.mark.parametrize("env,status", [
    ({"FREQTRADE__DRY_RUN": "false"}, 64),                                   # live without keys
    ({"FREQTRADE__DRY_RUN": "false", "FREQTRADE__EXCHANGE__WALLET_ADDRESS": "0xabc"}, 64),
    ({"FREQTRADE__DRY_RUN": "maybe"}, 64),
])
def test_entrypoint_refuses_live_without_keys_or_an_invalid_mode(tmp_path, env, status):
    r = _run_entrypoint(tmp_path, env)
    assert r.returncode == status and "trader" not in r.stdout and "guard" not in r.stdout


def test_entrypoint_stops_when_the_db_guard_fails(tmp_path):
    r = _run_entrypoint(tmp_path, {"FREQTRADE__DRY_RUN": "true"}, guard_status=78)
    assert r.returncode == 78 and "trader" not in r.stdout


def test_fleet_registries_list_the_bot():
    sys.path.insert(0, str(FT))
    try:
        import api_utils
    finally:
        sys.path.remove(str(FT))
    assert api_utils.SERVICE_API_SLUGS[SERVICE] == "UPBITFADE"
    assert api_utils.PORT_API_SLUGS[8105] == "UPBITFADE"
    bot = json.loads((FT / "bots_config.json").read_text())["bots"]["UpbitFadeLiveV1"]
    assert bot["service"] == SERVICE and bot["port"] == 8105 and bot["monitor"] is True
    assert bot["active"] is False and bot["capital_account"] == "hyperliquid-upbit-fade"
    assert bot["wallet_env"] == "HYPERLIQUID_UPBIT_FADE_WALLET_ADDRESS"
    assert "('ft-upbit-fade-hl', 8105, 'UpbitFadeLiveV1')" in (ROOT / "deploy/vps/verify_fleet.py").read_text()
    assert "export_bot_creds UPBITFADE" in (ROOT / "deploy/vps/run-health-report.sh").read_text()
    slugs = re.search(r'^SLUGS="([^"]+)"', (ROOT / "deploy/vps/preflight-credentials.sh").read_text(),
                      re.M).group(1).split()
    assert "UPBITFADE" in slugs


# --- preregistration ----------------------------------------------------------------------

def test_prereg_freezes_what_the_code_runs():
    sys.path.insert(0, str(ROOT / "tests"))
    import importlib
    lt = importlib.import_module("test_upbit_fade_live_trigger").lt
    e = prereg()
    fr = e["frozen"]
    S, c = strategy(), config()
    assert e["status"] == "open" and e["bot"] == "UpbitFadeLiveV1" and e["issue"] == "#252"
    assert e["parent"] == "upbit-krw-fade-forward-2026-11" and e["resolution"] is None
    assert fr["measurement"] == "live" and fr["epoch_start"] is None
    assert fr["direction"] == lt.SIDE == "short"
    assert fr["stake_usdc"] == lt.STAKE_USDC == c["stake_amount"] == 50
    assert fr["leverage"] == lt.LEVERAGE == 1
    assert fr["margin_mode"] == c["margin_mode"] == "isolated"
    assert fr["max_open"] == lt.MAX_OPEN == c["max_open_trades"] == 2
    assert fr["latest_entry_after_t0_s"] * 1000 == lt.LATEST_ENTRY_MS
    assert fr["time_exit_s"] == 1440 * 60 and S.minimal_roi["1440"] == -1
    assert fr["emergency_stop_ratio"] == S.stoploss == -0.6
    assert fr["dry_run_wallet_usdc"] == c["dry_run_wallet"] == 150
    assert fr["kill_realized_pnl_usdc"] == lt.KILL_REALIZED_PNL_USD == -75
    assert lt.PREREG_ID == PREREG_ID
    rules = " ".join(e["rules"])
    assert "-75 USDC" in rules and "never used in the decision of upbit-krw-fade-forward-2026-11" in rules
