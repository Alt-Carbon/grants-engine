"""Dual-Perspective Reviewer — Funder + Scientific review of completed drafts.

Each reviewer agent is configurable via agent_config (agent: "reviewer"):
  - strictness: how harsh the scoring is (lenient / balanced / strict)
  - focus_areas: what to prioritize in the review
  - custom_criteria: additional evaluation criteria beyond the grant's own
  - temperature: LLM creativity for the review
  - custom_instructions: extra reviewer-specific guidance

Standalone module (not a LangGraph node). Reads the latest draft from MongoDB,
runs two independent LLM reviews in parallel, and stores results in draft_reviews.

Usage:
    from backend.agents.dual_reviewer import run_dual_review
    result = await run_dual_review("683a1f...")  # grant_id
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.utils.llm import chat, ANALYST_HEAVY

logger = logging.getLogger(__name__)

# ── Default reviewer profiles ─────────────────────────────────────────────────

REVIEWER_PROFILES: Dict[str, Dict] = {
    "funder": {
        "display_name": "Funder Perspective",
        "role": "senior grant program officer",
        "focus_areas": [
            "Alignment with funder priorities",
            "Budget justification and value for money",
            "Measurable objectives and impact claims",
            "Team credibility for the proposed scope",
            "Competitiveness vs. typical winning applications",
            "Compliance with submission requirements",
        ],
        "scoring_guidance": {
            "lenient": "Be encouraging. Score generously — focus on potential. Flag only critical issues.",
            "balanced": "Be fair and constructive. Acknowledge strengths before issues. Score based on realistic competitiveness.",
            "strict": "Be demanding. Score as a skeptical program officer with limited funding. Every weakness matters.",
        },
        "default_temperature": 0.3,
    },
    "scientific": {
        "display_name": "Scientific Perspective",
        "role": "peer reviewer and domain scientist",
        "focus_areas": [
            "Methodology soundness and reproducibility",
            "MRV rigor and data quality",
            "Scientific novelty vs. incremental work",
            "Scalability evidence and pathway",
            "Uncertainties honestly acknowledged",
            "Claims supported by data or citations",
            "Technical feasibility of proposed approach",
        ],
        "scoring_guidance": {
            "lenient": "Be supportive of emerging approaches. Accept preliminary data. Focus on scientific promise.",
            "balanced": "Expect solid methodology but accept reasonable assumptions. Flag unsupported claims.",
            "strict": "Peer-review standard. Every claim needs evidence. Methodology must be reproducible. No hand-waving.",
        },
        "default_temperature": 0.25,
    },
}

# ── Prompt templates ──────────────────────────────────────────────────────────

REVIEW_PROMPT = """You are a {role} evaluating a grant application.
{role_context}

SCORING APPROACH: {scoring_guidance}

GRANT: {grant_title}
FUNDER: {funder}
{extra_context}

EVALUATION CRITERIA (from the funder):
{criteria}

{custom_criteria_block}

FOCUS YOUR REVIEW ON:
{focus_areas}

{custom_instructions_block}

COMPLETE DRAFT APPLICATION:
{draft}

Review this application thoroughly. Be specific and constructive. {perspective_guidance}

Respond ONLY with valid JSON:
{{
  "overall_score": <float 1-10>,
  "section_reviews": {{
    "<section_name>": {{
      "score": <int 1-10>,
      "strengths": ["<specific strength>"],
      "issues": ["<specific issue>"],
      "suggestions": ["<actionable fix>"]
    }}
  }},
  "top_issues": ["<most critical issue 1>", "<issue 2>", "<issue 3>"],
  "strengths": ["<key strength 1>", "<strength 2>", "<strength 3>"],
  "verdict": "<one of: strong_submit | submit_with_revisions | major_revisions | reconsider>",
  "summary": "<2-3 sentence assessment>"
}}"""

PERSPECTIVE_GUIDANCE = {
    "funder": (
        "Consider: Would you fund this? Is the money well-spent? "
        "Does this stand out from competing proposals? Is the team credible?"
    ),
    "scientific": (
        "Consider: Is the science solid? Are methods reproducible? "
        "Are claims evidence-based? What's missing from a technical standpoint?"
    ),
}

ROLE_CONTEXT = {
    "funder": "You represent the funder and must decide whether this application deserves funding over other proposals.",
    "scientific": "You are evaluating the scientific and technical rigor of this proposal for a funding body.",
}


# ── Core logic ──────────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> Dict:
    """Parse LLM JSON response, stripping markdown fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


