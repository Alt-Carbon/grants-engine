"""Company Brain Agent — AltCarbon's institutional memory.

Syncs from Notion + Google Drive, chunks content, tags with Claude Haiku,
embeds with OpenAI text-embedding-3-small, stores in MongoDB Atlas Vector Search.

Query interface: given a grant's themes and requirements, return the most
relevant chunks to ground Analyst scoring and Drafter writing.
"""
from __future__ import annotations

import asyncio
import logging
import re
import textwrap
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from backend.db.mongo import knowledge_chunks, knowledge_sync_logs
from backend.graph.state import GrantState
from backend.utils.llm import chat, HAIKU

logger = logging.getLogger(__name__)

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
        if not self.notion_token:
            logger.warning("NOTION_TOKEN not set — skipping Notion sync")
            return []
        import httpx
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        pages = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Search all pages
                r = await client.post(
                    "https://api.notion.com/v1/search",
                    headers=headers,
                    json={"filter": {"value": "page", "property": "object"}, "page_size": 100},
                )
                r.raise_for_status()
                results = r.json().get("results", [])

                for page in results:
                    page_id = page["id"]
                    title = ""
                    # Get title from properties
                    props = page.get("properties", {})
                    for prop in props.values():
                        if prop.get("type") == "title":
                            title_parts = prop.get("title", [])
                            title = "".join(t.get("plain_text", "") for t in title_parts)
                            break

                    # Fetch page blocks (content)
                    blocks_r = await client.get(
                        f"https://api.notion.com/v1/blocks/{page_id}/children",
                        headers=headers,
                    )
                    if blocks_r.status_code != 200:
                        continue
                    blocks = blocks_r.json().get("results", [])
                    text = self._blocks_to_text(blocks)
                    if len(text.split()) < MIN_CHUNK_WORDS:
                        continue
                    pages.append({"id": page_id, "title": title, "text": text, "source": "notion"})

        except Exception as e:
            logger.error("Notion sync error: %s", e)

        logger.info("Notion: fetched %d pages", len(pages))
        return pages

    def _blocks_to_text(self, blocks: List[Dict]) -> str:
        lines = []
        for block in blocks:
            btype = block.get("type", "")
            content = block.get(btype, {})
            rich = content.get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich)
            if text.strip():
                lines.append(text)
        return "\n".join(lines)

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
        """Sync Notion + Drive → chunk → tag → embed → upsert to MongoDB."""
        start = datetime.now(timezone.utc)
        logger.info("Company Brain: starting knowledge sync")

        notion_pages, drive_files = await asyncio.gather(
            self._fetch_notion_pages(),
            self._fetch_drive_files(),
        )
        all_docs = notion_pages + drive_files
        logger.info("Company Brain: %d total documents to process", len(all_docs))

        col = knowledge_chunks()
        chunks_saved = 0
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

        await asyncio.gather(*(process_doc(d) for d in all_docs))

        duration = (datetime.now(timezone.utc) - start).seconds
        await knowledge_sync_logs().insert_one({
            "synced_at": start.isoformat(),
            "notion_pages": len(notion_pages),
            "drive_files": len(drive_files),
            "total_chunks": chunks_saved,
            "duration_seconds": duration,
        })

        logger.info("Company Brain sync complete: %d chunks in %ds", chunks_saved, duration)
        return {
            "total_chunks": chunks_saved,
            "notion_pages": len(notion_pages),
            "drive_files": len(drive_files),
        }

    # ── Query interface ────────────────────────────────────────────────────────

    async def query(
        self,
        query_text: str,
        themes: Optional[List[str]] = None,
        doc_types: Optional[List[str]] = None,
        top_k: int = 6,
    ) -> List[Dict]:
        """Vector search for relevant knowledge chunks."""
        try:
            query_embedding = await self._embed(query_text)
        except Exception as e:
            logger.error("Embedding query failed: %s", e)
            return []

        pipeline: List[Dict] = [
            {
                "$vectorSearch": {
                    "index": "knowledge_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                    **({"filter": {"themes": {"$in": themes}}} if themes else {}),
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
            query = {"is_useful_for_grants": True}
            if themes:
                query["themes"] = {"$in": themes}
            if doc_types:
                query["doc_type"] = {"$in": doc_types}
            async for doc in col.find(query).limit(top_k):
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
