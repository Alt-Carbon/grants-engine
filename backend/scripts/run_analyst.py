"""Re-run the Analyst agent across all grants in MongoDB.

Usage:
    python -m backend.scripts.run_analyst [--force] [--limit 500]

    --force   Re-score ALL grants, even already-scored ones
    --limit   Max grants to process (default: 5000)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_analyst")


async def main():
    parser = argparse.ArgumentParser(description="Run Analyst agent")
    parser.add_argument("--force", action="store_true",
                        help="Re-score all grants, ignoring already-scored checks")
    parser.add_argument("--limit", type=int, default=5000,
                        help="Max grants to process (default: 5000)")
    args = parser.parse_args()

    # Verify env
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        logger.error("MONGODB_URI not set")
        sys.exit(1)

    logger.info("Connecting to MongoDB...")
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(mongo_uri)
    db = client.altcarbon_grants

    # Fetch grants
    if args.force:
        raw_docs = await db.grants_raw.find({}).to_list(length=args.limit)
        logger.info("FORCE mode: fetched %d total grants from grants_raw", len(raw_docs))
    else:
        raw_docs = await db.grants_raw.find({"processed": False}).to_list(length=args.limit)
        logger.info("Fetched %d unprocessed grants from grants_raw", len(raw_docs))

    if not raw_docs:
        logger.info("No grants to process. Exiting.")
        return

    # Check browser availability
    from backend.utils.browser import is_available
    logger.info("agent-browser available: %s", is_available())

    # Load settings and config
    from backend.config.settings import get_settings
    s = get_settings()

    from backend.agents.analyst import AnalystAgent, DEFAULT_WEIGHTS

    agent = AnalystAgent(
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        weights=DEFAULT_WEIGHTS,
        min_funding=s.min_grant_funding,
    )

    logger.info("Starting Analyst run on %d grants (force=%s)...", len(raw_docs), args.force)
    scored = await agent.run(raw_docs, force=args.force)
    logger.info("=" * 60)
    logger.info("Analyst complete: %d grants scored out of %d input", len(scored), len(raw_docs))
    logger.info("=" * 60)

    # Sync scored grants to Notion
    logger.info("Syncing scored grants to Notion...")
    from backend.integrations.notion_sync import sync_scored_grant
    success = 0
    failed = 0
    for i, grant in enumerate(scored):
        name = grant.get("grant_name") or grant.get("title") or "Unnamed"
        try:
            result = await sync_scored_grant(grant)
            if result:
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error("Notion sync failed for %s: %s", name[:50], e)

        if (i + 1) % 3 == 0:
            await asyncio.sleep(1.0)

    logger.info("Notion sync: %d success, %d failed", success, failed)


if __name__ == "__main__":
    asyncio.run(main())
