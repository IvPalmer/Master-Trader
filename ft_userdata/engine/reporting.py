"""
Stage 6: Reporting
==================

Generates report cards per strategy, Telegram summaries, and JSON result
files. Includes kill/keep/optimize recommendation logic based on combined
stage results from the Backtest Engine v2 pipeline.

Report card format uses plain ASCII box drawing (no external dependencies).
Telegram messages are capped at 4096 characters.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .registry import RESULTS_DIR, WEBHOOK_URL

log = logging.getLogger("engine.reporting")

# ── Constants ────────────────────────────────────────────────────────────────

TELEGRAM_CHAR_LIMIT = 4096

# Thresholds for recommendation classification
KILL_CALIBRATION = 50
KILL_MC_SCORE = 40
MONITOR_CALIBRATION_LOW = 50
MONITOR_CALIBRATION_HIGH = 69
MONITOR_MC_LOW = 40
MONITOR_MC_HIGH = 59
OPTIMIZE_CALIBRATION = 70
OPTIMIZE_MC_SCORE = 60

# Box drawing characters (plain ASCII)
BOX_TL = "+"
BOX_TR = "+"
BOX_BL = "+"
BOX_BR = "+"
BOX_H = "-"
BOX_V = "|"
BOX_ML = "+"  # middle-left join
BOX_MR = "+"  # middle-right join

BOX_WIDTH = 50  # inner width (excluding border chars)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_get(d: dict, *keys, default=None):
    """Safely traverse nested dicts."""
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _format_pf(pf: Optional[float]) -> str:
    """Format profit factor for display."""
    if pf is None:
        return "N/A"
    return f"{pf:.2f}"


def _box_line(text: str) -> str:
    """Build a box line: | text padded to BOX_WIDTH |"""
    return f"{BOX_V} {text:<{BOX_WIDTH - 1}}{BOX_V}"


def _box_top() -> str:
    return f"{BOX_TL}{BOX_H * BOX_WIDTH}{BOX_TR}"


def _box_bottom() -> str:
    return f"{BOX_BL}{BOX_H * BOX_WIDTH}{BOX_BR}"


def _box_separator() -> str:
    return f"{BOX_ML}{BOX_H * BOX_WIDTH}{BOX_MR}"


def _calibration_label(score: Optional[int]) -> str:
    """Map calibration score to a human label."""
    if score is None:
        return "SKIPPED"
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Poor"


# ── Recommendation Logic ────────────────────────────────────────────────────

def classify_recommendation(results: dict) -> str:
    """
    Determine recommendation from combined stage results.

    Decision tree:
        KILL:           viability=DEAD OR mc_score<40
        INVESTIGATE:    calibration<50 (engine broken, NOT strategy fault)
        MONITOR:        viability=MARGINAL OR calibration 50-69 OR mc_score 40-59
        OPTIMIZE:       viability=VIABLE AND calibration>=70 AND mc_score>=60
        KEEP:           All checks pass, no param changes needed

    NOTE: Low calibration means the backtest engine doesn't reproduce live results.
    This is an ENGINE problem, not a strategy problem. Don't kill strategies
    based on calibration — investigate why backtests diverge from live.

    Returns: 'KILL', 'INVESTIGATE', 'OPTIMIZE', 'MONITOR', or 'KEEP'
    """
    viability = _safe_get(results, "viability", "classification", default="UNKNOWN")
    calibration = _safe_get(results, "calibration", "score")
    mc_score = _safe_get(results, "robustness", "monte_carlo", "mc_score")
    wf_profitable = _safe_get(results, "walk_forward", "consensus", "windows_profitable", default=0)
    wf_total = _safe_get(results, "walk_forward", "consensus", "windows_total", default=0)

    # ── KILL conditions (viability or MC only — NOT calibration) ──────────
    if viability == "DEAD":
        return "KILL"

    if mc_score is not None and mc_score < KILL_MC_SCORE:
        return "KILL"

    # ── INVESTIGATE: low calibration = engine problem ─────────────────────
    if calibration is not None and calibration < KILL_CALIBRATION:
        return "INVESTIGATE"

    # ── MONITOR conditions ───────────────────────────────────────────────
    is_marginal = viability == "MARGINAL"
    cal_monitor = (calibration is not None
                   and MONITOR_CALIBRATION_LOW <= calibration <= MONITOR_CALIBRATION_HIGH)
    mc_monitor = (mc_score is not None
                  and MONITOR_MC_LOW <= mc_score <= MONITOR_MC_HIGH)

    if is_marginal or cal_monitor or mc_monitor:
        return "MONITOR"

    # ── OPTIMIZE: viable with good scores, but walk-forward suggests tuning
    if viability == "VIABLE":
        cal_ok = calibration is None or calibration >= OPTIMIZE_CALIBRATION
        mc_ok = mc_score is None or mc_score >= OPTIMIZE_MC_SCORE
        if cal_ok and mc_ok:
            # Check if walk-forward produced consensus params worth applying
            has_consensus = _safe_get(results, "walk_forward", "consensus", "consensus_params") is not None
            wf_profitable_enough = wf_total == 0 or (wf_profitable / wf_total >= 0.5)
            if has_consensus and wf_profitable_enough:
                return "OPTIMIZE"

    # ── KEEP: everything passes, no param changes needed ─────────────────
    if viability == "VIABLE":
        cal_ok = calibration is None or calibration >= OPTIMIZE_CALIBRATION
        mc_ok = mc_score is None or mc_score >= OPTIMIZE_MC_SCORE
        if cal_ok and mc_ok:
            return "KEEP"

    # Fallback: if we can't determine clearly, monitor
    return "MONITOR"


# ── Report Card Builder ─────────────────────────────────────────────────────

def build_report_card(strategy_name: str, results: dict) -> str:
    """
    Build ASCII report card for console output.

    Args:
        strategy_name: Name of the strategy
        results: Dict with keys: calibration, viability, walk_forward, robustness.
                 Each sub-dict has its stage-specific metrics.

    Returns:
        Multi-line ASCII report card string.
    """
    recommendation = classify_recommendation(results)

    # ── Extract metrics (handle missing stages) ──────────────────────────
    cal_score = _safe_get(results, "calibration", "score")
    cal_label = _calibration_label(cal_score)
    cal_display = f"{cal_score}/100 ({cal_label})" if cal_score is not None else "SKIPPED"

    viability_class = _safe_get(results, "viability", "classification", default="SKIPPED")
    pf = _safe_get(results, "viability", "metrics", "profit_factor")
    trades = _safe_get(results, "viability", "metrics", "total_trades")
    lookahead_passed = _safe_get(results, "viability", "lookahead", "passed")

    if viability_class != "SKIPPED":
        via_parts = [viability_class]
        if pf is not None:
            via_parts.append(f"PF {_format_pf(pf)}")
        if trades is not None:
            via_parts.append(f"{trades} trades")
        via_display = " (".join(via_parts[:1]) + (" (" + ", ".join(via_parts[1:]) + ")" if len(via_parts) > 1 else "")
    else:
        via_display = "SKIPPED"

    if lookahead_passed is not None:
        la_display = "PASS" if lookahead_passed else "FAIL"
    else:
        la_display = "SKIPPED"

    wf_profitable = _safe_get(results, "walk_forward", "consensus", "windows_profitable")
    wf_total = _safe_get(results, "walk_forward", "consensus", "windows_total")
    if wf_profitable is not None and wf_total is not None:
        wf_display = f"{wf_profitable}/{wf_total} windows profitable"
    else:
        wf_display = "SKIPPED"

    # Consensus PF (from walk-forward Sharpe/Sortino/Calmar)
    avg_oos_sharpe = _safe_get(results, "walk_forward", "consensus", "avg_oos_sharpe")
    if avg_oos_sharpe is not None:
        consensus_display = f"{avg_oos_sharpe:.2f} (avg OOS Sharpe)"
    else:
        consensus_display = "SKIPPED"

    mc_score = _safe_get(results, "robustness", "monte_carlo", "mc_score")
    if mc_score is not None:
        if mc_score >= 80:
            mc_label = "Good"
        elif mc_score >= 60:
            mc_label = "Acceptable"
        elif mc_score >= 40:
            mc_label = "Marginal"
        else:
            mc_label = "Poor"
        mc_display = f"{mc_score}/100 ({mc_label})"
    else:
        mc_display = "SKIPPED"

    perturbation = _safe_get(results, "robustness", "perturbation", "overall")
    stability = _safe_get(results, "robustness", "perturbation", "stability_score")
    if perturbation is not None:
        pert_parts = [perturbation]
        if stability is not None:
            high_count = 0
            # Count HIGH sensitivities if available
            if perturbation == "FAIL":
                pert_parts.append("HIGH sensitivity detected")
            else:
                pert_parts.append(f"stability {stability}/100")
        pert_display = " (".join(pert_parts[:1]) + (" (" + ", ".join(pert_parts[1:]) + ")" if len(pert_parts) > 1 else "")
    else:
        pert_display = "SKIPPED"

    # Recommendation details
    rec_display = recommendation
    if recommendation == "OPTIMIZE":
        rec_display = "KEEP + APPLY CONSENSUS"
    elif recommendation == "KILL":
        rec_display = "FLAG -- RECOMMEND REMOVAL (manual action required)"
    elif recommendation == "INVESTIGATE":
        rec_display = "INVESTIGATE -- ENGINE DIVERGES FROM LIVE"
    elif recommendation == "MONITOR":
        rec_display = "MONITOR -- REVIEW NEXT CYCLE"

    # Pair information
    top_pairs = _safe_get(results, "viability", "pair_analysis", "top_5", default=[])
    worst_pairs = _safe_get(results, "viability", "pair_analysis", "bottom_5", default=[])

    # ── Build the card ───────────────────────────────────────────────────
    lines = []
    lines.append(_box_top())
    lines.append(_box_line(f"{strategy_name.upper()} -- REPORT CARD"))
    lines.append(_box_separator())
    lines.append(_box_line(f"Calibration:    {cal_display}"))
    lines.append(_box_line(f"Viability:      {via_display}"))
    lines.append(_box_line(f"Lookahead:      {la_display}"))
    lines.append(_box_line(f"Walk-Forward:   {wf_display}"))
    lines.append(_box_line(f"Consensus:      {consensus_display}"))
    lines.append(_box_line(f"Monte Carlo:    {mc_display}"))
    lines.append(_box_line(f"Perturbation:   {pert_display}"))
    lines.append(_box_line(""))
    lines.append(_box_line(f"RECOMMENDATION: {rec_display}"))

    if top_pairs:
        pairs_str = ", ".join(p.split("/")[0] for p in top_pairs[:5])
        lines.append(_box_line(""))
        lines.append(_box_line(f"Top pairs: {pairs_str}"))

    if worst_pairs:
        pairs_str = ", ".join(p.split("/")[0] for p in worst_pairs[:5])
        lines.append(_box_line(f"Drop pairs: {pairs_str} (negative expectancy)"))

    # Extra details
    max_dd = _safe_get(results, "viability", "metrics", "max_drawdown_pct")
    p95_dd = _safe_get(results, "robustness", "monte_carlo", "p95_max_drawdown")
    prob_ruin = _safe_get(results, "robustness", "monte_carlo", "probability_of_ruin")

    if max_dd is not None or p95_dd is not None:
        lines.append(_box_line(""))
        if max_dd is not None:
            lines.append(_box_line(f"Max Drawdown:   {max_dd:.1f}%"))
        if p95_dd is not None:
            lines.append(_box_line(f"p95 Drawdown:   {p95_dd:.1f}%"))
        if prob_ruin is not None:
            lines.append(_box_line(f"Prob of Ruin:   {prob_ruin:.1%}"))

    lines.append(_box_bottom())
    return "\n".join(lines)


# ── Telegram Message Builder ────────────────────────────────────────────────

def build_telegram_message(all_results: dict) -> str:
    """
    Build condensed Telegram summary across all strategies.
    Keeps output under 4096 chars (Telegram limit).

    Args:
        all_results: Dict mapping strategy names to their combined results.

    Returns:
        Formatted Telegram message string.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"Engine v2 Report -- {now}", ""]

    recommendations = {}
    for strategy, results in sorted(all_results.items()):
        rec = classify_recommendation(results)
        recommendations[strategy] = rec

        # One-line summary per strategy
        viability = _safe_get(results, "viability", "classification", default="?")
        cal = _safe_get(results, "calibration", "score")
        mc = _safe_get(results, "robustness", "monte_carlo", "mc_score")
        pf = _safe_get(results, "viability", "metrics", "profit_factor")
        trades = _safe_get(results, "viability", "metrics", "total_trades")

        # Emoji-free status indicators
        if rec == "KILL":
            indicator = "[X]"
        elif rec == "MONITOR":
            indicator = "[?]"
        elif rec == "OPTIMIZE":
            indicator = "[~]"
        else:
            indicator = "[+]"

        parts = [f"{indicator} {strategy}"]
        parts.append(f"  {rec}")
        sub_parts = []
        if viability != "?":
            sub_parts.append(viability)
        if pf is not None:
            sub_parts.append(f"PF {_format_pf(pf)}")
        if trades is not None:
            sub_parts.append(f"{trades}T")
        if cal is not None:
            sub_parts.append(f"Cal {cal}")
        if mc is not None:
            sub_parts.append(f"MC {mc}")
        if sub_parts:
            parts.append(f"  {' | '.join(sub_parts)}")

        lines.extend(parts)
        lines.append("")

    # Summary counts
    kills = sum(1 for r in recommendations.values() if r == "KILL")
    investigates = sum(1 for r in recommendations.values() if r == "INVESTIGATE")
    monitors = sum(1 for r in recommendations.values() if r == "MONITOR")
    optimizes = sum(1 for r in recommendations.values() if r == "OPTIMIZE")
    keeps = sum(1 for r in recommendations.values() if r == "KEEP")

    lines.append("---")
    counts = f"KILL: {kills} | INVESTIGATE: {investigates} | MONITOR: {monitors} | OPTIMIZE: {optimizes} | KEEP: {keeps}"
    lines.append(counts)

    message = "\n".join(lines)

    # Truncate if over Telegram limit
    if len(message) > TELEGRAM_CHAR_LIMIT:
        truncation_notice = "\n... (truncated)"
        max_len = TELEGRAM_CHAR_LIMIT - len(truncation_notice)
        message = message[:max_len] + truncation_notice

    return message


