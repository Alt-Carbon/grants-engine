"""APScheduler-based cron scheduler — runs inside the FastAPI process.

Replaces Vercel cron (not available on Railway). APScheduler is already
in requirements.txt. Jobs are idempotent, so restarts are safe.

Schedule:
  - Scout: Monday 8 AM IST (2:30 AM UTC) — 15-min timeout, auto-triggers Analyst
  - Knowledge sync: daily 3 AM UTC
  - Profile rebuild: weekly Sunday 4 AM UTC
  - Notion change detection: every 30 min
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Timeout for Scout runs (seconds) — prevents runaway jobs
SCOUT_TIMEOUT_SECONDS = 15 * 60  # 15 minutes


def setup_scheduler() -> None:
    """Register all recurring jobs. Called during FastAPI lifespan startup.

    Uses CronTrigger for predictable schedules instead of IntervalTrigger
    (which resets on every deploy).
    """
    import os

    # Skip scheduler in test/dev if DISABLE_SCHEDULER is set
    if os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        logger.info("APScheduler disabled via DISABLE_SCHEDULER env var")
        return

    # Scout: Monday 8 AM IST (= 2:30 AM UTC) — weekly
    # Has 15-min timeout. Auto-triggers Analyst after completion.
    scheduler.add_job(
        _safe_scout_with_analyst,
        trigger=CronTrigger(day_of_week="mon", hour=2, minute=30),
        id="scout_cron",
        name="Scout + Analyst (Mon 8AM IST / 2:30AM UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
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

    # Notion change detection: every 30 min
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

    # Log next run times
    for job in scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else "none"
        logger.info("  %s → next run: %s", job.name, next_run)


def teardown_scheduler() -> None:
    """Shutdown scheduler gracefully. Called during FastAPI lifespan shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")


def get_scheduler_status() -> dict:
    """Return all jobs, next run times, and last run stats."""
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
        "scout_timeout_seconds": SCOUT_TIMEOUT_SECONDS,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def get_last_runs() -> dict:
    """Fetch last run stats from audit_logs for monitoring dashboard."""
    try:
        from backend.db.mongo import audit_logs
        runs = {}
        for event_type in ["cron_scout_analyst", "knowledge_sync", "profile_sync"]:
            doc = await audit_logs().find_one(
                {"event_type": event_type},
                sort=[("timestamp", -1)],
            )
            if doc:
                runs[event_type] = {
                    "timestamp": doc.get("timestamp"),
                    "duration_seconds": doc.get("duration_seconds"),
                    "status": doc.get("scout", {}).get("status") if event_type == "cron_scout_analyst" else doc.get("status"),
                }
        return runs
    except Exception:
        return {}


# ── Safe wrappers (catch errors, emit notifications) ─────────────────────────

async def _safe_scout_with_analyst() -> None:
    """Run Scout with 15-min timeout, then auto-trigger Analyst on results.

    Pipeline:
      1. Scout discovers grants (15-min timeout)
      2. Analyst scores all new unscored grants
      3. Notifications emitted for both stages
      4. Run stats logged to audit_logs for monitoring
    """
    from backend.jobs.scout_job import run_scout_pipeline

    start = datetime.now(timezone.utc)
    scout_result = {}
    analyst_result = {}

    # ── Step 1: Scout with timeout ──
    try:
        scout_result = await asyncio.wait_for(
            run_scout_pipeline(),
            timeout=SCOUT_TIMEOUT_SECONDS,
        )
        scout_status = scout_result.get("status", "unknown")
        logger.info("Scout complete in %.0fs: %s", (datetime.now(timezone.utc) - start).total_seconds(), scout_status)
    except asyncio.TimeoutError:
        scout_result = {"status": "timeout", "timeout_seconds": SCOUT_TIMEOUT_SECONDS}
        logger.warning("Scout timed out after %d seconds — stopping gracefully", SCOUT_TIMEOUT_SECONDS)
    except Exception as e:
        scout_result = {"status": "error", "error": str(e)}
        logger.error("Scout failed: %s", e)

    # Notify scout completion
    try:
        from backend.notifications.hub import notify
        scout_status = scout_result.get("status", "unknown")
        scout_emoji = {"timeout": "⏰", "error": "❌"}.get(scout_status, "✅")
        await notify(
            event_type="scout_complete",
            title=f"{scout_emoji} Scout run {scout_status}",
            body=f"Duration: {(datetime.now(timezone.utc) - start).total_seconds():.0f}s" + (
                f" — timed out after {SCOUT_TIMEOUT_SECONDS}s" if scout_status == "timeout" else ""
            ),
            action_url="/monitoring",
            metadata=scout_result,
        )
    except Exception:
        logger.debug("Scout notification failed", exc_info=True)

    # ── Step 2: Auto-trigger Analyst on unscored grants ──
    analyst_start = datetime.now(timezone.utc)
    try:
        from backend.db.mongo import get_db
        db = get_db()

        # Find raw grants not yet in grants_scored
        scored_hashes = set()
        async for doc in db["grants_scored"].find({}, {"url_hash": 1}):
            scored_hashes.add(doc.get("url_hash", ""))

        unscored = []
        async for doc in db["grants_raw"].find({"processed": {"$ne": True}}):
            h = doc.get("url_hash", "")
            if h and h not in scored_hashes:
                doc["_id"] = str(doc["_id"])
                unscored.append(doc)

        if unscored:
            logger.info("Analyst auto-triggered: %d unscored grants to process", len(unscored))
            from backend.agents.analyst import AnalystAgent
            agent = AnalystAgent()
            scored = await agent.run(unscored)
            analyst_result = {
                "status": "complete",
                "input_count": len(unscored),
                "scored_count": len(scored),
                "duration_s": (datetime.now(timezone.utc) - analyst_start).total_seconds(),
            }
            logger.info("Analyst complete: scored %d/%d grants in %.0fs",
                         len(scored), len(unscored), analyst_result["duration_s"])
        else:
            analyst_result = {"status": "skipped", "reason": "no unscored grants"}
            logger.info("Analyst skipped: no unscored grants")

        # Notify analyst completion
        try:
            from backend.notifications.hub import notify
            await notify(
                event_type="analyst_complete",
                title=f"Analyst: scored {analyst_result.get('scored_count', 0)} grants",
                body=f"Duration: {analyst_result.get('duration_s', 0):.0f}s",
                action_url="/pipeline",
                metadata=analyst_result,
            )
        except Exception:
            logger.debug("Analyst notification failed", exc_info=True)
    except Exception as e:
        analyst_result = {"status": "error", "error": str(e)}
        logger.error("Analyst auto-trigger failed: %s", e)

    # ── Step 3: Log run to audit_logs for monitoring ──
    total_duration = (datetime.now(timezone.utc) - start).total_seconds()
    try:
        from backend.db.mongo import audit_logs
        await audit_logs().insert_one({
            "event_type": "cron_scout_analyst",
            "node": "scheduler",
            "action": "scout_analyst_pipeline",
            "timestamp": start.isoformat(),
            "duration_seconds": total_duration,
            "scout": scout_result,
            "analyst": analyst_result,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        logger.debug("Audit log write failed", exc_info=True)

    logger.info(
        "Scout+Analyst pipeline complete: total %.0fs, scout=%s, analyst=%s",
        total_duration,
        scout_result.get("status", "?"),
        analyst_result.get("status", "?"),
    )


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
