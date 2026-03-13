"""LangGraph GrantState — single source of truth for the entire pipeline."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class GrantState(TypedDict):
    # ── Discovery ──────────────────────────────────────────────────────────────
    raw_grants: List[Dict]          # Scout output — raw discovered grants
    scored_grants: List[Dict]       # Analyst output — scored + ranked

    # ── Human Gate 1: Triage ───────────────────────────────────────────────────
    human_triage_decision: Optional[str]    # "pursue" | "pass" | "watch"
    selected_grant_id: Optional[str]        # MongoDB _id of chosen grant
    triage_notes: Optional[str]

    # ── Grant Reading ──────────────────────────────────────────────────────────
    grant_requirements: Optional[Dict]      # Structured grant doc (sections, criteria, budget)
    grant_raw_doc: Optional[str]            # Raw fetched content

    # ── Company Brain ─────────────────────────────────────────────────────────
    company_profile: Optional[str]          # General company profile (loaded before analyst)
    company_context: Optional[str]          # Retrieved knowledge for this grant
    style_examples: Optional[str]           # Past grant application chunks
    style_examples_loaded: bool

    # ── Draft Guardrail ───────────────────────────────────────────────────────
    draft_guardrail_result: Optional[Dict]     # {passed, checks, reason, ...}
    override_guardrails: bool

    # ── Drafter: Theme + Outline ────────────────────────────────────────────────
    grant_theme: Optional[str]             # Resolved theme key (e.g. "climatetech")
    draft_outline: Optional[str]           # Narrative outline for cross-section coherence

    # ── Drafter: Section Loop ─────────────────────────────────────────────────
    current_section_index: int
    approved_sections: Dict[str, Dict]      # section_name → {content, word_count, ...}
    section_critiques: Dict[str, str]       # section_name → critique text
    section_revision_instructions: Dict[str, str]

    # ── Human Gate 2: Section Review ──────────────────────────────────────────
    pending_interrupt: Optional[Dict]       # Current section awaiting review
    section_review_decision: Optional[str]  # "approve" | "revise"
    section_edited_content: Optional[str]   # Human-edited content (if any)

    # ── Reviewer ──────────────────────────────────────────────────────────────
    reviewer_output: Optional[Dict]

    # ── Export ────────────────────────────────────────────────────────────────
    draft_version: int
    draft_filepath: Optional[str]
    draft_filename: Optional[str]
    markdown_content: Optional[str]

    # ── Meta ──────────────────────────────────────────────────────────────────
    pipeline_id: Optional[str]
    thread_id: str
    run_id: str
    errors: List[str]
    audit_log: List[Dict]
