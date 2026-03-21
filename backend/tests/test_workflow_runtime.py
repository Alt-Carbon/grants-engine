from __future__ import annotations

from copy import deepcopy

import pytest

from backend.platform.contracts import AgentExecutionContext
from backend.platform.orchestrators.mongo import MongoWorkflowOrchestrator


def _get_nested(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_nested(doc: dict, path: str, value):
    cur = doc
    parts = path.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _matches(doc: dict, query: dict) -> bool:
    for key, value in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in value):
                return False
            continue

        actual = _get_nested(doc, key)
        if isinstance(value, dict):
            for op, expected in value.items():
                if op == "$in" and actual not in expected:
                    return False
                if op == "$lt" and not (actual is not None and actual < expected):
                    return False
            continue

        if actual != value:
            return False
    return True


class _InsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeWorkflowCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict):
        stored = deepcopy(doc)
        stored.setdefault("_id", f"id_{len(self.docs) + 1}")
        self.docs.append(stored)
        return _InsertResult(stored["_id"])

    async def find_one(self, query: dict, projection=None, sort=None):
        docs = [deepcopy(doc) for doc in self.docs if _matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda d: _get_nested(d, key), reverse=direction < 0)
        if not docs:
            return None
        doc = docs[0]
        if projection:
            if any(val == 0 for val in projection.values()):
                for field, include in projection.items():
                    if include == 0 and field in doc:
                        doc.pop(field, None)
        return doc

    async def update_one(self, query: dict, update: dict):
        for doc in self.docs:
            if _matches(doc, query):
                self._apply_update(doc, update)
                return

    async def find_one_and_update(self, query: dict, update: dict, sort=None, return_document=None):
        docs = [doc for doc in self.docs if _matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda d: _get_nested(d, key), reverse=direction < 0)
        if not docs:
            return None
        target = docs[0]
        self._apply_update(target, update)
        return deepcopy(target)

    def _apply_update(self, doc: dict, update: dict):
        for key, value in update.get("$set", {}).items():
            _set_nested(doc, key, value)
        for key, value in update.get("$inc", {}).items():
            current = _get_nested(doc, key) or 0
            _set_nested(doc, key, current + value)
        for key, value in update.get("$push", {}).items():
            current = _get_nested(doc, key) or []
            _set_nested(doc, key, [*current, value])


class FakeAuditCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict):
        self.docs.append(deepcopy(doc))
        return _InsertResult(len(self.docs))


@pytest.mark.asyncio
async def test_start_and_complete_workflow(monkeypatch):
    coll = FakeWorkflowCollection()
    monkeypatch.setattr("backend.platform.orchestrators.mongo.workflow_runs", lambda: coll)

    async def handler(payload, context):
        return {"ok": True, "value": payload["value"]}

    orchestrator = MongoWorkflowOrchestrator(handlers={"demo": handler})
    context = AgentExecutionContext(
        project="test",
        workflow_name="demo",
        run_id="run-1",
        request_id="req-1",
    )

    handle = await orchestrator.start_workflow("demo", {"value": 7}, context)
    assert handle["status"] == "pending"

    processed = await orchestrator.drain(limit=1)
    assert processed == 1
    run = await coll.find_one({"workflow_id": "run-1"})
    assert run["status"] == "completed"
    assert run["result"] == {"ok": True, "value": 7}


@pytest.mark.asyncio
async def test_failed_workflow_requeues_when_attempts_remaining(monkeypatch):
    coll = FakeWorkflowCollection()
    monkeypatch.setattr("backend.platform.orchestrators.mongo.workflow_runs", lambda: coll)

    async def handler(payload, context):
        raise RuntimeError("boom")

    orchestrator = MongoWorkflowOrchestrator(
        handlers={"demo": handler},
        default_max_attempts=3,
    )
    context = AgentExecutionContext(
        project="test",
        workflow_name="demo",
        run_id="run-2",
        request_id="req-2",
    )
    await orchestrator.start_workflow("demo", {}, context)

    processed = await orchestrator.drain(limit=1)
    assert processed == 1
    run = await coll.find_one({"workflow_id": "run-2"})
    assert run["status"] == "pending"
    assert run["last_error"] == "boom"
    assert run["attempt_count"] == 1


@pytest.mark.asyncio
async def test_cancel_retry_and_requeue_workflow(monkeypatch):
    workflow_coll = FakeWorkflowCollection()
    audit_coll = FakeAuditCollection()
    monkeypatch.setattr("backend.platform.services.workflow_service.workflow_runs", lambda: workflow_coll)
    monkeypatch.setattr("backend.platform.services.workflow_service.audit_logs", lambda: audit_coll)

    base_run = {
        "workflow_id": "wf-1",
        "workflow_name": "demo",
        "project": "test",
        "status": "pending",
        "payload": {"value": 1},
        "context": {"project": "test", "workflow_name": "demo", "run_id": "wf-1", "request_id": "req-1", "metadata": {}},
        "attempt_count": 0,
        "max_attempts": 3,
        "signals": [],
        "result": None,
        "last_error": None,
        "created_at": "2026-03-21T00:00:00+00:00",
        "updated_at": "2026-03-21T00:00:00+00:00",
        "started_at": None,
        "completed_at": None,
        "lease_expires_at": None,
        "worker_id": None,
    }
    await workflow_coll.insert_one(base_run)

    from backend.platform.services.workflow_service import (
        cancel_workflow_run,
        requeue_workflow_run,
        retry_workflow_run,
    )

    cancelled = await cancel_workflow_run(workflow_id="wf-1", user_email="ops@altcarbon.com")
    assert cancelled["status"] == "cancelled"

    retried = await retry_workflow_run(workflow_id="wf-1", user_email="ops@altcarbon.com")
    assert retried["status"] == "pending"

    requeued = await requeue_workflow_run(workflow_id="wf-1", user_email="ops@altcarbon.com")
    assert requeued["workflow_id"] != "wf-1"
    new_run = await workflow_coll.find_one({"workflow_id": requeued["workflow_id"]})
    assert new_run["status"] == "pending"
    assert new_run["context"]["metadata"]["requeued_from"] == "wf-1"
    assert len(audit_coll.docs) == 3
