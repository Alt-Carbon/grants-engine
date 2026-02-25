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
    # Non-fatal startup: if MongoDB is unreachable (e.g. env var not yet
    # propagated on Railway), the app still starts and /health responds.
    try:
        await ensure_indexes()
        await _seed_default_agent_config()
        logger.info("AltCarbon Grants Intelligence backend started")
    except Exception as exc:
        logger.error("Startup DB init failed (non-fatal — check MONGODB_URI): %s", exc)
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
    decision: str                      # "pursue" | "watch" | "pass"
    notes: Optional[str] = None
    human_override: bool = False       # True when human overrides the AI recommendation
    override_reason: Optional[str] = None  # Required explanation when human_override=True


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


class UpdateGrantStatusRequest(BaseModel):
    grant_id: str
    status: str


class ManualGrantRequest(BaseModel):
    url: str
    title_override: Optional[str] = ""
    funder_override: Optional[str] = ""
    notes: Optional[str] = ""


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


# ── Analyst job state ─────────────────────────────────────────────────────────
_analyst_running: bool = False
_analyst_started_at: Optional[str] = None


@app.get("/status/analyst")
async def analyst_status():
    """Current analyst job state + last run info."""
    from backend.db.mongo import get_db
    db = get_db()
    last = await db["audit_logs"].find_one(
        {"event": "analyst_run_complete"},
        sort=[("created_at", -1)],
    )
    pending = await db["grants_raw"].count_documents({"processed": False})
    return {
        "running": _analyst_running,
        "started_at": _analyst_started_at,
        "last_run_at": last["created_at"] if last else None,
        "last_run_scored": last.get("scored_count", 0) if last else 0,
        "pending_unprocessed": pending,
    }


