"""Grant Reader — fetches and parses the official grant document.

Primary: Jina Reader (handles PDFs + messy HTML cleanly)
Fallback: Firecrawl (if Jina fails or content is thin)
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


async def _fetch_with_jina(url: str, api_key: str = "") -> str:
    jina_url = f"https://r.jina.ai/{url.strip()}"
    headers: Dict[str, str] = {"X-Return-Format": "markdown"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        r = await client.get(jina_url, headers=headers)
        r.raise_for_status()
        return r.text.strip()


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


async def fetch_grant_document(url: str, jina_key: str = "", firecrawl_key: str = "") -> str:
    """Fetch grant document content. Jina primary, Firecrawl fallback."""
    content = ""

    if jina_key or True:  # Jina works without a key (rate-limited)
        try:
            content = await _fetch_with_jina(url, jina_key)
            if len(content) > 500:
                logger.info("Grant Reader: Jina fetched %d chars from %s", len(content), url)
                return content[:120_000]
            logger.warning("Grant Reader: Jina returned thin content (%d chars), trying fallback", len(content))
        except Exception as e:
            logger.warning("Grant Reader: Jina failed for %s: %s", url, e)

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
    from backend.db.mongo import grants_scored
    from bson import ObjectId

    s = get_settings()

    grant_id = state.get("selected_grant_id")
    grant = {}
    if grant_id:
        try:
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

    raw_doc = await fetch_grant_document(url, s.jina_api_key)
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
