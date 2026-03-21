"""Core contracts for reusable agentic backends.

These models are intentionally project-agnostic. Product-specific code should
live under ``backend/projects/<project_name>`` and bind to these contracts.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepKind(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    HUMAN = "human"
    SERVICE = "service"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentExecutionContext(BaseModel):
    """Context shared across agents, tools, and workflow steps."""

    project: str
    workflow_name: str
    run_id: str
    request_id: str
    user_email: Optional[str] = None
    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    """Typed reference to a stored artifact or external document."""

    kind: str
    uri: str
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    """Audit record for tool usage."""

    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    output_summary: Optional[str] = None
    success: bool = True
    latency_ms: Optional[int] = None


class AgentResult(BaseModel):
    """Normalized output shape returned by agents."""

    status: str = "ok"
    summary: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class AgentSpec(BaseModel):
    """Contract for an agent worker."""

    name: str
    description: str
    input_schema: str
    output_schema: str
    allowed_tools: List[str] = Field(default_factory=list)
    human_review_required: bool = False
    timeout_seconds: int = 300
    retry_limit: int = 2
    tags: List[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    """Contract for a callable tool."""

    name: str
    description: str
    input_schema: str
    output_schema: str
    read_only: bool = True
    timeout_seconds: int = 60
    tags: List[str] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    """Single step in a durable workflow definition."""

    id: str
    kind: StepKind
    target: str
    description: str
    next_steps: List[str] = Field(default_factory=list)
    checkpoint: bool = False
    timeout_seconds: int = 300
    retry_limit: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    """Project workflow definition that can be executed by an orchestrator."""

    name: str
    project: str
    version: str
    description: str
    entrypoint: str
    steps: List[WorkflowStep]
    default_timeout_seconds: int = 3600
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HumanTask(BaseModel):
    """Human approval or review checkpoint."""

    task_type: str
    title: str
    instructions: str
    assignee: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
