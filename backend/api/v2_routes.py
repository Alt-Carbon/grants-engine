"""v2 API endpoints — reads from Notion (grants) + SQLite (metadata).

Replaces direct MongoDB access from the frontend.
Frontend calls these instead of querying MongoDB directly.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, Body
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
router = APIRouter(tags=["v2"])

# ── In-memory cache for Notion grants (avoid 40s+ queries on every page load) ─
_grants_cache: list | None = None
_grants_cache_ts: float = 0
_GRANTS_CACHE_TTL = 300  # 5 minutes — avoid Notion 429 rate limits


async def _cached_all_grants() -> list:
    """Return all grants from Notion with a 5-min in-memory cache."""
    global _grants_cache, _grants_cache_ts
    now = time.monotonic()
    if _grants_cache is not None and (now - _grants_cache_ts) < _GRANTS_CACHE_TTL:
        return _grants_cache
    from backend.integrations.notion_data import query_all_grants
    try:
        grants = await query_all_grants()
    except Exception as e:
        log.error("Failed to fetch grants from Notion: %s", e)
        # Return stale cache if available, otherwise empty
        return _grants_cache if _grants_cache is not None else []
    # Don't cache empty results if we previously had data (likely a transient error)
    if not grants and _grants_cache and len(_grants_cache) > 0:
        log.warning("Notion returned 0 grants but cache has %d — keeping stale cache", len(_grants_cache))
        return _grants_cache
    _grants_cache = grants
    _grants_cache_ts = now
    return _grants_cache


# ── Grants (from Notion) ─────────────────────────────────────────────────────

@router.get("/grants")
async def v2_get_all_grants():
    """All grants grouped by status (replaces getPipelineGrants)."""
    grants = list(await _cached_all_grants())

    grouped: dict[str, list] = {
        "shortlisted": [],
        "pursue": [],
        "drafting": [],
        "submitted": [],
        "rejected": [],
    }

    grants.sort(key=lambda g: g.get("weighted_total", 0) or 0, reverse=True)

    for g in grants:
        g["_id"] = g.get("notion_page_id", "")
        if not g.get("grant_name") and g.get("title"):
            g["grant_name"] = g["title"]

        status = g.get("status", "raw")
        if status in ("triage", "raw", "shortlisted"):
            grouped["shortlisted"].append(g)
        elif status in ("pursue", "pursuing"):
            grouped["pursue"].append(g)
        elif status == "drafting":
            grouped["drafting"].append(g)
        elif status in ("draft_complete", "submitted", "won"):
            grouped["submitted"].append(g)
        elif status in ("passed", "auto_pass", "human_passed", "reported", "watch"):
            grouped["rejected"].append(g)

    return grouped


@router.get("/grants/by-id/{grant_id}")
async def v2_get_grant_by_id(grant_id: str):
    """Single grant by Notion page ID."""
    from backend.integrations.notion_data import get_grant_by_page_id

    grant = await get_grant_by_page_id(grant_id)
    if not grant:
        return JSONResponse({"error": "Grant not found"}, status_code=404)
    grant["_id"] = grant.get("notion_page_id", "")
    if not grant.get("grant_name") and grant.get("title"):
        grant["grant_name"] = grant["title"]
    return grant


@router.get("/grants/status/{status}")
async def v2_get_grants_by_status(status: str):
    """Grants by internal status key."""
    from backend.integrations.notion_data import query_grants_by_status
    from backend.integrations.notion_config import STATUS_MAP

    notion_status = STATUS_MAP.get(status, status.capitalize())
    grants = await query_grants_by_status(notion_status)

    for g in grants:
        g["_id"] = g.get("notion_page_id", "")
        if not g.get("grant_name") and g.get("title"):
            g["grant_name"] = g["title"]

    grants.sort(key=lambda g: g.get("weighted_total", 0) or 0, reverse=True)
    return grants


@router.post("/grants/status")
async def v2_update_grant_status(body: dict = Body(...)):
    """Update a grant's status in Notion."""
    from backend.integrations.notion_data import update_grant_status

    grant_id = body.get("grant_id")
    status = body.get("status")
    if not grant_id or not status:
        return JSONResponse({"error": "grant_id and status required"}, status_code=400)

    ok = await update_grant_status(grant_id, status)
    if not ok:
        return JSONResponse({"error": "Failed to update"}, status_code=500)
    global _grants_cache_ts
    _grants_cache_ts = 0  # invalidate cache
    return {"ok": True, "status": status}


