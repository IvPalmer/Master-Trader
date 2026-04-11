"""
Stage 1: Data Preparation
=========================

Downloads historical price data for all required pairs and timeframes
from Binance via Freqtrade Docker containers. Validates that downloaded
files exist and cover the requested date range.

This module does NOT run backtests — it only ensures data is ready.
"""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from .registry import (
    CONFIGS_DIR,
    DATA_DIR,
    FT_DIR,
    get_active_strategies,
    get_all_timeframes,
    get_futures_strategies,
    get_mode,
    get_spot_strategies,
)

log = logging.getLogger("engine.data")

# ── Constants ────────────────────────────────────────────────────────────────

BINANCE_SPOT_TICKER = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_FUTURES_TICKER = "https://fapi.binance.com/fapi/v1/ticker/24hr"

STABLECOIN_BASES = {"USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDT", "USDP", "PYUSD"}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

SPOT_DATA_DIR = DATA_DIR / "binance"
FUTURES_DATA_DIR = DATA_DIR / "binance" / "futures"

DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"
DOCKER_VOLUME = f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data"
DOCKER_TIMEOUT = 600  # 10 minutes for large downloads

# Timeframe detail: always download 5m for --timeframe-detail support
DETAIL_TF = "5m"


# ── Pair Fetching ────────────────────────────────────────────────────────────

def _is_excluded(symbol: str) -> bool:
    """Check if a symbol should be excluded (stablecoins, leveraged tokens)."""
    base = symbol.replace("USDT", "")
    if base in STABLECOIN_BASES:
        return True
    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return True
    return False


def fetch_top_pairs_spot(
    limit: int = 50,
    min_volume_usd: float = 20_000_000,
) -> list[str]:
    """
    Fetch top Binance spot pairs by 24h quote volume.

    Returns pairs formatted as 'BTC/USDT' for Freqtrade.
    """
    log.info("Fetching top %d spot pairs (min vol $%.0fM)...",
             limit, min_volume_usd / 1_000_000)

    try:
        resp = requests.get(BINANCE_SPOT_TICKER, timeout=30)
        resp.raise_for_status()
        tickers = resp.json()
    except requests.RequestException as e:
        log.error("Failed to fetch spot tickers: %s", e)
        raise

    # Filter USDT pairs, exclude stablecoins and leveraged tokens
    usdt_pairs = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if _is_excluded(symbol):
            continue
        quote_vol = float(t.get("quoteVolume", 0))
        if quote_vol < min_volume_usd:
            continue
        usdt_pairs.append((symbol, quote_vol))

    # Sort by volume descending, take top N
    usdt_pairs.sort(key=lambda x: x[1], reverse=True)
    top = usdt_pairs[:limit]

    # Convert BTCUSDT -> BTC/USDT
    pairs = [f"{sym.replace('USDT', '')}/USDT" for sym, _ in top]

    log.info("Found %d spot pairs above $%.0fM volume", len(pairs), min_volume_usd / 1_000_000)
    if pairs:
        log.debug("Top 5: %s", pairs[:5])

    return pairs


def fetch_top_pairs_futures(
    limit: int = 20,
    min_volume_usd: float = 20_000_000,
) -> list[str]:
    """
    Fetch top Binance futures pairs by 24h volume.

    Returns pairs formatted as 'BTC/USDT:USDT' for Freqtrade futures.
    """
    log.info("Fetching top %d futures pairs...", limit)

    try:
        resp = requests.get(BINANCE_FUTURES_TICKER, timeout=30)
        resp.raise_for_status()
        tickers = resp.json()
    except requests.RequestException as e:
        log.error("Failed to fetch futures tickers: %s", e)
        raise

    usdt_pairs = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if _is_excluded(symbol):
            continue
        quote_vol = float(t.get("quoteVolume", 0))
        if quote_vol < min_volume_usd:
            continue
        usdt_pairs.append((symbol, quote_vol))

    usdt_pairs.sort(key=lambda x: x[1], reverse=True)
    top = usdt_pairs[:limit]

    # Convert BTCUSDT -> BTC/USDT:USDT
    pairs = [f"{sym.replace('USDT', '')}/USDT:USDT" for sym, _ in top]

    log.info("Found %d futures pairs", len(pairs))
    if pairs:
        log.debug("Top 5: %s", pairs[:5])

    return pairs


# ── Data Download ────────────────────────────────────────────────────────────

