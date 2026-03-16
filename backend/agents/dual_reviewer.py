"""Dual-Perspective Reviewer — Funder + Scientific review of completed drafts.

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
from typing import Dict, Optional

from backend.utils.llm import chat, ANALYST_HEAVY

logger = logging.getLogger(__name__)

# ── Prompts ─────────────────────────────────────────────────────────────────

FUNDER_PROMPT = """You are a senior grant program officer evaluating a grant application.
You represent the funder and must decide whether this application deserves funding.

GRANT: {grant_title}
FUNDER: {funder}
FUNDING AMOUNT: {funding}
DEADLINE: {deadline}

EVALUATION CRITERIA (from the funder):
{criteria}

COMPLETE DRAFT APPLICATION:
{draft}

Review this application AS A FUNDER. Be rigorous and specific. Consider:
1. Does the proposal clearly address the funder's stated priorities?
2. Are the objectives measurable and achievable within the timeline?
3. Is the budget justified and reasonable for the proposed work?
4. How competitive is this vs. typical winning applications?
5. Are impact claims backed by evidence or just aspirational?
6. Does it follow submission requirements (word limits, sections)?
7. Is the team credible for this scope of work?

Respond ONLY with valid JSON:
{{
  "overall_score": <float 1-10>,
  "section_reviews": {{
    "<section_name>": {{
      "score": <int 1-10>,
      "strengths": ["<specific strength from funder view>"],
      "issues": ["<specific issue a funder would flag>"],
      "suggestions": ["<actionable fix to improve competitiveness>"]
    }}
  }},
  "top_issues": ["<most critical issue 1>", "<issue 2>", "<issue 3>"],
  "strengths": ["<key strength 1>", "<strength 2>", "<strength 3>"],
  "verdict": "<one of: strong_submit | submit_with_revisions | major_revisions | reconsider>",
  "summary": "<2-3 sentence funder assessment — would you fund this? why or why not?>"
}}"""

SCIENTIFIC_PROMPT = """You are a peer reviewer and domain scientist evaluating a grant application
for scientific and technical rigor.

GRANT: {grant_title}
FUNDER: {funder}
THEMES: {themes}

COMPLETE DRAFT APPLICATION:
{draft}

Review this application AS A SCIENTIST. Be thorough and technical. Evaluate:
1. Is the methodology scientifically sound and well-described?
2. Are MRV (Measurement, Reporting, Verification) approaches rigorous?
3. Are data quality claims and baselines credible?
4. Is the scalability pathway realistic given the evidence?
5. Does it demonstrate scientific novelty or just incremental work?
6. Are uncertainties and limitations honestly acknowledged?
7. Are claims properly supported by data, citations, or preliminary results?
8. Is the technical approach appropriate for the stated objectives?

Respond ONLY with valid JSON:
{{
  "overall_score": <float 1-10>,
  "section_reviews": {{
    "<section_name>": {{
      "score": <int 1-10>,
      "strengths": ["<specific technical strength>"],
      "issues": ["<scientific concern or gap>"],
      "suggestions": ["<specific technical improvement>"]
    }}
  }},
  "top_issues": ["<most critical scientific issue 1>", "<issue 2>", "<issue 3>"],
  "strengths": ["<key technical strength 1>", "<strength 2>", "<strength 3>"],
  "verdict": "<one of: strong_submit | submit_with_revisions | major_revisions | reconsider>",
  "summary": "<2-3 sentence scientific assessment — is the science solid? what's missing?>"
}}"""


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
    prompt_template: str,
) -> Dict:
    """Run a single review perspective and return structured result."""
    # Build context
    criteria = ""
    deep = grant.get("deep_analysis") or {}
    eval_criteria = deep.get("evaluation_criteria") or grant.get("evaluation_criteria") or []
    if eval_criteria:
        criteria = "\n".join(
            f"- {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))} "
            f"({c.get('weight', 'unweighted')})"
            for c in eval_criteria
        )
    else:
        criteria = "No explicit criteria provided — evaluate based on standard grant review practices."

    themes = ", ".join(grant.get("themes_detected", [])) or "Not specified"
    funding = grant.get("max_funding_usd") or grant.get("max_funding") or grant.get("amount") or "Not specified"
    if isinstance(funding, (int, float)):
        funding = f"${funding:,.0f}"

    prompt = prompt_template.format(
        grant_title=grant.get("title") or grant.get("grant_name") or "Untitled",
        funder=grant.get("funder") or "Unknown",
        funding=funding,
        deadline=grant.get("deadline") or "Not specified",
        themes=themes,
        criteria=criteria,
        draft=draft_text[:30000],
    )

    try:
        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=3000)
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

    Returns {"funder": {...}, "scientific": {...}} with full review data.
    Stores both reviews in the draft_reviews collection.
    """
    from backend.db.mongo import grant_drafts, grants_scored, draft_reviews
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

    grant_title = grant.get("title") or grant.get("grant_name") or "Untitled"
    logger.info(
        "Starting dual review for '%s' (grant_id=%s, draft v%d)",
        grant_title, grant_id, draft_doc.get("version", 0),
    )

    # Run both perspectives in parallel
    funder_result, scientific_result = await asyncio.gather(
        _run_single_review(grant, draft_text, "funder", FUNDER_PROMPT),
        _run_single_review(grant, draft_text, "scientific", SCIENTIFIC_PROMPT),
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

    return {"funder": funder_result, "scientific": scientific_result}
