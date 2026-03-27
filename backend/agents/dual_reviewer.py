"""Reviewer — funder, scientific, and coherence review of completed drafts.

Each reviewer agent is configurable via agent_config (agent: "reviewer"):
  - strictness: how harsh the scoring is (lenient / balanced / strict)
  - focus_areas: what to prioritize in the review
  - custom_criteria: additional evaluation criteria beyond the grant's own
  - temperature: LLM creativity for the review
  - custom_instructions: extra reviewer-specific guidance

Standalone module (not a LangGraph node). Reads the latest draft from MongoDB,
runs three review perspectives in parallel, and stores results in draft_reviews.

Features:
  - Loads the full grant document (raw page content) for complete context
  - Web research via Tavily: verifies claims, checks funder priorities, finds
    competing approaches before scoring
  - Three parallel review perspectives: Funder, Scientific, Coherence
  - Outcome-calibrated scoring: injects past win/loss lessons into reviewer prompts
  - Golden example comparison: pulls top-scoring sections as benchmarks

Usage:
    from backend.agents.dual_reviewer import run_dual_review
    result = await run_dual_review("683a1f...")  # grant_id
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.utils.llm import chat, ANALYST_HEAVY

logger = logging.getLogger(__name__)

# ── Outcome & Golden Example Loaders ─────────────────────────────────────────

async def _load_outcome_lessons(grant: Dict) -> str:
    """Load past win/loss lessons relevant to this grant's funder and themes.

    Returns a formatted text block to inject into reviewer prompts.
    Non-fatal: returns empty string on failure.
    """
    try:
        from backend.agents.feedback_learner import get_lessons_for_grant
        funder = grant.get("funder") or ""
        themes = grant.get("themes_detected") or []
        lessons = await get_lessons_for_grant(funder=funder, themes=themes)
        if not lessons:
            return ""

        parts = ["LESSONS FROM PAST GRANT OUTCOMES (use to calibrate your scoring):"]
        for lesson in lessons[:5]:
            outcome = lesson.get("outcome", "unknown")
            funder_name = lesson.get("funder", "")
            what_worked = lesson.get("what_worked", [])
            what_failed = lesson.get("what_failed", [])
            summary = f"  [{outcome.upper()}] {funder_name}"
            if what_worked:
                summary += f" — Worked: {'; '.join(what_worked[:2])}"
            if what_failed:
                summary += f" — Failed: {'; '.join(what_failed[:2])}"
            parts.append(summary)

        return "\n".join(parts)
    except Exception as e:
        logger.debug("Outcome lessons load failed: %s", e)
        return ""


async def _load_golden_benchmarks(grant: Dict, section_names: List[str]) -> str:
    """Load golden example sections as quality benchmarks.

    Returns a formatted text block showing what a high-scoring section looks like.
    Non-fatal: returns empty string on failure.
    """
    try:
        from backend.agents.golden_examples.manager import get_golden_examples
        themes = grant.get("themes_detected") or []
        theme = themes[0] if themes else ""

        examples = await get_golden_examples(
            agent="drafter",
            theme=theme,
            example_type="section",
            limit=2,
        )
        if not examples:
            return ""

        parts = ["BENCHMARK — High-scoring sections from past successful grants (for calibration):"]
        for ex in examples[:2]:
            title = ex.get("grant_title", "")
            score = ex.get("quality_score", 0)
            output = ex.get("output", "")
            # Truncate to keep prompt reasonable
            snippet = output[:500] + "..." if len(output) > 500 else output
            parts.append(f"  [{score:.1f}/10] {title}")
            parts.append(f"    {snippet}")

        return "\n".join(parts)
    except Exception as e:
        logger.debug("Golden benchmarks load failed: %s", e)
        return ""


# ── Grant Page Fetcher — fetch actual application page for format/limits ──────

async def _fetch_grant_page(grant: Dict) -> str:
    """Fetch the actual grant application page to understand format, word limits, fields.

    Returns extracted text from the grant page, or empty string on failure.
    """
    url = grant.get("url") or grant.get("application_url") or ""
    if not url:
        return ""

    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return ""

            import re
            html = r.text
            # Strip scripts/styles
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text).strip()

            if len(text) > 500:
                logger.info("Fetched grant page: %d chars from %s", len(text), url[:60])
                return text[:10000]
    except Exception as e:
        logger.debug("Grant page fetch failed for %s: %s", url[:60], e)

    return ""


# ── Claim Verification — check draft claims against knowledge base ───────────

async def _verify_claims(draft_text: str, grant: Dict) -> str:
    """Extract factual claims from the draft and verify against the knowledge base.

    Uses Haiku to extract claims, then checks Pinecone for supporting evidence.
    Returns a formatted block of verified/unverified claims.
    """
    try:
        from backend.utils.llm import chat as llm_chat
        from backend.db.pinecone_store import search_similar, is_pinecone_configured
        from backend.db.mongo import company_facts

        if not is_pinecone_configured():
            return ""

        # Extract verifiable claims from draft
        extract_prompt = f"""Extract all specific factual claims about the company from this grant draft.
Focus on numbers, dates, team details, technology specs, certifications, partnerships.

Draft:
{draft_text[:5000]}

Return JSON: {{"claims": ["<claim 1>", "<claim 2>", ...]}}
Only include specific, verifiable claims (not opinions or plans). Max 10 claims."""

        raw = await llm_chat(extract_prompt, model="claude-haiku-4-5-20251001", max_tokens=400, temperature=0)
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
        claims = json.loads(clean.strip()).get("claims", [])

        if not claims:
            return ""

        # Check each claim against Pinecone + company_facts
        results = []
        # Load company facts for quick lookup
        facts_col = company_facts()
        stored_facts = await facts_col.find({}).to_list(length=50)
        facts_text = " ".join(f.get("fact", "") for f in stored_facts)

        for claim in claims[:8]:
            # Search Pinecone for supporting evidence
            matches = search_similar(claim, top_k=2)
            best_score = matches[0].get("score", 0) if matches else 0
            best_source = matches[0].get("source_title", "") if matches else ""
            best_content = matches[0].get("content", "")[:150] if matches else ""

            # Check company_facts
            claim_lower = claim.lower()
            fact_match = any(
                f.get("fact", "").lower() in claim_lower or claim_lower in f.get("fact", "").lower()
                for f in stored_facts
            )

            if best_score > 0.85 or fact_match:
                status = "VERIFIED"
                source = f"Knowledge base ({best_source})" if best_score > 0.85 else "Company facts"
            elif best_score > 0.7:
                status = "PARTIALLY SUPPORTED"
                source = f"Weak match in {best_source}"
            else:
                status = "UNVERIFIED"
                source = "No supporting evidence found"

            results.append(f"  [{status}] {claim}\n    → {source}")

        if results:
            return "CLAIM VERIFICATION (checked against company knowledge base):\n" + "\n".join(results)
    except Exception as e:
        logger.debug("Claim verification failed: %s", e)

    return ""


# ── Winning Proposal Analysis — search for and analyze past winners ──────────

async def _analyze_past_winners(grant: Dict) -> str:
    """Search for past winners of this grant and analyze what made them successful.

    Uses Tavily for web search, then synthesizes findings with Haiku.
    Returns a formatted analysis block.
    """
    from backend.config.settings import get_settings
    s = get_settings()
    if not s.tavily_api_key:
        return ""

    try:
        from tavily import TavilyClient
    except ImportError:
        return ""

    title = grant.get("title") or grant.get("grant_name") or ""
    funder = grant.get("funder") or ""
    if not title and not funder:
        return ""

    try:
        client = TavilyClient(api_key=s.tavily_api_key)

        # Search for past winners
        queries = [
            f'"{title}" winners awarded funded projects',
            f'"{title}" successful proposal what they funded',
            f'{funder} past grants funded organizations {datetime.now().year - 1}',
        ]

        all_snippets = []
        for q in queries:
            try:
                result = await asyncio.to_thread(
                    client.search, query=q, search_depth="advanced", max_results=5,
                )
                for r in result.get("results", []):
                    snippet = r.get("content", "")[:500]
                    source = r.get("url", "")
                    if snippet and len(snippet) > 50:
                        all_snippets.append(f"{snippet} [source: {source}]")
            except Exception:
                continue

        if not all_snippets:
            return ""

        # Synthesize with Haiku
        from backend.utils.llm import chat as llm_chat
        synthesis_prompt = f"""Based on these web search results about past winners of "{title}" by {funder}, write a concise competitive intelligence briefing.

Search results:
{chr(10).join(all_snippets[:8])}

Write 3-5 bullet points covering:
1. Who won previously (org names, types)
2. Common traits of winning proposals (themes, approaches, scale)
3. What the funder specifically valued
4. How this applicant (Alt Carbon, a climate tech company doing ERW + biochar CDR) compares

Be specific — cite org names and project types from the search results."""

        analysis = await llm_chat(synthesis_prompt, model="claude-haiku-4-5-20251001", max_tokens=500, temperature=0.1)
        if analysis and len(analysis) > 50:
            logger.info("Past winners analysis: %d chars", len(analysis))
            return f"PAST WINNERS ANALYSIS (competitive intelligence):\n{analysis.strip()}"
    except Exception as e:
        logger.debug("Past winners analysis failed: %s", e)

    return ""


# ── Red Team Mode — brutal 30-second first impression ────────────────────────

RED_TEAM_PROMPT = """You are a grant reviewer who has read 200 applications today for "{funder}" — "{title}".
You have 30 seconds to decide: does this one go in the "maybe" pile or the "reject" pile?

{format_note}

APPLICATION:
{draft}

Give your gut reaction in this JSON format:
{{
  "first_impression": "<one sentence — what hit you first>",
  "pile": "<maybe | reject | strong_maybe>",
  "stand_out_factor": "<what, if anything, makes this different from the other 199 applications — or null if nothing>",
  "instant_red_flags": ["<thing that would make you stop reading>"],
  "missing_hook": "<what opening line or fact would have grabbed your attention in the first 10 seconds>",
  "competitive_position": "<where this sits vs typical applications: bottom_third | middle | top_third | top_10_percent>"
}}"""


async def _run_red_team(grant: Dict, draft_text: str, format_note: str = "") -> Dict:
    """Simulate a fatigued reviewer's 30-second first impression."""
    try:
        prompt = RED_TEAM_PROMPT.format(
            funder=grant.get("funder") or "Unknown",
            title=grant.get("title") or grant.get("grant_name") or "Untitled",
            draft=draft_text[:6000],
            format_note=format_note,
        )
        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=500, temperature=0.4)
        result = _parse_json_response(raw)
        logger.info("Red team review: pile=%s, position=%s", result.get("pile"), result.get("competitive_position"))
        return result
    except Exception as e:
        logger.debug("Red team review failed: %s", e)
        return {}