def _build_timerange(days: int) -> str:
    """Build a Freqtrade timerange string: YYYYMMDD-YYYYMMDD."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def download_data(
    pairs: list[str],
    timeframes: list[str],
    timerange: str,
    trading_mode: str = "spot",
    image: str = DOCKER_IMAGE,
) -> bool:
    """
    Download data via Freqtrade Docker container.

    Args:
        pairs: List of pairs (e.g. ['BTC/USDT'] or ['BTC/USDT:USDT'])
        timeframes: List of timeframes (e.g. ['1h', '1d', '5m'])
        timerange: Freqtrade timerange string (YYYYMMDD-YYYYMMDD)
        trading_mode: 'spot' or 'futures'
        image: Docker image to use

    Returns:
        True on success, False on failure.
    """
    if not pairs:
        log.warning("No pairs to download — skipping")
        return True

    if not timeframes:
        log.warning("No timeframes to download — skipping")
        return True

    pairs_str = " ".join(pairs)
    tfs_str = " ".join(sorted(set(timeframes)))

    log.info("Downloading %s data: %d pairs x %d timeframes, range %s",
             trading_mode, len(pairs), len(timeframes), timerange)

    cmd = [
        "docker", "run", "--rm",
        "-v", DOCKER_VOLUME,
        image,
        "download-data",
        "--exchange", "binance",
        "--pairs", *pairs,
        "--timeframes", *timeframes,
        "--timerange", timerange,
        "--config", "/freqtrade/user_data/configs/backtest_base.json",
    ]

    # Futures-specific flags
    if trading_mode == "futures":
        cmd.extend(["--trading-mode", "futures"])

    log.debug("Docker command: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DOCKER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error("Data download timed out after %ds", DOCKER_TIMEOUT)
        return False

    if result.returncode != 0:
        log.error("Data download failed (rc=%d):\n%s", result.returncode, result.stderr[-2000:])
        return False

    # Log any warnings from stdout
    if result.stdout:
        for line in result.stdout.strip().split("\n")[-10:]:
            log.debug("freqtrade: %s", line)

    log.info("Download complete for %s (%d pairs)", trading_mode, len(pairs))
    return True


# ── Data Validation ──────────────────────────────────────────────────────────

def _feather_filename(pair: str, timeframe: str, trading_mode: str = "spot") -> str:
    """
    Build the expected .feather filename.

    Spot:    BTC_USDT-1h.feather
    Futures: BTC_USDT_USDT-1h-futures.feather
    """
    # BTC/USDT -> BTC_USDT, BTC/USDT:USDT -> BTC_USDT_USDT
    sanitized = pair.replace("/", "_").replace(":", "_")
    if trading_mode == "futures":
        return f"{sanitized}-{timeframe}-futures.feather"
    return f"{sanitized}-{timeframe}.feather"


def _get_data_dir(trading_mode: str) -> Path:
    """Return the correct data directory for the trading mode."""
    if trading_mode == "futures":
        return FUTURES_DATA_DIR
    return SPOT_DATA_DIR


def validate_data(
    pairs: list[str],
    timeframes: list[str],
    timerange: str,
    trading_mode: str = "spot",
) -> dict:
    """
    Check that .feather files exist for all pair/timeframe combos.

    Returns a validation report dict:
        {
            "valid": bool,
            "total": int,
            "found": int,
            "missing": int,
            "missing_files": [{"pair": ..., "timeframe": ..., "file": ...}, ...],
            "errors": [str, ...],
        }
    """
    data_dir = _get_data_dir(trading_mode)
    missing_files = []
    found = 0
    total = 0
    errors = []

    if not data_dir.exists():
        return {
            "valid": False,
            "total": len(pairs) * len(timeframes),
            "found": 0,
            "missing": len(pairs) * len(timeframes),
            "missing_files": [],
            "errors": [f"Data directory does not exist: {data_dir}"],
        }

    for pair in pairs:
        for tf in timeframes:
            total += 1
            fname = _feather_filename(pair, tf, trading_mode)
            fpath = data_dir / fname

            if fpath.exists():
                # Check file is not empty (corrupted downloads)
                if fpath.stat().st_size < 100:
                    errors.append(f"Suspiciously small file ({fpath.stat().st_size}B): {fname}")
                    missing_files.append({"pair": pair, "timeframe": tf, "file": fname})
                else:
                    found += 1
            else:
                missing_files.append({"pair": pair, "timeframe": tf, "file": fname})

    missing = total - found
    valid = missing == 0 and len(errors) == 0

    report = {
        "valid": valid,
        "total": total,
        "found": found,
        "missing": missing,
        "missing_files": missing_files,
        "errors": errors,
    }

    if valid:
        log.info("Validation passed: %d/%d files present (%s)", found, total, trading_mode)
    else:
        log.warning("Validation issues: %d/%d files missing, %d errors (%s)",
                     missing, total, len(errors), trading_mode)
        for mf in missing_files[:10]:
            log.debug("  Missing: %s", mf["file"])
        if len(missing_files) > 10:
            log.debug("  ... and %d more", len(missing_files) - 10)

    return report


# ── Main Entry Point ─────────────────────────────────────────────────────────

def run_data_stage(
    mode_name: str = "fast",
    strategies: Optional[list[str]] = None,
    days: int = 400,
) -> dict:
    """
    Main entry point for Stage 1: Data Preparation.

    1. Determine which pairs/timeframes are needed based on active strategies
    2. Fetch top pairs from Binance API (spot and/or futures)
    3. Download via Freqtrade Docker
    4. Validate downloaded data

    Args:
        mode_name: Operating mode from registry ('fast', 'thorough', 'rigorous')
        strategies: Optional list of strategy names to limit scope (default: all active)
        days: Number of days of data to download (default: 400 = 1 year + buffer)

    Returns:
        Stage result dict with keys:
            stage, status, timerange,
            spot_pairs, futures_pairs, timeframes,
            spot_download, futures_download,
            spot_validation, futures_validation,
            errors
    """
    log.info("=" * 60)
    log.info("Stage 1: Data Preparation (mode=%s, days=%d)", mode_name, days)
    log.info("=" * 60)

    # Validate mode exists (raises KeyError if invalid)
    get_mode(mode_name)

    timerange = _build_timerange(days)
    result = {
        "stage": "data",
        "status": "running",
        "timerange": timerange,
        "spot_pairs": [],
        "futures_pairs": [],
        "timeframes": [],
        "spot_download": None,
        "futures_download": None,
        "spot_validation": None,
        "futures_validation": None,
        "errors": [],
    }

    # ── Determine scope ──────────────────────────────────────────────────

    active = get_active_strategies()
    if strategies:
        # Filter to requested strategies only
        active = {k: v for k, v in active.items() if k in strategies}
        unknown = set(strategies) - set(active.keys())
        if unknown:
            log.warning("Unknown strategies ignored: %s", unknown)

    if not active:
        result["status"] = "error"
        result["errors"].append("No active strategies found")
        return result

    spot_strats = {k: v for k, v in active.items() if v["trading_mode"] == "spot"}
    futures_strats = {k: v for k, v in active.items() if v["trading_mode"] == "futures"}

    # Collect all required timeframes from selected strategies
    all_tfs = set()
    for s in active.values():
        all_tfs.add(s["timeframe"])
        all_tfs.update(s.get("informative_tfs", []))
    # Always include 5m for --timeframe-detail support
    all_tfs.add(DETAIL_TF)

    all_tfs_list = sorted(all_tfs)
    result["timeframes"] = all_tfs_list

    log.info("Strategies: %d spot, %d futures", len(spot_strats), len(futures_strats))
    log.info("Timeframes: %s", all_tfs_list)
    log.info("Timerange: %s", timerange)

    # ── Fetch pairs ──────────────────────────────────────────────────────

    spot_pairs = []
    futures_pairs = []

    if spot_strats:
        try:
            spot_pairs = fetch_top_pairs_spot(limit=50)
            result["spot_pairs"] = spot_pairs
        except Exception as e:
            msg = f"Failed to fetch spot pairs: {e}"
            log.error(msg)
            result["errors"].append(msg)

    if futures_strats:
        try:
            futures_pairs = fetch_top_pairs_futures(limit=20)
            result["futures_pairs"] = futures_pairs
        except Exception as e:
            msg = f"Failed to fetch futures pairs: {e}"
            log.error(msg)
            result["errors"].append(msg)

    # ── Download data ────────────────────────────────────────────────────

    if spot_pairs:
        log.info("Downloading spot data...")
        ok = download_data(
            pairs=spot_pairs,
            timeframes=all_tfs_list,
            timerange=timerange,
            trading_mode="spot",
        )
        result["spot_download"] = "success" if ok else "failed"
        if not ok:
            result["errors"].append("Spot data download failed")

    if futures_pairs:
        log.info("Downloading futures data...")
        # Futures needs all TFs from futures strategies specifically,
        # plus 5m detail
        futures_tfs = set()
        for s in futures_strats.values():
            futures_tfs.add(s["timeframe"])
            futures_tfs.update(s.get("informative_tfs", []))
        futures_tfs.add(DETAIL_TF)
        futures_tfs_list = sorted(futures_tfs)

        ok = download_data(
            pairs=futures_pairs,
            timeframes=futures_tfs_list,
            timerange=timerange,
            trading_mode="futures",
        )
        result["futures_download"] = "success" if ok else "failed"
        if not ok:
            result["errors"].append("Futures data download failed")

    # ── Validate ─────────────────────────────────────────────────────────

    if spot_pairs:
        log.info("Validating spot data...")
        result["spot_validation"] = validate_data(
            pairs=spot_pairs,
            timeframes=all_tfs_list,
            timerange=timerange,
            trading_mode="spot",
        )

    if futures_pairs:
        log.info("Validating futures data...")
        result["futures_validation"] = validate_data(
            pairs=futures_pairs,
            timeframes=futures_tfs_list,
            timerange=timerange,
            trading_mode="futures",
        )

    # ── Final status ─────────────────────────────────────────────────────

    has_errors = len(result["errors"]) > 0
    spot_ok = result.get("spot_validation", {}).get("valid", True) if spot_pairs else True
    futures_ok = result.get("futures_validation", {}).get("valid", True) if futures_pairs else True

    if has_errors or not spot_ok or not futures_ok:
        # Partial success if downloads worked but validation found gaps
        if result.get("spot_download") == "success" or result.get("futures_download") == "success":
            result["status"] = "partial"
        else:
            result["status"] = "error"
    else:
        result["status"] = "success"

    log.info("Stage 1 complete: status=%s, spot=%d pairs, futures=%d pairs",
             result["status"], len(spot_pairs), len(futures_pairs))

    if result["errors"]:
        for err in result["errors"]:
            log.error("  Error: %s", err)

    return result
