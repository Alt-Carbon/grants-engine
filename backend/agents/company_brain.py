"""Company Brain Agent — AltCarbon's institutional memory.

Syncs from Notion + Google Drive, chunks content, tags with Claude Haiku,
stores in MongoDB (metadata) + Pinecone Integrated Inference (vector search).

Pinecone handles embedding server-side via multilingual-e5-large — no external
embedding API (OpenAI) required.

Query interface: given a grant's themes and requirements, return the most
relevant chunks to ground Analyst scoring and Drafter writing.

Notion sync modes:
- NOTION_KNOWLEDGE_BASE_PAGE_ID set: sync only that page + all descendants (AltCarbon knowledge)
- Otherwise: sync all workspace pages (legacy, with pagination)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx

from backend.config.settings import get_settings
from backend.db.mongo import knowledge_chunks, knowledge_sync_logs
from backend.graph.state import GrantState
from backend.utils.llm import chat, HAIKU, BRAIN_MODEL

logger = logging.getLogger(__name__)

# ── Static knowledge profile (from Notion, cached locally) ─────────────────
_PROFILE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "altcarbon_profile.md"
_SUPPLEMENTS_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "articulation_supplements.md"
_cached_profile: Optional[str] = None
_cached_supplements: Optional[str] = None


def _load_static_profile() -> str:
    """Load the AltCarbon knowledge profile from the local markdown file."""
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile
    try:
        _cached_profile = _PROFILE_PATH.read_text(encoding="utf-8")
        logger.info("Loaded static AltCarbon profile (%d chars)", len(_cached_profile))
    except FileNotFoundError:
        logger.warning("Static profile not found at %s", _PROFILE_PATH)
        _cached_profile = ""
    return _cached_profile


def _load_articulation_supplements() -> str:
    """Load IoT/sensor specs, biochar costs, and LA-ICP-MS details."""
    global _cached_supplements
    if _cached_supplements is not None:
        return _cached_supplements
    try:
        _cached_supplements = _SUPPLEMENTS_PATH.read_text(encoding="utf-8")
        logger.info("Loaded articulation supplements (%d chars)", len(_cached_supplements))
    except FileNotFoundError:
        _cached_supplements = ""
    return _cached_supplements


_s = get_settings()
CHUNK_SIZE = _s.chunk_size           # words
CHUNK_OVERLAP = _s.chunk_overlap     # words
MIN_CHUNK_WORDS = _s.min_chunk_words

TAGGING_PROMPT = """You are tagging a document chunk from AltCarbon's internal knowledge base.
AltCarbon is a climate technology company focused on carbon removal verification and alternative carbon markets.

Chunk:
---
{chunk}
---

