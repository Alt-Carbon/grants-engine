"""Reviewer Agent — critiques the full assembled draft before export.

Reads all approved sections as a complete document, scores each section
against the grant's evaluation criteria, and produces a change log.

If any section scores below the revision threshold (< 6), produces structured
critique that can be fed back to the drafter for auto-revision.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List

from backend.graph.state import GrantState
from backend.utils.llm import chat, DRAFTER_DEFAULT

logger = logging.getLogger(__name__)

def _get_thresholds():
    """Lazy accessor for reviewer guardrail thresholds from settings."""
    from backend.config.settings import get_settings
    s = get_settings()
    return s.reviewer_revision_threshold, s.reviewer_export_threshold

REVIEW_PROMPT = """You are a senior grant reviewer performing a final quality check on a grant application for AltCarbon.

GRANT: {grant_title}
FUNDER: {funder}
THEME: {theme}

EVALUATION CRITERIA:
{criteria}

COMPLETE DRAFT:
{draft}

Review each section against the evaluation criteria. Be specific and constructive.

Respond ONLY with valid JSON:
{{
  "overall_score": <float 1-10>,
  "section_critiques": {{
    "<section_name>": {{
      "score": <int 1-10>,
      "strengths": ["<specific strength>"],
      "issues": ["<specific issue>"],
      "suggestions": ["<actionable fix>"],
      "revision_instructions": "<if score < 6, specific instructions for rewriting this section; null otherwise>"
    }}
  }},
  "top_3_fixes": [
    "<most impactful fix 1>",
    "<most impactful fix 2>",
    "<most impactful fix 3>"
  ],
  "evidence_gaps_critical": ["<any [EVIDENCE NEEDED] items that are critical to fix>"],
  "coherence_score": <int 1-10>,
  "coherence_notes": "<do sections tell a consistent story? any contradictions or gaps between sections?>",
  "ready_for_export": <true if overall_score >= {export_threshold} else false>,
  "summary": "<2-3 sentence overall assessment>"
}}"""


async def reviewer_node(state: GrantState) -> Dict:
    """LangGraph node: critique the full draft and produce a review report."""
    from backend.db.mongo import grants_scored
    from bson import ObjectId

    grant_id = state.get("selected_grant_id")
    grant = {}
    if grant_id:
        try:
            grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
        except Exception:
            pass

    requirements = state.get("grant_requirements") or {}
    approved_sections = state.get("approved_sections") or {}
    grant_theme = state.get("grant_theme", "climatetech")

    # Assemble full draft text for review
    sections_text = "\n\n".join(
        f"## {name}\n{sec.get('content', '')}"
        for name, sec in approved_sections.items()
    )

    criteria = requirements.get("evaluation_criteria", [])
    criteria_text = "\n".join(
        f"- {c.get('criterion', '')}: {c.get('description', '')} ({c.get('weight', '')})"
        for c in criteria
    ) or "No explicit criteria provided — evaluate for clarity, evidence, and impact."

    # Get theme display name
    theme_display = grant_theme
    try:
        from backend.agents.drafter.theme_profiles import get_theme_profile
        theme_display = get_theme_profile(grant_theme).get("display_name", grant_theme)
    except Exception:
        pass

    revision_threshold, export_threshold = _get_thresholds()

    prompt = REVIEW_PROMPT.format(
        grant_title=grant.get("title", ""),
        funder=grant.get("funder", ""),
        theme=theme_display,
        criteria=criteria_text,
        draft=sections_text[:30000],
        export_threshold=export_threshold,
    )

    try:
        raw = await chat(prompt, model=DRAFTER_DEFAULT, max_tokens=2048)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        review = json.loads(raw)
    except Exception as e:
        logger.error("Reviewer failed: %s", e)
        review = {
            "overall_score": 0,
            "section_critiques": {},
            "top_3_fixes": [],
            "evidence_gaps_critical": [],
            "coherence_score": 0,
            "coherence_notes": "",
            "ready_for_export": False,
            "summary": f"Automated review failed ({e}). Manual review required before export.",
        }

    # Extract sections that need revision (score < threshold)
    sections_needing_revision = []
    section_critiques = review.get("section_critiques", {})
    for sec_name, critique in section_critiques.items():
        if isinstance(critique, dict) and critique.get("score", 0) < revision_threshold:
            sections_needing_revision.append({
                "section_name": sec_name,
                "score": critique.get("score"),
                "issues": critique.get("issues", []),
                "revision_instructions": critique.get("revision_instructions", ""),
            })

    if sections_needing_revision:
        logger.info(
            "Reviewer: %d sections below threshold (<%.1f): %s",
            len(sections_needing_revision),
            revision_threshold,
            [s["section_name"] for s in sections_needing_revision],
        )

    logger.info(
        "Reviewer: overall=%.1f, coherence=%s, ready=%s, revisions_needed=%d",
        review.get("overall_score", 0),
        review.get("coherence_score", "?"),
        review.get("ready_for_export", True),
        len(sections_needing_revision),
    )

    audit_entry = {
        "node": "reviewer",
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall_score": review.get("overall_score"),
        "coherence_score": review.get("coherence_score"),
        "ready_for_export": review.get("ready_for_export"),
        "sections_flagged": [s["section_name"] for s in sections_needing_revision],
    }
    return {
        "reviewer_output": review,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
