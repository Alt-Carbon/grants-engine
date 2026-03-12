"""Remove duplicate grant pages from Notion Grant Pipeline database.

Groups pages by MongoDB ID, keeps the most recently edited one, archives the rest.
Also archives any pages with no/empty MongoDB ID (orphans).

Usage:
    python -m backend.scripts.dedup_notion_grants [--dry-run]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dedup_notion")


async def main():
    import argparse
    import httpx

    parser = argparse.ArgumentParser(description="Deduplicate Notion Grant Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Only report duplicates, don't archive")
    args = parser.parse_args()

    token = os.getenv("NOTION_TOKEN")
    if not token:
        logger.error("NOTION_TOKEN not set")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    db_id = os.getenv("NOTION_GRANT_PIPELINE_DS", "8e9cd5d9-0239-4072-8233-6006aa184e48")
    base_url = "https://api.notion.com/v1"

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as http:
        # Step 1: Fetch ALL pages from the database (paginated)
        logger.info("Fetching all pages from Grant Pipeline DB...")
        all_pages = []
        has_more = True
        start_cursor = None

        while has_more:
            body: dict = {"page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
            r = await http.post(f"{base_url}/databases/{db_id}/query", json=body)
            r.raise_for_status()
            resp = r.json()
            all_pages.extend(resp["results"])
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")
            logger.info("  Fetched %d pages so far...", len(all_pages))

        logger.info("Total pages in Notion: %d", len(all_pages))

        # Step 2: Group by MongoDB ID
        by_mongo_id: dict[str, list[dict]] = defaultdict(list)
        orphans = []

        for page in all_pages:
            props = page.get("properties", {})
            mongo_prop = props.get("MongoDB ID", {})
            rt = mongo_prop.get("rich_text", [])
            mongo_id = rt[0]["plain_text"].strip() if rt else ""

            if not mongo_id:
                orphans.append(page)
            else:
                by_mongo_id[mongo_id].append(page)

        # Step 3: Identify duplicates
        duplicates_to_archive = []
        unique_count = 0

        for mongo_id, pages in by_mongo_id.items():
            if len(pages) == 1:
                unique_count += 1
                continue

            # Sort by last_edited_time descending — keep the newest
            pages.sort(key=lambda p: p.get("last_edited_time", ""), reverse=True)
            keep = pages[0]
            to_archive = pages[1:]

            keep_name = ""
            title_prop = keep.get("properties", {}).get("Grant Name", {}).get("title", [])
            if title_prop:
                keep_name = title_prop[0].get("plain_text", "")[:60]

            logger.info(
                "MongoDB ID %s: %d pages, keeping %s (%s), archiving %d",
                mongo_id[:12], len(pages), keep["id"][:8], keep_name, len(to_archive),
            )
            duplicates_to_archive.extend(to_archive)
            unique_count += 1

        logger.info("=" * 60)
        logger.info("Summary:")
        logger.info("  Unique grants: %d", unique_count)
        logger.info("  Duplicate pages to archive: %d", len(duplicates_to_archive))
        logger.info("  Orphan pages (no MongoDB ID): %d", len(orphans))
        logger.info("  Total to archive: %d", len(duplicates_to_archive) + len(orphans))
        logger.info("  Will remain: %d", len(all_pages) - len(duplicates_to_archive) - len(orphans))

        if args.dry_run:
            logger.info("DRY RUN — no changes made.")
            return

        # Step 4: Archive duplicates and orphans
        to_archive_all = duplicates_to_archive + orphans
        archived = 0
        failed = 0

        for i, page in enumerate(to_archive_all):
            try:
                r = await http.patch(
                    f"{base_url}/pages/{page['id']}",
                    json={"archived": True},
                )
                r.raise_for_status()
                archived += 1
                if (i + 1) % 10 == 0:
                    logger.info("  Archived %d / %d...", archived, len(to_archive_all))
            except Exception as e:
                failed += 1
                logger.error("  Failed to archive %s: %s", page["id"], e)

            # Rate limit
            if (i + 1) % 3 == 0:
                await asyncio.sleep(0.5)

        logger.info("=" * 60)
        logger.info("Done: archived %d pages, %d failed", archived, failed)
        logger.info("Remaining pages: %d", len(all_pages) - archived)


if __name__ == "__main__":
    asyncio.run(main())
