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


def route_after_guardrail(state: GrantState) -> str:
    """After draft guardrail: route to drafter if passed, pipeline_update if failed.

    Defaults to failed (fail-closed) if guardrail result is missing or malformed.
    """
    result = state.get("draft_guardrail_result") or {}
    if result.get("passed", False):
        return "drafter"
    return "pipeline_update"


def route_after_drafter(state: GrantState) -> str:
    """After drafter node: loop back if more sections needed, else go to reviewer.

    If sections_required is empty, route to pipeline_update to avoid an infinite loop.
    """
    sections = (state.get("grant_requirements") or {}).get("sections_required", [])
    approved = state.get("approved_sections") or {}

    if not sections:
        return "pipeline_update"
    if len(approved) >= len(sections):
        return "reviewer"
    return "drafter"


def route_after_reviewer(state: GrantState) -> str:
    """Always proceed to export after review (score is informational)."""
    return "export"
