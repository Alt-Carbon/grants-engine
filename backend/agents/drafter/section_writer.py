"""Section Writer — writes one grant application section at a time.

Theme-aware: uses domain terminology, tone guidance, and section-specific
knowledge from Pinecone (articulation docs + company knowledge).

Grounded in:
- Section-specific RAG (targeted Pinecone chunks for THIS section)
- Theme profile (domain terms, tone, strengths)
- Draft outline (cross-section coherence)
- Past application style examples
- Grant evaluation criteria

Flags [EVIDENCE NEEDED: description] rather than inventing facts.
Accepts revision instructions to rewrite with human feedback.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from backend.utils.llm import chat, DRAFTER_DEFAULT, resolve_drafter_model

logger = logging.getLogger(__name__)

WRITE_PROMPT = """You are writing a section of a grant application for AltCarbon.

THEME CONTEXT: {theme_display}
{tone_guidance}

DOMAIN TERMINOLOGY (use these terms naturally where relevant):
{domain_terms}

KEY STRENGTHS TO HIGHLIGHT (where relevant to this section):
{strengths}

GRANT: {grant_title}
FUNDER: {funder}
SECTION: {section_name} (section {section_num} of {total_sections})
SECTION DESCRIPTION: {section_description}
WORD LIMIT: {word_limit} words{word_limit_note}

{outline_block}

EVALUATION CRITERIA FOR THIS GRANT:
{criteria}

COMPANY KNOWLEDGE FOR THIS SECTION (use as primary evidence base):
{section_context}

