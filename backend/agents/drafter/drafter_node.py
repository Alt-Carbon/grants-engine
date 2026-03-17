"""Drafter Node — LangGraph node that manages the section-by-section loop.

Theme-aware: resolves grant theme, generates a narrative outline for coherence,
then writes each section with targeted Pinecone knowledge retrieval.

Flow:
  1. Called after grant_reader + company_brain
  2. On first call (index 0): resolve theme, generate outline
  3. Checks section_review_decision (from interrupt resume):
     - "approve": save current section, advance index
     - "revise": rewrite current section with instructions
  4. Retrieves section-specific context from Pinecone
  5. Writes next section with theme profile + outline + targeted knowledge
  6. Interrupts — waits for human review via /resume/section-review
  7. When all sections approved → move to reviewer
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.agents.drafter.section_writer import get_section_context, write_section
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)


async def _generate_outline(
    grant: Dict,
    theme_key: str,
    sections: List[Dict],
    company_context: str,
) -> str:
    """Generate a narrative outline that ties all sections together.

    This outline is passed to each section writer so sections tell a coherent story.
    """
    from backend.agents.drafter.theme_profiles import get_theme_profile
    from backend.utils.llm import chat, DRAFTER_DEFAULT

    profile = get_theme_profile(theme_key)

    section_list = "\n".join(
        f"  {i+1}. {s.get('name', f'Section {i+1}')}: {s.get('description', '')}"
        for i, s in enumerate(sections)
    )

    prompt = f"""You are planning a grant application for AltCarbon ({profile.get('display_name', 'Climate Tech')}).

GRANT: {grant.get('title', 'Unknown')}
FUNDER: {grant.get('funder', 'Unknown')}

SECTIONS TO WRITE:
{section_list}

COMPANY STRENGTHS:
{chr(10).join('- ' + s for s in profile.get('strengths', []))}

COMPANY CONTEXT (key knowledge):
{company_context[:3000]}

Generate a brief NARRATIVE OUTLINE (150-200 words) that:
1. Identifies the core narrative thread connecting all sections
2. Lists 3-5 key claims/arguments to weave through the application
3. Notes which AltCarbon strengths to emphasize in which sections
4. Identifies the "so what" — why should the funder care?

