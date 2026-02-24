"""MongoDB client singleton and collection accessors."""
from __future__ import annotations

import os
from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        from backend.config.settings import get_settings
        uri = get_settings().mongodb_uri
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


async def ensure_indexes():
    """Create all MongoDB indexes. Call once at startup."""
    db = get_db()

    # grants_raw
    await db["grants_raw"].create_index("url_hash", unique=True)
    await db["grants_raw"].create_index("scraped_at")
    await db["grants_raw"].create_index("processed")
    await db["grants_raw"].create_index("normalized_url_hash", sparse=True)
    await db["grants_raw"].create_index("content_hash", sparse=True)
    await db["grants_raw"].create_index("grant_type", sparse=True)

    # grants_scored — url_hash is now the primary dedup key (unique, sparse)
    await db["grants_scored"].create_index("url_hash", unique=True, sparse=True)
    await db["grants_scored"].create_index("raw_grant_id", sparse=True)
    await db["grants_scored"].create_index("status")
    await db["grants_scored"].create_index([("weighted_total", -1)])
    await db["grants_scored"].create_index("deadline")
    await db["grants_scored"].create_index("content_hash", sparse=True)
    await db["grants_scored"].create_index("grant_type", sparse=True)
    await db["grants_scored"].create_index([("funder", 1), ("title", 1)], sparse=True)
    await db["grants_scored"].create_index("scored_at")

    # grants_pipeline
    await db["grants_pipeline"].create_index("grant_id")
    await db["grants_pipeline"].create_index("thread_id", unique=True)
    await db["grants_pipeline"].create_index("status")

    # grant_drafts
    await db["grant_drafts"].create_index("pipeline_id")
    await db["grant_drafts"].create_index("grant_id")
    await db["grant_drafts"].create_index([("pipeline_id", 1), ("version", -1)])

    # knowledge_chunks
    await db["knowledge_chunks"].create_index("source_id")
    await db["knowledge_chunks"].create_index("doc_type")
    await db["knowledge_chunks"].create_index("themes")
    await db["knowledge_chunks"].create_index("last_synced")

    # graph_checkpoints / audit_logs / config
    await db["graph_checkpoints"].create_index([("thread_id", 1), ("checkpoint_id", -1)])
    await db["audit_logs"].create_index([("created_at", -1)])
    await db["audit_logs"].create_index("node")
    await db["agent_config"].create_index("agent", unique=True)

    # funder context cache (7-day TTL index on cached_at)
    await db["funder_context_cache"].create_index("funder", unique=True)
    await db["funder_context_cache"].create_index(
        "cached_at",
        expireAfterSeconds=7 * 24 * 3600,  # MongoDB TTL — auto-deletes stale entries
    )
