"""MCP Hub — generic multi-server MCP client manager.

Reads backend/config/mcp_servers.yaml, spawns each enabled server as a stdio
subprocess, and exposes a unified interface for any agent to call tools on any
connected server.

Usage:
    from backend.integrations.mcp_hub import mcp_hub

    # In FastAPI lifespan:
    await mcp_hub.connect_all()
    ...
    await mcp_hub.disconnect_all()

    # Anywhere in the app:
    result = await mcp_hub.call_tool("notion", "API-post-search", {"query": "ERW"})
    tools  = await mcp_hub.list_tools("slack")
    status = await mcp_hub.health()

    # Legacy compat (notion_mcp still works as before):
    from backend.integrations.notion_mcp import notion_mcp
    await notion_mcp.search("AltCarbon")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "mcp_servers.yaml"


# ── Server config dataclass ──────────────────────────────────────────────────

class MCPServerConfig:
    """Parsed config for a single MCP server."""

    def __init__(self, name: str, raw: Dict[str, Any]):
        self.name = name
        self.description: str = raw.get("description", name)
        self.command: str = raw.get("command", "")
        self.npm_package: str = raw.get("npm_package", "")
        self.args: List[str] = raw.get("args", [])
        self.env_map: Dict[str, str] = raw.get("env_map", {})
        self.required_env: List[str] = raw.get("required_env", [])
        self.enabled: bool = raw.get("enabled", True)
        self.tags: List[str] = raw.get("tags", [])


# ── Per-server connection ────────────────────────────────────────────────────

class MCPServerConnection:
    """Manages a single MCP server subprocess + session."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._tools: List[str] = []

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None

    @property
    def tools(self) -> List[str]:
        return list(self._tools)

    async def connect(self) -> bool:
        """Spawn the MCP server and initialize the session."""
        async with self._lock:
            if self._connected:
                return True

            if not self.config.enabled:
                logger.debug("MCP server '%s' is disabled — skipping", self.config.name)
                return False

            # Check required env vars
            missing = [v for v in self.config.required_env if not os.environ.get(v)]
            if missing:
                logger.warning(
                    "MCP server '%s' skipped — missing env vars: %s",
                    self.config.name, ", ".join(missing),
                )
                return False

            # Resolve command: prefer globally installed binary, fall back to npx
            cmd = self.config.command
            args = list(self.config.args)
            if not shutil.which(cmd):
                if self.config.npm_package:
                    cmd, args = "npx", ["-y", self.config.npm_package] + args
                else:
                    logger.warning(
                        "MCP server '%s': command '%s' not found and no npm_package set",
                        self.config.name, self.config.command,
                    )
                    return False

            # Build env: inherit os.environ + mapped env vars
            env = {**os.environ}
            for mcp_var, source_var in self.config.env_map.items():
                val = os.environ.get(source_var, "")
                if val:
                    env[mcp_var] = val

            server_params = StdioServerParameters(
                command=cmd,
                args=args,
                env=env,
            )

            try:
                self._exit_stack = AsyncExitStack()
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                self._session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await self._session.initialize()

                # Cache available tool names
                tools_result = await self._session.list_tools()
                self._tools = [t.name for t in tools_result.tools]
                logger.info(
                    "MCP '%s' connected — %d tools: %s",
                    self.config.name, len(self._tools),
                    ", ".join(self._tools[:10]) + ("..." if len(self._tools) > 10 else ""),
                )
                self._connected = True
                return True

            except Exception as e:
                logger.error("MCP '%s' connection failed: %s", self.config.name, e)
                await self._cleanup()
                return False

    async def disconnect(self):
        """Shut down the MCP server session."""
        async with self._lock:
            await self._cleanup()
            logger.info("MCP '%s' disconnected", self.config.name)

    async def _cleanup(self):
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.debug("MCP '%s' cleanup error: %s", self.config.name, e)
        self._session = None
        self._exit_stack = None
        self._connected = False
        self._tools = []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool. Auto-reconnects once on failure."""
        if not self._connected:
            if not await self.connect():
                raise RuntimeError(f"MCP '{self.config.name}' not connected")

        try:
            return await self._call_tool_raw(tool_name, arguments)
        except Exception as e:
            logger.warning("MCP '%s' tool '%s' failed: %s — retrying", self.config.name, tool_name, e)
            self._connected = False
            if await self.connect():
                return await self._call_tool_raw(tool_name, arguments)
            raise

    async def _call_tool_raw(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        result = await self._session.call_tool(tool_name, arguments)
        if result.content and len(result.content) > 0:
            text = result.content[0].text
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        return None

    async def list_tools_full(self) -> List[Dict]:
        """Return full tool schemas (name + description + inputSchema)."""
        if not self._connected:
            return []
        try:
            result = await self._session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {},
                }
                for t in result.tools
            ]
        except Exception:
            return []

    async def health(self) -> Dict:
        if not self._connected:
            return {
                "name": self.config.name,
                "status": "disconnected",
                "enabled": self.config.enabled,
            }
        try:
            tools = await self._session.list_tools()
            return {
                "name": self.config.name,
                "status": "connected",
                "tools": len(tools.tools),
                "description": self.config.description,
            }
        except Exception as e:
            return {
                "name": self.config.name,
                "status": "error",
                "error": str(e),
            }


# ── Hub: manages all servers ─────────────────────────────────────────────────

class MCPHub:
    """Central registry that manages multiple MCP server connections."""

    def __init__(self):
        self._servers: Dict[str, MCPServerConnection] = {}
        self._configs: Dict[str, MCPServerConfig] = {}

    def _load_config(self) -> Dict[str, MCPServerConfig]:
        """Load and parse mcp_servers.yaml."""
        if not _CONFIG_PATH.exists():
            logger.warning("MCP config not found at %s", _CONFIG_PATH)
            return {}
        try:
            raw = yaml.safe_load(_CONFIG_PATH.read_text())
            servers = raw.get("servers", {})
            return {
                name: MCPServerConfig(name, cfg)
                for name, cfg in servers.items()
            }
        except Exception as e:
            logger.error("Failed to parse MCP config: %s", e)
            return {}

    async def connect_all(self) -> Dict[str, bool]:
        """Connect all enabled MCP servers. Returns {name: connected} map."""
        self._configs = self._load_config()
        results = {}

        for name, config in self._configs.items():
            if not config.enabled:
                logger.debug("MCP '%s' disabled — skipping", name)
                results[name] = False
                continue

            conn = MCPServerConnection(config)
            self._servers[name] = conn
            results[name] = await conn.connect()

        connected = sum(1 for v in results.values() if v)
        total = len(self._configs)
        enabled = sum(1 for c in self._configs.values() if c.enabled)
        logger.info(
            "MCP Hub: %d/%d servers connected (%d enabled, %d total configured)",
            connected, enabled, enabled, total,
        )
        return results

    async def connect_one(self, name: str) -> bool:
        """Connect (or reconnect) a single server by name."""
        if name not in self._configs:
            self._configs = self._load_config()
        config = self._configs.get(name)
        if not config:
            logger.warning("MCP server '%s' not found in config", name)
            return False

        # Disconnect existing if any
        if name in self._servers:
            await self._servers[name].disconnect()

        conn = MCPServerConnection(config)
        self._servers[name] = conn
        return await conn.connect()

    async def disconnect_all(self):
        """Disconnect all MCP servers."""
        for name, conn in self._servers.items():
            try:
                await conn.disconnect()
            except Exception as e:
                logger.debug("MCP '%s' disconnect error: %s", name, e)
        self._servers.clear()

    async def disconnect_one(self, name: str):
        """Disconnect a single server."""
        conn = self._servers.pop(name, None)
        if conn:
            await conn.disconnect()

    # ── Tool access ──────────────────────────────────────────────────────────

    def get_server(self, name: str) -> Optional[MCPServerConnection]:
        """Get a server connection by name (or None if not connected)."""
        return self._servers.get(name)

    def is_connected(self, name: str) -> bool:
        conn = self._servers.get(name)
        return conn.connected if conn else False

    async def call_tool(self, server: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on a specific server."""
        conn = self._servers.get(server)
        if not conn:
            raise RuntimeError(f"MCP server '{server}' not registered")
        return await conn.call_tool(tool_name, arguments)

    async def list_tools(self, server: str) -> List[str]:
        """List tool names for a specific server."""
        conn = self._servers.get(server)
        if not conn:
            return []
        return conn.tools

    async def list_all_tools(self) -> Dict[str, List[str]]:
        """List all tool names across all connected servers."""
        return {
            name: conn.tools
            for name, conn in self._servers.items()
            if conn.connected
        }

    def find_servers_by_tag(self, tag: str) -> List[str]:
        """Find server names that match a given tag (agent name)."""
        return [
            name for name, config in self._configs.items()
            if tag in config.tags and name in self._servers and self._servers[name].connected
        ]

    # ── Status ───────────────────────────────────────────────────────────────

    async def health(self) -> Dict:
        """Full health check for all configured servers."""
        server_health = []
        for name in self._configs:
            conn = self._servers.get(name)
            if conn:
                server_health.append(await conn.health())
            else:
                server_health.append({
                    "name": name,
                    "status": "not_started",
                    "enabled": self._configs[name].enabled,
                })

        connected = sum(1 for s in server_health if s.get("status") == "connected")
        return {
            "connected": connected,
            "total": len(self._configs),
            "servers": server_health,
        }

    @property
    def configs(self) -> Dict[str, MCPServerConfig]:
        if not self._configs:
            self._configs = self._load_config()
        return self._configs


# ── Singleton ────────────────────────────────────────────────────────────────
mcp_hub = MCPHub()