# ── Result Persistence ───────────────────────────────────────────────────────

def save_results(all_results: dict, mode: str) -> Path:
    """
    Save full results to engine_results/{date}_{mode}/ directory.

    Creates:
        - run_config.json       Overall run metadata
        - per-stage JSONs       {strategy}_{stage}.json for each stage
        - report_cards.txt      All report cards concatenated
        - telegram_message.txt  The Telegram summary

    Args:
        all_results: Dict mapping strategy names to their combined results.
        mode: Operating mode ('fast', 'thorough', 'rigorous')

    Returns:
        Path to the results directory.
    """
    date_str = datetime.now().strftime("%Y%m%d")
    results_dir = RESULTS_DIR / f"{date_str}_{mode}"
    results_dir.mkdir(parents=True, exist_ok=True)

    log.info("Saving results to %s", results_dir)

    # ── Run config ───────────────────────────────────────────────────────
    run_config = {
        "date": datetime.now().isoformat(),
        "mode": mode,
        "strategies": list(all_results.keys()),
        "recommendations": {},
    }

    for strategy, results in all_results.items():
        run_config["recommendations"][strategy] = classify_recommendation(results)

    _write_json(results_dir / "run_config.json", run_config)

    # ── Per-strategy, per-stage JSONs ────────────────────────────────────
    stages = ["calibration", "viability", "walk_forward", "robustness"]
    for strategy, results in all_results.items():
        for stage in stages:
            stage_data = results.get(stage)
            if stage_data is not None:
                fname = f"{strategy}_{stage}.json"
                _write_json(results_dir / fname, stage_data)

    # ── Report cards ─────────────────────────────────────────────────────
    cards = []
    for strategy, results in sorted(all_results.items()):
        cards.append(build_report_card(strategy, results))

    cards_text = "\n\n".join(cards)
    (results_dir / "report_cards.txt").write_text(cards_text, encoding="utf-8")
    log.info("Saved report_cards.txt (%d strategies)", len(cards))

    # ── Telegram message ─────────────────────────────────────────────────
    tg_message = build_telegram_message(all_results)
    (results_dir / "telegram_message.txt").write_text(tg_message, encoding="utf-8")

    log.info("Results saved: %s", results_dir)
    return results_dir


