"""Preference Learner — learns what the user wants from approve/revise/edit signals.

Every section interaction creates a preference pair:
  - AI version (what the drafter wrote)
  - Final version (what the human approved, possibly after editing)
  - Edit analysis (what changed and why)

Over time, builds a per-user preference profile that the drafter injects
into its prompt to produce better first drafts.

This is NOT reinforcement learning. It's preference-aware prompting:
the system learns from the human's edits and feeds patterns back as context.

Schema (draft_preferences collection):
{
    "grant_id": str,
    "section_name": str,
    "theme": str,
    "funder": str,
    "grant_type": str,
    "ai_version": str,           # what the AI wrote
    "final_version": str,        # what the human approved
    "was_edited": bool,          # did the human change anything?
    "was_revised": bool,         # was this a revise (not first draft)?
    "revision_instructions": str,
    "edit_analysis": {
        "edit_type": str,        # "approved_as_is", "minor_edit", "major_rewrite"
        "words_added": int,
        "words_removed": int,
        "changes": [str],        # LLM-extracted list of what changed
        "issues_detected": [str],# categorized: "too_generic", "wrong_tone", etc.
    },
    "user_id": str,
    "created_at": str,
}

Usage:
    # Record a preference pair (called on every section approve)
    await record_preference(grant_id, section, ai_version, final_version, ...)

    # Get user's learned preferences (called before writing each section)
    preferences = await get_user_preferences(user_id, theme, section_type)
"""
from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Edit Analysis ────────────────────────────────────────────────────────────

async def _analyze_edit(
    ai_version: str,
    final_version: str,
    section_name: str,
    revision_instructions: str = "",
) -> Dict:
    """Use LLM to analyze what the human changed and why.

    Returns structured edit analysis: edit_type, changes, issues_detected.
    """
    if ai_version.strip() == final_version.strip():
        return {
            "edit_type": "approved_as_is",
            "words_added": 0,
            "words_removed": 0,
            "changes": [],
            "issues_detected": [],
        }

    ai_words = set(ai_version.lower().split())
    final_words = set(final_version.lower().split())
    words_added = len(final_words - ai_words)
    words_removed = len(ai_words - final_words)

    # Classify edit magnitude
    ai_len = len(ai_version.split())
    final_len = len(final_version.split())
    change_ratio = (words_added + words_removed) / max(ai_len, 1)

    if change_ratio < 0.15:
        edit_type = "minor_edit"
    elif change_ratio < 0.5:
        edit_type = "major_edit"
    else:
        edit_type = "major_rewrite"

    # LLM analysis of what changed and why
    changes = []
    issues_detected = []

    try:
        from backend.utils.llm import chat, ANALYST_LIGHT

        prompt = f"""Compare these two versions of a grant application section and identify what the human changed.

SECTION: {section_name}
{f"REVISION INSTRUCTIONS: {revision_instructions}" if revision_instructions else ""}

AI VERSION:
{ai_version[:3000]}

HUMAN-APPROVED VERSION:
{final_version[:3000]}

Analyze the differences. Respond ONLY with valid JSON:
{{
  "changes": [
    "<specific change 1: e.g. 'Replaced generic claim with specific data point: 47 field sites'>",
    "<specific change 2: e.g. 'Removed adjective: innovative'>",
    "<specific change 3>"
  ],
  "issues_detected": [
    "<category>: <description>"
  ]
}}

For issues_detected, use these categories:
- "too_generic": claims lacked specific numbers or evidence
- "empty_adjectives": used banned words (innovative, cutting-edge, etc.)
- "wrong_tone": too formal/informal, too marketing-heavy, etc.
- "missing_evidence": paragraph had no data, citation, or figure reference
- "wrong_structure": didn't follow Finding→Evidence→Implication→Justification
- "too_verbose": paragraphs too long, filler transitions
- "missing_section_element": expected element absent (e.g., no National Status)
- "hedging": used "aim to", "could", "may" instead of "will"
- "not_only_but_also": used the "not only X but also Y" construction
- "off_topic": content didn't address the section's purpose or evaluation criteria"""

        raw = await chat(prompt, model=ANALYST_LIGHT, max_tokens=1000, temperature=0.1)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        changes = result.get("changes", [])
        issues_detected = result.get("issues_detected", [])

    except Exception as e:
        logger.warning("Edit analysis LLM call failed: %s", e)
        # Fallback: basic heuristic analysis
        if words_added > words_removed * 2:
            issues_detected.append("too_generic: human added substantial content")
        if words_removed > words_added * 2:
            issues_detected.append("too_verbose: human removed substantial content")

    return {
        "edit_type": edit_type,
        "words_added": words_added,
        "words_removed": words_removed,
        "changes": changes[:10],
        "issues_detected": issues_detected[:10],
    }


