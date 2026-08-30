"""Invariants from the 2026-08-30 live-fleet security review.

Each test pins one finding so it cannot silently regress:

  1. The signal receivers authenticate their trading ingress, and every client
     that talks to them is wired with a token.
  2. ShortKeltnerV2HL does not accept force-entry it has no use for.
  3. ShortKeltnerV2HL reports trades like the rest of the fleet.
  4. The macro-gate watchdog checks every column the gate actually reads.
  5. No live config carries a usable API credential, and per-bot credential
     slugs agree across compose, api_utils and the dashboard.

These are cheap file-level assertions on purpose: the fleet holds real money
and the failure mode being defended against is a quiet configuration drift,
not a subtle algorithmic bug.
"""
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
FT_DIR = ROOT / "ft_userdata"
CONFIGS = FT_DIR / "user_data" / "configs"
STRATEGIES = FT_DIR / "user_data" / "strategies"
COMPOSE_PROD = FT_DIR / "docker-compose.prod.yml"

LIVE_CONFIGS = [
    "KeltnerBounceV1.json",
    "FundingFadeV1.live.json",
    "OITrendPullbackV1.live.json",
    "KillersScalpV1.json",
    "InsidersScalpV2.json",
    "ShortKeltnerV2HL-live.json",
]

# Bot services that expose a Freqtrade API and therefore may be issued their
# own credentials. Keep in sync with api_utils.SERVICE_API_SLUGS.
EXPECTED_SLUGS = {
    "KELTNER", "FUNDINGFADE", "OITREND", "KILLERS", "INSIDERS", "SHORTKELTNER",
}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PROD.read_text())


def _config(name: str) -> dict:
    return json.loads((CONFIGS / name).read_text())


# ── 1. Receiver ingress authentication ────────────────────────────────────


def test_receiver_refuses_to_start_without_an_ingress_token():
    """The receiver's own guard, asserted from the repo side.

    `POST /event` opens leveraged positions and the container shares
    dokploy-network with unrelated applications, so 'no token configured'
    must be a startup failure, never a fall-open.
    """
    source = (ROOT / "services" / "killers-receiver" / "app" / "main.py").read_text()
    assert "KILLERS_INGRESS_TOKEN" in source
    assert "raise RuntimeError(" in source
    assert "secrets.compare_digest" in source, (
        "token comparison must be constant-time"
    )
    assert "dependencies=[Depends(_require_ingress_token)]" in source, (
        "auth must be an app-level dependency so new routes are protected "
        "by default, not opt-in per route"
    )


def test_both_receivers_get_a_token_and_they_are_different_variables(compose):
    """One token per funded account, so a leak of one cannot drive the other."""
    killers = compose["services"]["killers-receiver"]["environment"]
    insiders = compose["services"]["insiders-receiver"]["environment"]
    assert "KILLERS_INGRESS_TOKEN" in killers["KILLERS_INGRESS_TOKEN"]
    assert "INSIDERS_INGRESS_TOKEN" in insiders["KILLERS_INGRESS_TOKEN"]
    assert killers["KILLERS_INGRESS_TOKEN"] != insiders["KILLERS_INGRESS_TOKEN"]


@pytest.mark.parametrize(
    "service,token_var",
    [
        ("ft-killers-scalp", "KILLERS_INGRESS_TOKEN"),
        ("ft-insiders-scalp", "INSIDERS_INGRESS_TOKEN"),
    ],
)
def test_strategy_containers_carry_the_matching_receiver_token(
    compose, service, token_var
):
    """KillersScalpV1.custom_stoploss polls the receiver for moved stops.

    Without the token that call 401s and receiver-moved stops stop being
    applied, so the wiring is part of the risk control, not a nicety.
    """
    env = compose["services"][service]["environment"]
    assert token_var in env["SIGNAL_RECEIVER_TOKEN"]


def test_dashboard_carries_both_receiver_tokens(compose):
    """The dashboard reads /ingress, which is now authenticated."""
    env = compose["services"]["ft-dashboard"]["environment"]
    assert "KILLERS_INGRESS_TOKEN" in env["KILLERS_RECEIVER_TOKEN"]
    assert "INSIDERS_INGRESS_TOKEN" in env["INSIDERS_RECEIVER_TOKEN"]


