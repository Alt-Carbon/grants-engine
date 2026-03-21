"""Durable workflow orchestrator contract.

The current grants backend still uses FastAPI BackgroundTasks plus LangGraph.
This module defines the abstraction that should eventually be backed by
Temporal or another durable workflow engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from backend.platform.contracts import AgentExecutionContext, WorkflowStatus


class WorkflowHandle(dict):
    """Opaque workflow handle returned by an orchestrator."""


class WorkflowOrchestrator(ABC):
    @abstractmethod
    async def start_workflow(
        self,
        workflow_name: str,
        payload: Dict[str, Any],
        context: AgentExecutionContext,
    ) -> WorkflowHandle:
        raise NotImplementedError

    @abstractmethod
    async def signal_workflow(
        self,
        workflow_id: str,
        signal_name: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_status(self, workflow_id: str) -> WorkflowStatus:
        raise NotImplementedError