async def _run_single_review(
    grant: Dict,
    draft_text: str,
    perspective: str,
    settings: Dict,
) -> Dict:
    """Run a single review perspective with configurable settings."""
    profile = REVIEWER_PROFILES.get(perspective, REVIEWER_PROFILES["funder"])

    # Build grant context
    deep = grant.get("deep_analysis") or {}
    eval_criteria = deep.get("evaluation_criteria") or grant.get("evaluation_criteria") or []
    criteria = ""
    if eval_criteria:
        criteria = "\n".join(
            f"- {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))} "
            f"({c.get('weight', 'unweighted')})"
            for c in eval_criteria
        )
    else:
        criteria = "No explicit criteria provided — evaluate based on standard grant review practices."

    # Extra context varies by perspective
    extra_parts = []
    if perspective == "funder":
        funding = grant.get("max_funding_usd") or grant.get("max_funding") or grant.get("amount") or "Not specified"
        if isinstance(funding, (int, float)):
            funding = f"${funding:,.0f}"
        extra_parts.append(f"FUNDING AMOUNT: {funding}")
        extra_parts.append(f"DEADLINE: {grant.get('deadline') or 'Not specified'}")
    else:
        themes = ", ".join(grant.get("themes_detected", [])) or "Not specified"
        extra_parts.append(f"THEMES: {themes}")
    extra_context = "\n".join(extra_parts)

    # Settings
    strictness = settings.get("strictness", "balanced")
    scoring_guidance = profile["scoring_guidance"].get(strictness, profile["scoring_guidance"]["balanced"])

    # Focus areas: user overrides + defaults
    user_focus = settings.get("focus_areas", [])
    focus_list = user_focus if user_focus else profile["focus_areas"]
    focus_areas = "\n".join(f"- {f}" for f in focus_list)

    # Custom criteria
    custom_criteria = settings.get("custom_criteria", [])
    custom_criteria_block = ""
    if custom_criteria:
        custom_criteria_block = "ADDITIONAL EVALUATION CRITERIA (weight these equally):\n" + "\n".join(
            f"- {c}" for c in custom_criteria
        )

    # Custom instructions
    custom_instructions = settings.get("custom_instructions", "")
    custom_instructions_block = ""
    if custom_instructions:
        custom_instructions_block = f"REVIEWER INSTRUCTIONS:\n{custom_instructions}"

    temperature = settings.get("temperature") or profile.get("default_temperature", 0.3)

    prompt = REVIEW_PROMPT.format(
        role=profile["role"],
        role_context=ROLE_CONTEXT.get(perspective, ""),
        scoring_guidance=scoring_guidance,
        grant_title=grant.get("title") or grant.get("grant_name") or "Untitled",
        funder=grant.get("funder") or "Unknown",
        extra_context=extra_context,
        criteria=criteria,
        custom_criteria_block=custom_criteria_block,
        focus_areas=focus_areas,
        custom_instructions_block=custom_instructions_block,
        draft=draft_text[:30000],
        perspective_guidance=PERSPECTIVE_GUIDANCE.get(perspective, ""),
    )

    try:
        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=3000, temperature=temperature)
        review = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        logger.error("Review JSON parse failed (%s): %s", perspective, e)
        review = _fallback_review(perspective, f"JSON parse error: {e}")
    except Exception as e:
        logger.error("Review LLM call failed (%s): %s", perspective, e)
        review = _fallback_review(perspective, str(e))

    # Ensure required fields
    review.setdefault("overall_score", 5.0)
    review.setdefault("section_reviews", {})
    review.setdefault("top_issues", [])
    review.setdefault("strengths", [])
    review.setdefault("verdict", "major_revisions")
    review.setdefault("summary", "Review completed.")

    return review


