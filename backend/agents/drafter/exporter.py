"""Exporter — assembles approved sections into a clean Markdown file.

Output:
- Clean Markdown with header (grant title, funder, deadline, version, date)
- Sections in order with word count annotations
- Internal evidence gaps summary (remove before submission)
- Submission checklist
- Saved to /tmp/drafts/{filename}.md
- Saved to MongoDB grant_drafts collection (versioned)
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.db.mongo import grant_drafts, grants_pipeline, grants_scored
from backend.integrations.notion_data import (
    get_grant_by_page_id as _notion_get_grant,
    update_grant_status as _notion_update_status,
)
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)


def _safe_filename(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s]+", "_", text.strip())
    return text[:60]


def _assemble_markdown(
    grant: Dict,
    requirements: Dict,
    approved_sections: Dict[str, Dict],
    version: int,
) -> str:
    title = grant.get("title", "Grant Application")
    funder = grant.get("funder", "Unknown Funder")
    deadline = requirements.get("submission", {}).get("deadline") or grant.get("deadline", "TBD")
    max_funding = grant.get("max_funding") or requirements.get("budget", {}).get("max")
    funding_str = f"${max_funding:,}" if max_funding else "Not specified"

    lines = [
        f"# {title}",
        f"**Funder:** {funder}  ",
        f"**Deadline:** {deadline}  ",
        f"**Funding:** {funding_str}  ",
        f"**Draft Version:** v{version}  ",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        "",
        "---",
        "",
    ]

    sections = requirements.get("sections_required", [])
    section_order = [s.get("name") for s in sections]

    all_evidence_gaps = []
    total_words = 0

    for section_name in section_order:
        sec = approved_sections.get(section_name)
        if not sec:
            continue
        content = sec.get("content", "")
        word_count = sec.get("word_count", len(content.split()))
        word_limit = sec.get("word_limit", 500)
        within = sec.get("within_limit", True)
        status = "✓" if within else f"⚠ OVER LIMIT ({word_count}/{word_limit})"

        lines.append(f"## {section_name}")
        lines.append(f"*{word_count} words / {word_limit} limit {status}*")
        lines.append("")
        lines.append(content)
        lines.append("")
        lines.append("---")
        lines.append("")

        gaps = re.findall(r"\[EVIDENCE NEEDED:[^\]]+\]", content)
        all_evidence_gaps.extend(gaps)
        total_words += word_count

    # Internal section — evidence gaps
    if all_evidence_gaps:
        lines.append("## ⚠ INTERNAL: Evidence Gaps (Remove Before Submission)")
        lines.append("*The following information was not available in the Company Brain.*")
        lines.append("*You must fill these in before submitting.*")
        lines.append("")
        for gap in all_evidence_gaps:
            lines.append(f"- {gap}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Submission checklist
    eligibility = requirements.get("eligibility_checklist", [])
    if eligibility:
        lines.append("## ⚠ INTERNAL: Submission Checklist (Remove Before Submission)")
        for item in eligibility:
            lines.append(f"- [ ] {item.get('requirement', '')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(f"*Total word count: {total_words}*")

    return "\n".join(lines)


async def exporter_node(state: GrantState) -> Dict:
    """LangGraph node: assemble and save the complete draft."""
    # Notion-first, MongoDB fallback
    grant = {}
    notion_page_id = state.get("selected_notion_page_id")
    if notion_page_id:
        try:
            grant = await _notion_get_grant(notion_page_id) or {}
        except Exception:
            pass

    if not grant:
        grant_id = state.get("selected_grant_id")
        if grant_id:
            try:
                from bson import ObjectId
                grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
            except Exception:
                pass

    requirements = state.get("grant_requirements") or {}
    approved_sections = state.get("approved_sections") or {}
    version = (state.get("draft_version") or 0) + 1

    markdown = _assemble_markdown(grant, requirements, approved_sections, version)

    # Save to /tmp/drafts/
    title_slug = _safe_filename(grant.get("title", "grant"))
    filename = f"{title_slug}_v{version}.md"
    filepath = f"/tmp/drafts/{filename}"
    os.makedirs("/tmp/drafts", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(markdown)
    logger.info("Exporter: saved draft to %s", filepath)

    # Save to MongoDB
    pipeline_id = state.get("pipeline_id")
    draft_record = {
        "pipeline_id": pipeline_id,
        "grant_id": str(grant.get("_id", "")),
        "version": version,
        "sections": {
            name: {
                "content": sec.get("content", ""),
                "word_count": sec.get("word_count", 0),
                "word_limit": sec.get("word_limit", 500),
                "within_limit": sec.get("within_limit", True),
            }
            for name, sec in approved_sections.items()
        },
        "evidence_gaps_all": [
            gap
            for sec in approved_sections.values()
            for gap in re.findall(r"\[EVIDENCE NEEDED:[^\]]+\]", sec.get("content", ""))
        ],
        "total_word_count": sum(s.get("word_count", 0) for s in approved_sections.values()),
        "draft_filename": filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await grant_drafts().insert_one(draft_record)

    # Update pipeline status — Notion first, MongoDB second
    if notion_page_id:
        try:
            await _notion_update_status(notion_page_id, "draft_complete")
        except Exception:
            logger.debug("Notion status update failed for exporter", exc_info=True)
    if pipeline_id:
        try:
            from bson import ObjectId
            await grants_pipeline().update_one(
                {"_id": ObjectId(pipeline_id)},
                {"$set": {"status": "draft_complete", "current_draft_version": version}},
            )
        except Exception:
            logger.debug("MongoDB pipeline update failed for exporter", exc_info=True)

    audit_entry = {
        "node": "exporter",
        "ts": datetime.now(timezone.utc).isoformat(),
        "filename": filename,
        "version": version,
        "total_words": draft_record["total_word_count"],
    }
    return {
        "draft_version": version,
        "draft_filepath": filepath,
        "draft_filename": filename,
        "markdown_content": markdown,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
