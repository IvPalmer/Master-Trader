#!/usr/bin/env python3
"""
AI Health Report — Claude-powered portfolio analysis
=====================================================

Gathers deterministic metrics from strategy_health_report.py, injects them
into a prompt template, and runs Claude CLI for contextual analysis.
Falls back to the rule-based report if Claude fails.

Usage:
    python ai_health_report.py                # Full report to Telegram
    python ai_health_report.py --stdout       # Print to stdout only
    python ai_health_report.py --json-only    # Just gather data, no Claude
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FT_DIR = Path.home() / "ft_userdata"
PROMPT_TEMPLATE_FULL = FT_DIR / "report_prompt.md"
PROMPT_TEMPLATE_BRIEF = FT_DIR / "report_prompt_brief.md"
STATE_FILE = FT_DIR / "health_report_state.json"
LOGS_DIR = FT_DIR / "logs"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"

# Project memory — read at runtime for fresh context
MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-palmer-Work-Dev-Master-Trader" / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"

CLAUDE_TIMEOUT = 90  # seconds
CLAUDE_CMD = "claude"
SAO_PAULO_TZ = timezone(timedelta(hours=-3))

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "ai_health_report.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ai-health-report")


# ---------------------------------------------------------------------------
# Step 1: Gather data
# ---------------------------------------------------------------------------

def run_health_report_json() -> Optional[dict]:
    """Run strategy_health_report.py --json and parse output."""
    try:
        result = subprocess.run(
            [sys.executable, str(FT_DIR / "strategy_health_report.py"), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(FT_DIR),
        )
        if result.returncode != 0:
            log.error("Health report failed: %s", result.stderr)
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        log.error("Health report timed out")
        return None
    except json.JSONDecodeError as e:
        log.error("Health report JSON parse error: %s", e)
        return None


def run_health_report_text() -> Optional[str]:
    """Run strategy_health_report.py --stdout for fallback."""
    try:
        result = subprocess.run(
            [sys.executable, str(FT_DIR / "strategy_health_report.py"), "--stdout"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(FT_DIR),
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception as e:
        log.error("Fallback report failed: %s", e)
        return None


def load_previous_state() -> Optional[dict]:
    """Load the previous report state for trend comparison."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def compute_trends(current: dict, previous: Optional[dict]) -> str:
    """Compute trend deltas between current and previous report."""
    if not previous or "bots" not in previous:
        return "No previous report available for comparison (first run)."

    lines = []
    prev_ts = previous.get("timestamp", "unknown")
    lines.append(f"Previous report: {prev_ts}")
    lines.append("")

    # Portfolio-level trends
    prev_portfolio = previous.get("portfolio", {})
    curr_portfolio = current.get("portfolio", {})
    pnl_delta = curr_portfolio.get("true_pnl", 0) - prev_portfolio.get("true_pnl", 0)
    trade_delta = curr_portfolio.get("total_trades", 0) - prev_portfolio.get("total_trades", 0)
    lines.append(f"Portfolio P&L change: ${pnl_delta:+.2f}")
    lines.append(f"New trades since last report: {trade_delta}")
    lines.append("")

    # Per-bot trends
    prev_bots = previous.get("bots", {})
    for strategy, curr_bot in current.get("bots", {}).items():
        prev_bot = prev_bots.get(strategy)
        if not prev_bot:
            lines.append(f"{strategy}: NEW (no previous data)")
            continue

        bot_pnl_delta = curr_bot.get("true_pnl", 0) - prev_bot.get("true_pnl", 0)
        bot_score_delta = curr_bot.get("health_score", 0) - prev_bot.get("health_score", 0)
        bot_trade_delta = curr_bot.get("total_trades", 0) - prev_bot.get("total_trades", 0)
        wr_delta = curr_bot.get("win_rate", 0) - prev_bot.get("win_rate", 0)

        direction = "UP" if bot_pnl_delta > 0.5 else ("DOWN" if bot_pnl_delta < -0.5 else "FLAT")
        lines.append(
            f"{strategy}: {direction} | P&L {bot_pnl_delta:+.2f} | "
            f"Score {bot_score_delta:+d} | WR {wr_delta:+.1f}% | "
            f"{bot_trade_delta} new trades"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 2: Build dynamic context and prompt
# ---------------------------------------------------------------------------

def load_dynamic_context() -> str:
    """Build context dynamically from project memory files.

    Reads MEMORY.md index, then loads referenced memory files that are
    relevant to report generation. This ensures the prompt always has
    fresh project context without hardcoded data.
    """
    context_parts = []

    # Read the memory index
    if MEMORY_INDEX.exists():
        index_text = MEMORY_INDEX.read_text()
        context_parts.append("PROJECT MEMORY (live context from project knowledge base):")
        context_parts.append(index_text)
        context_parts.append("")

        # Load individual memory files referenced in the index
        # Focus on files relevant to trading operations
        for md_file in sorted(MEMORY_DIR.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            try:
                content = md_file.read_text()
                # Skip files that aren't useful for report context
                # (e.g. pure feedback about Claude behavior)
                frontmatter_end = content.find("---", 3)
                if frontmatter_end > 0:
                    frontmatter = content[3:frontmatter_end].strip()
                    # Include project, reference, and relevant user memories
                    if any(t in frontmatter for t in ["type: project", "type: reference", "type: user"]):
                        context_parts.append(f"--- {md_file.name} ---")
                        context_parts.append(content)
                        context_parts.append("")
            except Exception:
                continue
    else:
        context_parts.append("No project memory available.")

    return "\n".join(context_parts)


def build_prompt(metrics: dict, previous: Optional[dict], brief: bool = False) -> str:
    """Assemble the full prompt with injected data."""
    template_path = PROMPT_TEMPLATE_BRIEF if brief else PROMPT_TEMPLATE_FULL
    template = template_path.read_text()

    # Dynamic context from project memory
    context_str = f"DYNAMIC CONTEXT:\n{load_dynamic_context()}"

    # Format metrics JSON (compact but readable)
    metrics_str = json.dumps(metrics, indent=2, default=str)

    # Format previous state
    if previous:
        prev_str = f"PREVIOUS REPORT STATE:\n{json.dumps(previous, indent=2, default=str)}"
    else:
        prev_str = "PREVIOUS REPORT STATE: None (first run)"

    # Compute trends
    trends_str = f"TREND ANALYSIS:\n{compute_trends(metrics, previous)}"

    prompt = template.replace("{CONTEXT}", context_str)
    prompt = prompt.replace("{METRICS_JSON}", f"CURRENT METRICS:\n{metrics_str}")
    prompt = prompt.replace("{PREVIOUS_STATE}", prev_str)
    prompt = prompt.replace("{TRENDS}", trends_str)

    return prompt


# ---------------------------------------------------------------------------
# Step 3: Run Claude
# ---------------------------------------------------------------------------

def run_claude(prompt: str) -> Optional[str]:
    """Run claude --print with the assembled prompt."""
    try:
        # Remove CLAUDECODE env var to allow running from within a Claude session
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            [CLAUDE_CMD, "--print", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            cwd=str(FT_DIR),
            env=env,
        )
        if result.returncode != 0:
            log.error("Claude CLI failed (rc=%d): %s", result.returncode, result.stderr[:500])
            return None
        output = result.stdout.strip()
        if not output:
            log.error("Claude returned empty output")
            return None
        # Strip markdown code fences if Claude adds them despite instructions
        if output.startswith("```"):
            lines = output.split("\n")
            # Remove first line (```...) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            output = "\n".join(lines).strip()
        return output
    except subprocess.TimeoutExpired:
        log.error("Claude CLI timed out after %ds", CLAUDE_TIMEOUT)
        return None
    except FileNotFoundError:
        log.error("Claude CLI not found at: %s", CLAUDE_CMD)
        return None


# ---------------------------------------------------------------------------
# Step 4: Deliver
# ---------------------------------------------------------------------------

def send_telegram(message: str) -> bool:
    """Send report to Telegram via claude-assistant webhook."""
    try:
        payload = {"type": "status", "status": message}
        resp = requests.post(WEBHOOK_URL, data=payload, timeout=10)
        if resp.status_code in (200, 201, 204):
            log.info("Report sent to Telegram")
            return True
        log.warning("Webhook returned HTTP %d", resp.status_code)
        return False
    except Exception as e:
        log.error("Failed to send report: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AI Health Report")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout only")
    parser.add_argument("--brief", action="store_true", help="Short status update (morning/evening)")
    parser.add_argument("--json-only", action="store_true", help="Just gather and print data")
    args = parser.parse_args()

    log.info("=" * 50)
    log.info("AI Health Report - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 50)

    # Step 1: Gather data
    log.info("Gathering metrics...")
    metrics = run_health_report_json()
    if not metrics:
        log.error("Failed to gather metrics — aborting")
        return 1

    previous = load_previous_state()

    if args.json_only:
        print(json.dumps(metrics, indent=2, default=str))
        return 0

    # Step 2: Build prompt
    log.info("Building prompt (mode=%s)...", "brief" if args.brief else "full")
    prompt = build_prompt(metrics, previous, brief=args.brief)
    log.info("Prompt size: %d chars", len(prompt))

    # Step 3: Run Claude
    log.info("Running Claude analysis...")
    report = run_claude(prompt)

    if report:
        # Prefix with timestamp
        now = datetime.now(SAO_PAULO_TZ).strftime("%Y-%m-%d %H:%M")
        label = "STATUS UPDATE" if args.brief else "PORTFOLIO REPORT"
        header = f"AI {label} — {now} (São Paulo)\n{'=' * 40}\n\n"
        report = header + report
        log.info("Claude analysis complete (%d chars)", len(report))
    else:
        # Fallback to rule-based report
        log.warning("Claude failed — falling back to rule-based report")
        report = run_health_report_text()
        if report:
            report = f"[FALLBACK — Rule-based report]\n\n{report}"
        else:
            log.error("Both Claude and fallback failed — aborting")
            return 1

    # Step 4: Deliver
    if args.stdout:
        print(report)
        return 0

    print(report)
    send_telegram(report)
    log.info("AI Health Report complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