# ── Funder DNA Profiling — build funder profile from public data ─────────────

async def _build_funder_dna(grant: Dict, research: Dict) -> str:
    """Build a funder DNA profile from research findings.

    Synthesizes what the funder values, their pattern of funding, and
    what makes proposals successful with them.
    """
    funder = grant.get("funder") or ""
    if not funder:
        return ""

    # Combine all research snippets
    all_context = []
    for key in ["funder_context", "claim_checks", "grant_format"]:
        for snippet in (research.get(key) or []):
            all_context.append(snippet)

    if not all_context:
        return ""

    try:
        from backend.utils.llm import chat as llm_chat

        prompt = f"""Based on these research findings about {funder}, create a concise "Funder DNA" profile.

Research:
{chr(10).join(all_context[:10])}

Write a structured profile:
**Funding Pattern**: What types of projects/orgs they fund
**Values**: What they care about most (open-source? scale? equity? scientific rigor?)
**Red Lines**: What would get an application rejected
**Sweet Spot**: The ideal proposal for this funder
**Scoring Weights**: What they weight most heavily (estimate percentages)

Keep it to 5-8 lines, specific and actionable."""

        dna = await llm_chat(prompt, model="claude-haiku-4-5-20251001", max_tokens=400, temperature=0.1)
        if dna and len(dna) > 50:
            return f"FUNDER DNA PROFILE ({funder}):\n{dna.strip()}"
    except Exception as e:
        logger.debug("Funder DNA build failed: %s", e)

    return ""


# ── A/B Section Variants — generate alternatives for weak sections ───────────

async def _generate_section_variants(
    weak_sections: Dict[str, Dict],
    grant: Dict,
    company_context: str = "",
) -> Dict[str, str]:
    """For sections scoring below 5, generate an improved alternative.

    Returns {section_name: improved_content}.
    """
    if not weak_sections:
        return {}

    try:
        from backend.utils.llm import chat as llm_chat

        funder = grant.get("funder") or ""
        title = grant.get("title") or grant.get("grant_name") or ""
        variants = {}

        for sec_name, sec_data in list(weak_sections.items())[:3]:  # Max 3 sections
            original = sec_data.get("content", "")
            issues = sec_data.get("issues", [])
            wc = len(original.split())

            prompt = f"""Rewrite this grant section to address the reviewer's issues.

GRANT: {title}
FUNDER: {funder}
SECTION: {sec_name}
WORD COUNT TARGET: ~{wc} words (stay within ±20%)

ORIGINAL:
{original}

ISSUES TO FIX:
{chr(10).join(f'- {i}' for i in issues[:5])}

{f'COMPANY CONTEXT:{chr(10)}{company_context[:3000]}' if company_context else ''}

Write an improved version that:
1. Fixes ALL listed issues
2. Keeps roughly the same word count
3. Uses specific data and claims (not generic statements)
4. Is ready to submit

Write ONLY the improved section text, nothing else."""

            improved = await llm_chat(prompt, model=ANALYST_HEAVY, max_tokens=1500, temperature=0.3)
            if improved and len(improved.split()) > 20:
                variants[sec_name] = improved.strip()

        return variants
    except Exception as e:
        logger.debug("Section variant generation failed: %s", e)
        return {}


# ── Revision Priority Matrix — rank issues by impact × effort ────────────────

async def _build_revision_priorities(review_results: Dict) -> Dict:
    """Analyze all review results and build a prioritized revision plan.

    Returns a structured priority matrix with estimated score impact.
    """
    try:
        from backend.utils.llm import chat as llm_chat

        # Collect all issues across perspectives
        all_issues = []
        for perspective in ["funder", "scientific"]:
            result = review_results.get(perspective, {})
            for sec_name, sec_review in result.get("section_reviews", {}).items():
                for issue in sec_review.get("issues", []):
                    all_issues.append(f"[{perspective}/{sec_name}] {issue}")
                for suggestion in sec_review.get("suggestions", []):
                    all_issues.append(f"[{perspective}/{sec_name}] SUGGESTION: {suggestion}")

        coherence = review_results.get("coherence", {})
        for issue in coherence.get("issues", []):
            desc = issue.get("description", "") if isinstance(issue, dict) else str(issue)
            all_issues.append(f"[coherence] {desc}")

        if not all_issues:
            return {}

        current_scores = {
            "funder": review_results.get("funder", {}).get("overall_score", 0),
            "scientific": review_results.get("scientific", {}).get("overall_score", 0),
            "coherence": coherence.get("coherence_score", 0),
        }

        prompt = f"""Given these review issues from a grant application, create a revision priority matrix.

Current scores: Funder: {current_scores['funder']}/10, Scientific: {current_scores['scientific']}/10, Coherence: {current_scores['coherence']}/10

All issues:
{chr(10).join(all_issues[:30])}

Create a prioritized action plan. Return JSON:
{{
  "quick_wins": [
    {{"action": "<what to do>", "sections": ["<affected sections>"], "estimated_score_impact": "+X.X points", "effort": "5 min"}}
  ],
  "high_impact": [
    {{"action": "<what to do>", "sections": ["<affected sections>"], "estimated_score_impact": "+X.X points", "effort": "30 min"}}
  ],
  "nice_to_have": [
    {{"action": "<what to do>", "sections": ["<affected sections>"], "estimated_score_impact": "+X.X points", "effort": "1 hour"}}
  ],
  "predicted_score_after_fixes": {{
    "funder": <float>,
    "scientific": <float>,
    "coherence": <float>
  }},
  "top_3_actions": ["<most impactful action 1>", "<action 2>", "<action 3>"]
}}"""

        raw = await llm_chat(prompt, model="claude-haiku-4-5-20251001", max_tokens=800, temperature=0.1)
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(clean.strip())
    except Exception as e:
        logger.debug("Revision priority matrix failed: %s", e)
        return {}


# ── Win Probability Prediction ────────────────────────────────────────────────

WIN_PREDICTION_PROMPT = """You are a grant outcome prediction model. Based on all available signals, estimate the probability that this application will be funded.

GRANT: {grant_title}
FUNDER: {funder}
FUNDING: {funding}

REVIEW SCORES:
- Funder perspective: {funder_score}/10 ({funder_verdict})
- Scientific perspective: {scientific_score}/10 ({scientific_verdict})
- Coherence: {coherence_score}/10
- Red team pile: {red_team_pile}
- Red team competitive position: {red_team_position}

CLAIM VERIFICATION:
{claim_summary}

FUNDER DNA:
{funder_dna}

PAST OUTCOMES (if any):
{past_outcomes}

COMPETITIVE LANDSCAPE:
{competitive_context}

APPLICATION FORMAT: {format_type}
SECTIONS: {num_sections} sections, avg {avg_words} words each

Analyze systematically:
1. Score-based signal: What do the review scores suggest?
2. Funder fit signal: How well does this match the funder's pattern?
3. Competitive signal: How does this compare to typical winners?
4. Red flags: Any dealbreakers?
5. Calibration: Are there past outcomes to calibrate against?

Respond with JSON:
{{
  "win_probability": <float 0.0 to 1.0>,
  "confidence": "<low|medium|high — how confident are you in this estimate>",
  "confidence_reasoning": "<why this confidence level>",
  "key_factors": {{
    "working_for": ["<factor increasing probability>"],
    "working_against": ["<factor decreasing probability>"],
    "uncertain": ["<factor that could go either way>"]
  }},
  "comparable_outcome": "<what happened to similar applications in the past, if known>",
  "to_reach_60_percent": ["<specific action that would increase win probability>"],
  "to_reach_80_percent": ["<specific action that would increase win probability further>"],
  "reasoning": "<2-3 sentences explaining the prediction logic>"
}}"""


async def _predict_win_probability(
    grant: Dict,
    review_results: Dict,
    red_team_result: Dict,
    funder_dna: str = "",
    claim_verification: str = "",
    format_info: str = "",
) -> Dict:
    """Predict win probability based on all review signals."""
    try:
        # Load past outcomes for calibration
        from backend.db.mongo import grant_outcomes
        funder = grant.get("funder") or ""
        themes = grant.get("themes_detected") or []

        past = []
        if funder:
            past_docs = await grant_outcomes().find(
                {"funder": {"$regex": funder, "$options": "i"}}
            ).sort("created_at", -1).to_list(length=10)
            for p in past_docs:
                past.append(
                    f"  [{p.get('outcome', '?').upper()}] {p.get('grant_title', '?')[:60]} "
                    f"— funder_score: {p.get('reviewer_scores', {}).get('funder', '?')}, "
                    f"scientific_score: {p.get('reviewer_scores', {}).get('scientific', '?')}"
                )

        funder_result = review_results.get("funder", {})
        scientific_result = review_results.get("scientific", {})
        coherence_result = review_results.get("coherence", {})

        funding = grant.get("max_funding_usd") or grant.get("amount") or "Unknown"
        if isinstance(funding, (int, float)):
            funding = f"${funding:,.0f}"

        prompt = WIN_PREDICTION_PROMPT.format(
            grant_title=grant.get("title") or grant.get("grant_name") or "?",
            funder=funder,
            funding=funding,
            funder_score=funder_result.get("overall_score", 0),
            funder_verdict=funder_result.get("verdict", "?"),
            scientific_score=scientific_result.get("overall_score", 0),
            scientific_verdict=scientific_result.get("verdict", "?"),
            coherence_score=coherence_result.get("coherence_score", 0),
            red_team_pile=red_team_result.get("pile", "unknown"),
            red_team_position=red_team_result.get("competitive_position", "unknown"),
            claim_summary=claim_verification[:1000] if claim_verification else "No claims verified",
            funder_dna=funder_dna[:1000] if funder_dna else "No funder profile available",
            past_outcomes="\n".join(past[:5]) if past else "No past outcomes recorded for this funder",
            competitive_context=red_team_result.get("stand_out_factor", "Unknown"),
            format_type=format_info or "Standard narrative",
            num_sections=len(review_results.get("funder", {}).get("section_reviews", {})),
            avg_words="short-form" if "form" in format_info.lower() else "narrative",
        )

        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=800, temperature=0.2)
        result = _parse_json_response(raw)
        result.setdefault("win_probability", 0.5)
        result.setdefault("confidence", "low")
        logger.info(
            "Win probability for '%s': %.0f%% (%s confidence)",
            grant.get("grant_name", "?")[:40],
            result["win_probability"] * 100,
            result["confidence"],
        )
        return result
    except Exception as e:
        logger.debug("Win probability prediction failed: %s", e)
        return {}


