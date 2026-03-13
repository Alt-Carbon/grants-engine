"""Notion Data Access Layer — primary CRUD for grants in the Grant Pipeline DB.

This replaces MongoDB as the primary store for grants. All grant reads/writes
go through here. Rate-limited to respect Notion's 3 req/sec limit.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from notion_client import AsyncClient

from backend.config.settings import get_settings
from backend.integrations.notion_config import (
    GRANT_PIPELINE_DS,
    STATUS_MAP,
    THEME_DISPLAY,
    get_priority_label,
)

# Notion data source (collection) ID for the Grant Pipeline.
# In notion-client v3 (API 2025-09-03), page creation requires data_source_id.
GRANT_PIPELINE_COLLECTION = "f6e99042-f99d-4e29-9bbe-fc695c790ef8"

log = logging.getLogger(__name__)

# ── Rate limiter: Notion allows ~3 requests/sec ─────────────────────────────
_rate_sem = asyncio.Semaphore(3)


async def _rate_limited(coro):
    """Execute a coroutine under the Notion rate limiter."""
    async with _rate_sem:
        try:
            return await coro
        finally:
            # Sliding window: wait 350ms after each request
            await asyncio.sleep(0.35)


# ── Client singleton ────────────────────────────────────────────────────────
_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _client
    if _client is None:
        token = get_settings().notion_token
        if not token:
            raise RuntimeError("NOTION_TOKEN not set — cannot access Notion")
        _client = AsyncClient(auth=token)
    return _client


# ── Property extraction helpers ─────────────────────────────────────────────

def _extract_text(prop: dict) -> str:
    """Extract plain text from a Notion rich_text or title property."""
    arr = prop.get("rich_text") or prop.get("title") or []
    return "".join(seg.get("plain_text", "") for seg in arr).strip()


def _extract_select(prop: dict) -> str | None:
    """Extract name from a Notion select property."""
    sel = prop.get("select")
    return sel["name"] if sel else None


def _extract_multi_select(prop: dict) -> list[str]:
    """Extract names from a Notion multi_select property."""
    return [s["name"] for s in (prop.get("multi_select") or [])]


def _extract_number(prop: dict) -> float | None:
    """Extract number from a Notion number property."""
    return prop.get("number")


def _extract_url(prop: dict) -> str | None:
    """Extract URL from a Notion url property."""
    return prop.get("url")


def _extract_date(prop: dict) -> str | None:
    """Extract start date from a Notion date property."""
    d = prop.get("date")
    return d["start"] if d else None


def _extract_checkbox(prop: dict) -> bool:
    """Extract checkbox value."""
    return prop.get("checkbox", False)


def _extract_email(prop: dict) -> str | None:
    """Extract email value."""
    return prop.get("email")


# ── Notion page → grant dict ────────────────────────────────────────────────

# Reverse status map: Notion display → internal key
REVERSE_STATUS = {
    "Raw": "raw",
    "Shortlisted": "triage",
    "Pursue": "pursue",
    "Watch": "watch",
    "Pass": "passed",
    "Rejected": "auto_pass",
    "Draft": "drafting",
    "Submit": "submitted",
    "Won": "won",
    "Hold": "hold",
}


def _page_to_grant(page: dict) -> dict:
    """Convert a Notion page to a grant dict matching the MongoDB schema."""
    props = page.get("properties", {})

    grant: dict[str, Any] = {
        "notion_page_id": page["id"],
        "title": _extract_text(props.get("Grant Name", {})),
        "grant_name": _extract_text(props.get("Grant Name", {})),
        "funder": _extract_text(props.get("Funder", {})),
        "url": _extract_url(props.get("Grant URL", {})),
        "application_url": _extract_url(props.get("Application URL", {})),
        "status": REVERSE_STATUS.get(
            _extract_select(props.get("Status", {})) or "", "raw"
        ),
        "weighted_total": _extract_number(props.get("Score", {})) or 0,
        "themes_detected": _extract_multi_select(props.get("Themes", {})),
        "geography": _extract_text(props.get("Geography", {})),
        "grant_type": _extract_text(props.get("Grant Type", {})),
        "eligibility_details": _extract_text(props.get("Eligibility", {})),
        "rationale": _extract_text(props.get("AI Rationale", {})),
        "url_hash": _extract_text(props.get("URL Hash", {})),
        "content_hash": _extract_text(props.get("Content Hash", {})),
        "max_funding_usd": _extract_number(props.get("Funding USD", {})),
        "amount": _extract_text(props.get("Ticket Size", {})),
        "currency": _extract_text(props.get("Currency", {})),
        "deadline": _extract_date(props.get("Deadline", {})),
        "deadline_urgent": _extract_checkbox(props.get("Urgent", {})),
        "days_to_deadline": _extract_number(props.get("Days Left", {})),
        "recommended_action": _extract_select(props.get("AI Recommendation", {})),
        "priority": _extract_select(props.get("Priority", {})),
        "score_breakdown": _extract_text(props.get("Score Breakdown", {})),
        "strategic_angle": _extract_text(props.get("Strategic Angle", {})),
        "altcarbon_fit": _extract_select(props.get("AltCarbon Fit", {})),
        "contact_email": _extract_email(props.get("Contact Email", {})),
        "source": _extract_select(props.get("Source", {})),
    }

    # Compute scores dict from Score Breakdown text
    breakdown = grant.get("score_breakdown", "")
    if breakdown:
        scores = {}
        for part in breakdown.split("|"):
            part = part.strip()
            if ":" in part:
                dim, val = part.rsplit(":", 1)
                val = val.strip().split("/")[0].strip()
                try:
                    scores[dim.strip().lower().replace(" ", "_")] = float(val)
                except ValueError:
                    pass
        grant["scores"] = scores

    return grant


# ── CRUD Operations ─────────────────────────────────────────────────────────

def _build_properties(grant: dict, status: str | None = None) -> dict[str, Any]:
    """Build Notion properties dict from a grant dict."""
    from backend.integrations.notion_sync import _rt

    score = grant.get("weighted_total", 0) or 0
    status_raw = status or grant.get("status", "raw")
    themes_raw: list[str] = grant.get("themes_detected", []) or []

    props: dict[str, Any] = {
        "Grant Name": {"title": [{"text": {"content": (
            grant.get("grant_name") or grant.get("title") or "Unnamed"
        )[:2000]}}]},
        "Funder": {"rich_text": _rt(grant.get("funder", "") or "")},
        "Score": {"number": round(score, 2)},
        "Priority": {"select": {"name": get_priority_label(score)}},
        "Status": {"select": {"name": STATUS_MAP.get(status_raw, "Raw")}},
        "Themes": {"multi_select": [
            {"name": THEME_DISPLAY.get(t, t)} for t in themes_raw if THEME_DISPLAY.get(t, t)
        ]},
        "Geography": {"rich_text": _rt((grant.get("geography", "") or "")[:2000])},
        "Grant Type": {"rich_text": _rt(grant.get("grant_type", "") or "")},
        "Eligibility": {"rich_text": _rt(
            (grant.get("eligibility_details") or grant.get("eligibility") or "")[:2000]
        )},
        "AI Rationale": {"rich_text": _rt((grant.get("rationale", "") or "")[:2000])},
    }

    # URL Hash + Content Hash (for dedup)
    if grant.get("url_hash"):
        props["URL Hash"] = {"rich_text": _rt(grant["url_hash"])}
    if grant.get("content_hash"):
        props["Content Hash"] = {"rich_text": _rt(grant["content_hash"])}

    # Source
    source = grant.get("source")
    if source:
        props["Source"] = {"select": {"name": source[:100]}}

    # Optional fields
    rec = grant.get("recommended_action")
    if rec:
        props["AI Recommendation"] = {"select": {"name": rec}}

    url = grant.get("url")
    if url:
        props["Grant URL"] = {"url": url}

    app_url = grant.get("application_url")
    if app_url:
        props["Application URL"] = {"url": app_url}

    funding = grant.get("max_funding_usd") or grant.get("max_funding")
    if funding:
        props["Funding USD"] = {"number": funding}

    amount_str = grant.get("amount")
    if amount_str:
        props["Ticket Size"] = {"rich_text": _rt(str(amount_str)[:200])}

    currency = grant.get("currency")
    if currency:
        props["Currency"] = {"rich_text": _rt(currency)}

    deadline = grant.get("deadline")
    if deadline:
        try:
            if hasattr(deadline, "strftime"):
                props["Deadline"] = {"date": {"start": deadline.strftime("%Y-%m-%d")}}
            elif isinstance(deadline, str):
                from backend.agents.analyst import parse_deadline
                parsed = parse_deadline(deadline)
                if parsed:
                    props["Deadline"] = {"date": {"start": parsed.strftime("%Y-%m-%d")}}
                else:
                    stripped = deadline.strip()[:10]
                    if len(stripped) >= 10 and stripped[4] == "-" and stripped[7] == "-":
                        props["Deadline"] = {"date": {"start": stripped}}
        except Exception:
            log.debug("Skipping unparseable deadline: %s", deadline)

    if grant.get("deadline_urgent") is True:
        props["Urgent"] = {"checkbox": True}

    dtd = grant.get("days_to_deadline")
    if dtd is not None:
        props["Days Left"] = {"number": dtd}

    scored_at = grant.get("scored_at")
    if scored_at:
        sa = scored_at.isoformat() if hasattr(scored_at, "isoformat") else str(scored_at)[:10]
        props["Scored At"] = {"date": {"start": sa}}

    # Score Breakdown
    from backend.integrations.notion_config import SCORE_DIMENSION_DISPLAY
    scores = grant.get("scores") or {}
    if scores:
        breakdown_lines = []
        for dim_key, dim_display in SCORE_DIMENSION_DISPLAY.items():
            val = scores.get(dim_key)
            if val is not None:
                breakdown_lines.append(f"{dim_display}: {val:.1f}/10")
        if breakdown_lines:
            props["Score Breakdown"] = {"rich_text": _rt(" | ".join(breakdown_lines))}

    # Strategic Angle from deep analysis
    deep = grant.get("deep_analysis") or {}
    strategic_angle = deep.get("strategic_angle")
    if strategic_angle:
        props["Strategic Angle"] = {"rich_text": _rt(strategic_angle[:2000])}

    # AltCarbon Fit
    past_winners = grant.get("past_winners") or {}
    verdict = past_winners.get("altcarbon_fit_verdict")
    fit_map = {"strong": "Strong", "moderate": "Moderate", "weak": "Weak", "unknown": "Unknown"}
    if verdict and verdict in fit_map:
        props["AltCarbon Fit"] = {"select": {"name": fit_map[verdict]}}

    # Past Winners count
    winners_list = past_winners.get("winners") or []
    if winners_list:
        props["Past Winners"] = {"number": len(winners_list)}

    # Contact Email
    contact = deep.get("contact") or {}
    contact_email = contact.get("email")
    if contact_email:
        props["Contact Email"] = {"email": contact_email}

    return props


async def create_grant_page(grant: dict, status: str = "raw") -> str:
    """Create a new grant page in the Notion Grant Pipeline.

    Returns the Notion page ID on success.
    Raises on failure (caller should handle fallback).
    """
    from backend.integrations.notion_sync import _build_grant_page_body

    client = _get_client()
    props = _build_properties(grant, status=status)

    page = await _rate_limited(
        client.pages.create(
            parent={"type": "data_source_id", "data_source_id": GRANT_PIPELINE_COLLECTION},
            properties=props,
        )
    )
    page_id = page["id"]

    # Append body blocks in batches of 100
    body_blocks = _build_grant_page_body(grant)
    if body_blocks:
        for i in range(0, len(body_blocks), 100):
            await _rate_limited(
                client.blocks.children.append(
                    block_id=page_id,
                    children=body_blocks[i: i + 100],
                )
            )

    log.info("Notion: created grant page %s (status=%s)", page_id, status)
    return page_id


async def update_grant_page(page_id: str, updates: dict, status: str | None = None) -> None:
    """Update an existing grant page in Notion with new data.

    `updates` is a grant dict with changed fields. Only non-None fields are sent.
    """
    from backend.integrations.notion_sync import _build_grant_page_body, _replace_page_children

    client = _get_client()
    props = _build_properties(updates, status=status)

    await _rate_limited(
        client.pages.update(page_id=page_id, properties=props)
    )

    # Rebuild page body if scoring data is present
    if updates.get("weighted_total") or updates.get("deep_analysis"):
        body_blocks = _build_grant_page_body(updates)
        if body_blocks:
            await _replace_page_children(client, page_id, body_blocks)

    log.info("Notion: updated grant page %s", page_id)


async def get_grant_by_page_id(page_id: str) -> dict | None:
    """Fetch a single grant by Notion page ID.

    Returns a grant dict or None if not found.
    """
    try:
        client = _get_client()
        page = await _rate_limited(client.pages.retrieve(page_id=page_id))
        if page.get("archived"):
            return None
        return _page_to_grant(page)
    except Exception:
        log.warning("Failed to fetch grant page %s", page_id, exc_info=True)
        return None


async def find_grant_by_url_hash(url_hash: str) -> str | None:
    """Find a grant page by URL Hash property.

    Returns the Notion page ID if found, else None.
    """
    try:
        client = _get_client()
        resp = await _rate_limited(
            client.data_sources.query(
                database_id=GRANT_PIPELINE_DS,
                filter={
                    "property": "URL Hash",
                    "rich_text": {"equals": url_hash},
                },
                page_size=1,
            )
        )
        if resp["results"]:
            return resp["results"][0]["id"]
    except Exception:
        log.debug("URL Hash lookup failed for %s", url_hash, exc_info=True)
    return None


async def batch_find_url_hashes(url_hashes: list[str]) -> dict[str, str]:
    """Find existing grants by URL Hash, returning {url_hash: page_id}.

    Uses batch queries to minimize API calls (100 per query page).
    """
    known: dict[str, str] = {}
    if not url_hashes:
        return known

    try:
        client = _get_client()
        # Query all pages that have a URL Hash set, paginate through results
        has_more = True
        start_cursor: str | None = None

        while has_more:
            query_args: dict[str, Any] = {
                "data_source_id": GRANT_PIPELINE_COLLECTION,
                "filter": {
                    "property": "URL Hash",
                    "rich_text": {"is_not_empty": True},
                },
                "page_size": 100,
            }
            if start_cursor:
                query_args["start_cursor"] = start_cursor

            resp = await _rate_limited(client.data_sources.query(**query_args))
            for page in resp.get("results", []):
                props = page.get("properties", {})
                uh = _extract_text(props.get("URL Hash", {}))
                if uh:
                    known[uh] = page["id"]

            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

    except Exception:
        log.warning("Batch URL Hash lookup failed", exc_info=True)

    return known


async def query_grants_by_status(status: str) -> list[dict]:
    """Query all grants with a given Notion status.

    `status` is the Notion display name (e.g. "Raw", "Shortlisted", "Pursue").
    """
    grants = []
    try:
        client = _get_client()
        has_more = True
        start_cursor: str | None = None

        while has_more:
            query_args: dict[str, Any] = {
                "data_source_id": GRANT_PIPELINE_COLLECTION,
                "filter": {
                    "property": "Status",
                    "select": {"equals": status},
                },
                "page_size": 100,
            }
            if start_cursor:
                query_args["start_cursor"] = start_cursor

            resp = await _rate_limited(client.data_sources.query(**query_args))
            for page in resp.get("results", []):
                grants.append(_page_to_grant(page))

            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

    except Exception:
        log.warning("Query grants by status '%s' failed", status, exc_info=True)

    return grants


async def query_all_grants() -> list[dict]:
    """Query all grants from the Grant Pipeline DB."""
    grants = []
    try:
        client = _get_client()
        has_more = True
        start_cursor: str | None = None

        while has_more:
            query_args: dict[str, Any] = {
                "data_source_id": GRANT_PIPELINE_COLLECTION,
                "page_size": 100,
            }
            if start_cursor:
                query_args["start_cursor"] = start_cursor

            resp = await _rate_limited(client.data_sources.query(**query_args))
            for page in resp.get("results", []):
                grants.append(_page_to_grant(page))

            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

    except Exception:
        log.warning("Query all grants failed", exc_info=True)

    return grants


async def update_grant_status(page_id: str, new_status: str) -> bool:
    """Update just the status of a grant page.

    `new_status` is the internal status key (e.g. "raw", "triage", "pursue").
    """
    try:
        client = _get_client()
        notion_status = STATUS_MAP.get(new_status, "Shortlisted")
        await _rate_limited(
            client.pages.update(
                page_id=page_id,
                properties={"Status": {"select": {"name": notion_status}}},
            )
        )
        log.info("Notion: updated status for %s → %s", page_id, notion_status)
        return True
    except Exception:
        log.warning("Failed to update grant status for %s", page_id, exc_info=True)
        return False