@app.post("/run/analyst")
async def manual_analyst(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Run the Analyst on all unprocessed grants_raw entries (including manually
    added ones). Idempotent — already-scored grants are skipped automatically."""
    global _analyst_running, _analyst_started_at
    if _analyst_running:
        return {"status": "analyst_already_running", "started_at": _analyst_started_at}

    _analyst_running = True
    _analyst_started_at = datetime.now(timezone.utc).isoformat()

    async def _run():
        global _analyst_running, _analyst_started_at
        try:
            from backend.agents.analyst import AnalystAgent
            from backend.config.settings import get_settings
            from backend.db.mongo import grants_raw, agent_config, get_db

            s = get_settings()
            cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
            from backend.agents.analyst import DEFAULT_WEIGHTS
            weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
            min_funding = cfg_doc.get("min_funding", s.min_grant_funding)

            # Fetch ALL unprocessed raw grants
            raw_docs = await grants_raw().find({"processed": False}).to_list(length=2000)
            logger.info("Analyst run: %d unprocessed grants found", len(raw_docs))

            agent = AnalystAgent(
                perplexity_api_key=s.perplexity_api_key,
                weights=weights,
                min_funding=min_funding,
            )
            scored = await agent.run(raw_docs)
            scored_count = len(scored)
            logger.info("Analyst run: %d grants scored", scored_count)

            # Write run audit entry so /status/analyst can report last run
            db = get_db()
            await db["audit_logs"].insert_one({
                "event": "analyst_run_complete",
                "scored_count": scored_count,
                "input_count": len(raw_docs),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error("Analyst run failed: %s", e)
        finally:
            _analyst_running = False
            _analyst_started_at = None

    background_tasks.add_task(_run)
    return {"status": "analyst_job_started", "started_at": _analyst_started_at}


# ── Resume endpoints ───────────────────────────────────────────────────────────

@app.post("/resume/triage")
async def resume_triage(
    body: TriageResumeRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Human made triage decision. Resume graph from human_triage node.

    If human_override=True, the override fields are written to grants_scored
    immediately (before the graph resumes) so the Streamlit UI can display them
    instantly and the flag survives even if the LangGraph resume fails.
    """
    # Durably persist the human override decision to MongoDB (fix #15).
    if body.human_override:
        from backend.db.mongo import grants_scored
        from bson import ObjectId
        try:
            await grants_scored().update_one(
                {"_id": ObjectId(body.grant_id)},
                {"$set": {
                    "human_override":  True,
                    "override_reason": body.override_reason or "",
                    "override_at":     datetime.now(timezone.utc).isoformat(),
                }},
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist human_override for grant %s: %s", body.grant_id, exc
            )

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
    total     = await db["grants_scored"].count_documents({})
    triage    = await db["grants_scored"].count_documents({"status": "triage"})
    pursuing  = await db["grants_scored"].count_documents({"status": "pursue"})
    watching  = await db["grants_scored"].count_documents({"status": "watch"})
    on_hold   = await db["grants_scored"].count_documents({"status": "hold"})
    # Grants with ≤30 days to deadline that are still actionable (fix #17/#18)
    deadline_urgent_count = await db["grants_scored"].count_documents(
        {"deadline_urgent": True, "status": {"$in": ["triage", "pursue", "watch"]}}
    )
    drafting  = await db["grants_pipeline"].count_documents({"status": "drafting"})
    complete  = await db["grants_pipeline"].count_documents({"status": "draft_complete"})

    # Build actionable warnings (fix #18)
    warnings: list = []
    if total > 0 and triage == 0:
        warnings.append(
            "Triage queue is empty — all scored grants have been reviewed or auto-passed. "
            "Run a new scout to discover fresh opportunities."
        )
    if deadline_urgent_count > 0:
        warnings.append(
            f"{deadline_urgent_count} grant(s) with urgent deadlines (≤30 days) "
            f"in your active queue — review now."
        )
    if on_hold > 0:
        warnings.append(
            f"{on_hold} grant(s) on HOLD due to unresolved currency — manual review needed."
        )

    return {
        "total_discovered":       total,
        "in_triage":              triage,
        "pursuing":               pursuing,
        "watching":               watching,
        "on_hold":                on_hold,
        "deadline_urgent_count":  deadline_urgent_count,
        "drafting":               drafting,
        "draft_complete":         complete,
        "warnings":               warnings,
        "ts":                     datetime.now(timezone.utc).isoformat(),
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


# ── Grant management ───────────────────────────────────────────────────────────

_VALID_STATUSES = {
    "triage", "pursue", "pursuing", "watch", "drafting",
    "draft_complete", "submitted", "won", "passed", "auto_pass", "hold", "reported",
}


@app.post("/grants/manual")
async def add_manual_grant(
    body: ManualGrantRequest,
    _: None = Depends(verify_internal),
):
    """Save a manually entered grant URL — fetches content via Jina, detects themes,
    saves to grants_raw as an unprocessed entry ready for the analyst."""
    import hashlib
    import re
    from urllib.parse import urlparse

    import httpx

    from backend.db.mongo import get_db
    from backend.config.settings import get_settings

    url = body.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    url_hash = hashlib.md5(url.lower().encode()).hexdigest()
    db = get_db()
    existing = await db["grants_raw"].find_one({"url_hash": url_hash})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Already in database (added {str(existing.get('scraped_at', 'previously'))[:10]}).",
        )

    s = get_settings()
    raw_content = ""
    jina_url = f"https://r.jina.ai/{url}"
    headers: dict = {"X-Return-Format": "markdown", "X-With-Links-Summary": "false"}
    if s.jina_api_key:
        headers["Authorization"] = f"Bearer {s.jina_api_key}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            r = await client.get(jina_url, headers=headers)
            r.raise_for_status()
            raw_content = r.text.strip()[:80_000]
        except Exception:
            try:
                r2 = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                r2.raise_for_status()
                raw_content = r2.text[:60_000]
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Could not fetch URL: {e}")

    if len(raw_content) < 100:
        raise HTTPException(status_code=422, detail="Page returned too little content. Check the URL.")

    # Theme detection
    text_lower = (raw_content + " " + (body.title_override or "")).lower()
    themes: list[str] = []
    if any(k in text_lower for k in ["climate", "carbon", "net zero", "decarboni", "emission", "cdr", "mrv", "cleantech", "renewable"]):
        themes.append("climatetech")
    if any(k in text_lower for k in ["agri", "soil", "farm", "crop", "food", "land use", "regenerative"]):
        themes.append("agritech")
    if any(k in text_lower for k in ["artificial intelligence", "machine learning", "ai for", "deep learning", "nlp"]):
        themes.append("ai_for_sciences")
    if any(k in text_lower for k in ["earth science", "remote sensing", "satellite", "geology", "geospatial", "subsurface"]):
        themes.append("applied_earth_sciences")
    if any(k in text_lower for k in ["social impact", "community", "rural", "livelihood", "inclusive", "women", "development"]):
        themes.append("social_impact")
    if not themes:
        themes = ["climatetech"]

    # Title extraction
    title = (body.title_override or "").strip()
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", raw_content, re.IGNORECASE)
        if m:
            title = m.group(1).strip()[:120]
        else:
            for line in raw_content.split("\n"):
                line = line.lstrip("#").strip()
                if len(line) > 10:
                    title = line[:120]
                    break
        if not title:
            title = url

    # Funder extraction
    funder = (body.funder_override or "").strip()
    if not funder:
        try:
            domain = urlparse(url).netloc.replace("www.", "")
            funder = domain.split(".")[0].upper()
        except Exception:
            funder = "Unknown"

    doc = {
        "title": title,
        "url": url,
        "url_hash": url_hash,
        "funder": funder,
        "raw_content": raw_content,
        "themes_detected": themes,
        "source": "manual",
        "deadline": None,
        "max_funding": None,
        "currency": "USD",
        "eligibility_raw": "",
        "processed": False,
        "notes": body.notes or "",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    await db["grants_raw"].insert_one(doc)

    return {
        "success": True,
        "title": title,
        "funder": funder,
        "themes": themes,
        "chars_fetched": len(raw_content),
        "message": f"Saved '{title[:70]}' · {len(raw_content):,} chars · themes: {', '.join(themes)}",
    }


@app.post("/update/grant-status")
async def update_grant_status_api(
    body: UpdateGrantStatusRequest,
    _: None = Depends(verify_internal),
):
    """Move a grant to a new Kanban stage (called by the drag-and-drop UI)."""
    from backend.db.mongo import grants_scored
    from bson import ObjectId

    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status!r}")
    try:
        oid = ObjectId(body.grant_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid grant_id")

    result = await grants_scored().update_one(
        {"_id": oid},
        {"$set": {"status": body.status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Grant not found")
    return {"status": "updated", "grant_id": body.grant_id, "new_status": body.status}


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
