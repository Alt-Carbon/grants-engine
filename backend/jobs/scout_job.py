"""Scout cron job — triggered by APScheduler every 48h.

Uses the Discovery Graph (Graph A): scout → company_brain_load → analyst → pre_triage_guardrail → notify_triage → END.
Runs fully autonomously — no interrupts. Output goes to Notion Grant Pipeline.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from backend.graph.graph import get_discovery_graph
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)


async def run_scout_pipeline() -> dict:
    """Run Discovery Pipeline: Scout → Analyst → END (autonomous, no interrupts)."""
    thread_id = f"scout_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
    run_id = str(uuid.uuid4())

    initial_state: GrantState = {
        "raw_grants": [],
        "scored_grants": [],
        "notion_page_ids": {},
        "selected_notion_page_id": None,
        "human_triage_decision": None,
        "selected_grant_id": None,
        "triage_notes": None,
        "grant_requirements": None,
        "grant_raw_doc": None,
        "company_profile": None,
        "company_context": None,
        "style_examples": None,
        "style_examples_loaded": False,
        "draft_guardrail_result": None,
        "override_guardrails": False,
        "grant_theme": None,
        "draft_outline": None,
        "current_section_index": 0,
        "approved_sections": {},
        "section_critiques": {},
        "section_revision_instructions": {},
        "pending_interrupt": None,
        "section_review_decision": None,
        "section_edited_content": None,
        "reviewer_output": None,
        "draft_version": 0,
        "draft_filepath": None,
        "draft_filename": None,
        "markdown_content": None,
        "pipeline_id": None,
        "thread_id": thread_id,
        "run_id": run_id,
        "errors": [],
        "audit_log": [],
    }

    config = {"configurable": {"thread_id": thread_id}}
    graph = get_discovery_graph()

    logger.info("Discovery pipeline starting: thread_id=%s", thread_id)
    try:
        result = await graph.ainvoke(initial_state, config=config)
        scored = result.get("scored_grants", [])
        logger.info(
            "Discovery pipeline complete: thread_id=%s, grants_scored=%d",
            thread_id, len(scored),
        )
        return {
            "status": "complete",
            "thread_id": thread_id,
            "total_found": len(result.get("raw_grants", [])),
            "new_grants": len(scored),
        }
    except Exception as e:
        logger.error("Discovery pipeline failed: %s", e)
        try:
            import traceback as _tb
            from backend.integrations.notion_sync import log_error
            await log_error(
                agent="scout",
                error=e,
                tb=_tb.format_exc(),
                severity="Critical",
            )
        except Exception:
            logger.debug("Notion error sync skipped (scout job)", exc_info=True)
        return {"status": "error", "error": str(e), "thread_id": thread_id}
