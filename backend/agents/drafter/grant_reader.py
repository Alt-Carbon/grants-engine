"""Grant Reader — fetches and parses the official grant document.

Primary: Cloudflare Browser Rendering (renders JS, returns clean markdown)
Fallback: Firecrawl (if Cloudflare BR fails or content is thin)
Parsing: Claude Sonnet extracts structured requirements
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.utils.llm import chat, DRAFTER_DEFAULT

logger = logging.getLogger(__name__)

PARSE_PROMPT = """You are parsing an official grant application document.
Extract structured information from this grant document.

GRANT DOCUMENT:
{content}

Respond ONLY with valid JSON:
{{
  "sections_required": [
    {{"name": "<section name>", "description": "<what to write>", "word_limit": <int or null>, "required": true, "order": <int>}}
  ],
  "evaluation_criteria": [
    {{"criterion": "<name>", "weight": "<percentage or description>", "description": "<what evaluators look for>"}}
  ],
  "eligibility_checklist": [
    {{"requirement": "<requirement>", "mandatory": true}}
  ],
  "budget": {{
    "min": <int or null>,
    "max": <int or null>,
    "currency": "<currency code>",
    "allowable_costs": ["<cost type>"],
    "restricted_costs": ["<cost type>"]
  }},
  "submission": {{
    "deadline": "<YYYY-MM-DD or text>",
    "platform": "<where to submit>",
    "file_format": "<format>",
    "special_instructions": "<any notes>"
  }},
  "title": "<official grant title>",
  "funder": "<funder organisation>",
  "max_funding": <int or null>
}}

If a field cannot be determined, use null. Sections should cover the full application.
If no sections are listed in the document, use these defaults:
  Project Overview, Technical Approach, Team & Capabilities, Budget Justification, Impact & Outcomes"""


DEFAULT_SECTIONS = [
    {"name": "Project Overview", "description": "High-level summary of the project", "word_limit": 500, "required": True, "order": 1},
    {"name": "Technical Approach", "description": "Detailed technical methodology", "word_limit": 800, "required": True, "order": 2},
    {"name": "Team & Capabilities", "description": "Team qualifications and relevant experience", "word_limit": 400, "required": True, "order": 3},
    {"name": "Budget Justification", "description": "How funds will be used", "word_limit": 300, "required": True, "order": 4},
    {"name": "Impact & Outcomes", "description": "Expected results and broader impact", "word_limit": 400, "required": True, "order": 5},
]

# NOTE: These generic defaults are replaced by theme-specific sections in
# drafter_node.py when the grant's theme is resolved. See theme_profiles.py.


async def _fetch_with_cloudflare(url: str, account_id: str = "", api_token: str = "") -> str:
    """Fetch page content as markdown via Cloudflare Browser Rendering."""
    if not account_id or not api_token:
        return ""
    cf_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/browser-rendering/markdown"
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(
            cf_url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json={"url": url.strip()},
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("result") or "").strip()


async def _fetch_with_firecrawl(url: str, api_key: str) -> str:
    payload = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data", {}).get("markdown") or data.get("markdown", "")


async def fetch_grant_document(url: str, cf_account_id: str = "", cf_token: str = "", firecrawl_key: str = "") -> str:
    """Fetch grant document content. Cloudflare BR primary, Firecrawl fallback."""
    content = ""

    if cf_account_id and cf_token:
        try:
            content = await _fetch_with_cloudflare(url, cf_account_id, cf_token)
            if len(content) > 500:
                logger.info("Grant Reader: Cloudflare BR fetched %d chars from %s", len(content), url)
                return content[:120_000]
            logger.warning("Grant Reader: Cloudflare BR returned thin content (%d chars), trying fallback", len(content))
        except Exception as e:
            logger.warning("Grant Reader: Cloudflare BR failed for %s: %s", url, e)

    if firecrawl_key:
        try:
            content = await _fetch_with_firecrawl(url, firecrawl_key)
            if len(content) > 500:
                logger.info("Grant Reader: Firecrawl fetched %d chars from %s", len(content), url)
                return content[:120_000]
        except Exception as e:
            logger.warning("Grant Reader: Firecrawl failed for %s: %s", url, e)

    return content[:120_000] if content else ""


async def parse_grant_document(raw_content: str) -> Dict:
    """Use Claude Sonnet to parse raw grant content into structured requirements."""
    if not raw_content or len(raw_content) < 100:
        logger.warning("Grant Reader: insufficient content to parse, using defaults")
        return {"sections_required": DEFAULT_SECTIONS, "evaluation_criteria": [], "eligibility_checklist": [], "budget": {}, "submission": {}}

    prompt = PARSE_PROMPT.format(content=raw_content[:8000])
    try:
        raw = await chat(prompt, model=DRAFTER_DEFAULT, max_tokens=2048)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)

        # Ensure sections exist
        if not parsed.get("sections_required"):
            parsed["sections_required"] = DEFAULT_SECTIONS

        return parsed
    except Exception as e:
        logger.error("Grant Reader: parse failed: %s", e)
        return {"sections_required": DEFAULT_SECTIONS, "evaluation_criteria": [], "eligibility_checklist": [], "budget": {}, "submission": {}}


async def grant_reader_node(state: dict) -> dict:
    """LangGraph node: fetch and parse the grant document."""
    from backend.config.settings import get_settings

    s = get_settings()

    # Notion-first: try selected_notion_page_id, fallback to MongoDB
    grant = {}
    notion_page_id = state.get("selected_notion_page_id")
    if notion_page_id:
        try:
            from backend.integrations.notion_data import get_grant_by_page_id
            grant = await get_grant_by_page_id(notion_page_id) or {}
        except Exception:
            pass

    if not grant:
        grant_id = state.get("selected_grant_id")
        if grant_id:
            try:
                from backend.db.mongo import grants_scored
                from bson import ObjectId
                grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
            except Exception:
                pass

    url = grant.get("url", "")
    if not url:
        logger.warning("Grant Reader: no URL for grant %s", grant_id)
        return {
            "grant_raw_doc": "",
            "grant_requirements": {"sections_required": DEFAULT_SECTIONS},
        }

    raw_doc = await fetch_grant_document(url, s.cloudflare_account_id, s.cloudflare_browser_token)
    requirements = await parse_grant_document(raw_doc)

    from datetime import datetime, timezone
    audit_entry = {
        "node": "grant_reader",
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "content_length": len(raw_doc),
        "sections_found": len(requirements.get("sections_required", [])),
    }
    return {
        "grant_raw_doc": raw_doc,
        "grant_requirements": requirements,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