Respond ONLY with valid JSON:
{{
  "doc_type": "<one of: company_overview|team_bio|technical_methodology|project_description|impact_metrics|past_grant_application|market_research|financial_data|misc>",
  "themes": ["<from: climatetech|agritech|ai_for_sciences|applied_earth_sciences|social_impact>"],
  "key_topics": ["<2-4 keywords>"],
  "contains_data": <true|false>,
  "is_useful_for_grants": <true|false>,
  "confidence": "<high|medium|low>"
}}"""


def _chunk_text(text: str) -> List[str]:
    words = text.split()
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for i in range(0, len(words), step):
        chunk_words = words[i : i + CHUNK_SIZE]
        if len(chunk_words) < MIN_CHUNK_WORDS:
            continue
        chunks.append(" ".join(chunk_words))
    return chunks


class CompanyBrainAgent:
    def __init__(
        self,
        anthropic_api_key: str = "",
        openai_api_key: str = "",  # kept for backward compat, no longer used
        notion_token: str = "",
        google_refresh_token: str = "",
        google_client_id: str = "",
        google_client_secret: str = "",
    ):
        self.anthropic_api_key = anthropic_api_key
        self.notion_token = notion_token
        self.google_refresh_token = google_refresh_token
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret

    # ── Notion sync ────────────────────────────────────────────────────────────

    async def _fetch_notion_pages(self) -> List[Dict]:
        # Prefer MCP if connected
        try:
            from backend.integrations.notion_mcp import notion_mcp
            if notion_mcp.connected:
                return await self._fetch_via_mcp()
        except Exception as e:
            logger.debug("MCP not available, falling back to API: %s", e)

        if not self.notion_token:
            logger.warning("NOTION_TOKEN not set — skipping Notion sync")
            return []
        root_id = get_settings().notion_knowledge_base_page_id
        if root_id:
            return await self._fetch_from_root_page(root_id)
        return await self._fetch_via_search()

    async def _fetch_via_mcp(self) -> List[Dict]:
        """Fetch Notion pages via the MCP server (preferred path)."""
        from backend.integrations.notion_mcp import notion_mcp

        # Search for AltCarbon-related content
        queries = [
            "AltCarbon company overview technology",
            "Alt Carbon ERW biochar carbon removal MRV",
            "Alt Carbon projects Darjeeling Bengal",
            "Alt Carbon team methodology impact",
        ]
        seen: Set[str] = set()
        pages: List[Dict] = []

        for q in queries:
            try:
                results = await notion_mcp.search(q)
                for r in results:
                    page_id = r.get("id", "")
                    if page_id in seen:
                        continue
                    seen.add(page_id)
                    title = r.get("title", "Untitled")
                    # Fetch full page content
                    text = await notion_mcp.fetch_page(page_id)
                    if text and len(text.split()) >= MIN_CHUNK_WORDS:
                        pages.append({
                            "id": page_id,
                            "title": title,
                            "text": text,
                            "source": "notion",
                            "priority": "medium",
                        })
            except Exception as e:
                logger.debug("MCP search/fetch failed for '%s': %s", q, e)

        logger.info("Notion (MCP): fetched %d pages", len(pages))
        return pages

    async def _fetch_from_table_of_content(self) -> List[Dict]:
        """Fetch content from the Table of Content registry (Grants DB).

        Reads every row, follows links based on Content type:
          - "Notion Page"  → fetch via Notion Page ID
          - "Google Docx"  → extract doc ID from URL → fetch via Drive API
          - "Notion Site"  → fetch via Notion Page ID (resolved from published URL)
          - "Sheets"       → skip for now (not text-exportable easily)

        Also fetches Extra page url if present (secondary source).
        Tags: Main-source entries → priority "high", others → "medium".
        """
        try:
            from backend.integrations.notion_config import (
                TABLE_OF_CONTENT_DS,
                TOC_THEME_MAP,
            )

            # Query the Table of Content database via Notion REST API
            # (MCP query_data_source returns 400 for this DB)
            headers = {
                "Authorization": f"Bearer {self.notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            }
            rows: List[Dict] = []
            cursor: Optional[str] = None
            async with httpx.AsyncClient(timeout=60.0) as client:
                while True:
                    body: Dict[str, Any] = {"page_size": 100}
                    if cursor:
                        body["start_cursor"] = cursor
                    r = await client.post(
                        f"https://api.notion.com/v1/databases/{TABLE_OF_CONTENT_DS}/query",
                        headers=headers,
                        json=body,
                    )
                    if r.status_code != 200:
                        logger.warning("Table of Content query failed: %s %s", r.status_code, r.text[:200])
                        break
                    data = r.json()
                    rows.extend(data.get("results", []))
                    cursor = data.get("next_cursor")
                    if not cursor:
                        break

            if not rows:
                logger.debug("Table of Content: no rows returned")
                return []
        except Exception as e:
            logger.warning("Failed to query Table of Content: %s", e)
            return []

        docs: List[Dict] = []
        seen_drive_ids: Set[str] = set()  # Deduplicate same Drive doc across entries

        for row in rows:
            if not isinstance(row, dict):
                continue
            props = row.get("properties", {})

            # Extract title (Document Name)
            doc_name_prop = props.get("Document Name", {})
            doc_name = "".join(
                t.get("plain_text", "")
                for t in doc_name_prop.get("title", [])
            ).strip()
            display_name = re.sub(r'\*\*|<[^>]+>', '', doc_name).strip() or "Untitled"

            # Extract Content type (select)
            content_type = (props.get("Content type", {}).get("select") or {}).get("name", "")

            # Extract Content info (multi_select) → themes + is_main_source
            content_info = [
                opt.get("name", "")
                for opt in props.get("Content info", {}).get("multi_select", [])
            ]
            is_main_source = "Main-source" in content_info
            themes = [TOC_THEME_MAP[t] for t in content_info if t in TOC_THEME_MAP]

            # Extract URL (named "URL" in Notion, mapped to userDefined:URL)
            url_field = (props.get("URL", {}).get("url") or "")

            # Extract Notion Page ID (rich_text)
            notion_page_id_raw = "".join(
                t.get("plain_text", "")
                for t in props.get("Notion Page ID", {}).get("rich_text", [])
            ).strip()

            # Extract Extra page url
            extra_url = (props.get("Extra page url", {}).get("url") or "")

            # Parse Notion Page ID (may be plain ID, markdown link, or extractable from URL)
            notion_page_id = ""
            if notion_page_id_raw:
                id_match = re.search(r'([a-f0-9]{32})', notion_page_id_raw.replace("-", ""))
                if id_match:
                    notion_page_id = id_match.group(1)

            # Fallback: extract page ID from URL field (notion.so/workspace/Title-<id>?...)
            if not notion_page_id and url_field and "notion.so" in url_field:
                # Notion URLs end with Title-<32-hex-id>?query_params
                clean_path = url_field.split("?")[0].rstrip("/")
                last_segment = clean_path.split("/")[-1]
                # The ID is always the last 32 hex chars of the segment (after removing dashes)
                segment_clean = last_segment.replace("-", "")
                url_id_match = re.search(r'([a-f0-9]{32})$', segment_clean)
                if url_id_match:
                    notion_page_id = url_id_match.group(1)

            # Extract Drive doc ID from URL field
            drive_doc_id = ""
            if url_field and "docs.google.com/document" in url_field:
                dm = re.search(r'docs\.google\.com/document/d/([a-zA-Z0-9_-]+)', url_field)
                if dm:
                    drive_doc_id = dm.group(1)

            # Also check Extra page url for Drive links
            extra_drive_id = ""
            if extra_url and "docs.google.com/document" in extra_url:
                dm2 = re.search(r'docs\.google\.com/document/d/([a-zA-Z0-9_-]+)', extra_url)
                if dm2:
                    extra_drive_id = dm2.group(1)

            # ── Fetch content based on Content type ──
            texts: List[str] = []
            source_type = "documents_list"

            # For Notion Site entries without an ID, try MCP search by title
            if content_type == "Notion Site" and not notion_page_id and display_name != "Untitled":
                try:
                    from backend.integrations.notion_mcp import notion_mcp
                    if notion_mcp.connected:
                        search_results = await notion_mcp.search(display_name)
                        for sr in search_results:
                            sr_id = sr.get("id", "").replace("-", "")
                            if sr_id and len(sr_id) == 32:
                                notion_page_id = sr_id
                                break
                except Exception as e:
                    logger.debug("ToC: MCP search for '%s' failed: %s", display_name, e)

            if content_type in ("Notion Page", "Notion Site") and notion_page_id:
                # Fetch the Notion page by its workspace ID
                try:
                    from backend.integrations.notion_mcp import notion_mcp
                    page_text = await notion_mcp.fetch_page(notion_page_id)
                    if page_text and len(page_text.split()) >= MIN_CHUNK_WORDS:
                        texts.append(page_text)
                        source_type = "notion"
                except Exception as e:
                    logger.debug("ToC: Notion page %s fetch failed: %s", notion_page_id, e)

            if content_type == "Google Docx" and drive_doc_id:
                # Fetch Google Drive doc (deduplicate by doc ID)
                if drive_doc_id not in seen_drive_ids:
                    seen_drive_ids.add(drive_doc_id)
                    drive_text = await self._fetch_google_doc_by_id(drive_doc_id)
                    if drive_text and len(drive_text.split()) >= MIN_CHUNK_WORDS:
                        texts.append(drive_text)
                        source_type = "drive"

            # Fetch Extra page url as secondary source
            if extra_drive_id and extra_drive_id not in seen_drive_ids:
                seen_drive_ids.add(extra_drive_id)
                extra_text = await self._fetch_google_doc_by_id(extra_drive_id)
                if extra_text and len(extra_text.split()) >= MIN_CHUNK_WORDS:
                    texts.append(extra_text)

            if content_type == "Sheets":
                logger.debug("ToC: skipping Sheets entry '%s' (not supported yet)", display_name)
                continue

            if not texts:
                logger.debug("ToC: no content fetched for '%s' (%s)", display_name, content_type)
                continue

            combined = "\n\n---\n\n".join(texts)
            doc_id = notion_page_id or drive_doc_id or row.get("url", "").rstrip("/").split("/")[-1]

            docs.append({
                "id": doc_id,
                "title": display_name,
                "text": combined,
                "source": source_type,
                "priority": "high" if is_main_source else "medium",
                "source_registry": "table_of_content",
                "focus_areas": themes,
                "content_type": content_type,
            })

        logger.info("Table of Content: fetched %d documents (%d main-source)",
                     len(docs), sum(1 for d in docs if d["priority"] == "high"))
        return docs

    async def _fetch_from_root_page(self, root_page_id: str) -> List[Dict]:
        """Fetch root page + all descendants. Use when NOTION_KNOWLEDGE_BASE_PAGE_ID is set."""
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        pages: List[Dict] = []
        seen: Set[str] = set()

        async def collect_page(page_id: str, title_prefix: str = "") -> None:
            if page_id in seen:
                return
            seen.add(page_id)
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # Fetch page metadata
                    page_r = await client.get(
                        f"https://api.notion.com/v1/pages/{page_id}",
                        headers=headers,
                    )
                    if page_r.status_code != 200:
                        return
                    page = page_r.json()
                    title = self._get_page_title(page)
                    full_title = f"{title_prefix}{title}" if title_prefix else title

                    # Fetch blocks (with recursive children)
                    text = await self._blocks_to_text_recursive(client, headers, page_id)
                    if len(text.split()) >= MIN_CHUNK_WORDS:
                        pages.append({
                            "id": page_id,
                            "title": full_title or title or "Untitled",
                            "text": text,
                            "source": "notion",
                            "priority": "medium",
                        })

                    # Recurse into child_page and child_database blocks
                    blocks_r = await client.get(
                        f"https://api.notion.com/v1/blocks/{page_id}/children",
                        headers=headers,
                        params={"page_size": 100},
                    )
                    if blocks_r.status_code != 200:
                        return
                    blocks = blocks_r.json().get("results", [])
                    for block in blocks:
                        btype = block.get("type", "")
                        bid = block.get("id", "")
                        if btype == "child_page":
                            child_title = block.get("child_page", {}).get("title", "Untitled")
                            await collect_page(bid, f"{full_title} > ")
                        elif btype == "child_database":
                            await collect_database(bid, full_title)
            except Exception as e:
                logger.debug("Notion page fetch failed for %s: %s", page_id, e)

        async def collect_database(database_id: str, prefix: str) -> None:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    cursor = None
                    while True:
                        body: Dict[str, Any] = {"page_size": 100}
                        if cursor:
                            body["start_cursor"] = cursor
                        r = await client.post(
                            f"https://api.notion.com/v1/databases/{database_id}/query",
                            headers=headers,
                            json=body,
                        )
                        if r.status_code != 200:
                            break
                        data = r.json()
                        for page in data.get("results", []):
                            pid = page["id"]
                            if pid in seen:
                                continue
                            seen.add(pid)
                            title = self._get_page_title(page)
                            text = await self._blocks_to_text_recursive(client, headers, pid)
                            if len(text.split()) >= MIN_CHUNK_WORDS:
                                pages.append({
                                    "id": pid,
                                    "title": f"{prefix} > {title}" if prefix else title,
                                    "text": text,
                                    "source": "notion",
                                    "priority": "medium",
                                })
                        cursor = data.get("next_cursor")
                        if not cursor:
                            break
            except Exception as e:
                logger.debug("Notion database fetch failed for %s: %s", database_id, e)

        await collect_page(root_page_id)
        logger.info("Notion (root mode): fetched %d pages from %s", len(pages), root_page_id[:8])
        return pages

    def _get_page_title(self, page: Dict) -> str:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                return "".join(t.get("plain_text", "") for t in title_parts)
        return ""

    async def _blocks_to_text_recursive(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        block_id: str,
    ) -> str:
        """Fetch blocks and recursively fetch nested children. Returns plain text."""
        lines: List[str] = []
        cursor = None
        while True:
            try:
                params: Dict[str, Any] = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                r = await client.get(
                    f"https://api.notion.com/v1/blocks/{block_id}/children",
                    headers=headers,
                    params=params,
                )
                if r.status_code != 200:
                    break
                data = r.json()
                blocks = data.get("results", [])
                for block in blocks:
                    text = await self._block_to_text(client, headers, block)
                    if text.strip():
                        lines.append(text)
                cursor = data.get("next_cursor")
                if not cursor:
                    break
            except Exception as e:
                logger.warning("Block fetch failed for %s: %s", block_id, e)
                break
        return "\n".join(lines)

    async def _block_to_text(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        block: Dict,
    ) -> str:
        btype = block.get("type", "")
        content = block.get(btype, {})
        rich = content.get("rich_text", [])
        text = "".join(r.get("plain_text", "") for r in rich)
        if block.get("has_children"):
            child_text = await self._blocks_to_text_recursive(
                client, headers, block["id"]
            )
            if child_text:
                text = f"{text}\n{child_text}" if text else child_text
        return text

    async def _fetch_via_search(self) -> List[Dict]:
        """Legacy: search all workspace pages with pagination."""
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        pages: List[Dict] = []
        cursor = None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                while True:
                    body: Dict[str, Any] = {
                        "filter": {"value": "page", "property": "object"},
                        "page_size": 100,
                    }
                    if cursor:
                        body["start_cursor"] = cursor
                    r = await client.post(
                        "https://api.notion.com/v1/search",
                        headers=headers,
                        json=body,
                    )
                    r.raise_for_status()
                    data = r.json()
                    results = data.get("results", [])

                    for page in results:
                        page_id = page["id"]
                        title = self._get_page_title(page)
                        text = await self._blocks_to_text_recursive(client, headers, page_id)
                        if len(text.split()) >= MIN_CHUNK_WORDS:
                            pages.append({
                                "id": page_id,
                                "title": title or "Untitled",
                                "text": text,
                                "source": "notion",
                                "priority": "low",
                            })

                    cursor = data.get("next_cursor")
                    if not cursor:
                        break
        except Exception as e:
            logger.error("Notion sync error: %s", e)

        logger.info("Notion (search mode): fetched %d pages", len(pages))
        return pages

    # ── Google Drive sync ──────────────────────────────────────────────────────

    async def _fetch_drive_files(self) -> List[Dict]:
        if not self.google_refresh_token:
            logger.warning("GOOGLE_REFRESH_TOKEN not set — skipping Drive sync")
            return []
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            import httpx

            creds = Credentials(
                token=None,
                refresh_token=self.google_refresh_token,
                client_id=self.google_client_id,
                client_secret=self.google_client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )

            service = await asyncio.to_thread(
                build, "drive", "v3", credentials=creds, cache_discovery=False
            )

            # List all docs + sheets
            results = await asyncio.to_thread(
                lambda: service.files().list(
                    q="mimeType='application/vnd.google-apps.document'",
                    fields="files(id, name)",
                    pageSize=100,
                ).execute()
            )
            files = results.get("files", [])
            docs = []

            for f in files:
                try:
                    export = await asyncio.to_thread(
                        lambda fid=f["id"]: service.files().export(
                            fileId=fid, mimeType="text/plain"
                        ).execute()
                    )
                    text = export.decode("utf-8") if isinstance(export, bytes) else str(export)
                    if len(text.split()) >= MIN_CHUNK_WORDS:
                        docs.append({"id": f["id"], "title": f["name"], "text": text, "source": "drive", "priority": "low"})
                except Exception as e:
                    logger.debug("Drive export failed for %s: %s", f["name"], e)

            logger.info("Drive: fetched %d documents", len(docs))
            return docs
        except Exception as e:
            logger.error("Drive sync error: %s", e)
            return []

    async def _fetch_google_doc_by_id(self, doc_id: str) -> Optional[str]:
        """Fetch a single Google Drive document by ID. Returns plain text."""
        if not self.google_refresh_token:
            logger.debug("No Google credentials — skipping Drive doc %s", doc_id)
            return None
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(
                token=None,
                refresh_token=self.google_refresh_token,
                client_id=self.google_client_id,
                client_secret=self.google_client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )
            service = await asyncio.to_thread(
                build, "drive", "v3", credentials=creds, cache_discovery=False
            )
            export = await asyncio.to_thread(
                lambda: service.files().export(
                    fileId=doc_id, mimeType="text/plain"
                ).execute()
            )
            text = export.decode("utf-8") if isinstance(export, bytes) else str(export)
            logger.debug("Drive doc %s: %d chars", doc_id, len(text))
            return text
        except Exception as e:
            logger.warning("Failed to fetch Drive doc %s: %s", doc_id, e)
            return None

    # ── Tagging with Claude Haiku ──────────────────────────────────────────────

    async def _tag_chunk(self, chunk: str) -> Dict:
        import json
        try:
            raw = await chat(TAGGING_PROMPT.format(chunk=chunk[:1500]), model=BRAIN_MODEL, max_tokens=256)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except Exception as e:
            logger.debug("Tagging failed: %s", e)
            return {
                "doc_type": "misc",
                "themes": ["climatetech"],
                "key_topics": [],
                "contains_data": False,
                "is_useful_for_grants": True,
                "confidence": "low",
            }

    # ── Full sync ──────────────────────────────────────────────────────────────

    async def sync(self) -> Dict:
        """Sync Table of Content + supplementary Notion/Drive → chunk → tag → upsert.

        Primary path: Table of Content (unified fetcher handles all content types).
        Supplementary: MCP-discovered Notion pages + Drive files (deduplicated).
        Pinecone embeds server-side via multilingual-e5-large.
        """
        from backend.db.pinecone_store import is_pinecone_configured, upsert_chunks as pc_upsert

        start = datetime.now(timezone.utc)
        logger.info("Company Brain: starting knowledge sync")
        use_pinecone = is_pinecone_configured()
        if use_pinecone:
            logger.info("Pinecone configured — dual-writing vectors")

        # Phase 1: Table of Content — primary source (all content types)
        google_creds = {
            "google_refresh_token": self.google_refresh_token,
            "google_client_id": self.google_client_id,
            "google_client_secret": self.google_client_secret,
        }
        try:
            from backend.agents.content_fetcher import fetch_all_from_toc
            docs_list_pages = await fetch_all_from_toc(
                use_cache=True, google_creds=google_creds,
            )
        except Exception as e:
            logger.warning("Unified ToC fetch failed, falling back to legacy: %s", e)
            docs_list_pages = await self._fetch_from_table_of_content()

        # Phase 2: Supplementary Notion pages + generic Drive files
        notion_pages, drive_files = await asyncio.gather(
            self._fetch_notion_pages(),
            self._fetch_drive_files(),
        )

        # Deduplicate: ToC pages take priority over supplementary sources
        seen_ids = {d["id"] for d in docs_list_pages}
        notion_pages = [p for p in notion_pages if p["id"] not in seen_ids]
        drive_files = [d for d in drive_files if d["id"] not in seen_ids]

        all_docs = docs_list_pages + notion_pages + drive_files
        logger.info(
            "Company Brain: %d docs (%d toc, %d notion-supplementary, %d drive-supplementary)",
            len(all_docs), len(docs_list_pages), len(notion_pages), len(drive_files),
        )

        col = knowledge_chunks()
        chunks_saved = 0
        chunks_skipped = 0
        stale_deleted = 0
        pinecone_vectors: List[Dict] = []
        doc_chunk_counts: Dict[str, int] = {}  # source_id → num chunks produced
        sem = asyncio.Semaphore(5)

        async def process_doc(doc: Dict):
            nonlocal chunks_saved, chunks_skipped

            # ── Incremental sync: skip unchanged docs ──
            content_hash = hashlib.sha256(doc["text"].encode()).hexdigest()
            existing = await col.find_one(
                {"source_id": doc["id"], "chunk_index": 0},
                {"content_hash": 1},
            )
            if existing and existing.get("content_hash") == content_hash:
                # Content unchanged — skip re-chunking/tagging/embedding
                old_count = await col.count_documents({"source_id": doc["id"]})
                doc_chunk_counts[doc["id"]] = old_count
                chunks_skipped += old_count
                logger.debug("Skipping unchanged doc: %s (%d chunks)", doc["title"], old_count)
                return

            chunks = _chunk_text(doc["text"])
            doc_chunk_counts[doc["id"]] = len(chunks)
            priority = doc.get("priority", "low")

            for i, chunk in enumerate(chunks):
                async with sem:
                    tag = await self._tag_chunk(chunk)

                    doc_record = {
                        "source": doc["source"],
                        "source_id": doc["id"],
                        "source_title": doc["title"],
                        "chunk_index": i,
                        "content": chunk,
                        "content_hash": content_hash,
                        "doc_type": tag.get("doc_type", "misc"),
                        "themes": tag.get("themes", []),
                        "key_topics": tag.get("key_topics", []),
                        "contains_data": tag.get("contains_data", False),
                        "is_useful_for_grants": tag.get("is_useful_for_grants", True),
                        "confidence": tag.get("confidence", "low"),
                        "priority": priority,
                        "last_synced": datetime.now(timezone.utc).isoformat(),
                    }

                    # Carry Table of Content metadata
                    if doc.get("source_registry"):
                        doc_record["source_registry"] = doc["source_registry"]
                    if doc.get("focus_areas"):
                        doc_record["focus_areas"] = doc["focus_areas"]
                    if doc.get("doc_status"):
                        doc_record["doc_status"] = doc["doc_status"]

                    await col.update_one(
                        {"source_id": doc["id"], "chunk_index": i},
                        {"$set": doc_record},
                        upsert=True,
                    )
                    chunks_saved += 1

                    # Queue for Pinecone batch upsert (text-based, Pinecone embeds server-side)
                    if use_pinecone:
                        pc_record: Dict[str, Any] = {
                            "_id": f"{doc['id']}#{i}",
                            "content": chunk,
                            "source": doc["source"],
                            "source_id": doc["id"],
                            "source_title": doc["title"],
                            "doc_type": tag.get("doc_type", "misc"),
                            "themes": tag.get("themes", []),
                            "key_topics": tag.get("key_topics", []),
                            "contains_data": tag.get("contains_data", False),
                            "is_useful_for_grants": tag.get("is_useful_for_grants", True),
                            "priority": priority,
                        }
                        pinecone_vectors.append(pc_record)

        await asyncio.gather(*(process_doc(d) for d in all_docs))

        # ── P0: Clean up stale chunks ──
        # If a doc shrank (e.g. 10 chunks → 3), delete orphaned chunks 3-9
        for doc_id, new_count in doc_chunk_counts.items():
            try:
                result = await col.delete_many({
                    "source_id": doc_id,
                    "chunk_index": {"$gte": new_count},
                })
                if result.deleted_count > 0:
                    stale_deleted += result.deleted_count
                    logger.debug("Cleaned %d stale chunks for %s", result.deleted_count, doc_id)
            except Exception as e:
                logger.debug("Stale chunk cleanup failed for %s: %s", doc_id, e)

        if stale_deleted:
            logger.info("Cleaned %d stale chunks across all docs", stale_deleted)
        if chunks_skipped:
            logger.info("Skipped %d unchanged chunks (incremental sync)", chunks_skipped)

        # Batch upsert to Pinecone
        pinecone_count = 0
        if use_pinecone and pinecone_vectors:
            try:
                pinecone_count = pc_upsert(pinecone_vectors)
                logger.info("Pinecone: upserted %d vectors", pinecone_count)
            except Exception as e:
                logger.error("Pinecone upsert failed: %s", e)

        duration = (datetime.now(timezone.utc) - start).seconds
        await knowledge_sync_logs().insert_one({
            "synced_at": start.isoformat(),
            "notion_pages": len(notion_pages),
            "drive_files": len(drive_files),
            "documents_list": len(docs_list_pages),
            "total_chunks": chunks_saved,
            "chunks_skipped": chunks_skipped,
            "stale_deleted": stale_deleted,
            "pinecone_vectors": pinecone_count,
            "duration_seconds": duration,
        })

        # Update Knowledge Connections DB (best-effort)
        await self._update_knowledge_connections(
            docs_list_pages, notion_pages, chunks_saved
        )

        logger.info(
            "Company Brain sync complete: %d chunks saved, %d skipped, %d stale deleted in %ds",
            chunks_saved, chunks_skipped, stale_deleted, duration,
        )
        return {
            "total_chunks": chunks_saved,
            "chunks_skipped": chunks_skipped,
            "stale_deleted": stale_deleted,
            "notion_pages": len(notion_pages),
            "drive_files": len(drive_files),
            "documents_list": len(docs_list_pages),
            "pinecone_vectors": pinecone_count,
        }

    async def sync_single_document(self, page_id: str) -> Dict:
        """Re-sync a single document by page_id (triggered by webhook or polling).

        Fetches content, compares hash, re-chunks/tags/upserts if changed.
        Returns {status, page_id, chunks_updated, skipped}.
        """
        from backend.db.pinecone_store import is_pinecone_configured, upsert_chunks as pc_upsert

        col = knowledge_chunks()
        normalized_id = page_id.replace("-", "")

        # Find the document in MongoDB to get its metadata
        existing_chunk = await col.find_one({"source_id": normalized_id, "chunk_index": 0})
        if not existing_chunk:
            # Also try with dashes
            existing_chunk = await col.find_one({"source_id": page_id, "chunk_index": 0})
            if existing_chunk:
                normalized_id = page_id

        if not existing_chunk:
            logger.info("sync_single_document: page_id %s not found in knowledge_chunks", page_id)
            return {"status": "not_found", "page_id": page_id, "chunks_updated": 0, "skipped": True}

        source_title = existing_chunk.get("source_title", "Unknown")
        source_type = existing_chunk.get("source", "notion")
        old_hash = existing_chunk.get("content_hash", "")

        # Fetch fresh content via MCP
        text = None
        try:
            from backend.integrations.notion_mcp import notion_mcp
            if notion_mcp.connected:
                text = await notion_mcp.fetch_page(page_id)
        except Exception as e:
            logger.warning("sync_single_document: MCP fetch failed for %s: %s", page_id, e)

        if not text or len(text.split()) < MIN_CHUNK_WORDS:
            logger.info("sync_single_document: no content fetched for %s", page_id)
            return {"status": "fetch_failed", "page_id": page_id, "chunks_updated": 0, "skipped": True}

        # Compare hash — skip if unchanged
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        if content_hash == old_hash:
            logger.debug("sync_single_document: %s unchanged (hash match)", source_title)
            return {"status": "unchanged", "page_id": page_id, "chunks_updated": 0, "skipped": True}

        # Content changed — re-chunk, re-tag, upsert
        logger.info("sync_single_document: %s changed, re-syncing", source_title)
        chunks = _chunk_text(text)
        use_pinecone = is_pinecone_configured()
        pinecone_vectors: List[Dict] = []
        sem = asyncio.Semaphore(5)
        priority = existing_chunk.get("priority", "medium")

        for i, chunk in enumerate(chunks):
            async with sem:
                tag = await self._tag_chunk(chunk)

                doc_record = {
                    "source": source_type,
                    "source_id": normalized_id,
                    "source_title": source_title,
                    "chunk_index": i,
                    "content": chunk,
                    "content_hash": content_hash,
                    "doc_type": tag.get("doc_type", "misc"),
                    "themes": tag.get("themes", []),
                    "key_topics": tag.get("key_topics", []),
                    "contains_data": tag.get("contains_data", False),
                    "is_useful_for_grants": tag.get("is_useful_for_grants", True),
                    "confidence": tag.get("confidence", "low"),
                    "priority": priority,
                    "last_synced": datetime.now(timezone.utc).isoformat(),
                }

                # Carry over existing metadata
                for field in ("source_registry", "focus_areas", "doc_status"):
                    if existing_chunk.get(field):
                        doc_record[field] = existing_chunk[field]

                await col.update_one(
                    {"source_id": normalized_id, "chunk_index": i},
                    {"$set": doc_record},
                    upsert=True,
                )

                if use_pinecone:
                    from typing import Any as _Any
                    pc_record: Dict[str, _Any] = {
                        "_id": f"{normalized_id}#{i}",
                        "content": chunk,
                        "source": source_type,
                        "source_id": normalized_id,
                        "source_title": source_title,
                        "doc_type": tag.get("doc_type", "misc"),
                        "themes": tag.get("themes", []),
                        "key_topics": tag.get("key_topics", []),
                        "contains_data": tag.get("contains_data", False),
                        "is_useful_for_grants": tag.get("is_useful_for_grants", True),
                        "priority": priority,
                    }
                    pinecone_vectors.append(pc_record)

        # Clean up stale chunks if document shrank
        stale_deleted = 0
        try:
            result = await col.delete_many({
                "source_id": normalized_id,
                "chunk_index": {"$gte": len(chunks)},
            })
            stale_deleted = result.deleted_count
        except Exception as e:
            logger.debug("Stale chunk cleanup failed for %s: %s", normalized_id, e)

        # Batch upsert to Pinecone
        pinecone_count = 0
        if use_pinecone and pinecone_vectors:
            try:
                pinecone_count = pc_upsert(pinecone_vectors)
            except Exception as e:
                logger.error("Pinecone upsert failed for %s: %s", normalized_id, e)

        # Log to knowledge_sync_logs
        await knowledge_sync_logs().insert_one({
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "source": "webhook",
            "trigger": "webhook",
            "page_id": page_id,
            "source_title": source_title,
            "total_chunks": len(chunks),
            "stale_deleted": stale_deleted,
            "pinecone_vectors": pinecone_count,
        })

        logger.info(
            "sync_single_document: %s — %d chunks updated, %d stale deleted",
            source_title, len(chunks), stale_deleted,
        )
        return {
            "status": "synced",
            "page_id": page_id,
            "source_title": source_title,
            "chunks_updated": len(chunks),
            "stale_deleted": stale_deleted,
            "skipped": False,
        }

    async def _update_knowledge_connections(
        self,
        docs_list_pages: List[Dict],
        notion_pages: List[Dict],
        total_chunks: int,
    ) -> None:
        """Update Knowledge Connections DB with sync status per source (best-effort)."""
        try:
            from backend.integrations.notion_mcp import notion_mcp
            from backend.integrations.notion_config import KNOWLEDGE_CONNECTIONS_DS

            if not notion_mcp.connected:
                return

            # Fetch existing rows
            rows = await notion_mcp.query_data_source(
                KNOWLEDGE_CONNECTIONS_DS, limit=100
            )

            # Build map of source_id/section_key → page URL
            existing: Dict[str, str] = {}
            for row in rows:
                if isinstance(row, dict):
                    key = row.get("Source ID", "") or row.get("Section Key", "")
                    url = row.get("url", "")
                    if key and url:
                        existing[key] = url

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            # Update existing entries
            for doc in docs_list_pages + notion_pages:
                source_id = doc["id"]
                if source_id not in existing:
                    continue
                page_url = existing[source_id]
                page_id = page_url.rstrip("/").split("/")[-1].replace("-", "")
                if len(page_id) < 32:
                    continue
                page_id = (
                    f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}"
                    f"-{page_id[16:20]}-{page_id[20:32]}"
                )
                try:
                    await notion_mcp.update_page(
                        page_id=page_id,
                        properties={
                            "Chars Fetched": len(doc.get("text", "")),
                            "Errors": "",
                        },
                    )
                except Exception as e:
                    logger.debug("Connection log update failed for %s: %s", source_id, e)

            # Create new entries for Documents List pages not yet tracked
            for doc in docs_list_pages:
                if doc["id"] in existing:
                    continue
                try:
                    await notion_mcp.create_page(
                        parent_id=KNOWLEDGE_CONNECTIONS_DS,
                        title=doc.get("title", "Untitled"),
                        parent_type="database_id",
                        properties={
                            "title": doc.get("title", "Untitled"),
                            "Source Type": "Documents List",
                            "Source ID": doc["id"],
                            "Sync Method": "MCP + Drive" if doc.get("source") == "documents_list" else "MCP",
                            "Chars Fetched": len(doc.get("text", "")),
                        },
                    )
                except Exception as e:
                    logger.debug("Failed to create connection entry for %s: %s", doc.get("title"), e)

            logger.info("Updated Knowledge Connections with %d sources", len(docs_list_pages) + len(notion_pages))
        except Exception as e:
            logger.warning("Knowledge Connections update failed: %s", e)

    # ── Query interface ────────────────────────────────────────────────────────

    async def query(
        self,
        query_text: str,
        themes: Optional[List[str]] = None,
        doc_types: Optional[List[str]] = None,
        top_k: int = 6,
    ) -> List[Dict]:
        """Two-phase priority vector search for relevant knowledge chunks.

        Phase 1: Fetch high-priority (Documents List) chunks
        Phase 2: Fetch all chunks
        Merge, deduplicate, priority content first. Uses Pinecone (text query,
        server-side embedding) or MongoDB text fallback.
        """
        from backend.db.pinecone_store import is_pinecone_configured, search_similar

        half_k = max(top_k // 2, 2)

        # ── Pinecone path (preferred — text-based, server-side embedding) ──
        if is_pinecone_configured():
            return self._merge_priority(
                self._pinecone_phase(search_similar, query_text, themes, doc_types, half_k, priority="high"),
                self._pinecone_phase(search_similar, query_text, themes, doc_types, half_k, priority=None),
                top_k,
            )

        # ── MongoDB text fallback (no vector search without embeddings) ──
        return await self._mongo_text_fallback(query_text, themes, doc_types, top_k)

    def _pinecone_phase(
        self,
        search_fn,
        query_text: str,
        themes: Optional[List[str]],
        doc_types: Optional[List[str]],
        k: int,
        priority: Optional[str] = None,
    ) -> List[Dict]:
        """Build Pinecone filter and text-search query."""
        pc_filter: Dict[str, Any] = {}
        if priority:
            pc_filter["priority"] = priority
        if themes:
            pc_filter["themes"] = {"$in": themes}
        if doc_types:
            pc_filter["doc_type"] = {"$in": doc_types}
        try:
            return search_fn(query_text, top_k=k, filter_dict=pc_filter or None)
        except Exception as e:
            logger.debug("Pinecone search failed (priority=%s): %s", priority, e)
            return []

    @staticmethod
    def _merge_priority(
        phase1: List[Dict], phase2: List[Dict], top_k: int
    ) -> List[Dict]:
        """Merge two phases: phase1 results first, then phase2, deduplicated."""
        seen: Set[str] = set()
        merged: List[Dict] = []
        for r in phase1 + phase2:
            rid = r.get("_id", r.get("source_id", ""))
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            merged.append(r)
        return merged[:top_k]

    async def _mongo_text_fallback(
        self,
        query_text: str,
        themes: Optional[List[str]],
        doc_types: Optional[List[str]],
        top_k: int,
    ) -> List[Dict]:
        """MongoDB text-based fallback when Pinecone is unavailable.

        Uses theme/doc_type filtering + priority ranking (no vector search).
        """
        col = knowledge_chunks()
        text_query: Dict[str, Any] = {"is_useful_for_grants": True}
        if themes:
            text_query["themes"] = {"$in": themes}
        if doc_types:
            text_query["doc_type"] = {"$in": doc_types}

        results: List[Dict] = []
        async for doc in col.find(text_query).sort("priority", 1).limit(top_k + 4):
            doc["_id"] = str(doc.get("_id", ""))
            results.append(doc)

        # Re-rank: high priority first
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        results.sort(key=lambda c: priority_rank.get(c.get("priority", "low"), 2))
        return results[:top_k]

    async def get_style_examples(
        self,
        themes: Optional[List[str]] = None,
        section_name: str = "",
    ) -> List[Dict]:
        """Get past grant application chunks as style examples.

        Theme-aware: prefers past grants matching the grant's theme.
        Section-aware: tailors query to find examples of similar sections.
        """
        # Build a targeted query
        query_parts = ["grant application proposal"]
        if section_name:
            query_parts.append(section_name)
        if themes:
            query_parts.extend(themes[:2])
        query_parts.append("writing methodology approach")

        return await self.query(
            " ".join(query_parts),
            themes=themes,
            doc_types=["past_grant_application"],
            top_k=6,
        )

    async def get_company_overview(
        self,
        themes: Optional[List[str]] = None,
        max_chars: int = 4000,
    ) -> str:
        """Get AltCarbon company knowledge for Analyst/Drafter prompts.
        Prioritizes company_overview, technical_methodology, project_description.
        Falls back to the static Notion-sourced profile if vector search is empty.
        """
        chunks = await self.query(
            "AltCarbon company overview technology methodology pilots team",
            themes=themes,
            doc_types=[
                "company_overview",
                "technical_methodology",
                "project_description",
                "impact_metrics",
                "team_bio",
            ],
            top_k=10,
        )
        if not chunks:
            chunks = await self.query(
                "AltCarbon climate technology carbon removal MRV",
                themes=themes or ["climatetech"],
                top_k=8,
            )
        parts = []
        total = 0
        for c in chunks:
            content = c.get("content", "")
            if content and total + len(content) <= max_chars:
                parts.append(f"[{c.get('doc_type', 'misc')} | {c.get('source_title', '')}]\n{content}")
                total += len(content)

        if parts:
            return "\n\n---\n\n".join(parts)

        # Fallback: use the static profile sourced from Notion
        profile = _load_static_profile()
        if profile:
            logger.info("Using static AltCarbon profile as fallback (no vector chunks found)")
            return profile[:max_chars]
        return ""

    # ── Past grants ingestion ────────────────────────────────────────────────

    async def sync_past_grants(self) -> Dict:
        """Ingest past grant PDFs from /past_grants/ into MongoDB + Pinecone.

        Uses pdftotext for extraction, then follows the standard chunk → tag → upsert
        pipeline. Tags with doc_type='past_grant_application' so they're retrievable
        as style examples by the drafter.
        """
        import subprocess
        from pathlib import Path
        from backend.db.pinecone_store import is_pinecone_configured, upsert_chunks as pc_upsert
        from backend.knowledge.past_grants_config import PAST_GRANTS

        col = knowledge_chunks()
        use_pinecone = is_pinecone_configured()
        grants_dir = Path(__file__).resolve().parent.parent.parent / "past_grants"

        if not grants_dir.exists():
            return {"error": "past_grants/ directory not found", "chunks": 0}

        chunks_saved = 0
        chunks_skipped = 0
        pinecone_vectors: List[Dict] = []
        grant_results: List[Dict] = []
        sem = asyncio.Semaphore(5)

        for grant_meta in PAST_GRANTS:
            pdf_path = grants_dir / grant_meta["filename"]
            if not pdf_path.exists():
                logger.warning("Past grant PDF not found: %s", pdf_path)
                grant_results.append({"title": grant_meta["title"], "status": "file_not_found"})
                continue

            # Extract text via pdftotext
            try:
                result = subprocess.run(
                    ["pdftotext", str(pdf_path), "-"],
                    capture_output=True, text=True, timeout=30,
                )
                text = result.stdout.strip()
            except Exception as e:
                logger.warning("pdftotext failed for %s: %s", grant_meta["filename"], e)
                grant_results.append({"title": grant_meta["title"], "status": f"extract_failed: {e}"})
                continue

            if len(text.split()) < MIN_CHUNK_WORDS:
                grant_results.append({"title": grant_meta["title"], "status": "too_short", "words": len(text.split())})
                continue

            # Source ID: stable identifier based on filename
            source_id = f"past_grant:{grant_meta['filename']}"
            content_hash = hashlib.sha256(text.encode()).hexdigest()

            # Check if already synced with same content
            existing = await col.find_one(
                {"source_id": source_id, "chunk_index": 0},
                {"content_hash": 1},
            )
            if existing and existing.get("content_hash") == content_hash:
                old_count = await col.count_documents({"source_id": source_id})
                chunks_skipped += old_count
                grant_results.append({
                    "title": grant_meta["title"],
                    "status": "unchanged",
                    "chunks": old_count,
                })
                continue

            # Chunk the text
            chunks = _chunk_text(text)
            logger.info(
                "Past grant: %s — %d words → %d chunks",
                grant_meta["title"][:50], len(text.split()), len(chunks),
            )

            for i, chunk in enumerate(chunks):
                async with sem:
                    tag = await self._tag_chunk(chunk)

                    # Override doc_type to past_grant_application
                    doc_record = {
                        "source": "past_grant",
                        "source_id": source_id,
                        "source_title": grant_meta["title"],
                        "chunk_index": i,
                        "content": chunk,
                        "content_hash": content_hash,
                        "doc_type": "past_grant_application",
                        "themes": grant_meta.get("themes", tag.get("themes", [])),
                        "key_topics": tag.get("key_topics", []),
                        "contains_data": tag.get("contains_data", False),
                        "is_useful_for_grants": True,
                        "confidence": "high",
                        "priority": "high",
                        "last_synced": datetime.now(timezone.utc).isoformat(),
                        # Past grant metadata
                        "grant_funder": grant_meta.get("funder", ""),
                        "grant_scheme": grant_meta.get("scheme", ""),
                        "grant_year": grant_meta.get("year"),
                        "grant_pi": grant_meta.get("pi", ""),
                        "grant_institution": grant_meta.get("institution", ""),
                    }

                    await col.update_one(
                        {"source_id": source_id, "chunk_index": i},
                        {"$set": doc_record},
                        upsert=True,
                    )
                    chunks_saved += 1

                    if use_pinecone:
                        pinecone_vectors.append({
                            "_id": f"{source_id}#{i}",
                            "content": chunk,
                            "source": "past_grant",
                            "source_id": source_id,
                            "source_title": grant_meta["title"],
                            "doc_type": "past_grant_application",
                            "themes": grant_meta.get("themes", []),
                            "key_topics": tag.get("key_topics", []),
                            "contains_data": tag.get("contains_data", False),
                            "is_useful_for_grants": True,
                            "priority": "high",
                        })

            # Clean stale chunks if doc shrank
            await col.delete_many({
                "source_id": source_id,
                "chunk_index": {"$gte": len(chunks)},
            })

            grant_results.append({
                "title": grant_meta["title"],
                "status": "synced",
                "words": len(text.split()),
                "chunks": len(chunks),
            })

        # Batch upsert to Pinecone
        pinecone_count = 0
        if use_pinecone and pinecone_vectors:
            try:
                pinecone_count = pc_upsert(pinecone_vectors)
                logger.info("Pinecone: upserted %d past grant vectors", pinecone_count)
            except Exception as e:
                logger.error("Pinecone upsert for past grants failed: %s", e)

        logger.info(
            "Past grants sync: %d chunks saved, %d skipped, %d pinecone vectors",
            chunks_saved, chunks_skipped, pinecone_count,
        )
        return {
            "chunks_saved": chunks_saved,
            "chunks_skipped": chunks_skipped,
            "pinecone_vectors": pinecone_count,
            "grants": grant_results,
        }

    async def health(self) -> Dict:
        col = knowledge_chunks()
        total = await col.count_documents({})
        notion_count = await col.count_documents({"source": "notion"})
        drive_count = await col.count_documents({"source": "drive"})
        past_grants = await col.count_documents({"doc_type": "past_grant_application"})

        last_sync = await knowledge_sync_logs().find_one(sort=[("synced_at", -1)])
        return {
            "total_chunks": total,
            "notion_chunks": notion_count,
            "drive_chunks": drive_count,
            "past_grant_application_chunks": past_grants,
            "last_synced": last_sync["synced_at"] if last_sync else None,
            "status": "healthy" if total >= 50 else ("thin" if total >= 1 else "empty"),
        }


async def company_brain_node(state: GrantState) -> Dict:
    """LangGraph node: query Company Brain for the selected grant's context."""
    from backend.config.settings import get_settings
    s = get_settings()

    agent = CompanyBrainAgent(
        openai_api_key=s.openai_api_key,
        notion_token=s.notion_token,
        google_refresh_token=s.google_refresh_token,
        google_client_id=s.google_client_id,
        google_client_secret=s.google_client_secret,
    )

    # Find the selected grant
    from backend.db.mongo import grants_scored
    from bson import ObjectId
    grant_id = state.get("selected_grant_id")
    grant = {}
    if grant_id:
        grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}

    themes = grant.get("themes_detected", [])
    query_text = f"{grant.get('title', '')} {grant.get('reasoning', '')} {' '.join(themes)}"

    # Load style examples once (theme-aware)
    style_examples = []
    if not state.get("style_examples_loaded"):
        style_examples = await agent.get_style_examples(themes=themes)

    context_chunks = await agent.query(query_text, themes=themes, top_k=8)

    company_context = "\n\n---\n\n".join(
        f"[{c.get('doc_type','misc')} | {c.get('source_title','')}]\n{c['content']}"
        for c in context_chunks
    )

    # Always prepend the static profile for rich baseline context
    static_profile = _load_static_profile()
    if static_profile and not company_context:
        company_context = static_profile[:6000]
    elif static_profile:
        company_context = f"[STATIC PROFILE]\n{static_profile[:3000]}\n\n---\n\n{company_context}"
    style_text = "\n\n---\n\n".join(
        f"[PAST APPLICATION EXAMPLE]\n{c['content']}"
        for c in style_examples
    ) if style_examples else state.get("style_examples", "")

    audit_entry = {
        "node": "company_brain",
        "ts": datetime.now(timezone.utc).isoformat(),
        "context_chunks": len(context_chunks),
        "style_examples": len(style_examples),
    }
    return {
        "company_context": company_context,
        "style_examples": style_text or state.get("style_examples", ""),
        "style_examples_loaded": True,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }


