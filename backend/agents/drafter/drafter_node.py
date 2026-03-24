"""Drafter Node — LangGraph node that manages the section-by-section loop.

Theme-aware: resolves grant theme, generates a narrative outline for coherence,
then writes each section with targeted Pinecone knowledge retrieval.

Flow:
  1. Called after grant_reader + company_brain
  2. On first call (index 0): resolve theme, generate outline, build criteria map,
     extract funder language
  3. Checks section_review_decision (from interrupt resume):
     - "approve": save current section, advance index
     - "revise": rewrite current section with instructions
  4. Retrieves section-specific context from Pinecone
  5. Writes next section with theme profile + outline + targeted knowledge +
     criteria map + funder terms
  6. Self-critique loop reviews output before interrupt
  7. Auto-resolves evidence gaps via Pinecone search
  8. Interrupts — waits for human review via /resume/section-review
  9. When all sections approved → move to reviewer
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
    """Generate a strategic outline that ties all sections into a coherent narrative.

    This outline is passed to each section writer so sections tell a coherent story
    with explicit transitions, argument flow, and evidence allocation.
    """
    from backend.agents.drafter.theme_profiles import get_theme_profile
    from backend.utils.llm import chat, DRAFTER_DEFAULT

    profile = get_theme_profile(theme_key)

    section_list = "\n".join(
        f"  {i+1}. {s.get('name', f'Section {i+1}')} ({s.get('word_limit', 500)} words): {s.get('description', '')}"
        for i, s in enumerate(sections)
    )

    # Extract evaluation criteria for strategic mapping
    eval_criteria = (
        (grant.get("grant_requirements") or {}).get("evaluation_criteria")
        or grant.get("evaluation_criteria")
        or (grant.get("deep_analysis") or {}).get("evaluation_criteria")
        or []
    )
    criteria_block = ""
    if eval_criteria:
        criteria_block = "EVALUATION CRITERIA (the funder will score on these):\n" + "\n".join(
            f"  - {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))} "
            f"(weight: {c.get('weight', 'unspecified')})"
            for c in eval_criteria
        )

    # Extract strategic angle if available
    strategic_angle = (grant.get("deep_analysis") or {}).get("strategic_angle", "")
    strategic_block = f"\nSTRATEGIC ANGLE (from grant analysis):\n{strategic_angle}" if strategic_angle else ""

    prompt = f"""You are a grant strategist planning a winning application for AltCarbon ({profile.get('display_name', 'Climate Tech')}).

GRANT: {grant.get('title', 'Unknown')}
FUNDER: {grant.get('funder', 'Unknown')}

SECTIONS TO WRITE:
{section_list}

COMPANY STRENGTHS:
{chr(10).join('- ' + s for s in profile.get('strengths', []))}

{criteria_block}
{strategic_block}

COMPANY CONTEXT (verified facts and capabilities):
{company_context[:6000]}

Generate a STRATEGIC OUTLINE (300-400 words) with this exact structure:

## CORE NARRATIVE
One sentence: what is AltCarbon proposing, why does it matter to THIS funder, and what makes it credible?

## ARGUMENT FLOW
For each section, specify:
- **[Section Name]**: Opening claim → Key evidence to cite (specific numbers/facts from company context) → Closing hook that transitions to next section
(Each section entry should be 2-3 sentences)

## KEY CLAIMS (weave these through multiple sections)
5-7 quantified claims that MUST appear, with the specific evidence source:
- Claim: "..." → Evidence: "..." → Use in: Section X, Section Y

## EVIDENCE ALLOCATION
Map the strongest evidence to sections where it has maximum scoring impact:
- [Evidence item] → [Section] (addresses criterion: ...)

## FUNDER ALIGNMENT
2-3 specific ways to mirror this funder's language, priorities, and scoring criteria.

Rules:
- Every claim must have a specific number, date, or verifiable fact
- Every section must explicitly connect to at least one evaluation criterion
- Transitions between sections must be logical, not generic ("Furthermore...")
- Allocate evidence strategically — don't repeat the same fact in every section"""

    try:
        outline = await chat(prompt, model=DRAFTER_DEFAULT, max_tokens=1024)
        return outline.strip()
    except Exception as e:
        logger.warning("Outline generation failed: %s", e)
        return ""


