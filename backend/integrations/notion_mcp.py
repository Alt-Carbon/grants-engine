"""Notion MCP client — connects to the official Notion MCP server.

Now backed by MCPHub for connection management. The high-level API
(search, fetch_page, create_page, etc.) is unchanged — existing code
continues to work with zero changes.

Usage:
    from backend.integrations.notion_mcp import notion_mcp

    # In FastAPI lifespan (handled by mcp_hub.connect_all()):
    await notion_mcp.connect()
    ...
    await notion_mcp.disconnect()

    # Anywhere in the app:
    results = await notion_mcp.search("AltCarbon ERW")
    page = await notion_mcp.fetch_page("page-id-here")
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Server name in mcp_servers.yaml
_SERVER_NAME = "notion"


class NotionMCPClient:
    """Notion-specific wrapper that delegates to MCPHub for connection management.

    Preserves the exact same high-level API as before (search, fetch_page,
    create_page, update_page, etc.) so existing code is fully backward-compatible.
    """

    @property
    def connected(self) -> bool:
        from backend.integrations.mcp_hub import mcp_hub
        return mcp_hub.is_connected(_SERVER_NAME)

    async def connect(self) -> bool:
        """Connect the Notion MCP server via the hub."""
        from backend.integrations.mcp_hub import mcp_hub
        return await mcp_hub.connect_one(_SERVER_NAME)

    async def disconnect(self):
        """Disconnect the Notion MCP server."""
        from backend.integrations.mcp_hub import mcp_hub
        await mcp_hub.disconnect_one(_SERVER_NAME)

    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool via the hub."""
        from backend.integrations.mcp_hub import mcp_hub
        return await mcp_hub.call_tool(_SERVER_NAME, tool_name, arguments)

    # ── High-level API (unchanged) ───────────────────────────────────────────

    async def search(self, query: str, **kwargs) -> List[Dict]:
        """Search Notion workspace. Returns list of results."""
        args = {"query": query, "page_size": 100, **kwargs}
        result = await self._call_tool("API-post-search", args)
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    async def fetch_page(self, page_id: str) -> Optional[str]:
        """Fetch a Notion page with its content blocks. Returns text."""
        result = await self._call_tool("API-retrieve-a-page", {"page_id": page_id})

        if isinstance(result, str) and len(result) > 50:
            return result

        title = ""
        if isinstance(result, dict):
            md = result.get("markdown") or result.get("text")
            if md and len(md) > 50:
                return md
            props = result.get("properties", {})
            for p in props.values():
                if isinstance(p, dict) and p.get("type") == "title":
                    ta = p.get("title", [])
                    title = "".join(
                        t.get("plain_text", "") for t in ta if isinstance(t, dict)
                    )
                    break

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

        if isinstance(result, dict):
            return json.dumps(result)
        return None

    async def _extract_block_text_recursive(self, block: Dict, depth: int = 0) -> str:
        """Extract plain text from a Notion block, recursing into children (max depth 3)."""
        btype = block.get("type", "")
        bdata = block.get(btype, {})

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
        """Fetch child blocks of a page/block with pagination."""
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
        from backend.integrations.mcp_hub import mcp_hub
        conn = mcp_hub.get_server(_SERVER_NAME)
        if conn:
            return await conn.health()
        return {"status": "disconnected"}


# ── Singleton instance (backward compatible) ─────────────────────────────────
notion_mcp = NotionMCPClient()