Keep it concise — this will be provided as context to each section writer."""

    try:
        outline = await chat(prompt, model=DRAFTER_DEFAULT, max_tokens=512)
        return outline.strip()
    except Exception as e:
        logger.warning("Outline generation failed: %s", e)
        return ""


async def drafter_node(state: GrantState) -> Dict:
    """LangGraph node: write/revise section, set pending_interrupt for human review."""
    import traceback as _tb

    try:
        result = await _drafter_node_inner(state)
        # Update heartbeat on success
        try:
            from backend.agents.agent_context import update_heartbeat
            section = (result.get("pending_interrupt") or {}).get("section_name", "")
            await update_heartbeat("drafter", {
                "status": "success",
                "action": result.get("audit_log", [{}])[-1].get("action", "section_written") if result.get("audit_log") else "section_written",
                "section": section,
                "theme": state.get("grant_theme", ""),
                "grant_id": state.get("selected_grant_id", ""),
            })
        except Exception:
            logger.debug("Heartbeat update skipped (drafter)", exc_info=True)
        return result
    except Exception as exc:
        grant_id = state.get("selected_grant_id", "")
        try:
            from backend.agents.agent_context import update_heartbeat
            await update_heartbeat("drafter", {
                "status": "error",
                "error": str(exc)[:200],
                "grant_id": grant_id,
            })
        except Exception:
            pass
        try:
            from backend.integrations.notion_sync import log_error
            await log_error(
                agent="drafter",
                error=exc,
                tb=_tb.format_exc(),
                grant_name=str(grant_id),
                severity="Critical",
            )
        except Exception:
            logger.debug("Notion error sync skipped (drafter failure)", exc_info=True)
        raise


async def _drafter_node_inner(state: GrantState) -> Dict:
    """Inner drafter logic, wrapped by drafter_node() for error handling."""
    from backend.agents.drafter.theme_profiles import resolve_theme, get_theme_profile
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

    # ── Theme resolution (once, on first call) ────────────────────────────────
    grant_theme = state.get("grant_theme", "")
    draft_outline = state.get("draft_outline", "")

    if not grant_theme:
        themes_detected = grant.get("themes_detected", [])
        grant_theme = resolve_theme(themes_detected)
        logger.info("Drafter: resolved theme → %s (from %s)", grant_theme, themes_detected)

    # ── Outline generation (once, on first section) ───────────────────────────
    if not draft_outline and current_idx == 0 and review_decision is None:
        profile = get_theme_profile(grant_theme)
        # Use theme-specific default sections if grant_reader returned generic ones
        if _sections_are_generic(sections):
            theme_sections = profile.get("default_sections", [])
            if theme_sections:
                sections = theme_sections
                grant_requirements = dict(grant_requirements)
                grant_requirements["sections_required"] = sections
                total_sections = len(sections)
                logger.info("Drafter: using theme-specific sections for %s (%d sections)", grant_theme, total_sections)

        draft_outline = await _generate_outline(grant, grant_theme, sections, company_context)
        if draft_outline:
            logger.info("Drafter: generated outline (%d chars)", len(draft_outline))

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

            # Notion sync — mark section approved
            try:
                from backend.integrations.notion_sync import sync_draft_section
                grant_name = grant.get("grant_name") or grant.get("title") or "Unknown"
                await sync_draft_section(
                    grant_id=str(grant_id or ""),
                    grant_name=grant_name,
                    section_name=prev_name,
                    content=content_to_save,
                    word_count=len(content_to_save.split()),
                    word_limit=prev_section.get("word_limit") or 500,
                    status="Approved",
                )
            except Exception:
                logger.debug("Notion sync skipped (section approval)", exc_info=True)

    elif review_decision == "revise" and current_idx > 0:
        # Rewrite current section — stay on same index
        section = sections[current_idx - 1]
        prev_interrupt = state.get("pending_interrupt") or {}
        instructions = state.get("section_revision_instructions", {}).get(section.get("name", ""), "")
        critique = state.get("section_critiques", {}).get(section.get("name", ""), "")

        # Get fresh section-specific context for the revision
        grant_themes = grant.get("themes_detected", [])
        section_ctx = await get_section_context(
            grant_theme, section.get("name", ""), grant.get("title", ""), grant_themes, company_context,
        )

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
            theme_key=grant_theme,
            section_context=section_ctx,
            draft_outline=draft_outline,
        )
        # Return interrupt for the rewritten section
        return {
            "pending_interrupt": result,
            "approved_sections": approved_sections,
            "section_review_decision": None,
            "section_edited_content": None,
            "grant_theme": grant_theme,
            "draft_outline": draft_outline,
            "grant_requirements": grant_requirements,
            "audit_log": state.get("audit_log", []) + [{
                "node": "drafter",
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "section_rewritten",
                "section": result["section_name"],
                "theme": grant_theme,
            }],
        }

    # Check if all sections are done
    if len(approved_sections) >= total_sections:
        logger.info("Drafter: all %d sections approved — moving to reviewer", total_sections)
        return {
            "approved_sections": approved_sections,
            "pending_interrupt": None,
            "current_section_index": total_sections,
            "grant_theme": grant_theme,
            "draft_outline": draft_outline,
            "grant_requirements": grant_requirements,
            "audit_log": state.get("audit_log", []) + [{
                "node": "drafter",
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "all_sections_approved",
                "theme": grant_theme,
            }],
        }

    # ── Write the next section with section-specific RAG ──────────────────────
    section = sections[current_idx]
    section_name = section.get("name", f"Section {current_idx + 1}")
    logger.info("Drafter: writing section %d/%d: %s (theme=%s)", current_idx + 1, total_sections, section_name, grant_theme)

    # Retrieve section-specific context from Pinecone
    grant_themes = grant.get("themes_detected", [])
    section_ctx = await get_section_context(
        grant_theme, section_name, grant.get("title", ""), grant_themes, company_context,
    )

    # Load drafter settings from agent_config
    from backend.db.mongo import agent_config
    drafter_cfg = await agent_config().find_one({"agent": "drafter"}) or {}
    theme_settings = (drafter_cfg.get("theme_settings") or {}).get(grant_theme) or {}

    # Retrieve lessons from past grant outcomes (feedback learning)
    past_outcomes = ""
    try:
        from backend.agents.feedback_learner import get_lessons_for_grant
        funder = grant.get("funder", "")
        grant_themes = grant.get("themes_detected", [])
        past_outcomes = await get_lessons_for_grant(funder=funder, themes=grant_themes)
        if past_outcomes:
            logger.info("Drafter: loaded past outcome lessons for funder=%s (%d chars)", funder, len(past_outcomes))
    except Exception as e:
        logger.debug("Drafter: feedback learner unavailable: %s", e)

    result = await write_section(
        section=section,
        section_num=current_idx + 1,
        total_sections=total_sections,
        grant=grant,
        company_context=company_context,
        style_examples=style_examples,
        theme_key=grant_theme,
        section_context=section_ctx,
        draft_outline=draft_outline,
        writing_style=drafter_cfg.get("writing_style", "professional"),
        custom_instructions=drafter_cfg.get("custom_instructions", ""),
        temperature=theme_settings.get("temperature") or drafter_cfg.get("temperature"),
        tone_override=theme_settings.get("tone", ""),
        voice_override=theme_settings.get("voice", ""),
        strengths_override=theme_settings.get("strengths") or None,
        domain_terms_override=theme_settings.get("domain_terms") or None,
        theme_instructions=theme_settings.get("custom_instructions", ""),
        past_outcomes=past_outcomes,
    )

    # ── Notion Mission Control sync ──────────────────────────────────────────
    try:
        from backend.integrations.notion_sync import sync_draft_section
        grant_name = grant.get("grant_name") or grant.get("title") or "Unknown"
        await sync_draft_section(
            grant_id=str(grant_id or ""),
            grant_name=grant_name,
            section_name=result["section_name"],
            content=result.get("content", ""),
            word_count=result.get("word_count", 0),
            word_limit=section.get("word_limit", 500),
            version=1,
            status="In Review",
            evidence_gaps=result.get("evidence_gaps"),
        )
    except Exception:
        logger.debug("Notion sync skipped (drafter section)", exc_info=True)

    return {
        "current_section_index": current_idx + 1,
        "approved_sections": approved_sections,
        "pending_interrupt": result,
        "section_review_decision": None,
        "section_edited_content": None,
        "grant_theme": grant_theme,
        "draft_outline": draft_outline,
        "grant_requirements": grant_requirements,
        "audit_log": state.get("audit_log", []) + [{
            "node": "drafter",
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": "section_written",
            "section": result["section_name"],
            "word_count": result["word_count"],
            "within_limit": result["within_limit"],
            "theme": grant_theme,
        }],
    }


def _sections_are_generic(sections: List[Dict]) -> bool:
    """Check if sections are the generic defaults from grant_reader."""
    generic_names = {"Project Overview", "Technical Approach", "Team & Capabilities", "Budget Justification", "Impact & Outcomes"}
    section_names = {s.get("name", "") for s in sections}
    return section_names == generic_names


def should_continue_drafting(state: GrantState) -> str:
    """Router: continue drafting or move to reviewer when done."""
    sections = (state.get("grant_requirements") or {}).get("sections_required", [])
    approved = state.get("approved_sections", {})

    if len(approved) >= len(sections) and sections:
        return "reviewer"
    return "drafter"
