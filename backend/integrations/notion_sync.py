"""Sync engine state to Notion Mission Control databases.

All functions are fire-and-forget safe — errors are logged but never
propagate to the caller, so agent pipelines are never blocked by Notion.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from notion_client import AsyncClient

from backend.config.settings import get_settings
from backend.integrations.notion_config import (
    AGENT_DISPLAY,
    AGENT_RUNS_DS,
    DRAFT_SECTIONS_DS,
    ERROR_LOGS_DS,
    GRANT_PIPELINE_DS,
    STATUS_MAP,
    THEME_DISPLAY,
    TRIAGE_DECISIONS_DS,
    get_priority_label,
)

log = logging.getLogger(__name__)

# ── Notion client singleton ──────────────────────────────────────────────────

_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _client
    if _client is None:
        token = get_settings().notion_token
        if not token:
            raise RuntimeError("NOTION_TOKEN not set — cannot sync to Notion")
        _client = AsyncClient(auth=token)
    return _client


# ── Helper: find existing page by MongoDB ID ─────────────────────────────────

async def _find_page_by_mongo_id(
    database_id: str, mongo_id: str, title_prop: str = "Grant Name"
) -> str | None:
    """Search a Notion database for a page whose 'MongoDB ID' matches.

    Returns the Notion page ID if found, else None.
    """
    try:
        client = _get_client()
        resp = await client.databases.query(
            database_id=database_id,
            filter={"property": "MongoDB ID", "rich_text": {"equals": mongo_id}},
            page_size=1,
        )
        if resp["results"]:
            return resp["results"][0]["id"]
    except Exception:
        log.debug("Notion lookup failed for %s in %s", mongo_id, database_id, exc_info=True)
    return None


async def _store_notion_url(mongo_id: str, notion_page_id: str) -> None:
    """Store the Notion page URL back in MongoDB for dashboard cross-linking."""
    try:
        from backend.db.mongo import grants_scored
        from bson import ObjectId
        notion_url = f"https://notion.so/{notion_page_id.replace('-', '')}"
        await grants_scored().update_one(
            {"_id": ObjectId(mongo_id)},
            {"$set": {"notion_page_url": notion_url}},
        )
    except Exception:
        log.debug("Failed to store Notion URL for %s", mongo_id, exc_info=True)


# ── Grant Pipeline sync ──────────────────────────────────────────────────────

async def sync_scored_grant(grant: dict[str, Any]) -> str | None:
    """Upsert a scored grant into the Notion Grant Pipeline database.

    Returns the Notion page ID on success, None on failure.
    """
    try:
        client = _get_client()
        mongo_id = str(grant.get("_id", ""))
        score = grant.get("weighted_total", 0) or 0
        status_raw = grant.get("status", "triage")
        themes_raw: list[str] = grant.get("themes_detected", []) or []

        # Build properties dict
        props: dict[str, Any] = {
            "Grant Name": {"title": [{"text": {"content": grant.get("grant_name") or grant.get("title") or "Unnamed"}}]},
            "Funder": {"rich_text": [{"text": {"content": grant.get("funder", "") or ""}}]},
            "Score": {"number": round(score, 2)},
            "Priority": {"select": {"name": get_priority_label(score)}},
            "Status": {"select": {"name": STATUS_MAP.get(status_raw, "Triage")}},
            "Themes": {"multi_select": [{"name": THEME_DISPLAY.get(t, t)} for t in themes_raw if THEME_DISPLAY.get(t, t)]},
            "Geography": {"rich_text": [{"text": {"content": grant.get("geography", "") or ""}}]},
            "Grant Type": {"rich_text": [{"text": {"content": grant.get("grant_type", "") or ""}}]},
            "Eligibility": {"rich_text": [{"text": {"content": (grant.get("eligibility", "") or "")[:2000]}}]},
            "AI Rationale": {"rich_text": [{"text": {"content": (grant.get("rationale", "") or "")[:2000]}}]},
            "MongoDB ID": {"rich_text": [{"text": {"content": mongo_id}}]},
        }

        # Optional fields
        rec = grant.get("recommended_action")
        if rec:
            props["AI Recommendation"] = {"select": {"name": rec}}

        url = grant.get("url")
        if url:
            props["Grant URL"] = {"url": url}

        funding = grant.get("max_funding_usd") or grant.get("max_funding")
        if funding:
            props["Funding USD"] = {"number": funding}

        deadline = grant.get("deadline")
        if deadline:
            dl = deadline[:10] if isinstance(deadline, str) else deadline.strftime("%Y-%m-%d")
            props["Deadline"] = {"date": {"start": dl}}

        scored_at = grant.get("scored_at")
        if scored_at:
            sa = scored_at.isoformat() if hasattr(scored_at, "isoformat") else str(scored_at)[:10]
            props["Scored At"] = {"date": {"start": sa}}

        # Upsert: check if page exists
        existing_id = await _find_page_by_mongo_id(GRANT_PIPELINE_DS, mongo_id)

        if existing_id:
            await client.pages.update(page_id=existing_id, properties=props)
            log.info("Notion: updated grant %s (%s)", mongo_id, existing_id)
            # Store Notion page URL back in MongoDB for cross-linking
            await _store_notion_url(mongo_id, existing_id)
            return existing_id
        else:
            page = await client.pages.create(
                parent={"database_id": GRANT_PIPELINE_DS},
                properties=props,
            )
            log.info("Notion: created grant %s (%s)", mongo_id, page["id"])
            await _store_notion_url(mongo_id, page["id"])
            return page["id"]

    except Exception:
        log.warning("Notion sync_scored_grant failed", exc_info=True)
        return None


async def update_grant_status(mongo_id: str, new_status: str) -> bool:
    """Update just the status of an existing grant in Notion."""
    try:
        client = _get_client()
        existing_id = await _find_page_by_mongo_id(GRANT_PIPELINE_DS, mongo_id)
        if not existing_id:
            log.debug("Notion: grant %s not found for status update", mongo_id)
            return False

        notion_status = STATUS_MAP.get(new_status, "Triage")
        await client.pages.update(
            page_id=existing_id,
            properties={"Status": {"select": {"name": notion_status}}},
        )
        log.info("Notion: updated status for %s → %s", mongo_id, notion_status)
        return True
    except Exception:
        log.warning("Notion update_grant_status failed", exc_info=True)
        return False


# ── Agent Runs logging ───────────────────────────────────────────────────────

async def log_agent_run(
    agent: str,
    status: str,
    trigger: str = "Manual",
    started_at: datetime | None = None,
    duration_seconds: float | None = None,
    grants_found: int | None = None,
    grants_scored: int | None = None,
    errors: int = 0,
    summary: str = "",
) -> str | None:
    """Create a row in the Agent Runs database."""
    try:
        client = _get_client()
        agent_display = AGENT_DISPLAY.get(agent, agent.title())
        ts = started_at or datetime.now(timezone.utc)

        duration_str = ""
        if duration_seconds is not None:
            mins = int(duration_seconds // 60)
            secs = int(duration_seconds % 60)
            duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        props: dict[str, Any] = {
            "Run": {"title": [{"text": {"content": f"{agent_display} — {ts.strftime('%b %d %H:%M')}"}}]},
            "Agent": {"select": {"name": agent_display}},
            "Status": {"select": {"name": status}},
            "Trigger": {"select": {"name": trigger}},
            "Started At": {"date": {"start": ts.isoformat()}},
            "Errors": {"number": errors},
        }

        if duration_str:
            props["Duration"] = {"rich_text": [{"text": {"content": duration_str}}]}
        if grants_found is not None:
            props["Grants Found"] = {"number": grants_found}
        if grants_scored is not None:
            props["Grants Scored"] = {"number": grants_scored}
        if summary:
            props["Summary"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

        page = await client.pages.create(
            parent={"database_id": AGENT_RUNS_DS},
            properties=props,
        )
        log.info("Notion: logged %s run (%s) — %s", agent_display, status, page["id"])
        return page["id"]

    except Exception:
        log.warning("Notion log_agent_run failed", exc_info=True)
        return None


async def update_agent_run(
    page_id: str,
    status: str,
    duration_seconds: float | None = None,
    grants_found: int | None = None,
    grants_scored: int | None = None,
    errors: int | None = None,
    summary: str | None = None,
) -> bool:
    """Update an existing agent run page (e.g. Running → Completed)."""
    try:
        client = _get_client()
        props: dict[str, Any] = {
            "Status": {"select": {"name": status}},
        }

        if duration_seconds is not None:
            mins = int(duration_seconds // 60)
            secs = int(duration_seconds % 60)
            duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            props["Duration"] = {"rich_text": [{"text": {"content": duration_str}}]}
        if grants_found is not None:
            props["Grants Found"] = {"number": grants_found}
        if grants_scored is not None:
            props["Grants Scored"] = {"number": grants_scored}
        if errors is not None:
            props["Errors"] = {"number": errors}
        if summary:
            props["Summary"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

        await client.pages.update(page_id=page_id, properties=props)
        log.info("Notion: updated run %s → %s", page_id, status)
        return True
    except Exception:
        log.warning("Notion update_agent_run failed", exc_info=True)
        return False


# ── Error Logs ───────────────────────────────────────────────────────────────

async def log_error(
    agent: str,
    error: Exception | str,
    tb: str | None = None,
    grant_name: str = "",
    severity: str = "Critical",
) -> str | None:
    """Create an error log page with full traceback in the body."""
    try:
        client = _get_client()
        agent_display = AGENT_DISPLAY.get(agent, agent.title())
        error_msg = str(error)[:200]
        error_type = type(error).__name__ if isinstance(error, Exception) else "Error"
        tb_text = tb or (traceback.format_exc() if isinstance(error, Exception) else "")
        ts = datetime.now(timezone.utc)

        props: dict[str, Any] = {
            "Error": {"title": [{"text": {"content": error_msg}}]},
            "Agent": {"select": {"name": agent_display}},
            "Severity": {"select": {"name": severity}},
            "Error Type": {"rich_text": [{"text": {"content": error_type}}]},
            "Timestamp": {"date": {"start": ts.isoformat()}},
            "Resolved": {"checkbox": False},
        }

        if grant_name:
            props["Grant Name"] = {"rich_text": [{"text": {"content": grant_name[:200]}}]}

        # Create page with traceback as body content
        children = []
        if tb_text:
            # Notion blocks have a 2000-char limit per rich_text item
            for chunk in [tb_text[i:i + 1900] for i in range(0, len(tb_text), 1900)]:
                children.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"text": {"content": chunk}}],
                        "language": "python",
                    },
                })

        page = await client.pages.create(
            parent={"database_id": ERROR_LOGS_DS},
            properties=props,
            children=children if children else None,
        )
        log.info("Notion: logged error for %s (%s)", agent_display, page["id"])
        return page["id"]

    except Exception:
        log.warning("Notion log_error failed", exc_info=True)
        return None


# ── Triage Decisions ─────────────────────────────────────────────────────────

async def log_triage_decision(
    grant_id: str,
    grant_name: str,
    decision: str,
    ai_recommendation: str | None = None,
    is_override: bool = False,
    override_reason: str = "",
    decided_by: str = "",
) -> str | None:
    """Log a human triage decision to the Triage Decisions database."""
    try:
        client = _get_client()
        ts = datetime.now(timezone.utc)

        props: dict[str, Any] = {
            "Decision": {"title": [{"text": {"content": f"{decision.title()} — {grant_name[:80]}"}}]},
            "Grant Name": {"rich_text": [{"text": {"content": grant_name[:200]}}]},
            "Action": {"select": {"name": decision.title()}},
            "Is Override": {"checkbox": is_override},
            "Decided At": {"date": {"start": ts.isoformat()}},
            "MongoDB Grant ID": {"rich_text": [{"text": {"content": grant_id}}]},
        }

        if ai_recommendation:
            props["AI Recommendation"] = {"select": {"name": ai_recommendation}}
        if override_reason:
            props["Override Reason"] = {"rich_text": [{"text": {"content": override_reason[:2000]}}]}
        if decided_by:
            props["Decided By"] = {"rich_text": [{"text": {"content": decided_by}}]}

        page = await client.pages.create(
            parent={"database_id": TRIAGE_DECISIONS_DS},
            properties=props,
        )
        log.info("Notion: logged triage %s for %s (%s)", decision, grant_name, page["id"])
        return page["id"]

    except Exception:
        log.warning("Notion log_triage_decision failed", exc_info=True)
        return None


# ── Draft Sections ───────────────────────────────────────────────────────────

async def sync_draft_section(
    grant_id: str,
    grant_name: str,
    section_name: str,
    content: str,
    word_count: int = 0,
    word_limit: int = 0,
    version: int = 1,
    status: str = "Draft",
    evidence_gaps: list[str] | None = None,
    revision_notes: str = "",
) -> str | None:
    """Upsert a draft section in the Draft Sections database.

    Content is placed in the page body (not a property) since it can be long.
    """
    try:
        client = _get_client()

        props: dict[str, Any] = {
            "Section": {"title": [{"text": {"content": f"{section_name} — {grant_name[:60]}"}}]},
            "Grant Name": {"rich_text": [{"text": {"content": grant_name[:200]}}]},
            "Status": {"select": {"name": status}},
            "Word Count": {"number": word_count},
            "Word Limit": {"number": word_limit},
            "Version": {"number": version},
            "MongoDB Grant ID": {"rich_text": [{"text": {"content": grant_id}}]},
        }

        if evidence_gaps:
            gaps_text = "\n".join(f"- {g}" for g in evidence_gaps)
            props["Evidence Gaps"] = {"rich_text": [{"text": {"content": gaps_text[:2000]}}]}
        if revision_notes:
            props["Revision Notes"] = {"rich_text": [{"text": {"content": revision_notes[:2000]}}]}

        # Build page body with the section content
        children = []
        if content:
            for chunk in [content[i:i + 1900] for i in range(0, len(content), 1900)]:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": chunk}}],
                    },
                })

        # Try to find existing page for this section + grant
        existing_id = None
        try:
            resp = await client.databases.query(
                database_id=DRAFT_SECTIONS_DS,
                filter={
                    "and": [
                        {"property": "MongoDB Grant ID", "rich_text": {"equals": grant_id}},
                        {"property": "Section", "title": {"starts_with": section_name}},
                    ]
                },
                page_size=1,
            )
            if resp["results"]:
                existing_id = resp["results"][0]["id"]
        except Exception:
            pass

        if existing_id:
            await client.pages.update(page_id=existing_id, properties=props)
            # Can't replace children via pages.update — archive and note in log
            log.info("Notion: updated draft section %s for %s", section_name, grant_name)
            return existing_id
        else:
            page = await client.pages.create(
                parent={"database_id": DRAFT_SECTIONS_DS},
                properties=props,
                children=children if children else None,
            )
            log.info("Notion: created draft section %s for %s (%s)", section_name, grant_name, page["id"])
            return page["id"]

    except Exception:
        log.warning("Notion sync_draft_section failed", exc_info=True)
        return None


# ── Bulk sync (for initial backfill) ─────────────────────────────────────────

async def backfill_grants(grants: list[dict[str, Any]]) -> int:
    """Sync a list of scored grants to Notion. Returns count of successful syncs."""
    count = 0
    for grant in grants:
        result = await sync_scored_grant(grant)
        if result:
            count += 1
    log.info("Notion backfill: synced %d / %d grants", count, len(grants))
    return count