async def _build_criteria_map(
    grant: Dict,
    sections: List[Dict],
    company_context: str,
    theme_key: str,
) -> Dict[str, str]:
    """Pre-map evaluation criteria → evidence → sections.

    Returns a dict mapping section_name → formatted criteria-evidence text
    that tells the section writer exactly which criteria to address and
    what evidence to use.
    """
    from backend.utils.llm import chat, ANALYST_LIGHT

    grant_requirements = grant.get("grant_requirements") or {}
    eval_criteria = (
        grant_requirements.get("evaluation_criteria")
        or grant.get("evaluation_criteria")
        or (grant.get("deep_analysis") or {}).get("evaluation_criteria")
        or []
    )

    if not eval_criteria:
        return {}

    section_list = "\n".join(
        f"  {i+1}. {s.get('name', f'Section {i+1}')}: {s.get('description', '')}"
        for i, s in enumerate(sections)
    )

    criteria_list = "\n".join(
        f"  - {c.get('criterion', '')}: {c.get('description', c.get('what_they_look_for', ''))} "
        f"(weight: {c.get('weight', 'unspecified')})"
        for c in eval_criteria
    )

    prompt = f"""Map each evaluation criterion to the grant sections where it should be addressed,
and identify the best available evidence for each.

GRANT: {grant.get('title', 'Unknown')}
FUNDER: {grant.get('funder', 'Unknown')}

EVALUATION CRITERIA:
{criteria_list}

APPLICATION SECTIONS:
{section_list}

AVAILABLE COMPANY EVIDENCE (summary):
{company_context[:3000]}

For each section, list which criteria it must address and what specific evidence to cite.

Respond ONLY with valid JSON:
{{
  "<section_name>": "Criterion 1 (weight): use [evidence X] to demonstrate... | Criterion 2 (weight): cite [evidence Y]...",
  ...
}}

Rules:
- Every criterion must appear in at least one section
- High-weight criteria should appear in 2+ sections
- Be specific about which evidence to use — don't say "mention capabilities", say "cite Frontier/Stripe buyer relationships"
- If no evidence exists for a criterion, note "[EVIDENCE GAP: description]"
"""

    try:
        raw = await chat(prompt, model=ANALYST_LIGHT, max_tokens=2000, temperature=0.2)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import json
        result = json.loads(raw)
        logger.info("Criteria map built: %d sections mapped", len(result))
        return result
    except Exception as e:
        logger.warning("Criteria map generation failed: %s", e)
        return {}


