# Agentic Platform Blueprint

This repo should evolve from a grants-specific backend into a reusable
fullstack product platform with an agentic core.

## What The Base Platform Should Own

- authentication and user identity
- workflow orchestration
- durable queueing / retries / timeouts
- tool execution contracts
- session and memory ownership
- audit logs and observability
- artifact storage
- human approval checkpoints

## What Project Modules Should Own

- domain schemas
- domain prompts
- domain tools
- workflow definitions
- domain-specific service rules

## Recommended Runtime Shape

```text
Frontend / Product UI
  ->
FastAPI control plane
  ->
Durable orchestrator
  ->
Agent workers
  ->
Tools / services / external systems
  ->
Postgres + Redis + object storage + project data stores
```

## Current Repo Mapping

Today:

- `backend/main.py` mixes API, orchestration, session logic, and workflow rules
- `backend/agents/*` contains project-specific agent logic
- `backend/graph/*` contains grants-specific orchestration state
- `backend/db/*` contains storage access

Target:

- `backend/platform/*` becomes the reusable core
- `backend/projects/grants_engine/*` binds grants-specific workflows to that core
- the current grants flow is migrated gradually, not rewritten in one step

## Immediate Migration Priorities

1. introduce a real auth model beyond shared internal secrets
2. replace in-process FastAPI background tasks with a durable queue/workflow engine
3. move status transitions into a dedicated service layer
4. move session ownership into authenticated user-scoped services
5. split workflow definitions from API route handlers

## New Modules Added In This Step

- `backend/platform/contracts.py`
- `backend/platform/base.py`
- `backend/platform/registry.py`
- `backend/platform/orchestrator.py`
- `backend/platform/orchestrators/mongo.py`
- `backend/platform/services/auth_service.py`
- `backend/platform/services/session_service.py`
- `backend/projects/grants_engine/workflow_blueprint.py`
- `backend/projects/grants_engine/workflow_runtime.py`

These modules are intentionally non-breaking. They provide the reusable typed
foundation that later migrations can target.

## Current Bridge Runtime

The repo now has a Mongo-backed workflow run store that acts as a bridge
between ad hoc `BackgroundTasks` and a future durable runtime like Temporal.

- workflow requests are persisted in `workflow_runs` before execution
- workers claim jobs with leases, so queued work survives process restarts
- the first live paths using this are reviewer execution, analyst execution, draft start, human resume actions, scout, knowledge sync, and admin maintenance jobs
- immediate execution still happens in-process by draining the durable queue

This is not the final orchestration architecture, but it is a safer migration
step than adding more uncaptured background tasks directly in route handlers.
