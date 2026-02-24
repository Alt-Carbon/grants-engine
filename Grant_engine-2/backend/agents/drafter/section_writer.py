"""Section Writer — writes one grant application section at a time.

Grounded in:
- Company Brain context (RAG chunks relevant to this section + grant themes)
- Past application style examples (loaded once, reused)
- Grant evaluation criteria (what the funder scores on)
- Word limit constraints

Flags [EVIDENCE NEEDED: description] rather than inventing facts.
Accepts revision instructions to rewrite with human feedback.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from backend.utils.llm import chat, SONNET

logger = logging.getLogger(__name__)

WRITE_PROMPT = """You are writing a section of a grant application for AltCarbon, a climate technology company.

GRANT: {grant_title}
FUNDER: {funder}
SECTION: {section_name} (section {section_num} of {total_sections})
SECTION DESCRIPTION: {section_description}
WORD LIMIT: {word_limit} words{word_limit_note}

EVALUATION CRITERIA FOR THIS GRANT:
{criteria}

COMPANY KNOWLEDGE (use this as your primary evidence base):
{company_context}

STYLE EXAMPLES (match this voice and tone — these are AltCarbon's past applications):
{style_examples}

{revision_block}

INSTRUCTIONS:
- Write ONLY this section, nothing else
- Stay within the word limit
- Ground every claim in the company knowledge provided
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
) -> Dict:
    """Write or rewrite a single section. Returns section dict with content + metadata."""

    section_name = section.get("name", f"Section {section_num}")
    word_limit = section.get("word_limit") or 500
    word_limit_note = " (hard limit — do not exceed)" if section.get("word_limit") else " (guideline)"

    criteria_text = ""
    eval_criteria = grant.get("evaluation_criteria", [])
    if eval_criteria:
        criteria_text = "\n".join(
            f"- {c.get('criterion', '')}: {c.get('description', '')} ({c.get('weight', '')})"
            for c in eval_criteria
        )
    else:
        criteria_text = "No specific criteria listed — aim for clarity, evidence, and impact."

    revision_block = ""
    if previous_content and revision_instructions:
        revision_block = REVISION_PROMPT.format(
            previous_content=previous_content,
            critique=critique or "(No specific critique provided)",
            instructions=revision_instructions,
        )

    prompt = WRITE_PROMPT.format(
        grant_title=grant.get("title", ""),
        funder=grant.get("funder", ""),
        section_name=section_name,
        section_num=section_num,
        total_sections=total_sections,
        section_description=section.get("description", ""),
        word_limit=word_limit,
        word_limit_note=word_limit_note,
        criteria=criteria_text,
        company_context=company_context[:4000] if company_context else "No company context available.",
        style_examples=style_examples[:2000] if style_examples else "No style examples available.",
        revision_block=revision_block,
    )

    try:
        content = await chat(prompt, model=SONNET, max_tokens=2048)
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
    }
