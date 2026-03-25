"""Analyst Agent — scores grants against AltCarbon's mission and surfaces ranked list.

Flow per grant:
  1. Check if grant already exists in grants_scored (skip if so — idempotent)
  2. Apply hard eligibility rules → auto_pass immediately if any fail
  3. Perplexity funder enrichment — ONLY for grants that passed hard rules
     (cached per funder in MongoDB for 3 days to reduce API spend)
  4. Claude Sonnet 6-dimension scoring with retry (up to 3 attempts)
  5. Compute weighted_total → determine recommended_action via threshold
  6. Upsert to grants_scored (keyed on url_hash — never creates duplicates)
  7. Mark raw grant as processed
  8. Write audit entry to audit_logs collection

Robustness fixes vs previous version:
  - Status bug: auto_pass grants now get status="auto_pass" not "triage"
  - No duplicates: update_one upsert keyed on url_hash, not insert_one
  - Existing scored grants skipped via pre-check (handles run_scraper overlap)
  - max_tokens raised from 1024 → 2048 (prevents JSON truncation)
  - parse_json_safe: handles code fences, prose prefix, array wrapping
  - retry_async: up to 3 attempts on LLM scoring with exponential backoff
  - scoring_error flag set in DB when all retries fail
  - Perplexity enrichment only for grants that pass hard rules
  - Funder context cached in MongoDB (7-day TTL) — no repeat API calls
  - url_hash + content_hash stored in scored records for future dedup
  - grant_name field included alongside title
  - funder_context removed from scoring JSON schema (was redundant with input)
  - Audit entries written to both state AND audit_logs MongoDB collection
  - Deadline comparison uses timezone-aware datetime throughout
  - max_funding=0 funding check fixed (was bypassed by falsy check)
  - Hard rule theme check removed (was dead code — detect_themes has no fallback now)
  - Perplexity cache TTL reduced 7 → 3 days — avoids stale funder context
  - Funder context validated — warns when Perplexity response omits funder name tokens
  - max_funding_usd normalized to USD before scoring prompt — fixes INR/USD confusion
  - England/Scotland/Wales/Great Britain geo exclusion patterns added to hard rules
  - days_to_deadline + deadline_urgent computed in every scored doc
  - human_override/override_reason/override_at fields initialized in scored doc
  - deep_analysis_error flag set when deep research fails or times out
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

from backend.db.mongo import grants_raw, grants_scored, agent_config, audit_logs
from backend.graph.state import GrantState
from backend.utils.llm import chat, ANALYST_HEAVY, ANALYST_LIGHT, ANALYST_FUNDER, SONNET, HAIKU
from backend.utils.parsing import parse_json_safe, retry_async, api_health, CreditExhaustedError

logger = logging.getLogger(__name__)

# ── Default scoring weights (centralized in settings.py) ──────────────────────
from pathlib import Path

from backend.config.settings import get_settings as _get_settings

DEFAULT_WEIGHTS: Dict[str, float] = _get_settings().get_scoring_weights()

# ── Company profile loader (cached, used in all prompts) ──────────────────────
_company_profile_cache: Optional[str] = None


def _get_company_profile() -> str:
    """Load company profile from knowledge file; cache for process lifetime."""
    global _company_profile_cache
    if _company_profile_cache is None:
        profile_path = Path(__file__).parent.parent / "knowledge" / "altcarbon_profile.md"
        try:
            _company_profile_cache = profile_path.read_text(encoding="utf-8")[:3000]
        except FileNotFoundError:
            _company_profile_cache = f"{_get_settings().company_name} — company profile not found"
    return _company_profile_cache


def _get_company_name() -> str:
    return _get_settings().company_name


# ── Scoring prompt ─────────────────────────────────────────────────────────────
SCORING_SYSTEM = (
    "You are an expert grant analyst for {company_name}, a climate technology startup based in India. "
    "Respond ONLY with valid JSON — no prose, no markdown fences, no explanation before or after."
)

# ── Deep research prompt (second LLM pass — pursue/watch grants only) ──────────
DEEP_ANALYSIS_SYSTEM = (
    "You are a senior grant advisor for {company_name}, a climate technology startup based in India "
    "working on CDR, MRV, agritech, AI for earth sciences, and social impact. "
    "You read grant RFPs thoroughly and produce structured research briefs that tell the team "
    "exactly what is required, whether they are eligible, and how to win. "
    "Respond ONLY with valid JSON — no prose, no markdown fences."
)

DEEP_ANALYSIS_PROMPT = """Read the following grant opportunity THOROUGHLY and produce a comprehensive
research brief for {company_name}'s grants team.

{company_name} profile (default — use when no internal knowledge provided):
{company_profile}

{company_context_section}

Grant details:
  Title:           {title}
  Funder:          {funder}
  Source URL:      {source_url}
  Application URL: {application_url}
  Amount:          {amount} {currency}
  Deadline:        {deadline}
  Geography:       {geography}
  Eligibility:     {eligibility}
  Themes:          {themes}
  Notes:           {notes}

Full grant content:
{content}

Funder background:
{funder_context}

Return this exact JSON structure (fill null where information is not found in the content):
{{
  "requirements": {{
    "documents_needed": ["<each required document — e.g. 'Project proposal (max 15 pages)', 'Audited financials', 'Letters of support'>"],
    "attachments": ["<additional attachments — e.g. 'Company registration certificate', 'CVs of key team members'>"],
    "submission_format": "<online portal / email / postal — as stated in the grant>",
    "submission_portal": "<URL of the application portal if mentioned, else null>",
    "word_page_limits": "<any overall length limits stated — e.g. 'Concept note max 5 pages, Full proposal max 30 pages'>",
    "language": "<language requirement if stated, else 'English'>",
    "co_funding_required": "<co-funding or matching requirement if any — e.g. '20% of project cost', else null>"
  }},
  "eligibility_checklist": [
    {{
      "criterion": "<specific eligibility requirement>",
      "altcarbon_status": "<met | likely_met | verify | not_met>",
      "note": "<brief note on why and what {company_name} needs to confirm or do>"
    }}
  ],
  "evaluation_criteria": [
    {{
      "criterion": "<evaluation dimension — e.g. 'Technical innovation'>",
      "weight": "<weight/points if stated — e.g. '40%', '20 points', else null>",
      "what_they_look_for": "<what reviewers want to see for this criterion>"
    }}
  ],
  "application_sections": [
    {{
      "section": "<section name — e.g. 'Executive Summary'>",
      "limit": "<word/page limit if stated, else null>",
      "what_to_cover": "<key points this section should address based on grant requirements>"
    }}
  ],
  "key_dates": {{
    "application_deadline": "<deadline as stated>",
    "loi_deadline": "<Letter of Intent deadline if applicable, else null>",
    "qa_window": "<Q&A or clarification period if mentioned, else null>",
    "notification_date": "<when results will be announced, if stated, else null>",
    "project_start": "<expected project start date if stated, else null>",
    "project_duration": "<grant period — e.g. '12 months', '2 years', else null>"
  }},
  "funding_terms": {{
    "disbursement_schedule": "<how and when funds are released — e.g. '3 tranches: 40%/40%/20%', else null>",
    "reporting_requirements": "<what reports are required and how often>",
    "ip_ownership": "<who owns intellectual property created — state the grant's position>",
    "permitted_costs": ["<allowed cost categories — e.g. 'R&D salaries', 'Equipment', 'Travel'>"],
    "excluded_costs": ["<explicitly excluded costs — e.g. 'Land purchase', 'Overheads >20%'>"],
    "audit_requirement": "<is an independent audit required? yes/no/conditional>"
  }},
  "red_flags": [
    "<anything that could disqualify {company_name} or make the application very difficult>"
  ],
  "strategic_angle": "<2-3 sentences: exactly what narrative {company_name} should lead with given this funder's stated priorities. Name the specific {company_name} product/data/pilot that maps to the grant's evaluation criteria.>",
  "application_tips": [
    "<specific, actionable tip for writing the application — e.g. 'Lead with the soil carbon MRV data from the Karnataka pilot — the evaluation criterion on measurable impact is worth 30%'>"
  ],
  "opportunity_summary": "<4-sentence summary: (1) what this grant funds and its total budget, (2) what a successful applicant receives (money + non-monetary: mentorship, networking, visibility, lab access, etc.), (3) who the ideal applicant is, (4) why {company_name} should care about this specific opportunity>",
  "application_process_detailed": "<step-by-step process in detail: (1) how to apply — online portal URL, email address, or postal submission, (2) required documents at each stage (LOI, concept note, full proposal, budget template, pitch deck, letters of support), (3) stages (e.g. LOI → shortlist → full proposal → interview → award), (4) review timeline — when to expect decisions, (5) any pre-registration, account creation, or partnership requirements before applying>",
  "contact": {{
    "name": "<program manager or contact person name if stated, else null>",
    "email": "<contact email if stated, else null>",
    "emails_all": ["<ALL email addresses found in the content — program team, general inquiries, technical support, regional contacts>"],
    "phone": "<contact phone if stated, else null>",
    "office": "<office or department name if stated, else null>"
  }},
  "resources": {{
    "brochure_urls": ["<URLs of any downloadable brochures, PDFs, guidelines, program guides, FAQs, or information packs found in the content>"],
    "info_session_urls": ["<URLs of webinars, info sessions, Q&A sessions, or orientation events related to this grant>"],
    "template_urls": ["<URLs of any application templates, budget templates, or sample proposals>"],
    "faq_url": "<URL of FAQ page if found, else null>",
    "guidelines_url": "<URL of detailed program guidelines or RFP document if found, else null>"
  }},
  "similar_grants": [
    "<name of similar programs or previous rounds mentioned in the content that {company_name} should also track>"
  ]
}}"""

# ── Past winners extraction (third pass — runs concurrently with deep analysis) ─
WINNERS_EXTRACTION_SYSTEM = (
    "You are a grant research analyst for {company_name}, a climate technology startup in India. "
    "Return ONLY valid JSON — no prose, no markdown fences."
)

WINNERS_EXTRACTION_PROMPT = """Scan this grant page content for information about past winners,
previous awardees, funded projects, or portfolio companies.

Grant: {title}
Funder: {funder}
Source URL: {source_url}

Content:
{content}