def test_every_receiver_client_sends_a_bearer_header():
    """All four callers must actually attach the token, not just receive it."""
    callers = {
        "observer": ROOT / "killers_bot" / "observer.py",
        "strategy": STRATEGIES / "KillersScalpV1.py",
        "dashboard": FT_DIR / "ft_dashboard" / "app.py",
        "insiders_bridge": FT_DIR / "insiders_bridge" / "listener.py",
    }
    for name, path in callers.items():
        assert "Bearer " in path.read_text(), (
            f"{name} ({path.name}) talks to a receiver but never sends a bearer token"
        )


# ── 2 & 3. ShortKeltnerV2HL live-config hardening ─────────────────────────


def test_short_keltner_does_not_enable_force_entry():
    """Nothing issues /forceenter to this bot; the endpoint is pure surface."""
    assert _config("ShortKeltnerV2HL-live.json")["force_entry_enable"] is False


def test_short_keltner_reports_trades_like_the_rest_of_the_fleet():
    """It was the only live bot with no entry/exit notification path."""
    webhook = _config("ShortKeltnerV2HL-live.json")["webhook"]
    assert webhook["enabled"] is True
    assert webhook["url"].startswith("http://trade-webhook:8088/")
    for key in ("webhookentry", "webhookentryfill", "webhookexit",
                "webhookexitfill", "webhookstatus"):
        assert key in webhook, f"missing {key}"
        assert webhook[key]["bot_name"], f"{key} has no bot_name"


def test_short_keltner_webhook_reports_short_futures_fields():
    """A short futures bot whose alerts omit direction/leverage is misleading."""
    webhook = _config("ShortKeltnerV2HL-live.json")["webhook"]
    for key in ("webhookentry", "webhookentryfill"):
        assert webhook[key]["direction"] == "{direction}"
        assert webhook[key]["leverage"] == "{leverage}"
    for key in ("webhookexit", "webhookexitfill"):
        assert webhook[key]["direction"] == "{direction}"
        assert webhook[key]["exit_reason"] == "{exit_reason}"


# ── 4. Macro-gate watchdog covers every gate input ────────────────────────


