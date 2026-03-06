"""Knowledge sync job — triggered daily at midnight."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _update_vector_store_log(result: dict) -> None:
    """Update the vector_store entry in Knowledge Connections DB."""
    try:
        from backend.integrations.notion_mcp import notion_mcp
        from backend.integrations.notion_config import KNOWLEDGE_CONNECTIONS_DS

        if not notion_mcp.connected:
            return

        rows = await notion_mcp.query_data_source(
            KNOWLEDGE_CONNECTIONS_DS, limit=50
        )

        for row in rows:
            if isinstance(row, dict) and row.get("Section Key") == "vector_store":
                page_url = row.get("url", "")
                page_id = page_url.rstrip("/").split("/")[-1].replace("-", "")
                if len(page_id) < 32:
                    break
                page_id = (
                    f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}"
                    f"-{page_id[16:20]}-{page_id[20:32]}"
                )

                chunks = result.get("chunks_upserted", 0)
                error_msg = result.get("error", "")
                await notion_mcp.update_page(
                    page_id=page_id,
                    properties={
                        "Chars Fetched": chunks,
                        "Errors": error_msg[:200] if error_msg else "",
                    },
                )
                logger.info("Updated vector_store connection log: %d chunks", chunks)
                break
    except Exception as e:
        logger.debug("Vector store connection log update failed: %s", e)


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

        # Update connection log in Notion
        await _update_vector_store_log(result)

        return {"status": "ok", **result}
    except Exception as e:
        logger.error("Knowledge sync failed: %s", e)

        # Log error to connection log
        await _update_vector_store_log({"error": str(e)})

        return {"status": "error", "error": str(e)}
