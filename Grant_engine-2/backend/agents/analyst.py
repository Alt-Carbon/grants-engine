"""Analyst Agent — scores grants against AltCarbon's mission and surfaces ranked list.

Flow per grant:
  1. Check if grant already exists in grants_scored (skip if so — idempotent)
  2. Apply hard eligibility rules → auto_pass immediately if any fail
  3. Perplexity funder enrichment — ONLY for grants that passed hard rules
     (cached per funder in MongoDB for 7 days to reduce API spend)
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
from backend.utils.llm import chat, SONNET
from backend.utils.parsing import parse_json_safe, retry_async

logger = logging.getLogger(__name__)

# ── Default scoring weights (must sum to 1.0) ─────────────────────────────────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "theme_alignment":        0.25,
    "eligibility_confidence": 0.20,
    "funding_amount":         0.20,
    "deadline_urgency":       0.15,
    "geography_fit":          0.10,
    "competition_level":      0.10,
}

# ── Scoring prompt ─────────────────────────────────────────────────────────────
SCORING_SYSTEM = (
    "You are an expert grant analyst for AltCarbon, a climate technology startup based in India. "
    "Respond ONLY with valid JSON — no prose, no markdown fences, no explanation before or after."
)

SCORING_PROMPT = """AltCarbon's five focus themes:
1. Climatetech — carbon removal, MRV, net-zero technology
2. Agritech — soil carbon, precision agriculture, farmer tech
3. AI for Sciences — AI applied to environmental and scientific problems
4. Applied Earth Sciences — remote sensing, satellite, geospatial
5. Social Impact — inclusive climate solutions, rural communities

Evaluate this grant for AltCarbon:

Title: {title}
Funder: {funder}
URL: {url}
Geography: {geography}
Amount: {amount} {currency}
Deadline: {deadline}
Eligibility: {eligibility}
Themes detected: {themes}

Content snippet:
{content}

Funder research context:
{funder_context}

Score each dimension 1–10:
1. theme_alignment: How closely does this grant's purpose match AltCarbon's 5 themes?
2. eligibility_confidence: How confident are you AltCarbon meets the requirements? (startup stage, sector, org type)
3. funding_amount: Based on grant size (max_funding_usd={max_funding_usd}). >$500k=10, >$100k=8, >$50k=6, >$10k=4, <$10k=2
4. deadline_urgency: Lead time available. >3 months=10, 1–3 months=7, <1 month=3, rolling/unknown=6
5. geography_fit: India or global eligible? Explicitly India=10, Global open=8, Unclear=5, Excludes India=0
6. competition_level: Estimated applicant pool. Very selective/niche=10, broad open call=5, highly competitive=3

