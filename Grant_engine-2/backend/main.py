"""AltCarbon Grants Intelligence — FastAPI Backend (Railway)

Endpoints:
  POST /cron/scout              ← Vercel cron every 48h
  POST /cron/knowledge-sync     ← Vercel cron daily
  POST /run/scout               ← Streamlit manual trigger
  POST /run/knowledge-sync      ← Streamlit manual trigger
  POST /resume/triage           ← Streamlit triage decision
  POST /resume/section-review   ← Streamlit section approve/revise
  POST /resume/start-draft      ← Streamlit start draft for a grant
  GET  /health
  GET  /status/pipeline
  GET  /status/thread/{thread_id}
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.db.mongo import ensure_indexes, get_db
from backend.graph.graph import get_graph
from backend.jobs.backfill_job import run_field_backfill, run_deduplication
from backend.jobs.knowledge_job import run_knowledge_sync
from backend.jobs.scout_job import run_scout_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Scout job state (in-process flag) ─────────────────────────────────────────
_scout_running: bool = False
_scout_started_at: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    await _seed_default_agent_config()
    logger.info("AltCarbon Grants Intelligence backend started")
    yield
    logger.info("Backend shutting down")


app = FastAPI(title="AltCarbon Grants Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helpers ───────────────────────────────────────────────────────────────

def verify_cron(x_cron_secret: Optional[str] = Header(default=None)):
    expected = os.environ.get("CRON_SECRET", "dev-cron-secret")
    if x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret")


def verify_internal(x_internal_secret: Optional[str] = Header(default=None)):
    expected = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")
    if x_internal_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


# ── Request/Response models ────────────────────────────────────────────────────

class TriageResumeRequest(BaseModel):
    thread_id: str
    grant_id: str
    decision: str   # "pursue" | "watch" | "pass"
    notes: Optional[str] = None


class SectionReviewRequest(BaseModel):
    thread_id: str
    section_name: str
    action: str                         # "approve" | "revise"
    instructions: Optional[str] = None
    critique: Optional[str] = None
    edited_content: Optional[str] = None


class StartDraftRequest(BaseModel):
    grant_id: str
    thread_id: Optional[str] = None


# ── Seed default agent config ──────────────────────────────────────────────────

async def _seed_default_agent_config():
    from backend.db.mongo import agent_config
    defaults = [
        {
            "agent": "scout",
            "enabled": True,
            "run_frequency_hours": 48,
            "max_results_per_query": 10,
            "search_tools": ["tavily", "exa"],
            "themes": ["climatetech", "agritech", "ai_for_sciences", "applied_earth_sciences", "social_impact"],
            "custom_queries": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "agent": "analyst",
            "enabled": True,
            "scoring_weights": {
                "theme_alignment": 0.25,
                "eligibility_confidence": 0.20,
                "funding_amount": 0.20,
                "deadline_urgency": 0.15,
                "geography_fit": 0.10,
                "competition_level": 0.10,
            },
            "pursue_threshold": 6.5,
            "watch_threshold": 5.0,
            "min_funding": 3000,
            "eligible_geographies": ["India", "Global"],
            "perplexity_enrichment": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "agent": "drafter",
            "enabled": True,
            "writing_style": "professional",
            "word_limit_buffer_pct": 10,
            "context_chunks_per_section": 6,
            "custom_instructions": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    col = agent_config()
    for cfg in defaults:
        await col.update_one({"agent": cfg["agent"]}, {"$setOnInsert": cfg}, upsert=True)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/status/scout")
async def scout_status():
    """Current scout job state + last run info. Polled by Streamlit."""
    from backend.db.mongo import scout_runs
    last = await scout_runs().find_one(sort=[("run_at", -1)])
    return {
        "running": _scout_running,
        "started_at": _scout_started_at,
        "last_run_at": last["run_at"] if last else None,
        "last_run_new_grants": last.get("new_grants", 0) if last else 0,
        "last_run_total_found": last.get("total_found", 0) if last else 0,
        "total_runs": await scout_runs().count_documents({}),
    }


# ── Cron endpoints (called by Vercel) ─────────────────────────────────────────

@app.post("/cron/scout")
async def cron_scout(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_cron),
):
    background_tasks.add_task(run_scout_pipeline)
    return {"status": "scout_job_started"}


@app.post("/cron/knowledge-sync")
async def cron_knowledge_sync(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_cron),
):
    background_tasks.add_task(run_knowledge_sync)
    return {"status": "knowledge_sync_started"}


# ── Manual run endpoints (called by Streamlit) ────────────────────────────────

@app.post("/run/scout")
async def manual_scout(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    global _scout_running, _scout_started_at
    if _scout_running:
        return {"status": "scout_already_running", "started_at": _scout_started_at}

    _scout_running = True
    _scout_started_at = datetime.now(timezone.utc).isoformat()

    async def _run():
        global _scout_running, _scout_started_at
        try:
            await run_scout_pipeline()
        finally:
            _scout_running = False
            _scout_started_at = None

    background_tasks.add_task(_run)
    return {"status": "scout_job_started", "started_at": _scout_started_at}


@app.post("/run/knowledge-sync")
async def manual_knowledge_sync(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    background_tasks.add_task(run_knowledge_sync)
    return {"status": "knowledge_sync_started"}


# ── Resume endpoints ───────────────────────────────────────────────────────────

@app.post("/resume/triage")
async def resume_triage(
    body: TriageResumeRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Human made triage decision. Resume graph from human_triage node."""
    async def _resume():
        graph = get_graph()
        config = {"configurable": {"thread_id": body.thread_id}}
        await graph.ainvoke(
            {
                "human_triage_decision": body.decision,
                "selected_grant_id": body.grant_id,
                "triage_notes": body.notes,
            },
            config=config,
        )

    background_tasks.add_task(_resume)
    return {"status": "triage_resumed", "thread_id": body.thread_id}