{company_name} profile (for similarity scoring):
- India-based for-profit climate + data science company (DPIIT-registered)
- Core tech: ERW on 60,000+ acres, Biochar, MRV platform (FELUDA), D-CAL lab
- Stage: early-growth with revenue; 50 people, 8,000+ farmers, Isometric-verified

Extract ALL past winner/awardee entries you can find. For each winner assess how similar
they are to {company_name} — look for: climate/agritech/AI theme, startup type, Indian origin,
similar technology (MRV, soil carbon, earth observation, precision ag).

Return this exact JSON (no other text):
{{
  "past_winners_url": "<URL of a dedicated past-winners/awardees/portfolio page visible in the content — null if none found>",
  "winners": [
    {{
      "name": "<company or project name>",
      "year": <year as integer, or null>,
      "project_brief": "<1-2 sentences: what they built or researched>",
      "country": "<country or region, or null>",
      "amount": "<amount received if stated, else null>",
      "website": "<their website URL if visible, else null>",
      "altcarbon_similarity": "<high|medium|low>",
      "similarity_reason": "<one sentence: why similar or different to {company_name}>"
    }}
  ],
  "total_winners_found": <integer count of winners extracted>,
  "altcarbon_comparable_count": <count with high or medium similarity>,
  "funder_pattern": "<2-3 sentences: what patterns do you see in who gets funded? Sectors, geographies, org types, project stages. Be specific.>",
  "altcarbon_fit_verdict": "<strong|moderate|weak|unknown — how well does {company_name}'s profile match the historical awardee profile?>",
  "strategic_note": "<1-2 sentences: one concrete insight for {company_name} based on past winners — e.g. 'All 4 Indian awardees were post-revenue; {company_name}'s pilot data directly addresses this bar'>"
}}

If NO past winner data is visible in the content return:
{{"past_winners_url": null, "winners": [], "total_winners_found": 0,
  "altcarbon_comparable_count": 0, "funder_pattern": "No past winner data found in content.",
  "altcarbon_fit_verdict": "unknown", "strategic_note": null}}"""


SCORING_PROMPT = """You are scoring a grant opportunity for {company_name}. Use the profile below to judge fit.

=== COMPANY PROFILE ===
{company_profile}

{company_context_section}

=== GRANT TO EVALUATE ===
Title: {title}
Funder: {funder}
Source URL: {source_url}
Application URL: {application_url}
Geography: {geography}
Amount: {amount} {currency}
Deadline: {deadline}
Eligibility: {eligibility}
Program themes: {themes}
Notes: {notes}

Content snippet:
{content}

Funder research context:
{funder_context}

=== SCORING RUBRIC (score each dimension 1–10) ===

1. theme_alignment:
   9-10 = Directly funds CDR, ERW, biochar, MRV, soil carbon monitoring, or carbon credit verification
   7-8  = Funds broader climate tech, agritech, AI for earth sciences, or deep tech that {company_name} works in
   5-6  = Adjacent sector (clean energy, water, biodiversity) with partial overlap to {company_name}'s work
   3-4  = Tangential (general sustainability, ESG, green finance) — {company_name} could stretch to fit
   1-2  = Unrelated sector (fintech, pharma, arts, pure digital, social media, edtech)

2. eligibility_confidence:
   9-10 = {company_name} explicitly qualifies: for-profit, DPIIT-registered, India-based, climate/agritech startup accepted
   7-8  = Likely eligible: open to startups or companies, no org-type exclusion, India or global eligible
   5-6  = Uncertain: eligibility criteria unclear, or requires verification (e.g. "SME" may or may not include Indian startups)
   3-4  = Likely ineligible: requires nonprofit status, academic affiliation, specific country registration, or government entity
   1-2  = Clearly ineligible: US/EU-only entities, 501(c)(3) required, individual researchers only

3. funding_amount (max_funding_usd={max_funding_usd}):
   9-10 = >$500K per applicant
   7-8  = $100K–$500K
   5-6  = $25K–$100K
   3-4  = $10K–$25K
   1-2  = <$10K or amount unknown

4. geography_fit:
   9-10 = Explicitly targets India, South Asia, or developing countries
   7-8  = Global/international — open to all countries including India
   5-6  = Unclear geography, or targets a region that may include India (Asia-Pacific, BRICS, G20)
   3-4  = Targets a specific non-India region but does not explicitly exclude India
   1-2  = Explicitly excludes India (US-only, EU-only, specific country registration required)

5. competition_level:
   9-10 = Highly niche/selective (<50 expected applicants) — e.g. CDR-specific, ERW-specific, India climate only
   7-8  = Moderately selective (<200 expected applicants) — sector-specific or regional
   5-6  = Broad but themed (~200-1000 applicants) — e.g. "climate innovation" open call
   3-4  = Very broad (1000-5000 applicants) — e.g. general startup competitions, large accelerators
   1-2  = Mass open call (5000+ applicants) — e.g. global prizes, mega-competitions

Return this exact JSON (no other text):
{{
  "scores": {{
    "theme_alignment": <int 1-10>,
    "eligibility_confidence": <int 1-10>,
    "funding_amount": <int 1-10>,
    "geography_fit": <int 1-10>,
    "competition_level": <int 1-10>
  }},
  "evidence_found": ["<specific thing matching {company_name}'s mission>", ...],
  "evidence_gaps": ["<requirement {company_name} may not meet>", ...],
  "red_flags": ["<serious disqualifying concern>"],
  "reasoning": "<2-3 sentences explaining the overall score and key trade-offs — be specific about which eligibility or scope issues matter most>",
  "rationale": "<SPECIFIC 2-3 sentences: name the grant and funder, state exactly which {company_name} theme (CDR/MRV/agritech/AI for sciences/earth sciences/social impact/deep tech) aligns with the funder's stated priorities, and what competitive edge {company_name} has (India base, startup stage, specific technology). Be actionable and crisp — e.g. 'The Bezos CDR Fund directly funds companies building carbon removal measurement — {company_name}'s MRV platform addresses the core verification gap this program targets. India-headquartered with global pilots gives geographic diversity few CDR applicants offer.'>"
}}"""


# ── Currency conversion for hard rules ─────────────────────────────────────────
# How many foreign-currency units equal 1 USD (approximate, used only for
# minimum-funding gating — not for financial calculations).
# The LLM extraction stores max_funding_usd as the raw original-currency amount
# when currency != USD, so we convert here before comparing against the threshold.
def _get_exchange_rates() -> Dict[str, float]:
    """Lazy accessor for exchange rates from settings (avoids import-time settings load)."""
    from backend.config.settings import get_settings
    return get_settings().get_exchange_rates()

_CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$", "INR": "₹", "EUR": "€", "GBP": "£",
    "CAD": "CA$", "AUD": "A$", "SGD": "S$", "JPY": "¥",
    "BRL": "R$", "ZAR": "R", "KES": "KES ", "NGN": "₦",
}

def _get_currency_min_funding() -> Dict[str, float]:
    """Lazy accessor for per-currency minimum funding thresholds from settings."""
    from backend.config.settings import get_settings
    return {
        "INR": get_settings().min_funding_inr,
    }

# Currency values that mean "we don't know the currency".
# When a funding amount is present but currency is unrecognised, the grant is
# placed on HOLD for manual review rather than auto-passed or scored with wrong scale.
_UNKNOWN_CURRENCY_TERMS = frozenset({
    "", "unknown", "other", "n/a", "na", "tbd", "not specified",
    "various", "local currency", "local", "multiple",
})


def _normalize_to_usd(amount: float, currency: str) -> float:
    """Convert an amount in any supported currency to approximate USD.

    Example: _normalize_to_usd(250_000, "INR") → 2,994.0 USD
    """
    rate = _get_exchange_rates().get(currency.upper(), 1.0)
    return round(amount / rate, 2)


_CURRENCY_RESOLUTION_SYSTEM = (
    "You are a grant data specialist. "
    "Return ONLY valid JSON — no prose, no markdown, no explanation."
)

_CURRENCY_RESOLUTION_PROMPT = """A grant page was scraped but its currency is missing or unrecognised.
Read the content carefully and identify the currency and amount.

Grant title:   {title}
Extracted amount string: {amount_raw}
Source URL:    {source_url}

Page content:
{content}

Look for ANY of these signals:
- Currency symbols: ₹ → INR, $ → USD, € → EUR, £ → GBP, CA$ → CAD, A$ → AUD, S$ → SGD, ¥ → JPY
- Currency words: "rupees", "lakh", "crore", "lakhs" → INR; "dollars" → USD; "euros" → EUR; "pounds" → GBP
- Contextual clues: Indian government/BIRAC/DST/state govt pages → almost certainly INR
- Funding ranges like "50,000 – 2,00,000" with Indian comma style → INR
- If the funder is in the URL domain (birac.nic.in, dst.gov.in, *.gov.in, *.nic.in) → INR