async def _extract_funder_language(
    grant_raw_doc: str,
    grant: Dict,
) -> str:
    """Extract the funder's key terms and phrases from the RFP.

    Returns a formatted string of funder-specific terminology for the
    section writer to mirror.
    """
    from backend.utils.llm import chat, ANALYST_LIGHT

    if not grant_raw_doc or len(grant_raw_doc) < 200:
        return ""

    prompt = f"""Extract 15-20 key terms and phrases this funder uses repeatedly in their grant document.

FUNDER: {grant.get('funder', 'Unknown')}
GRANT: {grant.get('title', 'Unknown')}

GRANT DOCUMENT (first 6000 chars):
{grant_raw_doc[:6000]}

Focus on:
1. How they name the PROBLEM (e.g., "climate change" vs "climate crisis" vs "global warming")
2. How they name the SOLUTION TYPE (e.g., "nature-based solutions" vs "natural climate solutions")
3. IMPACT METRICS they care about (e.g., "tonnes of CO2" vs "carbon credits" vs "drawdown potential")
4. EVALUATION language (e.g., "scalability" vs "growth potential", "innovation" vs "novelty")
5. TONE markers (e.g., "transformative" vs "incremental", "community" vs "stakeholder")

Return ONLY a bullet list of terms/phrases with brief notes on usage:
- "term or phrase" — context of how funder uses it"""

    try:
        result = await chat(prompt, model=ANALYST_LIGHT, max_tokens=800, temperature=0.1)
        result = result.strip()
        if result and len(result) > 50:
            logger.info("Extracted funder language: %d chars", len(result))
            return result
    except Exception as e:
        logger.warning("Funder language extraction failed: %s", e)

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
    from backend.config.settings import get_settings
    from backend.db.mongo import grants_scored
    from bson import ObjectId

    _settings = get_settings()
    _default_word_limit = _settings.default_section_word_limit

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

    # ── Outline + Criteria Map + Funder Language (once, on first section) ────
    criteria_map = state.get("criteria_map") or {}
    funder_terms = state.get("funder_terms") or ""

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

        # Run outline, criteria map, and funder language extraction in parallel
        import asyncio
        outline_task = _generate_outline(grant, grant_theme, sections, company_context)
        criteria_task = _build_criteria_map(grant, sections, company_context, grant_theme)
        funder_lang_task = _extract_funder_language(
            state.get("grant_raw_doc", ""), grant,
        )

        draft_outline, criteria_map, funder_terms = await asyncio.gather(
            outline_task, criteria_task, funder_lang_task,
        )

        if draft_outline:
            logger.info("Drafter: generated outline (%d chars)", len(draft_outline))
        if criteria_map:
            logger.info("Drafter: criteria map covers %d sections", len(criteria_map))
        if funder_terms:
            logger.info("Drafter: extracted funder language (%d chars)", len(funder_terms))

    # Handle review decision from previous interrupt
    if review_decision == "approve" and current_idx > 0:
        # Save the section that was just reviewed
        prev_section = sections[current_idx - 1]
        prev_name = prev_section.get("name", f"Section {current_idx}")
        prev_interrupt = state.get("pending_interrupt") or {}
        ai_version = prev_interrupt.get("content", "")
        content_to_save = edited_content or ai_version
        if not content_to_save or not content_to_save.strip():
            logger.warning("Drafter: empty content on approve for section '%s' — cannot save", prev_name)
            return {
                "errors": state.get("errors", []) + [f"Cannot approve section '{prev_name}' with empty content"],
                "section_review_decision": None,
                "section_edited_content": None,
                "pending_interrupt": prev_interrupt,
                "grant_theme": grant_theme,
                "draft_outline": draft_outline,
                "grant_requirements": grant_requirements,
                "criteria_map": criteria_map,
                "funder_terms": funder_terms,
            }
        if prev_name not in approved_sections:
            approved_sections[prev_name] = {
                "content": content_to_save,
                "word_count": len(content_to_save.split()),
                "word_limit": prev_section.get("word_limit") or _default_word_limit,
                "within_limit": len(content_to_save.split()) <= (prev_section.get("word_limit") or _default_word_limit),
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info("Drafter: section '%s' approved", prev_name)

            # ── Preference learning: record the approve signal ───────────
            try:
                from backend.agents.preference_learner import record_preference
                await record_preference(
                    grant_id=str(grant_id or ""),
                    section_name=prev_name,
                    ai_version=ai_version,
                    final_version=content_to_save,
                    was_revised=False,
                    theme=grant_theme,
                    funder=grant.get("funder", ""),
                    grant_type=grant.get("grant_type", ""),
                )
            except Exception:
                logger.debug("Preference recording skipped (approve)", exc_info=True)

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
                    word_limit=prev_section.get("word_limit") or _default_word_limit,
                    status="Approved",
                )
            except Exception:
                logger.debug("Notion sync skipped (section approval)", exc_info=True)

    elif review_decision == "revise" and current_idx > 0:
        # Rewrite current section — stay on same index
        section = sections[current_idx - 1]
        section_name_key = section.get("name", f"Section {current_idx}")

        # ── Enforce max revision attempts ────────────────────────────────
        revision_counts = dict(state.get("section_revision_counts", {}))
        revision_counts[section_name_key] = revision_counts.get(section_name_key, 0) + 1
        max_revisions = _settings.max_revision_attempts

        if revision_counts[section_name_key] > max_revisions:
            logger.warning(
                "Drafter: section '%s' hit max revisions (%d) — auto-approving and continuing",
                section_name_key, max_revisions,
            )
            prev_interrupt = state.get("pending_interrupt") or {}
            content = prev_interrupt.get("content", "")
            if content and content.strip():
                approved_sections[section_name_key] = {
                    "content": content,
                    "word_count": len(content.split()),
                    "word_limit": section.get("word_limit") or _default_word_limit,
                    "within_limit": len(content.split()) <= (section.get("word_limit") or _default_word_limit),
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "auto_approved": True,
                    "reason": f"Max revisions ({max_revisions}) reached",
                }
            # Don't return — fall through to "check if all done / write next section"
            # so the drafter continues without a dead-end interrupt.
            review_decision = None
        else:

            prev_interrupt = state.get("pending_interrupt") or {}
            instructions = state.get("section_revision_instructions", {}).get(section.get("name", ""), "")
            critique = state.get("section_critiques", {}).get(section.get("name", ""), "")

            # ── Preference learning: record the revise signal ────────────
            # The revision instruction is gold — it says exactly what was wrong
            try:
                from backend.agents.preference_learner import record_preference
                await record_preference(
                    grant_id=str(grant_id or ""),
                    section_name=section.get("name", ""),
                    ai_version=prev_interrupt.get("content", ""),
                    final_version=prev_interrupt.get("content", ""),  # not yet rewritten
                    was_revised=True,
                    revision_instructions=instructions,
                    theme=grant_theme,
                    funder=grant.get("funder", ""),
                    grant_type=grant.get("grant_type", ""),
                )
            except Exception:
                logger.debug("Preference recording skipped (revise)", exc_info=True)

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
                "section_revision_counts": revision_counts,
                "section_review_decision": None,
                "section_edited_content": None,
                "grant_theme": grant_theme,
                "draft_outline": draft_outline,
                "grant_requirements": grant_requirements,
                "criteria_map": criteria_map,
                "funder_terms": funder_terms,
                "audit_log": state.get("audit_log", []) + [{
                    "node": "drafter",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "action": "section_rewritten",
                    "section": result["section_name"],
                    "revision_number": revision_counts.get(section_name_key, 0),
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
            "criteria_map": criteria_map,
            "funder_terms": funder_terms,
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

    # ── Load previous reviewer feedback (if redrafting after review) ────
    reviewer_feedback_block = ""
    try:
        from backend.db.mongo import draft_reviews
        reviews_cursor = draft_reviews().find({"grant_id": str(grant_id)})
        feedback_parts = []
        async for rev in reviews_cursor:
            perspective = rev.get("perspective", "")
            for sec_name, sec_review in (rev.get("section_reviews") or {}).items():
                if sec_name.lower() == section_name.lower() or section_name.lower() in sec_name.lower():
                    suggestions = sec_review.get("suggestions", [])
                    weaknesses = sec_review.get("weaknesses", [])
                    if suggestions or weaknesses:
                        parts = []
                        if weaknesses:
                            parts.append("Weaknesses: " + "; ".join(weaknesses[:3]))
                        if suggestions:
                            parts.append("Suggestions: " + "; ".join(suggestions[:3]))
                        feedback_parts.append(f"[{perspective.upper()} REVIEWER] {' | '.join(parts)}")
        if feedback_parts:
            reviewer_feedback_block = "PREVIOUS REVIEWER FEEDBACK:\n" + "\n".join(feedback_parts)
            logger.info("Drafter: loaded reviewer feedback for section '%s' (%d chars)", section_name, len(reviewer_feedback_block))
    except Exception:
        logger.debug("Reviewer feedback loading skipped", exc_info=True)

    # ── Preference learning: load user preferences + approved examples ────
    user_preferences = ""
    approved_examples = ""
    try:
        from backend.agents.preference_learner import get_user_preferences, get_approved_examples
        user_preferences = await get_user_preferences(
            theme=grant_theme,
            section_name=section_name,
        )
        approved_examples = await get_approved_examples(
            section_name=section_name,
            theme=grant_theme,
        )
        if user_preferences:
            logger.info("Drafter: loaded user preferences (%d chars)", len(user_preferences))
        if approved_examples:
            logger.info("Drafter: loaded %d approved examples", approved_examples.count("Approved Example"))
    except Exception:
        logger.debug("Preference loading skipped", exc_info=True)

    # Load drafter settings: per-grant overrides global config
    from backend.db.mongo import agent_config
    global_cfg = await agent_config().find_one({"agent": "drafter"}) or {}

    # Load per-grant drafter settings (if any)
    grant_cfg = (grant.get("drafter_settings") or {}) if grant else {}
    if grant_id and not grant_cfg:
        # Grant may have been loaded without drafter_settings projection — re-fetch
        try:
            _grant_with_settings = await grants_scored().find_one(
                {"_id": ObjectId(grant_id)}, {"drafter_settings": 1}
            )
            grant_cfg = ((_grant_with_settings or {}).get("drafter_settings") or {})
        except Exception:
            grant_cfg = {}

    # Merge: per-grant values override global, missing fields fall back to global
    drafter_cfg = {**global_cfg}
    if grant_cfg.get("writing_style"):
        drafter_cfg["writing_style"] = grant_cfg["writing_style"]
    if grant_cfg.get("custom_instructions"):
        drafter_cfg["custom_instructions"] = grant_cfg["custom_instructions"]
    if grant_cfg.get("temperature") is not None:
        drafter_cfg["temperature"] = grant_cfg["temperature"]

    if grant_cfg:
        logger.info("Drafter: using per-grant settings for grant %s (keys: %s)",
                     grant_id, list(grant_cfg.keys()))

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

    # Look up section-specific criteria map
    section_criteria = criteria_map.get(section_name, "")
    # Also try partial matches
    if not section_criteria:
        for map_key, map_val in criteria_map.items():
            if map_key.lower() in section_name.lower() or section_name.lower() in map_key.lower():
                section_criteria = map_val
                break

    # Build prior sections summary for cross-section coherence
    prior_sections_summary = ""
    if approved_sections:
        summary_parts = []
        for sec_name, sec_data in approved_sections.items():
            content = sec_data.get("content", "")
            # Extract first 2 sentences + key claims (bold text) for a compact summary
            sentences = [s.strip() for s in content.split(".") if s.strip()][:3]
            summary = ". ".join(sentences) + "." if sentences else ""
            wc = sec_data.get("word_count", 0)
            summary_parts.append(f"**{sec_name}** ({wc} words): {summary[:300]}")
        prior_sections_summary = "\n".join(summary_parts)
        if prior_sections_summary:
            logger.info("Drafter: passing %d prior sections as context (%d chars)",
                         len(approved_sections), len(prior_sections_summary))

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
        temperature=theme_settings.get("temperature") if theme_settings.get("temperature") is not None else drafter_cfg.get("temperature"),
        tone_override=theme_settings.get("tone", ""),
        voice_override=theme_settings.get("voice", ""),
        strengths_override=theme_settings.get("strengths") or None,
        domain_terms_override=theme_settings.get("domain_terms") or None,
        theme_instructions=theme_settings.get("custom_instructions", ""),
        past_outcomes=past_outcomes,
        # P0 improvements
        criteria_map_for_section=section_criteria,
        funder_terms=funder_terms,
        # Preference learning
        user_preferences=user_preferences,
        approved_examples=approved_examples,
        # Reviewer feedback for redraft context
        reviewer_feedback=reviewer_feedback_block,
        # Cross-section coherence
        prior_sections_summary=prior_sections_summary,
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
            word_limit=section.get("word_limit", _default_word_limit),
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
        "criteria_map": criteria_map,
        "funder_terms": funder_terms,
        "audit_log": state.get("audit_log", []) + [{
            "node": "drafter",
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": "section_written",
            "section": result["section_name"],
            "word_count": result["word_count"],
            "within_limit": result["within_limit"],
            "theme": grant_theme,
            "self_critique": result.get("self_critique", {}),
        }],
    }


def _sections_are_generic(sections: List[Dict]) -> bool:
    """Check if sections are the generic defaults from grant_reader."""
    generic_names = {"Project Overview", "Technical Approach", "Team & Capabilities", "Budget Justification", "Impact & Outcomes"}
    section_names = {s.get("name", "") for s in sections}
    return section_names == generic_names


def should_continue_drafting(state: GrantState) -> str:
    """Router: continue drafting or move to reviewer when done.

    If sections_required is empty, route to pipeline_update to avoid an infinite loop.
    """
    sections = (state.get("grant_requirements") or {}).get("sections_required", [])
    approved = state.get("approved_sections", {})

    if not sections:
        return "pipeline_update"
    if len(approved) >= len(sections):
        return "reviewer"
    return "drafter"
