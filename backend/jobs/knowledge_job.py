"""Knowledge sync job — triggered daily at midnight."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_knowledge_sync() -> dict:
    """Sync Notion + Drive → chunk → tag → embed → upsert."""
    from backend.agents.company_brain import CompanyBrainAgent
    from backend.config.settings import get_settings

    s = get_settings()
    agent = CompanyBrainAgent(
        anthropic_api_key=s.anthropic_api_key,
        openai_api_key=s.openai_api_key,
        notion_token=s.notion_token,
        google_refresh_token=s.google_refresh_token,
        google_client_id=s.google_client_id,
        google_client_secret=s.google_client_secret,
    )

    try:
        result = await agent.sync()
        logger.info("Knowledge sync complete: %s", result)
        return {"status": "ok", **result}
    except Exception as e:
        logger.error("Knowledge sync failed: %s", e)
        return {"status": "error", "error": str(e)}