# ── Reviewer Chat — interactive follow-up with the reviewer ──────────────────

REVIEWER_CHAT_PROMPT = """You are continuing a grant review conversation. The user wants to discuss the review findings.

You previously reviewed this application:
GRANT: {grant_title}
FUNDER: {funder}

YOUR REVIEW RESULTS:
{review_summary}

{red_team_summary}

{revision_plan_summary}

{win_probability_summary}

DRAFT APPLICATION:
{draft_text}

The user is asking about the review. Be direct, specific, and constructive.
When they ask "why", give the exact reasoning from your review.
When they ask "how to fix", give concrete text they can use.
When they ask "what would a 9/10 look like", write an example.

USER: {message}

Respond in markdown. Be specific — reference section names, quote the draft text, cite your review findings."""


async def reviewer_chat(
    grant_id: str,
    message: str,
    perspective: str = "funder",
    chat_history: Optional[List[Dict]] = None,
) -> str:
    """Interactive chat with the reviewer about their review findings.

    Loads the full review context and answers follow-up questions.
    """
    from backend.db.mongo import grant_drafts, grants_scored, draft_reviews

    from bson import ObjectId

    grant = await grants_scored().find_one({"_id": ObjectId(grant_id)})
    if not grant:
        return "Grant not found."

    # Load all review perspectives
    reviews = {}
    async for doc in draft_reviews().find({"grant_id": grant_id}):
        reviews[doc.get("perspective", "unknown")] = doc

    # Load draft
    draft_doc = await grant_drafts().find_one({"grant_id": grant_id}, sort=[("version", -1)])
    draft_text = ""
    if draft_doc:
        for name, sec in draft_doc.get("sections", {}).items():
            draft_text += f"\n## {name}\n{sec.get('content', '')}\n"

    # Build review summary
    review_parts = []
    for p in ["funder", "scientific", "coherence"]:
        r = reviews.get(p, {})
        if p == "coherence":
            review_parts.append(f"**Coherence**: {r.get('coherence_score', '?')}/10 — {r.get('overall_assessment', '')[:200]}")
            for issue in r.get("issues", [])[:5]:
                desc = issue.get("description", "") if isinstance(issue, dict) else str(issue)
                review_parts.append(f"  - {desc[:150]}")
        else:
            review_parts.append(f"**{p.title()}**: {r.get('overall_score', '?')}/10 ({r.get('verdict', '?')})")
            review_parts.append(f"  Summary: {r.get('summary', '')[:200]}")
            for sec_name, sec_r in r.get("section_reviews", {}).items():
                review_parts.append(f"  {sec_name}: {sec_r.get('score', '?')}/10")
                for issue in sec_r.get("issues", [])[:2]:
                    review_parts.append(f"    - {issue[:150]}")

    # Red team
    rt = reviews.get("red_team", {})
    red_team_summary = ""
    if rt:
        red_team_summary = (
            f"RED TEAM RESULT:\n"
            f"  Pile: {rt.get('pile', '?')}\n"
            f"  First impression: {rt.get('first_impression', '')}\n"
            f"  Stand-out: {rt.get('stand_out_factor', 'None')}\n"
            f"  Competitive position: {rt.get('competitive_position', '?')}"
        )

    # Revision plan
    rp = reviews.get("revision_plan", {})
    revision_plan_summary = ""
    if rp:
        top_actions = rp.get("top_3_actions", [])
        predicted = rp.get("predicted_score_after_fixes", {})
        revision_plan_summary = (
            f"REVISION PLAN:\n"
            f"  Top actions: {'; '.join(top_actions[:3])}\n"
            f"  Predicted scores after fixes: funder={predicted.get('funder', '?')}, "
            f"scientific={predicted.get('scientific', '?')}"
        )

    # Win probability
    wp = reviews.get("win_probability", {})
    win_prob_summary = ""
    if wp:
        win_prob_summary = (
            f"WIN PROBABILITY: {wp.get('win_probability', 0)*100:.0f}% ({wp.get('confidence', '?')} confidence)\n"
            f"  Reasoning: {wp.get('reasoning', '')[:200]}"
        )

    # Build history
    history_block = ""
    if chat_history:
        lines = []
        for msg in chat_history[-6:]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")[:400]
            lines.append(f"[{role}]: {content}")
        history_block = "PREVIOUS CONVERSATION:\n" + "\n".join(lines) + "\n\n"

    prompt = REVIEWER_CHAT_PROMPT.format(
        grant_title=grant.get("title") or grant.get("grant_name") or "?",
        funder=grant.get("funder") or "?",
        review_summary="\n".join(review_parts),
        red_team_summary=red_team_summary,
        revision_plan_summary=revision_plan_summary,
        win_probability_summary=win_prob_summary,
        draft_text=draft_text[:8000],
        message=f"{history_block}{message}",
    )

    response = await chat(prompt, model=ANALYST_HEAVY, max_tokens=2000, temperature=0.3)
    return response.strip()


# ── Default reviewer profiles ─────────────────────────────────────────────────

REVIEWER_PROFILES: Dict[str, Dict] = {
    "funder": {
        "display_name": "Funder Perspective",
        "role": "senior grant program officer",
        "focus_areas": [
            "Alignment with funder priorities",
            "Budget justification and value for money",
            "Measurable objectives and impact claims",
            "Team credibility for the proposed scope",
            "Competitiveness vs. typical winning applications",
        ],
        "scoring_guidance": {
            "lenient": "Be encouraging. Score generously — focus on potential. Flag only critical issues.",
            "balanced": "Be fair and constructive. Acknowledge strengths before issues. Score based on realistic competitiveness.",
            "strict": "Be demanding. Score as a skeptical program officer with limited funding. Every weakness matters.",
        },
        "default_temperature": 0.3,
    },
    "scientific": {
        "display_name": "Scientific Perspective",
        "role": "peer reviewer and domain scientist",
        "focus_areas": [
            "Methodology soundness and reproducibility",
            "MRV rigor and data quality",
            "Scientific novelty vs. incremental work",
            "Scalability evidence and pathway",
            "Uncertainties honestly acknowledged",
            "Claims supported by data or citations",
            "Technical feasibility of proposed approach",
        ],
        "scoring_guidance": {
            "lenient": "Be supportive of emerging approaches. Accept preliminary data. Focus on scientific promise.",
            "balanced": "Expect solid methodology but accept reasonable assumptions. Flag unsupported claims.",
            "strict": "Peer-review standard. Every claim needs evidence. Methodology must be reproducible. No hand-waving.",
        },
        "default_temperature": 0.25,
    },
}

# ── Prompt templates ──────────────────────────────────────────────────────────

REVIEW_PROMPT = """You are a {role} evaluating a grant application.
{role_context}

SCORING APPROACH: {scoring_guidance}

GRANT: {grant_title}
FUNDER: {funder}
{extra_context}

{section_structure_block}

EVALUATION CRITERIA (from the funder):
{criteria}

{custom_criteria_block}

{grant_document_block}

{research_block}

FOCUS YOUR REVIEW ON:
{focus_areas}

{custom_instructions_block}

COMPLETE DRAFT APPLICATION:
{draft}

{outcome_lessons_block}

{golden_benchmarks_block}

REVIEW RULES:
1. Review each section ONLY within its stated scope — do not penalize a section for not covering topics assigned to other sections
2. If a word limit is shown for a section, flag violations. If NO word limit is shown, do not invent one or penalize length
3. Evaluate whether each section addresses the evaluation criteria relevant to its scope
4. Suggestions must be actionable within the section's constraints — if a word limit exists, don't suggest adding content that would exceed it
5. Score each section relative to what it was ASKED to cover, not what you wish it covered
6. For EVERY issue and suggestion, explain your REASONING: WHY this matters to the funder, WHY this weakens the application, and WHAT EVIDENCE from the web research or grant criteria supports your assessment
7. Use web research findings to ground your feedback — cite specific insights about the funder's priorities, past winners, or domain context when making suggestions
8. If the application format is form-based (short answers), evaluate density and impact of each answer, not length

Review this application thoroughly. Be specific and constructive. {perspective_guidance}
Use the original grant document, web research context, past outcome lessons, and benchmark examples (if provided) to verify claims, calibrate scores, and identify gaps.

CRITICAL OUTPUT CONSTRAINT: Keep your response under 6000 characters total. Be concise:
- Max 2 strengths, 3 issues, 3 suggestions PER SECTION
- Each string max 1-2 sentences
- Prioritize the most important points

Respond ONLY with valid JSON:
{{
  "overall_score": <float 1-10>,
  "section_reviews": {{
    "<section_name>": {{
      "score": <int 1-10>,
      "strengths": ["<1-2 sentence strength>"],
      "issues": ["<1-2 sentence issue with reason>"],
      "suggestions": ["<1-2 sentence actionable fix>"],
      "word_count": <int>,
      "word_limit": <int or null>,
      "within_scope": true
    }}
  }},
  "top_issues": ["<critical issue 1>", "<issue 2>", "<issue 3>"],
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "verdict": "<strong_submit | submit_with_revisions | major_revisions | reconsider>",
  "summary": "<2-3 sentence assessment>",
  "research_insights": ["<1 key web research finding>"]
}}"""

PERSPECTIVE_GUIDANCE = {
    "funder": (
        "Consider: Would you fund this? Is the money well-spent? "
        "Does this stand out from competing proposals? Is the team credible?"
    ),
    "scientific": (
        "Consider: Is the science solid? Are methods reproducible? "
        "Are claims evidence-based? What's missing from a technical standpoint?"
    ),
}

