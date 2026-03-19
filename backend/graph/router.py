"""Conditional edge routing logic for the LangGraph grant pipeline."""
from __future__ import annotations

from backend.graph.state import GrantState


def route_triage(state: GrantState) -> str:
    """After human triage gate: route based on decision.

    Only "pursue" advances the pipeline. All other decisions (pass, watch,
    unknown) terminate via pipeline_update → END.
    """
    decision = state.get("human_triage_decision", "pass")
    grant_id = state.get("selected_grant_id")

    # Safety: can't pursue without a grant selected
    if decision == "pursue" and not grant_id:
        return "pipeline_update"

    if decision == "pursue":
        return "company_brain"
    return "pipeline_update"


def route_after_guardrail(state: GrantState) -> str:
    """After draft guardrail: route to drafter if passed, pipeline_update if failed.

    Fail-open: if guardrail_result is missing (node crashed), we pass through
    to drafter rather than blocking — consistent with the guardrail's own
    fail-open policy on LLM errors.
    """
    result = state.get("draft_guardrail_result") or {}
    if result.get("passed", True):
        return "drafter"
    return "pipeline_update"


def route_after_drafter(state: GrantState) -> str:
    """After drafter node: loop back if more sections needed, else go to reviewer.

    Edge case: if sections_required is empty (grant_reader failed), route to
    pipeline_update to avoid an infinite drafter loop.
    """
    sections = (state.get("grant_requirements") or {}).get("sections_required", [])
    approved = state.get("approved_sections") or {}

    # No sections = grant_reader failed → stop, don't loop forever
    if not sections:
        return "pipeline_update"

    if len(approved) >= len(sections):
        return "reviewer"
    return "drafter"


def route_after_reviewer(state: GrantState) -> str:
    """Proceed to export after review. Score is informational."""
    return "export"