@router.get("/dashboard/stats")
async def v2_dashboard_stats():
    """Dashboard stats from Notion."""
    grants = await _cached_all_grants()

    total = len(grants)
    triage = sum(1 for g in grants if g.get("status") in ("triage", "raw"))
    pursuing = sum(1 for g in grants if g.get("status") in ("pursue", "pursuing"))
    on_hold = sum(1 for g in grants if g.get("status") == "hold")
    drafting = sum(1 for g in grants if g.get("status") == "drafting")
    complete = sum(1 for g in grants if g.get("status") in ("draft_complete", "submitted", "won"))
    urgent = sum(
        1 for g in grants
        if g.get("deadline_urgent") and g.get("status") in ("triage", "pursue", "raw")
    )

    warnings: list[str] = []
    if total > 0 and triage == 0:
        warnings.append("Shortlist is empty — run a new scout to discover fresh opportunities.")
    if urgent > 0:
        warnings.append(f"{urgent} grant(s) with urgent deadlines in your active queue — review now.")
    if on_hold > 0:
        warnings.append(f"{on_hold} grant(s) on HOLD — manual review needed.")

    return {
        "total_discovered": total,
        "in_triage": triage,
        "pursuing": pursuing,
        "on_hold": on_hold,
        "deadline_urgent_count": urgent,
        "drafting": drafting,
        "draft_complete": complete,
        "warnings": warnings,
    }


@router.get("/discoveries")
async def v2_recent_discoveries(limit: int = Query(20)):
    """Recent grants from Notion sorted by score."""
    grants = list(await _cached_all_grants())
    grants.sort(key=lambda g: g.get("weighted_total", 0) or 0, reverse=True)
    grants = grants[:limit]

    return [
        {
            "_id": g.get("notion_page_id", ""),
            "grant_name": g.get("grant_name") or g.get("title") or "Untitled",
            "funder": g.get("funder") or "Unknown",
            "source": g.get("source") or "scout",
            "scored_at": None,
            "scraped_at": None,
            "weighted_total": g.get("weighted_total"),
            "status": g.get("status") or "raw",
            "themes_detected": g.get("themes_detected") or [],
            "max_funding_usd": g.get("max_funding_usd"),
            "url": g.get("url"),
        }
        for g in grants
    ]


@router.get("/pipeline-summary")
async def v2_pipeline_summary():
    """Pipeline counts from Notion."""
    grants = await _cached_all_grants()

    return {
        "total_discovered": len(grants),
        "in_triage": sum(1 for g in grants if g.get("status") == "triage"),
        "pursuing": sum(1 for g in grants if g.get("status") in ("pursue", "pursuing")),
        "on_hold": sum(1 for g in grants if g.get("status") == "hold"),
        "drafting": sum(1 for g in grants if g.get("status") == "drafting"),
        "submitted": sum(1 for g in grants if g.get("status") in ("draft_complete", "submitted", "won")),
        "rejected": sum(1 for g in grants if g.get("status") in ("passed", "auto_pass", "human_passed")),
        "urgent": sum(
            1 for g in grants
            if g.get("deadline_urgent") and g.get("status") in ("triage", "pursue")
        ),
        "unprocessed": sum(1 for g in grants if g.get("status") == "raw"),
        "watching": sum(1 for g in grants if g.get("status") == "watch"),
    }


# ── Drafts (from Notion — grants with status "Draft" or "drafting") ──────────

