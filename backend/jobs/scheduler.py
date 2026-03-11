"""APScheduler-based cron scheduler — runs inside the FastAPI process.

Replaces Vercel cron (not available on Railway). APScheduler is already
in requirements.txt. Jobs are idempotent, so restarts are safe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler() -> None:
    """Register all recurring jobs. Called during FastAPI lifespan startup."""
    from backend.jobs.scout_job import run_scout_pipeline
    from backend.jobs.knowledge_job import run_knowledge_sync

    # Scout: every 48 hours
    scheduler.add_job(
        _safe_scout,
        trigger=IntervalTrigger(hours=48),
        id="scout_cron",
        name="Scout Discovery (48h)",
        replace_existing=True,
        misfire_grace_time=3600,  # 1h grace for missed runs
    )

    # Knowledge sync: daily at 3 AM UTC
    scheduler.add_job(
        _safe_knowledge_sync,
        trigger=CronTrigger(hour=3, minute=0),
        id="knowledge_cron",
        name="Knowledge Sync (daily 3AM UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Profile rebuild: weekly Sunday 4 AM UTC
    scheduler.add_job(
        _safe_profile_sync,
        trigger=CronTrigger(day_of_week="sun", hour=4),
        id="profile_cron",
        name="Profile Rebuild (weekly Sun 4AM UTC)",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # Notion change detection: every 30 min (polling fallback for webhooks)
    scheduler.add_job(
        _safe_check_notion_changes,
        trigger=IntervalTrigger(minutes=30),
        id="notion_change_check",
        name="Notion Change Detection (30min polling)",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    scheduler.start()
    logger.info(
        "APScheduler started with %d jobs: %s",
        len(scheduler.get_jobs()),
        ", ".join(j.id for j in scheduler.get_jobs()),
    )


def teardown_scheduler() -> None:
    """Shutdown scheduler gracefully. Called during FastAPI lifespan shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")


def get_scheduler_status() -> dict:
    """Return all jobs and their next run times."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return {
        "running": scheduler.running,
        "jobs": jobs,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ── Safe wrappers (catch errors, emit notifications) ─────────────────────────

async def _safe_scout() -> None:
    """Run scout pipeline with error handling + notification."""
    from backend.jobs.scout_job import run_scout_pipeline
    try:
        result = await run_scout_pipeline()
        logger.info("Scheduled scout complete: %s", result.get("status"))
        # Emit notification
        try:
            from backend.notifications.hub import notify
            await notify(
                event_type="scout_complete",
                title="Scout run complete",
                body=f"Status: {result.get('status', 'unknown')}",
                action_url="/monitoring",
                metadata=result,
            )
        except Exception:
            logger.debug("Scout notification failed", exc_info=True)
    except Exception as e:
        logger.error("Scheduled scout failed: %s", e)


async def _safe_knowledge_sync() -> None:
    """Run knowledge sync with error handling."""
    from backend.jobs.knowledge_job import run_knowledge_sync
    try:
        result = await run_knowledge_sync()
        logger.info("Scheduled knowledge sync complete: %s", result.get("status"))
        try:
            from backend.notifications.hub import notify
            await notify(
                event_type="knowledge_sync",
                title="Knowledge sync complete",
                body=f"Chunks: {result.get('chunks_upserted', 0)}",
                action_url="/knowledge",
                metadata=result,
            )
        except Exception:
            logger.debug("Knowledge sync notification failed", exc_info=True)
    except Exception as e:
        logger.error("Scheduled knowledge sync failed: %s", e)


async def _safe_profile_sync() -> None:
    """Run profile rebuild with error handling."""
    try:
        from backend.knowledge.sync_profile import sync_profile_from_notion
        result = await sync_profile_from_notion()
        logger.info("Scheduled profile sync complete: %s", result)
    except Exception as e:
        logger.error("Scheduled profile sync failed: %s", e)


async def _safe_check_notion_changes() -> None:
    """Poll Notion for page edits newer than last sync (webhook fallback)."""
    try:
        await check_notion_changes()
    except Exception as e:
        logger.error("Scheduled Notion change check failed: %s", e)


async def check_notion_changes() -> dict:
    """Check Table of Content pages for edits since last sync.

    For each page: fetch metadata (last_edited_time) from Notion API,
    compare with last_synced in MongoDB. If newer → run sync_single_document.
    Lightweight: only fetches page metadata, not content, until a change is confirmed.
    """
    import re
    import httpx
    from backend.config.settings import get_settings
    from backend.integrations.notion_config import TABLE_OF_CONTENT_DS
    from backend.db.mongo import knowledge_chunks
    from backend.agents.company_brain import CompanyBrainAgent

    s = get_settings()
    if not s.notion_token:
        return {"status": "skipped", "reason": "NOTION_TOKEN not set"}

    col = knowledge_chunks()

    # Get last_synced per source_id
    sync_times: dict = {}
    pipeline = [
        {"$match": {"source_id": {"$exists": True}}},
        {"$group": {
            "_id": "$source_id",
            "last_synced": {"$max": "$last_synced"},
        }},
    ]
    async for row in col.aggregate(pipeline):
        sync_times[str(row["_id"])] = row.get("last_synced", "")

    # Query Table of Content for all rows
    headers = {
        "Authorization": f"Bearer {s.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
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
                logger.warning("Notion change check: API returned %d", r.status_code)
                break
            data = r.json()
            rows.extend(data.get("results", []))
            cursor = data.get("next_cursor")
            if not cursor:
                break

    # Check each page for changes
    agent = CompanyBrainAgent(
        notion_token=s.notion_token,
        google_refresh_token=s.google_refresh_token,
        google_client_id=s.google_client_id,
        google_client_secret=s.google_client_secret,
    )

    synced = 0
    checked = 0
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

        checked += 1
        last_synced = sync_times.get(notion_page_id, "")

        if page_edited and last_synced and page_edited > last_synced:
            logger.info(
                "Notion change detected: %s (edited=%s, synced=%s)",
                notion_page_id, page_edited, last_synced,
            )
            try:
                result = await agent.sync_single_document(notion_page_id)
                if result.get("status") == "synced":
                    synced += 1
            except Exception as e:
                logger.error("Polling re-sync failed for %s: %s", notion_page_id, e)

    logger.info("Notion change check: %d pages checked, %d re-synced", checked, synced)
    return {"status": "complete", "checked": checked, "synced": synced}
