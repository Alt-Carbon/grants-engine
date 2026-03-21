"""Reusable grant status mutation service."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from backend.db.mongo import audit_logs, grants_pipeline, grants_scored
from backend.pipeline.status_contract import is_valid_transition, pre_draft_cleanup_statuses, valid_statuses


logger = logging.getLogger(__name__)


def _normalize_status(status: str) -> str:
    value = (status or "").strip().lower()
    if value == "pass":
        return "passed"
    return value


async def change_grant_status(
    *,
    grant_id: str,
    new_status: str,
    user_email: str = "system",
    hold_reason: Optional[str] = None,
    source: str = "api",
    sync_notion: bool = True,
) -> dict:
    """Change a grant's status through one validated service path.

    This service updates the canonical grant record, updates only the latest
    relevant pipeline record, and emits a single audit log entry.
    """
    from bson import ObjectId

    normalized_status = _normalize_status(new_status)
    if normalized_status not in valid_statuses():
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status!r}")

    try:
        oid = ObjectId(grant_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid grant_id")

    grant = await grants_scored().find_one({"_id": oid}, {"status": 1, "title": 1, "grant_name": 1})
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    current_status = _normalize_status(grant.get("status") or "")
    if not is_valid_transition(current_status, normalized_status):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invalid pipeline transition: {current_status or 'unknown'} -> {normalized_status}. "
                "Use the appropriate workflow action instead of forcing the status."
            ),
        )

    hold_reason_clean = (hold_reason or "").strip() or None
    if normalized_status == "hold" and not hold_reason_clean:
        raise HTTPException(status_code=422, detail="hold_reason is required when status is 'hold'")

    now = datetime.now(timezone.utc).isoformat()
    update_doc = {"status": normalized_status, "updated_at": now}
    unset_doc: dict[str, str] = {}

    if normalized_status == "human_passed":
        update_doc["human_override"] = True
        update_doc["override_at"] = now

    if normalized_status == "hold":
        update_doc["hold_reason"] = hold_reason_clean
        update_doc["hold_at"] = now
    else:
        unset_doc["hold_reason"] = ""
        unset_doc["hold_at"] = ""

    grant_update: dict = {"$set": update_doc}
    if unset_doc:
        grant_update["$unset"] = unset_doc
    await grants_scored().update_one({"_id": oid}, grant_update)

    if normalized_status in pre_draft_cleanup_statuses():
        await grants_pipeline().update_many(
            {"grant_id": grant_id, "status": {"$in": ["drafting", "pending_interrupt"]}},
            {"$set": {"status": "cancelled", "updated_at": now}},
        )
    else:
        latest_pipeline = await grants_pipeline().find_one(
            {"grant_id": grant_id, "status": {"$nin": ["cancelled"]}},
            sort=[("started_at", -1), ("_id", -1)],
        )
        if latest_pipeline:
            pipeline_update = {"status": normalized_status, "updated_at": now}
            if normalized_status == "hold":
                pipeline_update["hold_reason"] = hold_reason_clean
                pipeline_update["hold_at"] = now
            else:
                pipeline_update["hold_reason"] = None
            await grants_pipeline().update_one(
                {"_id": latest_pipeline["_id"]},
                {"$set": pipeline_update},
            )

    await audit_logs().insert_one({
        "node": "status_service",
        "action": "status_changed",
        "source": source,
        "grant_id": grant_id,
        "grant_name": grant.get("title") or grant.get("grant_name") or "",
        "from_status": current_status,
        "to_status": normalized_status,
        "hold_reason": hold_reason_clean,
        "user_email": user_email,
        "created_at": now,
    })

    if sync_notion:
        try:
            from backend.integrations.notion_sync import update_grant_status

            await update_grant_status(grant_id, normalized_status)
        except Exception:
            logger.debug("Notion status sync skipped for grant %s", grant_id, exc_info=True)

    return {
        "status": "updated",
        "grant_id": grant_id,
        "old_status": current_status,
        "new_status": normalized_status,
    }