ROLE_CONTEXT = {
    "funder": "You represent the funder and must decide whether this application deserves funding over other proposals.",
    "scientific": "You are evaluating the scientific and technical rigor of this proposal for a funding body.",
}


# ── Web Research ─────────────────────────────────────────────────────────────

async def _web_research_for_review(
    grant: Dict,
    draft_text: str,
) -> Dict[str, List[str]]:
    """Use Tavily to research context that helps reviewers score more accurately.

    Searches for:
    - Grant application format, word limits, requirements
    - Funder's recent priorities and past funded projects
    - Competing approaches / state of the art in the grant's domain
    - Past winners and what made them successful

    Returns {"funder_context": [...], "scientific_context": [...], "claim_checks": [...],
             "grant_format": [...]}.
    All values are short text snippets. Non-fatal: returns empty dicts on failure.
    """
    from backend.config.settings import get_settings

    s = get_settings()
    tavily_key = s.tavily_api_key
    empty = {"funder_context": [], "scientific_context": [], "claim_checks": [], "grant_format": []}
    if not tavily_key:
        logger.info("Reviewer research skipped: no TAVILY_API_KEY configured")
        return empty

    try:
        from tavily import TavilyClient
    except ImportError:
        logger.warning("tavily-python not installed — reviewer research skipped")
        return empty

    client = TavilyClient(api_key=tavily_key)
    funder = grant.get("funder") or ""
    title = grant.get("title") or grant.get("grant_name") or ""
    themes = ", ".join(grant.get("themes_detected", []))
    grant_url = grant.get("url") or grant.get("application_url") or ""
    year = datetime.now().year

    # Build targeted queries — more specific than generic searches
    queries = {
        "grant_format": (
            f'"{title}" application form requirements word limit format {year}'
            if title else f"{funder} grant application format requirements"
        ),
        "funder_context": (
            f'"{funder}" grant winners funded projects {year} what they look for'
            if funder else f"{title} past winners evaluation"
        ),
        "scientific_context": (
            f"{themes} latest research advances methodology {year}"
            if themes else f"{title} state of the art scientific approaches"
        ),
        "claim_checks": (
            f'"{title}" past winners successful applications tips advice'
            if title else f"{funder} grant successful proposal characteristics"
        ),
    }

    async def _search(query: str, depth: str = "basic") -> List[str]:
        try:
            result = await asyncio.to_thread(
                client.search,
                query=query,
                search_depth=depth,
                max_results=5,
            )
            snippets = []
            for r in result.get("results", []):
                snippet = r.get("content", "")[:400]
                source = r.get("url", "")
                title_r = r.get("title", "")
                if snippet:
                    snippets.append(f"[{title_r}] {snippet} [source: {source}]")
            return snippets
        except Exception as e:
            logger.warning("Reviewer research query failed: %s — %s", query[:60], e)
            return []

    # Use advanced search for grant format (most important), basic for rest
    tasks = {}
    for key, q in queries.items():
        depth = "advanced" if key == "grant_format" else "basic"
        tasks[key] = _search(q, depth)

    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results = {}
    for key, res in zip(tasks.keys(), gathered):
        results[key] = res if isinstance(res, list) else []

    total = sum(len(v) for v in results.values())
    logger.info("Reviewer research complete: %d snippets across %d queries", total, len(queries))
    return results


def _format_research_block(research: Dict[str, List[str]]) -> str:
    """Format research findings into a prompt block for the reviewer."""
    parts = []
    if research.get("grant_format"):
        parts.append("GRANT APPLICATION FORMAT (from web research — use to calibrate expectations):")
        for s in research["grant_format"][:4]:
            parts.append(f"  - {s}")
    if research.get("funder_context"):
        parts.append("FUNDER INTELLIGENCE (what they fund and look for):")
        for s in research["funder_context"][:4]:
            parts.append(f"  - {s}")
    if research.get("claim_checks"):
        parts.append("PAST WINNERS & SUCCESS PATTERNS:")
        for s in research["claim_checks"][:3]:
            parts.append(f"  - {s}")
    if research.get("scientific_context"):
        parts.append("DOMAIN CONTEXT (latest research & approaches):")
        for s in research["scientific_context"][:3]:
            parts.append(f"  - {s}")
    if not parts:
        return ""
    return "\n".join(parts)


# ── Core logic ──────────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> Dict:
    """Parse LLM JSON response, stripping markdown fences and fixing truncation."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fix truncated JSON: try closing open braces/brackets
    fixed = raw.rstrip()
    # Remove trailing incomplete string (unterminated)
    if fixed.count('"') % 2 != 0:
        # Odd number of quotes — find last complete field
        last_complete = fixed.rfind('",')
        if last_complete > 0:
            fixed = fixed[:last_complete + 1]

    # Close any open structures
    open_braces = fixed.count('{') - fixed.count('}')
    open_brackets = fixed.count('[') - fixed.count(']')
    # Trim trailing comma
    fixed = fixed.rstrip().rstrip(',')
    fixed += ']' * max(0, open_brackets)
    fixed += '}' * max(0, open_braces)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        # Last resort: find the last valid JSON object boundary
        for end_pos in range(len(raw), max(0, len(raw) - 500), -1):
            candidate = raw[:end_pos]
            open_b = candidate.count('{') - candidate.count('}')
            open_br = candidate.count('[') - candidate.count(']')
            candidate = candidate.rstrip().rstrip(',')
            candidate += ']' * max(0, open_br)
            candidate += '}' * max(0, open_b)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        # Nothing worked — raise the original error
        raise json.JSONDecodeError("Could not parse truncated JSON", raw, 0)


async def _run_single_review(
    grant: Dict,
    draft_text: str,
    perspective: str,
    settings: Dict,
    research: Optional[Dict[str, List[str]]] = None,
    grant_raw_doc: str = "",
    outcome_lessons: str = "",
    golden_benchmarks: str = "",
    section_structure_block: str = "",
) -> Dict:
    """Run a single review perspective with configurable settings.

    Args:
        research: Web research findings from _web_research_for_review.
        grant_raw_doc: Original grant page content for full context.
        outcome_lessons: Formatted text block with past win/loss lessons.
        golden_benchmarks: Formatted text block with high-scoring example sections.
    """
    profile = REVIEWER_PROFILES.get(perspective, REVIEWER_PROFILES["funder"])

    # Build grant context
    deep = grant.get("deep_analysis") or {}
    eval_criteria = deep.get("evaluation_criteria") or grant.get("evaluation_criteria") or []
    criteria = ""
    if eval_criteria:
        criteria_lines = []
        for c in eval_criteria:
            if isinstance(c, dict):
                criteria_lines.append(
                    f"- {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))} "
                    f"({c.get('weight', 'unweighted')})"
                )
            else:
                criteria_lines.append(f"- {c}")
        criteria = "\n".join(criteria_lines)
    else:
        criteria = "No explicit criteria provided — evaluate based on standard grant review practices."

    # Extra context varies by perspective
    extra_parts = []
    if perspective == "funder":
        funding = grant.get("max_funding_usd") or grant.get("max_funding") or grant.get("amount") or "Not specified"
        if isinstance(funding, (int, float)):
            funding = f"${funding:,.0f}"
        extra_parts.append(f"FUNDING AMOUNT: {funding}")
        extra_parts.append(f"DEADLINE: {grant.get('deadline') or 'Not specified'}")
    else:
        themes = ", ".join(grant.get("themes_detected", [])) or "Not specified"
        extra_parts.append(f"THEMES: {themes}")
    extra_context = "\n".join(extra_parts)

    # Settings
    strictness = settings.get("strictness", "balanced")
    scoring_guidance = profile["scoring_guidance"].get(strictness, profile["scoring_guidance"]["balanced"])

    # Focus areas: user overrides + defaults
    user_focus = settings.get("focus_areas", [])
    focus_list = user_focus if user_focus else profile["focus_areas"]
    focus_areas = "\n".join(f"- {f}" for f in focus_list)

    # Custom criteria
    custom_criteria = settings.get("custom_criteria", [])
    custom_criteria_block = ""
    if custom_criteria:
        custom_criteria_block = "ADDITIONAL EVALUATION CRITERIA (weight these equally):\n" + "\n".join(
            f"- {c}" for c in custom_criteria
        )

    # Custom instructions
    custom_instructions = settings.get("custom_instructions", "")
    custom_instructions_block = ""
    if custom_instructions:
        custom_instructions_block = f"REVIEWER INSTRUCTIONS:\n{custom_instructions}"

    # Grant document block — original funder page for reference
    grant_document_block = ""
    if grant_raw_doc:
        # Truncate to keep prompt reasonable
        truncated = grant_raw_doc[:8000]
        grant_document_block = (
            "ORIGINAL GRANT DOCUMENT (from funder's page — use to verify alignment):\n"
            f"{truncated}"
        )

    # Research block — web-sourced intelligence
    research_block = _format_research_block(research or {})

    temperature = settings.get("temperature") or profile.get("default_temperature", 0.3)

    prompt = REVIEW_PROMPT.format(
        role=profile["role"],
        role_context=ROLE_CONTEXT.get(perspective, ""),
        scoring_guidance=scoring_guidance,
        grant_title=grant.get("title") or grant.get("grant_name") or "Untitled",
        funder=grant.get("funder") or "Unknown",
        extra_context=extra_context,
        section_structure_block=section_structure_block,
        criteria=criteria,
        custom_criteria_block=custom_criteria_block,
        grant_document_block=grant_document_block,
        research_block=research_block,
        focus_areas=focus_areas,
        custom_instructions_block=custom_instructions_block,
        outcome_lessons_block=outcome_lessons,
        golden_benchmarks_block=golden_benchmarks,
        draft=draft_text[:15000],
        perspective_guidance=PERSPECTIVE_GUIDANCE.get(perspective, ""),
    )

    try:
        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=8192, temperature=temperature)
        review = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        logger.warning("Review JSON parse failed (%s), retrying with shorter prompt: %s", perspective, str(e)[:100])
        # Retry: ask for a condensed review to fit within token limits
        retry_prompt = (
            f"Your previous review was cut off due to length. Please provide a CONDENSED review.\n\n"
            f"GRANT: {grant.get('title') or grant.get('grant_name') or 'Untitled'}\n"
            f"FUNDER: {grant.get('funder') or 'Unknown'}\n\n"
            f"{section_structure_block}\n\n"
            f"DRAFT:\n{draft_text[:8000]}\n\n"
            f"Respond with valid JSON. Keep each field concise (1-2 sentences per issue/suggestion):\n"
            f'{{"overall_score": <1-10>, "section_reviews": {{"<section>": {{"score": <1-10>, '
            f'"strengths": ["..."], "issues": ["..."], "suggestions": ["..."]}}}}, '
            f'"top_issues": ["..."], "strengths": ["..."], "verdict": "<strong_submit|submit_with_revisions|major_revisions>", '
            f'"summary": "...", "research_insights": ["..."]}}'
        )
        try:
            raw2 = await chat(retry_prompt, model=ANALYST_HEAVY, max_tokens=6000, temperature=temperature)
            review = _parse_json_response(raw2)
        except Exception as e2:
            logger.error("Review retry also failed (%s): %s", perspective, e2)
            review = _fallback_review(perspective, f"JSON parse error after retry: {e}")
    except Exception as e:
        logger.error("Review LLM call failed (%s): %s", perspective, e)
        review = _fallback_review(perspective, str(e))

    # Ensure required fields
    review.setdefault("overall_score", 5.0)
    review.setdefault("section_reviews", {})
    review.setdefault("top_issues", [])
    review.setdefault("strengths", [])
    review.setdefault("verdict", "major_revisions")
    review.setdefault("summary", "Review completed.")
    review.setdefault("research_insights", [])

    return review


def _fallback_review(perspective: str, error: str) -> Dict:
    """Return a minimal review when the LLM call fails."""
    return {
        "overall_score": 0,
        "section_reviews": {},
        "top_issues": [f"Automated {perspective} review failed: {error}"],
        "strengths": [],
        "verdict": "major_revisions",
        "summary": f"The {perspective} review could not be completed due to an error. Please retry.",
        "research_insights": [],
    }


COHERENCE_PROMPT = """You are reviewing a COMPLETE grant application for cross-section coherence.

