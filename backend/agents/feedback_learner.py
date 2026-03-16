"""Feedback Learner — stores grant outcomes and retrieves lessons for future drafts.

When a grant is won or rejected, the outcome + funder feedback is stored.
Before writing future drafts, the learner retrieves relevant past outcomes
for the same funder, theme, or grant type — so the drafter can learn from
real-world results.

Schema (grant_outcomes collection):
{
    "grant_id": str,
    "grant_title": str,
    "funder": str,
    "themes": [str],
    "grant_type": str,
    "outcome": "won" | "rejected" | "shortlisted" | "withdrawn",
    "feedback": str,               # Funder's rejection/acceptance feedback
    "section_feedback": {           # Per-section lessons
        "<section_name>": {
            "was_weak": bool,
            "feedback": str,        # What the funder said about this section
            "lesson": str,          # Extracted lesson for future drafts
        }
    },
    "lessons_learned": [str],       # High-level takeaways
    "what_worked": [str],           # What the funder liked
    "what_failed": [str],           # What caused rejection
    "draft_settings": {             # Settings used when drafting (for correlation)
        "writing_style": str,
        "theme": str,
        "temperature": float,
    },
    "weighted_score": float,        # Analyst score at time of submission
    "reviewer_scores": {            # Internal reviewer scores
        "funder": float,
        "scientific": float,
    },
    "created_at": str,
    "updated_at": str,
}

Usage:
    # Record an outcome
    await record_outcome("grant_id", "rejected", "MRV section was too vague...")

    # Get lessons before drafting
    lessons = await get_lessons_for_grant(funder="Frontier", themes=["climatetech"])
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


async def record_outcome(
    grant_id: str,
    outcome: str,
    feedback: str = "",
    section_feedback: Optional[Dict[str, Dict]] = None,
    lessons_learned: Optional[List[str]] = None,
    what_worked: Optional[List[str]] = None,
    what_failed: Optional[List[str]] = None,
) -> Dict:
    """Record the real-world outcome of a grant application.

    Call this when you learn whether a submitted grant was won/rejected.
    The system uses this data to improve future drafts.
    """
    from backend.db.mongo import grant_outcomes, grants_scored, draft_reviews, agent_config
    from bson import ObjectId

    # Load grant metadata
    grant = await grants_scored().find_one({"_id": ObjectId(grant_id)})
    if not grant:
        raise ValueError(f"Grant {grant_id} not found")

    # Load internal reviewer scores
    reviewer_scores = {}
    reviews = await draft_reviews().find({"grant_id": grant_id}).to_list(5)
    for r in reviews:
        perspective = r.get("perspective")
        if perspective:
            reviewer_scores[perspective] = r.get("overall_score", 0)

    # Load drafter settings at time of recording
    drafter_cfg = await agent_config().find_one({"agent": "drafter"}) or {}
    themes = grant.get("themes_detected", [])

    # If feedback provided but no explicit lessons, extract them with LLM
    extracted_lessons = lessons_learned or []
    extracted_worked = what_worked or []
    extracted_failed = what_failed or []

    if feedback and not lessons_learned:
        try:
            extracted = await _extract_lessons(
                grant_title=grant.get("title") or grant.get("grant_name") or "",
                funder=grant.get("funder") or "",
                outcome=outcome,
                feedback=feedback,
            )
            extracted_lessons = extracted.get("lessons_learned", [])
            extracted_worked = extracted.get("what_worked", [])
            extracted_failed = extracted.get("what_failed", [])
            if not section_feedback:
                section_feedback = extracted.get("section_feedback", {})
        except Exception as e:
            logger.warning("Lesson extraction failed: %s", e)

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "grant_id": grant_id,
        "grant_title": grant.get("title") or grant.get("grant_name") or "",
        "funder": grant.get("funder") or "",
        "themes": themes,
        "grant_type": grant.get("grant_type") or "",
        "outcome": outcome,
        "feedback": feedback,
        "section_feedback": section_feedback or {},
        "lessons_learned": extracted_lessons,
        "what_worked": extracted_worked,
        "what_failed": extracted_failed,
        "draft_settings": {
            "writing_style": drafter_cfg.get("writing_style", "professional"),
            "theme": themes[0] if themes else "",
            "temperature": drafter_cfg.get("temperature", 0.4),
        },
        "weighted_score": grant.get("weighted_total", 0),
        "reviewer_scores": reviewer_scores,
        "created_at": now,
        "updated_at": now,
    }

    await grant_outcomes().replace_one(
        {"grant_id": grant_id},
        doc,
        upsert=True,
    )

    logger.info(
        "Recorded outcome for '%s': %s (lessons=%d, worked=%d, failed=%d)",
        doc["grant_title"], outcome,
        len(extracted_lessons), len(extracted_worked), len(extracted_failed),
    )

    return doc


async def _extract_lessons(
    grant_title: str,
    funder: str,
    outcome: str,
    feedback: str,
) -> Dict:
    """Use LLM to extract structured lessons from funder feedback."""
    from backend.utils.llm import chat, ANALYST_HEAVY
    import json

    prompt = f"""Analyze this grant application outcome and extract structured lessons.

