"""Notion webhook utilities — signature validation, event parsing, source cache."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Set, Tuple

from backend.db.mongo import knowledge_chunks

logger = logging.getLogger(__name__)

# ── Cached known source IDs (from Table of Content) ─────────────────────────
_known_sources: Set[str] = set()
_known_sources_ts: float = 0.0
_CACHE_TTL = 300  # 5 minutes


def validate_signature(body: bytes, signature: str, secret: str) -> bool:
    """Validate X-Notion-Signature header using HMAC-SHA256."""
    if not secret or not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    # Notion sends "v1=<hex>" format
    sig_value = signature.removeprefix("v1=") if signature.startswith("v1=") else signature
    return hmac.compare_digest(expected, sig_value)


def parse_event(payload: dict) -> Tuple[str, str]:
    """Extract (event_type, page_id) from a Notion webhook payload.

    Notion webhook payloads have:
      - type: e.g. "page.content_updated"
      - entity.id: the page ID
    """
    event_type = payload.get("type", "")
    entity = payload.get("entity", {})
    page_id = entity.get("id", "")
    # Normalize: remove dashes from page_id for consistent matching
    if page_id:
        page_id = page_id.replace("-", "")
    return event_type, page_id


async def get_known_source_ids() -> Set[str]:
    """Return set of page IDs registered in Table of Content (cached ~5 min).

    Queries MongoDB knowledge_chunks for distinct source_ids from table_of_content.
    """
    global _known_sources, _known_sources_ts

    now = time.time()
    if _known_sources and (now - _known_sources_ts) < _CACHE_TTL:
        return _known_sources

    try:
        col = knowledge_chunks()
        all_ids = await col.distinct("source_id")
        _known_sources = {str(sid).replace("-", "") for sid in all_ids if sid}
        _known_sources_ts = now
        logger.debug("Refreshed known source IDs cache: %d sources", len(_known_sources))
    except Exception as e:
        logger.warning("Failed to refresh known source IDs: %s", e)
        # Return stale cache rather than empty
        if not _known_sources:
            _known_sources = set()

    return _known_sources


def invalidate_source_cache() -> None:
    """Force cache refresh on next call."""
    global _known_sources_ts
    _known_sources_ts = 0.0
