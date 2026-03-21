"""Reusable drafter session persistence service."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from backend.db.mongo import audit_logs, chat_snapshots, drafter_chat_history


logger = logging.getLogger(__name__)


async def _find_history_doc_with_migration(pipeline_id: str, user_email: str) -> dict | None:
    doc = await drafter_chat_history().find_one(
        {"pipeline_id": pipeline_id, "user_email": user_email}
    )
    if doc:
        return doc

    legacy_doc = await drafter_chat_history().find_one(
        {
            "pipeline_id": pipeline_id,
            "$or": [
                {"user_email": {"$exists": False}},
                {"user_email": None},
            ],
        }
    )
    if not legacy_doc:
        return None

    await drafter_chat_history().update_one(
        {"_id": legacy_doc["_id"]},
        {"$set": {"user_email": user_email}},
    )
    legacy_doc["user_email"] = user_email
    return legacy_doc


async def _write_audit_log(
    *,
    action: str,
    pipeline_id: str,
    user_email: str,
    grant_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    payload = {
        "node": "session_service",
        "action": action,
        "pipeline_id": pipeline_id,
        "grant_id": grant_id or "",
        "user_email": user_email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    await audit_logs().insert_one(payload)


async def load_chat_history(*, pipeline_id: str, user_email: str) -> dict:
    doc = await _find_history_doc_with_migration(pipeline_id, user_email)
    if not doc:
        return {"pipeline_id": pipeline_id, "sections": {}, "user_email": user_email}

    doc.pop("_id", None)
    doc["user_email"] = user_email
    return doc


async def save_chat_history(
    *,
    pipeline_id: str,
    grant_id: str,
    sections: dict,
    user_email: str,
    session_id: Optional[str] = None,
) -> dict:
    from pymongo.errors import DuplicateKeyError as DupKeyError

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    query = {"pipeline_id": pipeline_id, "user_email": user_email}
    existing = await _find_history_doc_with_migration(pipeline_id, user_email)

    if existing:
        existing_sections = existing.get("sections", {})
        has_content = any(
            len(messages) > 1
            for messages in existing_sections.values()
            if isinstance(messages, list)
        )
        if has_content:
            last_snapshot = await chat_snapshots().find_one(
                {"pipeline_id": pipeline_id, "user_email": user_email},
                sort=[("snapshot_at", -1)],
            )
            should_snapshot = True
            if last_snapshot and last_snapshot.get("session_id") == session_id:
                try:
                    last_time = last_snapshot.get("snapshot_at")
                    if not isinstance(last_time, datetime):
                        last_time = datetime.fromisoformat(
                            str(last_time).replace("Z", "+00:00")
                        )
                    if (now - last_time).total_seconds() < 300:
                        should_snapshot = False
                except Exception:
                    logger.debug("Failed to parse last snapshot timestamp", exc_info=True)

            if should_snapshot:
                await chat_snapshots().insert_one(
                    {
                        "pipeline_id": pipeline_id,
                        "grant_id": grant_id,
                        "user_email": user_email,
                        "session_id": session_id or existing.get("session_id"),
                        "sections": existing_sections,
                        "snapshot_at": now,
                        "message_count": sum(
                            len(messages)
                            for messages in existing_sections.values()
                            if isinstance(messages, list)
                        ),
                        "section_names": list(existing_sections.keys()),
                    }
                )

    update_doc = {
        "pipeline_id": pipeline_id,
        "grant_id": grant_id,
        "sections": sections,
        "updated_at": now_iso,
        "user_email": user_email,
    }
    if session_id:
        update_doc["session_id"] = session_id

    try:
        await drafter_chat_history().replace_one(query, update_doc, upsert=True)
    except DupKeyError:
        await drafter_chat_history().update_one(query, {"$set": update_doc})

    try:
        await drafter_chat_history().delete_many(
            {
                "pipeline_id": pipeline_id,
                "$or": [
                    {"user_email": None},
                    {"user_email": {"$exists": False}},
                ],
            }
        )
    except Exception:
        logger.debug("Legacy drafter chat history cleanup skipped", exc_info=True)

    await _write_audit_log(
        action="chat_history_saved",
        pipeline_id=pipeline_id,
        grant_id=grant_id,
        user_email=user_email,
        extra={"session_id": session_id},
    )
    return {"status": "saved", "pipeline_id": pipeline_id, "user_email": user_email}


async def clear_section_history(
    *,
    pipeline_id: str,
    section_name: str,
    user_email: str,
) -> dict:
    await _find_history_doc_with_migration(pipeline_id, user_email)
    await drafter_chat_history().update_one(
        {"pipeline_id": pipeline_id, "user_email": user_email},
        {"$unset": {f"sections.{section_name}": ""}},
    )
    await _write_audit_log(
        action="chat_history_section_cleared",
        pipeline_id=pipeline_id,
        user_email=user_email,
        extra={"section_name": section_name},
    )
    return {"status": "cleared", "pipeline_id": pipeline_id, "section_name": section_name}


async def list_chat_sessions(
    *,
    pipeline_id: str,
    user_email: str,
    limit: int = 20,
) -> dict:
    docs = (
        await chat_snapshots()
        .find(
            {"pipeline_id": pipeline_id, "user_email": user_email},
            {"sections": 0},
        )
        .sort("snapshot_at", -1)
        .to_list(limit)
    )

    sessions = []
    for doc in docs:
        sessions.append(
            {
                "id": str(doc["_id"]),
                "session_id": doc.get("session_id"),
                "snapshot_at": doc.get("snapshot_at", "").isoformat()
                if hasattr(doc.get("snapshot_at", ""), "isoformat")
                else str(doc.get("snapshot_at", "")),
                "message_count": doc.get("message_count", 0),
                "section_names": doc.get("section_names", []),
                "user_email": user_email,
            }
        )

    return {"pipeline_id": pipeline_id, "sessions": sessions}


async def get_chat_snapshot(
    *,
    pipeline_id: str,
    snapshot_id: str,
    user_email: str,
) -> dict:
    from bson import ObjectId

    try:
        doc = await chat_snapshots().find_one(
            {
                "_id": ObjectId(snapshot_id),
                "pipeline_id": pipeline_id,
                "user_email": user_email,
            }
        )
    except Exception:
        doc = None

    if not doc:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    doc.pop("_id", None)
    doc["user_email"] = user_email
    if hasattr(doc.get("snapshot_at"), "isoformat"):
        doc["snapshot_at"] = doc["snapshot_at"].isoformat()
    return doc


async def restore_chat_snapshot(
    *,
    pipeline_id: str,
    snapshot_id: str,
    user_email: str,
) -> dict:
    from bson import ObjectId
    from pymongo.errors import DuplicateKeyError as DupKeyError

    try:
        snap = await chat_snapshots().find_one(
            {
                "_id": ObjectId(snapshot_id),
                "pipeline_id": pipeline_id,
                "user_email": user_email,
            }
        )
    except Exception:
        snap = None

    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    restore_doc = {
        "pipeline_id": pipeline_id,
        "grant_id": snap.get("grant_id", ""),
        "sections": snap.get("sections", {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": snap.get("session_id"),
        "user_email": user_email,
    }
    query = {"pipeline_id": pipeline_id, "user_email": user_email}

    try:
        await drafter_chat_history().replace_one(query, restore_doc, upsert=True)
    except DupKeyError:
        await drafter_chat_history().update_one(query, {"$set": restore_doc})

    await _write_audit_log(
        action="chat_snapshot_restored",
        pipeline_id=pipeline_id,
        grant_id=restore_doc.get("grant_id"),
        user_email=user_email,
        extra={"snapshot_id": snapshot_id, "session_id": snap.get("session_id")},
    )
    return {"status": "restored", "pipeline_id": pipeline_id, "snapshot_id": snapshot_id}
