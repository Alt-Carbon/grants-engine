"""Scout Agent — discovers grant opportunities via Tavily + Exa + Perplexity + direct crawl.

Architecture:
  1. Run all Tavily keyword queries in parallel
  2. Run all Exa semantic queries in parallel (with highlights)
  3. Run all Perplexity Sonar queries in parallel (direct API preferred, gateway fallback)
  4. Crawl known grant pages directly (DFIs, foundations, govt programs, aggregators)
  5. Merge + deduplicate results by URL hash
  6. 3-layer dedup against existing DB (url_hash → normalized URL hash → content hash)
  7. Fetch full content for each new grant (Jina primary, plain HTTP fallback) with retry
  8. LLM field extraction with robust JSON parsing
  9. Quality filter + save via upsert to grants_raw
  10. Hand off raw_grants list to Analyst

Robustness features:
- parse_json_safe: handles code fences, prose prefix, array wrapping
- retry_async: exponential backoff on Jina/Tavily/Exa failures
- Jina concurrency limited to 3 (respects free-tier 10 RPM with per-request delay)
- Per-item enrichment timeout (45s) prevents hung grants from blocking the pipeline
- Direct-crawl has an overall 180s timeout guard
- insert_one → update_one upsert (safe for concurrent/replayed runs)
- grants_scored imported at module level (not inside hot paths)
- Perplexity URL regex strips trailing punctuation
- Quality filter runs on raw title BEFORE LLM extraction overwrites it
- max_tokens raised to 1024 for field extraction
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import httpx

from backend.db.mongo import grants_raw, grants_scored, scout_runs, audit_logs
from backend.graph.state import GrantState
from backend.utils.llm import chat, HAIKU
from backend.utils.parsing import parse_json_safe, retry_async

logger = logging.getLogger(__name__)

# ── Tavily queries ─────────────────────────────────────────────────────────────
DEFAULT_TAVILY_QUERIES: List[str] = [
    # Climate Tech & CDR
    "climatetech startup grant open call 2026",
    "carbon removal CDR MRV startup funding 2026",
    "net zero decarbonisation grant program 2026",
    "climate innovation fund open call for proposals 2026",
    "carbon credit verification technology grant 2026",
    "nature based solutions NBS funding opportunity 2026",
    "climate fintech grant accelerator 2026",
    "biochar enhanced weathering carbon sequestration grant 2026",
    "direct air capture DAC startup grant 2026",
    # Agritech / Soil
    "agritech soil carbon grant program 2026",
    "regenerative agriculture funding open call 2026",
    "sustainable food systems startup grant 2026",
    "precision agriculture technology grant 2026",
    # AI for Sciences
    "AI for climate science research grant 2026",
    "machine learning earth observation grant 2026",
    "AI scientific discovery grant program 2026",
    # Earth Sciences
    "applied earth sciences remote sensing grant 2026",
    "geospatial satellite land use grant 2026",
    "subsurface geology technology grant 2026",
    # India-specific
    "startup India grant climatetech 2026",
    "BIRAC ANRF DST grant open call 2026",
    "India deep tech climate startup grant 2026",
    "SISFS startup India seed fund 2026",
    # Social Impact
    "social impact climate startup funding 2026",
    "inclusive climate solutions grant 2026",
    "rural livelihoods climate resilience grant 2026",
    # India state government grants
    "Karnataka KSCST KBITS startup grant open call 2026",
    "Maharashtra MSINS startup innovation grant 2026",
    "Telangana T-Hub WE Hub grant program 2026",
    "StartupTN Tamil Nadu climatetech agritech grant 2026",
    "KSUM Kerala startup mission grant 2026",
    "iStart Rajasthan Gujarat i-Create grant 2026",
    "India state government startup grant climatetech agritech 2026",
    # DFIs & Multilateral
    "World Bank IFC grant facility climate startups 2026",
    "ADB AIIB climate finance grant 2026",
    "Green Climate Fund GCF readiness grant 2026",
    "USAID climate innovation grant 2026",
    # Philanthropic
    "Bezos Earth Fund grant open call 2026",
    "Grantham Foundation climate grant 2026",
    "ClimateWorks Foundation grant 2026",
    "Rockefeller Foundation climate grant 2026",
    # Accelerators & challenges
    "Google.org Impact Challenge climate 2026",
    "XPRIZE carbon removal challenge 2026",
    "Microsoft Climate Innovation Fund 2026",
    "deep tech climate innovation grant India global 2026",
]

# ── Exa semantic queries ───────────────────────────────────────────────────────
DEFAULT_EXA_QUERIES: List[str] = [
    "grant funding for startups measuring carbon removal and MRV verification",
    "funding for AI-powered environmental monitoring and earth observation tools",
    "grants for alternative carbon market infrastructure and registry startups",
    "research grants for satellite-based land use change detection and geospatial",
    "open calls for climate technology companies in India or globally",
    "philanthropic funding for soil carbon sequestration technology startups",
    "grant programs for AI applied to climate science and biodiversity monitoring",
    "accelerator program for deep tech climate startups with equity-free funding",
    "government grant program for cleantech and net zero startups",
    "international development finance for climate resilience and adaptation startups",
    "Bezos Earth Fund open grant call for climate technology",
    "Green Climate Fund readiness support for developing countries",
    "EU Horizon Europe EIC Accelerator climate deep tech grant",
    "ARPA-E DOE energy innovation grant program open calls",
    "UKRI Innovate UK sustainability and net zero funding competition",
    "BIRAC DBT biotechnology grant agritech climate India",
    "India startup grant for climate technology social impact",
    "Tata Trusts Rohini Nilekani grant India climate livelihoods",
]

# ── Perplexity Sonar queries ────────────────────────────────────────────────────
DEFAULT_PERPLEXITY_QUERIES: List[str] = [
    "What grant programs are currently open for climate technology startups in 2026?",
    "List open calls for funding for carbon removal MRV and net-zero technology startups 2026",
    "What grants or accelerators are accepting applications from agritech and soil carbon startups in 2026?",
    "Open grant calls for AI applied to climate or earth sciences 2026",
    "Which foundations or government programs fund climate startups in India or globally right now?",
    "World Bank ADB IFC AIIB climate finance grant open calls 2026",
    "Bezos Earth Fund Grantham Foundation ClimateWorks open grant applications 2026",
    "BIRAC ANRF DST DBT India startup grant open applications 2026",
    "EU Horizon EIC UKRI climate deep tech grant open calls 2026",
    "XPRIZE Google.org Microsoft climate innovation grant competition 2026",
]

# ── Direct source URLs to crawl ────────────────────────────────────────────────
DIRECT_SOURCE_URLS: Dict[str, List[Dict[str, str]]] = {
    "DFI": [
        {"funder": "IFC", "url": "https://www.ifc.org/en/what-we-do/sector-expertise/climate-finance"},
        {"funder": "World Bank CIF", "url": "https://www.climateinvestmentfunds.org/programs"},
        {"funder": "World Bank", "url": "https://www.worldbank.org/en/programs/apply-for-funding"},
        {"funder": "ADB", "url": "https://www.adb.org/what-we-do/topics/climate-change/overview"},
        {"funder": "AIIB", "url": "https://www.aiib.org/en/about-aiib/who-we-are/partnership/index.html"},
        {"funder": "GCF", "url": "https://www.greenclimate.fund/projects/pipeline"},
        {"funder": "GCF Readiness", "url": "https://www.greenclimate.fund/readiness"},
        {"funder": "GEF SGP", "url": "https://www.thegef.org/who-we-are/secretariat/grants"},
        {"funder": "US DFC", "url": "https://www.dfc.gov/what-we-offer/financing"},
        {"funder": "EIB", "url": "https://www.eib.org/en/projects/index.htm"},
        {"funder": "KfW", "url": "https://www.kfw.de/international-financing/"},
    ],
    "Philanthropic": [
        {"funder": "Bezos Earth Fund", "url": "https://www.bezosearthfund.org/grants"},
        {"funder": "Grantham Foundation", "url": "https://www.granthamfoundation.org/grants"},
        {"funder": "Rockefeller Foundation", "url": "https://www.rockefellerfoundation.org/grants/"},
        {"funder": "ClimateWorks Foundation", "url": "https://www.climateworks.org/grants/"},
        {"funder": "Wellcome Trust", "url": "https://wellcome.org/grant-funding"},
        {"funder": "MacArthur Foundation", "url": "https://www.macfound.org/programs/what-we-fund"},
        {"funder": "Hewlett Foundation", "url": "https://hewlett.org/grants/"},
        {"funder": "Packard Foundation", "url": "https://www.packard.org/grants-and-investments/"},
        {"funder": "Gates Foundation", "url": "https://www.gatesfoundation.org/our-work/programs/global-development"},
        {"funder": "Ford Foundation", "url": "https://www.fordfoundation.org/work/our-grants/"},
        {"funder": "Gordon Betty Moore Foundation", "url": "https://www.moore.org/grants"},
        {"funder": "Rohini Nilekani Philanthropies", "url": "https://rohininilekani.org/"},
        {"funder": "Tata Trusts", "url": "https://www.tatatrusts.org/"},
        {"funder": "Azim Premji Philanthropic Initiative", "url": "https://azimpremjiphilanthropic.org/"},
    ],
    "Climate Funders": [
        {"funder": "Frontier AMC", "url": "https://frontierclimate.com/"},
        {"funder": "Carbon180", "url": "https://carbon180.org/funding"},
        {"funder": "XPRIZE", "url": "https://www.xprize.org/prizes"},
        {"funder": "Spark Climate Solutions", "url": "https://www.sparkclimatesolutions.org/"},
        {"funder": "Global Methane Hub", "url": "https://www.globalmethanehub.org/"},
        {"funder": "Energy Foundation", "url": "https://www.energyfoundation.org/grantmaking/"},
        {"funder": "Climate Collective India", "url": "https://climatecollective.org/"},
        {"funder": "Third Derivative D3", "url": "https://third-derivative.org/"},
        {"funder": "Builders Initiative", "url": "https://www.buildersinitiative.org/"},
        {"funder": "Trellis Climate", "url": "https://www.trellisclimate.org/"},
    ],
    "Government Programs": [
        {"funder": "EU EIC Accelerator", "url": "https://eic.ec.europa.eu/eic-funding-opportunities_en"},
        {"funder": "NSF SBIR", "url": "https://www.nsf.gov/eng/iip/sbir/"},
        {"funder": "DOE ARPA-E", "url": "https://arpa-e.energy.gov/technologies/programs"},
        {"funder": "USAID", "url": "https://www.usaid.gov/work-usaid/find-a-funding-opportunity"},
        {"funder": "UKRI Innovate UK", "url": "https://www.ukri.org/opportunity/"},
        # BIRAC: use the CFP hub listing page (not homepage) so sub-grant expansion picks up all calls
        {"funder": "BIRAC", "url": "https://birac.nic.in/cfp.php"},
        # DST: use the dedicated call-for-proposals listing page
        {"funder": "DST India CFP", "url": "https://dst.gov.in/callforproposals"},
        # ANRF: online portal with all active calls
        {"funder": "ANRF India", "url": "https://anrfonline.in/ANRF/HomePage"},
        {"funder": "Startup India SISFS", "url": "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"},
        {"funder": "AIM ANIC", "url": "https://aim.gov.in/"},
        {"funder": "MeitY Startup Hub", "url": "https://msh.gov.in/"},
        {"funder": "TDB India", "url": "https://www.tdb.gov.in/"},
        {"funder": "NABARD", "url": "https://www.nabard.org/"},
        {"funder": "Mitigation Action Facility", "url": "https://mitigation-action.org/call-for-projects-2026/"},
        {"funder": "ESA Kick-Start", "url": "https://business.esa.int/funding/open-competitive-calls"},
        {"funder": "NASA ROSES", "url": "https://science.nasa.gov/researchers/solicitations/roses-2025/"},
    ],
    "Aggregators": [
        # Hub pages — each is expanded into individual grant URLs via _extract_hub_subgrants()
        {"funder": "Grants.gov", "url": "https://www.grants.gov/search-grants?oppStatuses=forecasted%7Copen"},
        {"funder": "F6S Programs", "url": "https://www.f6s.com/programs"},
        {"funder": "EU Funding Tenders", "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search"},
        {"funder": "Devex", "url": "https://www.devex.com/funding"},
        {"funder": "CSRBOX", "url": "https://csrbox.org/India-CSR-Grants_India-grant-funding/"},
        {"funder": "IndiaGrants", "url": "https://indiagrants.org/"},
        # Extra seed sources from the LangSmith scout that produced good results
        {"funder": "Startup Grants India", "url": "https://www.startupgrantsindia.com/"},
        {"funder": "And Purpose Grants", "url": "https://andpurpose.world/grants/"},
        {"funder": "Grant Repository (Notion)", "url": "https://grantrepository.notion.site/Welcome-Founders-270d3c1b4a3680f3ba32f2eb8f09e9c3"},
        {"funder": "Alan Arguello Accelerators", "url": "https://www.alanarguello.me/blog/accelerators"},
        {"funder": "FundsForNGOs", "url": "https://www2.fundsforngos.org/category/climate-change/"},
        {"funder": "Climate Finance Lab", "url": "https://www.climatefinancelab.org/apply"},
        {"funder": "Wren Climate Collective", "url": "https://www.wren.co/open-grants"},
        {"funder": "remove.global India", "url": "https://remove.global/india-accelerator"},
        {"funder": "Milkywire CDR", "url": "https://milkywire.com/"},
    ],
    "Accelerators": [
        {"funder": "Google.org Impact Challenge", "url": "https://impactchallenge.withgoogle.com/"},
        {"funder": "Microsoft Climate Innovation Fund", "url": "https://www.microsoft.com/en-us/corporate-responsibility/sustainability/climate-innovation-fund"},
        {"funder": "Social Alpha", "url": "https://www.socialalpha.org/"},
        {"funder": "Villgro", "url": "https://villgro.org/"},
        {"funder": "India Climate Collaborative", "url": "https://indiaclimate.org/"},
        {"funder": "Uplink UNDP", "url": "https://uplink.undp.org/"},
        {"funder": "IFC She Wins Climate", "url": "https://www.ifc.org/en/what-we-do/sector-expertise/gender/gender-Inclusive-climate-investment/she-wins-climate"},
        {"funder": "Global Innovation Fund", "url": "https://www.globalinnovation.fund/apply-for-funding"},
        {"funder": "Wellcome Climate Impacts", "url": "https://wellcome.org/grant-funding/schemes/climate-impacts-awards"},
        {"funder": "AI for Climate Bezos", "url": "https://aiforclimateandnature.org/"},
    ],
    # Indian state government startup / science / climate programs.
    # Each state entry is the canonical program page — crawled directly so we
    # don't miss calls that Tavily or Exa overlook.
    "India State Programs": [
        # Karnataka — largest tech + agritech cluster for AltCarbon
        {"funder": "KSCST Karnataka", "url": "https://kscst.org.in/"},
        {"funder": "KBITS Karnataka", "url": "https://kbits.karnataka.gov.in/"},
        {"funder": "Startup Karnataka", "url": "https://startupkarnataka.gov.in/"},
        {"funder": "KIADB Karnataka Agri", "url": "https://www.kiadb.in/"},
        # Maharashtra — Mumbai + Pune startup + MSINS grants
        {"funder": "MSINS Maharashtra", "url": "https://msins.in/"},
        {"funder": "MCED Maharashtra", "url": "https://mced.in/"},
        # Telangana — T-Hub + WE Hub programs
        {"funder": "T-Hub Telangana", "url": "https://t-hub.co/programs"},
        {"funder": "WE Hub Telangana", "url": "https://wehub.telangana.gov.in/"},
        {"funder": "TSIC Telangana", "url": "https://tsic.telangana.gov.in/"},
        # Tamil Nadu
        {"funder": "StartupTN Tamil Nadu", "url": "https://www.startuptn.in/"},
        {"funder": "EDII Tamil Nadu", "url": "https://www.edii.tn.gov.in/"},
        # Kerala — KSUM is very active for climate/agritech
        {"funder": "KSUM Kerala", "url": "https://startupmission.kerala.gov.in/"},
        {"funder": "KSIDC Kerala", "url": "https://www.ksidc.org/"},
        # Gujarat
        {"funder": "i-Create Gujarat", "url": "https://www.icreate.org.in/"},
        {"funder": "GUSEC Gujarat", "url": "https://gusec.edu.in/"},
        # Rajasthan
        {"funder": "iStart Rajasthan", "url": "https://istart.rajasthan.gov.in/"},
        # Andhra Pradesh
        {"funder": "APNRT Andhra Pradesh", "url": "https://www.apnrt.in/"},
        {"funder": "AP Innovation Society", "url": "https://apinnovationsociety.com/"},
        # Madhya Pradesh
        {"funder": "MP Startup Centre", "url": "https://mpstartup.in/"},
        # Haryana
        {"funder": "Startup Haryana", "url": "https://startupharyana.gov.in/"},
        # Delhi
        {"funder": "Startup Delhi", "url": "https://delhi.gov.in/page/startup-delhi"},
        # Uttar Pradesh
        {"funder": "Startup UP", "url": "https://invest.up.gov.in/startup/"},
        # Punjab
        {"funder": "Invest Punjab Startup", "url": "https://www.investpunjab.gov.in/"},
        # Pan-India NABARD / SFAC for agritech specifically
        {"funder": "SFAC India Agritech", "url": "https://www.sfacindia.com/"},
        {"funder": "NABARD Agri Grant", "url": "https://www.nabard.org/content1.aspx?id=591&catid=23&mid=530"},
    ],
}

ALL_DIRECT_SOURCES: List[Dict[str, str]] = [
    src for srcs in DIRECT_SOURCE_URLS.values() for src in srcs
]

# ── LLM field extraction prompt ────────────────────────────────────────────────
EXTRACTION_SYSTEM = (
    "You are a grant data extraction specialist. "
    "Return ONLY valid JSON — no prose, no markdown, no explanation."
)

EXTRACTION_PROMPT = """Extract structured grant information from this grant page content.

