"""Grant Reader — fetches and parses the complete grant context.

Collects the FULL picture from the funder's website, not just one page:
  1. Discovers related pages (FAQ, criteria, tracks, past winners) via Tavily search
  2. Fetches all pages in parallel via Tavily Extract (batch) / Exa / Jina
  3. Combines into one comprehensive document
  4. Falls back to analyst deep_analysis if all fetchers fail

Parsing: LLM extracts structured requirements (sections, criteria, budget).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

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

MIN_CONTENT_CHARS = 500  # Below this, try the next fetcher
MAX_PAGES = 8  # Max subpages to fetch (keeps cost and latency reasonable)


# ── URL Discovery ─────────────────────────────────────────────────────────────

def _get_base_domain(url: str) -> str:
    """Extract base domain from URL (e.g. 'frontierclimate.com')."""
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def _collect_grant_urls(grant: Dict) -> List[str]:
    """Collect all known URLs from the grant record."""
    urls = set()
    for key in ("url", "application_url", "source_url"):
        val = grant.get(key)
        if val and val.startswith("http"):
            urls.add(val)

    # Resources from deep_analysis
    deep = grant.get("deep_analysis") or {}
    resources = deep.get("resources") or grant.get("resources") or {}
    for key in ("guidelines_url", "faq_url"):
        val = resources.get(key)
        if val and val.startswith("http"):
            urls.add(val)
    for key in ("brochure_urls", "template_urls", "info_session_urls"):
        for val in resources.get(key, []) or []:
            if val and val.startswith("http"):
                urls.add(val)

    return list(urls)


async def _discover_related_urls(
    primary_url: str,
    grant_title: str,
    funder: str,
    tavily_key: str,
) -> List[str]:
    """Use Tavily search to discover related pages from the funder's domain.

    Searches for: eligibility, criteria, FAQ, tracks, past winners, guidelines.
    Only keeps URLs from the same domain as the primary URL.
    """
    if not tavily_key:
        return []

    domain = _get_base_domain(primary_url)
    if not domain:
        return []

    query = f"site:{domain} {funder} {grant_title} eligibility criteria FAQ apply guidelines"

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_key)
        result = await asyncio.to_thread(
            client.search,
            query=query,
            search_depth="advanced",
            max_results=10,
            include_domains=[domain],
        )
        discovered = []
        for r in result.get("results", []):
            url = r.get("url", "")
            if url and domain in url:
                discovered.append(url)

        logger.info(
            "Grant Reader: discovered %d related pages from %s",
            len(discovered), domain,
        )
        return discovered
    except Exception as e:
        logger.warning("Grant Reader: discovery search failed: %s", e)
        return []


# ── Fetch methods ─────────────────────────────────────────────────────────────

async def _fetch_with_tavily_batch(urls: List[str], api_key: str) -> Dict[str, str]:
    """Tavily Extract — fetch multiple URLs in one call, returns {url: content}."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)
    result = await asyncio.to_thread(
        client.extract,
        urls=urls,
        extract_depth="advanced",
        format="markdown",
        timeout=60,
    )
    contents = {}
    for r in result.get("results", []):
        url = r.get("url", "")
        content = r.get("raw_content", "")
        if url and content:
            contents[url] = content
    return contents


async def _fetch_with_exa_batch(urls: List[str], api_key: str) -> Dict[str, str]:
    """Exa get_contents — fetch multiple URLs, returns {url: content}."""
    from exa_py import Exa

    client = Exa(api_key=api_key)
    result = await asyncio.to_thread(
        client.get_contents,
        urls=urls,
        text={"max_characters": 30_000},
    )
    contents = {}
    for r in result.results:
        url = getattr(r, "url", "")
        text = getattr(r, "text", "") or ""
        if url and text:
            contents[url] = text
    return contents


