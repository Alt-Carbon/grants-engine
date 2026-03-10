"""Notion MCP client — connects to the official Notion MCP server.

Spawns @notionhq/notion-mcp-server via stdio and keeps a persistent
session alive for the lifetime of the FastAPI app. All Notion operations
go through MCP tools: search, retrieve-a-page, create-a-page, etc.

Usage:
    from backend.integrations.notion_mcp import notion_mcp

    # In FastAPI lifespan:
    await notion_mcp.connect()
    ...
    await notion_mcp.disconnect()

    # Anywhere in the app:
    results = await notion_mcp.search("AltCarbon ERW")
    page = await notion_mcp.fetch_page("page-id-here")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)


class NotionMCPClient:
    """Singleton wrapper around the Notion MCP server session."""

    def __init__(self):
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None

    async def connect(self) -> bool:
        """Spawn the Notion MCP server and initialize the session."""
        async with self._lock:
            if self._connected:
                return True

            token = get_settings().notion_token
            if not token:
                logger.warning("NOTION_TOKEN not set — MCP client disabled")
                return False

            # Use globally installed binary if available, else fall back to npx
            import shutil
            if shutil.which("notion-mcp-server"):
                cmd, args = "notion-mcp-server", []
            else:
                cmd, args = "npx", ["-y", "@notionhq/notion-mcp-server"]

            server_params = StdioServerParameters(
                command=cmd,
                args=args,
                env={
                    **os.environ,
                    "NOTION_TOKEN": token,
                },
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

                # Log available tools
                tools = await self._session.list_tools()
                tool_names = [t.name for t in tools.tools]
                logger.info(
                    "Notion MCP connected — %d tools: %s",
                    len(tool_names), ", ".join(tool_names),
                )
                self._connected = True
                return True

            except Exception as e:
                logger.error("Notion MCP connection failed: %s", e)
                if self._exit_stack:
                    await self._exit_stack.aclose()
                    self._exit_stack = None
                self._session = None
                self._connected = False
                return False

    async def disconnect(self):
        """Shut down the MCP server session."""
        async with self._lock:
            if self._exit_stack:
                try:
                    await self._exit_stack.aclose()
                except Exception as e:
                    logger.debug("MCP disconnect error: %s", e)
            self._session = None
            self._exit_stack = None
            self._connected = False
            logger.info("Notion MCP disconnected")

    async def _ensure_connected(self):
        """Reconnect if the session dropped."""
        if not self._connected:
            await self.connect()
        if not self._connected:
            raise RuntimeError("Notion MCP not connected and reconnect failed")

    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool and return parsed result."""
        await self._ensure_connected()
        try:
            result = await self._session.call_tool(tool_name, arguments)
            if result.content and len(result.content) > 0:
                text = result.content[0].text
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
            return None
        except Exception as e:
            logger.error("MCP tool %s failed: %s", tool_name, e)
            # Try reconnecting once
            self._connected = False
            try:
                await self.connect()
                result = await self._session.call_tool(tool_name, arguments)
                if result.content and len(result.content) > 0:
                    text = result.content[0].text
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        return text
                return None
            except Exception as retry_err:
                logger.error("MCP retry also failed: %s", retry_err)
                raise

    # ── High-level API ────────────────────────────────────────────────────────

    async def search(self, query: str, **kwargs) -> List[Dict]:
        """Search Notion workspace. Returns list of results."""
        args = {"query": query, "page_size": 100, **kwargs}
        result = await self._call_tool("API-post-search", args)
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    async def fetch_page(self, page_id: str) -> Optional[str]:
        """Fetch a Notion page with its content blocks. Returns text."""
        # First get page metadata
        result = await self._call_tool("API-retrieve-a-page", {"page_id": page_id})

        # If the MCP server returns markdown/text directly, use it
        if isinstance(result, str) and len(result) > 50:
            return result

        # Extract title from metadata
        title = ""
        if isinstance(result, dict):
            # Check for markdown/text in response
            md = result.get("markdown") or result.get("text")
            if md and len(md) > 50:
                return md
            # Extract title
            props = result.get("properties", {})
            for p in props.values():
                if isinstance(p, dict) and p.get("type") == "title":
                    ta = p.get("title", [])
                    title = "".join(
                        t.get("plain_text", "") for t in ta if isinstance(t, dict)
                    )
                    break

        # Fetch actual content via block children (with pagination)
        try:
            blocks = await self.get_block_children(page_id)
            texts = []
            if title:
                texts.append(f"# {title}\n")
            for block in blocks:
                text = await self._extract_block_text_recursive(block, depth=0)
                if text:
                    texts.append(text)
            if texts:
                return "\n".join(texts)
        except Exception as e:
            logger.debug("Failed to fetch block children for %s: %s", page_id, e)

        # Fallback: return metadata as JSON
        if isinstance(result, dict):
            return json.dumps(result)
        return None

    async def _extract_block_text_recursive(self, block: Dict, depth: int = 0) -> str:
        """Extract plain text from a Notion block, recursing into children (max depth 3)."""
        btype = block.get("type", "")
        bdata = block.get(btype, {})

        # Most block types have rich_text array
        rich_text = bdata.get("rich_text", [])
        if not rich_text and isinstance(bdata, dict):
            rich_text = bdata.get("text", [])

        text = "".join(
            t.get("plain_text", "") for t in rich_text if isinstance(t, dict)
        )

        if not text:
            if btype == "child_page":
                return f"[Subpage: {bdata.get('title', '')}]"
            if btype == "child_database":
                return f"[Database: {bdata.get('title', '')}]"
            if btype == "image":
                caption = bdata.get("caption", [])
                cap_text = "".join(
                    t.get("plain_text", "") for t in caption if isinstance(t, dict)
                )
                return f"[Image: {cap_text}]" if cap_text else ""

        # Add formatting based on block type
        if btype.startswith("heading_1"):
            text = f"# {text}"
        elif btype.startswith("heading_2"):
            text = f"## {text}"
        elif btype.startswith("heading_3"):
            text = f"### {text}"
        elif btype == "bulleted_list_item":
            text = f"• {text}"
        elif btype == "numbered_list_item":
            text = f"- {text}"
        elif btype == "to_do":
            checked = bdata.get("checked", False)
            text = f"[{'x' if checked else ' '}] {text}"
        elif btype == "toggle":
            text = f"▸ {text}"
        elif btype == "quote":
            text = f"> {text}"
        elif btype == "callout":
            icon = block.get("callout", {}).get("icon", {}).get("emoji", "")
            text = f"{icon} {text}" if icon else text
        elif btype == "code":
            text = f"```\n{text}\n```"
        elif btype == "divider":
            text = "---"

        # Recurse into children if present (depth limit 3)
        if block.get("has_children") and depth < 3:
            try:
                children = await self.get_block_children(block["id"])
                child_texts = []
                for child in children:
                    ct = await self._extract_block_text_recursive(child, depth=depth + 1)
                    if ct:
                        child_texts.append(ct)
                if child_texts:
                    text = f"{text}\n{chr(10).join(child_texts)}" if text else "\n".join(child_texts)
            except Exception:
                pass

        return text or ""

    async def get_block_children(self, block_id: str) -> List[Dict]:
        """Fetch child blocks of a page/block with pagination. Returns list of blocks."""
        all_blocks: List[Dict] = []
        cursor: Optional[str] = None

        while True:
            args: Dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            result = await self._call_tool("API-get-block-children", args)
            if isinstance(result, dict):
                all_blocks.extend(result.get("results", []))
                cursor = result.get("next_cursor")
                if not cursor:
                    break
            else:
                break

        return all_blocks

    async def create_page(
        self,
        parent_id: str,
        title: str,
        content: str = "",
        properties: Optional[Dict] = None,
        parent_type: str = "page_id",
    ) -> Optional[str]:
        """Create a new Notion page. Returns the page ID."""
        args: Dict[str, Any] = {}
        if parent_type == "database_id":
            args["parent"] = {"database_id": parent_id}
        else:
            args["parent"] = {"page_id": parent_id}

        page_props = properties or {}
        if "title" not in page_props:
            page_props["title"] = title

        args["properties"] = page_props
        if content:
            args["content"] = content

        result = await self._call_tool("API-post-page", args)
        if isinstance(result, dict):
            return result.get("id")
        return None

    async def update_page(
        self,
        page_id: str,
        properties: Optional[Dict] = None,
        content: Optional[str] = None,
    ) -> bool:
        """Update a Notion page's properties or content."""
        if properties:
            await self._call_tool("API-patch-page", {
                "page_id": page_id,
                "properties": properties,
            })

        if content is not None:
            await self._call_tool("API-patch-page", {
                "page_id": page_id,
                "content": content,
            })

        return True

    async def fetch_database(self, database_id: str) -> Optional[Dict]:
        """Fetch a Notion database schema."""
        result = await self._call_tool("API-retrieve-a-database", {
            "database_id": database_id,
        })
        return result if isinstance(result, dict) else None

    async def query_data_source(
        self,
        data_source_id: str,
        filter_sql: str = "",
        sort: str = "",
        limit: int = 100,
    ) -> List[Dict]:
        """Query a Notion data source (collection)."""
        args: Dict[str, Any] = {"data_source_id": data_source_id}
        if filter_sql:
            args["filter"] = filter_sql
        if sort:
            args["sort"] = sort
        args["limit"] = limit
        result = await self._call_tool("API-query-data-source", args)
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    async def get_comments(self, page_id: str) -> List[Dict]:
        """Get comments on a Notion page."""
        result = await self._call_tool("API-retrieve-a-comment", {
            "page_id": page_id,
        })
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    async def add_comment(self, page_id: str, text: str) -> bool:
        """Add a comment to a Notion page."""
        await self._call_tool("API-create-a-comment", {
            "page_id": page_id,
            "rich_text": [{"text": {"content": text}}],
        })
        return True

    async def health(self) -> Dict:
        """Check MCP connection health."""
        if not self._connected or self._session is None:
            return {"status": "disconnected"}
        try:
            tools = await self._session.list_tools()
            return {
                "status": "connected",
                "tools": len(tools.tools),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ── Singleton instance ────────────────────────────────────────────────────────
notion_mcp = NotionMCPClient()