@router.get("/drafts")
async def v2_draft_grants():
    """Draft grants — reads from Notion (grants with drafting status) + scheduler thread info."""
    try:
        # Get all grants currently in drafting status from the cache
        grants = await _cached_all_grants()
        drafting = [g for g in grants if g.get("status") in ("drafting", "draft_complete")]

        if not drafting:
            # Also try direct query in case cache is stale
            from backend.integrations.notion_data import query_grants_by_status
            try:
                drafting = await query_grants_by_status("Draft")
            except Exception:
                pass

        # Get active drafting thread IDs from scheduler
        from backend.jobs.scheduler import _active_drafting_page_ids

        result = []
        for g in drafting:
            page_id = g.get("notion_page_id", "")
            rec = {
                "_id": page_id,
                "grant_id": page_id,
                "thread_id": f"draft-{page_id}" if page_id in _active_drafting_page_ids else "",
                "status": g.get("status", "drafting"),
                "started_at": None,
                "draft_started_at": None,
                "current_draft_version": 0,
                "final_draft_url": None,
                "grant_title": g.get("grant_name") or g.get("title") or "Unknown Grant",
                "grant_funder": g.get("funder") or "",
                "grant_themes": g.get("themes_detected") or [],
                "latest_draft": None,
            }

            # Try to find thread info from SQLite drafter_chat_history
            try:
                from backend.db.sqlite import drafter_chat_history
                chat = await drafter_chat_history().find_one({"pipeline_id": page_id})
                if chat:
                    rec["thread_id"] = chat.get("pipeline_id", rec["thread_id"])
            except Exception:
                pass

            result.append(rec)

        return result
    except Exception as exc:
        log.warning("v2_draft_grants: %s", exc)
        return []


@router.get("/drafts/{pipeline_id}/sections")
async def v2_get_sections(pipeline_id: str):
    """Draft sections for a pipeline — checks SQLite chat history and MongoDB fallback."""
    # Try MongoDB first (legacy drafts may still be there)
    try:
        from backend.db.mongo import grant_drafts

        draft = await grant_drafts().find_one(
            {"pipeline_id": pipeline_id},
            sort=[("version", -1)],
        )
        if draft:
            return draft.get("sections", {})
    except Exception:
        pass

    # No sections found yet — pipeline may be in progress
    return {}


# ── Audit Logs / Activity (from SQLite) ──────────────────────────────────────

