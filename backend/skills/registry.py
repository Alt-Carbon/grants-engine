"""Skill Registry — discovers, resolves, and executes pipeline skills.

Each skill is a high-level capability (e.g., "fetch_page", "vector_search")
backed by one or more providers in a fallback chain. The registry tries each
provider in order until one succeeds.

Provider types:
  - mcp:      Call a tool on an MCP server (via mcp_hub)
  - api:      Call a Python async function (dotted path)
  - internal: Same as api (alias for clarity — means no external dep)
  - static:   Call a synchronous Python function (file reads, etc.)

Usage:
    from backend.skills import skills

    # Execute a skill (tries provider chain automatically)
    result = await skills.execute("fetch_page", url="https://example.com")

    # Check what skills an agent has access to
    agent_skills = skills.for_agent("scout")

    # Get full skill info
    info = skills.get("vector_search")
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "skills.yaml"


# ── Skill data classes ───────────────────────────────────────────────────────

class SkillProvider:
    """A single provider in a skill's fallback chain."""

    def __init__(self, raw: Dict[str, Any]):
        self.type: str = raw.get("type", "internal")  # mcp | api | internal | static
        self.name: str = raw.get("name", "unknown")
        self.server: str = raw.get("server", "")       # MCP server name
        self.tool: str = raw.get("tool", "")            # MCP tool name
        self.function: str = raw.get("function", "")    # Python dotted path
        self.fallback_message: str = raw.get("fallback_message", "")

    def __repr__(self) -> str:
        if self.type == "mcp":
            return f"<Provider {self.name}: mcp/{self.server}/{self.tool}>"
        return f"<Provider {self.name}: {self.type}/{self.function}>"


class Skill:
    """A high-level pipeline capability with a provider fallback chain."""

    def __init__(self, name: str, raw: Dict[str, Any]):
        self.name = name
        self.description: str = raw.get("description", "")
        self.category: str = raw.get("category", "misc")
        self.agents: List[str] = raw.get("agents", [])
        self.providers: List[SkillProvider] = [
            SkillProvider(p) for p in raw.get("providers", [])
        ]
        self.required_env: List[str] = raw.get("required_env", [])
        self.enabled: bool = raw.get("enabled", True)

    def __repr__(self) -> str:
        return f"<Skill {self.name} [{self.category}] providers={len(self.providers)}>"

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "agents": self.agents,
            "enabled": self.enabled,
            "providers": [
                {"name": p.name, "type": p.type, "available": True}
                for p in self.providers
            ],
        }


# ── Registry ─────────────────────────────────────────────────────────────────

