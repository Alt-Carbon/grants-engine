"""Sync AltCarbon knowledge profile from Notion via MCP.

Uses the Notion MCP server (persistent connection) to fetch key pages,
extract markdown content, and rebuild backend/knowledge/altcarbon_profile.md.

After sync, updates the Knowledge Connections database in Notion with
per-source status (chars fetched, errors, last sync time).

Triggered via POST /run/sync-profile.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from backend.integrations.notion_mcp import notion_mcp

logger = logging.getLogger(__name__)

PROFILE_PATH = Path(__file__).resolve().parent / "altcarbon_profile.md"

# Key Notion page IDs to pull (curated from workspace)
NOTION_PAGES: Dict[str, str] = {
    "introducing": "24750d0e-c20e-806c-b3a4-c7eae131c6e2",
    "vision_comms": "2e250d0e-c20e-80e0-9ab1-c01a02ca2037",
    "mrv_moat": "1d950d0e-c20e-8036-b964-ff7aa1014e7c",
    "darjeeling_drp": "1f350d0e-c20e-8039-88db-de4f7fde7a54",
    "bengal_brp": "20250d0e-c20e-80da-a093-d4b1795ff6cf",
    "biochar_expansion": "2ef50d0e-c20e-80a2-82dc-e033bb95523d",
    "gigaton_scale": "065b07fd-a740-4f9e-b5a5-a6f189256f24",
    "shopify_report": "2fc50d0e-c20e-8035-99b3-edcc5d503cab",
    "brand_guidebook": "2e850d0e-c20e-80ce-a325-ce02d398888c",
}

# Max chars to keep per section (keeps profile under ~20K total)
SECTION_LIMITS: Dict[str, int] = {
    "vision_comms": 3000,
    "introducing": 5000,
    "mrv_moat": 3000,
    "darjeeling_drp": 3000,
    "bengal_brp": 2000,
    "biochar_expansion": 2000,
    "gigaton_scale": 2000,
    "shopify_report": 1500,
    "brand_guidebook": 1000,
}

SECTION_TITLES: Dict[str, str] = {
    "vision_comms": "Company Vision & Communications",
    "introducing": "Introducing Alt Carbon",
    "mrv_moat": "MRV Moat — Technical Advantage",
    "darjeeling_drp": "Darjeeling Revival Project (ERW)",
    "bengal_brp": "Bengal Renaissance Project (Biochar)",
    "biochar_expansion": "Biochar Expansion Plan",
    "gigaton_scale": "Reaching Gigaton Scale",
    "shopify_report": "Shopify Climate Report",
    "brand_guidebook": "Brand Guidebook",
}


def _build_profile(pages: Dict[str, str]) -> str:
    """Build the markdown profile from fetched page content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections: List[str] = []
    sections.append(
        f"# Alt Carbon — Company Knowledge Base\n"
        f"> Auto-synced from Notion via MCP on {now}\n"
    )

    for key in SECTION_TITLES:
        content = pages.get(key, "")
        if not content:
            continue
        limit = SECTION_LIMITS.get(key, 2000)
        title = SECTION_TITLES[key]
        sections.append(f"## {title}\n\n{content[:limit]}\n")

    # Reference IDs
    ref_lines = ["\n## Key Notion Page IDs\n"]
    for key, page_id in NOTION_PAGES.items():
        title = SECTION_TITLES.get(key, key)
        ref_lines.append(f"- {title}: {page_id}")
    sections.append("\n".join(ref_lines))

    return "\n---\n\n".join(sections)


# ── Connection log updates ──────────────────────────────────────────────────