def _fallback_review(perspective: str, error: str) -> Dict:
    """Return a minimal review when the LLM call fails."""
    return {
        "overall_score": 0,
        "section_reviews": {},
        "top_issues": [f"Automated {perspective} review failed: {error}"],
        "strengths": [],
        "verdict": "major_revisions",
        "summary": f"The {perspective} review could not be completed due to an error. Please retry.",
    }


async def run_dual_review(grant_id: str) -> Dict:
    """Run funder + scientific reviews on the latest draft for a grant.

    Loads reviewer settings from agent_config, then runs both perspectives in parallel.
    Returns {"funder": {...}, "scientific": {...}} with full review data.
    Stores both reviews in the draft_reviews collection.
    """
    from backend.db.mongo import grant_drafts, grants_scored, draft_reviews, agent_config
    from bson import ObjectId

    # Load grant
    grant = await grants_scored().find_one({"_id": ObjectId(grant_id)})
    if not grant:
        raise ValueError(f"Grant {grant_id} not found in grants_scored")

    # Load latest draft
    draft_doc = await grant_drafts().find_one(
        {"grant_id": grant_id},
        sort=[("version", -1)],
    )
    if not draft_doc:
        raise ValueError(f"No draft found for grant {grant_id}")

    # Assemble draft text
    sections = draft_doc.get("sections", {})
    draft_text = "\n\n".join(
        f"## {name}\n{sec.get('content', '')}"
        for name, sec in sections.items()
    )

    if not draft_text.strip():
        raise ValueError("Draft has no content")

    # Load reviewer settings
    reviewer_cfg = await agent_config().find_one({"agent": "reviewer"}) or {}
    funder_settings = reviewer_cfg.get("funder", {})
    scientific_settings = reviewer_cfg.get("scientific", {})

    grant_title = grant.get("title") or grant.get("grant_name") or "Untitled"
    logger.info(
        "Starting dual review for '%s' (grant_id=%s, draft v%d, funder_strictness=%s, sci_strictness=%s)",
        grant_title, grant_id, draft_doc.get("version", 0),
        funder_settings.get("strictness", "balanced"),
        scientific_settings.get("strictness", "balanced"),
    )

    # Run both perspectives in parallel
    funder_result, scientific_result = await asyncio.gather(
        _run_single_review(grant, draft_text, "funder", funder_settings),
        _run_single_review(grant, draft_text, "scientific", scientific_settings),
    )

    now = datetime.now(timezone.utc).isoformat()
    draft_id = str(draft_doc["_id"])
    draft_version = draft_doc.get("version", 0)

    # Store reviews
    for perspective, result in [("funder", funder_result), ("scientific", scientific_result)]:
        review_doc = {
            "grant_id": grant_id,
            "draft_id": draft_id,
            "draft_version": draft_version,
            "perspective": perspective,
            **result,
            "created_at": now,
        }
        # Upsert — replace previous review of same perspective for this grant
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": perspective},
            review_doc,
            upsert=True,
        )

    logger.info(
        "Dual review complete for '%s': funder=%.1f (%s), scientific=%.1f (%s)",
        grant_title,
        funder_result.get("overall_score", 0),
        funder_result.get("verdict", "?"),
        scientific_result.get("overall_score", 0),
        scientific_result.get("verdict", "?"),
    )

    # Update heartbeat
    try:
        from backend.agents.agent_context import update_heartbeat
        await update_heartbeat("reviewer", {
            "status": "success",
            "grant_title": grant_title[:50],
            "funder_score": funder_result.get("overall_score", 0),
            "scientific_score": scientific_result.get("overall_score", 0),
            "funder_verdict": funder_result.get("verdict", ""),
            "scientific_verdict": scientific_result.get("verdict", ""),
        })
    except Exception:
        logger.debug("Heartbeat update skipped (reviewer)", exc_info=True)

    return {"funder": funder_result, "scientific": scientific_result}
