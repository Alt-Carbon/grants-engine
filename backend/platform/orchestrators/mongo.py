"""Mongo-backed durable workflow orchestrator."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional
from uuid import uuid4

from pymongo import ReturnDocument

from backend.db.mongo import workflow_runs
from backend.platform.contracts import AgentExecutionContext, WorkflowStatus
from backend.platform.orchestrator import WorkflowHandle, WorkflowOrchestrator


logger = logging.getLogger(__name__)

WorkflowHandler = Callable[[Dict[str, Any], AgentExecutionContext], Awaitable[Dict[str, Any] | None]]


class MongoWorkflowOrchestrator(WorkflowOrchestrator):
    """A small durable queue backed by MongoDB.

    This is a bridge layer until the repo moves to a stronger workflow engine.
    Jobs are persisted before execution so they survive process restarts.
    """

    def __init__(
        self,
        *,
        handlers: Optional[Dict[str, WorkflowHandler]] = None,
        worker_id: Optional[str] = None,
        lease_seconds: int = 300,
        default_max_attempts: int = 3,
    ) -> None:
        self.handlers = handlers or {}
        self.worker_id = worker_id or f"mongo-worker-{uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.default_max_attempts = default_max_attempts

    async def start_workflow(
        self,
        workflow_name: str,
        payload: Dict[str, Any],
        context: AgentExecutionContext,
    ) -> WorkflowHandle:
        now = datetime.now(timezone.utc)
        workflow_id = context.run_id or uuid4().hex
        max_attempts = int(context.metadata.get("max_attempts") or self.default_max_attempts)
        doc = {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "project": context.project,
            "status": WorkflowStatus.PENDING.value,
            "payload": payload,
            "context": context.model_dump(mode="json"),
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "signals": [],
            "result": None,
            "last_error": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "started_at": None,
            "completed_at": None,
            "lease_expires_at": None,
            "worker_id": None,
        }
        await workflow_runs().insert_one(doc)
        return WorkflowHandle(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=WorkflowStatus.PENDING.value,
        )

    async def signal_workflow(
        self,
        workflow_id: str,
        signal_name: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await workflow_runs().update_one(
            {"workflow_id": workflow_id},
            {
                "$push": {
                    "signals": {
                        "signal_name": signal_name,
                        "payload": payload or {},
                        "created_at": now,
                    }
                },
                "$set": {"updated_at": now},
            },
        )

    async def get_status(self, workflow_id: str) -> WorkflowStatus:
        doc = await workflow_runs().find_one({"workflow_id": workflow_id}, {"status": 1})
        if not doc:
            raise KeyError(workflow_id)
        return WorkflowStatus(doc["status"])

    async def get_run(self, workflow_id: str) -> dict | None:
        return await workflow_runs().find_one({"workflow_id": workflow_id}, {"_id": 0})

    async def find_active_run(
        self,
        *,
        workflow_name: str,
        payload_match: Optional[Dict[str, Any]] = None,
    ) -> dict | None:
        query: Dict[str, Any] = {
            "workflow_name": workflow_name,
            "status": {"$in": [WorkflowStatus.PENDING.value, WorkflowStatus.RUNNING.value]},
        }
        for key, value in (payload_match or {}).items():
            query[f"payload.{key}"] = value
        return await workflow_runs().find_one(query, {"_id": 0}, sort=[("created_at", -1)])

    async def drain_once(
        self,
        *,
        allowed_workflows: Optional[Iterable[str]] = None,
    ) -> dict | None:
        now = datetime.now(timezone.utc)
        lease_until = (now + timedelta(seconds=self.lease_seconds)).isoformat()
        query: Dict[str, Any] = {
            "$or": [
                {"status": WorkflowStatus.PENDING.value},
                {
                    "status": WorkflowStatus.RUNNING.value,
                    "lease_expires_at": {"$lt": now.isoformat()},
                },
            ]
        }
        allowed = list(allowed_workflows or [])
        if allowed:
            query["workflow_name"] = {"$in": allowed}

        run = await workflow_runs().find_one_and_update(
            query,
            {
                "$set": {
                    "status": WorkflowStatus.RUNNING.value,
                    "updated_at": now.isoformat(),
                    "started_at": now.isoformat(),
                    "worker_id": self.worker_id,
                    "lease_expires_at": lease_until,
                },
                "$inc": {"attempt_count": 1},
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not run:
            return None

        workflow_name = run["workflow_name"]
        handler = self.handlers.get(workflow_name)
        if handler is None:
            await workflow_runs().update_one(
                {"workflow_id": run["workflow_id"]},
                {
                    "$set": {
                        "status": WorkflowStatus.FAILED.value,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": f"No handler registered for workflow {workflow_name}",
                        "lease_expires_at": None,
                    }
                },
            )
            return run

        context = AgentExecutionContext.model_validate(run["context"])
        try:
            result = await handler(run.get("payload") or {}, context)
        except Exception as exc:
            logger.exception("Workflow %s failed", run["workflow_id"])
            attempts = int(run.get("attempt_count") or 1)
            max_attempts = int(run.get("max_attempts") or self.default_max_attempts)
            next_status = (
                WorkflowStatus.PENDING.value if attempts < max_attempts else WorkflowStatus.FAILED.value
            )
            await workflow_runs().update_one(
                {"workflow_id": run["workflow_id"]},
                {
                    "$set": {
                        "status": next_status,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "completed_at": datetime.now(timezone.utc).isoformat()
                        if next_status == WorkflowStatus.FAILED.value
                        else None,
                        "last_error": str(exc),
                        "lease_expires_at": None,
                    }
                },
            )
            return run

        await workflow_runs().update_one(
            {"workflow_id": run["workflow_id"]},
            {
                "$set": {
                    "status": WorkflowStatus.COMPLETED.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "result": result or {},
                    "last_error": None,
                    "lease_expires_at": None,
                }
            },
        )
        return run

    async def drain(
        self,
        *,
        allowed_workflows: Optional[Iterable[str]] = None,
        limit: int = 10,
    ) -> int:
        processed = 0
        while processed < limit:
            run = await self.drain_once(allowed_workflows=allowed_workflows)
            if not run:
                break
            processed += 1
        return processed
