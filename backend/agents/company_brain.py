"""Company Brain Agent — AltCarbon's institutional memory.

Syncs from Notion + Google Drive, chunks content, tags with Claude Haiku,
embeds with OpenAI text-embedding-3-small, stores in MongoDB Atlas Vector Search.

Query interface: given a grant's themes and requirements, return the most
relevant chunks to ground Analyst scoring and Drafter writing.

Notion sync modes:
- NOTION_KNOWLEDGE_BASE_PAGE_ID set: sync only that page + all descendants (AltCarbon knowledge)
- Otherwise: sync all workspace pages (legacy, with pagination)
"""
from __future__ import annotations

import asyncio
import logging
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx
from openai import AsyncOpenAI

from backend.config.settings import get_settings
from backend.db.mongo import knowledge_chunks, knowledge_sync_logs
from backend.graph.state import GrantState
from backend.utils.llm import chat, HAIKU

logger = logging.getLogger(__name__)

# ── Static knowledge profile (from Notion, cached locally) ─────────────────
_PROFILE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "altcarbon_profile.md"
_cached_profile: Optional[str] = None


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


CHUNK_SIZE = 400       # words
CHUNK_OVERLAP = 80     # words
MIN_CHUNK_WORDS = 40

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
        openai_api_key: str = "",
        notion_token: str = "",
        google_refresh_token: str = "",
        google_client_id: str = "",
        google_client_secret: str = "",
    ):
        self.oai = AsyncOpenAI(api_key=openai_api_key)
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
                        })
            except Exception as e:
                logger.debug("MCP search/fetch failed for '%s': %s", q, e)

        logger.info("Notion (MCP): fetched %d pages", len(pages))
        return pages

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
            except Exception:
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
                        docs.append({"id": f["id"], "title": f["name"], "text": text, "source": "drive"})
                except Exception as e:
                    logger.debug("Drive export failed for %s: %s", f["name"], e)

            logger.info("Drive: fetched %d documents", len(docs))
            return docs
        except Exception as e:
            logger.error("Drive sync error: %s", e)
            return []

    # ── Tagging with Claude Haiku ──────────────────────────────────────────────

    async def _tag_chunk(self, chunk: str) -> Dict:
        import json
        try:
            raw = await chat(TAGGING_PROMPT.format(chunk=chunk[:1500]), model=HAIKU, max_tokens=256)
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

    # ── Embedding with OpenAI ──────────────────────────────────────────────────

    async def _embed(self, text: str) -> List[float]:
        r = await self.oai.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000],
        )
        return r.data[0].embedding

    # ── Full sync ──────────────────────────────────────────────────────────────

    async def sync(self) -> Dict:
        """Sync Notion + Drive → chunk → tag → embed → upsert to MongoDB + Pinecone."""
        from backend.db.pinecone_store import is_pinecone_configured, upsert_chunks as pc_upsert

        start = datetime.now(timezone.utc)
        logger.info("Company Brain: starting knowledge sync")
        use_pinecone = is_pinecone_configured()
        if use_pinecone:
            logger.info("Pinecone configured — dual-writing vectors")

        notion_pages, drive_files = await asyncio.gather(
            self._fetch_notion_pages(),
            self._fetch_drive_files(),
        )
        all_docs = notion_pages + drive_files
        logger.info("Company Brain: %d total documents to process", len(all_docs))

        col = knowledge_chunks()
        chunks_saved = 0
        pinecone_vectors: List[Dict] = []
        sem = asyncio.Semaphore(5)

        async def process_doc(doc: Dict):
            nonlocal chunks_saved
            chunks = _chunk_text(doc["text"])
            for i, chunk in enumerate(chunks):
                async with sem:
                    tag = await self._tag_chunk(chunk)
                    embedding = await self._embed(chunk)

                    doc_record = {
                        "source": doc["source"],
                        "source_id": doc["id"],
                        "source_title": doc["title"],
                        "chunk_index": i,
                        "content": chunk,
                        "embedding": embedding,
                        "doc_type": tag.get("doc_type", "misc"),
                        "themes": tag.get("themes", []),
                        "key_topics": tag.get("key_topics", []),
                        "contains_data": tag.get("contains_data", False),
                        "is_useful_for_grants": tag.get("is_useful_for_grants", True),
                        "confidence": tag.get("confidence", "low"),
                        "last_synced": datetime.now(timezone.utc).isoformat(),
                    }

                    await col.update_one(
                        {"source_id": doc["id"], "chunk_index": i},
                        {"$set": doc_record},
                        upsert=True,
                    )
                    chunks_saved += 1

                    # Queue for Pinecone batch upsert
                    if use_pinecone:
                        pinecone_vectors.append({
                            "id": f"{doc['id']}#{i}",
                            "values": embedding,
                            "metadata": {
                                "content": chunk,
                                "source": doc["source"],
                                "source_id": doc["id"],
                                "source_title": doc["title"],
                                "doc_type": tag.get("doc_type", "misc"),
                                "themes": tag.get("themes", []),
                                "key_topics": tag.get("key_topics", []),
                                "contains_data": tag.get("contains_data", False),
                                "is_useful_for_grants": tag.get("is_useful_for_grants", True),
                            },
                        })

        await asyncio.gather(*(process_doc(d) for d in all_docs))

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
            "total_chunks": chunks_saved,
            "pinecone_vectors": pinecone_count,
            "duration_seconds": duration,
        })

        logger.info("Company Brain sync complete: %d chunks in %ds", chunks_saved, duration)
        return {
            "total_chunks": chunks_saved,
            "notion_pages": len(notion_pages),
            "drive_files": len(drive_files),
            "pinecone_vectors": pinecone_count,
        }

    # ── Query interface ────────────────────────────────────────────────────────

    async def query(
        self,
        query_text: str,
        themes: Optional[List[str]] = None,
        doc_types: Optional[List[str]] = None,
        top_k: int = 6,
    ) -> List[Dict]:
        """Vector search for relevant knowledge chunks.

        Uses Pinecone when configured, falls back to MongoDB Atlas Vector Search.
        """
        from backend.db.pinecone_store import is_pinecone_configured, query_similar

        try:
            query_embedding = await self._embed(query_text)
        except Exception as e:
            logger.error("Embedding query failed: %s", e)
            return []

        # ── Pinecone path (preferred) ──
        if is_pinecone_configured():
            pc_filter: Dict[str, Any] = {}
            if themes:
                pc_filter["themes"] = {"$in": themes}
            if doc_types:
                pc_filter["doc_type"] = {"$in": doc_types}
            try:
                results = query_similar(query_embedding, top_k=top_k, filter_dict=pc_filter or None)
                if results:
                    return results
            except Exception as e:
                logger.warning("Pinecone query failed, falling back to MongoDB: %s", e)

        # ── MongoDB Atlas Vector Search (fallback) ──
        vs_filter: Dict[str, Any] = {}
        if themes or doc_types:
            parts = []
            if themes:
                parts.append({"themes": {"$in": themes}})
            if doc_types:
                parts.append({"doc_type": {"$in": doc_types}})
            vs_filter = {"$and": parts} if len(parts) > 1 else parts[0]

        pipeline: List[Dict] = [
            {
                "$vectorSearch": {
                    "index": "knowledge_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                    **({"filter": vs_filter} if vs_filter else {}),
                }
            },
            {
                "$project": {
                    "content": 1,
                    "source_title": 1,
                    "doc_type": 1,
                    "themes": 1,
                    "key_topics": 1,
                    "contains_data": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]

        col = knowledge_chunks()
        results = []
        async for doc in col.aggregate(pipeline):
            doc["_id"] = str(doc.get("_id", ""))
            results.append(doc)

        # Fallback: if vector search returns nothing, do text search
        if not results:
            text_query: Dict[str, Any] = {"is_useful_for_grants": True}
            if themes:
                text_query["themes"] = {"$in": themes}
            if doc_types:
                text_query["doc_type"] = {"$in": doc_types}
            async for doc in col.find(text_query).limit(top_k):
                doc["_id"] = str(doc.get("_id", ""))
                results.append(doc)

        return results

    async def get_style_examples(self) -> List[Dict]:
        """Get past grant application chunks as style examples."""
        return await self.query(
            "grant application proposal writing style",
            doc_types=["past_grant_application"],
            top_k=4,
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

    # Load style examples once
    style_examples = []
    if not state.get("style_examples_loaded"):
        style_examples = await agent.get_style_examples()

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