Return this exact JSON (no other text):
{{
  "currency": "<3-letter ISO code: INR/USD/EUR/GBP/CAD/AUD/SGD/JPY — or null if genuinely unknown>",
  "amount_per_applicant": <numeric value — max award per applicant; null if not determinable>,
  "confidence": "<high|medium|low>",
  "evidence": "<exact text snippet (≤ 80 chars) from the content that reveals the currency>"
}}"""


async def _resolve_unknown_currency(grant: Dict) -> Optional[Dict]:
    """Attempt to resolve an unknown currency by re-reading the grant's raw content
    with a focused LLM call.

    Returns a patch dict  {currency, max_funding, max_funding_usd, amount,
    _currency_resolved, _currency_evidence}  if resolved, or None if still unknown.
    The caller should merge the patch into the grant dict before continuing to scoring.
    """
    content = (grant.get("raw_content") or "")[:8_000]
    if not content:
        logger.debug("Currency resolution: no raw_content for %s", grant.get("url", "")[:60])
        return None

    title = grant.get("title") or grant.get("grant_name", "")
    prompt = _CURRENCY_RESOLUTION_PROMPT.format(
        title=title,
        amount_raw=grant.get("amount") or "not extracted",
        source_url=grant.get("source_url") or grant.get("url", ""),
        content=content,
    )

    try:
        raw = await chat(
            prompt,
            model=ANALYST_LIGHT,
            max_tokens=256,
            system=_CURRENCY_RESOLUTION_SYSTEM,
        )
        result = parse_json_safe(raw)
        if not result or not isinstance(result, dict):
            return None

        resolved_currency = (result.get("currency") or "").strip().upper()
        if not resolved_currency or resolved_currency in ("NULL", "NONE", "UNKNOWN"):
            logger.debug(
                "Currency resolution returned null for %s", grant.get("url", "")[:60]
            )
            return None

        # Accept recognised currencies only
        if resolved_currency not in _get_exchange_rates():
            logger.debug(
                "Currency resolution returned unrecognised code '%s' for %s",
                resolved_currency, grant.get("url", "")[:60],
            )
            return None

        amount = result.get("amount_per_applicant")
        try:
            usd_val = (
                _normalize_to_usd(float(amount), resolved_currency)
                if amount and float(amount) > 0
                else None
            )
        except (TypeError, ValueError):
            usd_val = None
        evidence = (result.get("evidence") or "")[:120]
        confidence = result.get("confidence", "low")

        logger.info(
            "Currency resolved: %s → %s %s  [%s confidence] evidence='%s'  url=%s",
            title[:40], resolved_currency, amount, confidence, evidence,
            grant.get("url", "")[:60],
        )

        return {
            "currency":        resolved_currency,
            "max_funding":     amount,
            "max_funding_usd": usd_val,
            # Update the human-readable amount string to include currency symbol
            "amount": (
                f"{_CURRENCY_SYMBOLS.get(resolved_currency, resolved_currency + ' ')}"
                f"{amount:,.0f}" if amount else grant.get("amount", "")
            ),
            "_currency_resolved":  True,
            "_currency_confidence": confidence,
            "_currency_evidence":  evidence,
        }

    except Exception as e:
        logger.debug(
            "Currency resolution failed for %s: %s", grant.get("url", "")[:60], e
        )
        return None


def _check_hold_conditions(grant: Dict) -> Optional[str]:
    """Return a reason string if the grant has an unknown currency with a stated amount.

    Used to trigger currency resolution attempts. If resolution fails, the grant
    proceeds to scoring anyway (with an evidence gap note) — never blocks triage.
    """
    raw_funding = grant.get("max_funding_usd") or grant.get("max_funding")
    try:
        raw_funding_num = float(raw_funding) if raw_funding else 0
    except (TypeError, ValueError):
        raw_funding_num = 0
    if raw_funding_num <= 0:
        return None  # No amount stated — currency irrelevant, proceed to scoring

    currency = (grant.get("currency") or "").strip()
    cu = currency.upper()

    is_unknown = (
        cu in {t.upper() for t in _UNKNOWN_CURRENCY_TERMS}
        or (len(cu) == 3 and cu not in _get_exchange_rates())
        or len(cu) == 0
    )
    if is_unknown:
        display = f"'{currency}'" if currency else "not set"
        return (
            f"Currency {display} — cannot evaluate funding amount {raw_funding_num:,.0f} "
            f"without knowing the currency; needs manual review"
        )
    return None


# ── Amount string → currency parser ──────────────────────────────────────────

# Maps common prefixes/symbols in amount strings to ISO currency codes
_AMOUNT_CURRENCY_PATTERNS = [
    (r"(?:INR|₹|Rs\.?)\s*", "INR"),
    (r"(?:USD|\$|US\$)\s*", "USD"),
    (r"(?:EUR|€)\s*", "EUR"),
    (r"(?:GBP|£)\s*", "GBP"),
    (r"(?:CAD|C\$|CA\$)\s*", "CAD"),
    (r"(?:AUD|A\$|AU\$)\s*", "AUD"),
    (r"(?:SGD|S\$|SG\$)\s*", "SGD"),
    (r"(?:JPY|¥)\s*", "JPY"),
    (r"(?:BRL|R\$)\s*", "BRL"),
]


def _patch_currency_from_amount(grant: Dict) -> None:
    """If currency is empty/unknown, try to parse it from the amount string.

    E.g. amount="INR 85,000,000" → sets currency="INR", max_funding=85000000.
    Mutates grant in-place.
    """
    currency = (grant.get("currency") or "").strip().upper()
    if currency and currency not in {t.upper() for t in _UNKNOWN_CURRENCY_TERMS}:
        return  # Already has a valid currency

    amount_str = grant.get("amount") or ""
    if not amount_str:
        return

    for pattern, iso_code in _AMOUNT_CURRENCY_PATTERNS:
        m = re.match(pattern, amount_str, re.IGNORECASE)
        if m:
            # Extract the numeric part after the currency prefix
            remainder = amount_str[m.end():].strip()
            # Parse number (handle commas, spaces)
            num_match = re.match(r"[\d,.\s]+", remainder)
            if num_match:
                num_str = num_match.group().replace(",", "").replace(" ", "").strip()
                try:
                    amount_val = float(num_str)
                    if amount_val > 0:
                        grant["currency"] = iso_code
                        grant["max_funding"] = amount_val
                        grant["max_funding_usd"] = _normalize_to_usd(amount_val, iso_code)
                        logger.info(
                            "Parsed currency from amount string: '%s' → %s %.0f (USD %.0f)",
                            amount_str[:40], iso_code, amount_val,
                            grant["max_funding_usd"],
                        )
                        return
                except (ValueError, TypeError):
                    pass
            break  # Pattern matched but number didn't parse — don't try other patterns


# ── Date parsing ───────────────────────────────────────────────────────────────
_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    "%B %Y", "%b %Y",
]
_ROLLING_TERMS = frozenset({
    "rolling", "ongoing", "open", "tbd", "not specified",
    "year-round", "no deadline", "continuous",
})


def parse_deadline(date_str: Optional[str]) -> Optional[datetime]:
    """Parse deadline string → timezone-aware datetime, or None if unparseable."""
    if not date_str:
        return None
    s = date_str.strip()
    if s.lower() in _ROLLING_TERMS or len(s) < 4:
        return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # YYYY-MM-DD anywhere in the string
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass

    # DD Month YYYY
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


# ── Hard eligibility rules ─────────────────────────────────────────────────────
#
# Geography exclusion patterns.
# Only triggers when a region is paired with "only / exclusive / entities / based".
# "US and global" or "US, India, EU" will NOT match — only explicit lock-out.
_GEO_EXCLUDE_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bus\s*(only|entities|organizations?|companies|startups?|based|registered)\b",
        r"\bunited\s*states?\s*(only|entities|organizations?|based|registered)\b",
        r"\bamerican\s*(entities|organizations?|companies|nonprofits?)\s*only\b",
        r"\beu\s*(only|member\s*states?\s*only|based\s*only|entities\s*only)\b",
        r"\beuropean\s*(union\s*)?(only|member\s*states?\s*only)\b",
        r"\beurope\s*only\b",
        r"\buk\s*only\b",
        r"\bunited\s*kingdom\s*only\b",
        r"\baustralia\s*only\b",
        r"\bcanada\s*only\b",
        r"\bafrica\s*only\b",
        r"\bsub.?saharan\s*africa\s*only\b",
        r"\blatin\s*america\s*only\b",
        r"\bnorth\s*america\s*only\b",
        # UK sub-region exclusions (supplement the existing uk/united-kingdom patterns)
        r"\bengland\s*only\b",
        r"\bscotland\s*only\b",
        r"\bwales\s*only\b",
        r"\bgreat\s*britain\s*only\b",
        r"\bnorthern\s*ireland\s*only\b",
    ]
]

# Geography eligible terms — if ANY of these appear, geo exclusion is overridden.
# Handles cases like "US entities or global applicants welcome".
_GEO_ELIGIBLE_TERMS: List[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bglobal\b", r"\bworldwide\b", r"\binternational\b",
        r"\bindia\b", r"\bindian\b", r"\bsouth\s*asia\b",
        r"\bdeveloping\s*countr", r"\bemerging\s*market",
        r"\basia\b", r"\basia.?pacific\b", r"\bapac\b",
        r"\bsaarc\b", r"\bbrics\b", r"\bg20\b",
        r"\blmic\b", r"\bglobal\s*south\b", r"\bindo.?pacific\b",
    ]
]

# Org-type exclusion patterns.
# Only fires when "only" or "exclusive" is nearby — avoids false positives on
# grants that say "non-profits and startups welcome".
_ORG_EXCLUDE_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bnon.?profits?\s*(organizations?\s*)?(only|exclusive)\b",
        r"\bngo\s*(only|exclusive|organizations?\s*only)\b",
        r"\b(only\s+)?(non.?profit|ngo|charitable)\s*organizations?\s*are\s*eligible\b",
        r"\bacademic\s*(institutions?\s*)?(only|exclusive)\b",
        r"\buniversit(y|ies)\s*(only|and\s*research\s*institutions?\s*only)\b",
        r"\bopen\s+only\s+to\s+(universities|academic\s*institutions?|researchers?)\b",
        r"\bstudents?\s*(only|exclusive|led\s*organizations?\s*only)\b",
        r"\bindividual\s*researchers?\s*(only|exclusive)\b",
        r"\btravel\s*(grant|costs?\s*only|expenses?\s*only)\b",
        r"\b501\(c\)\(3\)\s*(only|exclusive|organizations?\s*only)\b",
        r"\bregistered\s*charities\s*(only|exclusive)\b",
        r"\bgovernment\s*(agencies|entities)\s*only\b",
        r"\bcivil\s*society\s*organizations?\s*only\b",
        r"\bcommunity.?based\s*organizations?\s*only\b",
        r"\bpublic\s*sector\s*(only|exclusive)\b",
    ]
]

# Stage exclusion — if grant is only for pre-revenue/idea stage AND we're post-TRL
# (currently not used as hard rule — scored softly instead)


def _check_geography(geo: str, eligibility: str) -> Optional[str]:
    """Return rejection reason if geography explicitly excludes India/global applicants."""
    combined = f"{geo} {eligibility}".strip()
    if not combined:
        return None  # unknown geography — let scoring handle it

    # If any eligible term is present, assume India can apply
    if any(p.search(combined) for p in _GEO_ELIGIBLE_TERMS):
        return None

    # Check for explicit exclusion (region + "only")
    for pat in _GEO_EXCLUDE_PATTERNS:
        m = pat.search(combined)
        if m:
            return f"Geography excludes India/global applicants: '{m.group(0)}'"

    return None


def _check_org_type(eligibility: str) -> Optional[str]:
    """Return rejection reason if eligibility explicitly restricts to non-profits,
    academia, students, or other org types AltCarbon cannot satisfy."""
    if not eligibility:
        return None

    for pat in _ORG_EXCLUDE_PATTERNS:
        m = pat.search(eligibility)
        if m:
            return f"Org-type ineligible (for-profit startup excluded): '{m.group(0)}'"

    return None


def _apply_hard_rules(grant: Dict, min_funding: int = 3_000) -> Optional[str]:
    """Return a disqualification reason string, or None if the grant passes all rules.

    Rules (checked in order — first failure wins):
    1. Minimum funding threshold — INR: ₹1.5L native; USD: $3K; others: USD-converted
    2. Deadline already passed
    3. Geography explicitly excludes India / global applicants
    4. Org-type eligibility explicitly excludes for-profit startups
    """
    # Rule 1: minimum funding (currency-aware)
    # - INR grants: compared against per-currency min funding (₹1.5L) directly
    # - USD grants: compared against min_funding ($3,000) directly
    # - Other currencies: converted to USD then compared against min_funding
    raw_funding = grant.get("max_funding_usd") or grant.get("max_funding")
    currency = (grant.get("currency") or "USD").upper()
    currency_min_funding = _get_currency_min_funding()
    if raw_funding is not None and raw_funding > 0:
        sym = _CURRENCY_SYMBOLS.get(currency, f"{currency} ")
        if currency in currency_min_funding:
            # Use the currency-native threshold (e.g. ₹1.5L for INR)
            cur_min = currency_min_funding[currency]
            if raw_funding < cur_min:
                return (
                    f"Below {sym}{cur_min:,} minimum funding "
                    f"(found: {sym}{raw_funding:,.0f})"
                )
        elif currency == "USD":
            if raw_funding < min_funding:
                return f"Below ${min_funding:,} minimum funding (found: ${raw_funding:,})"
        else:
            # Convert to USD for all other currencies
            funding_usd = _normalize_to_usd(raw_funding, currency)
            if funding_usd < min_funding:
                return (
                    f"Below ${min_funding:,} minimum funding "
                    f"(found: {sym}{raw_funding:,.0f} ≈ ${funding_usd:,.0f} USD)"
                )

    # Rule 2: deadline already passed (timezone-aware comparison)
    deadline_str = grant.get("deadline")
    if deadline_str:
        parsed = parse_deadline(deadline_str)
        if parsed is not None and parsed < datetime.now(tz=timezone.utc):
            return f"Deadline has already passed ({deadline_str})"

    # Rule 3: geography explicitly excludes India
    geo_reason = _check_geography(
        grant.get("geography", ""),
        grant.get("eligibility", ""),
    )
    if geo_reason:
        return geo_reason

    # Rule 4: org type explicitly excludes for-profit startups
    org_reason = _check_org_type(grant.get("eligibility", ""))
    if org_reason:
        return org_reason

    return None


# ── Perplexity funder research (with 3-day MongoDB cache) ─────────────────────

def _validate_funder_context(funder: str, context: str) -> str:
    """Sanity-check Perplexity context — return unchanged if meaningful funder name
    tokens appear in the response, otherwise prepend a caution flag.

    Perplexity can return a hallucinated or unrelated funder profile when the
    funder name is ambiguous (e.g. 'DST' = US Dept. of Science & Technology vs
    Indian DST).  A simple name-token check catches obvious mismatches without
    being overly strict.
    """
    if not funder or not context or len(context) < 50:
        return context or "No funder research available."

    # Split funder name into meaningful tokens (skip short stop-words)
    tokens = [t.lower() for t in re.split(r"[\s\-/,()]+", funder) if len(t) > 3]
    if not tokens:
        return context

    ctx_lower = context.lower()
    matched = sum(1 for tok in tokens if tok in ctx_lower)
    # Accept if at least half the meaningful name-tokens appear in the context
    if matched >= max(1, len(tokens) // 2):
        return context

    logger.warning(
        "Funder context may be hallucinated for '%s' — name tokens not found in response",
        funder,
    )
    return (
        f"[CAUTION: Perplexity context may not describe '{funder}' — "
        f"treat with skepticism]\n\n{context}"
    )


async def _get_funder_context(
    funder: str,
    perplexity_key: str = "",
    gateway_api_key: str = "",
    gateway_url: str = "https://ai-gateway.vercel.sh/v1",
) -> str:
    """Fetch Perplexity funder intelligence. Results cached in MongoDB for 3 days."""
    if not funder or funder.lower() in ("unknown", ""):
        return "No funder research available."

    from backend.db.mongo import get_db
    db = get_db()
    cache_col = db["funder_context_cache"]

    # Check cache (3-day TTL — reduced from 7 to catch funder priority shifts)
    try:
        cached = await cache_col.find_one({"funder": funder})
        if cached:
            cached_at = datetime.fromisoformat(cached["cached_at"])
            if (datetime.now(tz=timezone.utc) - cached_at) < timedelta(days=3):
                logger.debug("Funder context cache hit: %s", funder)
                return _validate_funder_context(funder, cached["context"])
    except Exception:
        pass

    # Fetch from Perplexity (gateway preferred, direct fallback)
    context = await _perplexity_funder_research(
        funder,
        api_key=perplexity_key,
        gateway_api_key=gateway_api_key,
        gateway_url=gateway_url,
    )

    # Cache the raw context (validation prefix is applied at return time, not stored)
    try:
        await cache_col.update_one(
            {"funder": funder},
            {"$set": {
                "funder": funder,
                "context": context,
                "cached_at": datetime.now(tz=timezone.utc).isoformat(),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.debug("Failed to cache funder context for %s: %s", funder, e)

    return _validate_funder_context(funder, context)


async def _perplexity_funder_research(
    funder: str,
    api_key: str = "",
    gateway_api_key: str = "",
    gateway_url: str = "https://ai-gateway.vercel.sh/v1",
) -> str:
    """Funder research via Perplexity Sonar. Prefers AI Gateway, falls back to direct."""
    if not api_key and not gateway_api_key:
        return "No funder research available (no API key)."
    if api_health.is_exhausted("perplexity"):
        logger.debug("Skipping Perplexity funder research (exhausted) for %s", funder)
        return f"Funder research unavailable for {funder} (API quota exhausted)."

    user_msg = (
        f"What are {funder}'s current funding priorities, typical grant sizes, "
        f"and recent awards? What org types and sectors do they fund? "
        f"Is India or global applicants typically eligible? 120 words max."
    )

    # Prefer AI Gateway (routes Perplexity via OpenAI-compat API)
    if gateway_api_key:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=gateway_api_key, base_url=gateway_url)

        async def _do_gw() -> str:
            response = await client.chat.completions.create(
                model=ANALYST_FUNDER,
                max_tokens=512,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.choices[0].message.content or ""

        try:
            result = await retry_async(_do_gw, retries=3, base_delay=2.0, label=f"perplexity-funder-gw:{funder}", service="perplexity")
        except CreditExhaustedError:
            return f"Funder research unavailable for {funder} (API quota exhausted)."
        if result:
            api_health.record_success("perplexity")
        return result or f"Funder research unavailable for {funder}."

    # Fallback: direct Perplexity API
    payload = {
        "model": ANALYST_FUNDER,
        "messages": [{"role": "user", "content": user_msg}],
        "search_recency_filter": "year",
    }

    async def _do() -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    try:
        result = await retry_async(_do, retries=3, base_delay=2.0, label=f"perplexity-funder:{funder}", service="perplexity")
    except CreditExhaustedError:
        return f"Funder research unavailable for {funder} (API quota exhausted)."
    if result:
        api_health.record_success("perplexity")
    return result or f"Funder research unavailable for {funder}."


# ── Minimal HTTP fetch for analyst-side scraping ──────────────────────────────

async def _fetch_url_content(url: str) -> str:
    """Plain HTTP GET, used only for fetching past-winners pages — no Jina needed."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AltCarbonBot/1.0)"},
            )
            r.raise_for_status()
            return r.text[:60_000]
    except Exception as e:
        logger.debug("_fetch_url_content failed for %s: %s", url[:60], e)
        return ""