GRANT: {grant_title}
FUNDER: {funder}

{section_structure_block}

{research_block}

COMPLETE DRAFT:
{draft}

Review the application as a WHOLE (not section-by-section). Check for:

1. NARRATIVE CONSISTENCY: Is there a single coherent story from problem → solution → impact? Or do sections tell different stories?
2. BUDGET ↔ ACTIVITIES MATCH: Does the budget justify the activities described in the technical approach? Are there activities with no budget, or budget items with no corresponding activity?
3. CLAIMS ↔ EVIDENCE MATCH: Do impact claims in the outcomes section match what the methodology can actually deliver? Are there claims without methodological backing?
4. CROSS-SECTION CONTRADICTIONS: Do any sections contradict each other? (e.g., timeline says 12 months but impact claims require 24 months of data)
5. UNNECESSARY REPETITION: Are the same points made in multiple sections without adding new value?
6. MISSING THREADS: Are there important elements introduced in one section but never followed up? (e.g., partnerships mentioned in team section but absent from project plan)

REASONING REQUIREMENT:
For every issue you flag, briefly explain WHY it matters to the funder.

If this is a form-based application with short answers, evaluate coherence WITHIN the form format.

CRITICAL OUTPUT CONSTRAINT: Keep response under 4000 characters. Max 6 issues. Each description max 2 sentences.