Source URL: {url}
Page Title: {raw_title}

Content:
{content}

Return this exact JSON (no other text):
{{
  "grant_name": "<official grant/program name as stated on the page>",
  "sponsor": "<full legal name of the funding organization>",
  "grant_type": "<grant | prize | challenge | accelerator | fellowship | contract | loan | equity | other>",
  "geography": "<eligible countries/regions exactly as stated — e.g. 'India only', 'Global', 'US and EU'>",
  "amount": "<funding amount per applicant exactly as stated — e.g. 'up to $500,000', 'EUR 150,000'; capture what each applicant receives, not total program budget>",
  "max_funding_usd": <integer USD value per applicant — best conversion; null ONLY if truly no amount mentioned anywhere>,
  "currency": "<3-letter code: USD EUR GBP INR, default USD>",
  "deadline": "<application deadline EXACTLY as stated — e.g. 'March 31, 2026', 'Rolling', 'Ongoing'; extract ANY close/submission/deadline date visible; null ONLY if absolutely no date found>",
  "eligibility": "<who can apply: org type (startup/NGO/university), stage (seed/early/growth), sector, geography restrictions including any specific country/region exclusions — max 200 words>",
  "themes": "<key program focus areas and funding priorities — e.g. 'CDR, MRV, climate tech, India early-stage startups'>",
  "application_url": "<DIRECT link to the application form or portal — NOT the program overview page; fill only if you see a dedicated apply/submit/portal link; else null>",
  "source_url": "<the funder's own official grant program page URL; if this content came from a news article or blog mentioning the grant, provide the funder's direct grant page URL if visible in the content; otherwise use {url}>",
  "past_winners_url": "<URL of a past winners / previous awardees / funded projects / portfolio page if visible in the content — e.g. '/awardees', '/winners', '/portfolio'; null if not found>",
  "notes": "<2-3 crisp sentences: what this program funds, who it targets, any key requirements or noteworthy conditions>"
}}