# ── Past winners scraping (runs concurrently with deep analysis) ───────────────

# Common URL path suffixes that funder sites use for winner/awardee pages.
# We'll try appending these to the source_url if no past_winners_url was found.
_WINNERS_PATH_CANDIDATES = (
    "/awardees", "/winners", "/grantees", "/funded-projects", "/portfolio",
    "/past-grants", "/past-awardees", "/recipients", "/funded-companies",
    "/projects", "/cohort",
)


async def _scrape_past_winners(grant: Dict) -> Dict:
    """Extract past grant winners by:
    1. Running LLM extraction on already-fetched raw_content (free — no HTTP)
    2. If a past_winners_url is found or hinted at, fetch that page and re-extract

    Returns a winners dict merged into deep_analysis.past_winners.
    Never raises — on any failure returns an empty result dict.
    """
    title      = grant.get("title") or grant.get("grant_name", "")
    funder     = grant.get("funder", "")
    source_url = grant.get("source_url") or grant.get("url", "")
    content    = (grant.get("raw_content") or "")[:10_000]

    empty = {
        "past_winners_url": None, "winners": [], "total_winners_found": 0,
        "altcarbon_comparable_count": 0,
        "funder_pattern": "No past winner data found.",
        "altcarbon_fit_verdict": "unknown", "strategic_note": None,
    }

    if not content:
        return empty

    async def _extract(c: str, src: str) -> Dict:
        _cn = _get_company_name()
        prompt = WINNERS_EXTRACTION_PROMPT.format(
            company_name=_cn,
            title=title, funder=funder, source_url=src, content=c
        )
        raw = await chat(
            prompt, model=ANALYST_LIGHT, max_tokens=2048,
            system=WINNERS_EXTRACTION_SYSTEM.format(company_name=_cn),
        )
        result = parse_json_safe(raw)
        return result if isinstance(result, dict) else {}

    try:
        # ── Pass 1: scan raw_content (already in memory — no HTTP) ──────────
        result = await _extract(content, source_url)

        winners_found  = result.get("winners") or []
        hint_url       = (
            result.get("past_winners_url")
            or grant.get("past_winners_url")    # set by scout extraction
        )

        # ── Pass 2: fetch dedicated winners page if hinted ──────────────────
        # Either the LLM found a direct URL, or we probe common path suffixes.
        if not winners_found and source_url:
            candidates = (
                [hint_url] if hint_url
                else [source_url.rstrip("/") + p for p in _WINNERS_PATH_CANDIDATES]
            )
            for candidate_url in candidates[:4]:   # cap to 4 probes
                page = await _fetch_url_content(candidate_url)
                if len(page) < 300:
                    continue
                result2 = await _extract(page[:10_000], candidate_url)
                if result2.get("winners"):
                    result = result2
                    result["past_winners_url"] = candidate_url
                    winners_found = result["winners"]
                    logger.info(
                        "Past winners found at probed URL %s (%d winners)",
                        candidate_url[:60], len(winners_found),
                    )
                    break

        n = len(winners_found)
        comparable = result.get("altcarbon_comparable_count", 0)
        logger.info(
            "Past winners for '%s': %d found, %d comparable to AltCarbon",
            title[:50], n, comparable,
        )
        return result or empty

    except Exception as e:
        logger.warning(
            "Past winners scraping failed for %s: %s", grant.get("url", "")[:60], e
        )
        return empty


