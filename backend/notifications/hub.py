"""Notification hub — persists in-app notifications and broadcasts via Pusher.

No email channel. Two delivery paths:
  1. MongoDB `notifications` collection (in-app bell icon)
  2. Pusher channel `notifications` (real-time push to browser)

All calls are fire-and-forget — never block the caller.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Lazy Pusher import — optional dependency
_pusher_client = None


def _get_pusher():
    """Lazy-init Pusher client. Returns None if not configured."""
    global _pusher_client
    if _pusher_client is not None:
        return _pusher_client

    try:
        import pusher as pusher_lib
    except ImportError:
        logger.debug("pusher package not installed — Pusher notifications disabled")
        return None

    app_id = os.environ.get("PUSHER_APP_ID")
    key = os.environ.get("NEXT_PUBLIC_PUSHER_KEY")
    secret = os.environ.get("PUSHER_SECRET")
    cluster = os.environ.get("NEXT_PUBLIC_PUSHER_CLUSTER")

    if not all([app_id, key, secret, cluster]):
        return None

    _pusher_client = pusher_lib.Pusher(
        app_id=app_id,
        key=key,
        secret=secret,
        cluster=cluster,
        ssl=True,
    )
    return _pusher_client


async def notify(
    event_type: str,
    title: str,
    body: str,
    action_url: str = "/dashboard",
    priority: str = "normal",
    metadata: Optional[dict] = None,
    user_email: str = "all",
) -> None:
    """Emit a notification to MongoDB + Pusher.

    Args:
        event_type: scout_complete | triage_needed | high_score_grant |
                    draft_section_ready | draft_complete | agent_error |
                    deadline_warning | knowledge_sync
        title: Short headline (e.g. "Scout found 12 new grants")
        body: Detail line
        action_url: Deep-link in the frontend
        priority: "high" | "normal" | "low"
        metadata: Event-specific data dict
        user_email: Target user or "all" for broadcast
    """
    doc = {
        "user_email": user_email,
        "type": event_type,
        "priority": priority,
        "title": title,
        "body": body,
        "action_url": action_url,
        "metadata": metadata or {},
        "read": False,
        "read_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Persist to MongoDB ──
    try:
        from backend.db.mongo import get_db
        db = get_db()
        await db["notifications"].insert_one(doc)
    except Exception as e:
        logger.warning("Failed to persist notification: %s", e)

    # ── Broadcast via Pusher ──
    try:
        p = _get_pusher()
        if p:
            p.trigger("notifications", "notification:new", {
                "type": event_type,
                "title": title,
                "body": body,
                "action_url": action_url,
                "priority": priority,
                "created_at": doc["created_at"],
            })
    except Exception as e:
        logger.debug("Pusher notification broadcast failed: %s", e)

    # ── Broadcast agent status events ──
    if event_type in (
        "scout_complete", "analyst_complete",
        "draft_section_ready", "draft_complete",
    ):
        try:
            p = _get_pusher()
            if p:
                p.trigger("agent-status", f"{event_type}", {
                    "title": title,
                    "body": body,
                    **(metadata or {}),
                })
        except Exception:
            pass


async def notify_scout_complete(
    new_grants: int,
    total_found: int,
    high_score_count: int = 0,
    triage_count: int = 0,
) -> None:
    """Convenience: emit scout completion notification."""
    parts = [f"{new_grants} new grants discovered"]
    if high_score_count:
        parts.append(f"{high_score_count} scored above 7.0")
    if triage_count:
        parts.append(f"{triage_count} ready for triage")

    await notify(
        event_type="scout_complete",
        title=f"Scout found {new_grants} new grants",
        body=". ".join(parts),
        action_url="/triage" if triage_count else "/pipeline",
        priority="high" if high_score_count else "normal",
        metadata={
            "new_grants": new_grants,
            "total_found": total_found,
            "high_score_count": high_score_count,
            "triage_count": triage_count,
        },
    )


async def notify_analyst_complete(
    scored_count: int,
    triage_count: int = 0,
    pursue_count: int = 0,
) -> None:
    """Convenience: emit analyst completion notification."""
    await notify(
        event_type="analyst_complete",
        title=f"Analyst scored {scored_count} grants",
        body=f"{triage_count} shortlisted, {pursue_count} recommended to pursue",
        action_url="/triage" if triage_count else "/pipeline",
        priority="high" if triage_count else "normal",
        metadata={
            "scored_count": scored_count,
            "triage_count": triage_count,
            "pursue_count": pursue_count,
        },
    )


async def notify_high_score_grant(
    grant_name: str,
    grant_id: str,
    score: float,
    funder: str = "",
) -> None:
    """Convenience: emit high-score grant alert."""
    await notify(
        event_type="high_score_grant",
        title=f"High-score grant: {grant_name[:60]}",
        body=f"Score {score:.1f}/10 from {funder}" if funder else f"Score {score:.1f}/10",
        action_url=f"/grants/{grant_id}",
        priority="high",
        metadata={
            "grant_id": grant_id,
            "grant_name": grant_name,
            "score": score,
            "funder": funder,
        },
    )


async def notify_agent_error(
    agent: str,
    error_message: str,
) -> None:
    """Convenience: emit critical agent error notification."""
    await notify(
        event_type="agent_error",
        title=f"Agent error: {agent}",
        body=error_message[:200],
        action_url="/monitoring",
        priority="high",
        metadata={"agent": agent, "error": error_message[:500]},
    )


async def notify_triage_needed(count: int) -> None:
    """Convenience: emit triage queue notification."""
    await notify(
        event_type="triage_needed",
        title=f"{count} grants need triage review",
        body="New high-scoring grants are waiting for your decision",
        action_url="/triage",
        priority="high",
        metadata={"count": count},
    )


async def notify_draft_complete(
    grant_name: str,
    grant_id: str,
    pipeline_id: str,
) -> None:
    """Convenience: emit draft completion notification."""
    await notify(
        event_type="draft_complete",
        title=f"Draft complete: {grant_name[:60]}",
        body="All sections approved and assembled. Ready for download.",
        action_url=f"/drafter",
        priority="high",
        metadata={
            "grant_name": grant_name,
            "grant_id": grant_id,
            "pipeline_id": pipeline_id,
        },
    )
