"""Conditional edge routing logic for the LangGraph grant pipeline."""
from __future__ import annotations

from backend.graph.state import GrantState


def route_triage(state: GrantState) -> str:
    """After human triage gate: route based on decision."""
    decision = state.get("human_triage_decision", "pass")
    if decision == "pursue":
        return "company_brain"
    elif decision == "watch":
        return "pipeline_update"
    else:
        return "pipeline_update"


def route_after_drafter(state: GrantState) -> str:
    """After drafter node: loop back if more sections needed, else go to reviewer."""
    sections = (state.get("grant_requirements") or {}).get("sections_required", [])
    approved = state.get("approved_sections") or {}

    if len(approved) >= len(sections) and sections:
        return "reviewer"
    return "drafter"


def route_after_reviewer(state: GrantState) -> str:
    """Always proceed to export after review (score is informational)."""
    return "export"
