"""Tests for time-of-day and day-of-week performance analysis."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

ANALYZER_PATH = Path(__file__).parent.parent / "ft_userdata" / "trade_analyzer.py"

def _load_analyzer():
    spec = importlib.util.spec_from_file_location("trade_analyzer", ANALYZER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("requests", MagicMock())
    sys.modules.setdefault("requests.auth", MagicMock())
    spec.loader.exec_module(mod)
    return mod

class TestSessionAnalysis:
    def test_classify_session_function_exists(self):
        mod = _load_analyzer()
        assert hasattr(mod, 'classify_session')

    def test_classify_session_returns_correct_labels(self):
        mod = _load_analyzer()
        assert mod.classify_session(3) == "asian"
        assert mod.classify_session(10) == "european"
        assert mod.classify_session(20) == "us"

    def test_classify_session_boundaries(self):
        mod = _load_analyzer()
        assert mod.classify_session(0) == "asian"
        assert mod.classify_session(7) == "asian"
        assert mod.classify_session(8) == "european"
        assert mod.classify_session(15) == "european"
        assert mod.classify_session(16) == "us"
        assert mod.classify_session(23) == "us"

    def test_analyze_by_session_function_exists(self):
        mod = _load_analyzer()
        assert hasattr(mod, 'analyze_by_session')

    def test_analyze_by_day_of_week_function_exists(self):
        mod = _load_analyzer()
        assert hasattr(mod, 'analyze_by_day_of_week')

    def test_analyze_by_session_with_empty_trades(self):
        mod = _load_analyzer()
        result = mod.analyze_by_session([])
        assert isinstance(result, dict)
        assert "asian" in result
        assert "european" in result
        assert "us" in result

    def test_analyze_by_day_of_week_with_empty_trades(self):
        mod = _load_analyzer()
        result = mod.analyze_by_day_of_week([])
        assert isinstance(result, dict)
        assert "Monday" in result

    def test_analyze_by_session_with_trades(self):
        mod = _load_analyzer()
        trades = [
            {"open_date": "2026-03-15 03:00:00", "profit_abs": 1.5, "profit_pct": 2.0},
            {"open_date": "2026-03-15 04:00:00", "profit_abs": -0.5, "profit_pct": -1.0},
            {"open_date": "2026-03-15 10:00:00", "profit_abs": 2.0, "profit_pct": 3.0},
            {"open_date": "2026-03-15 20:00:00", "profit_abs": -1.0, "profit_pct": -2.0},
        ]
        result = mod.analyze_by_session(trades)
        assert result["asian"]["trades"] == 2
        assert result["european"]["trades"] == 1
        assert result["us"]["trades"] == 1
        assert result["asian"]["total_pnl"] == 1.0
        assert result["asian"]["win_rate"] == 50.0

    def test_analyze_by_day_of_week_with_trades(self):
        mod = _load_analyzer()
        # 2026-03-16 is a Monday, 2026-03-17 is a Tuesday
        trades = [
            {"open_date": "2026-03-16 10:00:00", "profit_abs": 2.0, "profit_pct": 3.0},
            {"open_date": "2026-03-16 14:00:00", "profit_abs": -1.0, "profit_pct": -1.5},
            {"open_date": "2026-03-17 10:00:00", "profit_abs": 3.0, "profit_pct": 4.0},
        ]
        result = mod.analyze_by_day_of_week(trades)
        assert result["Monday"]["trades"] == 2
        assert result["Tuesday"]["trades"] == 1
        assert result["Tuesday"]["win_rate"] == 100.0

    def test_session_stats_zero_division(self):
        """Ensure empty session stats don't cause division errors."""
        mod = _load_analyzer()
        result = mod.analyze_by_session([])
        for session in ("asian", "european", "us"):
            assert result[session]["trades"] == 0
            assert result[session]["win_rate"] == 0
            assert result[session]["avg_pnl"] == 0
            assert result[session]["total_pnl"] == 0
