"""MongoDB client singleton and collection accessors."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        from backend.config.settings import get_settings
        uri = get_settings().mongodb_uri.strip()
        if not uri:
            logger.error(
                "MONGODB_URI is empty or not set — all database operations will fail. "
                "Set the MONGODB_URI environment variable to a valid MongoDB connection string."
            )
        _client = AsyncIOMotorClient(uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()["altcarbon_grants"]


# Collection helpers — call these anywhere
def graph_checkpoints():
    return get_db()["graph_checkpoints"]

def grants_raw():
    return get_db()["grants_raw"]

def grants_scored():
    return get_db()["grants_scored"]

def grants_pipeline():
    return get_db()["grants_pipeline"]

def grant_drafts():
    return get_db()["grant_drafts"]

def draft_reviews():
    return get_db()["draft_reviews"]

def grant_outcomes():
    return get_db()["grant_outcomes"]

def golden_examples():
    return get_db()["golden_examples"]

def knowledge_chunks():
    return get_db()["knowledge_chunks"]

def knowledge_sync_logs():
    return get_db()["knowledge_sync_logs"]

def agent_config():
    return get_db()["agent_config"]

def audit_logs():
    return get_db()["audit_logs"]

def scout_runs():
    return get_db()["scout_runs"]

def funder_context_cache():
    return get_db()["funder_context_cache"]

def drafter_chat_history():
    return get_db()["drafter_chat_history"]

def notion_page_cache():
    return get_db()["notion_page_cache"]

def draft_preferences():
    return get_db()["draft_preferences"]

def chat_snapshots():
    return get_db()["chat_snapshots"]

def workflow_runs():
    return get_db()["workflow_runs"]


async def ensure_indexes():
    """Create all MongoDB indexes. Call once at startup. Skips indexes that already exist."""
    import logging
    from pymongo.errors import OperationFailure
    log = logging.getLogger(__name__)
    db = get_db()

    async def _idx(col, *args, **kwargs):
        try:
            await db[col].create_index(*args, **kwargs)
        except OperationFailure as e:
            log.warning("Index already exists (skipping): %s — %s", col, e)

    # grants_raw
    await _idx("grants_raw", "url_hash", unique=True)
    await _idx("grants_raw", "scraped_at")
    await _idx("grants_raw", "processed")
    await _idx("grants_raw", "normalized_url_hash", sparse=True)
    await _idx("grants_raw", "content_hash", sparse=True)
    await _idx("grants_raw", "grant_type", sparse=True)

    # grants_scored
    await _idx("grants_scored", "url_hash", unique=True, sparse=True)
    await _idx("grants_scored", "raw_grant_id")
    await _idx("grants_scored", "status")
    await _idx("grants_scored", [("weighted_total", -1)])
    await _idx("grants_scored", "deadline")
    await _idx("grants_scored", "content_hash", sparse=True)
    await _idx("grants_scored", "grant_type", sparse=True)
    await _idx("grants_scored", [("funder", 1), ("title", 1)], sparse=True)
    await _idx("grants_scored", "scored_at")
    await _idx("grants_scored", [("deadline_urgent", 1), ("status", 1)])

    # grants_pipeline
    await _idx("grants_pipeline", "grant_id")
    await _idx("grants_pipeline", "thread_id", unique=True)
    await _idx("grants_pipeline", "status")
    await _idx("grants_pipeline", [("status", 1), ("started_at", -1)])

    # grant_drafts
    await _idx("grant_drafts", "pipeline_id")
    await _idx("grant_drafts", "grant_id")
    await _idx("grant_drafts", [("pipeline_id", 1), ("version", -1)])

    # draft_reviews
    await _idx("draft_reviews", "grant_id")
    await _idx("draft_reviews", [("grant_id", 1), ("perspective", 1)])
    await _idx("draft_reviews", [("created_at", -1)])

    # grant_outcomes (feedback learning)
    await _idx("grant_outcomes", "grant_id", unique=True)
    await _idx("grant_outcomes", "funder")
    await _idx("grant_outcomes", [("themes", 1)])
    await _idx("grant_outcomes", [("outcome", 1), ("created_at", -1)])

    # golden_examples (few-shot learning)
    await _idx("golden_examples", [("agent", 1), ("quality_score", -1)])
    await _idx("golden_examples", [("agent", 1), ("theme", 1)])
    await _idx("golden_examples", "agent")

    # knowledge_chunks
    await _idx("knowledge_chunks", "source_id")
    await _idx("knowledge_chunks", [("source_id", 1), ("chunk_index", 1)], unique=True)
    await _idx("knowledge_chunks", "doc_type")
    await _idx("knowledge_chunks", "themes")
    await _idx("knowledge_chunks", "content_hash", sparse=True)
    await _idx("knowledge_chunks", "last_synced")
    # NOTE: Vector search is handled by Pinecone Integrated Inference.
    # MongoDB stores chunks as metadata/fallback only (no embeddings stored).

    # graph_checkpoints / audit_logs / config
    await _idx("graph_checkpoints", [("thread_id", 1), ("checkpoint_id", -1)])
    await _idx("audit_logs", [("created_at", -1)])
    await _idx("audit_logs", "node")
    await _idx("audit_logs", [("node", 1), ("created_at", -1)])
    await _idx("audit_logs", [("action", 1), ("created_at", -1)])
    await _idx("agent_config", "agent", unique=True)

    # funder context cache (7-day TTL index on cached_at)
    await _idx("funder_context_cache", "funder", unique=True)
    await _idx("funder_context_cache", "cached_at", expireAfterSeconds=7 * 24 * 3600)

    # deep research cache (7-day TTL)
    await _idx("deep_research_cache", "url_hash", unique=True)
    await _idx("deep_research_cache", "cached_at", expireAfterSeconds=7 * 24 * 3600)

    # drafter chat history (per-user: compound key)
    await _idx("drafter_chat_history", [("pipeline_id", 1), ("user_email", 1)], unique=True)

    # notion_page_cache (24-hour TTL for content fetcher)
    await _idx("notion_page_cache", "source_id", unique=True)
    await _idx("notion_page_cache", "cached_at", expireAfterSeconds=24 * 60 * 60)

    # notifications (30-day TTL auto-delete)
    await _idx("notifications", [("user_email", 1), ("read", 1), ("created_at", -1)])
    await _idx("notifications", "created_at", expireAfterSeconds=30 * 24 * 3600)
    await _idx("notifications", [("type", 1), ("created_at", -1)])

    # chat_snapshots (conversation history / versioning)
    await _idx("chat_snapshots", [("pipeline_id", 1), ("user_email", 1), ("snapshot_at", -1)])
    await _idx("chat_snapshots", [("pipeline_id", 1), ("snapshot_at", -1)])
    await _idx("chat_snapshots", "snapshot_at", expireAfterSeconds=90 * 24 * 3600)  # 90-day TTL

    # workflow_runs (durable queue / execution history)
    await _idx("workflow_runs", "workflow_id", unique=True)
    await _idx("workflow_runs", [("status", 1), ("created_at", 1)])
    await _idx("workflow_runs", [("workflow_name", 1), ("status", 1), ("created_at", 1)])
    await _idx("workflow_runs", [("lease_expires_at", 1)])

    # draft_preferences (preference learning)
    await _idx("draft_preferences", [("user_id", 1), ("created_at", -1)])
    await _idx("draft_preferences", [("user_id", 1), ("section_name", 1)])
    await _idx("draft_preferences", [("user_id", 1), ("theme", 1)])
    await _idx("draft_preferences", "grant_id")

    # knowledge_sync_logs
    await _idx("knowledge_sync_logs", [("synced_at", -1)])

    # grant_comments (if not already covered)
    await _idx("grant_comments", "grant_id")
    await _idx("grant_comments", [("created_at", -1)])