async def _update_connection_log(
    sync_results: Dict[str, Dict[str, Any]],
    profile_chars: int,
) -> None:
    """Update Knowledge Connections database entries with sync results.

    Uses the Notion MCP to find and update each source's row by section_key.
    Fire-and-forget safe — errors are logged but never propagate.
    """
    from backend.integrations.notion_config import KNOWLEDGE_CONNECTIONS_DS

    if not notion_mcp.connected:
        logger.debug("MCP not connected — skipping connection log update")
        return

    try:
        # Fetch all rows from the connections database
        rows = await notion_mcp.query_data_source(
            KNOWLEDGE_CONNECTIONS_DS, limit=50
        )
    except Exception as e:
        logger.warning("Failed to query Knowledge Connections DB: %s", e)
        return

    # Build section_key → page URL mapping
    key_to_url: Dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict):
            sk = row.get("Section Key", "")
            url = row.get("url", "")
            if sk and url:
                key_to_url[sk] = url

    if not key_to_url:
        logger.warning("No rows found in Knowledge Connections DB")
        return

    # Update each source's connection log entry
    for section_key, result in sync_results.items():
        page_url = key_to_url.get(section_key)
        if not page_url:
            continue

        # Extract page ID from URL (last 32 hex chars)
        page_id = page_url.rstrip("/").split("/")[-1].replace("-", "")
        if len(page_id) < 32:
            continue
        # Format as UUID
        page_id = (
            f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}"
            f"-{page_id[16:20]}-{page_id[20:32]}"
        )

        chars = result.get("chars", 0)
        error = result.get("error", "")

        try:
            await notion_mcp.update_page(
                page_id=page_id,
                properties={
                    "Chars Fetched": chars,
                    "Errors": error[:200] if error else "",
                },
            )
        except Exception as e:
            logger.debug("Failed to update connection log for %s: %s", section_key, e)

    # Also update static_profile entry
    static_url = key_to_url.get("static_profile")
    if static_url:
        page_id = static_url.rstrip("/").split("/")[-1].replace("-", "")
        if len(page_id) >= 32:
            page_id = (
                f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}"
                f"-{page_id[16:20]}-{page_id[20:32]}"
            )
            try:
                await notion_mcp.update_page(
                    page_id=page_id,
                    properties={
                        "Chars Fetched": profile_chars,
                        "Errors": "",
                    },
                )
            except Exception:
                pass

    logger.info("Updated %d connection log entries in Notion", len(sync_results))


# ── Main sync function ──────────────────────────────────────────────────────

async def sync_profile_from_notion() -> Dict[str, Any]:
    """Fetch key Notion pages via MCP and rebuild the static profile.

    Returns summary with page count and file path.
    Also updates Knowledge Connections database in Notion with sync status.
    """
    if not notion_mcp.connected:
        connected = await notion_mcp.connect()
        if not connected:
            return {"status": "error", "error": "Notion MCP not connected"}

    pages: Dict[str, str] = {}
    fetched = 0
    errors = 0
    sync_results: Dict[str, Dict[str, Any]] = {}

    for key, page_id in NOTION_PAGES.items():
        try:
            content = await notion_mcp.fetch_page(page_id)
            if content:
                pages[key] = content
                fetched += 1
                char_count = len(content)
                sync_results[key] = {"chars": char_count, "error": ""}
                logger.info("MCP fetched %s (%d chars)", key, char_count)
            else:
                logger.warning("Empty content for %s (%s)", key, page_id)
                errors += 1
                sync_results[key] = {"chars": 0, "error": "Empty content returned"}
        except Exception as e:
            logger.error("MCP fetch failed for %s: %s", key, e)
            errors += 1
            sync_results[key] = {"chars": 0, "error": str(e)}

    if not pages:
        return {"status": "error", "error": "No pages fetched", "errors": errors}

    # Build and write the profile
    profile = _build_profile(pages)
    PROFILE_PATH.write_text(profile, encoding="utf-8")

    # Clear the cached profile in company_brain so it reloads
    try:
        import backend.agents.company_brain as cb_module
        cb_module._cached_profile = None
    except Exception:
        pass

    # Update connection logs in Notion (fire-and-forget)
    try:
        await _update_connection_log(sync_results, len(profile))
    except Exception as e:
        logger.warning("Connection log update failed: %s", e)

    logger.info(
        "Profile synced via MCP: %d pages, %d chars written to %s",
        fetched, len(profile), PROFILE_PATH,
    )
    return {
        "status": "ok",
        "pages_fetched": fetched,
        "errors": errors,
        "profile_chars": len(profile),
        "profile_path": str(PROFILE_PATH),
    }
