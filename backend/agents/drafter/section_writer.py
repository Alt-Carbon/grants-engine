"""Section Writer — writes one grant application section at a time.

Theme-aware: uses domain terminology, tone guidance, and section-specific
knowledge from Pinecone (articulation docs + company knowledge).

Grounded in:
- Section-specific RAG (targeted Pinecone chunks for THIS section)
- Theme profile (domain terms, tone, strengths)
- Draft outline (cross-section coherence)
- Past application style examples
- Grant evaluation criteria
- Criteria-evidence mapping (pre-computed by drafter_node)

Flags [EVIDENCE NEEDED: description] rather than inventing facts.
Accepts revision instructions to rewrite with human feedback.
Self-critique loop: reviews own output before returning to human.
Auto-resolves evidence gaps via Pinecone search.
"""
from __future__ import annotations

import logging
import json
import re
from typing import Dict, List, Optional

from backend.utils.llm import chat, DRAFTER_DEFAULT, ANALYST_LIGHT, resolve_drafter_model

logger = logging.getLogger(__name__)

WRITE_PROMPT = """You are writing a section of a grant application for {company_name}.

WRITING STYLE: {writing_style}
THEME CONTEXT: {theme_display}
{tone_guidance}
{voice_guidance}

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

STYLE EXAMPLES (match this voice and tone — these are {company_name}'s past applications):
{style_examples}

{custom_instructions_block}

{past_outcomes_block}

{revision_block}

MANDATORY WRITING RULES (violating these will trigger a rewrite):
1. DECLARATIVE VOICE: Use "will" not "may/could/aim to". State what you will do, not what you hope to do.
2. NO EMPTY ADJECTIVES: Never write "innovative", "cutting-edge", "state-of-the-art", "world-class", "groundbreaking", "revolutionary", "game-changing", "holistic", "synergistic", "paradigm-shifting", "next-generation". DESCRIBE the innovation instead of labeling it.
3. QUANTIFY EVERY CLAIM: Every claim of scale, impact, or capability must include a number, unit, comparison, or citation. No "significant impact" — write "23% increase in soil organic carbon across 12 field plots".
4. NO "NOT ONLY X BUT ALSO Y": State both points directly. Write "ERW consumes atmospheric CO2 and exports alkalinity to rivers" not "ERW not only captures carbon but also improves soil health".
5. PROBLEM → GAP → STRATEGY: Structure as: what is known → what is missing → how this proposal fills it.
6. PRECISE TERMINOLOGY: Name exact methods, species, locations, equipment. "MC-ICP-MS" not "advanced instruments".
7. BOLD KEY CLAIMS: Bold the 3-5 most important sentences (gap statement, main deliverable, key differentiator). Do not bold entire paragraphs.
8. EVIDENCE HIERARCHY: Published results (with citations) first, then pilot data, then proposed work.
9. LOGICAL CONNECTORS: Use "Thus,", "Hence,", "However,", "Since". Avoid filler transitions like "Additionally,", "Furthermore,", "Moreover,".
10. ONE CLAIM PER PARAGRAPH with supporting evidence. No paragraphs without a number, citation, or data reference.
11. NEVER HEDGE when you have evidence. State data as fact. If you lack data, flag [EVIDENCE NEEDED].
12. SCIENTIFIC PARAGRAPH STRUCTURE (especially for Technical Approach, Methodology, Background sections): Each paragraph must follow Finding → Evidence → Implication → Justification. Open with the key observation/fact. Support with data/citations. State what it means. Close with why it justifies the next step. Never start with the method before establishing why it is needed. Never end with a finding and no justification.

ADDITIONAL INSTRUCTIONS:
- Write ONLY this section, nothing else
- Stay within the word limit
- Ground every claim in the company knowledge provided
- Use the domain terminology naturally — don't force it, but prefer precise terms
- Follow the tone and voice guidance consistently
- If an outline was provided, ensure this section aligns with the overall narrative
- Match {company_name}'s voice from the style examples
- For any required claim you cannot support with the provided knowledge, write exactly: [EVIDENCE NEEDED: <brief description of what's missing>]
- Do NOT invent statistics, team names, funding amounts, or technical claims
- Address the evaluation criteria directly

Write the section now:"""

