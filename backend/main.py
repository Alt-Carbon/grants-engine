"""AltCarbon Grants Intelligence — FastAPI Backend (Railway)

Endpoints:
  POST /cron/scout              ← Vercel cron every 48h
  POST /cron/knowledge-sync     ← Vercel cron daily
  POST /run/scout               ← Streamlit manual trigger
  POST /run/knowledge-sync      ← Streamlit manual trigger
  POST /run/sync-profile        ← Re-sync AltCarbon profile from Notion
  POST /resume/triage           ← Streamlit triage decision
  POST /resume/section-review   ← Streamlit section approve/revise
  POST /resume/start-draft      ← Streamlit start draft for a grant
  GET  /health
  GET  /status/pipeline
  GET  /status/thread/{thread_id}
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.db.mongo import ensure_indexes, get_db
from backend.graph.graph import get_graph
from backend.jobs.backfill_job import run_field_backfill, run_deduplication
from backend.jobs.knowledge_job import run_knowledge_sync
from backend.jobs.scout_job import run_scout_pipeline
from backend.jobs.scheduler import setup_scheduler, teardown_scheduler, get_scheduler_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Theme-specific sub-agent prompts ──────────────────────────────────────────

def _build_theme_agents() -> dict:
    """Build THEME_AGENTS from theme_profiles.py — single source of truth."""
    from backend.agents.drafter.theme_profiles import THEME_PROFILES

    _VOICE_MAP = {
        "climatetech": "Technical expert who translates complex climate science into compelling funder narratives. Precise but accessible.",
        "agritech": "Field-aware scientist who speaks both lab and farm. Emphasize real-world outcomes for farming communities.",
        "ai_for_sciences": "Applied ML researcher bridging algorithms and real-world environmental impact. Data-first storytelling.",
        "applied_earth_sciences": "Geoscientist who connects remote sensing data to actionable environmental insights. Systematic and thorough.",
        "social_impact": "Development practitioner who amplifies community voices. Warm but structured, balancing narrative with metrics.",
        "deeptech": "Deep tech strategist who bridges breakthrough science and market readiness. Confident, precise, IP-aware.",
    }
    _TEMP_MAP = {
        "climatetech": 0.4, "agritech": 0.4, "ai_for_sciences": 0.3,
        "applied_earth_sciences": 0.3, "social_impact": 0.5, "deeptech": 0.3,
    }

    agents = {}
    for key, profile in THEME_PROFILES.items():
        domain_terms_str = ", ".join(profile.get("domain_terms", [])[:8])
        strengths_str = "\n".join(f"- {s}" for s in profile.get("strengths", []))
        agents[key] = {
            "name": f"{profile['display_name']} Drafter",
            "temperature": _TEMP_MAP.get(key, 0.4),
            "tone": profile.get("tone", ""),
            "voice": _VOICE_MAP.get(key, ""),
            "expertise": (
                f"DOMAIN EXPERTISE — {profile['display_name']}:\n"
                f"Key terminology: {domain_terms_str}\n\n"
                f"STRENGTHS TO HIGHLIGHT:\n{strengths_str}"
            ),
        }
    return agents


THEME_AGENTS = _build_theme_agents()

# ── Full grant context builder ────────────────────────────────────────────────

def _build_grant_context(grant: dict) -> str:
    """Build a comprehensive text block from ALL grant fields for the drafter.

    Includes: basic info, deep analysis (eligibility, funding terms, evaluation
    criteria, application sections, key dates, past winners, strategic angle,
    contact, resources, red flags, application tips), scoring, and evidence.
    """
    parts: list[str] = []

    # ── Basic info ──
    title = grant.get("grant_name") or grant.get("title") or "Unknown"
    funder = grant.get("funder") or "Unknown"
    basics = [f"Grant: {title}", f"Funder: {funder}"]
    if grant.get("grant_type"):
        basics.append(f"Type: {grant['grant_type']}")
    if grant.get("amount"):
        basics.append(f"Funding amount: {grant['amount']}")
    if grant.get("max_funding_usd"):
        basics.append(f"Max funding (USD): ${grant['max_funding_usd']:,.0f}")
    if grant.get("currency"):
        basics.append(f"Currency: {grant['currency']}")
    if grant.get("deadline"):
        basics.append(f"Deadline: {grant['deadline']}")
    if grant.get("days_to_deadline") is not None:
        basics.append(f"Days to deadline: {grant['days_to_deadline']}")
    if grant.get("geography"):
        basics.append(f"Geography: {grant['geography']}")
    if grant.get("url"):
        basics.append(f"URL: {grant['url']}")
    if grant.get("application_url"):
        basics.append(f"Application URL: {grant['application_url']}")
    parts.append("GRANT OVERVIEW:\n" + "\n".join(basics))

    # ── Eligibility ──
    elig_parts = []
    if grant.get("eligibility"):
        elig_parts.append(f"Summary: {grant['eligibility']}")
    if grant.get("eligibility_details"):
        elig_parts.append(f"Details: {grant['eligibility_details']}")
    if elig_parts:
        parts.append("ELIGIBILITY:\n" + "\n".join(elig_parts))

    # ── About ──
    if grant.get("about_opportunity"):
        parts.append(f"ABOUT THE OPPORTUNITY:\n{grant['about_opportunity']}")
    if grant.get("application_process"):
        parts.append(f"APPLICATION PROCESS:\n{grant['application_process']}")

    # ── Scoring & analysis ──
    scores = grant.get("scores") or {}
    if scores:
        score_lines = [f"  {k}: {v}/10" for k, v in scores.items()]
        wt = grant.get("weighted_total")
        if wt is not None:
            score_lines.insert(0, f"  Overall score: {wt:.1f}/10")
        parts.append("AI SCORING:\n" + "\n".join(score_lines))
    if grant.get("rationale"):
        parts.append(f"SCORING RATIONALE:\n{grant['rationale']}")
    if grant.get("reasoning"):
        parts.append(f"STRATEGIC REASONING:\n{grant['reasoning']}")
    if grant.get("evidence_found"):
        parts.append("EVIDENCE FOUND (AltCarbon fit):\n" + "\n".join(f"  • {e}" for e in grant["evidence_found"]))
    if grant.get("evidence_gaps"):
        parts.append("EVIDENCE GAPS:\n" + "\n".join(f"  • {e}" for e in grant["evidence_gaps"]))
    if grant.get("red_flags"):
        parts.append("RED FLAGS:\n" + "\n".join(f"  ⚠ {r}" for r in grant["red_flags"]))
    if grant.get("funder_context"):
        parts.append(f"FUNDER BACKGROUND:\n{grant['funder_context']}")

    # ── Deep analysis ──
    da = grant.get("deep_analysis") or {}
    if not da:
        return "\n\n".join(parts)

    if da.get("opportunity_summary"):
        parts.append(f"OPPORTUNITY SUMMARY:\n{da['opportunity_summary']}")

    if da.get("strategic_angle"):
        parts.append(f"STRATEGIC ANGLE FOR ALTCARBON:\n{da['strategic_angle']}")

    # Key dates
    kd = da.get("key_dates") or {}
    if kd:
        date_lines = [f"  {k.replace('_', ' ').title()}: {v}" for k, v in kd.items() if v]
        if date_lines:
            parts.append("KEY DATES & TIMELINES:\n" + "\n".join(date_lines))

    # Requirements
    reqs = da.get("requirements") or {}
    if reqs:
        req_lines = []
        for doc in reqs.get("documents_needed") or []:
            req_lines.append(f"  • Document: {doc}")
        for att in reqs.get("attachments") or []:
            req_lines.append(f"  • Attachment: {att}")
        if reqs.get("submission_format"):
            req_lines.append(f"  Submission format: {reqs['submission_format']}")
        if reqs.get("submission_portal"):
            req_lines.append(f"  Submission portal: {reqs['submission_portal']}")
        if reqs.get("word_page_limits"):
            req_lines.append(f"  Word/page limits: {reqs['word_page_limits']}")
        if reqs.get("language"):
            req_lines.append(f"  Language: {reqs['language']}")
        if reqs.get("co_funding_required"):
            req_lines.append(f"  Co-funding: {reqs['co_funding_required']}")
        if req_lines:
            parts.append("APPLICATION REQUIREMENTS:\n" + "\n".join(req_lines))

    # Eligibility checklist
    ec = da.get("eligibility_checklist") or []
    if ec:
        ec_lines = []
        for item in ec:
            status = item.get("altcarbon_status", "?")
            icon = {"met": "✅", "likely_met": "🟡", "verify": "❓", "not_met": "❌"}.get(status, "•")
            ec_lines.append(f"  {icon} {item.get('criterion', '')} — {status} — {item.get('note', '')}")
        parts.append("ELIGIBILITY CHECKLIST (AltCarbon fit):\n" + "\n".join(ec_lines))

    # Evaluation criteria
    evc = da.get("evaluation_criteria") or []
    if evc:
        evc_lines = []
        for item in evc:
            w = f" ({item['weight']})" if item.get("weight") else ""
            evc_lines.append(f"  • {item.get('criterion', '')}{w}: {item.get('what_they_look_for', '')}")
        parts.append("EVALUATION CRITERIA (what reviewers look for):\n" + "\n".join(evc_lines))

    # Application sections
    asec = da.get("application_sections") or []
    if asec:
        asec_lines = []
        for item in asec:
            lim = f" [{item['limit']}]" if item.get("limit") else ""
            asec_lines.append(f"  • {item.get('section', '')}{lim}: {item.get('what_to_cover', '')}")
        parts.append("APPLICATION SECTIONS (expected structure):\n" + "\n".join(asec_lines))

    # Funding terms
    ft = da.get("funding_terms") or {}
    if ft:
        ft_lines = []
        if ft.get("disbursement_schedule"):
            ft_lines.append(f"  Disbursement: {ft['disbursement_schedule']}")
        if ft.get("reporting_requirements"):
            ft_lines.append(f"  Reporting: {ft['reporting_requirements']}")
        if ft.get("ip_ownership"):
            ft_lines.append(f"  IP ownership: {ft['ip_ownership']}")
        for cost in ft.get("permitted_costs") or []:
            ft_lines.append(f"  ✓ Permitted: {cost}")
        for cost in ft.get("excluded_costs") or []:
            ft_lines.append(f"  ✗ Excluded: {cost}")
        if ft.get("audit_requirement"):
            ft_lines.append(f"  Audit: {ft['audit_requirement']}")
        if ft_lines:
            parts.append("FUNDING TERMS:\n" + "\n".join(ft_lines))

    # Deep analysis red flags (may differ from top-level)
    da_rf = da.get("red_flags") or []
    if da_rf:
        parts.append("DEEP ANALYSIS RED FLAGS:\n" + "\n".join(f"  ⚠ {r}" for r in da_rf))

    # Application tips
    tips = da.get("application_tips") or []
    if tips:
        parts.append("APPLICATION TIPS:\n" + "\n".join(f"  💡 {t}" for t in tips))

    # Detailed application process
    if da.get("application_process_detailed"):
        parts.append(f"DETAILED APPLICATION PROCESS:\n{da['application_process_detailed']}")

    # Contact info
    contact = da.get("contact") or {}
    if any(contact.values()):
        c_lines = []
        if contact.get("name"):
            c_lines.append(f"  Name: {contact['name']}")
        if contact.get("email"):
            c_lines.append(f"  Email: {contact['email']}")
        for em in contact.get("emails_all") or []:
            if em != contact.get("email"):
                c_lines.append(f"  Also: {em}")
        if contact.get("phone"):
            c_lines.append(f"  Phone: {contact['phone']}")
        if contact.get("office"):
            c_lines.append(f"  Office: {contact['office']}")
        if c_lines:
            parts.append("CONTACT INFO:\n" + "\n".join(c_lines))

    # Resources
    res = da.get("resources") or {}
    if any(res.values()):
        res_lines = []
        for url in res.get("brochure_urls") or []:
            res_lines.append(f"  📄 Brochure/guideline: {url}")
        for url in res.get("info_session_urls") or []:
            res_lines.append(f"  🎥 Info session: {url}")
        for url in res.get("template_urls") or []:
            res_lines.append(f"  📋 Template: {url}")
        if res.get("faq_url"):
            res_lines.append(f"  ❓ FAQ: {res['faq_url']}")
        if res.get("guidelines_url"):
            res_lines.append(f"  📖 Guidelines: {res['guidelines_url']}")
        if res_lines:
            parts.append("RESOURCES & LINKS:\n" + "\n".join(res_lines))

    # Similar grants
    sg = da.get("similar_grants") or []
    if sg:
        parts.append("SIMILAR GRANTS / PREVIOUS ROUNDS:\n" + "\n".join(f"  • {g}" for g in sg))

    # Past winners analysis
    winners = da.get("winners") or []
    if winners:
        w_lines = []
        for w in winners:
            yr = f" ({w['year']})" if w.get("year") else ""
            sim = w.get("altcarbon_similarity", "")
            country = f" — {w.get('country', '')}" if w.get("country") else ""
            w_lines.append(
                f"  • {w.get('name', '?')}{yr}"
                f"{country}"
                f" [{sim} similarity]: {w.get('project_brief', '')}"
            )
        parts.append("PAST WINNERS:\n" + "\n".join(w_lines))
    if da.get("total_winners_found"):
        parts.append(f"Total past winners found: {da['total_winners_found']}")
    if da.get("altcarbon_comparable_count"):
        parts.append(f"AltCarbon-comparable winners: {da['altcarbon_comparable_count']}")
    if da.get("funder_pattern"):
        parts.append(f"FUNDER PATTERN (who gets funded):\n{da['funder_pattern']}")
    if da.get("altcarbon_fit_verdict"):
        parts.append(f"AltCarbon fit verdict: {da['altcarbon_fit_verdict']}")
    if da.get("strategic_note"):
        parts.append(f"STRATEGIC NOTE:\n{da['strategic_note']}")

    return "\n\n".join(parts)


# ── Scout job state (in-process flag) ─────────────────────────────────────────
_scout_running: bool = False
_scout_started_at: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite (primary state store)
    try:
        from backend.db.sqlite import ensure_db
        await ensure_db()
        logger.info("SQLite database initialized")
    except Exception as exc:
        logger.error("SQLite init failed (non-fatal): %s", exc)

    # Non-fatal startup: MongoDB kept for legacy/migration fallback
    try:
        await ensure_indexes()
        await _seed_default_agent_config()
        logger.info("AltCarbon Grants Intelligence backend started")
    except Exception as exc:
        logger.error("Startup DB init failed (non-fatal — check MONGODB_URI): %s", exc)

    # Start all MCP servers (non-fatal)
    try:
        from backend.integrations.mcp_hub import mcp_hub
        results = await mcp_hub.connect_all()
        connected = sum(1 for v in results.values() if v)
        logger.info("MCP Hub: %d/%d servers connected", connected, len(results))
    except Exception as exc:
        logger.warning("MCP Hub startup failed (non-fatal): %s", exc)

    # Start APScheduler (non-fatal)
    try:
        setup_scheduler()
    except Exception as exc:
        logger.warning("APScheduler startup failed (non-fatal): %s", exc)

    yield

    # Shutdown scheduler
    try:
        teardown_scheduler()
    except Exception:
        pass

    # Shutdown all MCP servers
    try:
        from backend.integrations.mcp_hub import mcp_hub
        await mcp_hub.disconnect_all()
    except Exception:
        pass

    # Close SQLite connection
    try:
        from backend.db.sqlite import close_conn
        await close_conn()
    except Exception:
        pass
    logger.info("Backend shutting down")


app = FastAPI(title="AltCarbon Grants Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── v2 API routes (Notion + SQLite, replaces direct MongoDB from frontend) ───
from backend.api.v2_routes import router as v2_router
app.include_router(v2_router, prefix="/api/v2")


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
    override_guardrails: bool = False
    override_reason: Optional[str] = None


class DrafterChatRequest(BaseModel):
    grant_id: str
    section_name: str
    message: str
    chat_history: Optional[list] = None  # [{role, content}, ...]
    model: Optional[str] = None  # "gpt-5.4" | "opus-4.6" — user-selectable
    user_email: Optional[str] = None  # authenticated user's email
    session_id: Optional[str] = None  # UUID per drafter session


class UpdateGrantStatusRequest(BaseModel):
    grant_id: str
    status: str


class ManualGrantRequest(BaseModel):
    url: str
    title_override: Optional[str] = ""
    funder_override: Optional[str] = ""
    notes: Optional[str] = ""
    auto_analyze: bool = True


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
            "theme_settings": {
                theme_key: {
                    "tone": agent["tone"],
                    "voice": agent["voice"],
                    "temperature": agent["temperature"],
                }
                for theme_key, agent in THEME_AGENTS.items()
            },
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


@app.get("/status/notion-mcp")
async def notion_mcp_status():
    """Check Notion MCP connection health."""
    from backend.integrations.notion_mcp import notion_mcp
    return await notion_mcp.health()


@app.post("/run/notion-mcp/reconnect")
async def reconnect_notion_mcp(
    _: None = Depends(verify_internal),
):
    """Force reconnect the Notion MCP server."""
    from backend.integrations.notion_mcp import notion_mcp
    await notion_mcp.disconnect()
    connected = await notion_mcp.connect()
    return {"status": "connected" if connected else "failed"}


# ── MCP Hub (all servers) ────────────────────────────────────────────────────

@app.get("/status/mcp")
async def mcp_hub_status():
    """Health check for all configured MCP servers."""
    from backend.integrations.mcp_hub import mcp_hub
    return await mcp_hub.health()


@app.get("/status/mcp/{server_name}/tools")
async def mcp_server_tools(server_name: str):
    """List all available tools for a specific MCP server."""
    from backend.integrations.mcp_hub import mcp_hub
    conn = mcp_hub.get_server(server_name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
    if not conn.connected:
        raise HTTPException(status_code=503, detail=f"MCP server '{server_name}' not connected")
    tools = await conn.list_tools_full()
    return {"server": server_name, "tools": tools}


@app.post("/run/mcp/{server_name}/reconnect")
async def reconnect_mcp_server(
    server_name: str,
    _: None = Depends(verify_internal),
):
    """Force reconnect a specific MCP server."""
    from backend.integrations.mcp_hub import mcp_hub
    connected = await mcp_hub.connect_one(server_name)
    return {"server": server_name, "status": "connected" if connected else "failed"}


@app.post("/run/mcp/reconnect-all")
async def reconnect_all_mcp(
    _: None = Depends(verify_internal),
):
    """Force reconnect all MCP servers."""
    from backend.integrations.mcp_hub import mcp_hub
    await mcp_hub.disconnect_all()
    results = await mcp_hub.connect_all()
    return {
        "results": {name: ("connected" if ok else "failed") for name, ok in results.items()},
    }


# ── Skills Registry ──────────────────────────────────────────────────────────

@app.get("/status/skills")
async def skills_status():
    """Full skill registry status — all skills, providers, and availability."""
    from backend.skills import skills
    return await skills.health()


@app.get("/status/skills/{agent_name}")
async def agent_skills(agent_name: str):
    """List skills available to a specific pipeline agent."""
    from backend.skills import skills
    manifest = skills.agent_manifest(agent_name)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"No skills found for agent '{agent_name}'")
    return {"agent": agent_name, "skills": manifest}


@app.get("/status/knowledge-sources")
async def knowledge_sources_status():
    """Return all Notion workspace pages and MCP connection status."""
    from backend.integrations.notion_mcp import notion_mcp
    from backend.knowledge.sync_profile import (
        NOTION_PAGES, SECTION_TITLES, PROFILE_PATH,
    )

    health = await notion_mcp.health()
    indexed_ids = set(NOTION_PAGES.values())

    # Fetch workspace pages via MCP search
    workspace_pages: list = []
    if notion_mcp.connected:
        try:
            # Search with broad queries to discover workspace content
            seen_ids: set = set()
            search_queries = [
                "Alt Carbon", "carbon", "climate", "project", "report",
                "grant", "studio", "team", "plan", "data", "science",
                "biochar", "darjeeling", "ERW", "MRV", "investor",
                "budget", "design", "brand", "policy", "sales",
            ]
            for query in search_queries:
                try:
                    raw = await notion_mcp._call_tool("API-post-search", {
                        "query": query,
                        "page_size": 100,
                    })
                    results = []
                    if isinstance(raw, dict):
                        results = raw.get("results", [])
                    elif isinstance(raw, list):
                        results = raw

                    for r in results:
                        if not isinstance(r, dict):
                            continue
                        page_id = r.get("id", "")
                        if not page_id or page_id in seen_ids:
                            continue
                        seen_ids.add(page_id)

                        obj_type = r.get("object", "page")
                        # Extract title
                        title = ""
                        props = r.get("properties", {})
                        for prop in props.values():
                            if isinstance(prop, dict) and prop.get("type") == "title":
                                title_arr = prop.get("title", [])
                                if title_arr and isinstance(title_arr, list):
                                    title = "".join(
                                        t.get("plain_text", "")
                                        for t in title_arr
                                        if isinstance(t, dict)
                                    )
                                break
                        if not title:
                            title = r.get("title", "Untitled")
                            if isinstance(title, list):
                                title = "".join(
                                    t.get("plain_text", "")
                                    for t in title
                                    if isinstance(t, dict)
                                ) or "Untitled"

                        # Get icon
                        icon = ""
                        icon_obj = r.get("icon")
                        if isinstance(icon_obj, dict):
                            if icon_obj.get("type") == "emoji":
                                icon = icon_obj.get("emoji", "")

                        clean_id = page_id.replace("-", "")
                        workspace_pages.append({
                            "page_id": page_id,
                            "title": title,
                            "type": obj_type,
                            "icon": icon,
                            "indexed": page_id in indexed_ids,
                            "notion_url": f"https://notion.so/{clean_id}",
                            "last_edited": r.get("last_edited_time", ""),
                        })
                except Exception as e:
                    logger.warning("Workspace search query '%s' failed: %s", query, e)
        except Exception as e:
            logger.warning("Workspace page discovery failed: %s", e)

    # Sort: indexed first, then by last_edited descending
    workspace_pages.sort(
        key=lambda p: (not p["indexed"], p.get("last_edited", "") or ""),
        reverse=False,
    )
    # Re-sort: indexed first, then most recently edited
    workspace_pages.sort(key=lambda p: (not p["indexed"],), reverse=False)

    # Profile sync time
    last_synced = None
    try:
        if PROFILE_PATH.exists():
            last_synced = datetime.fromtimestamp(
                PROFILE_PATH.stat().st_mtime, tz=timezone.utc
            ).isoformat()
    except Exception:
        pass

    indexed_count = sum(1 for p in workspace_pages if p["indexed"])

    return {
        "mcp_status": health.get("status", "unknown"),
        "mcp_tools": health.get("tools"),
        "sources": workspace_pages,
        "total_sources": len(workspace_pages),
        "indexed_count": indexed_count,
        "last_synced": last_synced,
    }


@app.get("/status/documents-list")
async def documents_list_status():
    """Return articulation documents from the Documents List database with sync status."""
    import re
    from backend.integrations.notion_mcp import notion_mcp
    from backend.integrations.notion_config import DOCUMENTS_LIST_DS
    from backend.db.mongo import knowledge_chunks

    if not notion_mcp.connected:
        return {"documents": [], "error": "MCP not connected"}

    try:
        rows = await notion_mcp.query_data_source(DOCUMENTS_LIST_DS, limit=100)
    except Exception as e:
        logger.warning("Failed to query Documents List: %s", e)
        return {"documents": [], "error": str(e)}

    # Fetch sync status from MongoDB knowledge_chunks collection
    col = knowledge_chunks()
    sync_stats: dict = {}
    try:
        pipeline = [
            {"$match": {"source": "documents_list"}},
            {"$group": {
                "_id": "$source_id",
                "chunks": {"$sum": 1},
                "total_chars": {"$sum": {"$strLenCP": "$content"}},
                "last_synced": {"$max": "$last_synced"},
            }},
        ]
        async for row in col.aggregate(pipeline):
            sync_stats[row["_id"]] = {
                "chunks": row["chunks"],
                "total_chars": row["total_chars"],
                "last_synced": row["last_synced"],
            }
    except Exception as e:
        logger.debug("Failed to fetch sync stats: %s", e)

    documents = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        doc_name = row.get("Document Name", "")
        # Extract Google Drive URL from markdown link: [Title](url)
        drive_url = None
        display_name = doc_name
        link_match = re.search(r'\[([^\]]+)\]\((https://docs\.google\.com/[^)]+)\)', doc_name)
        if link_match:
            display_name = link_match.group(1)
            drive_url = link_match.group(2)
        elif "docs.google.com" in doc_name:
            url_match = re.search(r'(https://docs\.google\.com/\S+)', doc_name)
            if url_match:
                drive_url = url_match.group(1)

        # Parse focus areas
        focus_raw = row.get("Focus Area", "")
        focus_areas = []
        if isinstance(focus_raw, str) and focus_raw:
            focus_areas = [f.strip() for f in focus_raw.split(",") if f.strip()]
        elif isinstance(focus_raw, list):
            focus_areas = focus_raw

        page_id = row.get("url", "").rstrip("/").split("/")[-1]
        stats = sync_stats.get(page_id, {})

        documents.append({
            "page_id": page_id,
            "name": display_name.strip() if display_name else "Untitled",
            "status": row.get("Status", "Not started"),
            "focus_areas": focus_areas,
            "drive_url": drive_url,
            "support_from": row.get("Need support from", ""),
            "notion_url": row.get("url", ""),
            "sync_chunks": stats.get("chunks", 0),
            "sync_chars": stats.get("total_chars", 0),
            "last_synced": stats.get("last_synced"),
        })

    # Sort: In progress / Review first, then Not started
    status_order = {"In progress": 0, "Review Pending": 1, "Review Completed": 2, "Done": 3, "Not started": 4}
    documents.sort(key=lambda d: status_order.get(d["status"], 5))

    synced_count = sum(1 for d in documents if d["sync_chunks"] > 0)

    return {
        "documents": documents,
        "total": len(documents),
        "synced": synced_count,
        "articulation_structure": [
            "Problem Statement",
            "Existing Literature",
            "Solution (Overview, Done so far, Needs to be done)",
            "Why we are best suited",
            "Academic & Industry Collaborators",
            "Outputs",
            "Outcomes",
            "Project Plan & Timelines",
            "Cobenefits",
            "Unit Economics",
            "Pricing",
            "Budget Breakdown",
        ],
    }


@app.get("/status/table-of-content")
async def table_of_content_status():
    """Return knowledge sources from the Table of Content (Grants DB) with sync status."""
    import re
    import httpx
    from backend.config.settings import get_settings
    from backend.integrations.notion_config import TABLE_OF_CONTENT_DS, TOC_THEME_MAP
    from backend.db.mongo import knowledge_chunks

    s = get_settings()
    if not s.notion_token:
        return {"sources": [], "error": "NOTION_TOKEN not set"}

    # Query the Table of Content database via Notion REST API
    headers = {
        "Authorization": f"Bearer {s.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    rows = []
    try:
        cursor = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                body: dict = {"page_size": 100}
                if cursor:
                    body["start_cursor"] = cursor
                r = await client.post(
                    f"https://api.notion.com/v1/databases/{TABLE_OF_CONTENT_DS}/query",
                    headers=headers,
                    json=body,
                )
                if r.status_code != 200:
                    return {"sources": [], "error": f"Notion API {r.status_code}"}
                data = r.json()
                rows.extend(data.get("results", []))
                cursor = data.get("next_cursor")
                if not cursor:
                    break
    except Exception as e:
        logger.warning("Failed to query Table of Content: %s", e)
        return {"sources": [], "error": str(e)}

    # Fetch sync stats from MongoDB
    col = knowledge_chunks()
    sync_stats: dict = {}
    try:
        pipeline = [
            {"$match": {"source_registry": "table_of_content"}},
            {"$group": {
                "_id": "$source_id",
                "chunks": {"$sum": 1},
                "total_chars": {"$sum": {"$strLenCP": "$content"}},
                "last_synced": {"$max": "$last_synced"},
            }},
        ]
        async for row in col.aggregate(pipeline):
            sync_stats[row["_id"]] = {
                "chunks": row["chunks"],
                "total_chars": row["total_chars"],
                "last_synced": row["last_synced"],
            }
    except Exception as e:
        logger.debug("Failed to fetch ToC sync stats: %s", e)

    sources = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        props = row.get("properties", {})

        # Title
        doc_name = "".join(
            t.get("plain_text", "")
            for t in props.get("Document Name", {}).get("title", [])
        ).strip()
        display_name = re.sub(r'\*\*|<[^>]+>', '', doc_name).strip() or "Untitled"

        # Content type (select)
        content_type = (props.get("Content type", {}).get("select") or {}).get("name", "")

        # URL
        url_field = props.get("URL", {}).get("url") or ""

        # Notion Page ID (rich_text)
        notion_page_id_raw = "".join(
            t.get("plain_text", "")
            for t in props.get("Notion Page ID", {}).get("rich_text", [])
        ).strip()

        # Extra page url
        extra_url = props.get("Extra page url", {}).get("url") or ""

        # Content info (multi_select)
        content_info = [
            opt.get("name", "")
            for opt in props.get("Content info", {}).get("multi_select", [])
        ]
        is_main = "Main-source" in content_info
        themes = [TOC_THEME_MAP[t] for t in content_info if t in TOC_THEME_MAP]

        # Parse Notion Page ID
        notion_page_id = ""
        if notion_page_id_raw:
            id_match = re.search(r'([a-f0-9]{32})', notion_page_id_raw.replace("-", ""))
            if id_match:
                notion_page_id = id_match.group(1)

        doc_id = notion_page_id or row.get("id", "").replace("-", "")
        stats = sync_stats.get(doc_id, {})

        sources.append({
            "id": doc_id,
            "name": display_name,
            "content_type": content_type,
            "is_main_source": is_main,
            "themes": themes,
            "url": url_field,
            "notion_page_id": notion_page_id,
            "extra_url": extra_url,
            "sync_chunks": stats.get("chunks", 0),
            "sync_chars": stats.get("total_chars", 0),
            "last_synced": stats.get("last_synced"),
        })

    # Sort: main sources first, then by name
    sources.sort(key=lambda s: (0 if s["is_main_source"] else 1, s["name"]))

    return {
        "sources": sources,
        "total": len(sources),
        "main_sources": sum(1 for s in sources if s["is_main_source"]),
        "synced": sum(1 for s in sources if s["sync_chunks"] > 0),
    }


@app.get("/status/api-health")
async def api_health_status():
    """Check credit/quota health of external APIs (Tavily, Exa, Perplexity, Cloudflare BR)."""
    from backend.utils.parsing import api_health
    return {
        "services": api_health.get_status(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


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


# ── Scheduler endpoints ───────────────────────────────────────────────────────

@app.get("/status/scheduler")
async def scheduler_status():
    """Return APScheduler jobs and next run times."""
    return get_scheduler_status()


@app.post("/scheduler/pause")
async def pause_scheduler(_: None = Depends(verify_internal)):
    """Pause all scheduled jobs."""
    from backend.jobs.scheduler import scheduler
    scheduler.pause()
    return {"status": "paused"}


@app.post("/scheduler/resume")
async def resume_scheduler(_: None = Depends(verify_internal)):
    """Resume all scheduled jobs."""
    from backend.jobs.scheduler import scheduler
    scheduler.resume()
    return {"status": "resumed"}


# ── Notification endpoints ────────────────────────────────────────────────────

@app.get("/notifications")
async def list_notifications(
    limit: int = 30,
    unread_only: bool = False,
):
    """List recent notifications (newest first)."""
    db = get_db()
    query: dict = {}
    if unread_only:
        query["read"] = False
    docs = await db["notifications"].find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"notifications": docs}


@app.get("/notifications/count")
async def notification_count():
    """Return unread notification count (for bell badge)."""
    db = get_db()
    count = await db["notifications"].count_documents({"read": False})
    return {"unread": count}


@app.post("/notifications/read")
async def mark_notifications_read(body: dict):
    """Mark specific notifications as read. Body: { ids: [str] }"""
    from bson import ObjectId
    db = get_db()
    ids = body.get("ids", [])
    if ids:
        obj_ids = [ObjectId(i) for i in ids]
        await db["notifications"].update_many(
            {"_id": {"$in": obj_ids}},
            {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}},
        )
    return {"status": "ok", "marked": len(ids)}


@app.post("/notifications/read-all")
async def mark_all_notifications_read():
    """Mark all notifications as read."""
    db = get_db()
    result = await db["notifications"].update_many(
        {"read": False},
        {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "ok", "marked": result.modified_count}


# ── Notion Webhook ──────────────────────────────────────────────────────────

@app.post("/webhooks/notion")
async def notion_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Receive Notion webhook events for real-time knowledge sync.

    Handles:
      - Verification handshake (returns verification_token)
      - page.content_updated events → selective single-document re-sync
    """
    from backend.config.settings import get_settings
    from backend.integrations.notion_webhooks import (
        validate_signature, parse_event, get_known_source_ids,
    )

    body = await request.body()
    payload = json.loads(body) if body else {}

    # ── Verification handshake ──
    if payload.get("type") == "url_verification":
        token = payload.get("verification_token", "")
        logger.info("Notion webhook verification handshake received")
        return {"verification_token": token}

    # ── Signature validation ──
    s = get_settings()
    if s.notion_webhook_secret:
        signature = request.headers.get("x-notion-signature", "")
        if not validate_signature(body, signature, s.notion_webhook_secret):
            logger.warning("Notion webhook: invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    # ── Event handling ──
    event_type, page_id = parse_event(payload)
    logger.info("Notion webhook: type=%s page_id=%s", event_type, page_id)

    if event_type == "page.content_updated" and page_id:
        # Check if this page is in our known knowledge sources
        known_ids = await get_known_source_ids()
        if page_id in known_ids:
            logger.info("Notion webhook: queuing re-sync for known page %s", page_id)

            async def _resync():
                try:
                    agent = _get_brain_agent()
                    result = await agent.sync_single_document(page_id)
                    logger.info("Webhook re-sync result: %s", result)
                    # Notify on successful sync
                    if result.get("status") == "synced":
                        try:
                            from backend.notifications.hub import notify
                            await notify(
                                event_type="knowledge_webhook_sync",
                                title="Knowledge updated (webhook)",
                                body=f"{result.get('source_title', page_id)}: {result.get('chunks_updated', 0)} chunks",
                                action_url="/knowledge",
                                metadata=result,
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.error("Webhook re-sync failed for %s: %s", page_id, e)

            background_tasks.add_task(_resync)
        else:
            logger.debug("Notion webhook: ignoring unknown page %s", page_id)

    return {"status": "ok"}


def _get_brain_agent():
    """Helper to instantiate CompanyBrainAgent with current settings."""
    from backend.agents.company_brain import CompanyBrainAgent
    from backend.config.settings import get_settings
    s = get_settings()
    return CompanyBrainAgent(
        notion_token=s.notion_token,
        google_refresh_token=s.google_refresh_token,
        google_client_id=s.google_client_id,
        google_client_secret=s.google_client_secret,
    )


# ── Knowledge Pending Changes ────────────────────────────────────────────────

@app.get("/status/knowledge-pending")
async def knowledge_pending():
    """Return pages where Notion last_edited_time > last_synced in MongoDB."""
    import httpx
    from backend.config.settings import get_settings
    from backend.integrations.notion_config import TABLE_OF_CONTENT_DS
    from backend.db.mongo import knowledge_chunks

    s = get_settings()
    if not s.notion_token:
        return {"pending": [], "count": 0, "error": "NOTION_TOKEN not set"}

    col = knowledge_chunks()

    # Get all known sources with their last_synced times
    sync_times: dict = {}
    try:
        pipeline = [
            {"$match": {"source_id": {"$exists": True}}},
            {"$group": {
                "_id": "$source_id",
                "last_synced": {"$max": "$last_synced"},
                "source_title": {"$first": "$source_title"},
            }},
        ]
        async for row in col.aggregate(pipeline):
            sync_times[str(row["_id"])] = {
                "last_synced": row.get("last_synced"),
                "source_title": row.get("source_title", ""),
            }
    except Exception as e:
        logger.warning("Failed to fetch sync times: %s", e)
        return {"pending": [], "count": 0, "error": str(e)}

    # Query Table of Content for page metadata (last_edited_time)
    headers = {
        "Authorization": f"Bearer {s.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    pending = []
    try:
        rows = []
        cursor = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                body: dict = {"page_size": 100}
                if cursor:
                    body["start_cursor"] = cursor
                r = await client.post(
                    f"https://api.notion.com/v1/databases/{TABLE_OF_CONTENT_DS}/query",
                    headers=headers,
                    json=body,
                )
                if r.status_code != 200:
                    break
                data = r.json()
                rows.extend(data.get("results", []))
                cursor = data.get("next_cursor")
                if not cursor:
                    break

        import re
        for row in rows:
            if not isinstance(row, dict):
                continue
            page_edited = row.get("last_edited_time", "")
            props = row.get("properties", {})

            # Extract Notion Page ID
            notion_page_id_raw = "".join(
                t.get("plain_text", "")
                for t in props.get("Notion Page ID", {}).get("rich_text", [])
            ).strip()
            notion_page_id = ""
            if notion_page_id_raw:
                id_match = re.search(r'([a-f0-9]{32})', notion_page_id_raw.replace("-", ""))
                if id_match:
                    notion_page_id = id_match.group(1)

            if not notion_page_id:
                continue

            # Title
            doc_name = "".join(
                t.get("plain_text", "")
                for t in props.get("Document Name", {}).get("title", [])
            ).strip()
            display_name = re.sub(r'\*\*|<[^>]+>', '', doc_name).strip() or "Untitled"

            # Compare times
            sync_info = sync_times.get(notion_page_id, {})
            last_synced = sync_info.get("last_synced", "")

            if page_edited and last_synced and page_edited > last_synced:
                pending.append({
                    "page_id": notion_page_id,
                    "title": display_name,
                    "edited_at": page_edited,
                    "last_synced": last_synced,
                })

    except Exception as e:
        logger.warning("Failed to check pending changes: %s", e)

    return {"pending": pending, "count": len(pending)}


# ── Cron endpoints (kept for external triggers / backward compat) ─────────────

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
            result = await run_scout_pipeline()
            # Emit scout completion notification
            try:
                from backend.notifications.hub import notify_scout_complete
                await notify_scout_complete(
                    new_grants=result.get("new_grants", 0) if isinstance(result, dict) else 0,
                    total_found=result.get("total_found", 0) if isinstance(result, dict) else 0,
                )
            except Exception:
                logger.debug("Scout notification failed", exc_info=True)
        except Exception as e:
            try:
                from backend.notifications.hub import notify_agent_error
                await notify_agent_error("scout", str(e))
            except Exception:
                pass
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


@app.post("/run/sync-profile")
async def manual_sync_profile(
    _: None = Depends(verify_internal),
):
    """Re-sync the AltCarbon static profile from Notion pages.

    Fetches key Notion pages via the API and rebuilds
    backend/knowledge/altcarbon_profile.md so agents have fresh context.
    """
    from backend.knowledge.sync_profile import sync_profile_from_notion
    result = await sync_profile_from_notion()
    return result


@app.post("/run/sync-past-grants")
async def sync_past_grants(
    _: None = Depends(verify_internal),
):
    """Ingest past grant PDFs from /past_grants/ into MongoDB + Pinecone.

    Extracts text via pdftotext, chunks, tags with Haiku, and upserts.
    Tagged as doc_type='past_grant_application' for drafter style examples.
    """
    from backend.config.settings import get_settings
    from backend.agents.company_brain import CompanyBrainAgent
    s = get_settings()
    agent = CompanyBrainAgent(
        notion_token=s.notion_token,
        google_refresh_token=s.google_refresh_token,
        google_client_id=s.google_client_id,
        google_client_secret=s.google_client_secret,
    )
    result = await agent.sync_past_grants()
    return result


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
    force: bool = False,
    source: str = "mongo",
    status_filter: str = "",
    _: None = Depends(verify_internal),
):
    """Run the Analyst on grants.

    - source=mongo (default): reads from grants_raw MongoDB collection.
    - source=notion: reads grants from Notion Grant Pipeline DB.
    - status_filter: when source=notion, filter by Notion status (e.g. "Shortlisted").
      If empty, fetches all grants from Notion.
    - force=true: re-scores ALL grants, ignoring processed/already-scored flags.
    """
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

            s = get_settings()
            from backend.agents.analyst import DEFAULT_WEIGHTS
            weights = DEFAULT_WEIGHTS
            min_funding = s.min_grant_funding

            # Try to load agent config from MongoDB (may fail during migration)
            try:
                from backend.db.mongo import agent_config
                cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
                weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
                min_funding = cfg_doc.get("min_funding", s.min_grant_funding)
            except Exception:
                logger.debug("Agent config from MongoDB unavailable, using defaults")

            # Fetch grants from the appropriate source
            if source == "notion":
                from backend.integrations.notion_data import (
                    query_grants_by_status,
                    query_all_grants,
                )
                if status_filter:
                    raw_docs = await query_grants_by_status(status_filter)
                    logger.info(
                        "Analyst (Notion source, status=%s): %d grants found",
                        status_filter, len(raw_docs),
                    )
                else:
                    raw_docs = await query_all_grants()
                    logger.info("Analyst (Notion source, all): %d grants found", len(raw_docs))
            else:
                from backend.db.mongo import grants_raw
                if force:
                    raw_docs = await grants_raw().find({}).to_list(length=5000)
                    logger.info("Analyst FORCE run: %d total grants found", len(raw_docs))
                else:
                    raw_docs = await grants_raw().find({"processed": False}).to_list(length=2000)
                    logger.info("Analyst run: %d unprocessed grants found", len(raw_docs))

            agent = AnalystAgent(
                perplexity_api_key=s.perplexity_api_key,
                gateway_api_key=s.ai_gateway_api_key,
                gateway_url=s.ai_gateway_url,
                weights=weights,
                min_funding=min_funding,
            )
            scored = await agent.run(raw_docs, force=force)
            scored_count = len(scored)
            logger.info("Analyst run: %d grants scored (source=%s)", scored_count, source)

            # Write run audit entry
            try:
                from backend.db.mongo import get_db
                db = get_db()
                await db["audit_logs"].insert_one({
                    "event": "analyst_run_complete",
                    "scored_count": scored_count,
                    "input_count": len(raw_docs),
                    "source": source,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                logger.debug("Audit log write failed", exc_info=True)

            # Emit analyst completion notification
            try:
                from backend.notifications.hub import notify_analyst_complete
                triage_count = sum(1 for g in scored if g.get("status") == "triage")
                pursue_count = sum(1 for g in scored if g.get("recommended_action") == "pursue")
                await notify_analyst_complete(
                    scored_count=scored_count,
                    triage_count=triage_count,
                    pursue_count=pursue_count,
                )
                # Notify for individual high-score grants
                from backend.notifications.hub import notify_high_score_grant
                for g in scored:
                    wt = g.get("weighted_total", 0)
                    if wt >= 7.0:
                        await notify_high_score_grant(
                            grant_name=g.get("grant_name") or g.get("title") or "Unknown",
                            grant_id=str(g.get("_id", "")),
                            score=wt,
                            funder=g.get("funder", ""),
                        )
            except Exception:
                logger.debug("Analyst notification failed", exc_info=True)
        except Exception as e:
            logger.error("Analyst run failed: %s", e)
            try:
                import traceback as _tb
                from backend.integrations.notion_sync import log_error
                await log_error(
                    agent="analyst",
                    error=e,
                    tb=_tb.format_exc(),
                    severity="Critical",
                )
            except Exception:
                logger.debug("Notion error sync skipped (analyst job)", exc_info=True)
            try:
                from backend.notifications.hub import notify_agent_error
                await notify_agent_error("analyst", str(e))
            except Exception:
                pass
        finally:
            _analyst_running = False
            _analyst_started_at = None

    background_tasks.add_task(_run)
    return {"status": "analyst_job_started", "source": source, "started_at": _analyst_started_at}


# ── Resume endpoints ───────────────────────────────────────────────────────────

# /resume/triage — REMOVED: replaced by Notion webhook/polling (Phase 3)
# Humans now triage directly in Notion by changing Status to "Pursue".
# The scheduler polls every 5 min and triggers the drafting pipeline.


@app.post("/resume/section-review")
async def resume_section_review(
    body: SectionReviewRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Human approved or requested revision on a section. Resume drafter."""
    async def _resume():
        try:
            from langgraph.types import Command

            graph = get_graph()
            config = {"configurable": {"thread_id": body.thread_id}}
            update: dict = {"section_review_decision": body.action}
            if body.edited_content:
                update["section_edited_content"] = body.edited_content
            if body.instructions:
                update["section_revision_instructions"] = {body.section_name: body.instructions}
            if body.critique:
                update["section_critiques"] = {body.section_name: body.critique}

            # Resume the interrupted drafter using Command — this properly
            # resumes from interrupt_before and injects state updates.
            await graph.ainvoke(Command(resume=True, update=update), config=config)
        except Exception as e:
            logger.error("Section review resume failed for thread %s: %s", body.thread_id, e, exc_info=True)

    background_tasks.add_task(_resume)
    return {"status": "section_review_resumed", "thread_id": body.thread_id}


@app.post("/drafter/chat")
async def drafter_chat(
    body: DrafterChatRequest,
    _: None = Depends(verify_internal),
):
    """Direct chat endpoint for the Drafter UI.

    Takes the user's message (grant question, revision instructions, etc.)
    along with grant context, and returns an LLM-generated response.
    This bypasses LangGraph for a synchronous chat experience.
    """
    from backend.db.mongo import grants_scored
    from backend.utils.llm import chat as llm_chat, DRAFTER_DEFAULT, resolve_drafter_model
    from bson import ObjectId

    # Resolve user-selected model (gpt-5.4 / opus-4.6)
    drafter_model = resolve_drafter_model(body.model) if body.model else DRAFTER_DEFAULT

    # Load grant context
    grant = {}
    try:
        grant = await grants_scored().find_one({"_id": ObjectId(body.grant_id)}) or {}
    except Exception:
        pass

    grant_title = grant.get("grant_name") or grant.get("title") or "Unknown Grant"
    funder = grant.get("funder") or "Unknown"

    # Build comprehensive grant context from ALL available fields
    grant_deep = _build_grant_context(grant)

    # Resolve theme-specific sub-agent
    themes_detected = grant.get("themes_detected") or []
    primary_theme = themes_detected[0] if themes_detected else "climatetech"
    agent_info = THEME_AGENTS.get(primary_theme, THEME_AGENTS["climatetech"])
    agent_name = agent_info["name"]
    agent_theme = primary_theme

    # Load company context — multiple layers for completeness

    # Layer 1: Static profile (always available, has core company facts)
    static_profile = ""
    try:
        from backend.agents.company_brain import _load_static_profile
        static_profile = _load_static_profile() or ""
    except Exception:
        pass

    # Layer 2: Knowledge chunks from MongoDB (theme-filtered)
    chunks_text = ""
    try:
        from backend.db.mongo import get_db
        db = get_db()
        theme_filter = {"themes": {"$in": themes_detected}} if themes_detected else {}
        chunks = await db["knowledge_chunks"].find(theme_filter).limit(10).to_list(length=10)
        if not chunks and themes_detected:
            chunks = await db["knowledge_chunks"].find({}).limit(10).to_list(length=10)
        chunks_text = "\n".join(c.get("content", "") for c in chunks if c.get("content"))[:3000]
    except Exception:
        pass

    # Layer 3: Notion MCP live search (if connected)
    notion_context = ""
    try:
        from backend.integrations.notion_mcp import notion_mcp
        if notion_mcp.connected:
            # Build smart search queries from the user message
            # Start with the raw message, then extract key terms
            search_queries = [body.message[:80]]

            # Extract individual meaningful words (3+ chars) for broader search
            import re
            stop_words = {
                "the", "and", "for", "are", "but", "not", "you", "all",
                "can", "had", "her", "was", "one", "our", "out", "has",
                "what", "when", "who", "how", "list", "show", "tell",
                "give", "find", "get", "about", "from", "with", "this",
                "that", "have", "will", "been", "they", "them", "their",
                "does", "which", "would", "could", "should", "into",
                "also", "just", "than", "then", "some", "each", "make",
            }
            words = re.findall(r"[a-zA-Z]{3,}", body.message.lower())
            key_words = [w for w in words if w not in stop_words]
            # Search for individual key terms too
            for kw in key_words[:3]:
                search_queries.append(kw)

            # Add broader company-related searches for org questions
            org_keywords = {"team", "teams", "people", "staff", "member",
                           "founder", "leadership", "organization", "structure"}
            if org_keywords & set(words):
                search_queries.extend(["introducing", "about", "team", "Alt Carbon"])

            if grant_title and grant_title != "Unknown Grant":
                search_queries.append(grant_title[:80])
            if body.section_name:
                search_queries.append(body.section_name[:60])

            # Deduplicate queries while preserving order
            seen_queries: set = set()
            unique_queries = []
            for sq in search_queries:
                sq_lower = sq.lower().strip()
                if sq_lower and sq_lower not in seen_queries:
                    seen_queries.add(sq_lower)
                    unique_queries.append(sq)

            seen_page_ids: set = set()

            # For org/team questions, directly fetch the "Introducing Alt Carbon" page
            if org_keywords & set(words):
                intro_page_id = "24750d0e-c20e-806c-b3a4-c7eae131c6e2"
                try:
                    intro_content = await notion_mcp.fetch_page(intro_page_id)
                    if intro_content:
                        seen_page_ids.add(intro_page_id)
                        notion_context += f"\n---\n[Introducing Alt Carbon]\n{intro_content[:5000]}"
                except Exception:
                    pass

            for sq in unique_queries:
                try:
                    results = await notion_mcp.search(sq)
                    for r in results[:5]:
                        pid = r.get("id", "")
                        if pid in seen_page_ids:
                            continue
                        seen_page_ids.add(pid)
                        page = await notion_mcp.fetch_page(pid)
                        if page:
                            # Extract title from properties
                            ptitle = ""
                            props = r.get("properties", {})
                            for p in props.values():
                                if isinstance(p, dict) and p.get("type") == "title":
                                    ta = p.get("title", [])
                                    ptitle = "".join(
                                        t.get("plain_text", "")
                                        for t in ta
                                        if isinstance(t, dict)
                                    )
                                    break
                            notion_context += f"\n---\n[{ptitle or 'Notion Page'}]\n{page[:3000]}"
                            if len(notion_context) > 16000:
                                break
                except Exception:
                    continue
                if len(notion_context) > 16000:
                    break
    except Exception:
        pass

    # Combine context in priority order
    context_parts = []
    if static_profile:
        context_parts.append(f"[COMPANY PROFILE]\n{static_profile[:6000]}")
    if chunks_text:
        context_parts.append(f"[KNOWLEDGE CHUNKS]\n{chunks_text}")
    if notion_context:
        context_parts.append(f"[LIVE NOTION]\n{notion_context[:12000]}")
    company_context = "\n\n".join(context_parts)

    # Build chat history for context
    history_block = ""
    if body.chat_history:
        history_lines = []
        for msg in body.chat_history[-6:]:  # last 6 messages for context
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")[:500]
            history_lines.append(f"[{role}]: {content}")
        if history_lines:
            history_block = "CONVERSATION HISTORY:\n" + "\n".join(history_lines) + "\n\n"

    # Track which sources were loaded
    sources_used = []
    if static_profile:
        sources_used.append("company_profile")
    if chunks_text:
        sources_used.append("knowledge_chunks")
    if notion_context:
        sources_used.append("notion_live")
    if grant_deep:
        sources_used.append("grant_deep_analysis")

    # Load DB overrides for drafter config (theme-specific tone/voice/temperature)
    from backend.db.mongo import agent_config
    drafter_cfg = await agent_config().find_one({"agent": "drafter"}) or {}
    theme_overrides = (drafter_cfg.get("theme_settings") or {}).get(primary_theme) or {}
    agent_tone = theme_overrides.get("tone") or agent_info.get("tone", "")
    agent_voice = theme_overrides.get("voice") or agent_info.get("voice", "")
    agent_temp = theme_overrides.get("temperature") or agent_info.get("temperature", 0.4)
    custom_instructions = drafter_cfg.get("custom_instructions") or ""

    system_prompt = f"""You are {agent_name}, a grant writing assistant for AltCarbon, a climate technology company.
You help draft responses to grant application questions and requirements.

TONE: {agent_tone}
VOICE: {agent_voice}

GRANT: {grant_title}
FUNDER: {funder}

{agent_info["expertise"]}

{f"GRANT DETAILS:{chr(10)}{grant_deep}" if grant_deep else ""}

{f"COMPANY KNOWLEDGE:{chr(10)}{company_context}" if company_context else ""}

The COMPANY PROFILE section contains verified facts about AltCarbon — always use these for founding details, team, address, buyers, and technology specs. Never use placeholders like [YEAR] or [ADDRESS] when this data is available. The LIVE NOTION section has the latest information from the company workspace.

{f"CUSTOM INSTRUCTIONS:{chr(10)}{custom_instructions}{chr(10)}" if custom_instructions else ""}INSTRUCTIONS:
- Answer the user's question or draft the requested section
- Adopt the TONE and VOICE described above consistently throughout your response
- Be specific and concrete — use the company knowledge when available
- Only flag [EVIDENCE NEEDED: brief description] for information truly absent from all provided knowledge sources
- Do NOT invent statistics, team names, or technical claims
- Format your response in clear markdown with headings, bold, and lists where appropriate
- Stay focused on what the user asked

SOURCE ATTRIBUTION:
At the end of your response, add a "---" divider followed by a small "Sources" section listing which knowledge sources you drew from. Use these labels:
- "Company Profile" — if you used facts from the [COMPANY PROFILE] section
- "Knowledge Base" — if you used facts from the [KNOWLEDGE CHUNKS] section
- "Notion (Live)" — if you used facts from the [LIVE NOTION] section
- "Grant Analysis" — if you used facts from the GRANT DETAILS section
Only list sources you actually referenced. Format as a compact comma-separated line, e.g.: **Sources:** Company Profile, Grant Analysis"""

    prompt = f"""{history_block}USER MESSAGE:
{body.message}

Write a well-structured response in markdown format:"""

    try:
        content = await llm_chat(
            prompt, model=drafter_model, max_tokens=2048, system=system_prompt,
            temperature=agent_temp,
        )
        content = content.strip()

        import re
        word_count = len(content.split())
        evidence_gaps = re.findall(r"\[EVIDENCE NEEDED:[^\]]+\]", content)

        return {
            "revised_content": content,
            "word_count": word_count,
            "evidence_gaps": evidence_gaps,
            "section_name": body.section_name,
            "agent_name": agent_name,
            "agent_theme": agent_theme,
            "sources_used": sources_used,
            "agent_temperature": agent_temp,
            "model": drafter_model,
        }
    except Exception as e:
        logger.error("Drafter chat failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Drafter Chat — Streaming SSE endpoint
# ---------------------------------------------------------------------------

@app.post("/drafter/chat/stream")
async def drafter_chat_stream(
    body: DrafterChatRequest,
    _: None = Depends(verify_internal),
):
    """Streaming version of /drafter/chat — sends Server-Sent Events.

    Events:
      event: status   data: {"step": "...", "detail": "..."}
      event: token    data: {"content": "..."}
      event: metadata data: {"word_count": N, "sources_used": [...], ...}
      event: done     data: {}
      event: error    data: {"message": "..."}
    """
    from starlette.responses import StreamingResponse
    from backend.db.mongo import grants_scored, agent_config as agent_config_col
    from backend.utils.llm import chat_stream, DRAFTER_DEFAULT, resolve_drafter_model
    from bson import ObjectId

    # Resolve user-selected model
    drafter_model = resolve_drafter_model(body.model) if body.model else DRAFTER_DEFAULT

    async def generate():
        try:
            # ── Step 1: Load grant context ──
            yield _sse("status", {"step": "Loading grant context", "detail": body.grant_id})

            grant = {}
            try:
                grant = await grants_scored().find_one({"_id": ObjectId(body.grant_id)}) or {}
            except Exception:
                pass

            grant_title = grant.get("grant_name") or grant.get("title") or "Unknown Grant"
            funder = grant.get("funder") or "Unknown"

            # Build comprehensive grant context from ALL available fields
            grant_deep = _build_grant_context(grant)

            themes_detected = grant.get("themes_detected") or []
            primary_theme = themes_detected[0] if themes_detected else "climatetech"
            agent_info = THEME_AGENTS.get(primary_theme, THEME_AGENTS["climatetech"])
            agent_name = agent_info["name"]
            agent_theme = primary_theme

            # ── Step 2: Load all knowledge sources in parallel ──
            yield _sse("status", {"step": "Searching knowledge base", "detail": "company profile + knowledge chunks + Notion"})

            import asyncio as aio

            async def _load_profile():
                try:
                    from backend.agents.company_brain import _load_static_profile
                    return _load_static_profile() or ""
                except Exception:
                    return ""

            async def _load_chunks():
                try:
                    from backend.db.mongo import get_db
                    db = get_db()
                    theme_filter = {"themes": {"$in": themes_detected}} if themes_detected else {}
                    chunks = await db["knowledge_chunks"].find(theme_filter).limit(10).to_list(length=10)
                    if not chunks and themes_detected:
                        chunks = await db["knowledge_chunks"].find({}).limit(10).to_list(length=10)
                    return "\n".join(c.get("content", "") for c in chunks if c.get("content"))[:3000]
                except Exception:
                    return ""

            async def _load_notion():
                try:
                    from backend.integrations.notion_mcp import notion_mcp
                    if not notion_mcp.connected:
                        return ""
                    import re
                    notion_ctx = ""
                    search_queries = [body.message[:80]]
                    stop_words = {
                        "the", "and", "for", "are", "but", "not", "you", "all",
                        "can", "had", "her", "was", "one", "our", "out", "has",
                        "what", "when", "who", "how", "list", "show", "tell",
                        "give", "find", "get", "about", "from", "with", "this",
                        "that", "have", "will", "been", "they", "them", "their",
                        "does", "which", "would", "could", "should", "into",
                        "also", "just", "than", "then", "some", "each", "make",
                    }
                    words = re.findall(r"[a-zA-Z]{3,}", body.message.lower())
                    key_words = [w for w in words if w not in stop_words]
                    for kw in key_words[:3]:
                        search_queries.append(kw)
                    if grant_title and grant_title != "Unknown Grant":
                        search_queries.append(grant_title[:80])
                    if body.section_name:
                        search_queries.append(body.section_name[:60])

                    seen_queries, unique_queries = set(), []
                    for sq in search_queries:
                        sq_lower = sq.lower().strip()
                        if sq_lower and sq_lower not in seen_queries:
                            seen_queries.add(sq_lower)
                            unique_queries.append(sq)

                    seen_page_ids = set()
                    org_keywords = {"team", "teams", "people", "staff", "member",
                                   "founder", "leadership", "organization", "structure"}
                    if org_keywords & set(words):
                        intro_page_id = "24750d0e-c20e-806c-b3a4-c7eae131c6e2"
                        try:
                            intro_content = await notion_mcp.fetch_page(intro_page_id)
                            if intro_content:
                                seen_page_ids.add(intro_page_id)
                                notion_ctx += f"\n---\n[Introducing Alt Carbon]\n{intro_content[:5000]}"
                        except Exception:
                            pass

                    for sq in unique_queries:
                        try:
                            results = await notion_mcp.search(sq)
                            for r in results[:5]:
                                pid = r.get("id", "")
                                if pid in seen_page_ids:
                                    continue
                                seen_page_ids.add(pid)
                                page = await notion_mcp.fetch_page(pid)
                                if page:
                                    ptitle = ""
                                    props = r.get("properties", {})
                                    for p in props.values():
                                        if isinstance(p, dict) and p.get("type") == "title":
                                            ta = p.get("title", [])
                                            ptitle = "".join(t.get("plain_text", "") for t in ta if isinstance(t, dict))
                                            break
                                    notion_ctx += f"\n---\n[{ptitle or 'Notion Page'}]\n{page[:3000]}"
                                    if len(notion_ctx) > 16000:
                                        break
                        except Exception:
                            continue
                        if len(notion_ctx) > 16000:
                            break
                    return notion_ctx
                except Exception:
                    return ""

            static_profile, chunks_text, notion_context = await aio.gather(
                _load_profile(), _load_chunks(), _load_notion()
            )

            # Report sources loaded
            sources_used = []
            if static_profile:
                sources_used.append("company_profile")
            if chunks_text:
                sources_used.append("knowledge_chunks")
            if notion_context:
                sources_used.append("notion_live")
            if grant_deep:
                sources_used.append("grant_deep_analysis")

            yield _sse("status", {"step": "Context ready", "detail": f"{len(sources_used)} sources loaded"})

            # Combine context
            context_parts = []
            if static_profile:
                context_parts.append(f"[COMPANY PROFILE]\n{static_profile[:6000]}")
            if chunks_text:
                context_parts.append(f"[KNOWLEDGE CHUNKS]\n{chunks_text}")
            if notion_context:
                context_parts.append(f"[LIVE NOTION]\n{notion_context[:12000]}")
            company_context = "\n\n".join(context_parts)

            # Build chat history
            history_block = ""
            if body.chat_history:
                history_lines = []
                for msg in body.chat_history[-6:]:
                    role = msg.get("role", "user").upper()
                    content = msg.get("content", "")[:500]
                    history_lines.append(f"[{role}]: {content}")
                if history_lines:
                    history_block = "CONVERSATION HISTORY:\n" + "\n".join(history_lines) + "\n\n"

            # Load drafter config overrides
            drafter_cfg = await agent_config_col().find_one({"agent": "drafter"}) or {}
            theme_overrides = (drafter_cfg.get("theme_settings") or {}).get(primary_theme) or {}
            agent_tone = theme_overrides.get("tone") or agent_info.get("tone", "")
            agent_voice = theme_overrides.get("voice") or agent_info.get("voice", "")
            agent_temp = theme_overrides.get("temperature") or agent_info.get("temperature", 0.4)
            custom_instructions = drafter_cfg.get("custom_instructions") or ""

            system_prompt = f"""You are {agent_name}, a grant writing assistant for AltCarbon, a climate technology company.
You help draft responses to grant application questions and requirements.

TONE: {agent_tone}
VOICE: {agent_voice}

GRANT: {grant_title}
FUNDER: {funder}

{agent_info["expertise"]}

{f"GRANT DETAILS:{chr(10)}{grant_deep}" if grant_deep else ""}

{f"COMPANY KNOWLEDGE:{chr(10)}{company_context}" if company_context else ""}

The COMPANY PROFILE section contains verified facts about AltCarbon — always use these for founding details, team, address, buyers, and technology specs. Never use placeholders like [YEAR] or [ADDRESS] when this data is available. The LIVE NOTION section has the latest information from the company workspace.

{f"CUSTOM INSTRUCTIONS:{chr(10)}{custom_instructions}{chr(10)}" if custom_instructions else ""}INSTRUCTIONS:
- Answer the user's question or draft the requested section
- Adopt the TONE and VOICE described above consistently throughout your response
- Be specific and concrete — use the company knowledge when available
- Only flag [EVIDENCE NEEDED: brief description] for information truly absent from all provided knowledge sources
- Do NOT invent statistics, team names, or technical claims
- Format your response in clear markdown with headings, bold, and lists where appropriate
- Stay focused on what the user asked

SOURCE ATTRIBUTION:
At the end of your response, add a "---" divider followed by a small "Sources" section listing which knowledge sources you drew from. Use these labels:
- "Company Profile" — if you used facts from the [COMPANY PROFILE] section
- "Knowledge Base" — if you used facts from the [KNOWLEDGE CHUNKS] section
- "Notion (Live)" — if you used facts from the [LIVE NOTION] section
- "Grant Analysis" — if you used facts from the GRANT DETAILS section
Only list sources you actually referenced. Format as a compact comma-separated line, e.g.: **Sources:** Company Profile, Grant Analysis"""

            user_prompt = f"""{history_block}USER MESSAGE:
{body.message}

Write a well-structured response in markdown format:"""

            # ── Step 3: Stream LLM response ──
            yield _sse("status", {"step": "Drafting response", "detail": agent_name})

            full_content = ""
            async for chunk in chat_stream(
                user_prompt, model=drafter_model, max_tokens=2048,
                system=system_prompt, temperature=agent_temp,
            ):
                full_content += chunk
                yield _sse("token", {"content": chunk})

            # ── Step 4: Send metadata ──
            import re
            word_count = len(full_content.split())
            evidence_gaps = re.findall(r"\[EVIDENCE NEEDED:[^\]]+\]", full_content)

            yield _sse("metadata", {
                "word_count": word_count,
                "evidence_gaps": evidence_gaps,
                "section_name": body.section_name,
                "agent_name": agent_name,
                "agent_theme": agent_theme,
                "sources_used": sources_used,
                "agent_temperature": agent_temp,
                "model": drafter_model,
            })

            yield _sse("done", {})

        except Exception as e:
            logger.error("Drafter stream failed: %s", e, exc_info=True)
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Intelligence Brief — full grant dossier as structured JSON
# ---------------------------------------------------------------------------

class IntelligenceBriefRequest(BaseModel):
    grant_id: str


class PushDraftToNotionRequest(BaseModel):
    grant_id: str
    pipeline_id: Optional[str] = None


@app.post("/drafter/push-to-notion")
async def push_draft_to_notion(
    body: PushDraftToNotionRequest,
    _: None = Depends(verify_internal),
):
    """Push the latest complete draft to Notion as a rich page."""
    from bson import ObjectId
    from backend.db.mongo import grant_drafts, grants_scored
    from backend.integrations.notion_sync import push_complete_draft_to_notion

    # Fetch latest draft from MongoDB
    query: dict = {"grant_id": body.grant_id}
    if body.pipeline_id:
        query["pipeline_id"] = body.pipeline_id
    draft = await grant_drafts().find_one(query, sort=[("version", -1)])
    if not draft:
        return {"success": False, "error": "No draft found for this grant"}

    # Fetch grant info for context
    grant = {}
    try:
        grant = await grants_scored().find_one({"_id": ObjectId(body.grant_id)}) or {}
    except Exception:
        pass

    grant_name = grant.get("grant_name") or grant.get("title") or "Unknown Grant"
    funder = grant.get("funder", "")
    deadline = grant.get("deadline", "")
    if hasattr(deadline, "strftime"):
        deadline = deadline.strftime("%Y-%m-%d")

    page_id = await push_complete_draft_to_notion(
        grant_id=body.grant_id,
        grant_name=grant_name,
        sections=draft.get("sections", {}),
        version=draft.get("version", 1),
        evidence_gaps=draft.get("evidence_gaps_all"),
        funder=funder,
        deadline=str(deadline) if deadline else "",
    )

    if page_id:
        notion_url = f"https://notion.so/{page_id.replace('-', '')}"
        return {"success": True, "notion_page_id": page_id, "notion_url": notion_url}
    return {"success": False, "error": "Notion push failed — check server logs"}


@app.post("/drafter/intelligence-brief")
async def intelligence_brief(
    body: IntelligenceBriefRequest,
    _: None = Depends(verify_internal),
):
    """Return a comprehensive grant intelligence brief as structured JSON.

    The frontend renders this into a downloadable .docx.
    Contains: overview, eligibility, funding terms, evaluation criteria,
    application structure, key dates, past winners, strategic analysis,
    contact info, resources, and AI scoring.
    """
    from backend.db.mongo import grants_scored
    from bson import ObjectId

    grant = {}
    try:
        grant = await grants_scored().find_one({"_id": ObjectId(body.grant_id)}) or {}
    except Exception:
        raise HTTPException(status_code=404, detail="Grant not found")

    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    da = grant.get("deep_analysis") or {}
    contact = da.get("contact") or {}
    resources = da.get("resources") or {}
    ft = da.get("funding_terms") or {}
    kd = da.get("key_dates") or {}
    reqs = da.get("requirements") or {}

    return {
        "overview": {
            "grant_name": grant.get("grant_name") or grant.get("title") or "",
            "funder": grant.get("funder") or "",
            "grant_type": grant.get("grant_type") or "",
            "amount": grant.get("amount") or "",
            "max_funding_usd": grant.get("max_funding_usd"),
            "currency": grant.get("currency") or "",
            "deadline": str(grant.get("deadline") or ""),
            "days_to_deadline": grant.get("days_to_deadline"),
            "deadline_urgent": grant.get("deadline_urgent", False),
            "geography": grant.get("geography") or "",
            "url": grant.get("url") or "",
            "application_url": grant.get("application_url") or "",
            "about_opportunity": grant.get("about_opportunity") or da.get("opportunity_summary") or "",
            "themes_detected": grant.get("themes_detected") or [],
        },
        "eligibility": {
            "summary": grant.get("eligibility") or "",
            "details": grant.get("eligibility_details") or "",
            "checklist": da.get("eligibility_checklist") or [],
        },
        "scoring": {
            "weighted_total": grant.get("weighted_total"),
            "scores": grant.get("scores") or {},
            "recommended_action": grant.get("recommended_action") or "",
            "rationale": grant.get("rationale") or "",
            "reasoning": grant.get("reasoning") or "",
            "evidence_found": grant.get("evidence_found") or [],
            "evidence_gaps": grant.get("evidence_gaps") or [],
            "red_flags": (grant.get("red_flags") or []) + (da.get("red_flags") or []),
        },
        "key_dates": kd,
        "requirements": {
            "documents_needed": reqs.get("documents_needed") or [],
            "attachments": reqs.get("attachments") or [],
            "submission_format": reqs.get("submission_format") or "",
            "submission_portal": reqs.get("submission_portal") or "",
            "word_page_limits": reqs.get("word_page_limits") or "",
            "language": reqs.get("language") or "",
            "co_funding_required": reqs.get("co_funding_required") or "",
        },
        "evaluation_criteria": da.get("evaluation_criteria") or [],
        "application_sections": da.get("application_sections") or [],
        "application_process": grant.get("application_process") or da.get("application_process_detailed") or "",
        "funding_terms": {
            "disbursement_schedule": ft.get("disbursement_schedule") or "",
            "reporting_requirements": ft.get("reporting_requirements") or "",
            "ip_ownership": ft.get("ip_ownership") or "",
            "permitted_costs": ft.get("permitted_costs") or [],
            "excluded_costs": ft.get("excluded_costs") or [],
            "audit_requirement": ft.get("audit_requirement") or "",
        },
        "strategy": {
            "strategic_angle": da.get("strategic_angle") or "",
            "application_tips": da.get("application_tips") or [],
            "funder_context": grant.get("funder_context") or "",
            "funder_pattern": da.get("funder_pattern") or "",
            "altcarbon_fit_verdict": da.get("altcarbon_fit_verdict") or "",
            "strategic_note": da.get("strategic_note") or "",
        },
        "past_winners": {
            "winners": da.get("winners") or [],
            "total_winners_found": da.get("total_winners_found") or 0,
            "altcarbon_comparable_count": da.get("altcarbon_comparable_count") or 0,
        },
        "contact": {
            "name": contact.get("name") or "",
            "email": contact.get("email") or "",
            "emails_all": contact.get("emails_all") or [],
            "phone": contact.get("phone") or "",
            "office": contact.get("office") or "",
        },
        "resources": {
            "brochure_urls": resources.get("brochure_urls") or [],
            "info_session_urls": resources.get("info_session_urls") or [],
            "template_urls": resources.get("template_urls") or [],
            "faq_url": resources.get("faq_url") or "",
            "guidelines_url": resources.get("guidelines_url") or "",
        },
        "similar_grants": da.get("similar_grants") or [],
    }


# ---------------------------------------------------------------------------
# Drafter Chat History — persist & load chat per pipeline
# ---------------------------------------------------------------------------

class ChatHistorySaveRequest(BaseModel):
    pipeline_id: str
    grant_id: str
    sections: dict  # { section_name: [ {role, content, timestamp, metadata?} ] }
    user_email: Optional[str] = None  # authenticated user's email
    session_id: Optional[str] = None  # UUID per drafter session


@app.get("/drafter/chat-history/{pipeline_id}")
async def get_chat_history(
    pipeline_id: str,
    user_email: Optional[str] = None,
    _: None = Depends(verify_internal),
):
    """Load persisted chat history for a pipeline (optionally scoped to user)."""
    from backend.db.mongo import drafter_chat_history

    query: dict = {"pipeline_id": pipeline_id}
    if user_email:
        query["user_email"] = user_email

    doc = await drafter_chat_history().find_one(query)
    if not doc:
        return {"pipeline_id": pipeline_id, "sections": {}, "user_email": user_email}
    doc.pop("_id", None)
    return doc


@app.put("/drafter/chat-history")
async def save_chat_history(
    body: ChatHistorySaveRequest,
    _: None = Depends(verify_internal),
):
    """Save/upsert chat history for a pipeline (scoped to user if email provided)."""
    from backend.db.mongo import drafter_chat_history

    # Build query key — scoped to user if email provided
    query: dict = {"pipeline_id": body.pipeline_id}
    if body.user_email:
        query["user_email"] = body.user_email

    update_doc: dict = {
        "pipeline_id": body.pipeline_id,
        "grant_id": body.grant_id,
        "sections": body.sections,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.user_email:
        update_doc["user_email"] = body.user_email
    if body.session_id:
        update_doc["session_id"] = body.session_id

    await drafter_chat_history().update_one(
        query,
        {"$set": update_doc},
        upsert=True,
    )
    return {"status": "saved", "pipeline_id": body.pipeline_id, "user_email": body.user_email}


@app.delete("/drafter/chat-history/{pipeline_id}/{section_name}")
async def clear_section_history(
    pipeline_id: str,
    section_name: str,
    user_email: Optional[str] = None,
    _: None = Depends(verify_internal),
):
    """Clear chat history for a single section within a pipeline."""
    from backend.db.mongo import drafter_chat_history

    query: dict = {"pipeline_id": pipeline_id}
    if user_email:
        query["user_email"] = user_email

    await drafter_chat_history().update_one(
        query,
        {"$unset": {f"sections.{section_name}": ""}},
    )
    return {"status": "cleared", "pipeline_id": pipeline_id, "section_name": section_name}


async def _predraft_validate(grant: dict) -> dict | None:
    """Layer 1 deterministic pre-draft checks. Returns error dict or None if OK."""
    from backend.agents.analyst import parse_deadline

    # 1. Status — reject if auto_pass, pass, or watch
    status = (grant.get("status") or "").lower()
    blocked_statuses = {"auto_pass", "pass", "watch"}
    if status in blocked_statuses:
        return {"check": "status", "reason": f"Grant status is '{status}' — not eligible for drafting"}

    # 2. Deadline freshness
    deadline_str = grant.get("deadline")
    if deadline_str:
        deadline_dt = parse_deadline(deadline_str)
        if deadline_dt and deadline_dt < datetime.now(timezone.utc):
            return {"check": "deadline", "reason": f"Grant deadline {deadline_dt.strftime('%Y-%m-%d')} has expired"}

    # 3. Score floor
    scores = grant.get("scores") or {}
    weighted_total = grant.get("weighted_total") or scores.get("weighted_total", 0)
    if isinstance(weighted_total, (int, float)) and weighted_total < 4.0:
        return {"check": "score_floor", "reason": f"Weighted score {weighted_total:.1f} is below minimum 4.0"}

    # 4. Theme floor
    theme_alignment = scores.get("theme_alignment", 0)
    if isinstance(theme_alignment, (int, float)) and theme_alignment <= 2:
        return {"check": "theme_floor", "reason": f"Theme alignment score {theme_alignment} is too low (≤2)"}

    return None


@app.post("/resume/start-draft")
async def start_draft(
    body: StartDraftRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Start a new draft pipeline for an already-triaged grant."""
    from backend.db.mongo import grants_pipeline, grants_scored
    from bson import ObjectId

    grant = await grants_scored().find_one({"_id": ObjectId(body.grant_id)})
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    # ── Layer 1: Deterministic pre-draft validation ──────────────────────────
    if not body.override_guardrails:
        validation_error = await _predraft_validate(grant)
        if validation_error:
            # Update grant status
            try:
                await grants_scored().update_one(
                    {"_id": ObjectId(body.grant_id)},
                    {"$set": {"status": "guardrail_rejected"}},
                )
            except Exception:
                pass

            # Fire notification
            try:
                from backend.notifications.hub import notify
                grant_title = grant.get("title") or grant.get("grant_name") or body.grant_id
                await notify(
                    event_type="guardrail_rejected",
                    title=f"Pre-draft blocked: {grant_title[:60]}",
                    body=validation_error["reason"][:200],
                    priority="high",
                    metadata={"grant_id": body.grant_id, "check": validation_error["check"]},
                )
            except Exception:
                pass

            raise HTTPException(
                status_code=422,
                detail={
                    "error": "predraft_validation_failed",
                    "check": validation_error["check"],
                    "reason": validation_error["reason"],
                    "grant_id": body.grant_id,
                },
            )
    else:
        logger.info("start_draft: guardrails overridden for grant %s — reason: %s",
                     body.grant_id, body.override_reason or "none given")

    thread_id = body.thread_id or f"draft_{body.grant_id[:8]}_{uuid.uuid4().hex[:6]}"
    run_id = str(uuid.uuid4())

    # Create pipeline record
    pipeline_id = None
    try:
        result = await grants_pipeline().insert_one({
            "grant_id": body.grant_id,
            "thread_id": thread_id,
            "status": "drafting",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "draft_started_at": datetime.now(timezone.utc).isoformat(),
            "current_draft_version": 0,
            "final_draft_url": None,
            "override_guardrails": body.override_guardrails,
            "override_reason": body.override_reason,
        })
        pipeline_id = str(result.inserted_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def _run_draft():
        graph = get_graph()
        config = {"configurable": {"thread_id": thread_id}}

        # Inject state as if human_triage just ran with "pursue" decision.
        # This skips scout/analyst/notify_triage entirely and resumes from
        # the next node after human_triage → company_brain.
        triage_state = {
            "raw_grants": [],
            "scored_grants": [],
            "human_triage_decision": "pursue",
            "selected_grant_id": body.grant_id,
            "triage_notes": None,
            "grant_requirements": None,
            "grant_raw_doc": None,
            "company_profile": None,
            "company_context": None,
            "style_examples": None,
            "style_examples_loaded": False,
            "draft_guardrail_result": None,
            "override_guardrails": body.override_guardrails,
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
            "audit_log": [{
                "node": "human_triage",
                "ts": datetime.now(timezone.utc).isoformat(),
                "decision": "pursue",
                "grant_id": body.grant_id,
                "override_guardrails": body.override_guardrails,
                "override_reason": body.override_reason,
            }],
        }

        # Write state as if human_triage just completed → graph resumes at company_brain
        await graph.aupdate_state(config, triage_state, as_node="human_triage")

        # First resume: runs company_brain → grant_reader → draft_guardrail → pauses at interrupt_before drafter
        # (If guardrail fails, routes to pipeline_update → END instead)
        await graph.ainvoke(None, config=config)

        # Second resume: runs drafter (writes first section) → pauses at next interrupt_before drafter
        # Only reaches here if guardrail passed
        await graph.ainvoke(None, config=config)

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


# ── Notion webhook endpoints (for Notion → Backend automation) ──────────────


class NotionTriageWebhookRequest(BaseModel):
    """Payload from Notion automation when a grant's Status property changes."""
    mongo_id: Optional[str] = None     # MongoDB _id (legacy)
    notion_page_id: Optional[str] = None  # Notion page ID (primary)
    new_status: str                    # "Pursue" | "Watch" | "Pass"
    notes: Optional[str] = None


class NotionSectionReviewWebhookRequest(BaseModel):
    """Payload from Notion automation when a Draft Section's Status changes."""
    mongo_grant_id: str                # MongoDB _id of the grant
    section_name: str                  # Name of the section being reviewed
    action: str                        # "approve" | "revise"
    revision_notes: Optional[str] = None


@app.post("/api/notion-webhook/triage")
async def notion_webhook_triage(
    body: NotionTriageWebhookRequest,
    background_tasks: BackgroundTasks,
):
    """Notion automation fires this when a grant Status changes to Pursue.

    Directly triggers Graph B (drafting pipeline) for the grant.
    No longer needs to find a paused LangGraph thread — Notion is primary.
    """
    import uuid as _uuid
    from backend.graph.graph import get_drafting_graph

    status_map = {
        "Pursue": "pursue", "pursue": "pursue",
        "Watch": "watch", "watch": "watch",
        "Pass": "pass", "pass": "pass",
    }
    decision = status_map.get(body.new_status)
    if not decision:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.new_status}'. Expected Pursue, Watch, or Pass.",
        )

    # For "pursue" — trigger the drafting pipeline
    if decision == "pursue" and body.notion_page_id:
        thread_id = f"draft-webhook-{body.notion_page_id}-{_uuid.uuid4().hex[:8]}"

        async def _start_drafting():
            try:
                graph = get_drafting_graph()
                initial_state = {
                    "selected_notion_page_id": body.notion_page_id,
                    "selected_grant_id": body.mongo_id,
                    "notion_page_ids": {},
                    "raw_grants": [],
                    "scored_grants": [],
                    "human_triage_decision": "pursue",
                    "triage_notes": body.notes,
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
                    "run_id": _uuid.uuid4().hex,
                    "errors": [],
                    "audit_log": [],
                }
                await graph.ainvoke(
                    initial_state,
                    config={"configurable": {"thread_id": thread_id}},
                )
            except Exception as e:
                logger.error("Notion webhook drafting failed: %s", e)

        background_tasks.add_task(_start_drafting)
        return {
            "status": "drafting_triggered",
            "decision": decision,
            "notion_page_id": body.notion_page_id,
            "thread_id": thread_id,
        }

    return {
        "status": "status_noted",
        "decision": decision,
        "notion_page_id": body.notion_page_id,
            "note": "No active LangGraph thread found. Grant status updated in MongoDB.",
        }


@app.post("/api/notion-webhook/section-review")
async def notion_webhook_section_review(
    body: NotionSectionReviewWebhookRequest,
    background_tasks: BackgroundTasks,
):
    """Notion automation fires this when a Draft Section status changes to
    Approved or Needs Revision.

    Finds the matching LangGraph thread and resumes the drafter checkpoint.
    """
    from backend.db.mongo import grants_pipeline

    action = body.action.lower()
    if action not in ("approve", "revise"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{body.action}'. Expected 'approve' or 'revise'.",
        )

    # Find the drafting pipeline for this grant
    pipeline = await grants_pipeline().find_one(
        {"grant_id": body.mongo_grant_id, "status": "drafting"},
        sort=[("started_at", -1)],
    )
    if not pipeline:
        raise HTTPException(
            status_code=404,
            detail=f"No active drafting pipeline found for grant {body.mongo_grant_id}",
        )

    thread_id = pipeline["thread_id"]

    async def _resume():
        try:
            graph = get_graph()
            config = {"configurable": {"thread_id": thread_id}}
            update: dict = {"section_review_decision": action}
            if body.revision_notes and action == "revise":
                update["section_revision_instructions"] = {body.section_name: body.revision_notes}
            await graph.ainvoke(update, config=config)
        except Exception as e:
            logger.error("Notion webhook section review resume failed: %s", e)

    background_tasks.add_task(_resume)
    logger.info(
        "Notion webhook: section '%s' %s for grant %s (thread %s)",
        body.section_name, action, body.mongo_grant_id, thread_id,
    )
    return {
        "status": "section_review_resumed",
        "action": action,
        "section_name": body.section_name,
        "grant_id": body.mongo_grant_id,
        "thread_id": thread_id,
    }


@app.post("/admin/notion-backfill")
async def admin_notion_backfill(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
    setup_views: bool = False,
):
    """Backfill all scored grants to Notion with full data + rich page body.

    Query params:
        setup_views: If true, also create Kanban and Table views in Notion.
    """
    from backend.db.mongo import grants_scored
    from backend.integrations.notion_sync import (
        backfill_grants,
        ensure_grant_pipeline_schema,
        setup_grant_pipeline_views,
    )

    async def _backfill():
        # Step 1: Ensure all new DB properties exist
        await ensure_grant_pipeline_schema()

        # Step 2: Optionally create views
        if setup_views:
            await setup_grant_pipeline_views()

        # Step 3: Backfill all grants with full data
        cursor = grants_scored().find({}).sort("weighted_total", -1)
        all_grants = await cursor.to_list(length=2000)
        count = await backfill_grants(all_grants)
        logger.info("Notion backfill complete: %d grants synced with full data", count)

    background_tasks.add_task(_backfill)
    return {"status": "notion_backfill_started", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/admin/notion-dedup")
async def admin_notion_dedup(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Remove duplicate pages in Notion Grant Pipeline (same MongoDB ID)."""
    from backend.integrations.notion_sync import dedup_notion_pipeline

    async def _dedup():
        result = await dedup_notion_pipeline()
        logger.info("Notion dedup complete: %s", result)

    background_tasks.add_task(_dedup)
    return {"status": "notion_dedup_started", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/admin/notion-reverse-sync")
async def admin_notion_reverse_sync(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_internal),
):
    """Pull status/priority changes from Notion back into MongoDB.

    Reads all grants from the Notion Grant Pipeline, compares Status and
    Priority with MongoDB, and updates any that differ. Safe to run repeatedly.
    """
    from backend.integrations.notion_sync import reverse_sync_from_notion

    async def _reverse_sync():
        result = await reverse_sync_from_notion()
        logger.info("Notion reverse sync: %s", result)

    background_tasks.add_task(_reverse_sync)
    return {"status": "notion_reverse_sync_started", "ts": datetime.now(timezone.utc).isoformat()}


# ── Grant management ───────────────────────────────────────────────────────────

_VALID_STATUSES = {
    "triage", "pursue", "pursuing", "watch", "drafting",
    "draft_complete", "submitted", "won", "passed", "auto_pass",
    "human_passed", "hold", "reported",
}


# /grants/manual — REMOVED: manual grant entry now happens directly in Notion
# Add a new page to the Grant Pipeline DB with Status="Raw"

@app.post("/grants/manual")
async def add_manual_grant(
    body: ManualGrantRequest,
    _: None = Depends(verify_internal),
):
    """Save a manually entered grant URL — fetches content via Cloudflare BR, detects themes,
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

    # Primary: Cloudflare Browser Rendering
    if s.cloudflare_account_id and s.cloudflare_browser_token:
        cf_url = f"https://api.cloudflare.com/client/v4/accounts/{s.cloudflare_account_id}/browser-rendering/markdown"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.post(
                    cf_url,
                    headers={
                        "Authorization": f"Bearer {s.cloudflare_browser_token}",
                        "Content-Type": "application/json",
                    },
                    json={"url": url},
                )
                r.raise_for_status()
                data = r.json()
                raw_content = (data.get("result") or "").strip()[:80_000]
            except Exception:
                pass

    # Fallback: plain HTTP
    if len(raw_content) < 100:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
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
        "grant_name": title,
        "url": url,
        "url_hash": url_hash,
        "funder": funder,
        "raw_content": raw_content,
        "themes_detected": themes,
        "source": "manual",
        "deadline": None,
        "max_funding": None,
        "max_funding_usd": None,
        "currency": "USD",
        "eligibility_raw": "",
        "notes": body.notes or "",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write to Notion Grant Pipeline as "Raw" (primary)
    notion_page_id = None
    try:
        from backend.integrations.notion_data import create_grant_page, find_grant_by_url_hash
        existing_pid = await find_grant_by_url_hash(url_hash)
        if existing_pid:
            raise HTTPException(
                status_code=409,
                detail=f"Already in Notion Grant Pipeline.",
            )
        notion_page_id = await create_grant_page(doc, status="raw")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Notion write failed for manual grant, falling back to MongoDB: %s", e)
        # Fallback: write to MongoDB
        await db["grants_raw"].insert_one(doc)

    # Auto-trigger analyst scoring for this grant
    analyst_message = ""
    if notion_page_id and body.auto_analyze:
        try:
            from backend.integrations.notion_data import get_grant_by_page_id
            grant_data = await get_grant_by_page_id(notion_page_id)
            if grant_data:
                grant_data["notion_page_id"] = notion_page_id
                grant_data["raw_content"] = raw_content
                from backend.agents.analyst import analyst_node
                from backend.graph.state import GrantsState
                state = GrantsState(
                    raw_grants=[grant_data],
                    scored=[],
                    run_config={},
                )
                result = await analyst_node(state)
                scored = result.get("scored", [])
                analyst_message = f" · Analyst scored: {scored[0].get('weighted_total', 0):.1f}" if scored else ""
        except Exception as e:
            logger.warning("Auto-analyze failed: %s", e)
            analyst_message = " · Auto-analyze failed (will retry on next run)"

    return {
        "success": True,
        "title": title,
        "funder": funder,
        "themes": themes,
        "chars_fetched": len(raw_content),
        "notion_page_id": notion_page_id,
        "message": f"Saved '{title[:70]}' · {len(raw_content):,} chars · themes: {', '.join(themes)}{analyst_message}",
    }


# /update/grant-status — REMOVED: status changes now happen directly in Notion
# The Kanban drag-and-drop UI has been replaced by Notion's native board view.


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
