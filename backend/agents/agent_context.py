"""Agent Context Loader — CLAUDE.md-style persistent context for each agent.

Each agent has two markdown files:
  skills.md   — static identity: capabilities, instructions, constraints, tools
  heartbeat.md — auto-updated: last run, performance, state, recent results

The loader reads these files and provides them as context strings that agents
inject into their system prompts. Heartbeat is updated after each run.

Directory structure:
  backend/agents/scout/skills.md
  backend/agents/scout/heartbeat.md
  backend/agents/analyst/skills.md
  backend/agents/analyst/heartbeat.md
  ...

Usage:
    from backend.agents.agent_context import load_context, update_heartbeat

    # Before running the agent
    ctx = load_context("scout")
    # ctx.skills → skills.md content
    # ctx.heartbeat → heartbeat.md content
    # ctx.system_block → formatted for system prompt injection

    # After the run
    await update_heartbeat("scout", {
        "status": "success",
        "grants_found": 12,
        "duration_seconds": 45,
    })
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent


@dataclass
class AgentContext:
    """Loaded context for an agent."""
    name: str
    skills: str
    heartbeat: str

    @property
    def system_block(self) -> str:
        """Formatted block ready for system prompt injection."""
        parts = []
        if self.skills:
            parts.append(f"## Agent Identity\n{self.skills}")
        if self.heartbeat:
            parts.append(f"## Current State\n{self.heartbeat}")
        return "\n\n".join(parts)


def _agent_dir(agent_name: str) -> Path:
    """Resolve agent directory. Handles both flat files and subdirectories."""
    # Try agent subdirectory first
    candidates = [
        AGENTS_DIR / agent_name,
        AGENTS_DIR / f"{agent_name}_agent",
        AGENTS_DIR / f"{agent_name}_agents",
    ]
    # Special cases
    if agent_name == "drafter":
        candidates.insert(0, AGENTS_DIR / "drafter")
    if agent_name == "reviewer":
        candidates.insert(0, AGENTS_DIR / "reviewer_agents")
    if agent_name == "company_brain":
        candidates.insert(0, AGENTS_DIR / "company_brain_agent")

    for d in candidates:
        if d.is_dir():
            return d

    # Create the directory if it doesn't exist
    default = AGENTS_DIR / agent_name
    default.mkdir(exist_ok=True)
    return default


def _read_md(path: Path) -> str:
    """Read a markdown file, return empty string if missing."""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.warning("Failed to read %s: %s", path, e)
    return ""


def load_context(agent_name: str) -> AgentContext:
    """Load skills.md and heartbeat.md for an agent."""
    agent_dir = _agent_dir(agent_name)
    skills = _read_md(agent_dir / "skills.md")
    heartbeat = _read_md(agent_dir / "heartbeat.md")

    return AgentContext(
        name=agent_name,
        skills=skills,
        heartbeat=heartbeat,
    )


async def update_heartbeat(
    agent_name: str,
    run_data: Dict[str, Any],
) -> None:
    """Update an agent's heartbeat.md after a run.

    Keeps the last 10 runs in the heartbeat for trend visibility.
    Also persists to MongoDB for cross-instance consistency.
    """
    agent_dir = _agent_dir(agent_name)
    heartbeat_path = agent_dir / "heartbeat.md"

    now = datetime.now(timezone.utc)
    run_entry = {
        "timestamp": now.isoformat(),
        **run_data,
    }

    # Load existing heartbeat data
    existing_runs: List[Dict] = []
    state: Dict[str, Any] = {}
    try:
        from backend.db.mongo import agent_config
        doc = await agent_config().find_one({"agent": f"{agent_name}_heartbeat"})
        if doc:
            existing_runs = doc.get("recent_runs", [])
            state = doc.get("state", {})
    except Exception:
        pass

    # Prepend new run, keep last 10
    existing_runs.insert(0, run_entry)
    existing_runs = existing_runs[:10]

    # Update aggregate state
    total_runs = state.get("total_runs", 0) + 1
    total_success = state.get("total_success", 0) + (1 if run_data.get("status") == "success" else 0)
    total_errors = state.get("total_errors", 0) + (1 if run_data.get("status") == "error" else 0)

    state.update({
        "total_runs": total_runs,
        "total_success": total_success,
        "total_errors": total_errors,
        "success_rate": round(total_success / total_runs * 100, 1) if total_runs else 0,
        "last_run": now.isoformat(),
        "last_status": run_data.get("status", "unknown"),
        "uptime_pct": round(total_success / total_runs * 100, 1) if total_runs else 0,
    })

    # Persist to MongoDB
    try:
        from backend.db.mongo import agent_config
        await agent_config().update_one(
            {"agent": f"{agent_name}_heartbeat"},
            {"$set": {
                "agent": f"{agent_name}_heartbeat",
                "state": state,
                "recent_runs": existing_runs,
                "updated_at": now.isoformat(),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning("Failed to persist heartbeat to MongoDB: %s", e)

    # Write heartbeat.md
    lines = [
        f"# {agent_name.replace('_', ' ').title()} — Heartbeat",
        "",
        f"**Last run:** {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Status:** {run_data.get('status', 'unknown')}",
        f"**Total runs:** {total_runs}  |  **Success rate:** {state['success_rate']}%",
        "",
    ]

    # Add run-specific metrics
    skip_keys = {"status", "timestamp"}
    metrics = {k: v for k, v in run_data.items() if k not in skip_keys}
    if metrics:
        lines.append("## Last Run Metrics")
        for k, v in metrics.items():
            lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        lines.append("")

    # Recent history
    if len(existing_runs) > 1:
        lines.append("## Recent History")
        for run in existing_runs[:5]:
            ts = run.get("timestamp", "?")[:16]
            status = run.get("status", "?")
            summary_parts = []
            for k, v in run.items():
                if k not in {"timestamp", "status"} and not isinstance(v, (dict, list)):
                    summary_parts.append(f"{k}={v}")
            summary = ", ".join(summary_parts[:3])
            lines.append(f"- `{ts}` **{status}** {summary}")
        lines.append("")

    # Known issues (from errors)
    if total_errors > 0:
        error_runs = [r for r in existing_runs if r.get("status") == "error"]
        if error_runs:
            lines.append("## Recent Errors")
            for er in error_runs[:3]:
                err_msg = er.get("error", "Unknown error")
                lines.append(f"- `{er.get('timestamp', '?')[:16]}` {err_msg}")
            lines.append("")

    try:
        heartbeat_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to write heartbeat.md: %s", e)
