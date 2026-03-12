"""Sync engine state to Notion Mission Control databases.

All functions are fire-and-forget safe — errors are logged but never
propagate to the caller, so agent pipelines are never blocked by Notion.
"""
from __future__ import annotations

import asyncio
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
    CHECKLIST_STATUS_EMOJI,
    DRAFT_SECTIONS_DS,
    ERROR_LOGS_DS,
    GRANT_PIPELINE_DS,
    SCORE_DIMENSION_DISPLAY,
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


# ── Notion block builder helpers ─────────────────────────────────────────────

def _rt(
    text: str,
    bold: bool = False,
    italic: bool = False,
    color: str = "default",
    link: str | None = None,
) -> list[dict[str, Any]]:
    """Build a rich_text array, auto-chunking at 1900 chars."""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    chunks: list[dict[str, Any]] = []
    for i in range(0, len(text), 1900):
        chunk_text = text[i : i + 1900]
        text_obj: dict[str, Any] = {"content": chunk_text}
        if link:
            text_obj["link"] = {"url": link}
        item: dict[str, Any] = {"type": "text", "text": text_obj}
        annotations: dict[str, Any] = {}
        if bold:
            annotations["bold"] = True
        if italic:
            annotations["italic"] = True
        if color != "default":
            annotations["color"] = color
        if annotations:
            item["annotations"] = annotations
        chunks.append(item)
    return chunks


def _heading2(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rt(text)}}


def _heading3(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rt(text)}}


def _paragraph(text: str, color: str = "default", bold: bool = False, italic: bool = False) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rt(text, bold=bold, italic=italic), "color": color},
    }


def _bullet(text: str, color: str = "default") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rt(text), "color": color},
    }


def _callout(text: str, emoji: str = "\U0001f4cb", color: str = "gray_background") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": _rt(text),
            "icon": {"type": "emoji", "emoji": emoji},
            "color": color,
        },
    }


def _divider() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _toggle(text: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": _rt(text, bold=True),
            "children": children[:100],
        },
    }


def _bookmark(url: str) -> dict[str, Any]:
    return {"object": "block", "type": "bookmark", "bookmark": {"url": url}}


# ── Rich page body builder ───────────────────────────────────────────────────