EXTRACTION RULES (follow strictly):
1. deadline — MANDATORY: extract ANY date that appears as a deadline, close date, or submission window end. Use 'Rolling' only if the grant explicitly says it accepts applications on a rolling or continuous basis. Use null only if no date is mentioned anywhere.
2. amount — extract the maximum award PER APPLICANT (not total fund size). E.g. if grant says "up to $500K per company", extract "$500K".
3. application_url — must link directly to an application form, portal, or submit page. Do NOT use the program overview or description page URL. Leave null if no direct apply link is found.
4. source_url — must be the funder's own official page for this specific grant. If content is from a news/blog/press article about the grant, look in the article for the funder's direct URL and use that instead.
5. eligibility — always include: eligible org types, geographic restrictions (including explicit exclusions like "US only", "UK registered only"), stage requirements, and sector focus. Write up to 200 words.
6. sponsor — use the full official organization name (e.g. "Bezos Earth Fund", not "BEF").
7. Indian currency notation — CRITICAL for Indian grants:
   "1 lakh" = 100,000  |  "10 lakh" = 1,000,000  |  "1 crore" = 10,000,000
   Indian comma grouping: "5,00,000" = 500,000 (NOT 5,000 — Indian style groups by 2 after first 3)
   Examples:
     "₹50 lakh"     → amount="₹50 lakh",     max_funding_usd=5000000,  currency="INR"
     "₹2 crore"     → amount="₹2 crore",      max_funding_usd=20000000, currency="INR"
     "Rs. 30,00,000" → amount="Rs. 30,00,000", max_funding_usd=3000000,  currency="INR"
     "₹1.5 lakh"   → amount="₹1.5 lakh",    max_funding_usd=150000,   currency="INR"
   Always set currency="INR" for rupee amounts — do NOT convert to USD in max_funding_usd."""

# ── URL helpers ─────────────────────────────────────────────────────────────────
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
})

_SOCIAL_MEDIA_DOMAINS = frozenset({
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "threads.net", "reddit.com", "t.co",
    "medium.com", "substack.com",
})

_JUNK_TITLE_PATTERNS = (
    "press release", "news:", "newsletter", "blog post", "annual report",
    "impact report", "conference recap", "webinar", "event recap",
    "linkedin post", "twitter thread",
)
_JUNK_URL_PATTERNS = (
    "/news/", "/blog/", "/press-release/", "/press_release/",
    "/events/", "/media/", "/webinar/", "/articles/",
    "/post/", "/posts/", "/status/",
)
_GRANT_KEYWORDS = (
    "apply", "application", "grant", "funding", "fund", "award", "prize",
    "call for", "open call", "deadline", "eligib", "proposal", "submit",
    "accelerator", "fellowship", "competition", "rfp", "rfq",
)

# Perplexity URL cleaner: strip common trailing punctuation
_URL_TRAILING_JUNK = re.compile(r"[.,;:!?\)\]]+$")

# ── Hub page sub-grant expansion ───────────────────────────────────────────────
# These domains host multiple individual grant calls on a single listing page.
# After fetching the hub, we extract each sub-grant URL and enrich it separately.
# This is how the LangSmith scout got 8+ BIRAC entries from a single BIRAC page.
_HUB_SUBGRANT_PATTERNS: Dict[str, List[re.Pattern]] = {
    # BIRAC CFP hub: each call is at cfp_view.php?id=NNN
    "birac.nic.in": [
        re.compile(r"cfp_view\.php\?id=\d+(?:&[^\s\"'<>]*)?"),
    ],
    # DST call-for-proposals listing: /callforproposals/some-title
    "dst.gov.in": [
        re.compile(r"/callforproposals/[a-z0-9][a-z0-9\-_/]+"),
    ],
    # ANRF online portal — match any sub-page except the generic entry points.
    # Previous pattern was too strict (required "call|grant|program|scheme" in path).
    # ANRF uses paths like /ANRF/CallForProposal, /ANRF/CurrentCFP, /ANRF/ListScheme etc.
    "anrfonline.in": [
        re.compile(r"/ANRF/(?!HomePage\b)(?!AnrfPDF\b)(?!index\b)[A-Za-z][A-Za-z0-9_\-/]{3,}", re.I),
    ],
    # Startup India individual scheme pages
    "startupindia.gov.in": [
        re.compile(r"/content/sih/en/[a-z0-9\-_/]+-scheme[a-z0-9\-_.]*\.html"),
    ],
}


def _extract_hub_subgrants(hub_url: str, content: str) -> List[str]:
    """Given a hub/aggregator page URL and its fetched content, extract individual
    grant sub-page URLs. Returns full absolute URLs, deduplicated."""
    from urllib.parse import urljoin
    parsed = urlparse(hub_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")

    sub_urls: List[str] = []
    for domain_key, patterns in _HUB_SUBGRANT_PATTERNS.items():
        if domain_key not in domain:
            continue
        for pat in patterns:
            for match in pat.finditer(content):
                raw = match.group(0)
                # Build absolute URL
                if raw.startswith("http"):
                    full = raw
                elif raw.startswith("/"):
                    full = base + raw
                else:
                    full = urljoin(hub_url, raw)
                # Strip trailing junk
                full = _URL_TRAILING_JUNK.sub("", full)
                if full != hub_url and len(full) > 20:
                    sub_urls.append(full)
        break  # only apply patterns for the first matched domain key

    # Deduplicate preserving order
    seen: set = set()
    result = []
    for u in sub_urls:
        if u not in seen:
            seen.add(u)
            result.append(u)

    if result:
        logger.info("Hub expansion: %s → %d sub-grant URLs", hub_url[:60], len(result))
    return result


def _url_hash(url: str) -> str:
    return hashlib.md5(url.strip().lower().encode()).hexdigest()


def _normalized_url_hash(url: str) -> str:
    try:
        parsed = urlparse(url.strip().lower())
        netloc = parsed.netloc.replace("www.", "")
        params = {k: v for k, v in parse_qs(parsed.query).items()
                  if k not in _TRACKING_PARAMS}
        query = urlencode(sorted(params.items()), doseq=True)
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{netloc}{path}{'?' + query if query else ''}"
        return hashlib.md5(normalized.encode()).hexdigest()
    except Exception:
        return _url_hash(url)


def _content_hash(title: str, funder: str) -> str:
    # If both are empty, fall back to a uuid-like hash to avoid false dedup
    if not title.strip() and not funder.strip():
        return hashlib.md5(os.urandom(16)).hexdigest()

    def norm(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[^\w\s]", "", s)
        return s

    return hashlib.md5(f"{norm(title)}|{norm(funder)}".encode()).hexdigest()


def _is_quality_grant(raw_title: str, url: str, content: str) -> Optional[str]:
    """Return disqualification reason or None. Checks raw_title BEFORE LLM extraction."""
    title_lower = (raw_title or "").lower()
    url_lower = (url or "").lower()
    content_lower = (content or "").lower()

    if len(content_lower) < 200:
        return "Content too short"
    # Block social media and blog platform URLs — these are mentions, not grant pages
    try:
        domain = urlparse(url_lower).netloc.replace("www.", "")
        if any(s in domain for s in _SOCIAL_MEDIA_DOMAINS):
            return "Social media/blog URL — not a grant page"
    except Exception:
        pass
    if any(p in title_lower for p in _JUNK_TITLE_PATTERNS):
        return f"Likely news/article: '{raw_title[:60]}'"
    if any(p in url_lower for p in _JUNK_URL_PATTERNS):
        return "Non-grant URL pattern"
    if not any(k in content_lower for k in _GRANT_KEYWORDS):
        return "No grant-related keywords in content"
    return None


def _detect_themes(text: str) -> List[str]:
    t = text.lower()
    themes = []
    if any(k in t for k in [
        "climate", "carbon", "net zero", "decarboni", "emission", "cdr", "mrv",
        "cleantech", "clean energy", "renewable", "solar", "wind", "green hydrogen",
        "nature based", "biodiversity", "ocean", "methane", "ghg", "greenhouse",
        "biochar", "enhanced weathering", "direct air capture", "dac", "blue carbon",
    ]):
        themes.append("climatetech")
    if any(k in t for k in [
        "agri", "soil", "farm", "crop", "food", "land use", "regenerative",
        "precision agriculture", "agroforestry", "livestock", "fisheries",
    ]):
        themes.append("agritech")
    if any(k in t for k in [
        "artificial intelligence", "machine learning", "ai for", "deep learning",
        "nlp", "computer vision", "neural network", "data science", "predictive model",
    ]):
        themes.append("ai_for_sciences")
    if any(k in t for k in [
        "earth science", "remote sensing", "satellite", "geology", "geospatial",
        "subsurface", "lidar", "mapping", "geophysics", "hydrogeology",
    ]):
        themes.append("applied_earth_sciences")
    if any(k in t for k in [
        "social impact", "community", "rural", "livelihood", "inclusive",
        "women", "gender", "equity", "vulnerable", "marginalized", "poverty",
    ]):
        themes.append("social_impact")
    # Note: NO default fallback — empty list is valid and used by hard rules
    return themes


# ── HTTP fetch helpers ─────────────────────────────────────────────────────────

# Jina concurrency: keep to 3 with a small delay between requests to stay
# within the free-tier limit of 10 RPM (6s per request at concurrency 1 is
# safest, but 3-concurrent with ~1s sleep per batch keeps us under 20 RPM).
_JINA_SEM: asyncio.Semaphore | None = None
_JINA_INTER_REQUEST_DELAY = 1.0  # seconds between Jina requests per slot


def _get_jina_sem() -> asyncio.Semaphore:
    global _JINA_SEM
    if _JINA_SEM is None:
        _JINA_SEM = asyncio.Semaphore(3)
    return _JINA_SEM


async def _fetch_with_jina(url: str, api_key: str = "") -> str:
    """Fetch page content via Jina Reader with rate-limit-aware concurrency."""
    jina_url = f"https://r.jina.ai/{url.strip()}"
    headers: Dict[str, str] = {
        "X-Return-Format": "markdown",
        "X-With-Links-Summary": "false",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def _do_fetch() -> str:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.get(jina_url, headers=headers)
            if r.status_code in (402, 429):
                raise httpx.HTTPStatusError(
                    f"Jina rate limit {r.status_code}", request=r.request, response=r
                )
            r.raise_for_status()
            return r.text.strip()[:80_000]

    sem = _get_jina_sem()
    async with sem:
        result = await retry_async(
            _do_fetch, retries=3, base_delay=4.0, label=f"jina:{url[:60]}"
        )
        await asyncio.sleep(_JINA_INTER_REQUEST_DELAY)
    return result or ""


async def _fetch_plain(url: str) -> str:
    async def _do_fetch() -> str:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; AltCarbonBot/1.0)"})
            r.raise_for_status()
            return r.text[:60_000]

    result = await retry_async(_do_fetch, retries=2, base_delay=2.0, label=f"plain:{url[:60]}")
    return result or ""


async def _fetch_content(url: str, jina_key: str = "") -> str:
    content = await _fetch_with_jina(url, jina_key)
    if len(content) > 300:
        return content
    logger.debug("Jina returned short content for %s — falling back to plain HTTP", url)
    return await _fetch_plain(url)


class ScoutAgent:
    def __init__(
        self,
        tavily_api_key: str = "",
        exa_api_key: str = "",
        jina_api_key: str = "",
        perplexity_api_key: str = "",
        gateway_api_key: str = "",
        gateway_url: str = "https://ai-gateway.vercel.sh/v1",
        custom_tavily_queries: Optional[List[str]] = None,
        custom_exa_queries: Optional[List[str]] = None,
        custom_perplexity_queries: Optional[List[str]] = None,
        max_results_per_query: int = 10,
        enable_direct_crawl: bool = True,
    ):
        self.tavily_key = tavily_api_key
        self.exa_key = exa_api_key
        self.jina_key = jina_api_key
        self.perplexity_key = perplexity_api_key  # direct API key (preferred)
        self.gateway_key = gateway_api_key          # gateway fallback for Perplexity
        self.gateway_url = gateway_url
        self.tavily_queries = custom_tavily_queries or DEFAULT_TAVILY_QUERIES
        self.exa_queries = custom_exa_queries or DEFAULT_EXA_QUERIES
        self.perplexity_queries = custom_perplexity_queries or DEFAULT_PERPLEXITY_QUERIES
        self.max_results = max_results_per_query
        self.enable_direct_crawl = enable_direct_crawl

        self._tavily = None
        if tavily_api_key:
            try:
                from tavily import TavilyClient
                self._tavily = TavilyClient(api_key=tavily_api_key)
            except ImportError:
                logger.warning("tavily-python not installed. Run: pip install tavily-python")

        self._exa = None
        if exa_api_key:
            try:
                from exa_py import Exa
                self._exa = Exa(api_key=exa_api_key)
            except ImportError:
                logger.warning("exa-py not installed. Run: pip install exa-py")

    # ── LLM field extraction ───────────────────────────────────────────────────

    async def _extract_grant_fields(self, url: str, raw_title: str, content: str) -> dict:
        """Use Claude Haiku to extract structured grant fields. Robust JSON parsing."""
        if len(content) < 150:
            return {}
        prompt = EXTRACTION_PROMPT.format(
            url=url,
            raw_title=raw_title,
            content=content[:6000],
        )
        try:
            raw = await chat(
                prompt,
                model=HAIKU,
                max_tokens=1024,   # was 600 — raised to prevent JSON truncation
                system=EXTRACTION_SYSTEM,
            )
            return parse_json_safe(raw)
        except Exception as e:
            logger.debug("Grant field extraction failed for %s: %s", url, e)
            return {}

    # ── Tavily keyword search ──────────────────────────────────────────────────

    async def _tavily_search(self, query: str) -> List[Dict]:
        if not self._tavily:
            return []

        async def _do():
            result = await asyncio.to_thread(
                self._tavily.search,
                query=query,
                search_depth="advanced",
                max_results=self.max_results,
                include_raw_content=True,
            )
            items = []
            for r in result.get("results", []):
                url = r.get("url", "")
                if not url:
                    continue
                items.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "url_hash": _url_hash(url),
                    "raw_content": r.get("raw_content") or r.get("content", ""),
                    "source": "tavily",
                    "relevance_score": r.get("score", 0.5),
                })
            return items

        result = await retry_async(_do, retries=3, base_delay=2.0, label=f"tavily:{query[:40]}")
        items = result or []
        logger.info("Tavily query=%r → %d results", query[:50], len(items))
        return items

    # ── Exa semantic search ────────────────────────────────────────────────────

    async def _exa_search(self, query: str) -> List[Dict]:
        if not self._exa:
            return []

        async def _do():
            result = await asyncio.to_thread(
                self._exa.search_and_contents,
                query,
                num_results=self.max_results,
                text={"max_characters": 3000},
                highlights={"num_sentences": 5, "highlights_per_url": 3},
            )
            items = []
            for r in result.results:
                url = r.url or ""
                if not url:
                    continue
                # Combine highlights + text for richer content
                highlights = getattr(r, "highlights", None) or []
                highlight_text = " ".join(highlights) if highlights else ""
                page_text = getattr(r, "text", None) or ""
                combined = f"{highlight_text}\n\n{page_text}".strip()
                items.append({
                    "title": r.title or "",
                    "url": url,
                    "url_hash": _url_hash(url),
                    "raw_content": combined,
                    "source": "exa",
                    "relevance_score": getattr(r, "score", 0.5) or 0.5,
                })
            return items

        result = await retry_async(_do, retries=3, base_delay=2.0, label=f"exa:{query[:40]}")
        items = result or []
        logger.info("Exa query=%r → %d results", query[:50], len(items))
        return items

    # ── Perplexity Sonar search ────────────────────────────────────────────────

    async def _perplexity_search(self, query: str) -> List[Dict]:
        """Query Perplexity. Uses direct API key if available, gateway as fallback."""
        if self.perplexity_key:
            return await self._perplexity_direct(query)
        if self.gateway_key:
            return await self._perplexity_gateway(query)
        return []

    async def _perplexity_direct(self, query: str) -> List[Dict]:
        """Direct Perplexity API — uses citations field for reliable URL extraction."""
        payload = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a grant research assistant. List specific active grant programs "
                        "with their official names, funders, and URLs. Include full https:// links."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "return_citations": True,
            "search_recency_filter": "month",
        }

        async def _do():
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.perplexity_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                r.raise_for_status()
                return r.json()

        data = await retry_async(_do, retries=3, base_delay=2.0, label=f"perplexity-direct:{query[:40]}")
        if not data:
            return []

        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        # Prefer structured citations, fallback to URL regex
        citations: List[str] = data.get("citations", [])
        text_urls = _extract_urls_from_text(answer)
        all_urls = list(dict.fromkeys(citations + text_urls))[:15]

        return [
            {
                "title": "",
                "url": url,
                "url_hash": _url_hash(url),
                "raw_content": "",   # will be fetched individually in enrich step
                "source": "perplexity",
                "relevance_score": 0.75,
            }
            for url in all_urls
        ]

    async def _perplexity_gateway(self, query: str) -> List[Dict]:
        """Perplexity via Vercel AI Gateway (OpenAI-compat API)."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.gateway_key, base_url=self.gateway_url)

        async def _do():
            response = await client.chat.completions.create(
                model="perplexity/sonar-pro",
                max_tokens=1024,
                messages=[
                    {
                        "role": "system",
                        "content": "List specific active grant programs with full https:// URLs.",
                    },
                    {"role": "user", "content": query},
                ],
            )
            return response.choices[0].message.content or ""

        answer = await retry_async(_do, retries=2, base_delay=2.0, label=f"perplexity-gw:{query[:40]}")
        if not answer:
            return []
        urls = _extract_urls_from_text(answer)[:15]
        return [
            {
                "title": "",
                "url": url,
                "url_hash": _url_hash(url),
                "raw_content": "",
                "source": "perplexity",
                "relevance_score": 0.70,
            }
            for url in urls
        ]

    # ── Direct source crawl ────────────────────────────────────────────────────

    async def _crawl_direct_source(self, source: Dict[str, str]) -> Optional[Dict]:
        url = source["url"]
        funder = source["funder"]
        content = await _fetch_content(url, self.jina_key)
        if len(content) < 100:
            logger.debug("Direct crawl: no content for %s", url)
            return None
        return {
            "title": f"{funder} — Grant Opportunities",
            "url": url,
            "url_hash": _url_hash(url),
            "raw_content": content,
            "source": "direct",
            "funder": funder,
            "relevance_score": 0.8,
        }

    async def _crawl_all_direct_sources(self) -> List[Dict]:
        if not self.enable_direct_crawl:
            return []

        logger.info("Direct crawl: fetching %d known grant source pages", len(ALL_DIRECT_SOURCES))

        async def _safe_crawl(source: Dict[str, str]) -> Optional[Dict]:
            try:
                return await asyncio.wait_for(
                    self._crawl_direct_source(source), timeout=45.0
                )
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug("Direct crawl failed for %s: %s", source["url"], e)
                return None

        # Apply overall 180s timeout to the entire direct crawl phase
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(_safe_crawl(s) for s in ALL_DIRECT_SOURCES)),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Direct crawl hit 180s global timeout — partial results used")
            results = []

        valid = [r for r in results if r is not None]
        logger.info(
            "Direct crawl: %d/%d sources returned content", len(valid), len(ALL_DIRECT_SOURCES)
        )
        return valid

    # ── Main scout run ─────────────────────────────────────────────────────────

    async def run(self) -> List[Dict]:
        """Run full scout: all search sources in parallel → dedup → enrich → save."""
        logger.info(
            "Scout starting: %d Tavily, %d Exa, %d Perplexity, %d direct sources",
            len(self.tavily_queries), len(self.exa_queries),
            len(self.perplexity_queries) if (self.perplexity_key or self.gateway_key) else 0,
            len(ALL_DIRECT_SOURCES) if self.enable_direct_crawl else 0,
        )

        # ── Run all searches in parallel ──────────────────────────────────────
        tavily_tasks = [self._tavily_search(q) for q in self.tavily_queries]
        exa_tasks = [self._exa_search(q) for q in self.exa_queries]
        perplexity_tasks = (
            [self._perplexity_search(q) for q in self.perplexity_queries]
            if (self.perplexity_key or self.gateway_key) else []
        )

        search_results, direct_results = await asyncio.gather(
            asyncio.gather(*(tavily_tasks + exa_tasks + perplexity_tasks)),
            self._crawl_all_direct_sources(),
        )

        # ── Hub expansion: extract sub-grant URLs from listing pages ─────────
        # For hub pages (BIRAC CFP, DST CFP, ANRF), each individual call on the
        # page becomes a separate discovery item — same approach the LangSmith scout
        # uses to produce 8+ BIRAC entries from a single BIRAC hub page.
        hub_expansions: List[Dict] = []
        for item in direct_results:
            sub_urls = _extract_hub_subgrants(item.get("url", ""), item.get("raw_content", ""))
            for sub_url in sub_urls:
                hub_expansions.append({
                    "title": "",
                    "url": sub_url,
                    "url_hash": _url_hash(sub_url),
                    "raw_content": "",   # will be fetched in enrich step
                    "source": "hub_expansion",
                    "funder": item.get("funder", ""),
                    "relevance_score": 0.85,
                })

        if hub_expansions:
            logger.info("Hub expansion: %d additional sub-grant URLs discovered", len(hub_expansions))

        # ── In-memory dedup by url_hash ───────────────────────────────────────
        seen_hashes: set = set()
        unique: List[Dict] = []
        for batch in [*search_results, direct_results, hub_expansions]:
            for item in batch:
                h = item["url_hash"]
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    unique.append(item)

        logger.info("Scout: %d unique URLs after in-memory dedup (incl. hub expansions)", len(unique))

        # ── DB dedup (3-layer) ────────────────────────────────────────────────
        col = grants_raw()
        scored_col = grants_scored()

        known_url_hashes: set = set()
        known_norm_hashes: set = set()
        known_content_hashes: set = set()

        async for doc in col.find({}, {"url_hash": 1, "url": 1, "content_hash": 1}):
            known_url_hashes.add(doc.get("url_hash"))
            if doc.get("url"):
                known_norm_hashes.add(_normalized_url_hash(doc["url"]))
            if doc.get("content_hash"):
                known_content_hashes.add(doc["content_hash"])

        async for doc in scored_col.find({}, {"url": 1, "content_hash": 1, "url_hash": 1}):
            if doc.get("url"):
                known_norm_hashes.add(_normalized_url_hash(doc["url"]))
            if doc.get("url_hash"):
                known_url_hashes.add(doc["url_hash"])
            if doc.get("content_hash"):
                known_content_hashes.add(doc["content_hash"])

        new_grants = []
        for item in unique:
            if item["url_hash"] in known_url_hashes:
                continue
            norm_h = _normalized_url_hash(item["url"])
            if norm_h in known_norm_hashes:
                logger.debug("Normalized URL duplicate, skipping: %s", item["url"])
                continue
            item["normalized_url_hash"] = norm_h
            known_norm_hashes.add(norm_h)
            known_url_hashes.add(item["url_hash"])
            new_grants.append(item)

        logger.info("Scout: %d new grants not in DB", len(new_grants))

        # ── Enrich: fetch content + theme detect + LLM extraction ─────────────
        enrich_sem = asyncio.Semaphore(4)

        async def enrich(item: Dict) -> Dict:
            async with enrich_sem:
                # Preserve the raw title BEFORE LLM extraction (used by quality filter)
                raw_title = item.get("title", "")

                # Fetch full content if we don't have enough
                if len(item.get("raw_content", "")) < 400:
                    item["raw_content"] = await _fetch_content(item["url"], self.jina_key)

                content = item.get("raw_content", "")

                # Theme detection (runs on raw content — no LLM needed)
                item["themes_detected"] = _detect_themes(content + " " + raw_title)

                # LLM field extraction
                extracted = await self._extract_grant_fields(item["url"], raw_title, content)

                # Merge extracted fields, preserving raw values as fallback
                item["grant_name"] = (
                    extracted.get("grant_name")
                    or raw_title
                )
                # Keep `title` as alias for compatibility with existing queries
                item["title"] = item["grant_name"]
                item["funder"] = (
                    extracted.get("sponsor")
                    or item.get("funder")
                    or _extract_funder_from_url(item["url"])
                )
                item["grant_type"] = extracted.get("grant_type") or "grant"
                item["geography"] = extracted.get("geography") or ""
                item["amount"] = extracted.get("amount") or ""
                item["max_funding"] = extracted.get("max_funding_usd")
                item["max_funding_usd"] = item["max_funding"]
                item["currency"] = extracted.get("currency") or "USD"
                item["deadline"] = extracted.get("deadline")
                item["eligibility"] = extracted.get("eligibility") or ""
                item["application_url"] = (
                    extracted.get("application_url") or item.get("url", "")
                )
                item["source_url"] = (
                    extracted.get("source_url") or item.get("url", "")
                )
                item["notes"] = extracted.get("notes") or ""
                item["themes_text"] = extracted.get("themes") or ""
                item["past_winners_url"] = extracted.get("past_winners_url") or None
                item["last_verified_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                item["processed"] = False
                item["scraped_at"] = datetime.now(timezone.utc).isoformat()
                item["_raw_title"] = raw_title  # preserve for quality filter
                return item

        # Wrap each enrich in a per-item timeout
        async def safe_enrich(item: Dict) -> Optional[Dict]:
            try:
                return await asyncio.wait_for(enrich(item), timeout=45.0)
            except asyncio.TimeoutError:
                logger.warning("Enrich timeout for %s", item.get("url"))
                return None
            except Exception as e:
                logger.warning("Enrich error for %s: %s", item.get("url"), e)
                return None

        enriched_raw = await asyncio.gather(*(safe_enrich(g) for g in new_grants))
        enriched = [g for g in enriched_raw if g is not None]

        # ── Quality filter + content-hash dedup + save ────────────────────────
        saved = []
        quality_rejected = 0
        content_dupes = 0

        for grant in enriched:
            if not grant.get("raw_content"):
                quality_rejected += 1
                continue

            # Quality check on the ORIGINAL raw title (before LLM extraction)
            reject_reason = _is_quality_grant(
                grant.get("_raw_title", grant.get("title", "")),
                grant.get("url", ""),
                grant.get("raw_content", ""),
            )
            if reject_reason:
                logger.debug("Quality rejected (%s): %s", reject_reason, grant.get("url"))
                quality_rejected += 1
                continue

            # Layer 3: content-hash dedup
            ch = _content_hash(grant.get("title", ""), grant.get("funder", ""))
            grant["content_hash"] = ch
            if ch in known_content_hashes:
                logger.debug(
                    "Content-hash duplicate (%s / %s) — skipping",
                    grant.get("title", "")[:40], grant.get("funder", ""),
                )
                content_dupes += 1
                continue
            known_content_hashes.add(ch)

            # Clean up internal tracking field
            grant.pop("_raw_title", None)

            # Upsert (safe for concurrent/replayed runs — unique index on url_hash)
            try:
                from pymongo.errors import DuplicateKeyError
                await col.update_one(
                    {"url_hash": grant["url_hash"]},
                    {"$setOnInsert": grant},
                    upsert=True,
                )
                saved.append(grant)
            except DuplicateKeyError:
                logger.debug("Race-condition duplicate for url_hash %s — skipped", grant["url_hash"])
            except Exception as e:
                logger.warning("Failed to save grant %s: %s", grant.get("url"), e)

        logger.info(
            "Scout: %d saved, %d quality-rejected, %d content-dupes",
            len(saved), quality_rejected, content_dupes,
        )

        # ── Log run stats ─────────────────────────────────────────────────────
        run_doc = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "tavily_queries": len(self.tavily_queries),
            "exa_queries": len(self.exa_queries),
            "perplexity_queries": len(self.perplexity_queries) if (self.perplexity_key or self.gateway_key) else 0,
            "direct_sources_crawled": len(ALL_DIRECT_SOURCES) if self.enable_direct_crawl else 0,
            "total_found": len(unique),
            "new_grants": len(saved),
            "quality_rejected": quality_rejected,
            "content_dupes": content_dupes,
        }
        await scout_runs().insert_one(run_doc)
        await audit_logs().insert_one({
            "node": "scout",
            "action": f"Scout run complete: {len(saved)} new grants saved",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **run_doc,
        })

        logger.info("Scout complete: %d grants saved to grants_raw", len(saved))
        return saved


