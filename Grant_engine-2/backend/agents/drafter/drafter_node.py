"""Drafter Node — LangGraph node that manages the section-by-section loop.

Flow:
  1. Called after grant_reader + company_brain
  2. Checks current_section_index — if 0, first section
  3. Checks section_review_decision (from interrupt resume):
     - "approve": save current section, advance index
     - "revise": rewrite current section with instructions
  4. Writes next section
  5. Interrupts — waits for human review via /resume/section-review
  6. When all sections approved → move to reviewer
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.agents.drafter.section_writer import write_section
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)


async def drafter_node(state: GrantState) -> Dict:
    """LangGraph node: write/revise section, set pending_interrupt for human review."""
    from backend.db.mongo import grants_scored
    from bson import ObjectId

    grant_requirements = state.get("grant_requirements") or {}
    sections = grant_requirements.get("sections_required", [])
    total_sections = len(sections)

    if not sections:
        logger.error("Drafter: no sections in grant_requirements")
        return {"errors": state.get("errors", []) + ["No sections found in grant requirements"]}

    current_idx = state.get("current_section_index", 0)
    approved_sections = dict(state.get("approved_sections", {}))
    review_decision = state.get("section_review_decision")
    edited_content = state.get("section_edited_content")

    # Load grant info
    grant = {}
    grant_id = state.get("selected_grant_id")
    if grant_id:
        try:
            grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
        except Exception:
            pass

    company_context = state.get("company_context", "")
    style_examples = state.get("style_examples", "")

    # Handle review decision from previous interrupt
    if review_decision == "approve" and current_idx > 0:
        # Save the section that was just reviewed
        prev_section = sections[current_idx - 1]
        prev_name = prev_section.get("name", f"Section {current_idx}")
        prev_interrupt = state.get("pending_interrupt") or {}
        content_to_save = edited_content or prev_interrupt.get("content", "")
        if content_to_save and prev_name not in approved_sections:
            approved_sections[prev_name] = {
                "content": content_to_save,
                "word_count": len(content_to_save.split()),
                "word_limit": prev_section.get("word_limit") or 500,
                "within_limit": len(content_to_save.split()) <= (prev_section.get("word_limit") or 500),
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info("Drafter: section '%s' approved", prev_name)

    elif review_decision == "revise" and current_idx > 0:
        # Rewrite current section — stay on same index
        section = sections[current_idx - 1]
        prev_interrupt = state.get("pending_interrupt") or {}
        instructions = state.get("section_revision_instructions", {}).get(section.get("name", ""), "")
        critique = state.get("section_critiques", {}).get(section.get("name", ""), "")

        logger.info("Drafter: rewriting section '%s'", section.get("name"))
        result = await write_section(
            section=section,
            section_num=current_idx,
            total_sections=total_sections,
            grant=grant,
            company_context=company_context,
            style_examples=style_examples,
            previous_content=prev_interrupt.get("content", ""),
            critique=critique,
            revision_instructions=instructions,
        )
        # Return interrupt for the rewritten section
        return {
            "pending_interrupt": result,
            "approved_sections": approved_sections,
            "section_review_decision": None,
            "section_edited_content": None,
            "audit_log": state.get("audit_log", []) + [{
                "node": "drafter",
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "section_rewritten",
                "section": result["section_name"],
            }],
        }

    # Check if all sections are done
    if len(approved_sections) >= total_sections:
        logger.info("Drafter: all %d sections approved — moving to reviewer", total_sections)
        return {
            "approved_sections": approved_sections,
            "pending_interrupt": None,
            "current_section_index": total_sections,
            "audit_log": state.get("audit_log", []) + [{
                "node": "drafter",
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "all_sections_approved",
            }],
        }

    # Write the next section
    section = sections[current_idx]
    logger.info("Drafter: writing section %d/%d: %s", current_idx + 1, total_sections, section.get("name"))

    result = await write_section(
        section=section,
        section_num=current_idx + 1,
        total_sections=total_sections,
        grant=grant,
        company_context=company_context,
        style_examples=style_examples,
    )

    return {
        "current_section_index": current_idx + 1,
        "approved_sections": approved_sections,
        "pending_interrupt": result,
        "section_review_decision": None,
        "section_edited_content": None,
        "audit_log": state.get("audit_log", []) + [{
            "node": "drafter",
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": "section_written",
            "section": result["section_name"],
            "word_count": result["word_count"],
            "within_limit": result["within_limit"],
        }],
    }


def should_continue_drafting(state: GrantState) -> str:
    """Router: continue drafting or move to reviewer when done."""
    sections = (state.get("grant_requirements") or {}).get("sections_required", [])
    approved = state.get("approved_sections", {})

    if len(approved) >= len(sections) and sections:
        return "reviewer"
    return "drafter"
