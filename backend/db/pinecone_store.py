"""Pinecone vector store — optional, falls back to MongoDB when not configured.

Lazy singleton: initialises on first use. Creates index if missing.
Vector ID format: {source_id}#{chunk_index}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

_index = None


def is_pinecone_configured() -> bool:
    return bool(get_settings().pinecone_api_key)


def get_pinecone_index():
    """Return (or create) the Pinecone index singleton."""
    global _index
    if _index is not None:
        return _index

    settings = get_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY not set")

    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=settings.pinecone_api_key)
    index_name = settings.pinecone_index_name

    # Create index if it doesn't exist
    existing = [i.name for i in pc.list_indexes()]
    if index_name not in existing:
        logger.info("Creating Pinecone index '%s'", index_name)
        pc.create_index(
            name=index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    _index = pc.Index(index_name)
    logger.info("Pinecone index '%s' ready", index_name)
    return _index


def upsert_chunks(vectors: List[Dict[str, Any]], namespace: str = "knowledge") -> int:
    """Batch upsert vectors. Each dict must have 'id', 'values', 'metadata'."""
    idx = get_pinecone_index()
    batch_size = 100
    total = 0
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        idx.upsert(vectors=batch, namespace=namespace)
        total += len(batch)
    return total


def query_similar(
    embedding: List[float],
    top_k: int = 6,
    filter_dict: Optional[Dict[str, Any]] = None,
    namespace: str = "knowledge",
) -> List[Dict[str, Any]]:
    """Query Pinecone for similar vectors. Returns matches with metadata."""
    idx = get_pinecone_index()
    result = idx.query(
        vector=embedding,
        top_k=top_k,
        filter=filter_dict or {},
        include_metadata=True,
        namespace=namespace,
    )
    matches = []
    for m in result.get("matches", []):
        doc = dict(m.get("metadata", {}))
        doc["score"] = m.get("score", 0)
        doc["_id"] = m.get("id", "")
        matches.append(doc)
    return matches