def _extract_funder_from_url(url: str) -> str:
    try:
        domain = urlparse(url).netloc.replace("www.", "")
        parts = domain.split(".")
        return parts[0].replace("-", " ").title() if parts else domain
    except Exception:
        return "Unknown"


def _extract_urls_from_text(text: str) -> List[str]:
    """Extract https:// URLs from text, stripping trailing punctuation."""
    raw_urls = re.findall(r"https?://[^\s\)\]\"\'>,]+", text)
    cleaned = []
    seen = set()
    for u in raw_urls:
        u = _URL_TRAILING_JUNK.sub("", u)
        if u not in seen and len(u) > 12:
            cleaned.append(u)
            seen.add(u)
    return cleaned


async def scout_node(state: GrantState) -> Dict:
    """LangGraph node: run Scout, populate raw_grants (new + backlog)."""
    from backend.config.settings import get_settings
    s = get_settings()

    cfg_doc = await __import__("backend.db.mongo", fromlist=["agent_config"]).agent_config().find_one(
        {"agent": "scout"}
    ) or {}

    agent = ScoutAgent(
        tavily_api_key=s.tavily_api_key,
        exa_api_key=s.exa_api_key,
        jina_api_key=s.jina_api_key,
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        custom_tavily_queries=cfg_doc.get("custom_queries") or None,
        max_results_per_query=cfg_doc.get("max_results_per_query", 10),
        enable_direct_crawl=cfg_doc.get("enable_direct_crawl", True),
    )

    newly_saved = await agent.run()

    # Also pick up any unprocessed grants from prior runs (backlog)
    col = grants_raw()
    backlog = await col.find({"processed": False}).to_list(length=500)
    logger.info("Scout node: %d newly saved, %d backlog unprocessed", len(newly_saved), len(backlog))

    seen: set = {g.get("url_hash") for g in newly_saved if g.get("url_hash")}
    for g in backlog:
        if g.get("url_hash") not in seen:
            seen.add(g.get("url_hash"))
            newly_saved.append(g)

    return {
        "raw_grants": newly_saved,
        "audit_log": state.get("audit_log", []) + [{
            "node": "scout",
            "ts": datetime.now(timezone.utc).isoformat(),
            "grants_found": len(newly_saved),
        }],
    }