STYLE EXAMPLES (match this voice and tone — these are AltCarbon's past applications):
{style_examples}

{revision_block}

INSTRUCTIONS:
- Write ONLY this section, nothing else
- Stay within the word limit
- Ground every claim in the company knowledge provided
- Use the domain terminology naturally — don't force it, but prefer precise terms
- Follow the tone guidance for this theme
- If an outline was provided, ensure this section aligns with the overall narrative
- Match AltCarbon's voice from the style examples
- For any required claim you cannot support with the provided knowledge, write exactly: [EVIDENCE NEEDED: <brief description of what's missing>]
- Do NOT invent statistics, team names, funding amounts, or technical claims
- Be specific and concrete — avoid vague platitudes
- Address the evaluation criteria directly

Write the section now:"""

REVISION_PROMPT = """You previously wrote this section:

{previous_content}

The reviewer left this feedback:
{critique}

Revision instructions:
{instructions}

Rewrite the section addressing all feedback. Keep the same word limit and evaluation criteria in mind."""


async def get_section_context(
    theme_key: str,
    section_name: str,
    grant_title: str,
    grant_themes: List[str],
    company_context: str = "",
    max_chars: int = 6000,
) -> str:
    """Retrieve section-specific knowledge from Pinecone.

    Combines:
    1. Theme + section targeted Pinecone query
    2. Articulation document chunks matching this section type
    3. Fallback to general company_context if Pinecone returns nothing
    """
    from backend.agents.drafter.theme_profiles import (
        get_articulation_sections,
        get_evidence_query,
    )

    evidence_query = get_evidence_query(theme_key, section_name)
    art_sections = get_articulation_sections(section_name)

    # Build a rich query combining theme evidence + section + grant title
    query = f"{evidence_query} {section_name} {grant_title[:100]}"

    parts: List[str] = []
    total = 0

    try:
        from backend.db.pinecone_store import is_pinecone_configured, search_similar

        if is_pinecone_configured():
            # Phase 1: Section-specific search with theme filter
            pc_filter: Dict = {}
            if grant_themes:
                pc_filter["themes"] = {"$in": grant_themes}

            results = search_similar(query, top_k=6, filter_dict=pc_filter or None)

            # Phase 2: Search for articulation doc chunks specifically
            if art_sections:
                art_query = " ".join(art_sections) + f" {theme_key} AltCarbon"
                art_results = search_similar(art_query, top_k=4, filter_dict=pc_filter or None)
                # Merge, dedup
                seen_ids = {r.get("id", r.get("_id", "")) for r in results}
                for r in art_results:
                    rid = r.get("id", r.get("_id", ""))
                    if rid and rid not in seen_ids:
                        results.append(r)
                        seen_ids.add(rid)

            for r in results:
                content = r.get("content") or r.get("text", "")
                source = r.get("source_title", r.get("title", ""))
                doc_type = r.get("doc_type", "misc")
                if content and total + len(content) <= max_chars:
                    parts.append(f"[{doc_type} | {source}]\n{content}")
                    total += len(content)
    except Exception as e:
        logger.debug("Section-specific Pinecone search failed: %s", e)

    if parts:
        return "\n\n---\n\n".join(parts)

    # Fallback: use the general company_context (truncated to max_chars)
    if company_context:
        return company_context[:max_chars]

    return "No company context available for this section."


async def write_section(
    section: Dict,
    section_num: int,
    total_sections: int,
    grant: Dict,
    company_context: str,
    style_examples: str,
    previous_content: Optional[str] = None,
    critique: Optional[str] = None,
    revision_instructions: Optional[str] = None,
    model: Optional[str] = None,
    # Theme-aware params
    theme_key: str = "",
    section_context: str = "",
    draft_outline: str = "",
) -> Dict:
    """Write or rewrite a single section. Returns section dict with content + metadata."""
    from backend.agents.drafter.theme_profiles import get_theme_profile

    section_name = section.get("name", f"Section {section_num}")
    word_limit = section.get("word_limit") or 500
    word_limit_note = " (hard limit — do not exceed)" if section.get("word_limit") else " (guideline)"

    # Load theme profile
    profile = get_theme_profile(theme_key) if theme_key else {}
    theme_display = profile.get("display_name", "Climate Tech / CDR")
    tone_guidance = f"TONE: {profile['tone']}" if profile.get("tone") else ""
    domain_terms = ", ".join(profile.get("domain_terms", [])[:12]) if profile.get("domain_terms") else "CDR, ERW, biochar, MRV, carbon credits"
    strengths = "\n".join(f"- {s}" for s in profile.get("strengths", [])) if profile.get("strengths") else ""

    criteria_text = ""
    eval_criteria = grant.get("evaluation_criteria", [])
    if eval_criteria:
        criteria_text = "\n".join(
            f"- {c.get('criterion', '')}: {c.get('description', '')} ({c.get('weight', '')})"
            for c in eval_criteria
        )
    else:
        criteria_text = "No specific criteria listed — aim for clarity, evidence, and impact."

    # Outline block for cross-section coherence
    outline_block = ""
    if draft_outline:
        outline_block = f"DRAFT OUTLINE (ensure this section aligns with the overall narrative):\n{draft_outline}"

    revision_block = ""
    if previous_content and revision_instructions:
        revision_block = REVISION_PROMPT.format(
            previous_content=previous_content,
            critique=critique or "(No specific critique provided)",
            instructions=revision_instructions,
        )

    # Use section-specific context if available, otherwise fall back to general
    effective_context = section_context if section_context else (company_context[:6000] if company_context else "No company context available.")

    prompt = WRITE_PROMPT.format(
        theme_display=theme_display,
        tone_guidance=tone_guidance,
        domain_terms=domain_terms,
        strengths=strengths,
        grant_title=grant.get("title", ""),
        funder=grant.get("funder", ""),
        section_name=section_name,
        section_num=section_num,
        total_sections=total_sections,
        section_description=section.get("description", ""),
        word_limit=word_limit,
        word_limit_note=word_limit_note,
        outline_block=outline_block,
        criteria=criteria_text,
        section_context=effective_context,
        style_examples=style_examples[:2000] if style_examples else "No style examples available.",
        revision_block=revision_block,
    )

    try:
        content = await chat(prompt, model=model or DRAFTER_DEFAULT, max_tokens=2048)
        content = content.strip()
    except Exception as e:
        logger.error("Section writer failed for %s: %s", section_name, e)
        content = f"[SECTION GENERATION FAILED: {e}]\n\n[EVIDENCE NEEDED: Full section content for {section_name}]"

    # Count words
    word_count = len(content.split())
    within_limit = word_count <= word_limit

    # Extract evidence gaps
    evidence_gaps = re.findall(r"\[EVIDENCE NEEDED:[^\]]+\]", content)

    return {
        "section_name": section_name,
        "content": content,
        "word_count": word_count,
        "word_limit": word_limit,
        "within_limit": within_limit,
        "evidence_gaps": evidence_gaps,
        "criteria_addressed": [c.get("criterion", "") for c in eval_criteria],
        "is_revision": bool(revision_instructions),
        "theme_key": theme_key,
    }