SELF_CRITIQUE_PROMPT = """You just wrote a section of a grant application. Now review your own work critically.

SECTION: {section_name}
WORD LIMIT: {word_limit}

EVALUATION CRITERIA FOR THIS GRANT:
{criteria}

{criteria_map_block}

YOUR DRAFT:
{content}

Score yourself honestly on these dimensions:
1. CRITERIA COVERAGE (1-5): Does every paragraph directly address at least one evaluation criterion? Are any criteria completely missing?
2. EVIDENCE GROUNDING (1-5): Are all claims backed by evidence from the company knowledge? Or are there vague platitudes like "innovative approach" or "significant impact"? Every paragraph must have at least one number, citation, or data reference.
3. WORD COUNT (pass/fail): Is it within the word limit of {word_limit}?
4. SPECIFICITY (1-5): Would a skeptical reviewer find unsupported assertions? Are there concrete numbers, dates, and names? Check for banned adjectives: "innovative", "cutting-edge", "state-of-the-art", "world-class", "groundbreaking", "revolutionary", "game-changing", "holistic", "synergistic", "paradigm-shifting". If ANY banned word appears, score 1.
5. FUNDER ALIGNMENT (1-5): Does this section use the funder's language and address what THIS specific funder values?
6. VOICE CHECK (pass/fail): Does it use declarative "will" voice (not "aim to", "could", "may")? Are there any "not only X but also Y" constructions? Any filler transitions ("Additionally", "Furthermore", "Moreover")? Any hedging ("we believe", "it is expected")?

Respond ONLY with valid JSON:
{{
  "scores": {{"criteria_coverage": <int>, "evidence_grounding": <int>, "specificity": <int>, "funder_alignment": <int>}},
  "word_count_ok": <bool>,
  "voice_check_ok": <bool>,
  "banned_words_found": ["<word1>", ...],
  "weaknesses": ["<specific weakness 1>", "<weakness 2>"],
  "needs_rewrite": <bool>,
  "rewritten": "<full rewritten section if needs_rewrite is true, else null>"
}}

Rules:
- Set needs_rewrite=true if ANY score < 4 OR word_count_ok is false OR voice_check_ok is false OR banned_words_found is non-empty
- If rewriting: remove ALL banned adjectives, fix hedging language, replace "not only X but also Y" with direct statements, ensure every paragraph has evidence
- The rewrite must stay within the word limit
- If all scores >= 4 and all checks pass, set needs_rewrite=false and rewritten=null"""


EVIDENCE_RESOLVE_MAX_ATTEMPTS = 3  # Max gaps to auto-resolve per section


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
                from backend.config.settings import get_settings as _gs
                art_query = " ".join(art_sections) + f" {theme_key} {_gs().company_name}"
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
                if not content:
                    continue
                if total + len(content) > max_chars:
                    continue  # Skip this result, try smaller ones
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


async def _self_critique(
    content: str,
    section_name: str,
    word_limit: int,
    criteria_text: str,
    criteria_map_for_section: str,
    model: Optional[str] = None,
) -> Dict:
    """Run self-critique on a written section. Returns improved content if needed.

    The LLM reviews its own output against evaluation criteria and rewrites
    if any quality dimension scores below 4/5.
    """
    criteria_map_block = ""
    if criteria_map_for_section:
        criteria_map_block = f"CRITERIA→EVIDENCE MAP FOR THIS SECTION (you MUST address all of these):\n{criteria_map_for_section}"

    prompt = SELF_CRITIQUE_PROMPT.format(
        section_name=section_name,
        word_limit=word_limit,
        criteria=criteria_text,
        criteria_map_block=criteria_map_block,
        content=content,
    )

    try:
        raw = await chat(prompt, model=model or ANALYST_LIGHT, max_tokens=3000, temperature=0.2)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)

        if result.get("needs_rewrite") and result.get("rewritten"):
            rewritten = result["rewritten"].strip()
            rewritten_word_count = len(rewritten.split())
            # Sanity: rewrite must be non-empty and reasonably sized
            if len(rewritten) > 50:
                if rewritten_word_count > word_limit:
                    logger.warning(
                        "Self-critique rewrite for '%s' exceeds word limit (%d/%d) — keeping original",
                        section_name, rewritten_word_count, word_limit,
                    )
                else:
                    logger.info(
                        "Self-critique rewrote '%s' (scores: %s, weaknesses: %s)",
                        section_name,
                        result.get("scores", {}),
                        result.get("weaknesses", [])[:3],
                    )
                    return {
                        "content": rewritten,
                        "was_rewritten": True,
                        "scores": result.get("scores", {}),
                        "weaknesses": result.get("weaknesses", []),
                    }

        logger.info(
            "Self-critique passed '%s' (scores: %s)",
            section_name, result.get("scores", {}),
        )
        return {
            "content": content,
            "was_rewritten": False,
            "scores": result.get("scores", {}),
            "weaknesses": result.get("weaknesses", []),
        }

    except Exception as e:
        logger.warning("Self-critique failed for '%s': %s — keeping original", section_name, e)
        return {"content": content, "was_rewritten": False, "scores": {}, "weaknesses": []}