def _build_grant_page_body(grant: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Notion page content blocks mirroring GrantDetailSheet.tsx."""
    blocks: list[dict[str, Any]] = []
    score = grant.get("weighted_total", 0) or 0
    priority = get_priority_label(score)
    status_raw = grant.get("status", "triage")
    status_display = STATUS_MAP.get(status_raw, "Triage")

    # ── 1. Header callout ────────────────────────────────────────────────
    emoji = "\u2b50" if priority == "High" else "\U0001f7e1" if priority == "Medium" else "\u26aa"
    header_parts = [f"Score: {score:.1f}/10  |  Priority: {priority}  |  Status: {status_display}"]
    rec = grant.get("recommended_action")
    if rec:
        header_parts.append(f"AI Recommendation: {rec}")
    blocks.append(_callout("  |  ".join(header_parts), emoji=emoji, color="blue_background"))

    # ── 2. Quick Facts ───────────────────────────────────────────────────
    blocks.append(_heading2("Quick Facts"))
    geography = grant.get("geography")
    if geography:
        blocks.append(_bullet(f"Geography: {geography}"))
    funding = grant.get("max_funding_usd") or grant.get("max_funding")
    if funding:
        blocks.append(_bullet(f"Funding: ${funding:,.0f}"))
    elif grant.get("amount"):
        blocks.append(_bullet(f"Funding: {grant['amount']}"))
    deadline = grant.get("deadline")
    days_left = grant.get("days_to_deadline")
    if deadline:
        dl_text = f"Deadline: {deadline}"
        if days_left is not None:
            dl_text += f" ({days_left} days left)"
            if grant.get("deadline_urgent"):
                dl_text += " \u26a0\ufe0f URGENT"
        blocks.append(_bullet(dl_text))
    grant_type = grant.get("grant_type")
    if grant_type:
        blocks.append(_bullet(f"Grant Type: {grant_type}"))
    funder = grant.get("funder")
    if funder:
        blocks.append(_bullet(f"Funder: {funder}"))
    blocks.append(_divider())

    # ── 3. Links ─────────────────────────────────────────────────────────
    url = grant.get("url")
    app_url = grant.get("application_url")
    if url or app_url:
        blocks.append(_heading2("Links"))
        if url:
            blocks.append(_bookmark(url))
        if app_url and app_url != url:
            blocks.append(_paragraph(f"Apply: {app_url}"))
        blocks.append(_divider())

    # ── 4. Score Breakdown ───────────────────────────────────────────────
    scores = grant.get("scores") or {}
    if scores:
        blocks.append(_heading2("Score Breakdown"))
        for dim_key, dim_display in SCORE_DIMENSION_DISPLAY.items():
            val = scores.get(dim_key)
            if val is not None:
                bar = "\u2588" * int(val) + "\u2591" * (10 - int(val))
                blocks.append(_bullet(f"{dim_display}: {val:.1f}/10  {bar}"))
        blocks.append(_paragraph(f"Weighted Total: {score:.1f}/10", bold=True))
        blocks.append(_divider())

    # ── 5. Eligibility ───────────────────────────────────────────────────
    eligibility = grant.get("eligibility")
    if eligibility:
        blocks.append(_heading2("Eligibility"))
        blocks.append(_paragraph(eligibility))
        blocks.append(_divider())

    # ── 6. AI Rationale ──────────────────────────────────────────────────
    rationale = grant.get("rationale")
    reasoning = grant.get("reasoning")
    if rationale or reasoning:
        blocks.append(_heading2("AI Analysis"))
        if rationale:
            blocks.append(_paragraph(rationale))
        if reasoning:
            blocks.append(_paragraph(reasoning, italic=True))
        blocks.append(_divider())

    # ── 7. Evidence (toggle) ─────────────────────────────────────────────
    evidence_found = grant.get("evidence_found") or []
    evidence_gaps = grant.get("evidence_gaps") or []
    if evidence_found or evidence_gaps:
        evidence_children: list[dict[str, Any]] = []
        if evidence_found:
            evidence_children.append(_heading3("Evidence Found"))
            for item in evidence_found:
                evidence_children.append(_bullet(f"\u2705 {item}", color="green_background"))
        if evidence_gaps:
            evidence_children.append(_heading3("Evidence Gaps"))
            for item in evidence_gaps:
                evidence_children.append(_bullet(f"\u26a0\ufe0f {item}", color="orange_background"))
        blocks.append(_toggle(f"Evidence ({len(evidence_found)} found, {len(evidence_gaps)} gaps)", evidence_children))

    # ── 8. Red Flags ─────────────────────────────────────────────────────
    red_flags = grant.get("red_flags") or []
    if red_flags:
        flag_children = [_bullet(f"\u274c {flag}") for flag in red_flags]
        blocks.append(_callout(
            f"{len(red_flags)} Red Flag{'s' if len(red_flags) != 1 else ''}",
            emoji="\U0001f6a9",
            color="red_background",
        ))
        for flag in red_flags:
            blocks.append(_bullet(f"\u274c {flag}"))

    # ── 9. Deep Analysis sections ────────────────────────────────────────
    deep = grant.get("deep_analysis") or {}

    # 9a. Eligibility Checklist
    checklist = deep.get("eligibility_checklist") or []
    if checklist:
        cl_children: list[dict[str, Any]] = []
        for item in checklist:
            status_emoji = CHECKLIST_STATUS_EMOJI.get(item.get("altcarbon_status", ""), "\u2753")
            criterion = item.get("criterion", "")
            note = item.get("note", "")
            line = f"{status_emoji} {criterion}"
            if note:
                line += f" \u2014 {note}"
            cl_children.append(_bullet(line))
        blocks.append(_toggle("Eligibility Checklist (Deep Analysis)", cl_children))

    # 9b. Key Dates
    key_dates = deep.get("key_dates") or {}
    if key_dates:
        date_children: list[dict[str, Any]] = []
        for k, v in key_dates.items():
            if v:
                label = k.replace("_", " ").title()
                date_children.append(_bullet(f"{label}: {v}"))
        if date_children:
            blocks.append(_toggle("Key Dates", date_children))

    # 9c. Requirements
    reqs = deep.get("requirements") or {}
    if reqs:
        req_children: list[dict[str, Any]] = []
        fmt = reqs.get("submission_format")
        if fmt:
            req_children.append(_bullet(f"Submission Format: {fmt}"))
        limits = reqs.get("word_page_limits")
        if limits:
            req_children.append(_bullet(f"Word/Page Limits: {limits}"))
        cofund = reqs.get("co_funding_required")
        if cofund:
            req_children.append(_bullet(f"Co-funding Required: {cofund}"))
        docs = reqs.get("documents_needed") or []
        if docs:
            req_children.append(_heading3("Documents Needed"))
            for doc in docs:
                req_children.append(_bullet(doc))
        if req_children:
            blocks.append(_toggle("Requirements", req_children))

    # 9d. Evaluation Criteria
    eval_criteria = deep.get("evaluation_criteria") or []
    if eval_criteria:
        ec_children: list[dict[str, Any]] = []
        for ec in eval_criteria:
            criterion = ec.get("criterion", "")
            weight = ec.get("weight", "")
            what = ec.get("what_they_look_for", "")
            line = criterion
            if weight:
                line += f" ({weight})"
            if what:
                line += f": {what}"
            ec_children.append(_bullet(line))
        blocks.append(_toggle("Evaluation Criteria", ec_children))

    # 9e. Strategic Advice
    strategic_angle = deep.get("strategic_angle")
    tips = deep.get("application_tips") or []
    if strategic_angle or tips:
        strat_children: list[dict[str, Any]] = []
        if strategic_angle:
            strat_children.append(_paragraph(strategic_angle))
        if tips:
            strat_children.append(_heading3("Application Tips"))
            for tip in tips:
                strat_children.append(_bullet(f"\u2192 {tip}"))
        blocks.append(_toggle("Strategic Advice", strat_children))

    # 9f. Contact Information
    contact = deep.get("contact") or {}
    if any(contact.values()):
        contact_children: list[dict[str, Any]] = []
        if contact.get("name"):
            contact_children.append(_bullet(f"Name: {contact['name']}"))
        if contact.get("email"):
            contact_children.append(_bullet(f"Email: {contact['email']}"))
        emails = contact.get("emails_all") or []
        if emails:
            contact_children.append(_bullet(f"All Emails: {', '.join(emails)}"))
        if contact.get("phone"):
            contact_children.append(_bullet(f"Phone: {contact['phone']}"))
        if contact.get("office"):
            contact_children.append(_bullet(f"Office: {contact['office']}"))
        if contact_children:
            blocks.append(_toggle("Contact Information", contact_children))

    # 9g. Resources
    resources = deep.get("resources") or {}
    if any(resources.values()):
        res_children: list[dict[str, Any]] = []
        for key in ("brochure_urls", "info_session_urls", "template_urls"):
            urls = resources.get(key) or []
            if urls:
                label = key.replace("_", " ").title()
                for u in urls:
                    res_children.append(_bullet(f"{label}: {u}"))
        faq = resources.get("faq_url")
        if faq:
            res_children.append(_bullet(f"FAQ: {faq}"))
        guidelines = resources.get("guidelines_url")
        if guidelines:
            res_children.append(_bullet(f"Guidelines: {guidelines}"))
        if res_children:
            blocks.append(_toggle("Resources & Links", res_children))

    # ── 10. Past Winners ─────────────────────────────────────────────────
    past_winners = grant.get("past_winners") or {}
    if past_winners:
        pw_children: list[dict[str, Any]] = []
        pattern = past_winners.get("funder_pattern")
        if pattern:
            pw_children.append(_paragraph(pattern))
        strat_note = past_winners.get("strategic_note")
        if strat_note:
            pw_children.append(_callout(strat_note, emoji="\U0001f4a1", color="yellow_background"))
        verdict = past_winners.get("altcarbon_fit_verdict")
        if verdict:
            pw_children.append(_paragraph(f"AltCarbon Fit: {verdict}", bold=True))
        winners = past_winners.get("winners") or []
        for w in winners[:10]:
            name = w.get("name", "")
            year = w.get("year", "")
            country = w.get("country", "")
            sim = w.get("altcarbon_similarity", "")
            brief = w.get("project_brief", "")
            meta = ", ".join(str(x) for x in [year, country] if x)
            line = f"{name}"
            if meta:
                line += f" ({meta})"
            if sim:
                line += f" \u2014 {sim} similarity"
            if brief:
                line += f" \u2014 {brief}"
            pw_children.append(_bullet(line))
        if pw_children:
            blocks.append(_toggle("Past Winners Analysis", pw_children))

    # ── 11. Themes ───────────────────────────────────────────────────────
    themes_raw: list[str] = grant.get("themes_detected") or []
    if themes_raw:
        blocks.append(_heading3("Themes Detected"))
        for t in themes_raw:
            blocks.append(_bullet(THEME_DISPLAY.get(t, t.replace("_", " ").title())))

    # ── 12. Human Override ───────────────────────────────────────────────
    if grant.get("human_override"):
        override_text = "AI recommendation was overridden by a human reviewer."
        reason = grant.get("override_reason")
        if reason:
            override_text += f"\nReason: {reason}"
        at = grant.get("override_at")
        if at:
            override_text += f"\nOverridden at: {at}"
        blocks.append(_callout(override_text, emoji="\u270b", color="yellow_background"))

    # ── 13. Metadata footer ──────────────────────────────────────────────
    blocks.append(_divider())
    mongo_id = str(grant.get("_id", ""))
    scored_at = grant.get("scored_at", "")
    if hasattr(scored_at, "isoformat"):
        scored_at = scored_at.isoformat()
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks.append(_paragraph(
        f"Synced from AltCarbon Grants Engine  |  MongoDB: {mongo_id}  |  Scored: {scored_at}  |  Last synced: {synced_at}",
        color="gray",
    ))

    return blocks


# ── Replace page children (for updates) ──────────────────────────────────────

async def _replace_page_children(client: AsyncClient, page_id: str, new_children: list[dict[str, Any]]) -> None:
    """Delete all existing child blocks and append new ones."""
    try:
        existing = await client.blocks.children.list(block_id=page_id, page_size=100)
        for block in existing.get("results", []):
            try:
                await client.blocks.delete(block_id=block["id"])
            except Exception:
                pass
        # Handle pagination for existing children
        while existing.get("has_more"):
            existing = await client.blocks.children.list(
                block_id=page_id,
                start_cursor=existing["next_cursor"],
                page_size=100,
            )
            for block in existing.get("results", []):
                try:
                    await client.blocks.delete(block_id=block["id"])
                except Exception:
                    pass

        # Append new children in batches of 100
        for i in range(0, len(new_children), 100):
            batch = new_children[i : i + 100]
            await client.blocks.children.append(block_id=page_id, children=batch)
    except Exception:
        log.debug("Failed to replace page children for %s", page_id, exc_info=True)


# ── Grant Pipeline sync ──────────────────────────────────────────────────────

async def sync_scored_grant(grant: dict[str, Any]) -> str | None:
    """Upsert a scored grant into the Notion Grant Pipeline database.

    Creates a rich page body mirroring the dashboard's GrantDetailSheet,
    including score breakdown, deep analysis, evidence, red flags, and more.

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

        # Optional fields (existing)
        # Note: "AI Recommendation" is a rollup in Notion (read-only), so we skip it.

        url = grant.get("url")
        if url:
            props["Grant URL"] = {"url": url}

        funding = grant.get("max_funding_usd") or grant.get("max_funding")
        if funding:
            props["Funding USD"] = {"number": funding}

        deadline = grant.get("deadline")
        if deadline:
            if hasattr(deadline, "strftime"):
                dl = deadline.strftime("%Y-%m-%d")
                props["Deadline"] = {"date": {"start": dl}}
            elif isinstance(deadline, str):
                # Only use if it looks like an ISO date (YYYY-MM-DD...)
                stripped = deadline.strip()[:10]
                if len(stripped) >= 10 and stripped[4] == "-" and stripped[7] == "-":
                    props["Deadline"] = {"date": {"start": stripped}}

        scored_at = grant.get("scored_at")
        if scored_at:
            sa = scored_at.isoformat() if hasattr(scored_at, "isoformat") else str(scored_at)[:10]
            props["Scored At"] = {"date": {"start": sa}}

        # ── New properties (full data — names match actual Notion DB schema) ──
        app_url = grant.get("application_url")
        if app_url:
            props["Application URL"] = {"url": app_url}

        days_left = grant.get("days_to_deadline")
        if days_left is not None:
            props["Days Left"] = {"number": days_left}

        props["Urgent"] = {"checkbox": bool(grant.get("deadline_urgent", False))}

        # Score Breakdown — formatted text of all 6 dimensions
        scores = grant.get("scores") or {}
        if scores:
            breakdown_lines = []
            for dim_key, dim_display in SCORE_DIMENSION_DISPLAY.items():
                val = scores.get(dim_key)
                if val is not None:
                    breakdown_lines.append(f"{dim_display}: {val:.1f}/10")
            if breakdown_lines:
                props["Score Breakdown"] = {"rich_text": [{"text": {"content": " | ".join(breakdown_lines)}}]}

        # Strategic Angle from deep analysis
        deep = grant.get("deep_analysis") or {}
        strategic_angle = deep.get("strategic_angle")
        if strategic_angle:
            props["Strategic Angle"] = {"rich_text": [{"text": {"content": strategic_angle[:2000]}}]}

        # AltCarbon Fit from past winners analysis
        past_winners = grant.get("past_winners") or {}
        verdict = past_winners.get("altcarbon_fit_verdict")
        fit_map = {"strong": "Strong", "moderate": "Moderate", "weak": "Weak", "unknown": "Unknown"}
        if verdict and verdict in fit_map:
            props["AltCarbon Fit"] = {"select": {"name": fit_map[verdict]}}

        # Past Winners count
        winners_list = past_winners.get("winners") or []
        if winners_list:
            props["Past Winners"] = {"number": len(winners_list)}

        # Contact Email from deep analysis
        contact = deep.get("contact") or {}
        contact_email = contact.get("email")
        if contact_email:
            props["Contact Email"] = {"email": contact_email}

        # Currency
        currency = grant.get("currency")
        if currency:
            props["Currency"] = {"rich_text": [{"text": {"content": currency}}]}

        # ── Build rich page body ─────────────────────────────────────────
        body_blocks = _build_grant_page_body(grant)

        # Upsert: check if page exists
        existing_id = await _find_page_by_mongo_id(GRANT_PIPELINE_DS, mongo_id)

        if existing_id:
            await client.pages.update(page_id=existing_id, properties=props)
            # Replace page body content
            if body_blocks:
                await _replace_page_children(client, existing_id, body_blocks)
            log.info("Notion: updated grant %s (%s)", mongo_id, existing_id)
            await _store_notion_url(mongo_id, existing_id)
            return existing_id
        else:
            page = await client.pages.create(
                parent={"database_id": GRANT_PIPELINE_DS},
                properties=props,
                children=body_blocks[:100] if body_blocks else None,
            )
            page_id = page["id"]
            # Append remaining blocks if > 100
            if body_blocks and len(body_blocks) > 100:
                for i in range(100, len(body_blocks), 100):
                    await client.blocks.children.append(
                        block_id=page_id,
                        children=body_blocks[i : i + 100],
                    )
            log.info("Notion: created grant %s (%s)", mongo_id, page_id)
            await _store_notion_url(mongo_id, page_id)
            return page_id

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


# ── Database schema setup ────────────────────────────────────────────────────

async def ensure_grant_pipeline_schema() -> bool:
    """Ensure the Grant Pipeline database has all required properties.

    Idempotent — safe to call multiple times. Notion ignores properties
    that already exist with the correct type.
    """
    try:
        client = _get_client()
        # These match actual Notion DB property names (most already exist)
        new_props: dict[str, Any] = {
            "Application URL": {"url": {}},
            "Days Left": {"number": {"format": "number"}},
            "Urgent": {"checkbox": {}},
            "Score Breakdown": {"rich_text": {}},
            "Strategic Angle": {"rich_text": {}},
            "AltCarbon Fit": {"select": {"options": [
                {"name": "Strong", "color": "green"},
                {"name": "Moderate", "color": "yellow"},
                {"name": "Weak", "color": "red"},
                {"name": "Unknown", "color": "gray"},
            ]}},
            "Past Winners": {"number": {"format": "number"}},
            "Contact Email": {"email": {}},
            "Currency": {"rich_text": {}},
        }

        await client.databases.update(
            database_id=GRANT_PIPELINE_DS,
            properties=new_props,
        )
        log.info("Notion: Grant Pipeline schema updated with %d new properties", len(new_props))
        return True
    except Exception:
        log.warning("Failed to update Grant Pipeline schema", exc_info=True)
        return False


# ── Notion views setup ───────────────────────────────────────────────────────

async def setup_grant_pipeline_views() -> dict[str, Any]:
    """Create Kanban (by Status) and Table views for the Grant Pipeline database.

    Uses the Notion MCP `notion-create-view` tool. Falls back gracefully
    if MCP is unavailable — views can be created manually in Notion UI.

    Existing views (Default board by AltCarbon Fit, Gallery timeline) are
    preserved; these are additive.
    """
    results: dict[str, Any] = {}
    try:
        from backend.integrations.notion_mcp import notion_mcp

        # Kanban view grouped by Status (Triage → Pursue → Drafting → Submitted)
        try:
            kanban = await notion_mcp._call_tool("notion-create-view", {
                "database_id": GRANT_PIPELINE_DS,
                "title": "Status Board",
                "type": "board",
                "board_cover": {"type": "none"},
                "board_groups": {"type": "select", "property": "Status"},
            })
            results["kanban"] = kanban
            log.info("Notion: created Status Board view")
        except Exception:
            log.warning("Failed to create Status Board view via MCP", exc_info=True)

        # Table view with all key columns
        try:
            table = await notion_mcp._call_tool("notion-create-view", {
                "database_id": GRANT_PIPELINE_DS,
                "title": "All Grants",
                "type": "table",
            })
            results["table"] = table
            log.info("Notion: created All Grants table view")
        except Exception:
            log.warning("Failed to create Table view via MCP", exc_info=True)

    except ImportError:
        log.warning("Notion MCP not available — create views manually in Notion UI")
    except Exception:
        log.warning("Failed to setup Notion views", exc_info=True)

    return results


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
            # Replace body content on update
            if children:
                await _replace_page_children(client, existing_id, children)
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


# ── Push complete draft to Notion ─────────────────────────────────────────────

async def push_complete_draft_to_notion(
    grant_id: str,
    grant_name: str,
    sections: dict[str, dict[str, Any]],
    version: int = 1,
    evidence_gaps: list[str] | None = None,
    funder: str = "",
    deadline: str = "",
) -> str | None:
    """Append the complete draft to the grant's own page in the Pipeline DB.

    Finds the grant page in Grant Pipeline, appends a "Draft" section with
    all draft sections, word counts, and evidence gaps. Updates status to
    "Drafting".

    Returns the Notion page ID on success, None on failure.
    """
    try:
        client = _get_client()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # ── Find the grant's page in the Pipeline DB ────────────────────
        page_id = await _find_page_by_mongo_id(GRANT_PIPELINE_DS, grant_id)
        if not page_id:
            log.warning("Notion: grant %s not found in pipeline for draft push", grant_id)
            return None

        # ── Build draft blocks to append ────────────────────────────────
        total_words = sum(
            int(sec.get("word_count") or len(str(sec.get("content", "")).split()))
            for sec in sections.values()
        )

        blocks: list[dict[str, Any]] = []

        blocks.append(_divider())
        blocks.append(_callout(
            f"\U0001f4dd Draft v{version}  |  {len(sections)} sections  |  {total_words} words  |  {now}",
            emoji="\U0001f4dd",
            color="blue_background",
        ))

        # Each section
        for section_name, sec_data in sections.items():
            content = str(sec_data.get("content", "") or "")
            word_count = int(sec_data.get("word_count") or len(content.split()))
            word_limit = int(sec_data.get("word_limit") or 500)
            within = bool(sec_data.get("within_limit", word_count <= word_limit))
            status_mark = "\u2705" if within else f"\u26a0\ufe0f OVER ({word_count}/{word_limit})"

            blocks.append(_heading2(section_name))
            blocks.append(_paragraph(
                f"{word_count} words / {word_limit} limit {status_mark}",
                italic=True, color="gray",
            ))

            # Content paragraphs (auto-chunked for Notion 2000-char limit)
            if content:
                for chunk in [content[i:i+1900] for i in range(0, len(content), 1900)]:
                    blocks.append(_paragraph(chunk))

            blocks.append(_divider())

        # Evidence gaps section
        if evidence_gaps:
            blocks.append(_callout(
                f"{len(evidence_gaps)} Evidence Gap{'s' if len(evidence_gaps) != 1 else ''} — Fill Before Submission",
                emoji="\u26a0\ufe0f",
                color="orange_background",
            ))
            for gap in evidence_gaps:
                blocks.append(_bullet(gap))
            blocks.append(_divider())

        # Footer
        blocks.append(_paragraph(
            f"Pushed from Grants Engine  |  {now}",
            color="gray",
        ))

        # ── Append blocks to the grant page ─────────────────────────────
        for i in range(0, len(blocks), 100):
            await client.blocks.children.append(
                block_id=page_id,
                children=blocks[i:i+100],
            )

        # ── Update status to Drafting ───────────────────────────────────
        try:
            await client.pages.update(
                page_id=page_id,
                properties={"Status": {"select": {"name": "Drafting"}}},
            )
        except Exception:
            log.debug("Failed to update grant status for %s", grant_id, exc_info=True)

        log.info("Notion: pushed draft v%d to grant page %s (%s)", version, grant_name[:40], page_id)
        return page_id

    except Exception:
        log.warning("Notion push_complete_draft failed", exc_info=True)
        return None


# ── Bulk sync (for initial backfill) ─────────────────────────────────────────

async def backfill_grants(grants: list[dict[str, Any]]) -> int:
    """Sync a list of scored grants to Notion with rate limiting.

    Returns count of successful syncs.
    """
    count = 0
    for i, grant in enumerate(grants):
        result = await sync_scored_grant(grant)
        if result:
            count += 1
        # Rate limit: ~3 grants per second to avoid Notion 429s
        if (i + 1) % 3 == 0:
            await asyncio.sleep(1.0)
    log.info("Notion backfill: synced %d / %d grants", count, len(grants))
    return count


# ── Reverse sync: Notion → MongoDB ───────────────────────────────────────────

# Notion select value → MongoDB status
REVERSE_STATUS_MAP = {
    "Triage": "triage",
    "Pursue": "pursuing",
    "Watch": "watch",
    "Pass": "passed",
    "Auto Pass": "auto_pass",
    "Drafting": "drafting",
    "Submitted": "submitted",
    "Won": "won",
}

REVERSE_PRIORITY_MAP = {
    "High": "high",
    "Medium": "medium",
    "Low": "low",
}


def _extract_text(prop: dict) -> str:
    """Extract plain text from a Notion rich_text or title property."""
    arr = prop.get("rich_text") or prop.get("title") or []
    return "".join(seg.get("plain_text", "") for seg in arr).strip()


def _extract_select(prop: dict) -> str | None:
    """Extract name from a Notion select property."""
    sel = prop.get("select")
    return sel["name"] if sel else None


async def reverse_sync_from_notion() -> dict[str, int]:
    """Read all grants from the Notion Pipeline DB and update MongoDB statuses.

    Syncs: Status, Priority (human overrides from Notion → MongoDB).
    Returns dict with counts: {checked, updated, errors}.
    """
    from backend.db.mongo import grants_scored

    client = _get_client()
    collection = grants_scored()
    checked = 0
    updated = 0
    errors = 0
    has_more = True
    start_cursor: str | None = None

    while has_more:
        try:
            query_args: dict[str, Any] = {
                "database_id": GRANT_PIPELINE_DS,
                "page_size": 100,
            }
            if start_cursor:
                query_args["start_cursor"] = start_cursor

            resp = await client.databases.query(**query_args)
            pages = resp.get("results", [])
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

            for page in pages:
                checked += 1
                try:
                    props = page.get("properties", {})

                    # Extract MongoDB ID
                    mongo_id = _extract_text(props.get("MongoDB ID", {}))
                    if not mongo_id:
                        continue

                    # Extract current Notion values
                    notion_status = _extract_select(props.get("Status", {}))
                    notion_priority = _extract_select(props.get("Priority", {}))

                    # Build MongoDB update
                    update_fields: dict[str, Any] = {}

                    if notion_status and notion_status in REVERSE_STATUS_MAP:
                        update_fields["status"] = REVERSE_STATUS_MAP[notion_status]

                    if notion_priority and notion_priority in REVERSE_PRIORITY_MAP:
                        update_fields["human_priority"] = REVERSE_PRIORITY_MAP[notion_priority]

                    if not update_fields:
                        continue

                    # Only update if values actually differ
                    from bson import ObjectId

                    try:
                        doc_filter = {"_id": ObjectId(mongo_id)}
                    except Exception:
                        doc_filter = {"_id": mongo_id}

                    existing = await collection.find_one(doc_filter, {"status": 1, "human_priority": 1})
                    if not existing:
                        continue

                    changes: dict[str, Any] = {}
                    if "status" in update_fields and existing.get("status") != update_fields["status"]:
                        changes["status"] = update_fields["status"]
                    if "human_priority" in update_fields and existing.get("human_priority") != update_fields.get("human_priority"):
                        changes["human_priority"] = update_fields["human_priority"]

                    if changes:
                        changes["notion_synced_at"] = datetime.now(timezone.utc)
                        await collection.update_one(doc_filter, {"$set": changes})
                        updated += 1
                        log.debug(
                            "Reverse sync: %s → %s",
                            mongo_id,
                            changes,
                        )

                except Exception:
                    errors += 1
                    log.debug("Reverse sync error for page %s", page.get("id"), exc_info=True)

            # Rate limit between pages
            if has_more:
                await asyncio.sleep(0.5)

        except Exception:
            log.error("Reverse sync query failed", exc_info=True)
            errors += 1
            break

    log.info("Reverse sync complete: checked=%d updated=%d errors=%d", checked, updated, errors)
    return {"checked": checked, "updated": updated, "errors": errors}
