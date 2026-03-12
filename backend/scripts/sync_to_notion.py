"""Sync all scored grants to Notion with full data + rich page body.

Usage:
    python -m backend.scripts.sync_to_notion [--status triage] [--limit 50] [--setup-schema] [--setup-views]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Load .env
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sync_to_notion")


async def main():
    parser = argparse.ArgumentParser(description="Sync grants to Notion")
    parser.add_argument("--status", type=str, default=None,
                        help="Filter by status (e.g. triage, pursue, watch). Default: all.")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max grants to sync (default: 200)")
    parser.add_argument("--setup-schema", action="store_true",
                        help="Update Notion DB schema before syncing")
    parser.add_argument("--setup-views", action="store_true",
                        help="Create Kanban + Table views in Notion")
    args = parser.parse_args()

    # Verify env vars
    mongo_uri = os.getenv("MONGODB_URI")
    notion_token = os.getenv("NOTION_TOKEN")
    if not mongo_uri:
        logger.error("MONGODB_URI not set")
        sys.exit(1)
    if not notion_token:
        logger.error("NOTION_TOKEN not set")
        sys.exit(1)

    logger.info("Connecting to MongoDB...")
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(mongo_uri)
    db = client.altcarbon_grants
    collection = db.grants_scored

    # Build query filter
    query = {}
    if args.status:
        query["status"] = args.status
        logger.info("Filtering by status: %s", args.status)

    # Count total
    total = await collection.count_documents(query)
    logger.info("Found %d grants matching query", total)

    if total == 0:
        logger.info("No grants to sync. Exiting.")
        return

    # Setup schema if requested
    if args.setup_schema:
        from backend.integrations.notion_sync import ensure_grant_pipeline_schema
        logger.info("Updating Notion DB schema...")
        ok = await ensure_grant_pipeline_schema()
        logger.info("Schema update: %s", "OK" if ok else "FAILED (continuing anyway)")

    # Setup views if requested
    if args.setup_views:
        from backend.integrations.notion_sync import setup_grant_pipeline_views
        logger.info("Creating Notion views...")
        results = await setup_grant_pipeline_views()
        logger.info("Views created: %s", list(results.keys()) if results else "none (create manually in Notion)")

    # Fetch grants
    cursor = collection.find(query).sort("weighted_total", -1).limit(args.limit)
    grants = await cursor.to_list(length=args.limit)
    logger.info("Syncing %d grants to Notion (with full page body)...", len(grants))

    # Sync each grant
    from backend.integrations.notion_sync import sync_scored_grant
    success = 0
    failed = 0
    for i, grant in enumerate(grants):
        name = grant.get("grant_name") or grant.get("title") or "Unnamed"
        score = grant.get("weighted_total", 0) or 0
        status = grant.get("status", "?")
        try:
            result = await sync_scored_grant(grant)
            if result:
                success += 1
                logger.info("[%d/%d] OK  — %.1f %s | %s", i + 1, len(grants), score, status, name)
            else:
                failed += 1
                logger.warning("[%d/%d] FAIL — %s", i + 1, len(grants), name)
        except Exception as e:
            failed += 1
            logger.error("[%d/%d] ERROR — %s: %s", i + 1, len(grants), name, e)

        # Rate limit: pause every 3 grants
        if (i + 1) % 3 == 0:
            await asyncio.sleep(1.0)

    logger.info("=" * 60)
    logger.info("Sync complete: %d success, %d failed out of %d total", success, failed, len(grants))
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
