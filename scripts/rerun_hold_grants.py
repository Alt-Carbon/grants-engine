#!/usr/bin/env python3
"""One-off script: re-run Analyst on all hold grants.

Usage (from project root):
    python -m scripts.rerun_hold_grants

Connects directly to MongoDB, fetches hold grants, deletes them from
grants_scored, and re-runs the full analyst pipeline.
"""
import asyncio
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


async def main():
    from backend.db.mongo import grants_scored, agent_config
    from backend.agents.analyst import AnalystAgent, DEFAULT_WEIGHTS
    from backend.config.settings import get_settings

    s = get_settings()

    # 1. Count and fetch hold grants
    col = grants_scored()
    hold_grants = await col.find({"status": "hold"}).to_list(2000)
    print(f"\n{'='*60}")
    print(f"Found {len(hold_grants)} grants on HOLD")
    print(f"{'='*60}")

    if not hold_grants:
        print("Nothing to do.")
        return

    for i, g in enumerate(hold_grants, 1):
        print(f"  {i}. {g.get('title', 'Untitled')[:60]}  —  {g.get('funder', '?')}")
        print(f"     Reason: {g.get('reasoning', 'unknown')[:80]}")

    # 2. Convert to raw-like format
    raw_like = []
    for g in hold_grants:
        raw_like.append({
            "_id": g["_id"],
            "title": g.get("title") or g.get("grant_name") or "",
            "grant_name": g.get("grant_name") or g.get("title") or "",
            "url": g.get("url") or g.get("source_url") or "",
            "source_url": g.get("source_url") or g.get("url") or "",
            "application_url": g.get("application_url") or "",
            "url_hash": g.get("url_hash", ""),
            "content_hash": g.get("content_hash", ""),
            "funder": g.get("funder", ""),
            "deadline": g.get("deadline", ""),
            "amount": g.get("amount") or "",
            "max_funding": g.get("max_funding"),
            "max_funding_usd": g.get("max_funding_usd"),
            "currency": g.get("currency", ""),
            "eligibility": g.get("eligibility", ""),
            "geography": g.get("geography", ""),
            "grant_type": g.get("grant_type", ""),
            "themes_detected": g.get("themes_detected", []),
            "themes_text": g.get("themes_text", ""),
            "notes": g.get("notes", ""),
            "about_opportunity": g.get("about_opportunity", ""),
            "application_process": g.get("application_process", ""),
            "eligibility_details": g.get("eligibility_details", ""),
            "raw_content": g.get("raw_content", ""),
            "scraped_at": g.get("scraped_at", ""),
        })

    # 3. Delete existing scored records so analyst doesn't skip
    hold_ids = [g["_id"] for g in hold_grants]
    delete_result = await col.delete_many({"_id": {"$in": hold_ids}})
    print(f"\nDeleted {delete_result.deleted_count} hold records from grants_scored")

    # 4. Run analyst
    cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
    weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
    min_funding = cfg_doc.get("min_funding", s.min_grant_funding)

    print(f"\nRunning Analyst on {len(raw_like)} grants...")
    print(f"  Model: heavy={s.analyst_heavy_model or 'default'}")
    print(f"  Min funding: {min_funding}")
    print()

    agent = AnalystAgent(
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        weights=weights,
        min_funding=min_funding,
    )
    scored = await agent.run(raw_like)

    # 5. Report results
    print(f"\n{'='*60}")
    print(f"RESULTS: {len(scored)} grants re-scored")
    print(f"{'='*60}")

    triage = 0
    still_hold = 0
    auto_pass = 0
    for g in scored:
        status = g.get("status", "?")
        action = g.get("recommended_action", "?")
        score = g.get("weighted_total", 0)
        title = g.get("title", "Untitled")[:50]

        if status == "triage":
            triage += 1
            icon = ">>>"
        elif status == "hold":
            still_hold += 1
            icon = "..."
        elif status == "auto_pass":
            auto_pass += 1
            icon = "XXX"
        else:
            icon = "   "

        print(f"  {icon} [{status:12s}] {score:5.2f}  {action:8s}  {title}")

    print(f"\n  Moved to triage: {triage}")
    print(f"  Still on hold:   {still_hold}")
    print(f"  Auto-passed:     {auto_pass}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