Return this exact JSON (no other text):
{{
  "scores": {{
    "theme_alignment": <int 1-10>,
    "eligibility_confidence": <int 1-10>,
    "funding_amount": <int 1-10>,
    "deadline_urgency": <int 1-10>,
    "geography_fit": <int 1-10>,
    "competition_level": <int 1-10>
  }},
  "evidence_found": ["<specific thing matching AltCarbon's mission>", ...],
  "evidence_gaps": ["<requirement AltCarbon may not meet>", ...],
  "red_flags": ["<serious disqualifying concern>"],
  "reasoning": "<2-3 sentences explaining the overall score and key trade-offs>",
  "rationale": "<2-3 sentences: why AltCarbon should apply, citing mission alignment and competitive advantage>"
}}"""


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


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
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

def _apply_hard_rules(grant: Dict, min_funding: int = 3_000) -> Optional[str]:
    """Return a disqualification reason string, or None if the grant passes all rules.

    Rules:
    1. Minimum funding threshold
    2. Deadline already passed
    """
    # Rule 1: minimum funding
    max_funding = grant.get("max_funding_usd") or grant.get("max_funding")
    if max_funding is not None and max_funding > 0 and max_funding < min_funding:
        return f"Below ${min_funding:,} minimum funding (found: ${max_funding:,})"

    # Rule 2: deadline already passed (timezone-aware comparison)
    deadline_str = grant.get("deadline")
    if deadline_str:
        parsed = _parse_date(deadline_str)
        if parsed is not None and parsed < datetime.now(tz=timezone.utc):
            return f"Deadline has already passed ({deadline_str})"

    return None


# ── Perplexity funder research (with 7-day MongoDB cache) ─────────────────────

async def _get_funder_context(funder: str, perplexity_key: str) -> str:
    """Fetch Perplexity funder intelligence. Results cached in MongoDB for 7 days."""
    if not funder or funder.lower() in ("unknown", ""):
        return "No funder research available."

    from backend.db.mongo import get_db
    db = get_db()
    cache_col = db["funder_context_cache"]

    # Check cache
    try:
        cached = await cache_col.find_one({"funder": funder})
        if cached:
            cached_at = datetime.fromisoformat(cached["cached_at"])
            if (datetime.now(tz=timezone.utc) - cached_at) < timedelta(days=7):
                logger.debug("Funder context cache hit: %s", funder)
                return cached["context"]
    except Exception:
        pass

    # Fetch from Perplexity
    context = await _perplexity_funder_research(funder, perplexity_key)

    # Cache the result
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

    return context


async def _perplexity_funder_research(funder: str, api_key: str) -> str:
    if not api_key:
        return "No funder research available (no API key)."

    payload = {
        "model": "sonar",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"What are {funder}'s current funding priorities, typical grant sizes, "
                    f"and recent awards? What org types and sectors do they fund? "
                    f"Is India or global applicants typically eligible? 120 words max."
                ),
            }
        ],
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

    result = await retry_async(_do, retries=3, base_delay=2.0, label=f"perplexity-funder:{funder}")
    return result or f"Funder research unavailable for {funder}."


# ── Core scoring ───────────────────────────────────────────────────────────────

async def _score_grant(
    grant: Dict,
    funder_context: str,
    weights: Dict[str, float],
    min_funding: int,
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

    # ── AI scoring with retry ─────────────────────────────────────────────────
    content_snippet = (grant.get("raw_content") or "")[:4000]
    themes_str = ", ".join(grant.get("themes_detected") or [])

    prompt = SCORING_PROMPT.format(
        title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", ""),
        url=grant.get("url", ""),
        geography=grant.get("geography") or "Unknown",
        amount=grant.get("amount") or "Not specified",
        currency=grant.get("currency", "USD"),
        deadline=grant.get("deadline") or "Not specified",
        eligibility=grant.get("eligibility") or "Not specified",
        themes=themes_str or "None detected",
        content=content_snippet,
        funder_context=funder_context,
        max_funding_usd=grant.get("max_funding_usd") or grant.get("max_funding") or "unknown",
    )

    scoring = None
    for attempt in range(3):
        try:
            raw_text = await chat(
                prompt,
                model=SONNET,
                max_tokens=2048,   # was 1024 — raised to prevent JSON truncation
                system=SCORING_SYSTEM,
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
        logger.error("All scoring attempts failed for %s — using defaults", grant.get("url"))
        scoring = {
            "scores": {k: 5 for k in weights},
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

    # Threshold-based action (model's suggestion is not used — thresholds are authoritative)
    from backend.config.settings import get_settings
    s = get_settings()
    if weighted_total >= s.pursue_threshold:
        action = "pursue"
    elif weighted_total >= s.watch_threshold:
        action = "watch"
    else:
        action = "auto_pass"

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
) -> Dict:
    """Build the full document written to grants_scored."""
    # Status: auto_pass grants DO NOT go to triage queue
    status = "auto_pass" if action == "auto_pass" else "triage"

    grant_name = grant.get("grant_name") or grant.get("title") or ""

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
        # ── Quality flags ─────────────────────────────────────────────────────
        "scoring_error":   scoring_error,
    }


# ── Analyst agent ──────────────────────────────────────────────────────────────

class AnalystAgent:
    def __init__(
        self,
        perplexity_api_key: str = "",
        weights: Optional[Dict[str, float]] = None,
        min_funding: int = 3_000,
    ):
        self.perplexity_key = perplexity_api_key
        self.weights = weights or DEFAULT_WEIGHTS
        self.min_funding = min_funding

    async def run(self, raw_grants: List[Dict]) -> List[Dict]:
        if not raw_grants:
            logger.info("Analyst: no grants to score")
            return []

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

        # ── Pre-filter: apply hard rules to identify auto-pass grants ─────────
        # Only run Perplexity enrichment for grants that pass hard rules
        passing_grants = []
        auto_pass_grants = []
        for g in to_score:
            reason = _apply_hard_rules(g, self.min_funding)
            if reason:
                g["_hard_fail_reason"] = reason
                auto_pass_grants.append(g)
            else:
                passing_grants.append(g)

        logger.info(
            "Analyst: %d pass hard rules, %d auto-pass immediately",
            len(passing_grants), len(auto_pass_grants),
        )

        # ── Perplexity funder enrichment (only for passing grants) ────────────
        unique_funders = list({g.get("funder", "") for g in passing_grants})
        funder_sem = asyncio.Semaphore(3)

        async def enrich_funder(funder: str) -> tuple:
            async with funder_sem:
                ctx = await _get_funder_context(funder, self.perplexity_key)
                return funder, ctx

        funder_contexts: Dict[str, str] = {}
        if unique_funders and self.perplexity_key:
            results = await asyncio.gather(*(enrich_funder(f) for f in unique_funders))
            funder_contexts = dict(results)

        # ── Score all grants (concurrent, max 5 LLM calls at once) ───────────
        score_sem = asyncio.Semaphore(5)

        async def score_one(grant: Dict) -> Dict:
            async with score_sem:
                funder = grant.get("funder", "")
                ctx = funder_contexts.get(funder, "No funder research available.")
                return await _score_grant(grant, ctx, self.weights, self.min_funding)

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
            except Exception as e:
                logger.warning("Failed to upsert scored grant %s: %s", s.get("url"), e)

        # Mark raw grants as processed
        from bson import ObjectId
        for g in to_score:
            if g.get("_id"):
                try:
                    await raw_col.update_one(
                        {"_id": g["_id"]},
                        {"$set": {"processed": True}},
                    )
                except Exception:
                    pass

        # ── Rank and summarize ────────────────────────────────────────────────
        ranked = sorted(scored, key=lambda x: x["weighted_total"], reverse=True)
        pursue_count = sum(1 for g in ranked if g["recommended_action"] == "pursue")
        watch_count  = sum(1 for g in ranked if g["recommended_action"] == "watch")
        pass_count   = sum(1 for g in ranked if g["recommended_action"] == "auto_pass")
        top_score    = ranked[0]["weighted_total"] if ranked else 0.0

        logger.info(
            "Analyst complete: %d scored (%d pursue, %d watch, %d auto_pass), "
            "top_score=%.2f, %d skipped as already-scored",
            len(ranked), pursue_count, watch_count, pass_count, top_score, skipped,
        )

        # Write to audit_logs collection (not just LangGraph state)
        await audit_logs().insert_one({
            "node": "analyst",
            "action": f"Scoring complete: {len(ranked)} grants",
            "grants_scored": len(ranked),
            "pursue_count": pursue_count,
            "watch_count": watch_count,
            "auto_pass_count": pass_count,
            "skipped_already_scored": skipped,
            "top_score": top_score,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })

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
        weights=weights,
        min_funding=min_funding,
    )

    raw_grants = state.get("raw_grants", [])
    scored = await agent.run(raw_grants)

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
