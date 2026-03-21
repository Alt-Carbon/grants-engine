"""Workflow queue summary helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.db.mongo import audit_logs, workflow_runs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_workflow_queue_summary(*, recent_limit: int = 20) -> dict:
    statuses = ["pending", "running", "completed", "failed", "cancelled", "waiting_human"]
    counts = {
        status: await workflow_runs().count_documents({"status": status})
        for status in statuses
    }

    recent = (
        await workflow_runs()
        .find(
            {},
            {
                "_id": 0,
                "context.metadata": 0,
                "signals": 0,
            },
        )
        .sort("created_at", -1)
        .to_list(length=max(1, min(recent_limit, 100)))
    )

    pipeline = [
        {"$match": {"status": {"$in": ["pending", "running"]}}},
        {"$group": {"_id": "$workflow_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    active_by_workflow = []
    async for row in workflow_runs().aggregate(pipeline):
        active_by_workflow.append(
            {"workflow_name": row["_id"], "count": row["count"]}
        )

    return {
        "counts": counts,
        "active_by_workflow": active_by_workflow,
        "recent_runs": recent,
    }


async def cancel_workflow_run(*, workflow_id: str, user_email: str) -> dict:
    run = await workflow_runs().find_one({"workflow_id": workflow_id})
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    if run.get("status") not in {"pending", "running", "waiting_human"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel workflow in status '{run.get('status')}'",
        )

    now = _now_iso()
    await workflow_runs().update_one(
        {"workflow_id": workflow_id},
        {
            "$set": {
                "status": "cancelled",
                "updated_at": now,
                "completed_at": now,
                "lease_expires_at": None,
                "worker_id": None,
            }
        },
    )
    await audit_logs().insert_one(
        {
            "node": "workflow_ops",
            "action": "workflow_cancelled",
            "workflow_id": workflow_id,
            "workflow_name": run.get("workflow_name"),
            "user_email": user_email,
            "created_at": now,
        }
    )
    return {
        "status": "cancelled",
        "workflow_id": workflow_id,
        "workflow_name": run.get("workflow_name"),
    }


async def retry_workflow_run(*, workflow_id: str, user_email: str) -> dict:
    run = await workflow_runs().find_one({"workflow_id": workflow_id})
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    if run.get("status") not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry workflow in status '{run.get('status')}'",
        )

    now = _now_iso()
    await workflow_runs().update_one(
        {"workflow_id": workflow_id},
        {
            "$set": {
                "status": "pending",
                "updated_at": now,
                "completed_at": None,
                "started_at": None,
                "lease_expires_at": None,
                "worker_id": None,
                "last_error": None,
                "result": None,
            }
        },
    )
    await audit_logs().insert_one(
        {
            "node": "workflow_ops",
            "action": "workflow_retried",
            "workflow_id": workflow_id,
            "workflow_name": run.get("workflow_name"),
            "user_email": user_email,
            "created_at": now,
        }
    )
    return {
        "status": "pending",
        "workflow_id": workflow_id,
        "workflow_name": run.get("workflow_name"),
    }


async def requeue_workflow_run(*, workflow_id: str, user_email: str) -> dict:
    run = await workflow_runs().find_one({"workflow_id": workflow_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    now = _now_iso()
    new_workflow_id = uuid4().hex
    context = dict(run.get("context") or {})
    context["run_id"] = new_workflow_id
    metadata = dict(context.get("metadata") or {})
    metadata["requeued_from"] = workflow_id
    context["metadata"] = metadata

    new_run = {
        **run,
        "workflow_id": new_workflow_id,
        "status": "pending",
        "context": context,
        "attempt_count": 0,
        "signals": [],
        "result": None,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "lease_expires_at": None,
        "worker_id": None,
    }
    await workflow_runs().insert_one(new_run)
    await audit_logs().insert_one(
        {
            "node": "workflow_ops",
            "action": "workflow_requeued",
            "workflow_id": new_workflow_id,
            "source_workflow_id": workflow_id,
            "workflow_name": run.get("workflow_name"),
            "user_email": user_email,
            "created_at": now,
        }
    )
    return {
        "status": "pending",
        "workflow_id": new_workflow_id,
        "source_workflow_id": workflow_id,
        "workflow_name": run.get("workflow_name"),
    }