# ── Deep research (second LLM pass — pursue/watch grants only) ────────────────

def _company_context_section(company_context: str) -> str:
    """Build the company context section for prompts. Empty if no context."""
    if not (company_context or "").strip():
        return ""
    company_name = _get_company_name()
    return (
        f"{company_name} internal knowledge (from Notion/Drive — use for eligibility and strategic angle):\n"
        f"{company_context.strip()[:4000]}\n\n"
    )


async def _deep_research_grant(
    grant: Dict,
    funder_context: str,
    company_context: str = "",
) -> Dict:
    """Run a thorough second-pass analysis on a grant that passed scoring.

    Uses up to 10,000 chars of full content (vs 6,000 for scoring) and asks
    Claude to act like a grant advisor reading the full RFP — extracting
    requirements, eligibility checklist, evaluation criteria, application
    sections, key dates, funding terms, red flags, and strategic tips.

    Results are cached in MongoDB (deep_research_cache, 7-day TTL) keyed by url_hash.
    Returns a dict stored in grants_scored.deep_analysis.
    Failures return a minimal error dict — never raises.
    """
    # ── Check cache first ────────────────────────────────────────────────────
    url_hash = grant.get("url_hash", "")
    if url_hash:
        try:
            from backend.db.mongo import get_db
            cache_col = get_db()["deep_research_cache"]
            cached = await cache_col.find_one({"url_hash": url_hash})
            if cached and cached.get("result"):
                # Enforce 7-day TTL — stale cache entries are ignored
                cached_at = cached.get("cached_at")
                if cached_at:
                    if isinstance(cached_at, str):
                        cached_at = datetime.fromisoformat(cached_at)
                    age = datetime.now(tz=timezone.utc) - cached_at
                    if age > timedelta(days=7):
                        logger.debug("Deep research cache expired (%s days): %s", age.days, grant.get("url", "")[:60])
                    else:
                        logger.debug("Deep research cache hit: %s", grant.get("url", "")[:60])
                        return cached["result"]
                else:
                    # Legacy entry without cached_at — use it but log
                    logger.debug("Deep research cache hit (no timestamp): %s", grant.get("url", "")[:60])
                    return cached["result"]
        except Exception:
            pass

    # Use as much content as available for deeper analysis
    full_content = (grant.get("raw_content") or "")[:10_000]
    themes_str = ", ".join(grant.get("themes_detected") or [])

    _cn = _get_company_name()
    prompt = DEEP_ANALYSIS_PROMPT.format(
        company_name=_cn,
        company_profile=_get_company_profile(),
        title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", ""),
        source_url=grant.get("source_url") or grant.get("url", ""),
        application_url=grant.get("application_url") or grant.get("url", ""),
        amount=grant.get("amount") or "Not specified",
        currency=grant.get("currency", "USD"),
        deadline=grant.get("deadline") or "Not specified",
        geography=grant.get("geography") or "Unknown",
        eligibility=grant.get("eligibility") or "Not specified",
        themes=themes_str or grant.get("themes_text") or "None detected",
        notes=grant.get("notes") or "None",
        content=full_content,
        funder_context=funder_context,
        company_context_section=_company_context_section(company_context),
    )

    try:
        # Run deep analysis (Sonnet) and past-winners scraping (Haiku) concurrently.
        # _scrape_past_winners never raises, so gather is safe without return_exceptions.
        deep_task    = chat(prompt, model=ANALYST_HEAVY, max_tokens=4096, system=DEEP_ANALYSIS_SYSTEM.format(company_name=_cn))
        winners_task = _scrape_past_winners(grant)

        raw_text, winners_data = await asyncio.gather(deep_task, winners_task)

        result = parse_json_safe(raw_text)
        if result and isinstance(result, dict):
            result["past_winners"] = winners_data   # always present, may be empty
            logger.debug(
                "Deep research + winners complete for %s (winners found: %d)",
                grant.get("url", "")[:60],
                len((winners_data or {}).get("winners", [])),
            )
            # Cache the result (7-day TTL via MongoDB index)
            if url_hash:
                try:
                    from backend.db.mongo import get_db
                    cache_col = get_db()["deep_research_cache"]
                    await cache_col.update_one(
                        {"url_hash": url_hash},
                        {"$set": {
                            "url_hash": url_hash,
                            "result": result,
                            "cached_at": datetime.now(tz=timezone.utc),
                        }},
                        upsert=True,
                    )
                except Exception:
                    pass
            return result

        logger.warning("Deep research returned unexpected structure for %s", grant.get("url"))
    except Exception as e:
        logger.warning("Deep research failed for %s: %s", grant.get("url", "")[:60], e)

    return {"error": "Deep research unavailable", "url": grant.get("url", "")}


# ── Mandatory field checks for shortlisted grants ─────────────────────────────

_VAGUE_DEADLINES = frozenset({
    "", "not specified", "not mentioned", "n/a", "none", "tbd", "tba",
    "to be announced", "unknown",
})


def _has_concrete_deadline(grant: Dict, deep: Dict) -> bool:
    """Return True if the grant has a usable application deadline."""
    # Check grant-level deadline
    dl = (grant.get("deadline") or "").strip().lower()
    if dl and dl not in _VAGUE_DEADLINES:
        return True
    # Check deep analysis key_dates
    kd = (deep or {}).get("key_dates") or {}
    for field in ("application_deadline", "loi_deadline"):
        val = (kd.get(field) or "").strip().lower()
        if val and val not in _VAGUE_DEADLINES and val != "null":
            return True
    return False


def _has_concrete_funding(grant: Dict, deep: Dict) -> bool:
    """Return True if the grant has a usable funding amount / ticket size."""
    # Check max_funding_usd (numeric)
    mf = grant.get("max_funding_usd") or grant.get("max_funding")
    if mf:
        try:
            if float(mf) > 0:
                return True
        except (ValueError, TypeError):
            pass
    # Check textual amount field
    amt = (grant.get("amount") or "").strip().lower()
    if amt and amt not in ("", "not specified", "not mentioned", "n/a", "none",
                           "unknown", "tbd", "varies", "variable"):
        return True
    # Check deep analysis funding_terms (disbursement implies known amount)
    ft = (deep or {}).get("funding_terms") or {}
    if ft.get("disbursement_schedule") and ft["disbursement_schedule"] != "null":
        return True
    return False


async def _extract_missing_mandatory(
    grant: Dict, has_deadline: bool, has_funding: bool
) -> Optional[Dict]:
    """Focused LLM extraction for missing deadline / funding from raw content.

    Returns a patch dict with any found values, or None if nothing recovered.
    """
    content = (grant.get("raw_content") or "")[:8000]
    if not content:
        return None

    fields_needed = []
    if not has_deadline:
        fields_needed.append(
            '"deadline": "<exact application deadline date — e.g. \'April 30, 2026\', \'Rolling\'; null if truly not found>"'
        )
    if not has_funding:
        fields_needed.append(
            '"amount": "<funding amount per applicant — e.g. \'up to $500,000\', \'₹50 lakh\'; null if not found>"'
        )
        fields_needed.append(
            '"max_funding_usd": <integer USD equivalent per applicant; null if not found>'
        )
        fields_needed.append(
            '"currency": "<3-letter code: USD EUR GBP INR; null if not found>"'
        )

    prompt = (
        "You are a grant data extraction specialist. "
        "Search the following grant page content CAREFULLY for the specific fields below. "
        "Look for any dates labelled as deadline, closing date, last date, due date, submission date. "
        "Look for any amounts labelled as grant size, award, funding, ticket size, financial support. "
        "Return ONLY valid JSON — no prose.\n\n"
        f"Grant: {grant.get('grant_name') or grant.get('title', '')}\n"
        f"URL: {grant.get('url', '')}\n\n"
        f"Content:\n{content}\n\n"
        "Return this JSON (null for fields you cannot find):\n"
        "{{\n  " + ",\n  ".join(fields_needed) + "\n}}"
    )

    try:
        raw = await chat(prompt, model=ANALYST_LIGHT, max_tokens=512)
        result = parse_json_safe(raw)
        if not result:
            return None

        patch: Dict = {}
        if not has_deadline and result.get("deadline"):
            dl = str(result["deadline"]).strip().lower()
            if dl not in _VAGUE_DEADLINES and dl != "null":
                patch["deadline"] = result["deadline"]
                logger.info(
                    "Recovered deadline '%s' for %s",
                    result["deadline"], grant.get("url", "")[:60],
                )

        if not has_funding:
            try:
                _mf_val = float(result.get("max_funding_usd") or 0)
            except (ValueError, TypeError):
                _mf_val = 0
            if _mf_val > 0:
                patch["max_funding_usd"] = int(_mf_val)
                patch["max_funding"] = patch["max_funding_usd"]
                if result.get("amount"):
                    patch["amount"] = result["amount"]
                if result.get("currency"):
                    patch["currency"] = result["currency"]
                logger.info(
                    "Recovered funding $%s for %s",
                    patch["max_funding_usd"], grant.get("url", "")[:60],
                )
            elif result.get("amount"):
                amt = str(result["amount"]).strip().lower()
                if amt not in ("", "null", "not specified", "none", "unknown"):
                    patch["amount"] = result["amount"]
                    logger.info(
                        "Recovered amount '%s' for %s",
                        result["amount"], grant.get("url", "")[:60],
                    )

        return patch if patch else None
    except Exception as e:
        logger.debug("Mandatory field extraction failed for %s: %s", grant.get("url", "")[:60], e)
        return None