async def _resolve_evidence_gaps(
    content: str,
    grant_themes: List[str],
    theme_key: str,
) -> str:
    """Attempt to auto-fill [EVIDENCE NEEDED: ...] gaps via Pinecone search.

    For each gap, searches Pinecone with the gap description as the query.
    Replaces the flag with found evidence + source attribution.
    Keeps the flag if no evidence is found — human must still fill it.
    """
    gaps = re.findall(r"\[EVIDENCE NEEDED:\s*([^\]]+)\]", content, re.IGNORECASE)
    if not gaps:
        return content

    try:
        from backend.db.pinecone_store import is_pinecone_configured, search_similar
        from backend.config.settings import get_settings as _get_settings
        if not is_pinecone_configured():
            return content
    except Exception:
        return content

    resolved_count = 0
    for gap_desc in gaps[:EVIDENCE_RESOLVE_MAX_ATTEMPTS]:
        try:
            pc_filter = {}
            if grant_themes:
                pc_filter["themes"] = {"$in": grant_themes}

            results = search_similar(
                f"{gap_desc} {theme_key} {_get_settings().company_name}",
                top_k=3,
                filter_dict=pc_filter or None,
            )

            if results:
                best = results[0]
                evidence = best.get("content") or best.get("text", "")
                source = best.get("source_title", best.get("title", "company knowledge"))

                if evidence and len(evidence.strip()) > 30:
                    # Truncate to a reasonable size for inline insertion
                    evidence_snippet = evidence.strip()[:500]
                    # Replace last partial sentence if truncated
                    if len(evidence.strip()) > 500:
                        last_period = evidence_snippet.rfind(".")
                        if last_period > 200:
                            evidence_snippet = evidence_snippet[:last_period + 1]

                    content = re.sub(
                        re.escape(f"[EVIDENCE NEEDED: {gap_desc}]"),
                        f"{evidence_snippet} [Source: {source}]",
                        content,
                        flags=re.IGNORECASE,
                    )
                    resolved_count += 1
        except Exception as e:
            logger.debug("Evidence gap resolution failed for '%s': %s", gap_desc[:50], e)

    if resolved_count:
        logger.info("Auto-resolved %d/%d evidence gaps", resolved_count, len(gaps))

    return content


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
    # Drafter settings overrides
    writing_style: str = "professional",
    custom_instructions: str = "",
    temperature: Optional[float] = None,
    tone_override: str = "",
    voice_override: str = "",
    strengths_override: Optional[List[str]] = None,
    domain_terms_override: Optional[List[str]] = None,
    theme_instructions: str = "",
    past_outcomes: str = "",
    # P0 improvements
    criteria_map_for_section: str = "",
    enable_self_critique: bool = True,
    funder_terms: str = "",
    # Preference learning
    user_preferences: str = "",
    approved_examples: str = "",
) -> Dict:
    """Write or rewrite a single section. Returns section dict with content + metadata.

    P0 improvements:
    - criteria_map_for_section: pre-computed criteria→evidence mapping for this section
    - enable_self_critique: run self-critique loop after writing (default True)
    - funder_terms: extracted funder language to mirror in writing
    """
    from backend.agents.drafter.theme_profiles import get_theme_profile
    from backend.config.settings import get_settings

    section_name = section.get("name", f"Section {section_num}")
    word_limit = section.get("word_limit") or get_settings().default_section_word_limit
    word_limit_note = " (hard limit — do not exceed)" if section.get("word_limit") else " (guideline)"

    # Load theme profile
    profile = get_theme_profile(theme_key) if theme_key else {}
    theme_display = profile.get("display_name", "Climate Tech / CDR")

    # Tone: user override > theme profile
    tone_text = tone_override or profile.get("tone", "")
    tone_guidance = f"TONE: {tone_text}" if tone_text else ""

    # Voice: user override
    voice_guidance = f"VOICE: {voice_override}" if voice_override else ""

    # Domain terms: user override > theme profile
    terms_list = domain_terms_override if domain_terms_override else profile.get("domain_terms", [])
    domain_terms = ", ".join(terms_list[:12]) if terms_list else "CDR, ERW, biochar, MRV, carbon credits"

    # Strengths: user override > theme profile
    strengths_list = strengths_override if strengths_override else profile.get("strengths", [])
    strengths = "\n".join(f"- {s}" for s in strengths_list) if strengths_list else ""

    # Writing style description
    style_desc = {
        "professional": "Professional & Corporate — clear, formal, confident. Use strong assertions, structured arguments, and business-oriented language.",
        "scientific": "Scientific & Academic — rigorous, precise, evidence-driven. Every paragraph follows Finding → Evidence → Implication → Justification. Open with the established fact, support with data/citations, state what it means, close with why it justifies the proposed work. Use technical terminology, cite methodologies, and maintain scholarly tone.",
        "startup-founder": "Startup-Founder voice for corporate/buyer grants — direct, operationally honest, conversational confidence. Use 'we' not 'I'. Use em-dashes for emphasis. Admit uncertainty where honest ('results are not guaranteed'). Lead with operational proof (deployment acres, verified tonnes, buyer names) not publications. No literature reviews, no academic formalities. Tight sentences, every word earns its place. Credibility comes from field operations and buyer validation (Google, Stripe, Shopify), not impact factors.",
    }.get(writing_style, writing_style)

    # Funder language mirroring
    funder_terms_block = ""
    if funder_terms:
        funder_terms_block = f"\nFUNDER'S LANGUAGE (mirror these terms — use their vocabulary, not ours):\n{funder_terms}\n"

    # Criteria-evidence map for this section
    criteria_map_block = ""
    if criteria_map_for_section:
        criteria_map_block = f"\nCRITERIA→EVIDENCE MAP FOR THIS SECTION (address ALL of these):\n{criteria_map_for_section}\n"

    # Custom instructions block — merge global + theme-specific
    all_instructions = []
    if custom_instructions:
        all_instructions.append(custom_instructions)
    if theme_instructions:
        all_instructions.append(theme_instructions)
    custom_instructions_block = ""
    if all_instructions:
        custom_instructions_block = f"CUSTOM INSTRUCTIONS (follow these closely):\n" + "\n".join(all_instructions)

    # Past outcomes block — lessons from previous applications
    past_outcomes_block = past_outcomes if past_outcomes else ""

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

    # User preferences block (learned from past editing patterns)
    preferences_block = ""
    if user_preferences:
        preferences_block = f"\n{user_preferences}\n"

    # Approved examples block (user's own approved sections as few-shot)
    approved_examples_block = ""
    if approved_examples:
        approved_examples_block = f"\n{approved_examples}\n"

    # Build the enriched custom instructions with all learned context
    enriched_custom = preferences_block + funder_terms_block + criteria_map_block + approved_examples_block + custom_instructions_block

    from backend.config.settings import get_settings as _get_settings
    prompt = WRITE_PROMPT.format(
        company_name=_get_settings().company_name,
        writing_style=style_desc,
        theme_display=theme_display,
        tone_guidance=tone_guidance,
        voice_guidance=voice_guidance,
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
        custom_instructions_block=enriched_custom,
        past_outcomes_block=past_outcomes_block,
        revision_block=revision_block,
    )

    try:
        content = await chat(
            prompt, model=model or DRAFTER_DEFAULT, max_tokens=2048,
            temperature=temperature,
        )
        content = content.strip()
    except Exception as e:
        logger.error("Section writer failed for %s: %s", section_name, e)
        content = f"[SECTION GENERATION FAILED: {e}]\n\n[EVIDENCE NEEDED: Full section content for {section_name}]"

    # ── P0: Auto-resolve evidence gaps ──────────────────────────────────────
    grant_themes = grant.get("themes_detected", [])
    content = await _resolve_evidence_gaps(content, grant_themes, theme_key)

    # ── P0: Self-critique loop ──────────────────────────────────────────────
    self_critique_result = {}
    if enable_self_critique and not revision_instructions:
        # Don't self-critique revisions (human already gave specific feedback)
        self_critique_result = await _self_critique(
            content=content,
            section_name=section_name,
            word_limit=word_limit,
            criteria_text=criteria_text,
            criteria_map_for_section=criteria_map_for_section,
            model=model,
        )
        content = self_critique_result.get("content", content)

    # Count words (after potential rewrite)
    word_count = len(content.split())
    within_limit = word_count <= word_limit

    # Extract remaining evidence gaps (after auto-resolve)
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
        "self_critique": {
            "was_rewritten": self_critique_result.get("was_rewritten", False),
            "scores": self_critique_result.get("scores", {}),
            "weaknesses": self_critique_result.get("weaknesses", []),
        },
    }