def _load_strategy(filename: str):
    """Import a strategy with freqtrade/talib stubbed out."""
    names = ["freqtrade", "freqtrade.strategy", "talib", "talib.abstract"]
    saved = {name: sys.modules.get(name) for name in names}
    freqtrade = types.ModuleType("freqtrade")
    strategy = types.ModuleType("freqtrade.strategy")
    strategy.IStrategy = object
    strategy.informative = lambda *a, **k: (lambda fn: fn)
    strategy.stoploss_from_absolute = lambda **k: k["stop_rate"] / k["current_rate"]
    talib = types.ModuleType("talib")
    talib_abstract = types.ModuleType("talib.abstract")
    talib.abstract = talib_abstract
    sys.modules.update({
        "freqtrade": freqtrade, "freqtrade.strategy": strategy,
        "talib": talib, "talib.abstract": talib_abstract,
    })
    try:
        path = STRATEGIES / filename
        spec = importlib.util.spec_from_file_location(f"hard_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_macro_gate_watchdog_declares_every_column_the_gate_reads():
    """The watchdog list and the gate expression must not drift apart.

    They did: the gate read btc_usdc_sma50_slope_1h while the watchdog did
    not check it, so a NaN slope — the likeliest fault on Hyperliquid's short
    history — blocked every entry with no warning.
    """
    module = _load_strategy("ShortKeltnerV2HL.py")
    declared = set(module.ShortKeltnerV2HL.MACRO_GATE_COLUMNS)

    source = (STRATEGIES / "ShortKeltnerV2HL.py").read_text()
    gate_block = source.split('dataframe["btc_bear"] = (')[1].split(").astype(int)")[0]
    read = set(re.findall(r'gate\["([a-z0-9_]+)"\]', gate_block))

    assert read, "could not parse the btc_bear expression"
    assert read <= declared, (
        f"gate reads columns the watchdog never checks: {sorted(read - declared)}"
    )
    assert "btc_usdc_sma50_slope_1h" in declared, (
        "the slope column is the original regression — keep it declared"
    )


def test_macro_gate_fails_closed_and_warns_when_the_slope_is_nan(caplog):
    """NaN slope must block entries AND produce the warning."""
    pd = pytest.importorskip("pandas")
    module = _load_strategy("ShortKeltnerV2HL.py")
    cls = module.ShortKeltnerV2HL
    strategy = cls.__new__(cls)

    n = 3
    frame = pd.DataFrame({
        "close": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "volume": [10.0] * n,
        # Every gate input says "bear" except the slope, which is NaN.
        "btc_usdc_close_1h": [100.0] * n,
        "btc_usdc_sma50_1h": [200.0] * n,
        "btc_usdc_sma200_1h": [200.0] * n,
        "btc_usdc_sma50_slope_1h": [float("nan")] * n,
        "btc_usdc_sma200_1d": [200.0] * n,
    })
    module.ta = types.SimpleNamespace(SMA=lambda *a, **k: None,
                                      RSI=lambda *a, **k: pd.Series([50.0] * n))

    with caplog.at_level("WARNING"):
        out = strategy.populate_indicators(frame, {"pair": "SOL/USDC:USDC"})

    assert out["btc_bear"].iloc[-1] == 0, "NaN input must fail the gate CLOSED"
    assert "btc_usdc_sma50_slope_1h" in caplog.text, (
        f"the NaN slope must be named in the warning; got: {caplog.text!r}"
    )


def test_macro_gate_rewrite_did_not_change_what_the_bot_trades():
    """The reindex rewrite must be behaviour-preserving, not just tidier.

    btc_bear decides when a live account opens a short. Compare the deployed
    expression against the pre-rewrite one across index shapes, NaN patterns
    and extra columns — they must agree exactly, and the result must stay
    aligned to the original index.
    """
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")

    cols = list(_load_strategy("ShortKeltnerV2HL.py").ShortKeltnerV2HL.MACRO_GATE_COLUMNS)
    rng = np.random.default_rng(7)
    n = 200

    def before(df):
        return (
            (df["btc_usdc_close_1h"] < df["btc_usdc_sma50_1h"])
            & (df["btc_usdc_close_1h"] < df["btc_usdc_sma200_1h"])
            & (df["btc_usdc_sma50_slope_1h"] < 0)
            & (df["btc_usdc_close_1h"] < df["btc_usdc_sma200_1d"])
        ).astype(int)

    def after(df):
        g = df.reindex(columns=cols)
        return (
            (g["btc_usdc_close_1h"] < g["btc_usdc_sma50_1h"])
            & (g["btc_usdc_close_1h"] < g["btc_usdc_sma200_1h"])
            & (g["btc_usdc_sma50_slope_1h"] < 0)
            & (g["btc_usdc_close_1h"] < g["btc_usdc_sma200_1d"])
        ).astype(int)

    for index in (
        pd.RangeIndex(n),
        pd.RangeIndex(start=50, stop=50 + n),
        pd.Index(rng.permutation(n)),
        pd.date_range("2026-01-01", periods=n, freq="h"),
    ):
        data = {}
        for col in cols:
            series = pd.Series(rng.normal(100, 5, n))
            data[col] = series.mask(rng.random(n) < 0.08).values
        data["unrelated_column"] = rng.normal(0, 1, n)
        frame = pd.DataFrame(data, index=index)

        expected, actual = before(frame), after(frame)
        assert actual.equals(expected), f"btc_bear changed on {type(index).__name__}"
        assert actual.index.equals(frame.index), "reindex must not move the index"

    # A column the informative never produced must fail the gate CLOSED rather
    # than raise KeyError and kill the candle.
    partial = pd.DataFrame(
        {c: [100.0] * 3 for c in cols if c != "btc_usdc_sma50_slope_1h"}
    )
    assert (after(partial) == 0).all()


# ── 5. Credentials ────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", LIVE_CONFIGS)
def test_live_configs_carry_no_usable_api_credential(name):
    """Committed credentials become live defaults the moment env is dropped.

    OVERRIDE_VIA_ENV is also shorter than freqtrade's 32-char minimum for
    jwt_secret_key, so a bot started without its env fails schema validation
    instead of coming up on a public default key.
    """
    api = _config(name)["api_server"]
    for field in ("username", "password", "jwt_secret_key"):
        assert api[field] == "OVERRIDE_VIA_ENV", (
            f"{name}: api_server.{field} must be the OVERRIDE_VIA_ENV "
            f"placeholder, not a real or default credential"
        )


def _fresh_api_utils(monkeypatch, **env):
    """Reimport api_utils under a controlled environment."""
    import importlib
    for key in ("FREQTRADE__API_SERVER__USERNAME", "FREQTRADE__API_SERVER__PASSWORD",
                "FT_ALLOW_LEGACY_API_CREDS"):
        monkeypatch.delenv(key, raising=False)
    for slug in EXPECTED_SLUGS:
        monkeypatch.delenv(f"FT_API_USER_{slug}", raising=False)
        monkeypatch.delenv(f"FT_API_PASS_{slug}", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(str(FT_DIR))
    import api_utils
    return importlib.reload(api_utils)


def test_legacy_default_credentials_are_never_tried_unless_allowed(monkeypatch):
    """The flag has to mean what it says.

    freqtrade's published freqtrader/mastertrader defaults must not be an
    automatic retry: that turns any reachable bot into a guessable target and
    hides a bot running without its env override. Earlier the fallback also
    fired whenever no shared pair was configured, which quietly reopened it
    for a credential-less cron.
    """
    mod = _fresh_api_utils(monkeypatch)
    assert mod.auth_candidates_for("keltnerbouncev1") == (), (
        "no credentials configured and legacy disallowed must yield nothing"
    )

    mod = _fresh_api_utils(monkeypatch, FT_ALLOW_LEGACY_API_CREDS="true")
    assert [a.username for a in mod.auth_candidates_for()] == ["freqtrader"]


def test_per_bot_credentials_resolve_by_service_and_by_loopback_port(monkeypatch):
    """The host-side health report reaches bots by port, not by service name.

    Without port resolution, opting one bot into its own credentials blinds
    the daily report for every other bot.
    """
    mod = _fresh_api_utils(
        monkeypatch,
        FREQTRADE__API_SERVER__USERNAME="shared",
        FREQTRADE__API_SERVER__PASSWORD="sharedpw",
        FT_API_USER_KELTNER="keltner-user",
        FT_API_PASS_KELTNER="keltner-pw",
    )
    by_service = mod.auth_candidates_for("ft-keltner-bounce")
    by_port = mod.auth_candidates_for("127.0.0.1", port=8095)
    for candidates in (by_service, by_port):
        assert [a.username for a in candidates] == ["keltner-user", "shared"]

    # A bot with no per-bot secret still resolves to the shared pair only.
    assert [a.username for a in mod.auth_candidates_for("127.0.0.1", port=8096)] == [
        "shared"
    ]
    assert set(mod.PORT_API_SLUGS.values()) == EXPECTED_SLUGS


def test_half_configured_per_bot_credentials_are_reported(monkeypatch, caplog):
    """Compose resolves user and password independently.

    Setting only FT_API_USER_<SLUG> starts the bot on a dedicated user with the
    shared password while every client falls back to the shared pair and gets
    401. That must not be silent.
    """
    mod = _fresh_api_utils(
        monkeypatch,
        FREQTRADE__API_SERVER__USERNAME="shared",
        FREQTRADE__API_SERVER__PASSWORD="sharedpw",
        FT_API_USER_KILLERS="only-the-user",
    )
    with caplog.at_level("ERROR"):
        candidates = mod.auth_candidates_for("ft-killers-scalp")
    assert [a.username for a in candidates] == ["shared"]
    assert "half-configured" in caplog.text


def test_exporter_service_names_resolve_to_real_compose_services(compose):
    """A bot the exporter cannot reach sits outside the circuit breaker.

    OITrendPullbackV1 fell back to 'oitrendpullback' while compose names the
    service 'oi-trend-pullback', so a LIVE bot was silently excluded from the
    breaker's capital math.
    """
    import ast

    source = (FT_DIR / "metrics_exporter.py").read_text()
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "_load_bots_config"
    )
    literal = next(n for n in ast.walk(fn) if isinstance(n, ast.Dict))
    service_map = {
        ast.literal_eval(k): ast.literal_eval(v)
        for k, v in zip(literal.keys, literal.values)
    }

    bots = json.loads((FT_DIR / "bots_config.json").read_text())["bots"]
    for name, info in bots.items():
        if not info.get("active", True):
            continue
        service = service_map.get(
            name, name.lower().replace("v1", "").replace("strategy", "")
        )
        assert service in compose["services"], (
            f"exporter would scrape http://{service}:8080 for {name}, "
            f"which is not a compose service — that bot is invisible to the "
            f"circuit breaker"
        )


def test_receiver_stop_refresh_throttles_failed_lookups():
    """A receiver outage must not schedule an HTTP call every bot loop.

    custom_stoploss runs per open trade per loop; only a SUCCESSFUL lookup used
    to stamp _sl_cache_updated, so the TTL guard never engaged during exactly
    the outage it exists for.
    """
    source = (STRATEGIES / "KillersScalpV1.py").read_text()
    body = source.split("def done(completed)")[1].split("future.add_done_callback")[0]
    stamps = body.count("self._sl_cache_updated[trade_id] = time.monotonic()")
    assert stamps >= 2, (
        "the attempt timestamp must be written on the failure path too, not "
        "only when a stop comes back"
    )


def test_per_bot_credential_slugs_agree_across_compose_api_utils_dashboard(compose):
    """Three components resolve per-bot credentials from the same slugs.

    The dashboard is built from its own context and cannot import api_utils,
    so the duplication is deliberate — this test is what keeps it honest.
    """
    compose_text = COMPOSE_PROD.read_text()
    compose_slugs = set(re.findall(r"FT_API_USER_([A-Z]+)", compose_text))

    api_utils_slugs = set(re.findall(
        r'"[a-z0-9-]+": "([A-Z]+)",', (FT_DIR / "api_utils.py").read_text()
    ))
    dash_text = (FT_DIR / "ft_dashboard" / "app.py").read_text()
    dash_block = dash_text.split("SERVICE_API_SLUGS = {")[1].split("}")[0]
    dashboard_slugs = set(re.findall(r'"([A-Z]+)"', dash_block))

    assert compose_slugs == EXPECTED_SLUGS, compose_slugs
    assert api_utils_slugs == EXPECTED_SLUGS, api_utils_slugs
    assert dashboard_slugs == EXPECTED_SLUGS, dashboard_slugs


@pytest.mark.parametrize(
    "service,slug",
    [
        ("keltnerbouncev1", "KELTNER"),
        ("fundingfadev1", "FUNDINGFADE"),
        ("oi-trend-pullback", "OITREND"),
        ("ft-killers-scalp", "KILLERS"),
        ("ft-insiders-scalp", "INSIDERS"),
        ("ft-short-keltner-hl-live", "SHORTKELTNER"),
    ],
)
def test_each_bot_prefers_its_own_credentials_and_falls_back_to_the_fleet(
    compose, service, slug
):
    """Per-bot secrets are opt-in: unset must render the shared value.

    That is what makes this migratable one bot at a time instead of a
    flag-day rotation across six money-holding containers.
    """
    env = compose["services"][service]["environment"]
    for field, var in (
        ("USERNAME", f"FT_API_USER_{slug}"),
        ("PASSWORD", f"FT_API_PASS_{slug}"),
        ("JWT_SECRET_KEY", f"FT_API_JWT_{slug}"),
    ):
        value = env[f"FREQTRADE__API_SERVER__{field}"]
        assert value == (
            f"${{{var}:-${{FREQTRADE__API_SERVER__{field}}}}}"
        ), f"{service}.{field} = {value}"


@pytest.mark.parametrize(
    "service,slug",
    [("killers-receiver", "KILLERS"), ("insiders-receiver", "INSIDERS")],
)
def test_receivers_authenticate_to_their_own_bot(compose, service, slug):
    """A receiver must hold the credentials of the bot it drives, not another."""
    env = compose["services"][service]["environment"]
    assert env["KILLERS_FT_USERNAME"] == (
        f"${{FT_API_USER_{slug}:-${{FREQTRADE__API_SERVER__USERNAME}}}}"
    )
    assert env["KILLERS_FT_PASSWORD"] == (
        f"${{FT_API_PASS_{slug}:-${{FREQTRADE__API_SERVER__PASSWORD}}}}"
    )