async def company_brain_load_node(state: GrantState) -> Dict:
    """LangGraph node: load general company profile BEFORE analyst scoring.

    Writes state.company_profile (general overview, ~3 000 chars).
    Does NOT touch state.company_context (that's grant-specific, loaded post-triage).
    """
    from backend.config.settings import get_settings
    s = get_settings()

    profile = ""
    try:
        agent = CompanyBrainAgent(
            notion_token=s.notion_token,
            google_refresh_token=s.google_refresh_token,
            google_client_id=s.google_client_id,
            google_client_secret=s.google_client_secret,
        )
        profile = await agent.get_company_overview(max_chars=3000)
    except Exception as e:
        logger.debug("company_brain_load: vector overview failed: %s", e)

    if not profile:
        profile = _load_static_profile()[:3000]
        if profile:
            logger.info("company_brain_load: using static profile (%d chars)", len(profile))

    audit_entry = {
        "node": "company_brain_load",
        "ts": datetime.now(timezone.utc).isoformat(),
        "profile_chars": len(profile),
        "source": "vector" if profile and "STATIC PROFILE" not in profile else "static",
    }

    try:
        from backend.integrations.notion_sync import log_agent_run
        await log_agent_run(
            agent="company_brain_load",
            status="Success" if profile else "Warning",
            trigger="Pipeline",
            started_at=datetime.now(timezone.utc),
            duration_seconds=0,
            errors=0,
            summary=f"Loaded {len(profile)} chars company profile for analyst",
        )
    except Exception:
        logger.debug("Notion sync skipped (company_brain_load)", exc_info=True)

    return {
        "company_profile": profile,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