@router.get("/audit-logs")
async def v2_audit_logs(
    agent: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = Query(100),
):
    """Audit logs from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()

    conditions: list[str] = []
    params: list = []
    if agent:
        conditions.append("node = ?")
        params.append(agent)
    if days:
        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = await conn.execute_fetchall(
        f"SELECT * FROM audit_logs WHERE {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    )

    result = []
    for r in rows:
        d = dict(r)
        d["_id"] = str(d.pop("id", ""))
        meta = d.pop("metadata_json", "{}")
        try:
            extra = json.loads(meta) if meta else {}
        except (json.JSONDecodeError, TypeError):
            extra = {}
        d.update(extra)
        result.append(d)

    return result


@router.get("/activity-feed")
async def v2_activity_feed(limit: int = Query(50)):
    """Activity feed from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )

    result = []
    for r in rows:
        d = dict(r)
        action = d.get("action", "") or ""
        is_error = "fail" in action.lower() or "error" in action.lower()
        is_warning = "warn" in action.lower() or "skip" in action.lower() or "reject" in action.lower()

        meta: dict = {}
        try:
            meta = json.loads(d.get("metadata_json", "{}") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        details = []
        for key in ("grants_scored", "new_grants", "total_found", "pursue_count", "auto_pass_count", "scored_count", "input_count"):
            val = meta.get(key)
            if val:
                details.append(f"{val} {key.replace('_', ' ')}")

        result.append({
            "_id": str(d.get("id", "")),
            "agent": d.get("node", "") or "system",
            "action": action,
            "details": " \u00b7 ".join(details) or "",
            "created_at": d.get("created_at", ""),
            "type": "error" if is_error else ("warning" if is_warning else "success"),
        })

    return result


@router.get("/activity")
async def v2_grants_activity(days: int = Query(30)):
    """Grant discovery activity over time."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        """SELECT date(created_at) as date, COUNT(*) as count
           FROM audit_logs
           WHERE created_at >= datetime('now', ?)
             AND node = 'scout'
           GROUP BY date(created_at)
           ORDER BY date ASC""",
        (f"-{days} days",),
    )

    return [{"date": dict(r)["date"], "count": dict(r)["count"]} for r in rows]


@router.get("/agent-health")
async def v2_agent_health():
    """Agent health stats from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    agents = ["scout", "analyst", "drafter", "knowledge_sync"]
    results = []

    for agent in agents:
        if agent == "knowledge_sync":
            rows = await conn.execute_fetchall(
                """SELECT * FROM audit_logs
                   WHERE action LIKE '%knowledge%' OR node LIKE '%knowledge%'
                   ORDER BY created_at DESC LIMIT 100"""
            )
        else:
            rows = await conn.execute_fetchall(
                "SELECT * FROM audit_logs WHERE node = ? ORDER BY created_at DESC LIMIT 100",
                (agent,),
            )

        all_runs = [dict(r) for r in rows]
        last_run = all_runs[0] if all_runs else None
        total_runs = len(all_runs)
        failed_runs = sum(1 for r in all_runs if "fail" in (r.get("action", "") or "").lower())

        scout_count = 0
        if agent == "scout":
            sr = await conn.execute_fetchall("SELECT COUNT(*) as cnt FROM scout_runs")
            scout_count = dict(sr[0])["cnt"] if sr else 0

        last_meta: dict = {}
        if last_run:
            try:
                last_meta = json.loads(last_run.get("metadata_json", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass

        results.append({
            "agent": agent,
            "lastRun": last_run["created_at"] if last_run else None,
            "lastStatus": "completed" if last_run else "never_run",
            "totalRuns": max(total_runs, scout_count) if agent == "scout" else total_runs,
            "successfulRuns": total_runs - failed_runs,
            "failedRuns": failed_runs,
            "uptimePct": round(((total_runs - failed_runs) / total_runs) * 100) if total_runs > 0 else 0,
            "lastGrantsProcessed": last_meta.get("grants_scored", 0) or last_meta.get("new_grants", 0),
        })

    return results


@router.get("/run-history")
async def v2_run_history(limit: int = Query(50)):
    """Run history from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        """SELECT * FROM audit_logs
           WHERE node IN ('scout', 'analyst', 'drafter', 'company_brain', 'grant_reader')
           ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    )

    result = []
    for r in rows:
        d = dict(r)
        entry: dict = {
            "_id": str(d.pop("id", "")),
            "node": d.get("node", ""),
            "action": d.get("action", ""),
            "created_at": d.get("created_at", ""),
        }
        try:
            meta = json.loads(d.get("metadata_json", "{}") or "{}")
            entry.update(meta)
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(entry)

    return result


@router.get("/error-timeline")
async def v2_error_timeline(days: int = Query(7)):
    """Error timeline from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        """SELECT * FROM audit_logs
           WHERE created_at >= datetime('now', ?)
             AND (action LIKE '%fail%' OR action LIKE '%error%')
           ORDER BY created_at DESC LIMIT 50""",
        (f"-{days} days",),
    )

    return [
        {
            "date": (dict(r).get("created_at", "") or "")[:10],
            "agent": dict(r).get("node", "unknown"),
            "message": dict(r).get("action", "Error"),
            "created_at": dict(r).get("created_at", ""),
        }
        for r in rows
    ]


# ── Scout Runs (from SQLite) ─────────────────────────────────────────────────

@router.get("/scout-runs")
async def v2_scout_runs(limit: int = Query(10)):
    """Scout run details from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        "SELECT * FROM scout_runs ORDER BY run_at DESC LIMIT ?",
        (limit,),
    )

    result = []
    for r in rows:
        d = dict(r)
        entry: dict = {"_id": str(d.pop("id", "")), "run_at": d.get("run_at", "")}
        try:
            run_data = json.loads(d.get("run_json", "{}") or "{}")
            entry.update(run_data)
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(entry)

    return result


# ── Knowledge (from SQLite) ──────────────────────────────────────────────────

@router.get("/knowledge/status")
async def v2_knowledge_status():
    """Knowledge health from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()

    total_r = await conn.execute_fetchall("SELECT COUNT(*) as c FROM knowledge_chunks")
    total = dict(total_r[0])["c"] if total_r else 0

    notion_r = await conn.execute_fetchall(
        "SELECT COUNT(*) as c FROM knowledge_chunks WHERE doc_type = 'notion'"
    )
    notion = dict(notion_r[0])["c"] if notion_r else 0

    drive_r = await conn.execute_fetchall(
        "SELECT COUNT(*) as c FROM knowledge_chunks WHERE doc_type = 'drive'"
    )
    drive = dict(drive_r[0])["c"] if drive_r else 0

    pg_r = await conn.execute_fetchall(
        "SELECT COUNT(*) as c FROM knowledge_chunks WHERE doc_type = 'past_grant_application'"
    )
    past_grants = dict(pg_r[0])["c"] if pg_r else 0

    by_type_r = await conn.execute_fetchall(
        "SELECT doc_type, COUNT(*) as c FROM knowledge_chunks GROUP BY doc_type"
    )
    by_type = {dict(r)["doc_type"]: dict(r)["c"] for r in by_type_r}

    by_theme: dict[str, int] = {}
    theme_rows = await conn.execute_fetchall(
        "SELECT themes FROM knowledge_chunks WHERE themes != '[]'"
    )
    for r in theme_rows:
        try:
            themes = json.loads(dict(r)["themes"])
            for t in themes:
                by_theme[t] = by_theme.get(t, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    last_sync_r = await conn.execute_fetchall(
        "SELECT created_at FROM knowledge_sync_logs ORDER BY created_at DESC LIMIT 1"
    )
    last_synced = dict(last_sync_r[0])["created_at"] if last_sync_r else None

    status = "healthy" if total >= 200 else ("thin" if total >= 50 else "critical")

    return {
        "total_chunks": total,
        "notion_chunks": notion,
        "drive_chunks": drive,
        "past_grant_chunks": past_grants,
        "by_type": by_type,
        "by_theme": by_theme,
        "last_synced": last_synced,
        "status": status,
    }


@router.get("/knowledge/sync-logs")
async def v2_sync_logs(limit: int = Query(5)):
    """Knowledge sync logs from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        "SELECT * FROM knowledge_sync_logs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )

    result = []
    for r in rows:
        d = dict(r)
        d["_id"] = str(d.pop("id", ""))
        # Alias fields to match what the frontend expects
        d["source"] = d.get("source_id", "")
        d["total_chunks"] = d.get("chunks_upserted", 0)
        d["synced_at"] = d.get("created_at", "")
        result.append(d)
    return result


# ── Agent Config (from SQLite) ───────────────────────────────────────────────

@router.get("/agent-config")
async def v2_get_agent_config(agent: Optional[str] = None):
    """Get agent config from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()

    if agent:
        rows = await conn.execute_fetchall(
            "SELECT * FROM agent_config WHERE agent = ?", (agent,)
        )
        if not rows:
            return {"agent": agent}
        d = dict(rows[0])
        try:
            config = json.loads(d.get("config_json", "{}") or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        return {"_id": agent, "agent": agent, **config}

    rows = await conn.execute_fetchall("SELECT * FROM agent_config")
    result = {}
    for r in rows:
        d = dict(r)
        try:
            config = json.loads(d.get("config_json", "{}") or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        a = d["agent"]
        result[a] = {"_id": a, "agent": a, **config}
    return result


@router.post("/agent-config")
async def v2_save_agent_config(body: dict = Body(...)):
    """Save agent config to SQLite."""
    from backend.db.sqlite import get_conn

    agent = body.pop("agent", None)
    if not agent:
        return JSONResponse({"error": "agent is required"}, status_code=400)

    conn = await get_conn()
    config_json = json.dumps(body)
    now = datetime.now(timezone.utc).isoformat()

    await conn.execute(
        """INSERT INTO agent_config (agent, config_json, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(agent) DO UPDATE SET config_json = ?, updated_at = ?""",
        (agent, config_json, now, config_json, now),
    )
    await conn.commit()
    return {"ok": True}


# ── Notifications (from SQLite) ──────────────────────────────────────────────

@router.get("/notifications")
async def v2_notifications(limit: int = Query(30), unread_only: bool = False):
    """Notifications from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()

    where = "read = 0" if unread_only else "1=1"
    rows = await conn.execute_fetchall(
        f"SELECT * FROM notifications WHERE {where} ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )

    result = []
    for r in rows:
        d = dict(r)
        meta: dict = {}
        try:
            meta = json.loads(d.pop("metadata_json", "{}") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        result.append({
            "_id": str(d.get("id", "")),
            "type": d.get("type", ""),
            "title": d.get("title", ""),
            "body": d.get("body", ""),
            "action_url": d.get("action_url", ""),
            "priority": meta.get("priority", "normal"),
            "read": bool(d.get("read", 0)),
            "read_at": meta.get("read_at"),
            "created_at": d.get("created_at", ""),
            "metadata": meta,
        })

    return result


@router.get("/notifications/count")
async def v2_notification_count():
    """Unread notification count from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall("SELECT COUNT(*) as c FROM notifications WHERE read = 0")
    return {"count": dict(rows[0])["c"] if rows else 0}


@router.post("/notifications/mark-read")
async def v2_mark_notifications_read(body: dict = Body(...)):
    """Mark specific notifications as read."""
    from backend.db.sqlite import get_conn

    ids = body.get("ids", [])
    if not ids:
        return {"ok": True}

    conn = await get_conn()
    placeholders = ",".join(["?"] * len(ids))
    await conn.execute(
        f"UPDATE notifications SET read = 1 WHERE id IN ({placeholders})",
        [int(i) for i in ids],
    )
    await conn.commit()
    return {"ok": True}


@router.post("/notifications/mark-all-read")
async def v2_mark_all_read():
    """Mark all notifications as read."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    await conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
    await conn.commit()
    return {"ok": True}


# ── Comments (from SQLite) ───────────────────────────────────────────────────

@router.get("/comments/{grant_id}")
async def v2_get_comments(grant_id: str):
    """Get grant comments from SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    rows = await conn.execute_fetchall(
        "SELECT * FROM grant_comments WHERE grant_id = ? ORDER BY created_at ASC LIMIT 100",
        (grant_id,),
    )

    return [
        {
            "_id": str(dict(r).get("id", "")),
            "grant_id": dict(r).get("grant_id", ""),
            "user_name": dict(r).get("user_name", ""),
            "user_email": dict(r).get("user_email", ""),
            "message": dict(r).get("text", ""),
            "created_at": dict(r).get("created_at", ""),
            "parent_id": None,
            "pinned": False,
            "reactions": {},
            "edited_at": None,
        }
        for r in rows
    ]


@router.post("/comments/{grant_id}")
async def v2_add_comment(grant_id: str, body: dict = Body(...)):
    """Add a grant comment to SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    now = datetime.now(timezone.utc).isoformat()

    cursor = await conn.execute(
        """INSERT INTO grant_comments (grant_id, user_name, user_email, text, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            grant_id,
            body.get("user_name", "Team Member"),
            body.get("user_email", ""),
            body.get("message", ""),
            now,
        ),
    )
    await conn.commit()
    new_id = cursor.lastrowid

    return {
        "_id": str(new_id),
        "grant_id": grant_id,
        "user_name": body.get("user_name", "Team Member"),
        "user_email": body.get("user_email", ""),
        "message": body.get("message", ""),
        "created_at": now,
        "parent_id": None,
        "pinned": False,
        "reactions": {},
        "edited_at": None,
    }


@router.patch("/comments/{comment_id}")
async def v2_patch_comment(comment_id: str, body: dict = Body(...)):
    """Update a comment (pin, react, edit) in SQLite."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()
    action = body.get("action")

    if action == "pin":
        await conn.execute(
            "UPDATE grant_comments SET text = text WHERE id = ?",  # no-op, pinning not supported in SQLite schema yet
            (int(comment_id),),
        )
    elif action == "edit":
        message = body.get("message", "").strip()
        if not message:
            return JSONResponse({"error": "message required"}, status_code=400)
        await conn.execute(
            "UPDATE grant_comments SET text = ? WHERE id = ?",
            (message, int(comment_id)),
        )
        await conn.commit()

    return {"ok": True}


# ── What's New Digest (mixed: Notion + SQLite) ──────────────────────────────

@router.get("/whats-new")
async def v2_whats_new(since: str = Query(...)):
    """What's new digest combining Notion + SQLite data."""
    from backend.db.sqlite import get_conn

    conn = await get_conn()

    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        since_dt = datetime.now(timezone.utc)
    days_since = max(1, (datetime.now(timezone.utc) - since_dt).days)

    # SQLite counts
    scout_r = await conn.execute_fetchall(
        "SELECT COUNT(*) as c FROM scout_runs WHERE run_at >= ?", (since,)
    )
    scout_runs = dict(scout_r[0])["c"] if scout_r else 0

    error_r = await conn.execute_fetchall(
        """SELECT COUNT(*) as c FROM audit_logs
           WHERE created_at >= ? AND (action LIKE '%fail%' OR action LIKE '%error%')""",
        (since,),
    )
    errors = dict(error_r[0])["c"] if error_r else 0

    activity_r = await conn.execute_fetchall(
        "SELECT * FROM audit_logs WHERE created_at >= ? ORDER BY created_at DESC LIMIT 8",
        (since,),
    )
    recent_runs = [
        {
            "agent": dict(r).get("node", "system"),
            "action": dict(r).get("action", ""),
            "created_at": dict(r).get("created_at", ""),
        }
        for r in activity_r
    ]

    # Notion: grant stats (cached)
    all_grants = await _cached_all_grants()
    triage_grants = [g for g in all_grants if g.get("status") in ("triage", "raw")]
    urgent_grants = [
        g for g in all_grants
        if g.get("deadline_urgent") and g.get("status") in ("triage", "pursue")
    ]

    sorted_grants = sorted(
        all_grants, key=lambda g: g.get("weighted_total", 0) or 0, reverse=True
    )[:5]
    top_new = [
        {
            "_id": g.get("notion_page_id", ""),
            "grant_name": g.get("grant_name") or g.get("title") or "Untitled",
            "funder": g.get("funder") or "Unknown",
            "weighted_total": g.get("weighted_total"),
            "themes_detected": g.get("themes_detected") or [],
            "scored_at": None,
        }
        for g in sorted_grants
    ]

    return {
        "daysSinceVisit": days_since,
        "scoutRuns": scout_runs,
        "totalFound": len(all_grants),
        "newGrantsAdded": len(all_grants),
        "grantsScored": len([g for g in all_grants if g.get("weighted_total", 0)]),
        "newInTriage": len(triage_grants),
        "urgentDeadlines": len(urgent_grants),
        "errors": errors,
        "topNewGrants": top_new,
        "recentAgentRuns": recent_runs,
    }
