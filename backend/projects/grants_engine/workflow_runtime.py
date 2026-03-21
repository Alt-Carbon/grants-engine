"""Grants-engine bindings for the reusable workflow orchestrator."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Sequence
from uuid import uuid4

from backend.db.mongo import workflow_runs
from backend.platform.contracts import AgentExecutionContext
from backend.platform.orchestrators import MongoWorkflowOrchestrator
from backend.pipeline.status_contract import draft_startable_statuses


logger = logging.getLogger(__name__)

REVIEW_WORKFLOW_NAME = "grants_engine.review_bundle"
DRAFT_START_WORKFLOW_NAME = "grants_engine.draft.start"
TRIAGE_RESUME_WORKFLOW_NAME = "grants_engine.triage.resume"
SECTION_REVIEW_RESUME_WORKFLOW_NAME = "grants_engine.section_review.resume"
SCOUT_RUN_WORKFLOW_NAME = "grants_engine.scout.run"
KNOWLEDGE_SYNC_WORKFLOW_NAME = "grants_engine.knowledge_sync.run"
FIELD_BACKFILL_WORKFLOW_NAME = "grants_engine.backfill.fields"
DEDUPLICATION_WORKFLOW_NAME = "grants_engine.deduplication.run"
NOTION_BACKFILL_WORKFLOW_NAME = "grants_engine.notion_backfill.run"
ANALYST_RUN_WORKFLOW_NAME = "grants_engine.analyst.run"
ANALYST_RESCORE_WORKFLOW_NAME = "grants_engine.analyst.rescore"
ANALYST_RESCORE_SINGLE_WORKFLOW_NAME = "grants_engine.analyst.rescore_single"
PROFILE_SYNC_WORKFLOW_NAME = "grants_engine.profile_sync.run"
NOTION_CHANGE_CHECK_WORKFLOW_NAME = "grants_engine.notion_change_check.run"
ANALYST_WORKFLOW_NAMES = [
    ANALYST_RUN_WORKFLOW_NAME,
    ANALYST_RESCORE_WORKFLOW_NAME,
    ANALYST_RESCORE_SINGLE_WORKFLOW_NAME,
]


async def _run_review_bundle(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.agents.dual_reviewer import run_dual_review

    grant_id = str(payload["grant_id"])
    await run_dual_review(grant_id)
    return {
        "grant_id": grant_id,
        "workflow_name": context.workflow_name,
        "status": "review_completed",
    }


async def _predraft_validate(grant: dict) -> dict | None:
    from backend.agents.analyst import parse_deadline

    status = (grant.get("status") or "").lower()
    if status not in draft_startable_statuses():
        return {
            "check": "status",
            "reason": f"Grant status is '{status}' — only pursue-stage grants can start drafting",
        }

    deadline_str = grant.get("deadline")
    if deadline_str:
        deadline_dt = parse_deadline(deadline_str)
        if deadline_dt and deadline_dt < datetime.now(timezone.utc):
            return {
                "check": "deadline",
                "reason": f"Grant deadline {deadline_dt.strftime('%Y-%m-%d')} has expired",
            }

    return None


async def _run_start_draft(payload: dict, context: AgentExecutionContext) -> dict:
    from bson import ObjectId

    from backend.db.mongo import audit_logs, grants_pipeline, grants_scored
    from backend.graph.graph import get_graph

    grant_id = str(payload["grant_id"])
    override_guardrails = bool(payload.get("override_guardrails"))
    override_reason = payload.get("override_reason")
    thread_id = str(payload["thread_id"])
    run_id = str(payload["run_id"])
    previous_status = str(payload.get("starting_status") or "pursue")

    grant = await grants_scored().find_one({"_id": ObjectId(grant_id)})
    if not grant:
        raise ValueError(f"Grant not found: {grant_id}")

    current_status = (grant.get("status") or "").lower()
    if current_status == "guardrail_rejected" and not override_guardrails:
        raise ValueError("Grant is guardrail_rejected and requires an explicit override")
    if current_status not in draft_startable_statuses() and current_status != "guardrail_rejected":
        raise ValueError(
            f"Grant status is '{current_status}' — only pursue-stage grants can start drafting"
        )

    existing_draft = await grants_pipeline().find_one(
        {
            "grant_id": grant_id,
            "status": {"$in": ["drafting", "pending_interrupt"]},
        }
    )
    if existing_draft:
        return {
            "grant_id": grant_id,
            "thread_id": existing_draft.get("thread_id"),
            "pipeline_id": str(existing_draft.get("_id", "")),
            "status": "draft_already_in_progress",
        }

    if not override_guardrails:
        validation_error = await _predraft_validate(grant)
        if validation_error:
            try:
                from backend.platform.services.status_service import change_grant_status

                await change_grant_status(
                    grant_id=grant_id,
                    new_status="guardrail_rejected",
                    user_email=context.user_email or "system",
                    source="draft_workflow",
                )
            except Exception:
                logger.debug("Failed to sync guardrail_rejected status", exc_info=True)

            try:
                from backend.notifications.hub import notify

                grant_title = grant.get("title") or grant.get("grant_name") or grant_id
                await notify(
                    event_type="guardrail_rejected",
                    title=f"Pre-draft blocked: {grant_title[:60]}",
                    body=validation_error["reason"][:200],
                    priority="high",
                    metadata={"grant_id": grant_id, "check": validation_error["check"]},
                )
            except Exception:
                logger.debug("Guardrail rejection notification failed", exc_info=True)

            raise ValueError(validation_error["reason"])

    pipeline_id = None
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        result = await grants_pipeline().insert_one(
            {
                "grant_id": grant_id,
                "thread_id": thread_id,
                "status": "drafting",
                "started_at": now_iso,
                "draft_started_at": now_iso,
                "current_draft_version": 0,
                "final_draft_url": None,
                "override_guardrails": override_guardrails,
                "override_reason": override_reason,
                "started_by": context.user_email or "system",
            }
        )
        pipeline_id = str(result.inserted_id)
        await grants_scored().update_one(
            {"_id": ObjectId(grant_id)},
            {"$set": {"status": "drafting"}},
        )
        await audit_logs().insert_one(
            {
                "node": "drafter",
                "action": "draft_started",
                "grant_id": grant_id,
                "grant_name": grant.get("title") or grant.get("grant_name") or "",
                "user_email": context.user_email or "system",
                "thread_id": thread_id,
                "workflow_id": context.run_id,
                "created_at": now_iso,
            }
        )

        graph = get_graph()
        config = {"configurable": {"thread_id": thread_id}}
        triage_state = {
            "raw_grants": [],
            "scored_grants": [],
            "human_triage_decision": "pursue",
            "selected_grant_id": grant_id,
            "triage_notes": None,
            "grant_requirements": None,
            "grant_raw_doc": None,
            "company_profile": None,
            "company_context": None,
            "style_examples": None,
            "style_examples_loaded": False,
            "draft_guardrail_result": None,
            "override_guardrails": override_guardrails,
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
            "pipeline_id": pipeline_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "errors": [],
            "audit_log": [
                {
                    "node": "human_triage",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "decision": "pursue",
                    "grant_id": grant_id,
                    "override_guardrails": override_guardrails,
                    "override_reason": override_reason,
                }
            ],
        }

        await graph.aupdate_state(config, triage_state, as_node="human_triage")
        await graph.ainvoke(None, config=config)
        await graph.ainvoke(None, config=config)
    except Exception:
        if pipeline_id:
            failure_time = datetime.now(timezone.utc).isoformat()
            await grants_pipeline().update_one(
                {"_id": ObjectId(pipeline_id)},
                {
                    "$set": {
                        "status": "cancelled",
                        "updated_at": failure_time,
                        "failure_reason": "draft_workflow_failed",
                    }
                },
            )
            await grants_scored().update_one(
                {"_id": ObjectId(grant_id)},
                {"$set": {"status": previous_status, "updated_at": failure_time}},
            )
        raise

    return {
        "grant_id": grant_id,
        "thread_id": thread_id,
        "pipeline_id": pipeline_id,
        "status": "draft_started",
    }


async def _run_resume_triage(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.graph.graph import get_graph

    graph = get_graph()
    thread_id = str(payload["thread_id"])
    grant_id = str(payload["grant_id"])
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(
        {
            "human_triage_decision": payload["decision"],
            "selected_grant_id": grant_id,
            "triage_notes": payload.get("notes"),
        },
        config=config,
    )
    return {
        "thread_id": thread_id,
        "grant_id": grant_id,
        "decision": payload["decision"],
        "status": "triage_resumed",
    }


async def _run_resume_section_review(payload: dict, context: AgentExecutionContext) -> dict:
    from langgraph.types import Command

    from backend.graph.graph import get_graph

    graph = get_graph()
    thread_id = str(payload["thread_id"])
    section_name = str(payload["section_name"])
    config = {"configurable": {"thread_id": thread_id}}
    update: dict = {"section_review_decision": payload["action"]}
    if payload.get("edited_content"):
        update["section_edited_content"] = payload["edited_content"]
    if payload.get("instructions"):
        update["section_revision_instructions"] = {section_name: payload["instructions"]}
    if payload.get("critique"):
        update["section_critiques"] = {section_name: payload["critique"]}

    await graph.ainvoke(Command(resume=True, update=update), config=config)
    return {
        "thread_id": thread_id,
        "section_name": section_name,
        "action": payload["action"],
        "status": "section_review_resumed",
    }


async def _run_scout(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.jobs.scout_job import run_scout_pipeline

    result = await run_scout_pipeline()
    if result.get("status") == "error":
        error_message = result.get("error") or "Scout workflow failed"
        try:
            from backend.notifications.hub import notify_agent_error

            await notify_agent_error("scout", error_message)
        except Exception:
            logger.debug("Scout error notification failed", exc_info=True)
        raise RuntimeError(error_message)

    try:
        from backend.notifications.hub import notify_scout_complete

        await notify_scout_complete(
            new_grants=result.get("new_grants", 0) if isinstance(result, dict) else 0,
            total_found=result.get("total_found", 0) if isinstance(result, dict) else 0,
        )
    except Exception:
        logger.debug("Scout notification failed", exc_info=True)

    return result


async def _run_knowledge_sync(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.jobs.knowledge_job import run_knowledge_sync

    result = await run_knowledge_sync()
    if result.get("status") == "error":
        raise RuntimeError(result.get("error") or "Knowledge sync failed")
    return result


async def _run_field_backfill(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.jobs.backfill_job import run_field_backfill

    return await run_field_backfill()


async def _run_deduplication(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.jobs.backfill_job import run_deduplication

    return await run_deduplication()


async def _run_notion_backfill(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.db.mongo import grants_scored
    from backend.integrations.notion_sync import backfill_grants

    cursor = grants_scored().find({}).sort("weighted_total", -1)
    all_grants = await cursor.to_list(length=2000)
    count = await backfill_grants(all_grants)
    return {
        "status": "ok",
        "synced_count": count,
        "input_count": len(all_grants),
    }


async def _run_analyst(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.agents.analyst import AnalystAgent, DEFAULT_WEIGHTS
    from backend.config.settings import get_settings
    from backend.db.mongo import agent_config, grants_raw, get_db

    s = get_settings()
    cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
    weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
    min_funding = cfg_doc.get("min_funding", s.min_grant_funding)

    raw_docs = await grants_raw().find({"processed": False}).to_list(length=2000)
    logger.info("Analyst workflow: %d unprocessed grants found", len(raw_docs))

    agent = AnalystAgent(
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        weights=weights,
        min_funding=min_funding,
    )
    scored = await agent.run(raw_docs)
    scored_count = len(scored)

    db = get_db()
    await db["audit_logs"].insert_one(
        {
            "event": "analyst_run_complete",
            "scored_count": scored_count,
            "input_count": len(raw_docs),
            "triggered_by": context.user_email or "system",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        from backend.notifications.hub import notify_analyst_complete, notify_high_score_grant

        triage_count = sum(1 for grant in scored if grant.get("status") == "triage")
        pursue_count = sum(
            1 for grant in scored if grant.get("recommended_action") == "pursue"
        )
        await notify_analyst_complete(
            scored_count=scored_count,
            triage_count=triage_count,
            pursue_count=pursue_count,
        )
        for grant in scored:
            score = grant.get("weighted_total", 0)
            if score >= 7.0:
                await notify_high_score_grant(
                    grant_name=grant.get("grant_name") or grant.get("title") or "Unknown",
                    grant_id=str(grant.get("_id", "")),
                    score=score,
                    funder=grant.get("funder", ""),
                )
    except Exception:
        logger.debug("Analyst notification failed", exc_info=True)

    return {
        "input_count": len(raw_docs),
        "scored_count": scored_count,
    }


async def _run_analyst_rescore(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.agents.analyst import AnalystAgent, DEFAULT_WEIGHTS
    from backend.config.settings import get_settings
    from backend.db.mongo import agent_config, grants_scored, get_db

    min_score = float(payload.get("min_score") or 3.0)
    s = get_settings()
    cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
    weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
    min_funding = cfg_doc.get("min_funding", s.min_grant_funding)

    rescore_grants = await grants_scored().find(
        {"weighted_total": {"$gte": min_score}}
    ).to_list(2000)
    logger.info(
        "Analyst rescore workflow: %d grants with score >= %.1f",
        len(rescore_grants),
        min_score,
    )
    if not rescore_grants:
        return {"input_count": 0, "scored_count": 0, "min_score": min_score}

    raw_like = []
    for grant in rescore_grants:
        raw_like.append(
            {
                "_id": grant["_id"],
                "title": grant.get("title") or grant.get("grant_name") or "",
                "url": grant.get("url") or grant.get("source_url") or "",
                "url_hash": grant.get("url_hash", ""),
                "content_hash": grant.get("content_hash", ""),
                "funder": grant.get("funder", ""),
                "deadline": grant.get("deadline", ""),
                "amount": grant.get("amount") or grant.get("max_funding") or "",
                "eligibility": grant.get("eligibility", ""),
                "geography": grant.get("geography", ""),
                "grant_type": grant.get("grant_type", ""),
                "themes_detected": grant.get("themes_detected", []),
                "about_opportunity": grant.get("about_opportunity", ""),
                "application_process": grant.get("application_process", ""),
                "scraped_at": grant.get("scraped_at", ""),
            }
        )

    scored_ids = [grant["_id"] for grant in rescore_grants]
    delete_result = await grants_scored().delete_many({"_id": {"$in": scored_ids}})
    logger.info("Analyst rescore workflow: deleted %d records", delete_result.deleted_count)

    agent = AnalystAgent(
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        weights=weights,
        min_funding=min_funding,
    )
    scored = await agent.run(raw_like)

    db = get_db()
    await db["audit_logs"].insert_one(
        {
            "event": "analyst_rescore_complete",
            "scored_count": len(scored),
            "input_count": len(rescore_grants),
            "min_score_filter": min_score,
            "triggered_by": context.user_email or "system",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        from backend.notifications.hub import notify_analyst_complete

        triage_count = sum(1 for grant in scored if grant.get("status") == "triage")
        pursue_count = sum(
            1 for grant in scored if grant.get("recommended_action") == "pursue"
        )
        await notify_analyst_complete(
            scored_count=len(scored),
            triage_count=triage_count,
            pursue_count=pursue_count,
        )
    except Exception:
        logger.debug("Rescore notification failed", exc_info=True)

    return {
        "input_count": len(rescore_grants),
        "scored_count": len(scored),
        "min_score": min_score,
    }


async def _run_analyst_rescore_single(payload: dict, context: AgentExecutionContext) -> dict:
    from bson import ObjectId

    from backend.agents.analyst import AnalystAgent, DEFAULT_WEIGHTS
    from backend.config.settings import get_settings
    from backend.db.mongo import agent_config, grants_scored, get_db

    grant_id = str(payload["grant_id"])
    s = get_settings()
    cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
    weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
    min_funding = cfg_doc.get("min_funding", s.min_grant_funding)

    try:
        oid = ObjectId(grant_id)
    except Exception as exc:
        raise ValueError(f"Invalid grant_id: {grant_id}") from exc

    grant_doc = await grants_scored().find_one({"_id": oid})
    if not grant_doc:
        raise ValueError(f"Grant not found: {grant_id}")

    raw_doc = {
        "_id": grant_doc["_id"],
        "title": grant_doc.get("title") or grant_doc.get("grant_name") or "",
        "url": grant_doc.get("url") or grant_doc.get("source_url") or "",
        "url_hash": grant_doc.get("url_hash", ""),
        "content_hash": grant_doc.get("content_hash", ""),
        "funder": grant_doc.get("funder", ""),
        "deadline": grant_doc.get("deadline", ""),
        "amount": grant_doc.get("amount") or grant_doc.get("max_funding") or "",
        "eligibility": grant_doc.get("eligibility", ""),
        "geography": grant_doc.get("geography", ""),
        "grant_type": grant_doc.get("grant_type", ""),
        "themes_detected": grant_doc.get("themes_detected", []),
        "about_opportunity": grant_doc.get("about_opportunity", ""),
        "application_process": grant_doc.get("application_process", ""),
        "scraped_at": grant_doc.get("scraped_at", ""),
    }

    await grants_scored().delete_one({"_id": oid})

    agent = AnalystAgent(
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        weights=weights,
        min_funding=min_funding,
    )
    scored = await agent.run([raw_doc])

    db = get_db()
    await db["audit_logs"].insert_one(
        {
            "event": "analyst_rescore_single",
            "grant_id": grant_id,
            "grant_name": grant_doc.get("grant_name") or grant_doc.get("title") or "",
            "triggered_by": context.user_email or "system",
            "scored_count": len(scored),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    return {
        "grant_id": grant_id,
        "grant_name": grant_doc.get("grant_name") or grant_doc.get("title") or "",
        "scored_count": len(scored),
    }


async def _run_profile_sync(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.knowledge.sync_profile import sync_profile_from_notion

    result = await sync_profile_from_notion()
    return {"status": "ok", "result": str(result)}


async def _run_notion_change_check(payload: dict, context: AgentExecutionContext) -> dict:
    from backend.jobs.scheduler import check_notion_changes

    result = await check_notion_changes()
    return result


def get_grants_orchestrator() -> MongoWorkflowOrchestrator:
    return MongoWorkflowOrchestrator(
        handlers={
            REVIEW_WORKFLOW_NAME: _run_review_bundle,
            DRAFT_START_WORKFLOW_NAME: _run_start_draft,
            TRIAGE_RESUME_WORKFLOW_NAME: _run_resume_triage,
            SECTION_REVIEW_RESUME_WORKFLOW_NAME: _run_resume_section_review,
            SCOUT_RUN_WORKFLOW_NAME: _run_scout,
            KNOWLEDGE_SYNC_WORKFLOW_NAME: _run_knowledge_sync,
            FIELD_BACKFILL_WORKFLOW_NAME: _run_field_backfill,
            DEDUPLICATION_WORKFLOW_NAME: _run_deduplication,
            NOTION_BACKFILL_WORKFLOW_NAME: _run_notion_backfill,
            ANALYST_RUN_WORKFLOW_NAME: _run_analyst,
            ANALYST_RESCORE_WORKFLOW_NAME: _run_analyst_rescore,
            ANALYST_RESCORE_SINGLE_WORKFLOW_NAME: _run_analyst_rescore_single,
            PROFILE_SYNC_WORKFLOW_NAME: _run_profile_sync,
            NOTION_CHANGE_CHECK_WORKFLOW_NAME: _run_notion_change_check,
        }
    )


async def _find_active_run_for_names(workflow_names: Sequence[str]) -> dict | None:
    return await workflow_runs().find_one(
        {
            "workflow_name": {"$in": list(workflow_names)},
            "status": {"$in": ["pending", "running"]},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _enqueue_workflow(
    *,
    workflow_name: str,
    payload: dict,
    user_email: str,
) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=workflow_name,
        payload_match=payload,
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "thread_id": (existing.get("payload") or {}).get("thread_id"),
            "deduplicated": True,
        }

    context = AgentExecutionContext(
        project="grants_engine",
        workflow_name=workflow_name,
        run_id=uuid4().hex,
        request_id=uuid4().hex,
        user_email=user_email,
        metadata={**payload, "max_attempts": 3},
    )
    handle = await orchestrator.start_workflow(
        workflow_name,
        payload,
        context,
    )
    handle["deduplicated"] = False
    return handle


async def enqueue_review_workflow(*, grant_id: str, user_email: str) -> dict:
    return await _enqueue_workflow(
        workflow_name=REVIEW_WORKFLOW_NAME,
        payload={"grant_id": grant_id},
        user_email=user_email,
    )


async def enqueue_start_draft_workflow(
    *,
    grant_id: str,
    user_email: str,
    thread_id: str,
    run_id: str,
    override_guardrails: bool,
    override_reason: str | None,
    starting_status: str,
) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=DRAFT_START_WORKFLOW_NAME,
        payload_match={"grant_id": grant_id},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=DRAFT_START_WORKFLOW_NAME,
        payload={
            "grant_id": grant_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "override_guardrails": override_guardrails,
            "override_reason": override_reason,
            "starting_status": starting_status,
        },
        user_email=user_email,
    )


async def enqueue_resume_triage_workflow(
    *,
    thread_id: str,
    grant_id: str,
    decision: str,
    notes: str | None,
    user_email: str,
) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=TRIAGE_RESUME_WORKFLOW_NAME,
        payload_match={"thread_id": thread_id},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "thread_id": (existing.get("payload") or {}).get("thread_id"),
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=TRIAGE_RESUME_WORKFLOW_NAME,
        payload={
            "thread_id": thread_id,
            "grant_id": grant_id,
            "decision": decision,
            "notes": notes,
        },
        user_email=user_email,
    )


async def enqueue_resume_section_review_workflow(
    *,
    thread_id: str,
    section_name: str,
    action: str,
    edited_content: str | None,
    instructions: str | None,
    critique: str | None,
    user_email: str,
) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=SECTION_REVIEW_RESUME_WORKFLOW_NAME,
        payload_match={"thread_id": thread_id},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "thread_id": (existing.get("payload") or {}).get("thread_id"),
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=SECTION_REVIEW_RESUME_WORKFLOW_NAME,
        payload={
            "thread_id": thread_id,
            "section_name": section_name,
            "action": action,
            "edited_content": edited_content,
            "instructions": instructions,
            "critique": critique,
        },
        user_email=user_email,
    )


async def enqueue_scout_run(*, user_email: str) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=SCOUT_RUN_WORKFLOW_NAME,
        payload_match={},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=SCOUT_RUN_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_knowledge_sync_run(*, user_email: str) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=KNOWLEDGE_SYNC_WORKFLOW_NAME,
        payload_match={},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=KNOWLEDGE_SYNC_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_field_backfill_run(*, user_email: str) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=FIELD_BACKFILL_WORKFLOW_NAME,
        payload_match={},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=FIELD_BACKFILL_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_deduplication_run(*, user_email: str) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=DEDUPLICATION_WORKFLOW_NAME,
        payload_match={},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=DEDUPLICATION_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_notion_backfill_run(*, user_email: str) -> dict:
    orchestrator = get_grants_orchestrator()
    existing = await orchestrator.find_active_run(
        workflow_name=NOTION_BACKFILL_WORKFLOW_NAME,
        payload_match={},
    )
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }

    return await _enqueue_workflow(
        workflow_name=NOTION_BACKFILL_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_analyst_run(*, user_email: str) -> dict:
    existing = await _find_active_run_for_names(ANALYST_WORKFLOW_NAMES)
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }
    return await _enqueue_workflow(
        workflow_name=ANALYST_RUN_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_analyst_rescore(*, min_score: float, user_email: str) -> dict:
    existing = await _find_active_run_for_names(ANALYST_WORKFLOW_NAMES)
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }
    return await _enqueue_workflow(
        workflow_name=ANALYST_RESCORE_WORKFLOW_NAME,
        payload={"min_score": min_score},
        user_email=user_email,
    )


async def enqueue_analyst_rescore_single(*, grant_id: str, user_email: str) -> dict:
    existing = await _find_active_run_for_names(ANALYST_WORKFLOW_NAMES)
    if existing:
        return {
            "workflow_id": existing["workflow_id"],
            "workflow_name": existing["workflow_name"],
            "status": existing["status"],
            "deduplicated": True,
        }
    return await _enqueue_workflow(
        workflow_name=ANALYST_RESCORE_SINGLE_WORKFLOW_NAME,
        payload={"grant_id": grant_id},
        user_email=user_email,
    )


async def enqueue_profile_sync_run(*, user_email: str) -> dict:
    return await _enqueue_workflow(
        workflow_name=PROFILE_SYNC_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def enqueue_notion_change_check_run(*, user_email: str) -> dict:
    return await _enqueue_workflow(
        workflow_name=NOTION_CHANGE_CHECK_WORKFLOW_NAME,
        payload={},
        user_email=user_email,
    )


async def drain_grants_workflows(
    *,
    workflow_names: Iterable[str] | None = None,
    limit: int = 10,
) -> int:
    orchestrator = get_grants_orchestrator()
    return await orchestrator.drain(allowed_workflows=workflow_names, limit=limit)


async def get_workflow_run(workflow_id: str) -> dict | None:
    return await workflow_runs().find_one({"workflow_id": workflow_id}, {"_id": 0})


async def get_latest_workflow_run(*, workflow_names: Sequence[str], statuses: Sequence[str]) -> dict | None:
    return await workflow_runs().find_one(
        {
            "workflow_name": {"$in": list(workflow_names)},
            "status": {"$in": list(statuses)},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
