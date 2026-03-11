"""Pinecone vector store with Integrated Inference — embeds text server-side.

Index created with `create_index_for_model(embed.model='multilingual-e5-large')`.
Pinecone auto-embeds the 'content' field on upsert and search — no external
embedding API needed.

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
    """Return the Pinecone index singleton (with integrated inference)."""
    global _index
    if _index is not None:
        return _index

    settings = get_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY not set")

    from pinecone import Pinecone

    pc = Pinecone(api_key=settings.pinecone_api_key)
    index_name = settings.pinecone_index_name

    if not pc.has_index(index_name):
        logger.info("Creating Pinecone index '%s' with integrated inference", index_name)
        pc.create_index_for_model(
            name=index_name,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": "multilingual-e5-large",
                "field_map": {"text": "content"},
            },
        )

    _index = pc.Index(index_name)
    logger.info("Pinecone index '%s' ready (integrated inference)", index_name)
    return _index


def upsert_chunks(chunks: List[Dict[str, Any]], namespace: str = "knowledge") -> int:
    """Batch upsert text records. Pinecone embeds the 'content' field server-side.

    Each dict must have:
      - '_id': str  (e.g. "source_id#chunk_index")
      - 'content': str  (text to embed)
      - any other fields become searchable metadata
    """
    import time

    idx = get_pinecone_index()
    batch_size = 20  # Conservative for integrated inference (embeds server-side)
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        idx.upsert_records(namespace=namespace, records=batch)
        total += len(batch)
        if i + batch_size < len(chunks):
            time.sleep(1)  # Rate limit: avoid 429
    return total


def search_similar(
    query_text: str,
    top_k: int = 6,
    filter_dict: Optional[Dict[str, Any]] = None,
    namespace: str = "knowledge",
) -> List[Dict[str, Any]]:
    """Search Pinecone with a text query. Embedding happens server-side.

    Returns list of dicts with metadata + score.
    """
    idx = get_pinecone_index()

    search_kwargs: Dict[str, Any] = {
        "namespace": namespace,
        "query": {"top_k": top_k, "inputs": {"text": query_text}},
    }
    if filter_dict:
        search_kwargs["query"]["filter"] = filter_dict

    result = idx.search(**search_kwargs)

    matches: List[Dict[str, Any]] = []
    # result.result.hits contains the search hits
    hits = result.get("result", {}).get("hits", [])
    for hit in hits:
        doc = dict(hit.get("fields", {}))
        doc["score"] = hit.get("_score", 0)
        doc["_id"] = hit.get("_id", "")
        matches.append(doc)
    return matches


# Keep backward compat alias
query_similar = search_similar