def _write_json(path: Path, data: dict) -> None:
    """Write dict as pretty-printed JSON, handling non-serializable types."""
    def default_serializer(obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, set):
            return sorted(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    path.write_text(
        json.dumps(data, indent=2, default=default_serializer),
        encoding="utf-8",
    )


# ── Telegram Sender ─────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """
    Send message to Telegram via webhook.

    Posts to WEBHOOK_URL with payload: {"type": "status", "status": message}

    Args:
        message: The message text to send.

    Returns:
        True on success, False on failure.
    """
    try:
        resp = requests.post(
            WEBHOOK_URL,
            json={"type": "status", "status": message},
            timeout=15,
        )
        if resp.status_code == 200:
            log.info("Telegram message sent (%d chars)", len(message))
            return True
        else:
            log.warning("Telegram webhook returned %d: %s",
                        resp.status_code, resp.text[:200])
            return False
    except requests.RequestException as e:
        log.error("Failed to send Telegram message: %s", e)
        return False


# ── Main Entry Point ─────────────────────────────────────────────────────────

def run_reporting_stage(
    all_results: dict,
    mode: str,
    send_tg: bool = False,
) -> dict:
    """
    Main entry point for Stage 6: Reporting.

    1. Classify recommendation for each strategy
    2. Build report cards (console output)
    3. Build Telegram summary
    4. Save all results to disk
    5. Optionally send Telegram notification

    Args:
        all_results: Dict mapping strategy names to their combined results.
                     Each value has keys: calibration, viability, walk_forward, robustness.
        mode: Operating mode ('fast', 'thorough', 'rigorous')
        send_tg: Whether to send the Telegram summary.

    Returns:
        Dict with keys:
            stage, status, recommendations, report_dir,
            report_cards (str), telegram_message (str),
            telegram_sent (bool or None)
    """
    log.info("=" * 60)
    log.info("Stage 6: Reporting (mode=%s, strategies=%d)", mode, len(all_results))
    log.info("=" * 60)

    result = {
        "stage": "reporting",
        "status": "running",
        "recommendations": {},
        "report_dir": None,
        "report_cards": "",
        "telegram_message": "",
        "telegram_sent": None,
    }

    if not all_results:
        log.warning("No results to report")
        result["status"] = "empty"
        return result

    # ── Classify recommendations ─────────────────────────────────────────
    for strategy, strat_results in sorted(all_results.items()):
        rec = classify_recommendation(strat_results)
        result["recommendations"][strategy] = rec
        log.info("  %s: %s", strategy, rec)

    # ── Build report cards ───────────────────────────────────────────────
    cards = []
    for strategy, strat_results in sorted(all_results.items()):
        card = build_report_card(strategy, strat_results)
        cards.append(card)
        # Print to console via logger
        for line in card.split("\n"):
            log.info(line)
        log.info("")

    result["report_cards"] = "\n\n".join(cards)

    # ── Build Telegram message ───────────────────────────────────────────
    tg_message = build_telegram_message(all_results)
    result["telegram_message"] = tg_message
    log.info("Telegram message: %d chars", len(tg_message))

    # ── Save to disk ─────────────────────────────────────────────────────
    try:
        report_dir = save_results(all_results, mode)
        result["report_dir"] = report_dir
    except Exception as e:
        log.error("Failed to save results: %s", e)
        result["report_dir"] = None

    # ── Send Telegram ────────────────────────────────────────────────────
    if send_tg:
        result["telegram_sent"] = send_telegram(tg_message)
    else:
        log.info("Telegram send skipped (send_tg=False)")
        result["telegram_sent"] = None

    # ── Summary ──────────────────────────────────────────────────────────
    recs = result["recommendations"]
    kills = sum(1 for r in recs.values() if r == "KILL")
    monitors = sum(1 for r in recs.values() if r == "MONITOR")
    optimizes = sum(1 for r in recs.values() if r == "OPTIMIZE")
    keeps = sum(1 for r in recs.values() if r == "KEEP")

    log.info("Recommendations: KILL=%d, MONITOR=%d, OPTIMIZE=%d, KEEP=%d",
             kills, monitors, optimizes, keeps)

    result["status"] = "success"

    log.info("Stage 6 complete")
    return result
