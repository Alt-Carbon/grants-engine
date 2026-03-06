"""Scout cron job — triggered by Vercel or APScheduler every 48h."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from backend.graph.graph import get_graph
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)


async def run_scout_pipeline() -> dict:
    """Run Scout → Analyst → notify_triage. Pauses at human_triage interrupt."""
    thread_id = f"scout_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
    run_id = str(uuid.uuid4())

    initial_state: GrantState = {
        "raw_grants": [],
        "scored_grants": [],
        "human_triage_decision": None,
        "selected_grant_id": None,
        "triage_notes": None,
        "grant_requirements": None,
        "grant_raw_doc": None,
        "company_context": None,
        "style_examples": None,
        "style_examples_loaded": False,
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
    graph = get_graph()

    logger.info("Scout job starting: thread_id=%s", thread_id)
    try:
        # Graph will run scout → analyst → notify_triage → PAUSE at human_triage
        await graph.ainvoke(initial_state, config=config)
        logger.info("Scout job complete: thread_id=%s (paused at triage)", thread_id)
        return {"status": "paused_at_triage", "thread_id": thread_id}
    except Exception as e:
        logger.error("Scout job failed: %s", e)
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