# ── Core scoring ───────────────────────────────────────────────────────────────

async def _score_grant(
    grant: Dict,
    funder_context: str,
    weights: Dict[str, float],
    min_funding: int,
    company_context: str = "",
) -> Dict:
    """Score a single grant. Returns the full scored document ready for MongoDB."""

    # ── Hard rules ────────────────────────────────────────────────────────────
    disqualified = _apply_hard_rules(grant, min_funding)
    if disqualified:
        return _build_scored_doc(
            grant=grant,
            scores={k: 0 for k in weights},
            weighted_total=0.0,
            action="auto_pass",
            rationale="",
            reasoning=disqualified,
            evidence_found=[],
            evidence_gaps=[],
            red_flags=[disqualified],
            funder_context="",
            scoring_error=False,
        )

    # ── Currency resolution: parse from amount string, then try raw content ──
    # Many grants have currency embedded in the amount field (e.g. "INR 85,000,000")
    # but the currency field is empty. Parse it before scoring.
    _patch_currency_from_amount(grant)

    # If currency is still unknown and there's a stated amount, try to resolve
    # from raw content via an LLM call.
    _currency_gap = False
    hold_reason = _check_hold_conditions(grant)
    if hold_reason:
        logger.info(
            "Unknown currency — attempting resolution from raw content: %s",
            grant.get("url", "")[:80],
        )
        patch = await _resolve_unknown_currency(grant)
        if patch:
            grant.update(patch)
            logger.info(
                "Currency resolved to %s — continuing to score: %s",
                patch["currency"], grant.get("url", "")[:60],
            )
        else:
            # Unresolvable — note it as evidence gap and continue to scoring.
            # The LLM will score funding_amount low when currency is unclear.
            logger.info("Currency unresolvable — scoring anyway: %s", grant.get("url", "")[:80])
            _currency_gap = True

    # ── AI scoring with retry ─────────────────────────────────────────────────
    content_snippet = (grant.get("raw_content") or "")[:6000]   # raised from 4000
    themes_str = ", ".join(grant.get("themes_detected") or [])

    # Normalize funding to USD for the scoring prompt (fix #2/#12).
    # max_funding_usd stores the raw original-currency amount when the LLM
    # extraction puts INR/EUR/etc. directly into the field, so we convert here
    # so the scorer always sees a USD figure and grades funding_amount correctly.
    _raw_funding = grant.get("max_funding_usd") or grant.get("max_funding") or 0
    _score_currency = (grant.get("currency") or "USD").upper()
    if _score_currency != "USD" and _raw_funding and float(_raw_funding) > 0:
        _funding_for_prompt: object = int(_normalize_to_usd(float(_raw_funding), _score_currency))
    else:
        _funding_for_prompt = _raw_funding or "unknown"

    _cn = _get_company_name()
    prompt = SCORING_PROMPT.format(
        company_name=_cn,
        company_profile=_get_company_profile(),
        title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", ""),
        source_url=grant.get("source_url") or grant.get("url", ""),
        application_url=grant.get("application_url") or grant.get("url", ""),
        geography=grant.get("geography") or "Unknown",
        amount=grant.get("amount") or "Not specified",
        currency=grant.get("currency", "USD"),
        deadline=grant.get("deadline") or "Not specified",
        eligibility=grant.get("eligibility") or "Not specified",
        themes=themes_str or grant.get("themes_text") or "None detected",
        notes=grant.get("notes") or "None",
        content=content_snippet,
        funder_context=funder_context,
        max_funding_usd=_funding_for_prompt,
        company_context_section=_company_context_section(company_context),
    )

    scoring = None
    for attempt in range(3):
        try:
            raw_text = await chat(
                prompt,
                model=ANALYST_HEAVY,
                max_tokens=2048,   # was 1024 — raised to prevent JSON truncation
                system=SCORING_SYSTEM.format(company_name=_cn),
            )
            result = parse_json_safe(raw_text)
            if result and "scores" in result:
                scoring = result
                break
            logger.warning(
                "Scoring attempt %d/%d got unexpected structure for %s",
                attempt + 1, 3, grant.get("url"),
            )
        except Exception as e:
            logger.warning(
                "Scoring attempt %d/%d failed for %s: %s",
                attempt + 1, 3, grant.get("url"), e,
            )
            if attempt < 2:
                await asyncio.sleep(2.0 * (2 ** attempt))

    scoring_error = scoring is None
    if scoring_error:
        logger.error("All scoring attempts failed for %s — using defaults (3s)", grant.get("url"))
        scoring = {
            "scores": {k: 3 for k in weights},
            "evidence_found": [],
            "evidence_gaps": ["Automated scoring failed — manual review required"],
            "reasoning": "Scoring failed after 3 attempts. Manual review needed.",
            "rationale": "",
            "red_flags": ["Scoring error"],
        }

    scores = scoring.get("scores", {})
    # Clamp scores to 1–10 range (guard against model returning out-of-range values)
    scores = {k: max(1, min(10, int(scores.get(k, 5)))) for k in weights}
    weighted_total = sum(scores[dim] * weight for dim, weight in weights.items())

    # Red flag penalty: each red flag reduces weighted_total by a configurable amount
    from backend.config.settings import get_settings
    s = get_settings()
    red_flags = scoring.get("red_flags") or []
    if red_flags and not scoring_error:
        penalty = min(len(red_flags) * s.red_flag_penalty, s.red_flag_max_penalty)
        weighted_total = max(0.0, weighted_total - penalty)
        logger.debug(
            "Red flag penalty: -%0.1f (%d flags) for %s → %.2f",
            penalty, len(red_flags), grant.get("url", "")[:60], weighted_total,
        )

    # Threshold-based action (model's suggestion is not used — thresholds are authoritative)
    if weighted_total >= s.pursue_threshold:
        action = "pursue"
    elif weighted_total >= s.watch_threshold:
        action = "watch"
    else:
        action = "auto_pass"

    # ── Deep research (second pass — pursue/watch only, not auto_pass) ───────
    # Runs concurrently with nothing else at this point — safe to await directly.
    deep_analysis: Dict = {}
    if action in ("pursue", "watch") and not scoring_error:
        logger.info(
            "Running deep research for %s grant: %s",
            action, (grant.get("grant_name") or grant.get("title", ""))[:60],
        )
        deep_analysis = await _deep_research_grant(
            grant, funder_context, company_context=company_context
        )

    # ── Mandatory fields gate for shortlisted grants ──────────────────────
    # Pursue/watch grants MUST have a concrete deadline and funding amount.
    # If missing after deep research, attempt enrichment from the grant page.
    # If still missing, demote to hold for manual review.
    if action in ("pursue", "watch") and not scoring_error:
        has_deadline = _has_concrete_deadline(grant, deep_analysis)
        has_funding = _has_concrete_funding(grant, deep_analysis)

        if not has_deadline or not has_funding:
            # Step 1: Focused extraction from raw content already in DB
            patch = await _extract_missing_mandatory(grant, has_deadline, has_funding)
            if patch:
                grant.update(patch)
                has_deadline = has_deadline or bool(patch.get("deadline"))
                has_funding = has_funding or bool(patch.get("max_funding_usd"))

        if not has_deadline or not has_funding:
            # Step 2: Fetch the grant page live and extract missing fields
            # Primary: Exa (clean text extraction), Fallback: HTTP + HTML strip
            try:
                grant_url = grant.get("url") or grant.get("source_url") or ""
                if grant_url:
                    page_text = ""

                    # Try Exa first — returns clean extracted text
                    from backend.config.settings import get_settings as _gs
                    _exa_key = _gs().exa_api_key
                    if _exa_key:
                        try:
                            from exa_py import Exa
                            exa = Exa(api_key=_exa_key)
                            exa_result = await asyncio.to_thread(
                                exa.get_contents, grant_url, text={"max_characters": 30000}
                            )
                            if exa_result.results:
                                page_text = (getattr(exa_result.results[0], "text", "") or "").strip()
                                if page_text:
                                    logger.debug("Enrichment: Exa fetched %d chars for %s", len(page_text), grant_url[:60])
                        except Exception as _exa_err:
                            logger.debug("Exa enrichment failed for %s: %s", grant_url[:60], _exa_err)

                    # Fallback: plain HTTP
                    if not page_text:
                        import httpx
                        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as _http:
                            r = await _http.get(grant_url, headers={"User-Agent": "Mozilla/5.0"})
                            if r.status_code == 200:
                                import re as _re
                                page_text = _re.sub(r'<[^>]+>', ' ', r.text[:30000])
                                page_text = _re.sub(r'\s+', ' ', page_text).strip()

                    if page_text and len(page_text) > 100:
                        from backend.utils.llm import chat as _llm_chat
                        enrich_prompt = (
                            f"Extract from this grant page:\n{page_text[:6000]}\n\n"
                            f"Return JSON: {{\"deadline\": \"YYYY-MM-DD or null\", "
                            f"\"funding_amount\": \"text or null\", \"max_funding_usd\": number_or_null, "
                            f"\"application_status\": \"open|closed|rolling|cohort_running|unknown\", "
                            f"\"eligibility\": \"1-2 sentences or null\", "
                            f"\"description\": \"2-3 sentences or null\"}}"
                        )
                        raw_enrich = await _llm_chat(enrich_prompt, model="claude-haiku-4-5-20251001", max_tokens=300, temperature=0)
                        clean = raw_enrich.strip()
                        if clean.startswith("```"):
                            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
                        enriched = json.loads(clean.strip())

                        # Apply enriched fields
                        if enriched.get("deadline") and not has_deadline:
                            grant["deadline"] = enriched["deadline"]
                            has_deadline = True
                        if enriched.get("max_funding_usd") and not has_funding:
                            grant["max_funding_usd"] = enriched["max_funding_usd"]
                            grant["amount"] = enriched.get("funding_amount", "")
                            has_funding = True
                        if enriched.get("eligibility"):
                            grant["eligibility"] = enriched["eligibility"]
                        if enriched.get("description"):
                            grant["description"] = enriched["description"]

                        # Detect closed/cohort applications
                        app_status = enriched.get("application_status", "unknown")
                        if app_status in ("closed", "cohort_running"):
                            logger.info(
                                "Grant application %s: %s",
                                app_status,
                                (grant.get("grant_name") or "")[:60],
                            )
                            action = "auto_pass"
                            scoring["red_flags"] = list(scoring.get("red_flags", []))
                            scoring["red_flags"].append(
                                f"Application {app_status} — "
                                + ("cohort already selected and running" if app_status == "cohort_running" else "applications no longer accepted")
                            )

                        logger.info("Enriched grant from page: deadline=%s, funding=%s, status=%s",
                                    enriched.get("deadline"), enriched.get("max_funding_usd"), app_status)
            except Exception as e:
                logger.debug("Grant page enrichment failed: %s", e)

        # Only demote to hold if FUNDING is missing.
        # Deadline is NOT mandatory — many grants are rolling/always-open.
        # Missing deadline is noted as evidence gap but doesn't block triage.
        if not has_deadline:
            evidence_gaps_list = list(scoring.get("evidence_gaps", []))
            evidence_gaps_list.append("No published application deadline — verify if rolling or check grant page")
            scoring["evidence_gaps"] = evidence_gaps_list

        if not has_funding and action != "auto_pass":
            # Missing funding is an evidence gap, not a blocker.
            # The grant proceeds to triage with a note so humans can decide.
            evidence_gaps_list = list(scoring.get("evidence_gaps", []))
            evidence_gaps_list.append("No published funding amount / ticket size — verify on grant page")
            scoring["evidence_gaps"] = evidence_gaps_list
            logger.info(
                "Missing funding for %s grant — noting as evidence gap (not holding): %s",
                action, (grant.get("grant_name") or grant.get("title", ""))[:60],
            )

    # Append currency gap note if currency was unresolvable
    if _currency_gap:
        evidence_gaps_list = list(scoring.get("evidence_gaps", []))
        evidence_gaps_list.append("Currency unknown — funding amount could not be verified")
        scoring["evidence_gaps"] = evidence_gaps_list

    return _build_scored_doc(
        grant=grant,
        scores=scores,
        weighted_total=round(weighted_total, 2),
        action=action,
        rationale=scoring.get("rationale", ""),
        reasoning=scoring.get("reasoning", ""),
        evidence_found=scoring.get("evidence_found", []),
        evidence_gaps=scoring.get("evidence_gaps", []),
        red_flags=scoring.get("red_flags", []),
        funder_context=funder_context,
        scoring_error=scoring_error,
        deep_analysis=deep_analysis,
    )


