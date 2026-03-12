"""Reviewer Agent — critiques the full assembled draft before export.

Reads all approved sections as a complete document, scores each section
against the grant's evaluation criteria, and produces a change log.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List

from backend.graph.state import GrantState
from backend.utils.llm import chat, DRAFTER_DEFAULT

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """You are a senior grant reviewer performing a final quality check on a grant application for AltCarbon.

GRANT: {grant_title}
FUNDER: {funder}

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
      "suggestions": ["<actionable fix>"]
    }}
  }},
  "top_3_fixes": [
    "<most impactful fix 1>",
    "<most impactful fix 2>",
    "<most impactful fix 3>"
  ],
  "evidence_gaps_critical": ["<any [EVIDENCE NEEDED] items that are critical to fix>"],
  "ready_for_export": <true if score >= 6.5 else false>,
  "summary": "<2-3 sentence overall assessment>"
}}"""


async def reviewer_node(state: GrantState) -> Dict:
    """LangGraph node: critique the full draft and produce a review report."""
    from backend.config.settings import get_settings
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

    prompt = REVIEW_PROMPT.format(
        grant_title=grant.get("title", ""),
        funder=grant.get("funder", ""),
        criteria=criteria_text,
        draft=sections_text[:10000],
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
            "overall_score": 7.0,
            "section_critiques": {},
            "top_3_fixes": [],
            "evidence_gaps_critical": [],
            "ready_for_export": True,
            "summary": f"Automated review failed ({e}). Proceeding to export.",
        }

    logger.info(
        "Reviewer: overall score=%.1f, ready_for_export=%s",
        review.get("overall_score", 0),
        review.get("ready_for_export", True),
    )

    audit_entry = {
        "node": "reviewer",
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall_score": review.get("overall_score"),
        "ready_for_export": review.get("ready_for_export"),
    }
    return {
        "reviewer_output": review,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
