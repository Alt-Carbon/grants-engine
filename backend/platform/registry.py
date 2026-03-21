"""Simple in-memory registry for platform contracts.

This is intentionally lightweight for now. Later this can be backed by a
plugin loader or dependency-injection container.
"""
from __future__ import annotations

from typing import Dict

from backend.platform.base import BaseAgent, BaseTool, BaseWorkflow


class PlatformRegistry:
    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}
        self._tools: Dict[str, BaseTool] = {}
        self._workflows: Dict[str, BaseWorkflow] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        self._agents[agent.spec.name] = agent

    def register_tool(self, tool: BaseTool) -> None:
        self._tools[tool.spec.name] = tool

    def register_workflow(self, workflow: BaseWorkflow) -> None:
        self._workflows[workflow.definition.name] = workflow

    def get_agent(self, name: str) -> BaseAgent:
        return self._agents[name]

    def get_tool(self, name: str) -> BaseTool:
        return self._tools[name]

    def get_workflow(self, name: str) -> BaseWorkflow:
        return self._workflows[name]


platform_registry = PlatformRegistry()