# ── Record Preference Pair ───────────────────────────────────────────────────

async def record_preference(
    grant_id: str,
    section_name: str,
    ai_version: str,
    final_version: str,
    was_revised: bool = False,
    revision_instructions: str = "",
    theme: str = "",
    funder: str = "",
    grant_type: str = "",
    user_id: str = "default",
) -> Dict:
    """Record a preference pair from a section approve/revise decision.

    Called every time a section is approved (with or without edits).
    This is the core data collection for preference learning.
    """
    from backend.db.mongo import draft_preferences

    was_edited = ai_version.strip() != final_version.strip()

    # Analyze the edit
    edit_analysis = await _analyze_edit(
        ai_version, final_version, section_name, revision_instructions,
    )

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "grant_id": grant_id,
        "section_name": section_name,
        "theme": theme,
        "funder": funder,
        "grant_type": grant_type,
        "ai_version": ai_version,
        "final_version": final_version,
        "was_edited": was_edited,
        "was_revised": was_revised,
        "revision_instructions": revision_instructions,
        "edit_analysis": edit_analysis,
        "user_id": user_id,
        "created_at": now,
    }

    await draft_preferences().insert_one(doc)

    logger.info(
        "Preference recorded: section='%s' edited=%s type=%s issues=%s",
        section_name, was_edited, edit_analysis["edit_type"],
        edit_analysis["issues_detected"][:3],
    )

    return doc


# ── Build User Preference Profile ────────────────────────────────────────────

