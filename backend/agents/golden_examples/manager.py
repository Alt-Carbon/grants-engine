"""Golden Examples Manager — curates the best agent outputs as few-shot examples.

Two modes of operation:
1. **Manual curation**: User marks an output as "golden" via API
2. **Auto-curation**: System auto-promotes outputs that score above threshold

Golden examples are injected into agent prompts as few-shot demonstrations.
Each agent type has its own collection of examples.

Schema (golden_examples collection):
{
    "agent": "drafter" | "analyst" | "scout" | "reviewer",
    "type": "section" | "scoring" | "review",
    "theme": str,                    # Theme key (climatetech, agritech, etc.)
    "grant_title": str,
    "funder": str,
    "quality_score": float,          # Combined reviewer + outcome score
    "input": {                       # What the agent received
        "grant_context": str,
        "section_name": str,         # For drafter
        "section_description": str,
    },
    "output": str,                   # The golden output
    "why_golden": str,               # Why this is a good example
    "source": "manual" | "auto",     # How it was added
    "created_at": str,
    "created_by": str,               # User email for manual
}

Usage:
    # Save a golden example
    await save_golden("drafter", section_data)

    # Retrieve examples for prompt injection
    examples = await get_golden_examples("drafter", theme="climatetech", limit=3)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AUTO_PROMOTE_THRESHOLD = 8.0  # Reviewer score above this → auto-golden


async def save_golden(
    agent: str,
    example_type: str,
    input_data: Dict,
    output: str,
    quality_score: float,
    theme: str = "",
    grant_title: str = "",
    funder: str = "",
    why_golden: str = "",
    source: str = "manual",
    created_by: str = "system",
) -> Dict:
    """Save a golden example for an agent."""
    from backend.db.mongo import golden_examples

    doc = {
        "agent": agent,
        "type": example_type,
        "theme": theme,
        "grant_title": grant_title,
        "funder": funder,
        "quality_score": quality_score,
        "input": input_data,
        "output": output,
        "why_golden": why_golden,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }

    result = await golden_examples().insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    logger.info(
        "Golden example saved: agent=%s type=%s theme=%s score=%.1f",
        agent, example_type, theme, quality_score,
    )
    return doc


async def get_golden_examples(
    agent: str,
    theme: str = "",
    example_type: str = "",
    limit: int = 3,
) -> List[Dict]:
    """Retrieve the best golden examples for an agent, optionally filtered by theme.

    Returns up to `limit` examples, sorted by quality_score descending.
    Prioritizes: same theme > any theme.
    """
    from backend.db.mongo import golden_examples

    results = []

    # First: try same-theme examples
    if theme:
        query = {"agent": agent, "theme": theme}
        if example_type:
            query["type"] = example_type
        docs = await golden_examples().find(query).sort("quality_score", -1).limit(limit).to_list(limit)
        results.extend(docs)

    # Fill remaining slots with any-theme examples
    if len(results) < limit:
        existing_ids = [d["_id"] for d in results]
        query = {"agent": agent, "_id": {"$nin": existing_ids}}
        if example_type:
            query["type"] = example_type
        remaining = limit - len(results)
        docs = await golden_examples().find(query).sort("quality_score", -1).limit(remaining).to_list(remaining)
        results.extend(docs)

    return results


def format_drafter_examples(examples: List[Dict]) -> str:
    """Format golden drafter examples for prompt injection."""
    if not examples:
        return ""

    parts = ["GOLDEN EXAMPLES (these are our best past sections — match this quality):"]
    for i, ex in enumerate(examples, 1):
        inp = ex.get("input", {})
        parts.append(
            f"\n--- Example {i}: {inp.get('section_name', 'Section')} "
            f"(for {ex.get('funder', 'unknown funder')}, score: {ex.get('quality_score', 0):.1f}/10) ---"
        )
        if inp.get("section_description"):
            parts.append(f"Section requirement: {inp['section_description']}")
        parts.append(f"\n{ex.get('output', '')}")

    return "\n".join(parts)


def format_analyst_examples(examples: List[Dict]) -> str:
    """Format golden analyst examples for scoring calibration."""
    if not examples:
        return ""

    parts = ["CALIBRATION EXAMPLES (these scores were confirmed by real outcomes):"]
    for ex in examples:
        inp = ex.get("input", {})
        parts.append(
            f"\n- {ex.get('grant_title', 'Grant')} ({ex.get('funder', '')}): "
            f"score={ex.get('quality_score', 0):.1f} → "
            f"outcome: {inp.get('actual_outcome', 'unknown')}"
        )
        if ex.get("why_golden"):
            parts.append(f"  Note: {ex['why_golden']}")

    return "\n".join(parts)


async def auto_promote_from_reviews() -> int:
    """Scan recent reviews and auto-promote high-scoring sections as golden examples.

    Called periodically or after reviews complete. Returns count of new golden examples.
    """
    from backend.db.mongo import draft_reviews, grant_drafts, grants_scored, golden_examples
    from bson import ObjectId

    # Find reviews with high overall scores
    high_reviews = await draft_reviews().find(
        {"overall_score": {"$gte": AUTO_PROMOTE_THRESHOLD}}
    ).sort("created_at", -1).limit(20).to_list(20)

    promoted = 0
    for review in high_reviews:
        grant_id = review.get("grant_id", "")
        perspective = review.get("perspective", "")

        # Check if we already have a golden example for this grant
        existing = await golden_examples().find_one({
            "agent": "drafter",
            "input.grant_id": grant_id,
        })
        if existing:
            continue

        # Load grant + draft
        grant = {}
        if grant_id:
            try:
                grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
            except Exception:
                pass

        draft = await grant_drafts().find_one(
            {"grant_id": grant_id},
            sort=[("version", -1)],
        )
        if not draft:
            continue

        # Get the highest-scoring sections from the review
        section_reviews = review.get("section_reviews", {})
        for sec_name, sec_review in section_reviews.items():
            if not isinstance(sec_review, dict):
                continue
            sec_score = sec_review.get("score", 0)
            if sec_score < AUTO_PROMOTE_THRESHOLD:
                continue

            # Get the actual section content from the draft
            sections = draft.get("sections", {})
            sec_data = sections.get(sec_name, {})
            content = sec_data.get("content", "")
            if not content or len(content) < 100:
                continue

            themes = grant.get("themes_detected", [])
            theme = themes[0] if themes else ""

            await save_golden(
                agent="drafter",
                example_type="section",
                input_data={
                    "grant_id": grant_id,
                    "section_name": sec_name,
                    "section_description": "",
                    "grant_context": f"Grant: {grant.get('title', '')} | Funder: {grant.get('funder', '')}",
                },
                output=content,
                quality_score=sec_score,
                theme=theme,
                grant_title=grant.get("title") or grant.get("grant_name") or "",
                funder=grant.get("funder", ""),
                why_golden=f"Auto-promoted: {perspective} reviewer scored {sec_score}/10. "
                           f"Strengths: {', '.join(sec_review.get('strengths', [])[:2])}",
                source="auto",
            )
            promoted += 1

    if promoted:
        logger.info("Auto-promoted %d golden examples from reviews", promoted)
    return promoted
