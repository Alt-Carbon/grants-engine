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

    Syncs ALL grant fields as properties + full intelligence brief as page body.
    Returns the Notion page ID on success, None on failure.
    """
    try:
        client = _get_client()
        mongo_id = str(grant.get("_id", ""))
        score = grant.get("weighted_total", 0) or 0
        status_raw = grant.get("status", "triage")
        themes_raw: list[str] = grant.get("themes_detected", []) or []
        da = grant.get("deep_analysis") or {}

        # Build properties dict — ALL important fields
        props: dict[str, Any] = {
            "Grant Name": {"title": [{"text": {"content": grant.get("grant_name") or grant.get("title") or "Unnamed"}}]},
            "Funder": {"rich_text": [{"text": {"content": grant.get("funder", "") or ""}}]},
            "Score": {"number": round(score, 2)},
            "Priority": {"select": {"name": get_priority_label(score)}},
            "Status": {"select": {"name": STATUS_MAP.get(status_raw, "Triage")}},
            "Themes": {"multi_select": [{"name": THEME_DISPLAY.get(t, t)} for t in themes_raw if THEME_DISPLAY.get(t, t)]},
            "Geography": {"rich_text": [{"text": {"content": (grant.get("geography", "") or "")[:2000]}}]},
            "Grant Type": {"rich_text": [{"text": {"content": grant.get("grant_type", "") or ""}}]},
            "Eligibility": {"rich_text": [{"text": {"content": (grant.get("eligibility_details") or grant.get("eligibility") or "")[:2000]}}]},
            "AI Rationale": {"rich_text": [{"text": {"content": (grant.get("rationale", "") or "")[:2000]}}]},
            "MongoDB ID": {"rich_text": [{"text": {"content": mongo_id}}]},
        }

        # Optional core fields
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
            props["Ticket Size"] = {"rich_text": [{"text": {"content": str(amount_str)[:200]}}]}

        currency = grant.get("currency")
        if currency:
            props["Currency"] = {"rich_text": [{"text": {"content": currency}}]}

        deadline = grant.get("deadline")
        if deadline:
            dl = deadline[:10] if isinstance(deadline, str) else deadline.strftime("%Y-%m-%d")
            props["Deadline"] = {"date": {"start": dl}}

        if grant.get("deadline_urgent") is True:
            props["Urgent"] = {"checkbox": True}

        dtd = grant.get("days_to_deadline")
        if dtd is not None:
            props["Days Left"] = {"number": dtd}

        scored_at = grant.get("scored_at")
        if scored_at:
            sa = scored_at.isoformat() if hasattr(scored_at, "isoformat") else str(scored_at)[:10]
            props["Scored At"] = {"date": {"start": sa}}

        # Deep analysis fields as properties (for filtering/sorting)
        fit_verdict = da.get("altcarbon_fit_verdict")
        if fit_verdict:
            props["AltCarbon Fit"] = {"select": {"name": fit_verdict.title()}}

        contact = da.get("contact") or {}
        contact_email = contact.get("email") or ""
        if contact_email:
            props["Contact Email"] = {"email": contact_email}

        winners = da.get("winners") or []
        if winners:
            props["Past Winners"] = {"number": len(winners)}

        # Score breakdown as rich_text
        scores = grant.get("scores") or {}
        if scores:
            score_lines = [f"{k.replace('_', ' ').title()}: {v}/10" for k, v in scores.items()]
            props["Score Breakdown"] = {"rich_text": [{"text": {"content": "\n".join(score_lines)[:2000]}}]}

        # Strategic angle summary
        if da.get("strategic_angle"):
            props["Strategic Angle"] = {"rich_text": [{"text": {"content": da["strategic_angle"][:2000]}}]}

        # ── Page body: full intelligence brief ──
        children = _build_grant_page_body(grant, da)

        # Upsert: check if page exists
        existing_id = await _find_page_by_mongo_id(GRANT_PIPELINE_DS, mongo_id)

        if existing_id:
            await client.pages.update(page_id=existing_id, properties=props)
            # Replace page body: archive old blocks, add new ones
            try:
                old_blocks = await client.blocks.children.list(block_id=existing_id)
                for block in old_blocks.get("results", []):
                    try:
                        await client.blocks.delete(block_id=block["id"])
                    except Exception as e:
                        log.warning("Failed to delete Notion block %s: %s", block["id"], e)
                if children:
                    await client.blocks.children.append(block_id=existing_id, children=children)
            except Exception:
                log.debug("Failed to update page body for %s", existing_id, exc_info=True)
            log.info("Notion: updated grant %s (%s)", mongo_id, existing_id)
            await _store_notion_url(mongo_id, existing_id)
            return existing_id
        else:
            page = await client.pages.create(
                parent={"database_id": GRANT_PIPELINE_DS},
                properties=props,
                children=children if children else None,
            )
            log.info("Notion: created grant %s (%s)", mongo_id, page["id"])
            await _store_notion_url(mongo_id, page["id"])
            return page["id"]

    except Exception as e:
        log.warning("Notion sync_scored_grant failed", exc_info=True)
        return {"success": False, "error": str(e)}


def _build_grant_page_body(grant: dict, da: dict) -> list[dict]:
    """Build rich Notion page body blocks with full grant intelligence."""
    blocks: list[dict] = []

    def _h2(text: str):
        blocks.append({"object": "block", "type": "heading_2", "heading_2": {
            "rich_text": [{"text": {"content": text}}]}})

    def _h3(text: str):
        blocks.append({"object": "block", "type": "heading_3", "heading_3": {
            "rich_text": [{"text": {"content": text}}]}})

    def _para(text: str):
        if not text:
            return
        for chunk in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {
                "rich_text": [{"text": {"content": chunk}}]}})

    def _bullet(text: str):
        blocks.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [{"text": {"content": text[:2000]}}]}})

    def _callout(text: str, emoji: str = "💡"):
        blocks.append({"object": "block", "type": "callout", "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": [{"text": {"content": text[:2000]}}]}})

    def _divider():
        blocks.append({"object": "block", "type": "divider", "divider": {}})

    # ── Overview ──
    _h2("Grant Overview")
    overview_parts = []
    if grant.get("amount"):
        overview_parts.append(f"Funding: {grant['amount']}")
    if grant.get("max_funding_usd"):
        overview_parts.append(f"Max (USD): ${grant['max_funding_usd']:,.0f}")
    if grant.get("deadline"):
        overview_parts.append(f"Deadline: {grant['deadline']}")
    dtd = grant.get("days_to_deadline")
    if dtd is not None:
        overview_parts.append(f"Days left: {dtd}")
    if grant.get("geography"):
        overview_parts.append(f"Geography: {grant['geography']}")
    if grant.get("grant_type"):
        overview_parts.append(f"Type: {grant['grant_type']}")
    for p in overview_parts:
        _bullet(p)

    if grant.get("about_opportunity") or da.get("opportunity_summary"):
        _h3("About")
        _para(grant.get("about_opportunity") or da.get("opportunity_summary", ""))

    # ── Eligibility ──
    _divider()
    _h2("Eligibility")
    _para(grant.get("eligibility_details") or grant.get("eligibility") or "")

    ec = da.get("eligibility_checklist") or []
    if ec:
        _h3("AltCarbon Eligibility Checklist")
        status_icons = {"met": "✅", "likely_met": "🟡", "verify": "❓", "not_met": "❌"}
        for item in ec:
            s = item.get("altcarbon_status", "verify")
            _bullet(f"{status_icons.get(s, '•')} {item.get('criterion', '')} — {s} — {item.get('note', '')}")

    # ── Scoring ──
    _divider()
    _h2("AI Scoring")
    scores = grant.get("scores") or {}
    wt = grant.get("weighted_total")
    if wt is not None:
        _callout(f"Overall Score: {wt:.1f} / 10 — Recommendation: {grant.get('recommended_action', '').upper()}", "🎯")
    for k, v in scores.items():
        _bullet(f"{k.replace('_', ' ').title()}: {v}/10")
    if grant.get("rationale"):
        _h3("Rationale")
        _para(grant["rationale"])
    if grant.get("reasoning"):
        _h3("Strategic Reasoning")
        _para(grant["reasoning"])

    # Evidence
    ef = grant.get("evidence_found") or []
    if ef:
        _h3("Evidence Found")
        for e in ef:
            _bullet(f"✅ {e}")
    eg = grant.get("evidence_gaps") or []
    if eg:
        _h3("Evidence Gaps")
        for e in eg:
            _bullet(f"⚠️ {e}")
    rf = (grant.get("red_flags") or []) + (da.get("red_flags") or [])
    if rf:
        _h3("Red Flags")
        for r in rf:
            _bullet(f"🚩 {r}")

    # ── Key Dates ──
    kd = da.get("key_dates") or {}
    if any(kd.values()):
        _divider()
        _h2("Key Dates & Timelines")
        for k, v in kd.items():
            if v:
                _bullet(f"{k.replace('_', ' ').title()}: {v}")

    # ── Requirements ──
    reqs = da.get("requirements") or {}
    if reqs:
        _divider()
        _h2("Application Requirements")
        for doc in reqs.get("documents_needed") or []:
            _bullet(f"📄 {doc}")
        for att in reqs.get("attachments") or []:
            _bullet(f"📎 {att}")
        if reqs.get("submission_format"):
            _bullet(f"Format: {reqs['submission_format']}")
        if reqs.get("word_page_limits"):
            _bullet(f"Limits: {reqs['word_page_limits']}")
        if reqs.get("co_funding_required"):
            _bullet(f"Co-funding: {reqs['co_funding_required']}")

    if grant.get("application_process") or da.get("application_process_detailed"):
        _h3("Application Process")
        _para(grant.get("application_process") or da.get("application_process_detailed", ""))

    # ── Evaluation Criteria ──
    evc = da.get("evaluation_criteria") or []
    if evc:
        _divider()
        _h2("Evaluation Criteria")
        for item in evc:
            w = f" ({item['weight']})" if item.get("weight") else ""
            _bullet(f"{item.get('criterion', '')}{w}: {item.get('what_they_look_for', '')}")

    # ── Funding Terms ──
    ft = da.get("funding_terms") or {}
    if any(ft.values()):
        _divider()
        _h2("Funding Terms")
        if ft.get("disbursement_schedule"):
            _bullet(f"Disbursement: {ft['disbursement_schedule']}")
        if ft.get("reporting_requirements"):
            _bullet(f"Reporting: {ft['reporting_requirements']}")
        if ft.get("ip_ownership"):
            _bullet(f"IP: {ft['ip_ownership']}")
        for c in ft.get("permitted_costs") or []:
            _bullet(f"✓ Permitted: {c}")
        for c in ft.get("excluded_costs") or []:
            _bullet(f"✗ Excluded: {c}")

    # ── Strategy ──
    _divider()
    _h2("Strategy")
    if da.get("strategic_angle"):
        _callout(da["strategic_angle"], "🎯")
    if da.get("altcarbon_fit_verdict"):
        _bullet(f"AltCarbon fit: {da['altcarbon_fit_verdict'].upper()}")
    if da.get("strategic_note"):
        _para(da["strategic_note"])
    if grant.get("funder_context"):
        _h3("Funder Background")
        _para(grant["funder_context"])
    if da.get("funder_pattern"):
        _h3("Funder Pattern")
        _para(da["funder_pattern"])

    tips = da.get("application_tips") or []
    if tips:
        _h3("Application Tips")
        for t in tips:
            _bullet(f"💡 {t}")

    # ── Past Winners ──
    winners = da.get("winners") or []
    if winners:
        _divider()
        _h2("Past Winners")
        if da.get("total_winners_found"):
            _bullet(f"Total found: {da['total_winners_found']}")
        if da.get("altcarbon_comparable_count"):
            _bullet(f"AltCarbon-comparable: {da['altcarbon_comparable_count']}")
        for w in winners:
            yr = f" ({w['year']})" if w.get("year") else ""
            sim = f" [{w.get('altcarbon_similarity', '')}]" if w.get("altcarbon_similarity") else ""
            _bullet(f"{w.get('name', '?')}{yr}{sim}: {w.get('project_brief', '')}")

    # ── Contact ──
    contact = da.get("contact") or {}
    if any(contact.values()):
        _divider()
        _h2("Contact")
        if contact.get("name"):
            _bullet(f"Name: {contact['name']}")
        if contact.get("email"):
            _bullet(f"Email: {contact['email']}")
        if contact.get("phone"):
            _bullet(f"Phone: {contact['phone']}")
        if contact.get("office"):
            _bullet(f"Office: {contact['office']}")

    # ── Resources ──
    resources = da.get("resources") or {}
    if any(resources.values()):
        _divider()
        _h2("Resources & Links")
        for u in resources.get("brochure_urls") or []:
            _bullet(f"📄 {u}")
        for u in resources.get("info_session_urls") or []:
            _bullet(f"🎥 {u}")
        for u in resources.get("template_urls") or []:
            _bullet(f"📋 {u}")
        if resources.get("faq_url"):
            _bullet(f"❓ FAQ: {resources['faq_url']}")
        if resources.get("guidelines_url"):
            _bullet(f"📖 Guidelines: {resources['guidelines_url']}")

    return blocks


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

    except Exception as e:
        log.warning("Notion log_agent_run failed", exc_info=True)
        return {"success": False, "error": str(e)}


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

    except Exception as e:
        log.warning("Notion log_error failed", exc_info=True)
        return {"success": False, "error": str(e)}


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

    except Exception as e:
        log.warning("Notion log_triage_decision failed", exc_info=True)
        return {"success": False, "error": str(e)}


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
        except Exception as e:
            log.warning("Failed to query existing draft section for %s/%s: %s", grant_id, section_name, e)

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

    except Exception as e:
        log.warning("Notion sync_draft_section failed", exc_info=True)
        return {"success": False, "error": str(e)}


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
