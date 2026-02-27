"""Standalone script — runs Scout + Analyst locally and outputs results as JSON.

Usage (from project root):
    python -m backend.scripts.run_scout_analyst

Outputs:
    output/grants_raw.json     — every raw grant discovered this run
    output/grants_scored.json  — scored + ranked grants (what the frontend shows)

Requirements: .env at project root with TAVILY_API_KEY, EXA_API_KEY, ANTHROPIC_API_KEY, MONGODB_URI
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Bootstrap (add project root to path so relative imports work) ──────────────
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before importing anything that reads settings
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("run_local")

OUTPUT_DIR = ROOT / "output"


def _serialize(doc: dict) -> dict:
    """Make a MongoDB document JSON-serialisable."""
    import bson
    result = {}
    for k, v in doc.items():
        if isinstance(v, bson.ObjectId):
            result[k] = str(v)
        elif isinstance(v, bytes):
            result[k] = v.hex()
        elif isinstance(v, dict):
            result[k] = _serialize(v)
        elif isinstance(v, list):
            result[k] = [_serialize(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("AltCarbon Grant Scout + Analyst — Local Run")
    logger.info("=" * 60)

    # ── 1. Validate API keys ──────────────────────────────────────────────────
    from backend.config.settings import get_settings
    s = get_settings()

    missing = []
    if not s.tavily_api_key:    missing.append("TAVILY_API_KEY")
    if not s.exa_api_key:       missing.append("EXA_API_KEY")
    if not s.anthropic_api_key and not s.ai_gateway_api_key:
        missing.append("ANTHROPIC_API_KEY or AI_GATEWAY_API_KEY")
    if not s.mongodb_uri or "localhost" in s.mongodb_uri:
        logger.warning("MONGODB_URI looks like localhost — make sure MongoDB is running")

    if missing:
        logger.error("Missing API keys: %s", ", ".join(missing))
        logger.error("Copy .env.example to .env and fill them in")
        sys.exit(1)

    logger.info("API keys: Tavily ✓  Exa ✓  Anthropic ✓")
    if s.perplexity_api_key:
        logger.info("Perplexity: ✓ (funder enrichment enabled)")
    if s.jina_api_key:
        logger.info("Jina: ✓ (full-page fetch enabled)")

    # ── 2. Ensure DB indexes ──────────────────────────────────────────────────
    from backend.db.mongo import ensure_indexes, get_db
    await ensure_indexes()

    # ── 3. Run Scout ──────────────────────────────────────────────────────────
    from backend.agents.scout import ScoutAgent, ALL_DIRECT_SOURCES

    agent = ScoutAgent(
        tavily_api_key=s.tavily_api_key,
        exa_api_key=s.exa_api_key,
        jina_api_key=s.jina_api_key,
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        max_results_per_query=10,
        enable_direct_crawl=True,
    )

    logger.info("Running Scout (this takes 5–15 min)…")
    t0 = asyncio.get_event_loop().time()
    raw_grants = await agent.run()
    elapsed = asyncio.get_event_loop().time() - t0

    logger.info(
        "Scout complete: %d new grants discovered in %.0fs",
        len(raw_grants), elapsed,
    )

    # Save raw grants JSON
    raw_path = OUTPUT_DIR / f"grants_raw_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
    raw_path.write_text(
        json.dumps([_serialize(g) for g in raw_grants], indent=2, default=str)
    )
    logger.info("Raw grants saved → %s", raw_path)

    # Also pull backlog of unprocessed grants from DB
    col = get_db()["grants_raw"]
    backlog = await col.find({"processed": False}).to_list(length=500)
    logger.info("Backlog: %d unprocessed grants from previous runs", len(backlog))

    seen: set = {g.get("url_hash") for g in raw_grants}
    all_raw: list = list(raw_grants)
    for g in backlog:
        if g.get("url_hash") not in seen:
            seen.add(g.get("url_hash"))
            all_raw.append(g)

    # ── 4. Run Analyst ────────────────────────────────────────────────────────
    if not all_raw:
        logger.info("No new grants to score — analyst skipped")
    else:
        logger.info("Running Analyst on %d grants…", len(all_raw))
        from backend.agents.analyst import analyst_node

        state = {
            "raw_grants": all_raw,
            "scored_grants": [],
            "audit_log": [],
            # Required GrantState keys (unused by analyst but must be present)
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
            "thread_id": f"local_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
            "run_id": "local_run",
            "errors": [],
        }

        t1 = asyncio.get_event_loop().time()
        analyst_result = await analyst_node(state)
        elapsed2 = asyncio.get_event_loop().time() - t1

        scored = analyst_result.get("scored_grants", [])
        logger.info(
            "Analyst complete: %d grants scored in %.0fs",
            len(scored), elapsed2,
        )

    # ── 5. Read final results from MongoDB and save JSON ──────────────────────
    db = get_db()
    all_scored = await db["grants_scored"].find(
        {}, sort=[("weighted_total", -1)]
    ).to_list(length=500)

    scored_path = OUTPUT_DIR / f"grants_scored_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
    scored_path.write_text(
        json.dumps([_serialize(g) for g in all_scored], indent=2, default=str)
    )

    # Pretty summary to stdout
    logger.info("\n" + "=" * 60)
    logger.info("RESULTS SUMMARY")
    logger.info("=" * 60)
    pursue  = [g for g in all_scored if g.get("status") == "pursue"]
    watch   = [g for g in all_scored if g.get("status") == "watch"]
    triage  = [g for g in all_scored if g.get("status") == "triage"]
    passed  = [g for g in all_scored if g.get("status") in ("auto_pass", "passed")]
    logger.info("Total scored : %d", len(all_scored))
    logger.info("Triage       : %d", len(triage))
    logger.info("Pursue       : %d (score ≥ 6.5)", len(pursue))
    logger.info("Watch        : %d (score 5.0–6.5)", len(watch))
    logger.info("Auto-passed  : %d", len(passed))
    logger.info("")
    logger.info("Top 10 grants by score:")
    for i, g in enumerate(all_scored[:10], 1):
        score = g.get("weighted_total", 0)
        name  = g.get("grant_name") or g.get("title") or "?"
        rec   = g.get("recommended_action", "?")
        logger.info("  %2d. [%.1f] %-55s  %s", i, score, name[:55], rec)

    logger.info("")
    logger.info("✅ Scored grants saved → %s", scored_path)
    logger.info("   Open http://localhost:3000 to see them in the frontend")


if __name__ == "__main__":
    asyncio.run(main())