async def get_user_preferences(
    user_id: str = "default",
    theme: str = "",
    section_name: str = "",
    limit: int = 30,
) -> str:
    """Build a preference profile from past interactions.

    Returns a formatted string ready to inject into the drafter prompt.
    Learns from: edit patterns, revision instructions, issue frequencies.

    Priority: same section + theme > same section > same theme > any.
    """
    from backend.db.mongo import draft_preferences

    # Fetch recent preference pairs for this user
    query = {"user_id": user_id}
    docs = await draft_preferences().find(query).sort(
        "created_at", -1
    ).to_list(limit)

    if not docs:
        return ""

    # ── Aggregate patterns ───────────────────────────────────────────────
    total = len(docs)
    edited_count = sum(1 for d in docs if d.get("was_edited"))
    revised_count = sum(1 for d in docs if d.get("was_revised"))

    # Count issue frequencies
    issue_counts: Dict[str, int] = {}
    all_changes: List[str] = []
    section_revision_rates: Dict[str, Dict] = {}

    for doc in docs:
        analysis = doc.get("edit_analysis", {})

        # Count issues
        for issue in analysis.get("issues_detected", []):
            category = issue.split(":")[0].strip()
            issue_counts[category] = issue_counts.get(category, 0) + 1

        # Collect changes
        all_changes.extend(analysis.get("changes", []))

        # Track per-section revision rates
        sec = doc.get("section_name", "")
        if sec:
            if sec not in section_revision_rates:
                section_revision_rates[sec] = {"total": 0, "edited": 0, "revised": 0}
            section_revision_rates[sec]["total"] += 1
            if doc.get("was_edited"):
                section_revision_rates[sec]["edited"] += 1
            if doc.get("was_revised"):
                section_revision_rates[sec]["revised"] += 1

    # Find top issues (sorted by frequency)
    top_issues = sorted(issue_counts.items(), key=lambda x: -x[1])[:8]

    # Find sections with highest edit rates
    problem_sections = [
        (sec, data["edited"] / max(data["total"], 1))
        for sec, data in section_revision_rates.items()
        if data["total"] >= 2
    ]
    problem_sections.sort(key=lambda x: -x[1])

    # ── Collect revision instructions (gold signal) ──────────────────────
    revision_themes: List[str] = []
    for doc in docs:
        instr = doc.get("revision_instructions", "")
        if instr:
            revision_themes.append(instr[:200])

    # ── Format as prompt injection ───────────────────────────────────────
    if not top_issues and not problem_sections and edited_count == 0:
        return ""

    parts = ["USER PREFERENCES (learned from your past editing patterns — follow these):"]

    # Overall stats
    edit_rate = round(edited_count / max(total, 1) * 100)
    parts.append(f"Based on {total} past section reviews: you edited {edit_rate}% of drafts.")

    # Top issues to avoid
    if top_issues:
        parts.append("\nISSUES YOU FREQUENTLY CORRECT (avoid these):")
        for issue, count in top_issues:
            pct = round(count / max(total, 1) * 100)
            parts.append(f"  - {issue} (found in {pct}% of drafts)")

    # Problem sections
    if problem_sections:
        parts.append("\nSECTIONS YOU EDIT MOST OFTEN (be extra careful here):")
        for sec, rate in problem_sections[:5]:
            parts.append(f"  - {sec}: edited {round(rate*100)}% of the time")

    # Recent revision instructions (the most direct signal)
    if revision_themes:
        parts.append("\nYOUR RECENT REVISION REQUESTS (what you explicitly asked for):")
        for instr in revision_themes[:5]:
            parts.append(f"  - \"{instr}\"")

    # Recent specific changes (what you actually do to drafts)
    if all_changes:
        parts.append("\nCHANGES YOU COMMONLY MAKE (replicate these proactively):")
        # Deduplicate similar changes
        seen = set()
        for change in all_changes[:10]:
            short = change[:100].lower()
            if short not in seen:
                parts.append(f"  - {change[:150]}")
                seen.add(short)

    # Section-specific preferences for the current section
    if section_name:
        section_docs = [d for d in docs if d.get("section_name", "").lower() == section_name.lower()]
        if section_docs:
            sec_issues = []
            for d in section_docs:
                sec_issues.extend(d.get("edit_analysis", {}).get("issues_detected", []))
            if sec_issues:
                parts.append(f"\nFOR THIS SECTION ({section_name}) specifically:")
                for issue in sec_issues[:5]:
                    parts.append(f"  - {issue}")

    return "\n".join(parts)


# ── Get Approved Examples for Few-Shot ────────────────────────────────────────

async def get_approved_examples(
    section_name: str = "",
    theme: str = "",
    user_id: str = "default",
    limit: int = 2,
) -> str:
    """Get the user's own approved sections as few-shot examples.

    These are better than generic golden examples because they reflect
    this specific user's preferences and editing style.
    """
    from backend.db.mongo import draft_preferences

    query: Dict = {"user_id": user_id, "was_edited": False}  # approved as-is = best signal
    if section_name:
        query["section_name"] = {"$regex": section_name, "$options": "i"}
    if theme:
        query["theme"] = theme

    docs = await draft_preferences().find(query).sort(
        "created_at", -1
    ).to_list(limit)

    # If not enough approved-as-is, include minor edits
    if len(docs) < limit:
        query_edited = {"user_id": user_id, "edit_analysis.edit_type": "minor_edit"}
        if section_name:
            query_edited["section_name"] = {"$regex": section_name, "$options": "i"}
        if theme:
            query_edited["theme"] = theme

        more = await draft_preferences().find(query_edited).sort(
            "created_at", -1
        ).to_list(limit - len(docs))
        docs.extend(more)

    if not docs:
        return ""

    parts = ["YOUR PREVIOUSLY APPROVED SECTIONS (match this quality and style):"]
    for i, doc in enumerate(docs, 1):
        # Use the final version (what the user actually wanted)
        version = doc.get("final_version", doc.get("ai_version", ""))
        sec = doc.get("section_name", "Section")
        funder = doc.get("funder", "")
        parts.append(f"\n--- Approved Example {i}: {sec} (for {funder}) ---")
        parts.append(version[:1500])

    return "\n".join(parts)