class SkillRegistry:
    """Central registry for all pipeline skills."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._loaded = False

    def _load(self):
        """Load skills from YAML config."""
        if self._loaded:
            return
        try:
            raw = yaml.safe_load(_CONFIG_PATH.read_text())
            for name, cfg in (raw.get("skills") or {}).items():
                self._skills[name] = Skill(name, cfg)
            logger.info("Skill registry loaded: %d skills", len(self._skills))
            self._loaded = True
        except Exception as e:
            logger.error("Failed to load skills config: %s", e)
            self._loaded = True  # Don't retry on error

    def _ensure_loaded(self):
        if not self._loaded:
            self._load()

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        self._ensure_loaded()
        return self._skills.get(name)

    def all(self) -> Dict[str, Skill]:
        """Get all registered skills."""
        self._ensure_loaded()
        return dict(self._skills)

    def for_agent(self, agent: str) -> List[Skill]:
        """Get all skills available to a specific agent."""
        self._ensure_loaded()
        return [s for s in self._skills.values() if agent in s.agents and s.enabled]

    def by_category(self, category: str) -> List[Skill]:
        """Get all skills in a category."""
        self._ensure_loaded()
        return [s for s in self._skills.values() if s.category == category]

    def categories(self) -> Dict[str, List[str]]:
        """Return {category: [skill_names]}."""
        self._ensure_loaded()
        cats: Dict[str, List[str]] = {}
        for s in self._skills.values():
            cats.setdefault(s.category, []).append(s.name)
        return cats

    # ── Execution ────────────────────────────────────────────────────────────

    async def execute(self, skill_name: str, **kwargs) -> Any:
        """Execute a skill, trying providers in fallback order.

        Args:
            skill_name: Name of the skill to execute
            **kwargs: Arguments passed to the provider function/tool

        Returns:
            Result from the first successful provider

        Raises:
            SkillError: If all providers fail or skill not found
        """
        self._ensure_loaded()
        skill = self._skills.get(skill_name)
        if not skill:
            raise SkillError(f"Skill '{skill_name}' not found")
        if not skill.enabled:
            raise SkillError(f"Skill '{skill_name}' is disabled")

        errors = []
        for provider in skill.providers:
            try:
                result = await self._execute_provider(provider, kwargs)
                logger.debug(
                    "Skill '%s' succeeded via provider '%s'",
                    skill_name, provider.name,
                )
                return result
            except Exception as e:
                if provider.fallback_message:
                    logger.debug("%s: %s", provider.fallback_message, e)
                else:
                    logger.debug(
                        "Skill '%s' provider '%s' failed: %s",
                        skill_name, provider.name, e,
                    )
                errors.append((provider.name, str(e)))

        raise SkillError(
            f"Skill '{skill_name}' failed — all {len(errors)} providers exhausted: "
            + "; ".join(f"{n}: {e}" for n, e in errors)
        )

    async def _execute_provider(self, provider: SkillProvider, kwargs: Dict) -> Any:
        """Execute a single provider."""
        if provider.type == "mcp":
            return await self._execute_mcp(provider, kwargs)
        elif provider.type in ("api", "internal"):
            return await self._execute_function(provider, kwargs)
        elif provider.type == "static":
            return self._execute_static(provider, kwargs)
        else:
            raise SkillError(f"Unknown provider type: {provider.type}")

    async def _execute_mcp(self, provider: SkillProvider, kwargs: Dict) -> Any:
        """Execute via MCP Hub."""
        from backend.integrations.mcp_hub import mcp_hub
        if not mcp_hub.is_connected(provider.server):
            raise SkillError(f"MCP server '{provider.server}' not connected")
        return await mcp_hub.call_tool(provider.server, provider.tool, kwargs)

    async def _execute_function(self, provider: SkillProvider, kwargs: Dict) -> Any:
        """Execute a Python async function by dotted path."""
        func = _resolve_function(provider.function)
        result = func(**kwargs)
        # Handle both async and sync functions
        if hasattr(result, "__await__"):
            return await result
        return result

    def _execute_static(self, provider: SkillProvider, kwargs: Dict) -> Any:
        """Execute a synchronous Python function."""
        func = _resolve_function(provider.function)
        return func(**kwargs)

    # ── Status ───────────────────────────────────────────────────────────────

    async def health(self) -> Dict:
        """Return full skill registry status."""
        self._ensure_loaded()
        from backend.integrations.mcp_hub import mcp_hub

        categories = {}
        for skill in self._skills.values():
            cat = categories.setdefault(skill.category, [])

            # Check which providers are available
            available_providers = []
            for p in skill.providers:
                available = True
                if p.type == "mcp":
                    available = mcp_hub.is_connected(p.server)
                elif p.required_env if hasattr(p, "required_env") else False:
                    available = all(os.environ.get(v) for v in p.required_env)
                available_providers.append({
                    "name": p.name,
                    "type": p.type,
                    "available": available,
                })

            cat.append({
                "name": skill.name,
                "description": skill.description,
                "enabled": skill.enabled,
                "providers": available_providers,
                "any_available": any(p["available"] for p in available_providers),
            })

        return {
            "total_skills": len(self._skills),
            "enabled": sum(1 for s in self._skills.values() if s.enabled),
            "categories": categories,
        }

    def agent_manifest(self, agent: str) -> List[Dict]:
        """Return a manifest of skills available to an agent (for LLM tool-use)."""
        agent_skills = self.for_agent(agent)
        return [
            {
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "providers": [p.name for p in s.providers],
            }
            for s in agent_skills
        ]


# ── Helpers ──────────────────────────────────────────────────────────────────

_function_cache: Dict[str, Any] = {}


def _resolve_function(dotted_path: str) -> Any:
    """Resolve a dotted path like 'backend.agents.scout:_fetch_content' to a callable."""
    if dotted_path in _function_cache:
        return _function_cache[dotted_path]

    if ":" in dotted_path:
        module_path, attr_path = dotted_path.rsplit(":", 1)
    elif "." in dotted_path:
        # Try last segment as function name
        parts = dotted_path.rsplit(".", 1)
        module_path, attr_path = parts[0], parts[1]
    else:
        raise SkillError(f"Cannot resolve function path: {dotted_path}")

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise SkillError(f"Cannot import module '{module_path}': {e}")

    # Handle nested attrs like 'ClassName.method'
    obj = module
    for part in attr_path.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError:
            raise SkillError(f"Cannot find '{part}' in '{module_path}'")

    _function_cache[dotted_path] = obj
    return obj


class SkillError(Exception):
    """Raised when a skill execution fails."""
    pass


# ── Singleton ────────────────────────────────────────────────────────────────
skills = SkillRegistry()