@app.post("/resume/section-review")
async def resume_section_review(
    body: SectionReviewRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Human approved or requested revision on a section. Resume drafter."""
    async def _resume():
        graph = get_graph()
        config = {"configurable": {"thread_id": body.thread_id}}
        update: dict = {"section_review_decision": body.action}
        if body.edited_content:
            update["section_edited_content"] = body.edited_content
        if body.instructions:
            # Merge revision instructions into state
            from backend.db.mongo import graph_checkpoints
            update["section_revision_instructions"] = {body.section_name: body.instructions}
        if body.critique:
            update["section_critiques"] = {body.section_name: body.critique}
        await graph.ainvoke(update, config=config)

    background_tasks.add_task(_resume)
    return {"status": "section_review_resumed", "thread_id": body.thread_id}


@app.post("/resume/start-draft")
async def start_draft(
    body: StartDraftRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Start a new draft pipeline for an already-triaged grant."""
    from backend.db.mongo import grants_pipeline, grants_scored
    from bson import ObjectId

    thread_id = body.thread_id or f"draft_{body.grant_id[:8]}_{uuid.uuid4().hex[:6]}"
    run_id = str(uuid.uuid4())

    # Create pipeline record
    pipeline_id = None
    try:
        grant = await grants_scored().find_one({"_id": ObjectId(body.grant_id)})
        if not grant:
            raise HTTPException(status_code=404, detail="Grant not found")

        result = await grants_pipeline().insert_one({
            "grant_id": body.grant_id,
            "thread_id": thread_id,
            "status": "drafting",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "draft_started_at": datetime.now(timezone.utc).isoformat(),
            "current_draft_version": 0,
            "final_draft_url": None,
        })
        pipeline_id = str(result.inserted_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def _run_draft():
        from backend.graph.state import GrantState
        graph = get_graph()
        config = {"configurable": {"thread_id": thread_id}}

        # Start from company_brain (triage already done)
        initial_state: GrantState = {
            "raw_grants": [],
            "scored_grants": [],
            "human_triage_decision": "pursue",
            "selected_grant_id": body.grant_id,
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
            "pipeline_id": pipeline_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "errors": [],
            "audit_log": [],
        }
        # Skip scout/analyst — start directly at company_brain
        # We do this by building a separate subgraph or invoking with correct config
        # For now: invoke the full graph but with human_triage already decided
        # The interrupt_before=["human_triage"] will pause — we pre-fill the decision
        await graph.ainvoke(initial_state, config=config)

    background_tasks.add_task(_run_draft)
    return {"status": "draft_started", "thread_id": thread_id, "pipeline_id": pipeline_id}


# ── Status endpoints ───────────────────────────────────────────────────────────

@app.get("/status/pipeline")
async def pipeline_status():
    db = get_db()
    total = await db["grants_scored"].count_documents({})
    triage = await db["grants_scored"].count_documents({"status": "triage"})
    pursuing = await db["grants_scored"].count_documents({"status": "pursue"})
    drafting = await db["grants_pipeline"].count_documents({"status": "drafting"})
    complete = await db["grants_pipeline"].count_documents({"status": "draft_complete"})
    return {
        "total_discovered": total,
        "in_triage": triage,
        "pursuing": pursuing,
        "drafting": drafting,
        "draft_complete": complete,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status/thread/{thread_id}")
async def thread_status(thread_id: str):
    """Check if a thread has a pending section interrupt."""
    from backend.db.mongo import graph_checkpoints
    doc = await graph_checkpoints().find_one(
        {"thread_id": thread_id},
        sort=[("checkpoint_id", -1)],
    )
    if not doc:
        return {"status": "not_found", "thread_id": thread_id}

    import json
    checkpoint = json.loads(doc.get("checkpoint", "{}"))
    channel_values = checkpoint.get("channel_values", {})
    pending_interrupt = channel_values.get("pending_interrupt")

    return {
        "status": "interrupted" if pending_interrupt else "running",
        "thread_id": thread_id,
        "pending_section": pending_interrupt.get("section_name") if pending_interrupt else None,
        "pending_interrupt": pending_interrupt,
    }


# ── Admin: backfill + deduplication ───────────────────────────────────────────

@app.post("/admin/backfill-fields")
async def admin_backfill_fields(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Backfill structured fields (grant_type, geography, eligibility, application_url,
    amount, rationale) on all existing grants missing these fields."""
    background_tasks.add_task(run_field_backfill)
    return {"status": "backfill_started", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/admin/deduplicate")
async def admin_deduplicate(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Remove duplicate grants from grants_raw and grants_scored collections."""
    background_tasks.add_task(run_deduplication)
    return {"status": "deduplication_started", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/drafts/{thread_id}/download")
async def download_draft(thread_id: str):
    """Return the latest draft markdown for a thread."""
    from backend.db.mongo import grants_pipeline, grant_drafts
    from bson import ObjectId
    from fastapi.responses import PlainTextResponse

    pipeline = await grants_pipeline().find_one({"thread_id": thread_id})
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    draft = await grant_drafts().find_one(
        {"pipeline_id": str(pipeline["_id"])},
        sort=[("version", -1)],
    )
    if not draft:
        # Try reading from /tmp
        import glob
        files = glob.glob(f"/tmp/drafts/*.md")
        if not files:
            raise HTTPException(status_code=404, detail="Draft not found")
        with open(files[-1]) as f:
            content = f.read()
        return PlainTextResponse(content, media_type="text/markdown")

    # Assemble from DB
    sections = draft.get("sections", {})
    content = "\n\n".join(
        f"## {name}\n{sec.get('content', '')}"
        for name, sec in sections.items()
    )
    return PlainTextResponse(content, media_type="text/markdown")
