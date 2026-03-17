"""
Market Intelligence Module — Shared across all strategies
=========================================================

Provides:
1. Fear & Greed Index — sentiment-based entry gating
2. Cross-Bot Position Tracker — prevents correlated exposure (with expiry)
3. BTC regime classification helper
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ── Cross-bot shared position file (inside Docker volume) ────────
SHARED_POSITIONS_FILE = Path("/freqtrade/user_data/shared_positions.json")
MAX_BOTS_PER_PAIR = 2  # Max bots allowed to hold the same pair simultaneously
POSITION_MAX_AGE_HOURS = 48  # Expire stale positions from dead/restarted bots


class FearGreedIndex:
    """Cached Crypto Fear & Greed Index fetcher."""

    _cache = {"value": 50, "classification": "Neutral", "last_fetch": 0}
    CACHE_TTL = 6 * 3600  # 6 hours

    @classmethod
    def get(cls) -> dict:
        now = time.time()
        if now - cls._cache["last_fetch"] > cls.CACHE_TTL:
            try:
                r = requests.get(
                    "https://api.alternative.me/fng/?limit=1",
                    timeout=10,
                )
                data = r.json()["data"][0]
                cls._cache["value"] = int(data["value"])
                cls._cache["classification"] = data["value_classification"]
                cls._cache["last_fetch"] = now
                logger.info(
                    "Fear & Greed: %d (%s)",
                    cls._cache["value"],
                    cls._cache["classification"],
                )
            except Exception as e:
                logger.warning("Fear & Greed fetch failed: %s", e)
        return cls._cache

    @classmethod
    def is_extreme_greed(cls) -> bool:
        return cls.get()["value"] >= 80

    @classmethod
    def is_extreme_fear(cls) -> bool:
        return cls.get()["value"] <= 20


class PositionTracker:
    """
    Cross-bot position tracking via shared JSON file.

    All bots write their open positions to a shared file so each bot
    can check whether another bot already holds a given pair before entering.
    Gracefully degrades if file is missing or unreadable.
    Positions older than POSITION_MAX_AGE_HOURS are ignored (handles dead bots).
    """

    @staticmethod
    def register(bot_name: str, pair: str, stake_amount: float):
        try:
            data = PositionTracker._read()
            if bot_name not in data:
                data[bot_name] = {}
            data[bot_name][pair] = {
                "stake_amount": stake_amount,
                "timestamp": datetime.now().isoformat(),
            }
            PositionTracker._write(data)
        except Exception as e:
            logger.warning("Position tracker register failed: %s", e)

    @staticmethod
    def unregister(bot_name: str, pair: str):
        try:
            data = PositionTracker._read()
            if bot_name in data and pair in data[bot_name]:
                del data[bot_name][pair]
                if not data[bot_name]:
                    del data[bot_name]
            PositionTracker._write(data)
        except Exception as e:
            logger.warning("Position tracker unregister failed: %s", e)

    @staticmethod
    def count_bots_holding(pair: str, exclude_bot: str = "") -> int:
        """Returns number of OTHER bots currently holding this pair (ignoring stale)."""
        try:
            data = PositionTracker._read()
            now = datetime.now()
            count = 0
            for bot_name, positions in data.items():
                if bot_name != exclude_bot and pair in positions:
                    # Check position age — ignore stale entries from dead bots
                    try:
                        ts = datetime.fromisoformat(positions[pair]["timestamp"])
                        age_hours = (now - ts).total_seconds() / 3600
                        if age_hours < POSITION_MAX_AGE_HOURS:
                            count += 1
                    except (KeyError, ValueError):
                        count += 1  # Can't parse timestamp, count it to be safe
            return count
        except Exception:
            return 0

    @staticmethod
    def _read() -> dict:
        try:
            if SHARED_POSITIONS_FILE.exists():
                return json.loads(SHARED_POSITIONS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    @staticmethod
    def _write(data: dict):
        try:
            SHARED_POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SHARED_POSITIONS_FILE.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("Position tracker write failed: %s", e)


def classify_btc_regime(btc_close, btc_sma200, btc_rsi, btc_adx) -> str:
    """
    Classify BTC market regime from indicator values.

    Returns: 'strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'
    """
    above_sma = btc_close > btc_sma200

    if above_sma and btc_adx > 25 and btc_rsi > 55:
        return "strong_bull"
    elif above_sma and btc_rsi > 45:
        return "bull"
    elif not above_sma and btc_adx > 25 and btc_rsi < 40:
        return "strong_bear"
    elif not above_sma and btc_rsi < 50:
        return "bear"
    else:
        return "neutral"
