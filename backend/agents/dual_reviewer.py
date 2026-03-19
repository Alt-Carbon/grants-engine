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


COHERENCE_PROMPT = """You are reviewing a COMPLETE grant application for cross-section coherence.

GRANT: {grant_title}
FUNDER: {funder}

COMPLETE DRAFT:
{draft}

Review the application as a WHOLE (not section-by-section). Check for:

1. NARRATIVE CONSISTENCY: Is there a single coherent story from problem → solution → impact? Or do sections tell different stories?
2. BUDGET ↔ ACTIVITIES MATCH: Does the budget justify the activities described in the technical approach? Are there activities with no budget, or budget items with no corresponding activity?
3. CLAIMS ↔ EVIDENCE MATCH: Do impact claims in the outcomes section match what the methodology can actually deliver? Are there claims without methodological backing?
4. CROSS-SECTION CONTRADICTIONS: Do any sections contradict each other? (e.g., timeline says 12 months but impact claims require 24 months of data)
5. UNNECESSARY REPETITION: Are the same points made in multiple sections without adding new value?
6. MISSING THREADS: Are there important elements introduced in one section but never followed up? (e.g., partnerships mentioned in team section but absent from project plan)

Respond ONLY with valid JSON:
{{
  "coherence_score": <float 1-10>,
  "narrative_consistent": <bool>,
  "issues": [
    {{"type": "<contradiction|budget_mismatch|unsupported_claim|repetition|missing_thread>", "sections_involved": ["<sec1>", "<sec2>"], "description": "<specific issue>", "fix": "<suggested fix>"}}
  ],
  "overall_assessment": "<2-3 sentence assessment of application coherence>"
}}"""


async def _run_coherence_review(
    grant: Dict,
    draft_text: str,
) -> Dict:
    """Run holistic coherence review across all sections."""
    prompt = COHERENCE_PROMPT.format(
        grant_title=grant.get("title") or grant.get("grant_name") or "Untitled",
        funder=grant.get("funder") or "Unknown",
        draft=draft_text[:30000],
    )

    try:
        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=2000, temperature=0.2)
        result = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        logger.error("Coherence review JSON parse failed: %s", e)
        result = {
            "coherence_score": 0,
            "narrative_consistent": True,
            "issues": [{"type": "error", "sections_involved": [], "description": f"Parse error: {e}", "fix": "Retry review"}],
            "overall_assessment": "Coherence review could not be completed.",
        }
    except Exception as e:
        logger.error("Coherence review LLM call failed: %s", e)
        result = {
            "coherence_score": 0,
            "narrative_consistent": True,
            "issues": [],
            "overall_assessment": f"Coherence review failed: {e}",
        }

    result.setdefault("coherence_score", 5.0)
    result.setdefault("issues", [])
    result.setdefault("overall_assessment", "Review completed.")
    return result


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

    # Load per-grant reviewer settings (stored by the frontend settings panel)
    grant_reviewer_cfg = (grant or {}).get("reviewer_settings") or {}

    # Load global reviewer config (existing behavior)
    reviewer_cfg = await agent_config().find_one({"agent": "reviewer"}) or {}

    # Merge: per-grant overrides global for funder/scientific settings
    funder_settings = {**reviewer_cfg.get("funder", {})}
    scientific_settings = {**reviewer_cfg.get("scientific", {})}

    # Apply per-grant overrides
    if grant_reviewer_cfg.get("funder_strictness"):
        funder_settings["strictness"] = grant_reviewer_cfg["funder_strictness"]
    if grant_reviewer_cfg.get("scientific_strictness"):
        scientific_settings["strictness"] = grant_reviewer_cfg["scientific_strictness"]
    if grant_reviewer_cfg.get("funder_focus_areas"):
        funder_settings["focus_areas"] = grant_reviewer_cfg["funder_focus_areas"]
    if grant_reviewer_cfg.get("scientific_focus_areas"):
        scientific_settings["focus_areas"] = grant_reviewer_cfg["scientific_focus_areas"]
    if grant_reviewer_cfg.get("custom_criteria"):
        funder_settings["custom_criteria"] = grant_reviewer_cfg["custom_criteria"]
        scientific_settings["custom_criteria"] = grant_reviewer_cfg["custom_criteria"]
    if grant_reviewer_cfg.get("custom_instructions"):
        funder_settings["custom_instructions"] = grant_reviewer_cfg["custom_instructions"]
        scientific_settings["custom_instructions"] = grant_reviewer_cfg["custom_instructions"]

    grant_title = grant.get("title") or grant.get("grant_name") or "Untitled"
    logger.info(
        "Starting dual review for '%s' (grant_id=%s, draft v%d, funder_strictness=%s, sci_strictness=%s)",
        grant_title, grant_id, draft_doc.get("version", 0),
        funder_settings.get("strictness", "balanced"),
        scientific_settings.get("strictness", "balanced"),
    )

    # Run all three perspectives in parallel: funder + scientific + coherence
    funder_result, scientific_result, coherence_result = await asyncio.gather(
        _run_single_review(grant, draft_text, "funder", funder_settings),
        _run_single_review(grant, draft_text, "scientific", scientific_settings),
        _run_coherence_review(grant, draft_text),
    )

    now = datetime.now(timezone.utc).isoformat()
    draft_id = str(draft_doc["_id"])
    draft_version = draft_doc.get("version", 0)

    # Store reviews (funder, scientific, coherence)
    for perspective, result in [
        ("funder", funder_result),
        ("scientific", scientific_result),
        ("coherence", coherence_result),
    ]:
        review_doc = {
            "grant_id": grant_id,
            "draft_id": draft_id,
            "draft_version": draft_version,
            "perspective": perspective,
            **result,
            "created_at": now,
        }
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": perspective},
            review_doc,
            upsert=True,
        )

    # Log coherence issues as critical if found
    coherence_issues = coherence_result.get("issues", [])
    if coherence_issues:
        logger.warning(
            "Coherence review found %d issues for '%s': %s",
            len(coherence_issues),
            grant_title,
            [i.get("type") for i in coherence_issues[:5]],
        )

    logger.info(
        "Triple review complete for '%s': funder=%.1f (%s), scientific=%.1f (%s), coherence=%.1f",
        grant_title,
        funder_result.get("overall_score", 0),
        funder_result.get("verdict", "?"),
        scientific_result.get("overall_score", 0),
        scientific_result.get("verdict", "?"),
        coherence_result.get("coherence_score", 0),
    )

    # Update heartbeat
    try:
        from backend.agents.agent_context import update_heartbeat
        await update_heartbeat("reviewer", {
            "status": "success",
            "grant_title": grant_title[:50],
            "funder_score": funder_result.get("overall_score", 0),
            "scientific_score": scientific_result.get("overall_score", 0),
            "coherence_score": coherence_result.get("coherence_score", 0),
            "funder_verdict": funder_result.get("verdict", ""),
            "scientific_verdict": scientific_result.get("verdict", ""),
            "coherence_issues": len(coherence_issues),
        })
    except Exception:
        logger.debug("Heartbeat update skipped (reviewer)", exc_info=True)

    return {
        "funder": funder_result,
        "scientific": scientific_result,
        "coherence": coherence_result,
    }