Respond ONLY with valid JSON:
{{
  "coherence_score": <float 1-10>,
  "narrative_consistent": <bool>,
  "issues": [
    {{"type": "<contradiction|budget_mismatch|unsupported_claim|repetition|missing_thread>", "sections_involved": ["<sec1>", "<sec2>"], "description": "<2 sentence issue + reason>", "fix": "<1 sentence fix>"}}
  ],
  "overall_assessment": "<2-3 sentence assessment>"
}}"""


async def _run_coherence_review(
    grant: Dict,
    draft_text: str,
    section_structure_block: str = "",
    research_block: str = "",
) -> Dict:
    """Run holistic coherence review across all sections."""
    prompt = COHERENCE_PROMPT.format(
        grant_title=grant.get("title") or grant.get("grant_name") or "Untitled",
        funder=grant.get("funder") or "Unknown",
        draft=draft_text[:15000],
        section_structure_block=section_structure_block,
        research_block=research_block,
    )

    try:
        raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=6000, temperature=0.2)
        result = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        logger.warning("Coherence review JSON parse failed, retrying condensed: %s", str(e)[:100])
        try:
            retry_prompt = (
                f"Review this grant draft for coherence. Be VERY concise — max 4 issues, 1 sentence each.\n\n"
                f"GRANT: {grant.get('title') or grant.get('grant_name') or '?'}\n"
                f"DRAFT:\n{draft_text[:6000]}\n\n"
                f"JSON: {{\"coherence_score\": <1-10>, \"narrative_consistent\": <bool>, "
                f"\"issues\": [{{\"type\": \"...\", \"sections_involved\": [...], \"description\": \"...\", \"fix\": \"...\"}}], "
                f"\"overall_assessment\": \"...\"}}"
            )
            raw2 = await chat(retry_prompt, model=ANALYST_HEAVY, max_tokens=3000, temperature=0.2)
            result = _parse_json_response(raw2)
        except Exception as e2:
            logger.error("Coherence retry also failed: %s", e2)
            result = {
                "coherence_score": 0,
                "narrative_consistent": True,
                "issues": [{"type": "error", "sections_involved": [], "description": f"Parse error: {e}", "fix": "Retry review"}],
                "overall_assessment": "Coherence review could not be completed.",
            }
    except Exception as e:
        logger.error("Coherence review LLM call failed: %s", e)
        result = {
            "coherence_score": 0,
            "narrative_consistent": True,
            "issues": [],
            "overall_assessment": f"Coherence review failed: {e}",
        }

    result.setdefault("coherence_score", 5.0)
    result.setdefault("issues", [])
    result.setdefault("overall_assessment", "Review completed.")
    return result


async def run_dual_review(grant_id: str) -> Dict:
    """Run funder + scientific reviews on the latest draft for a grant.

    Pipeline:
    1. Load grant + latest draft from MongoDB
    2. Load original grant document (raw page content) for full context
    3. Run web research via Tavily (funder priorities, domain context, claim checks)
    4. Run funder + scientific + coherence reviews in parallel (with research context)
    5. Store all results in draft_reviews collection

    Returns {"funder": {...}, "scientific": {...}, "coherence": {...}}.
    """
    from backend.db.mongo import grant_drafts, grants_scored, draft_reviews, agent_config
    from bson import ObjectId

    # Load grant
    grant = await grants_scored().find_one({"_id": ObjectId(grant_id)})
    if not grant:
        raise ValueError(f"Grant {grant_id} not found in grants_scored")

    # Load latest draft
    draft_doc = await grant_drafts().find_one(
        {"grant_id": grant_id},
        sort=[("version", -1)],
    )
    if not draft_doc:
        raise ValueError(f"No draft found for grant {grant_id}")

    # Assemble draft text with section metadata (word limits, word counts)
    sections = draft_doc.get("sections", {})

    # Load application_sections from grant for scope/description context
    deep = grant.get("deep_analysis") or {}
    app_sections = deep.get("application_sections") or []
    # Build lookup: section name → {description, word limit}
    section_spec = {}
    for asec in app_sections:
        if isinstance(asec, dict):
            sname = asec.get("section") or asec.get("name", "")
            section_spec[sname.lower()] = {
                "description": asec.get("what_to_cover") or asec.get("description", ""),
                "limit": asec.get("limit") or asec.get("word_limit", ""),
            }
        elif isinstance(asec, str):
            section_spec[asec.lower()] = {"description": "", "limit": ""}

    # Build structured draft text with constraints
    # Only show word limits that the grant itself specifies (from application_sections)
    draft_parts = []
    section_structure_parts = []
    for name, sec in sections.items():
        content = sec.get("content", "")
        wc = sec.get("word_count") or len(content.split())
        spec = section_spec.get(name.lower(), {})
        desc = spec.get("description", "")
        # Only use word limit from the grant's application_sections — not our internal defaults
        grant_wl = spec.get("limit", "")

        header = f"## {name}"
        if grant_wl:
            header += f" [{wc} / {grant_wl} words]"
        else:
            header += f" [{wc} words]"
        draft_parts.append(f"{header}\n{content}")

        # Build section structure summary for reviewer context
        struct_line = f"- **{name}**: {wc} words"
        if grant_wl:
            struct_line += f" (limit: {grant_wl})"
            try:
                if wc > int(str(grant_wl).split()[0]):
                    struct_line += " — OVER LIMIT"
            except (ValueError, IndexError):
                pass
        if desc:
            struct_line += f" — Scope: {desc[:150]}"
        section_structure_parts.append(struct_line)

    draft_text = "\n\n".join(draft_parts)

    if not draft_text.strip():
        raise ValueError("Draft has no content")

    # Section structure block injected into reviewer prompt
    section_structure_block = ""
    if section_structure_parts:
        section_structure_block = (
            "APPLICATION STRUCTURE (review each section ONLY within its stated scope and word limit):\n"
            + "\n".join(section_structure_parts)
        )

    # Build drafting context block — full conversation history per section
    drafting_ctx = draft_doc.get("drafting_context") or {}
    drafting_context_block = ""

    # If draft doc doesn't have drafting_context, try loading from chat history directly
    if not drafting_ctx.get("per_section"):
        try:
            from backend.db.mongo import drafter_chat_history, grants_pipeline
            # Find the pipeline record to get chat history
            pipeline = await grants_pipeline().find_one({"grant_id": grant_id}, sort=[("started_at", -1)])
            if pipeline:
                chat_doc = await drafter_chat_history().find_one({"pipeline_id": str(pipeline["_id"])})
                if chat_doc:
                    per_sec = {}
                    for sec_name, messages in (chat_doc.get("sections") or {}).items():
                        if not isinstance(messages, list):
                            continue
                        agent_msgs = [m for m in messages if m.get("role") == "agent"]
                        user_msgs = [m for m in messages if m.get("role") == "user"]
                        conversation_summary = []
                        user_instructions = []
                        for msg in messages:
                            role = msg.get("role", "")
                            mc = (msg.get("content") or "").strip()
                            if role == "user" and mc and len(mc) > 10:
                                conversation_summary.append(f"USER: {mc[:250]}")
                                user_instructions.append(mc[:300])
                            elif role == "agent" and mc:
                                wc = len(mc.split())
                                conversation_summary.append(f"AGENT: [wrote {wc} words]")
                        per_sec[sec_name] = {
                            "revision_count": max(0, len(agent_msgs) - 1),
                            "user_instructions": user_instructions,
                            "conversation_summary": conversation_summary,
                        }
                    if per_sec:
                        drafting_ctx = {"per_section": per_sec}
                        logger.info("Reviewer: loaded drafting context from chat history (%d sections)", len(per_sec))
        except Exception:
            logger.debug("Reviewer: chat history loading skipped", exc_info=True)

    if drafting_ctx:
        dc_parts = []
        ws = drafting_ctx.get("writing_style")
        if ws:
            dc_parts.append(f"Writing style: {ws}")
        ci = drafting_ctx.get("custom_instructions")
        if ci:
            dc_parts.append(f"Custom instructions given to drafter: {ci[:300]}")
        per_sec = drafting_ctx.get("per_section") or {}
        for sec_name, sec_ctx in per_sec.items():
            revisions = sec_ctx.get("revision_count", 0)
            instructions = sec_ctx.get("user_instructions", [])
            conv_summary = sec_ctx.get("conversation_summary", [])

            # Build a compact but complete conversation trail
            sec_parts = [f"**{sec_name}**: {revisions} revision(s)"]
            if instructions:
                # Include ALL user instructions so reviewer understands full intent
                for i, inst in enumerate(instructions):
                    sec_parts.append(f"  [{i+1}] User: {inst[:200]}")
            dc_parts.append("\n".join(sec_parts))

        if dc_parts:
            drafting_context_block = (
                "DRAFTING CONTEXT (full conversation history — understand what the author asked for and iterated on):\n"
                + "\n".join(dc_parts)
            )
            section_structure_block = section_structure_block + "\n\n" + drafting_context_block if section_structure_block else drafting_context_block

    # Detect application format: form-based (short answers) vs narrative (long-form)
    avg_wc = sum(s.get("word_count", len(s.get("content", "").split())) for s in sections.values()) / max(len(sections), 1)
    is_form_based = avg_wc < 200 and len(sections) >= 4
    if is_form_based:
        format_note = (
            f"\n\nAPPLICATION FORMAT: This is a FORM-BASED application with short-answer fields "
            f"(average {int(avg_wc)} words per section, {len(sections)} sections). "
            "Do NOT suggest expanding to longer narratives — the form constrains length. "
            "Evaluate quality, specificity, and impact WITHIN the short-answer format. "
            "A concise answer can be excellent if it's precise and impactful. "
            "Do NOT penalize brevity — penalize vagueness."
        )
        section_structure_block = section_structure_block + format_note

    # Load original grant context — use deep_analysis (always available on grants_scored)
    # The raw page HTML lives in the LangGraph checkpointer but is expensive to extract.
    # deep_analysis contains the structured extraction the analyst already performed.
    deep = grant.get("deep_analysis") or {}
    grant_raw_parts = []
    if deep.get("opportunity_summary"):
        grant_raw_parts.append(f"OPPORTUNITY: {deep['opportunity_summary']}")
    if deep.get("eligibility"):
        elig = deep["eligibility"]
        if isinstance(elig, dict):
            grant_raw_parts.append(f"ELIGIBILITY: {json.dumps(elig, default=str)[:2000]}")
        else:
            grant_raw_parts.append(f"ELIGIBILITY: {str(elig)[:2000]}")
    if deep.get("requirements"):
        reqs = deep["requirements"]
        if isinstance(reqs, dict):
            grant_raw_parts.append(f"REQUIREMENTS: {json.dumps(reqs, default=str)[:2000]}")
    if deep.get("evaluation_criteria"):
        ec = deep["evaluation_criteria"]
        if isinstance(ec, list):
            ec_lines = []
            for c in ec:
                if isinstance(c, dict):
                    ec_lines.append(f"  - {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))}")
                else:
                    ec_lines.append(f"  - {c}")
            grant_raw_parts.append("EVALUATION CRITERIA:\n" + "\n".join(ec_lines))
    if deep.get("funding_terms"):
        ft = deep["funding_terms"]
        if isinstance(ft, dict):
            grant_raw_parts.append(f"FUNDING TERMS: {json.dumps(ft, default=str)[:1500]}")
        elif isinstance(ft, str):
            grant_raw_parts.append(f"FUNDING TERMS: {ft[:1500]}")
    grant_raw_doc = "\n\n".join(grant_raw_parts)

    # Step 1: Pre-review context gathering (run in parallel)
    # Tier 1: grant page, web research, claim verification, past winners
    # Plus existing: outcome lessons, golden benchmarks
    format_note_for_red_team = (
        f"This is a FORM-BASED application (~{int(avg_wc)} words avg, {len(sections)} sections)."
        if is_form_based else ""
    )
    # Load articulation docs + company context for the reviewer
    async def _load_reviewer_articulations():
        try:
            from backend.main import _load_articulations
            themes = grant.get("themes_detected") or []
            primary_theme = themes[0] if themes else "climatetech"
            return await _load_articulations(primary_theme, draft_text[:500], grant.get("title", ""))
        except Exception:
            return ""

    async def _load_reviewer_company_context():
        parts = []
        try:
            from backend.agents.company_brain import _load_static_profile
            profile = _load_static_profile() or ""
            if profile:
                parts.append(profile[:8000])
        except Exception:
            pass
        try:
            from backend.db.mongo import company_facts
            facts = await company_facts().find({}).to_list(length=50)
            if facts:
                parts.append("VERIFIED FACTS:\n" + "\n".join(f"- {f['fact']}" for f in facts if f.get("fact")))
        except Exception:
            pass
        return "\n\n".join(parts)

    (
        research, outcome_lessons, golden_benchmarks,
        grant_page_content, claim_verification, past_winners_analysis,
        articulation_text, company_context,
    ) = await asyncio.gather(
        _web_research_for_review(grant, draft_text),
        _load_outcome_lessons(grant),
        _load_golden_benchmarks(grant, list(sections.keys())),
        _fetch_grant_page(grant),
        _verify_claims(draft_text, grant),
        _analyze_past_winners(grant),
        _load_reviewer_articulations(),
        _load_reviewer_company_context(),
    )

    # Enhance grant_raw_doc with fetched page content
    if grant_page_content:
        grant_raw_doc = f"LIVE GRANT PAGE CONTENT (fetched from {grant.get('url', '')}):\n{grant_page_content[:6000]}\n\n{grant_raw_doc}"

    # Add articulation docs + company context — reviewer needs these to verify claims
    if articulation_text:
        grant_raw_doc += f"\n\nARTICULATION DOCUMENTS (AltCarbon's authoritative methodology & data — verify draft claims against these):\n{articulation_text}"
    if company_context:
        grant_raw_doc += f"\n\nCOMPANY CONTEXT (verified facts about AltCarbon):\n{company_context[:6000]}"

    # Add claim verification and past winners to section_structure_block
    if claim_verification:
        section_structure_block = section_structure_block + "\n\n" + claim_verification
    if past_winners_analysis:
        section_structure_block = section_structure_block + "\n\n" + past_winners_analysis

    # Build funder DNA from research
    funder_dna = await _build_funder_dna(grant, research)
    if funder_dna:
        section_structure_block = section_structure_block + "\n\n" + funder_dna

    # Load per-grant reviewer settings (stored by the frontend settings panel)
    grant_reviewer_cfg = (grant or {}).get("reviewer_settings") or {}

    # Load global reviewer config (existing behavior)
    reviewer_cfg = await agent_config().find_one({"agent": "reviewer"}) or {}

    # Merge: per-grant overrides global for funder/scientific settings
    funder_settings = {**reviewer_cfg.get("funder", {})}
    scientific_settings = {**reviewer_cfg.get("scientific", {})}

    # Apply per-grant overrides
    if grant_reviewer_cfg.get("funder_strictness"):
        funder_settings["strictness"] = grant_reviewer_cfg["funder_strictness"]
    if grant_reviewer_cfg.get("scientific_strictness"):
        scientific_settings["strictness"] = grant_reviewer_cfg["scientific_strictness"]
    if grant_reviewer_cfg.get("funder_focus_areas"):
        funder_settings["focus_areas"] = grant_reviewer_cfg["funder_focus_areas"]
    if grant_reviewer_cfg.get("scientific_focus_areas"):
        scientific_settings["focus_areas"] = grant_reviewer_cfg["scientific_focus_areas"]
    if grant_reviewer_cfg.get("custom_criteria"):
        funder_settings["custom_criteria"] = grant_reviewer_cfg["custom_criteria"]
        scientific_settings["custom_criteria"] = grant_reviewer_cfg["custom_criteria"]
    if grant_reviewer_cfg.get("custom_instructions"):
        funder_settings["custom_instructions"] = grant_reviewer_cfg["custom_instructions"]
        scientific_settings["custom_instructions"] = grant_reviewer_cfg["custom_instructions"]

    grant_title = grant.get("title") or grant.get("grant_name") or "Untitled"
    context_stats = {
        "research_snippets": sum(len(v) for v in research.values()),
        "has_outcome_lessons": bool(outcome_lessons),
        "has_golden_benchmarks": bool(golden_benchmarks),
    }
    logger.info(
        "Starting full review for '%s' (grant_id=%s, draft v%d, funder_strictness=%s, sci_strictness=%s, %s)",
        grant_title, grant_id, draft_doc.get("version", 0),
        funder_settings.get("strictness", "balanced"),
        scientific_settings.get("strictness", "balanced"),
        context_stats,
    )

    # Step 2: Run all review perspectives in parallel (with enriched context)
    funder_result, scientific_result, coherence_result = await asyncio.gather(
        _run_single_review(grant, draft_text, "funder", funder_settings,
                           research=research, grant_raw_doc=grant_raw_doc,
                           outcome_lessons=outcome_lessons, golden_benchmarks=golden_benchmarks,
                           section_structure_block=section_structure_block),
        _run_single_review(grant, draft_text, "scientific", scientific_settings,
                           research=research, grant_raw_doc=grant_raw_doc,
                           outcome_lessons=outcome_lessons, golden_benchmarks=golden_benchmarks,
                           section_structure_block=section_structure_block),
        _run_coherence_review(grant, draft_text,
                              section_structure_block=section_structure_block,
                              research_block=_format_research_block(research)),
    )

    now = datetime.now(timezone.utc).isoformat()
    draft_id = str(draft_doc["_id"])
    draft_version = draft_doc.get("version", 0)

    # Store all three reviews
    for perspective, result in [
        ("funder", funder_result),
        ("scientific", scientific_result),
        ("coherence", coherence_result),
    ]:
        review_doc = {
            "grant_id": grant_id,
            "draft_id": draft_id,
            "draft_version": draft_version,
            "perspective": perspective,
            **result,
            "web_research_used": bool(any(research.values())),
            "outcome_lessons_used": bool(outcome_lessons),
            "golden_benchmarks_used": bool(golden_benchmarks),
            "created_at": now,
        }
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": perspective},
            review_doc,
            upsert=True,
        )

    # Log issues
    coherence_issues = coherence_result.get("issues", [])
    if coherence_issues:
        logger.warning(
            "Coherence review found %d issues for '%s': %s",
            len(coherence_issues),
            grant_title,
            [i.get("type") for i in coherence_issues[:5]],
        )

    # Cross-reviewer contradiction detection
    funder_verdict = funder_result.get("verdict", "")
    scientific_verdict = scientific_result.get("verdict", "")
    contradictions = None
    submit_verdicts = {"strong_submit", "submit_with_revisions"}
    reject_verdicts = {"major_revisions", "do_not_submit"}
    if (funder_verdict in submit_verdicts and scientific_verdict in reject_verdicts) or \
       (scientific_verdict in submit_verdicts and funder_verdict in reject_verdicts):
        contradictions = {
            "funder_verdict": funder_verdict,
            "scientific_verdict": scientific_verdict,
            "explanation": (
                f"Funder reviewer says '{funder_verdict}' but scientific reviewer says '{scientific_verdict}'. "
                f"These verdicts fundamentally disagree — averaged scores may hide this conflict."
            ),
        }
        logger.warning(
            "Contradiction detected for '%s': funder=%s vs scientific=%s",
            grant_title, funder_verdict, scientific_verdict,
        )
        # Store contradiction alongside reviews
        await draft_reviews().update_one(
            {"grant_id": grant_id, "perspective": "funder"},
            {"$set": {"contradictions": contradictions}},
        )

    # Step 3: Post-review enhancements (red team, priorities, A/B variants)
    review_results = {
        "funder": funder_result,
        "scientific": scientific_result,
        "coherence": coherence_result,
    }

    # Run red team + revision priorities in parallel
    red_team_result, revision_priorities = await asyncio.gather(
        _run_red_team(grant, draft_text, format_note=format_note_for_red_team),
        _build_revision_priorities(review_results),
    )

    # Generate A/B variants for weak sections (score < 5)
    weak_sections = {}
    for sec_name, sec_review in funder_result.get("section_reviews", {}).items():
        if sec_review.get("score", 10) < 5:
            sec_content = sections.get(sec_name, {})
            weak_sections[sec_name] = {
                "content": sec_content.get("content", ""),
                "issues": sec_review.get("issues", []) + sec_review.get("suggestions", []),
            }

    # Load company context for variants
    company_ctx = ""
    try:
        from backend.agents.company_brain import _load_static_profile
        company_ctx = _load_static_profile() or ""
    except Exception:
        pass

    section_variants = await _generate_section_variants(weak_sections, grant, company_context=company_ctx)

    # Store enhanced results
    if red_team_result:
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": "red_team"},
            {
                "grant_id": grant_id, "draft_id": draft_id, "draft_version": draft_version,
                "perspective": "red_team", **red_team_result, "created_at": now,
            },
            upsert=True,
        )

    if revision_priorities:
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": "revision_plan"},
            {
                "grant_id": grant_id, "draft_id": draft_id, "draft_version": draft_version,
                "perspective": "revision_plan", **revision_priorities, "created_at": now,
            },
            upsert=True,
        )

    if section_variants:
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": "section_variants"},
            {
                "grant_id": grant_id, "draft_id": draft_id, "draft_version": draft_version,
                "perspective": "section_variants",
                "variants": section_variants,
                "created_at": now,
            },
            upsert=True,
        )

    # Step 4: Win probability prediction (needs all other results)
    win_prediction = await _predict_win_probability(
        grant, review_results, red_team_result or {},
        funder_dna=funder_dna,
        claim_verification=claim_verification,
        format_info=format_note_for_red_team,
    )

    if win_prediction:
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": "win_probability"},
            {
                "grant_id": grant_id, "draft_id": draft_id, "draft_version": draft_version,
                "perspective": "win_probability", **win_prediction, "created_at": now,
            },
            upsert=True,
        )

    logger.info(
        "Full review complete for '%s': funder=%.1f (%s), scientific=%.1f (%s), coherence=%.1f, "
        "red_team=%s, priorities=%d actions, variants=%d sections, win_prob=%.0f%%",
        grant_title,
        funder_result.get("overall_score", 0),
        funder_result.get("verdict", "?"),
        scientific_result.get("overall_score", 0),
        scientific_result.get("verdict", "?"),
        coherence_result.get("coherence_score", 0),
        red_team_result.get("pile", "?") if red_team_result else "skipped",
        len(revision_priorities.get("top_3_actions", [])) if revision_priorities else 0,
        len(section_variants),
        win_prediction.get("win_probability", 0) * 100 if win_prediction else 0,
    )

    # Update grant status to "reviewed"
    try:
        await grants_scored().update_one(
            {"_id": ObjectId(grant_id)},
            {"$set": {"status": "reviewed", "updated_at": now}},
        )
    except Exception as e:
        logger.warning("run_dual_review: failed to update grant status: %s", e)

    # Sync status to Notion
    try:
        from backend.integrations.notion_sync import update_grant_status
        await update_grant_status(grant_id, "reviewed")
    except Exception:
        logger.debug("Notion sync skipped (review completion)", exc_info=True)

    # Update heartbeat
    try:
        from backend.agents.agent_context import update_heartbeat
        await update_heartbeat("reviewer", {
            "status": "success",
            "grant_title": grant_title[:50],
            "funder_score": funder_result.get("overall_score", 0),
            "scientific_score": scientific_result.get("overall_score", 0),
            "coherence_score": coherence_result.get("coherence_score", 0),
            "funder_verdict": funder_result.get("verdict", ""),
            "scientific_verdict": scientific_result.get("verdict", ""),
            "coherence_issues": len(coherence_issues),
        })
    except Exception:
        logger.debug("Heartbeat update skipped (reviewer)", exc_info=True)

    return {
        "funder": funder_result,
        "scientific": scientific_result,
        "coherence": coherence_result,
        **({"contradictions": contradictions} if contradictions else {}),
        **({"red_team": red_team_result} if red_team_result else {}),
        **({"revision_plan": revision_priorities} if revision_priorities else {}),
        **({"section_variants": section_variants} if section_variants else {}),
        **({"win_probability": win_prediction} if win_prediction else {}),
    }


# ── LangGraph Node ──────────────────────────────────────────────────────────

async def dual_reviewer_node(state: "GrantState") -> Dict:
    """LangGraph node: run the full dual (triple) review inside the pipeline.

    Uses approved_sections from graph state (instead of MongoDB draft) and
    the grant's deep_analysis for context. Saves results to draft_reviews
    collection so the Reviewers UI can display them immediately.
    """
    from backend.db.mongo import grants_scored, draft_reviews, grant_drafts, agent_config
    from backend.graph.state import GrantState
    from bson import ObjectId

    grant_id = state.get("selected_grant_id")
    if not grant_id:
        logger.error("dual_reviewer_node: no selected_grant_id in state")
        return {
            "reviewer_output": _fallback_review("pipeline", "No grant selected"),
            "audit_log": state.get("audit_log", []) + [{
                "node": "reviewer", "ts": datetime.now(timezone.utc).isoformat(),
                "error": "no grant_id",
            }],
        }

    # Load grant from MongoDB for full metadata
    grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}

    # Assemble draft text from graph state (approved_sections) with section metadata
    approved_sections = state.get("approved_sections") or {}

    # Load application_sections from grant for scope/description context
    _deep_for_sections = grant.get("deep_analysis") or {}
    _app_sections = _deep_for_sections.get("application_sections") or []
    _section_spec = {}
    for _asec in _app_sections:
        if isinstance(_asec, dict):
            _sname = _asec.get("section") or _asec.get("name", "")
            _section_spec[_sname.lower()] = {
                "description": _asec.get("what_to_cover") or _asec.get("description", ""),
                "limit": _asec.get("limit") or _asec.get("word_limit", ""),
            }
        elif isinstance(_asec, str):
            _section_spec[_asec.lower()] = {"description": "", "limit": ""}

    draft_parts = []
    section_structure_parts = []
    for name, sec in approved_sections.items():
        content = sec.get("content", "")
        wc = sec.get("word_count") or len(content.split())
        spec = _section_spec.get(name.lower(), {})
        desc = spec.get("description", "")
        # Only use word limit from the grant's application_sections — not our internal defaults
        grant_wl = spec.get("limit", "")

        header = f"## {name}"
        if grant_wl:
            header += f" [{wc} / {grant_wl} words]"
        else:
            header += f" [{wc} words]"
        draft_parts.append(f"{header}\n{content}")

        struct_line = f"- **{name}**: {wc} words"
        if grant_wl:
            struct_line += f" (limit: {grant_wl})"
            try:
                if wc > int(str(grant_wl).split()[0]):
                    struct_line += " — OVER LIMIT"
            except (ValueError, IndexError):
                pass
        if desc:
            struct_line += f" — Scope: {desc[:150]}"
        section_structure_parts.append(struct_line)

    draft_text = "\n\n".join(draft_parts)

    section_structure_block = ""
    if section_structure_parts:
        section_structure_block = (
            "APPLICATION STRUCTURE (review each section ONLY within its stated scope and word limit):\n"
            + "\n".join(section_structure_parts)
        )

    if not draft_text.strip():
        logger.error("dual_reviewer_node: draft is empty")
        return {
            "reviewer_output": _fallback_review("pipeline", "Draft is empty"),
            "audit_log": state.get("audit_log", []) + [{
                "node": "reviewer", "ts": datetime.now(timezone.utc).isoformat(),
                "error": "empty draft",
            }],
        }

    # Build grant document context from deep_analysis
    deep = grant.get("deep_analysis") or {}
    grant_raw_parts = []
    if deep.get("opportunity_summary"):
        grant_raw_parts.append(f"OPPORTUNITY: {deep['opportunity_summary']}")
    if deep.get("eligibility"):
        elig = deep["eligibility"]
        if isinstance(elig, dict):
            grant_raw_parts.append(f"ELIGIBILITY: {json.dumps(elig, default=str)[:2000]}")
        else:
            grant_raw_parts.append(f"ELIGIBILITY: {str(elig)[:2000]}")
    if deep.get("requirements"):
        reqs = deep["requirements"]
        if isinstance(reqs, dict):
            grant_raw_parts.append(f"REQUIREMENTS: {json.dumps(reqs, default=str)[:2000]}")
    if deep.get("evaluation_criteria"):
        ec = deep["evaluation_criteria"]
        if isinstance(ec, list):
            ec_lines = []
            for c in ec:
                if isinstance(c, dict):
                    ec_lines.append(f"  - {c.get('criterion', '')}: {c.get('what_they_look_for', c.get('description', ''))}")
                else:
                    ec_lines.append(f"  - {c}")
            grant_raw_parts.append("EVALUATION CRITERIA:\n" + "\n".join(ec_lines))
    if deep.get("funding_terms"):
        ft = deep["funding_terms"]
        if isinstance(ft, dict):
            grant_raw_parts.append(f"FUNDING TERMS: {json.dumps(ft, default=str)[:1500]}")
        elif isinstance(ft, str):
            grant_raw_parts.append(f"FUNDING TERMS: {ft[:1500]}")
    grant_raw_doc = "\n\n".join(grant_raw_parts)

    # Also use grant_raw_doc from state if deep_analysis is sparse
    if not grant_raw_doc and state.get("grant_raw_doc"):
        grant_raw_doc = (state.get("grant_raw_doc") or "")[:8000]

    # Step 1: Pre-review context gathering (run in parallel)
    research, outcome_lessons, golden_benchmarks = await asyncio.gather(
        _web_research_for_review(grant, draft_text),
        _load_outcome_lessons(grant),
        _load_golden_benchmarks(grant, list(approved_sections.keys())),
    )

    # Load reviewer settings (global + per-grant overrides)
    grant_reviewer_cfg = grant.get("reviewer_settings") or {}
    reviewer_cfg = await agent_config().find_one({"agent": "reviewer"}) or {}

    funder_settings = {**reviewer_cfg.get("funder", {})}
    scientific_settings = {**reviewer_cfg.get("scientific", {})}

    if grant_reviewer_cfg.get("funder_strictness"):
        funder_settings["strictness"] = grant_reviewer_cfg["funder_strictness"]
    if grant_reviewer_cfg.get("scientific_strictness"):
        scientific_settings["strictness"] = grant_reviewer_cfg["scientific_strictness"]
    if grant_reviewer_cfg.get("funder_focus_areas"):
        funder_settings["focus_areas"] = grant_reviewer_cfg["funder_focus_areas"]
    if grant_reviewer_cfg.get("scientific_focus_areas"):
        scientific_settings["focus_areas"] = grant_reviewer_cfg["scientific_focus_areas"]
    if grant_reviewer_cfg.get("custom_criteria"):
        funder_settings["custom_criteria"] = grant_reviewer_cfg["custom_criteria"]
        scientific_settings["custom_criteria"] = grant_reviewer_cfg["custom_criteria"]
    if grant_reviewer_cfg.get("custom_instructions"):
        funder_settings["custom_instructions"] = grant_reviewer_cfg["custom_instructions"]
        scientific_settings["custom_instructions"] = grant_reviewer_cfg["custom_instructions"]

    grant_title = grant.get("title") or grant.get("grant_name") or "Untitled"
    logger.info(
        "Pipeline full review for '%s' (grant_id=%s, sections=%d, research=%d, lessons=%s, benchmarks=%s)",
        grant_title, grant_id, len(approved_sections),
        sum(len(v) for v in research.values()),
        bool(outcome_lessons), bool(golden_benchmarks),
    )

    # Step 2: Run all review perspectives in parallel (with enriched context)
    funder_result, scientific_result, coherence_result = await asyncio.gather(
        _run_single_review(grant, draft_text, "funder", funder_settings,
                           research=research, grant_raw_doc=grant_raw_doc,
                           outcome_lessons=outcome_lessons, golden_benchmarks=golden_benchmarks,
                           section_structure_block=section_structure_block),
        _run_single_review(grant, draft_text, "scientific", scientific_settings,
                           research=research, grant_raw_doc=grant_raw_doc,
                           outcome_lessons=outcome_lessons, golden_benchmarks=golden_benchmarks,
                           section_structure_block=section_structure_block),
        _run_coherence_review(grant, draft_text,
                              section_structure_block=section_structure_block,
                              research_block=_format_research_block(research)),
    )

    now = datetime.now(timezone.utc).isoformat()

    # Find draft_id from MongoDB if a draft was already saved by exporter
    draft_doc = await grant_drafts().find_one(
        {"grant_id": grant_id},
        sort=[("version", -1)],
    )
    draft_id = str(draft_doc["_id"]) if draft_doc else ""
    draft_version = draft_doc.get("version", 0) if draft_doc else state.get("draft_version", 0)

    # Save all three reviews to draft_reviews collection
    for perspective, result in [
        ("funder", funder_result),
        ("scientific", scientific_result),
        ("coherence", coherence_result),
    ]:
        review_doc = {
            "grant_id": grant_id,
            "draft_id": draft_id,
            "draft_version": draft_version,
            "perspective": perspective,
            **result,
            "web_research_used": bool(any(research.values())),
            "outcome_lessons_used": bool(outcome_lessons),
            "golden_benchmarks_used": bool(golden_benchmarks),
            "source": "pipeline",
            "created_at": now,
        }
        await draft_reviews().replace_one(
            {"grant_id": grant_id, "perspective": perspective},
            review_doc,
            upsert=True,
        )

    coherence_issues = coherence_result.get("issues", [])

    # Compute combined score
    funder_score = funder_result.get("overall_score", 0)
    scientific_score = scientific_result.get("overall_score", 0)
    coherence_score = coherence_result.get("coherence_score", 0)
    combined_score = round(
        (funder_score + scientific_score + coherence_score) / 3, 1
    )

    # Determine ready_for_export from reviewer verdicts + coherence gate
    verdicts = [funder_result.get("verdict", ""), scientific_result.get("verdict", "")]
    ready = all(v in ("strong_submit", "submit_with_revisions") for v in verdicts) and coherence_score >= 5.0

    # Cross-reviewer contradiction detection
    funder_verdict = funder_result.get("verdict", "")
    scientific_verdict = scientific_result.get("verdict", "")
    contradictions = None
    _submit_v = {"strong_submit", "submit_with_revisions"}
    _reject_v = {"major_revisions", "do_not_submit"}
    if (funder_verdict in _submit_v and scientific_verdict in _reject_v) or \
       (scientific_verdict in _submit_v and funder_verdict in _reject_v):
        contradictions = {
            "funder_verdict": funder_verdict,
            "scientific_verdict": scientific_verdict,
            "explanation": (
                f"Funder reviewer says '{funder_verdict}' but scientific reviewer says '{scientific_verdict}'. "
                f"These verdicts fundamentally disagree — averaged scores may hide this conflict."
            ),
        }
        logger.warning(
            "Pipeline: contradiction detected for '%s': funder=%s vs scientific=%s",
            grant_title, funder_verdict, scientific_verdict,
        )
        await draft_reviews().update_one(
            {"grant_id": grant_id, "perspective": "funder"},
            {"$set": {"contradictions": contradictions}},
        )

    logger.info(
        "Pipeline full review complete for '%s': funder=%.1f (%s), scientific=%.1f (%s), "
        "coherence=%.1f, combined=%.1f, ready=%s",
        grant_title, funder_score, funder_result.get("verdict", "?"),
        scientific_score, scientific_result.get("verdict", "?"),
        coherence_score, combined_score, ready,
    )

    # Update heartbeat
    try:
        from backend.agents.agent_context import update_heartbeat
        await update_heartbeat("reviewer", {
            "status": "success",
            "source": "pipeline",
            "grant_title": grant_title[:50],
            "funder_score": funder_score,
            "scientific_score": scientific_score,
            "coherence_score": coherence_score,
            "funder_verdict": funder_result.get("verdict", ""),
            "scientific_verdict": scientific_result.get("verdict", ""),
            "coherence_issues": len(coherence_issues),
        })
    except Exception:
        logger.debug("Heartbeat update skipped (reviewer pipeline)", exc_info=True)

    # Update grant status to "reviewed"
    try:
        await grants_scored().update_one(
            {"_id": ObjectId(grant_id)},
            {"$set": {"status": "reviewed"}},
        )
    except Exception as e:
        logger.warning("dual_reviewer_node: failed to update grant status: %s", e)

    # Sync status to Notion
    try:
        from backend.integrations.notion_sync import update_grant_status as _notion_status
        await _notion_status(grant_id, "reviewed")
    except Exception:
        logger.debug("Notion sync skipped (pipeline review)", exc_info=True)

    # Build reviewer_output — backward-compatible shape + full review
    reviewer_output = {
        "overall_score": combined_score,
        "ready_for_export": ready,
        "summary": f"Funder: {funder_result.get('summary', '')} | Scientific: {scientific_result.get('summary', '')}",
        "funder": funder_result,
        "scientific": scientific_result,
        "coherence": coherence_result,
        "web_research_used": bool(any(research.values())),
        "outcome_lessons_used": bool(outcome_lessons),
        "golden_benchmarks_used": bool(golden_benchmarks),
        **({"contradictions": contradictions} if contradictions else {}),
    }

    audit_entry = {
        "node": "reviewer",
        "ts": now,
        "funder_score": funder_score,
        "scientific_score": scientific_score,
        "coherence_score": coherence_score,
        "combined_score": combined_score,
        "funder_verdict": funder_result.get("verdict", ""),
        "scientific_verdict": scientific_result.get("verdict", ""),
        "ready_for_export": ready,
        "web_research_used": bool(any(research.values())),
    }

    return {
        "reviewer_output": reviewer_output,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