async def _fetch_with_jina(url: str, api_key: str = "") -> str:
    """Jina Reader — single URL fetch, best for PDFs and static HTML."""
    jina_url = f"https://r.jina.ai/{url.strip()}"
    headers: Dict[str, str] = {"X-Return-Format": "markdown"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        r = await client.get(jina_url, headers=headers)
        r.raise_for_status()
        return r.text.strip()


async def _fetch_with_playwright(url: str) -> str:
    """Playwright — headless Chromium for heavily JS-protected pages.

    Last resort when Tavily/Exa/Jina all fail. Renders the full page,
    waits for JS, and extracts text content.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit for dynamic content
            await page.wait_for_timeout(2000)
            # Extract main content text
            content = await page.evaluate("""() => {
                // Try to get main content area first
                const main = document.querySelector('main, article, [role="main"], .content, #content');
                if (main && main.innerText.length > 200) return main.innerText;
                // Fall back to body
                return document.body.innerText;
            }""")
            return content.strip() if content else ""
        finally:
            await browser.close()


async def _fetch_with_playwright_batch(urls: List[str]) -> Dict[str, str]:
    """Fetch multiple URLs with Playwright in sequence (shared browser instance)."""
    from playwright.async_api import async_playwright

    contents: Dict[str, str] = {}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for url in urls:
                    try:
                        page = await browser.new_page()
                        await page.goto(url, wait_until="networkidle", timeout=30000)
                        await page.wait_for_timeout(2000)
                        content = await page.evaluate("""() => {
                            const main = document.querySelector('main, article, [role="main"], .content, #content');
                            if (main && main.innerText.length > 200) return main.innerText;
                            return document.body.innerText;
                        }""")
                        if content and len(content.strip()) > 100:
                            contents[url] = content.strip()
                        await page.close()
                    except Exception as e:
                        logger.warning("Grant Reader: Playwright failed for %s: %s", url, e)
            finally:
                await browser.close()
    except Exception as e:
        logger.warning("Grant Reader: Playwright browser launch failed: %s", e)
    return contents


# ── Main fetch orchestrator ───────────────────────────────────────────────────

async def fetch_grant_document(
    url: str,
    grant: Optional[Dict] = None,
    tavily_key: str = "",
    exa_key: str = "",
    jina_key: str = "",
) -> str:
    """Fetch complete grant context — primary page + related pages from funder site.

    1. Collect known URLs from grant record
    2. Discover related pages via Tavily search (same domain)
    3. Deduplicate, cap at MAX_PAGES
    4. Fetch all in parallel via Tavily Extract (batch)
    5. Fallback to Exa / Jina for any that failed
    6. Combine into one document
    """
    grant = grant or {}
    grant_title = grant.get("title") or grant.get("grant_name") or ""
    funder = grant.get("funder") or ""

    # Step 1: Collect all known URLs
    all_urls = _collect_grant_urls(grant) if grant else [url]
    if url not in all_urls:
        all_urls.insert(0, url)

    # Step 2: Discover related pages from funder's site
    if tavily_key:
        discovered = await _discover_related_urls(url, grant_title, funder, tavily_key)
        for d_url in discovered:
            if d_url not in all_urls:
                all_urls.append(d_url)

    # Step 3: Deduplicate and cap
    all_urls = list(dict.fromkeys(all_urls))[:MAX_PAGES]
    logger.info("Grant Reader: fetching %d pages for '%s'", len(all_urls), grant_title or url)

    # Step 4: Fetch all pages
    page_contents: Dict[str, str] = {}

    # Try Tavily batch first (handles SPAs, returns markdown)
    if tavily_key:
        try:
            tavily_results = await _fetch_with_tavily_batch(all_urls, tavily_key)
            page_contents.update(tavily_results)
            logger.info("Grant Reader: Tavily fetched %d/%d pages", len(tavily_results), len(all_urls))
        except Exception as e:
            logger.warning("Grant Reader: Tavily batch failed: %s", e)

    # Exa fallback for URLs that Tavily missed
    missing_urls = [u for u in all_urls if u not in page_contents or len(page_contents.get(u, "")) < MIN_CONTENT_CHARS]
    if missing_urls and exa_key:
        try:
            exa_results = await _fetch_with_exa_batch(missing_urls, exa_key)
            for u, content in exa_results.items():
                if len(content) > len(page_contents.get(u, "")):
                    page_contents[u] = content
            logger.info("Grant Reader: Exa fetched %d/%d missing pages", len(exa_results), len(missing_urls))
        except Exception as e:
            logger.warning("Grant Reader: Exa batch failed: %s", e)

    # Jina fallback for the primary URL if still missing
    if url not in page_contents or len(page_contents.get(url, "")) < MIN_CONTENT_CHARS:
        try:
            jina_content = await _fetch_with_jina(url, jina_key)
            if len(jina_content) > len(page_contents.get(url, "")):
                page_contents[url] = jina_content
                logger.info("Grant Reader: Jina fetched %d chars for primary URL", len(jina_content))
        except Exception as e:
            logger.warning("Grant Reader: Jina failed for %s: %s", url, e)

    # Playwright fallback for any URLs still missing (JS-protected pages)
    still_missing = [u for u in all_urls if u not in page_contents or len(page_contents.get(u, "")) < MIN_CONTENT_CHARS]
    if still_missing:
        try:
            pw_results = await _fetch_with_playwright_batch(still_missing)
            for u, content in pw_results.items():
                if len(content) > len(page_contents.get(u, "")):
                    page_contents[u] = content
            if pw_results:
                logger.info("Grant Reader: Playwright fetched %d/%d remaining pages", len(pw_results), len(still_missing))
        except Exception as e:
            logger.warning("Grant Reader: Playwright fallback failed: %s", e)

    # Step 5: Combine all pages into one document
    if not page_contents:
        logger.error(
            "Grant Reader: ALL fetch methods failed for '%s' (Tavily/Exa/Jina/Playwright) — "
            "drafter will use default sections. Grant: '%s', Funder: '%s'",
            url, grant_title, funder,
        )
        return ""

    # Primary URL first, then related pages
    sections = []
    for page_url in all_urls:
        content = page_contents.get(page_url, "")
        if content and len(content) > 100:
            # Label each page source
            path = urlparse(page_url).path.strip("/") or "home"
            sections.append(f"--- Page: {page_url} ({path}) ---\n\n{content}")

    combined = "\n\n".join(sections)
    total_chars = len(combined)
    logger.info(
        "Grant Reader: combined %d pages → %d chars for '%s'",
        len(sections), total_chars, grant_title or url,
    )

    return combined[:120_000]


# ── Parsing ───────────────────────────────────────────────────────────────────

async def parse_grant_document(raw_content: str) -> Dict:
    """Use LLM to parse raw grant content into structured requirements."""
    if not raw_content or len(raw_content) < 100:
        logger.warning("Grant Reader: insufficient content to parse, using defaults")
        return {"sections_required": DEFAULT_SECTIONS, "evaluation_criteria": [], "eligibility_checklist": [], "budget": {}, "submission": {}}

    prompt = PARSE_PROMPT.format(content=raw_content[:12000])
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


# ── LangGraph node ────────────────────────────────────────────────────────────

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

    raw_doc = await fetch_grant_document(
        url,
        grant=grant,
        tavily_key=s.tavily_api_key,
        exa_key=s.exa_api_key,
        jina_key=getattr(s, "jina_api_key", ""),
    )
    requirements = await parse_grant_document(raw_doc)

    # Fallback: if all fetchers failed but analyst has deep_analysis, use that
    deep = grant.get("deep_analysis") or {}
    fetch_failed = len(raw_doc) < MIN_CONTENT_CHARS
    if fetch_failed and deep:
        logger.info("Grant Reader: using analyst deep_analysis as fallback for %s", grant_id)
        app_sections = deep.get("application_sections", [])
        if app_sections:
            requirements["sections_required"] = [
                {
                    "name": sec.get("section", f"Section {i+1}"),
                    "description": sec.get("what_to_cover", ""),
                    "word_limit": int(sec["limit"].split()[0]) if sec.get("limit") and sec["limit"].split()[0].isdigit() else 500,
                    "required": True,
                    "order": i + 1,
                }
                for i, sec in enumerate(app_sections)
            ]
        eval_criteria = deep.get("evaluation_criteria", [])
        if eval_criteria:
            requirements["evaluation_criteria"] = eval_criteria
        reqs = deep.get("requirements") or {}
        if reqs:
            requirements["budget"] = requirements.get("budget") or {}
            requirements["submission"] = requirements.get("submission") or {}
            if reqs.get("word_page_limits"):
                requirements["submission"]["word_page_limits"] = reqs["word_page_limits"]
            if reqs.get("submission_format"):
                requirements["submission"]["file_format"] = reqs["submission_format"]
            if reqs.get("documents_needed"):
                requirements["submission"]["documents_needed"] = reqs["documents_needed"]
        raw_doc = _build_synthetic_doc(grant, deep)

    from datetime import datetime, timezone
    audit_entry = {
        "node": "grant_reader",
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "content_length": len(raw_doc),
        "sections_found": len(requirements.get("sections_required", [])),
        "pages_fetched": raw_doc.count("--- Page:") if raw_doc else 0,
        "used_deep_analysis_fallback": fetch_failed and bool(deep),
    }
    return {
        "grant_raw_doc": raw_doc,
        "grant_requirements": requirements,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }


def _build_synthetic_doc(grant: Dict, deep: Dict) -> str:
    """Build a synthetic grant document from analyst deep_analysis when fetching fails."""
    parts = []
    parts.append(f"# {grant.get('title') or grant.get('grant_name', 'Grant')}")
    parts.append(f"Funder: {grant.get('funder', 'Unknown')}")
    if grant.get("eligibility"):
        parts.append(f"\n## Eligibility\n{grant['eligibility']}")
    if grant.get("about_opportunity"):
        parts.append(f"\n## About\n{grant['about_opportunity']}")
    if grant.get("application_process"):
        parts.append(f"\n## Application Process\n{grant['application_process']}")
    if deep.get("strategic_angle"):
        parts.append(f"\n## Strategic Angle\n{deep['strategic_angle']}")
    if deep.get("opportunity_summary"):
        parts.append(f"\n## Opportunity Summary\n{deep['opportunity_summary']}")
    criteria = deep.get("evaluation_criteria", [])
    if criteria:
        parts.append("\n## Evaluation Criteria")
        for c in criteria:
            parts.append(f"- {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))} ({c.get('weight', '')})")
    sections = deep.get("application_sections", [])
    if sections:
        parts.append("\n## Application Sections")
        for s in sections:
            parts.append(f"- {s.get('section', '')}: {s.get('what_to_cover', '')} (limit: {s.get('limit', 'n/a')})")
    return "\n".join(parts)