GRANT: {grant_title}
FUNDER: {funder}
OUTCOME: {outcome}
FUNDER FEEDBACK:
{feedback}

Extract lessons that would help improve future grant applications to this funder.

Respond ONLY with valid JSON:
{{
  "lessons_learned": ["<actionable lesson 1>", "<lesson 2>", ...],
  "what_worked": ["<what the funder liked>", ...],
  "what_failed": ["<what caused rejection/weakness>", ...],
  "section_feedback": {{
    "<section_name>": {{
      "was_weak": true/false,
      "feedback": "<what funder said about this section>",
      "lesson": "<what to do differently next time>"
    }}
  }}
}}"""

    raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=1500, temperature=0.2)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


async def get_lessons_for_grant(
    funder: str = "",
    themes: Optional[List[str]] = None,
    grant_type: str = "",
    limit: int = 5,
) -> str:
    """Retrieve relevant past outcomes for a funder/theme combination.

    Returns a formatted string ready to inject into the drafter prompt.
    Prioritizes: same funder > same theme > same grant type.
    """
    from backend.db.mongo import grant_outcomes

    results = []

    # 1. Same funder (most valuable — funder-specific preferences)
    if funder:
        docs = await grant_outcomes().find(
            {"funder": {"$regex": funder, "$options": "i"}}
        ).sort("created_at", -1).to_list(limit)
        results.extend(docs)

    # 2. Same themes (if we don't have enough funder-specific data)
    if len(results) < limit and themes:
        theme_docs = await grant_outcomes().find(
            {"themes": {"$in": themes}, "grant_id": {"$nin": [r["grant_id"] for r in results]}}
        ).sort("created_at", -1).to_list(limit - len(results))
        results.extend(theme_docs)

    if not results:
        return ""

    # Format as context for the drafter
    parts = []
    for doc in results:
        outcome = doc.get("outcome", "unknown")
        title = doc.get("grant_title", "Unknown")
        funder_name = doc.get("funder", "Unknown")

        lines = [f"### {title} ({funder_name}) — {outcome.upper()}"]

        if doc.get("what_failed"):
            lines.append("**What failed:**")
            for f in doc["what_failed"]:
                lines.append(f"  - {f}")

        if doc.get("what_worked"):
            lines.append("**What worked:**")
            for w in doc["what_worked"]:
                lines.append(f"  - {w}")

        if doc.get("lessons_learned"):
            lines.append("**Lessons:**")
            for l in doc["lessons_learned"]:
                lines.append(f"  - {l}")

        # Section-level feedback
        sec_fb = doc.get("section_feedback", {})
        weak_sections = {k: v for k, v in sec_fb.items() if v.get("was_weak")}
        if weak_sections:
            lines.append("**Weak sections:**")
            for sec_name, sec_data in weak_sections.items():
                lines.append(f"  - {sec_name}: {sec_data.get('lesson', sec_data.get('feedback', ''))}")

        parts.append("\n".join(lines))

    header = f"PAST GRANT OUTCOMES (learn from these — avoid repeating mistakes):\n"
    return header + "\n\n".join(parts)


async def get_funder_insights(funder: str) -> Dict:
    """Get aggregated insights for a specific funder based on past outcomes.

    Returns stats + patterns: what this funder values, common rejection reasons.
    """
    from backend.db.mongo import grant_outcomes

    docs = await grant_outcomes().find(
        {"funder": {"$regex": funder, "$options": "i"}}
    ).to_list(50)

    if not docs:
        return {"funder": funder, "total_applications": 0}

    total = len(docs)
    won = sum(1 for d in docs if d.get("outcome") == "won")
    rejected = sum(1 for d in docs if d.get("outcome") == "rejected")

    # Aggregate lessons
    all_failed = []
    all_worked = []
    all_lessons = []
    for d in docs:
        all_failed.extend(d.get("what_failed", []))
        all_worked.extend(d.get("what_worked", []))
        all_lessons.extend(d.get("lessons_learned", []))

    return {
        "funder": funder,
        "total_applications": total,
        "won": won,
        "rejected": rejected,
        "win_rate": round(won / total * 100, 1) if total else 0,
        "common_failures": all_failed[:10],
        "what_works": all_worked[:10],
        "key_lessons": all_lessons[:10],
    }