def _build_scored_doc(
    grant: Dict,
    scores: Dict,
    weighted_total: float,
    action: str,
    rationale: str,
    reasoning: str,
    evidence_found: List,
    evidence_gaps: List,
    red_flags: List,
    funder_context: str,
    scoring_error: bool,
    deep_analysis: Optional[Dict] = None,
) -> Dict:
    """Build the full document written to grants_scored."""
    # Status mapping:
    #   auto_pass → skipped (failed hard rules or low score)
    #   pursue    → shortlisted (high priority)
    #   watch     → shortlisted (lower priority, same queue as pursue)
    #   everything else → triage (awaiting human review)
    status = "auto_pass" if action == "auto_pass" else "triage"

    grant_name = grant.get("grant_name") or grant.get("title") or ""

    # Compute days_to_deadline and deadline_urgent for proactive alerting (fix #17).
    # deadline_urgent=True triggers a UI badge when ≤ 30 days remain.
    _deadline_dt = parse_deadline(grant.get("deadline"))
    _now = datetime.now(tz=timezone.utc)
    if _deadline_dt and _deadline_dt > _now:
        days_to_deadline: Optional[int] = (_deadline_dt - _now).days
        deadline_urgent: bool = days_to_deadline <= _get_settings().deadline_urgent_days
    else:
        days_to_deadline = None
        deadline_urgent = False

    return {
        # ── Identity ──────────────────────────────────────────────────────────
        "raw_grant_id":   str(grant.get("_id", "")),
        "url_hash":       grant.get("url_hash", ""),        # for dedup on future runs
        "content_hash":   grant.get("content_hash", ""),    # for cross-pipeline dedup
        "grant_name":     grant_name,                       # NEW: explicit grant_name field
        "title":          grant_name,                       # kept for backward compat
        "funder":         grant.get("funder", ""),
        "grant_type":     grant.get("grant_type", "grant"),
        # ── URLs ──────────────────────────────────────────────────────────────
        "url":             grant.get("url", ""),
        "source_url":      grant.get("source_url") or grant.get("url", ""),
        "application_url": grant.get("application_url") or grant.get("url", ""),
        # ── Key details ───────────────────────────────────────────────────────
        "amount":          grant.get("amount", ""),
        "max_funding":     grant.get("max_funding"),
        "max_funding_usd": grant.get("max_funding_usd") or grant.get("max_funding"),
        "currency":        grant.get("currency", "USD"),
        "deadline":        grant.get("deadline"),
        "geography":       grant.get("geography", ""),
        "eligibility":     grant.get("eligibility", ""),
        "themes_detected": grant.get("themes_detected", []),
        "themes_text":     grant.get("themes_text", ""),
        "notes":             grant.get("notes", ""),
        # ── Opportunity details (deep analysis overrides scout extraction) ────
        "about_opportunity": (
            (deep_analysis or {}).get("opportunity_summary")
            or grant.get("about_opportunity", "")
        ),
        "eligibility_details": grant.get("eligibility_details", ""),
        "application_process": (
            (deep_analysis or {}).get("application_process_detailed")
            or grant.get("application_process", "")
        ),
        # ── Contact & resources (extracted from deep analysis) ────────────────
        "contact_info":    (deep_analysis or {}).get("contact") or {},
        "resources":       (deep_analysis or {}).get("resources") or {},
        "last_verified_date": grant.get("last_verified_date", ""),
        "past_winners_url":  grant.get("past_winners_url"),    # hint for analyst scraper
        # ── Past winners (top-level for frontend — also nested in deep_analysis) ─
        "past_winners":    (deep_analysis or {}).get("past_winners") or {},
        # ── Scoring ───────────────────────────────────────────────────────────
        "scores":          scores,
        "weighted_total":  weighted_total,
        # ── Analysis ──────────────────────────────────────────────────────────
        "rationale":       rationale,
        "reasoning":       reasoning,
        "evidence_found":  evidence_found,
        "evidence_gaps":   evidence_gaps,
        "red_flags":       red_flags,
        "funder_context":  funder_context,
        # ── Status ────────────────────────────────────────────────────────────
        "recommended_action": action,
        "status":          status,                          # FIXED: auto_pass → "auto_pass"
        "scored_at":       datetime.now(tz=timezone.utc).isoformat(),
        # ── Deadline alerting ─────────────────────────────────────────────────
        "days_to_deadline": days_to_deadline,   # int days remaining, or None
        "deadline_urgent":  deadline_urgent,    # True when ≤ 30 days remain
        # ── Human override (initialized False; updated durably via /resume/triage) ─
        "human_override":   False,
        "override_reason":  None,
        "override_at":      None,
        # ── Quality flags ─────────────────────────────────────────────────────
        "scoring_error":       scoring_error,
        "deep_analysis_error": bool(deep_analysis and deep_analysis.get("error")),
        # ── Deep research brief (pursue/watch grants only) ────────────────────
        "deep_analysis":   deep_analysis or {},
    }


# ── Analyst agent ──────────────────────────────────────────────────────────────

