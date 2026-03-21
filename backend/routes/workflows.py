"""Workflow management routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.routes.deps import get_user_email, verify_internal

router = APIRouter(tags=["workflows"])


@router.get("/workflows/summary")
async def get_workflow_summary(
    _: None = Depends(verify_internal),
    recent_limit: int = 20,
):
    from backend.platform.services.workflow_service import get_workflow_queue_summary

    return await get_workflow_queue_summary(recent_limit=recent_limit)


@router.get("/workflows/{workflow_id}")
async def get_workflow_status(
    workflow_id: str,
    _: None = Depends(verify_internal),
):
    from backend.projects.grants_engine.workflow_runtime import get_workflow_run

    run = await get_workflow_run(workflow_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


@router.post("/workflows/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    _: None = Depends(verify_internal),
    user_email: str = Depends(get_user_email),
):
    from backend.platform.services.workflow_service import cancel_workflow_run

    return await cancel_workflow_run(workflow_id=workflow_id, user_email=user_email)


@router.post("/workflows/{workflow_id}/retry")
async def retry_workflow(
    workflow_id: str,
    _: None = Depends(verify_internal),
    user_email: str = Depends(get_user_email),
):
    from backend.platform.services.workflow_service import retry_workflow_run

    return await retry_workflow_run(workflow_id=workflow_id, user_email=user_email)


@router.post("/workflows/{workflow_id}/requeue")
async def requeue_workflow(
    workflow_id: str,
    _: None = Depends(verify_internal),
    user_email: str = Depends(get_user_email),
):
    from backend.platform.services.workflow_service import requeue_workflow_run

    return await requeue_workflow_run(workflow_id=workflow_id, user_email=user_email)


@router.post("/workflows/drain")
async def drain_workflows_endpoint(
    _: None = Depends(verify_internal),
    workflow_name: Optional[str] = None,
    limit: int = 10,
):
    from backend.projects.grants_engine.workflow_runtime import drain_grants_workflows

    workflow_names = [workflow_name] if workflow_name else None
    processed = await drain_grants_workflows(
        workflow_names=workflow_names,
        limit=max(1, min(limit, 100)),
    )
    return {
        "status": "drained",
        "processed": processed,
        "workflow_name": workflow_name,
    }
