"""Abstract base classes for reusable agents, tools, and workflows."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from backend.platform.contracts import AgentExecutionContext, AgentResult, AgentSpec, ToolSpec, WorkflowDefinition


class BaseAgent(ABC):
    """Reusable agent interface.

    Project implementations should adapt domain-specific prompts/tools to this
    base instead of embedding business logic directly into API routes.
    """

    spec: AgentSpec

    @abstractmethod
    async def arun(
        self,
        payload: Dict[str, Any],
        context: AgentExecutionContext,
    ) -> AgentResult:
        raise NotImplementedError


class BaseTool(ABC):
    """Reusable tool interface."""

    spec: ToolSpec

    @abstractmethod
    async def arun(
        self,
        arguments: Dict[str, Any],
        context: AgentExecutionContext,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class BaseWorkflow(ABC):
    """Reusable workflow interface."""

    definition: WorkflowDefinition

    @abstractmethod
    async def arun(
        self,
        payload: Dict[str, Any],
        context: AgentExecutionContext,
    ) -> Dict[str, Any]:
        raise NotImplementedError