class AnalystAgent:
    def __init__(
        self,
        perplexity_api_key: str = "",
        gateway_api_key: str = "",
        gateway_url: str = "https://ai-gateway.vercel.sh/v1",
        weights: Optional[Dict[str, float]] = None,
        min_funding: int = 3_000,
    ):
        self.perplexity_key = perplexity_api_key
        self.gateway_key = gateway_api_key
        self.gateway_url = gateway_url
        self.weights = weights or DEFAULT_WEIGHTS
        self.min_funding = min_funding

    async def run(self, raw_grants: List[Dict], company_profile: str = "") -> List[Dict]:
        if not raw_grants:
            logger.info("Analyst: no grants to score")
            return []

        import traceback as _tb

        _run_start = datetime.now(timezone.utc)

        try:
            return await self._run_inner(raw_grants, company_profile=company_profile)
        except Exception as exc:
            elapsed = (datetime.now(timezone.utc) - _run_start).total_seconds()
            try:
                from backend.integrations.notion_sync import log_error, log_agent_run
                await log_error(
                    agent="analyst",
                    error=exc,
                    tb=_tb.format_exc(),
                    severity="Critical",
                )
                await log_agent_run(
                    agent="analyst",
                    status="Failed",
                    trigger="Pipeline",
                    started_at=_run_start,
                    duration_seconds=elapsed,
                    errors=1,
                    summary=f"Analyst failed on {len(raw_grants)} grants: {str(exc)[:200]}",
                )
            except Exception:
                logger.debug("Notion error sync skipped (analyst failure)", exc_info=True)
            raise

    async def _run_inner(self, raw_grants: List[Dict], company_profile: str = "") -> List[Dict]:
        logger.info("Analyst: received %d grants to process", len(raw_grants))

        # ── Skip already-scored grants (idempotency) ─────────────────────────
        col = grants_scored()
        existing_url_hashes: set = set()
        existing_raw_ids: set = set()

        async for doc in col.find(
            {},
            {"url_hash": 1, "raw_grant_id": 1, "url": 1},
        ):
            if doc.get("url_hash"):
                existing_url_hashes.add(doc["url_hash"])
            if doc.get("raw_grant_id"):
                existing_raw_ids.add(doc["raw_grant_id"])

        to_score = []
        skipped = 0
        for g in raw_grants:
            url_h = g.get("url_hash", "")
            raw_id = str(g.get("_id", ""))
            if url_h and url_h in existing_url_hashes:
                logger.debug("Already scored (url_hash match): %s", g.get("title", "")[:50])
                skipped += 1
                continue
            if raw_id and raw_id in existing_raw_ids:
                logger.debug("Already scored (raw_grant_id match): %s", g.get("title", "")[:50])
                skipped += 1
                continue
            to_score.append(g)

        logger.info(
            "Analyst: %d to score, %d already in grants_scored (skipped)",
            len(to_score), skipped,
        )

        if not to_score:
            return []

        # ── Pre-filter: hard rules only ───────────────────────────────────────
        # Unknown-currency grants are NOT pre-bucketed here — they go to
        # passing_grants so they get Perplexity enrichment and currency resolution
        # is attempted inside _score_grant() before any hold decision is made.
        passing_grants = []
        auto_pass_grants = []
        for g in to_score:
            reason = _apply_hard_rules(g, self.min_funding)
            if reason:
                g["_hard_fail_reason"] = reason
                auto_pass_grants.append(g)
            else:
                passing_grants.append(g)

        unknown_currency_count = sum(
            1 for g in passing_grants if _check_hold_conditions(g)
        )
        logger.info(
            "Analyst: %d pass hard rules (%d with unknown currency → will attempt resolution), "
            "%d auto-pass immediately",
            len(passing_grants), unknown_currency_count, len(auto_pass_grants),
        )

        # ── Company knowledge (Notion/Drive) for Analyst prompts ───────────────
        # Prefer company_profile from state (loaded by company_brain_load node).
        # Fall back to internal loading chain for backward compat (direct agent.run() calls).
        from backend.agents.company_brain import _load_static_profile
        base_company_context = ""
        _brain_agent = None

        if company_profile:
            base_company_context = company_profile
            logger.info("Analyst: using pre-loaded company profile (%d chars)", len(base_company_context))
            # Still create brain agent for per-grant vector search
            try:
                from backend.agents.company_brain import CompanyBrainAgent
                from backend.config.settings import get_settings
                _s = get_settings()
                _brain_agent = CompanyBrainAgent(
                    notion_token=_s.notion_token,
                    google_refresh_token=_s.google_refresh_token,
                    google_client_id=_s.google_client_id,
                    google_client_secret=_s.google_client_secret,
                )
            except Exception as e:
                logger.debug("Brain agent init skipped (per-grant search unavailable): %s", e)
        else:
            try:
                from backend.agents.company_brain import CompanyBrainAgent
                from backend.config.settings import get_settings
                _s = get_settings()
                _brain_agent = CompanyBrainAgent(
                    notion_token=_s.notion_token,
                    google_refresh_token=_s.google_refresh_token,
                    google_client_id=_s.google_client_id,
                    google_client_secret=_s.google_client_secret,
                )
                base_company_context = await _brain_agent.get_company_overview(max_chars=3000)
                if base_company_context:
                    logger.info("Analyst: loaded %d chars base company knowledge", len(base_company_context))
            except Exception as e:
                logger.debug("Company knowledge load skipped: %s", e)
            if not base_company_context:
                base_company_context = _load_static_profile()[:3000]
                if base_company_context:
                    logger.info("Analyst: using static AltCarbon profile (%d chars)", len(base_company_context))

        async def _get_grant_knowledge(grant: Dict) -> str:
            """Get grant-specific company knowledge via vector search.

            Combines the base company profile with vector-retrieved chunks
            that are relevant to this specific grant's themes and title.
            """
            if not _brain_agent:
                return base_company_context

            try:
                title = grant.get("title") or grant.get("grant_name", "")
                funder = grant.get("funder", "")
                themes = grant.get("themes_detected") or []
                eligibility = grant.get("eligibility", "")
                query_text = f"{title} {funder} {eligibility} {' '.join(themes)}"
                chunks = await _brain_agent.query(
                    query_text, themes=themes or None, top_k=6,
                )
                if chunks:
                    chunk_texts = [
                        f"[{c.get('doc_type', 'misc')} | {c.get('source_title', '')}]\n"
                        f"{c.get('content', '')}"
                        for c in chunks
                    ]
                    vector_context = "\n---\n".join(chunk_texts)[:3000]
                    return f"{base_company_context}\n\n--- Relevant knowledge for this grant ---\n{vector_context}"
            except Exception as e:
                logger.debug("Vector search for grant '%s' failed: %s",
                             grant.get("title", ""), e)
            return base_company_context

        # ── Perplexity funder enrichment (only for passing grants) ────────────
        unique_funders = list({g.get("funder", "") for g in passing_grants})
        funder_sem = asyncio.Semaphore(3)

        async def enrich_funder(funder: str) -> tuple:
            async with funder_sem:
                ctx = await _get_funder_context(
                    funder,
                    perplexity_key=self.perplexity_key,
                    gateway_api_key=self.gateway_key,
                    gateway_url=self.gateway_url,
                )
                return funder, ctx

        funder_contexts: Dict[str, str] = {}
        if unique_funders and (self.perplexity_key or self.gateway_key):
            results = await asyncio.gather(*(enrich_funder(f) for f in unique_funders))
            funder_contexts = dict(results)

        # ── Score all grants (concurrent, max 5 LLM calls at once) ───────────
        score_sem = asyncio.Semaphore(5)

        async def score_one(grant: Dict) -> Dict:
            async with score_sem:
                funder = grant.get("funder", "")
                ctx = funder_contexts.get(funder, "No funder research available.")
                # Per-grant vector knowledge retrieval
                company_context = await _get_grant_knowledge(grant)
                return await _score_grant(
                    grant, ctx, self.weights, self.min_funding,
                    company_context=company_context,
                )

        async def score_auto_pass(grant: Dict) -> Dict:
            """Build auto_pass scored doc without calling the LLM."""
            return _build_scored_doc(
                grant=grant,
                scores={k: 0 for k in self.weights},
                weighted_total=0.0,
                action="auto_pass",
                rationale="",
                reasoning=grant.get("_hard_fail_reason", "Failed hard eligibility rules"),
                evidence_found=[],
                evidence_gaps=[],
                red_flags=[grant.get("_hard_fail_reason", "")],
                funder_context="",
                scoring_error=False,
            )

        all_tasks = (
            [score_one(g) for g in passing_grants] +
            [score_auto_pass(g) for g in auto_pass_grants]
        )
        scored: List[Dict] = list(await asyncio.gather(*all_tasks))

        # ── Upsert to grants_scored (keyed on url_hash) ───────────────────────
        raw_col = grants_raw()
        saved_count = 0
        for s in scored:
            try:
                key = (
                    {"url_hash": s["url_hash"]}
                    if s.get("url_hash")
                    else {"raw_grant_id": s["raw_grant_id"]}
                )
                await col.update_one(
                    key,
                    {"$set": s},
                    upsert=True,
                )
                saved_count += 1

                # Sync to Notion Mission Control
                try:
                    from backend.integrations.notion_sync import sync_scored_grant
                    await sync_scored_grant(s)
                except Exception:
                    logger.debug("Notion sync skipped for grant %s", s.get("url"), exc_info=True)

            except Exception as e:
                logger.warning("Failed to upsert scored grant %s: %s", s.get("url"), e)

        # Mark raw grants as processed (both scored AND skipped-as-already-scored)
        all_to_mark = list(to_score) + list(raw_grants)
        seen_ids = set()
        for g in all_to_mark:
            gid = g.get("_id")
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                try:
                    await raw_col.update_one(
                        {"_id": gid},
                        {"$set": {"processed": True}},
                    )
                except Exception:
                    pass

        # ── Rank and summarize ────────────────────────────────────────────────
        ranked = sorted(scored, key=lambda x: x["weighted_total"], reverse=True)
        pursue_count = sum(1 for g in ranked if g["recommended_action"] == "pursue")
        watch_count  = sum(1 for g in ranked if g["recommended_action"] == "watch")
        pass_count   = sum(1 for g in ranked if g["recommended_action"] == "auto_pass")
        hold_count   = sum(1 for g in ranked if g["recommended_action"] == "hold")
        top_score    = ranked[0]["weighted_total"] if ranked else 0.0

        logger.info(
            "Analyst complete: %d scored (%d pursue, %d watch, %d auto_pass, %d hold), "
            "top_score=%.2f, %d skipped as already-scored",
            len(ranked), pursue_count, watch_count, pass_count, hold_count, top_score, skipped,
        )

        # Write to audit_logs collection (not just LangGraph state)
        await audit_logs().insert_one({
            "node": "analyst",
            "action": f"Scoring complete: {len(ranked)} grants",
            "grants_scored": len(ranked),
            "pursue_count": pursue_count,
            "watch_count": watch_count,
            "auto_pass_count": pass_count,
            "hold_count": hold_count,
            "skipped_already_scored": skipped,
            "top_score": top_score,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })

        # ── Notion Mission Control sync ──────────────────────────────────
        try:
            from backend.integrations.notion_sync import log_agent_run
            await log_agent_run(
                agent="analyst",
                status="Completed",
                trigger="Pipeline",
                started_at=datetime.now(timezone.utc),
                grants_scored=len(ranked),
                errors=0,
                summary=f"Scored {len(ranked)} grants: {pursue_count} pursue, "
                        f"{watch_count} watch, {pass_count} auto_pass, {hold_count} hold. "
                        f"Top score: {top_score:.2f}. {skipped} skipped (already scored).",
            )
        except Exception:
            logger.debug("Notion sync skipped (analyst run)", exc_info=True)

        return ranked


async def analyst_node(state: GrantState) -> Dict:
    """LangGraph node: score all raw_grants and return scored_grants."""
    from backend.config.settings import get_settings
    s = get_settings()

    cfg_doc = await agent_config().find_one({"agent": "analyst"}) or {}
    weights = cfg_doc.get("scoring_weights") or DEFAULT_WEIGHTS
    min_funding = cfg_doc.get("min_funding", s.min_grant_funding)

    agent = AnalystAgent(
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        weights=weights,
        min_funding=min_funding,
    )

    raw_grants = state.get("raw_grants", [])
    company_profile = state.get("company_profile", "")
    scored = await agent.run(raw_grants, company_profile=company_profile)

    pursue_count = sum(1 for g in scored if g["recommended_action"] == "pursue")
    audit_entry = {
        "node": "analyst",
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "grants_scored": len(scored),
        "pursue_count": pursue_count,
    }
    return {
        "scored_grants": scored,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }


async def notify_triage_node(state: GrantState) -> Dict:
    """LangGraph node: mark scored grants ready for human triage, then pause."""
    triage_count = sum(
        1 for g in state.get("scored_grants", [])
        if g.get("status") == "triage"
    )
    audit_entry = {
        "node": "notify_triage",
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "triage_count": triage_count,
        "message": f"{triage_count} grants ready for human triage review",
    }
    await audit_logs().insert_one({
        **audit_entry,
        "action": audit_entry["message"],
        "created_at": audit_entry["ts"],
    })
    return {"audit_log": state.get("audit_log", []) + [audit_entry]}
