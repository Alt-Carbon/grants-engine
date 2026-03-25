"""Pre-Triage Guardrail — LLM-powered filter on scored grants before human triage.

Rejects grants that are expired or that the LLM judges unfit for the company.
Runs AFTER analyst scoring but BEFORE the human triage queue.

Flow per grant (status == "triage" only):
  1. Deadline expired → deterministic reject (no LLM needed)
  2. LLM evaluation → reject with reason, or pass to triage queue

Grants with non-triage status (auto_pass) pass through unchanged.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agents.analyst import parse_deadline
from backend.config.settings import get_settings
from backend.graph.state import GrantState
from backend.utils.llm import chat, ANALYST_LIGHT
from backend.utils.parsing import parse_json_safe

logger = logging.getLogger(__name__)

_s = get_settings()

# ── Company profile (cached) ────────────────────────────────────────────────
_company_profile_cache: Optional[str] = None


def _get_company_profile() -> str:
    global _company_profile_cache
    if _company_profile_cache is None:
        profile_path = Path(__file__).parent.parent / "knowledge" / "altcarbon_profile.md"
        try:
            _company_profile_cache = profile_path.read_text(encoding="utf-8")[:3000]
        except FileNotFoundError:
            _company_profile_cache = f"{_s.company_name} — company profile not found"
    return _company_profile_cache


# ── LLM prompt ──────────────────────────────────────────────────────────────

GUARDRAIL_SYSTEM = (
    "You are a grant screening expert for {company_name}, a climate technology startup based in India. "
    "Your job is to quickly reject grants that are clearly a poor fit, saving the team's time. "
    "Respond ONLY with valid JSON — no prose, no markdown fences."
)

GUARDRAIL_PROMPT = """Evaluate whether this grant should be REJECTED from {company_name}'s triage queue, or PASSED through for human review.

## Company Profile
{company_profile}

## Grant Summary
- Title: {title}
- Funder: {funder}
- Type: {grant_type}
- Amount: {amount} {currency}
- Deadline: {deadline}
- Geography: {geography}
- Eligibility: {eligibility}
- Themes detected: {themes}
- AI Recommendation: {recommended_action}

## Analyst Scores (each out of 10)
{scores_text}
- Weighted Total: {weighted_total}/10

## Analyst Reasoning
{reasoning}

## Red Flags
{red_flags}

## Evidence of Fit
{evidence_found}

## Evidence Gaps
{evidence_gaps}

## Decision Criteria — REJECT if ANY of the following are clearly true:
1. The grant is fundamentally misaligned with the company's mission (climate tech, CDR, MRV, agritech, AI for earth sciences)
2. The company is clearly ineligible (e.g. grant restricted to a country/region the company doesn't operate in, or restricted to entity types that don't match)
3. The grant quality scores are very low across multiple dimensions (not just one weak area)
4. There are critical red flags that make this grant not worth pursuing
5. The grant is for a completely different sector or technology domain

DO NOT reject grants just because one score dimension is low — the team may still find value.
DO NOT reject grants with tight deadlines — that's a logistics decision, not a quality one.
When in doubt, PASS the grant through — false rejections are worse than false passes.

Return this exact JSON:
{{
  "decision": "reject" or "pass",
  "reason": "<2-3 sentence explanation of why this grant should be rejected or why it deserves human review>"
}}"""


def _check_deadline(grant: Dict) -> Dict[str, Any] | None:
    """Deterministic deadline check. Returns rejection dict or None."""
    deadline_str = grant.get("deadline")
    if not deadline_str:
        return None

    deadline_dt = parse_deadline(deadline_str)
    if deadline_dt is None:
        logger.warning(
            "pre_triage_guardrail: unparseable deadline '%s' for grant '%s'",
            deadline_str, grant.get("title", "unknown"),
        )
        return {
            "reason": "deadline_unparseable",
            "detail": f"Could not parse deadline '{deadline_str}' — manual review required",
        }
    if deadline_dt < datetime.now(timezone.utc):
        return {
            "reason": "deadline_expired",
            "detail": f"Deadline {deadline_str} is in the past",
        }
    return None


def _format_scores(scores: Dict) -> str:
    if not scores:
        return "No scores available"
    return "\n".join(f"- {k.replace('_', ' ').title()}: {v}/10" for k, v in scores.items())


async def _llm_evaluate(grant: Dict) -> Dict[str, Any] | None:
    """Ask the LLM whether this grant should be rejected. Returns rejection dict or None."""
    company_name = _s.company_name
    scores = grant.get("scores") or {}

    prompt = GUARDRAIL_PROMPT.format(
        company_name=company_name,
        company_profile=_get_company_profile(),
        title=grant.get("title") or grant.get("grant_name", "Untitled"),
        funder=grant.get("funder", "Unknown"),
        grant_type=grant.get("grant_type", "grant"),
        amount=grant.get("amount") or "Not specified",
        currency=grant.get("currency", "USD"),
        deadline=grant.get("deadline") or "Not specified",
        geography=grant.get("geography") or "Not specified",
        eligibility=grant.get("eligibility") or "Not specified",
        themes=", ".join(grant.get("themes_detected") or []) or "None detected",
        recommended_action=grant.get("recommended_action", "unknown"),
        scores_text=_format_scores(scores),
        weighted_total=f"{grant.get('weighted_total', 0):.2f}",
        reasoning=grant.get("reasoning") or grant.get("rationale") or "No reasoning provided",
        red_flags=", ".join(grant.get("red_flags") or []) or "None",
        evidence_found="\n".join(f"- {e}" for e in (grant.get("evidence_found") or [])) or "None",
        evidence_gaps="\n".join(f"- {e}" for e in (grant.get("evidence_gaps") or [])) or "None",
    )

    try:
        raw = await chat(
            prompt,
            model=ANALYST_LIGHT,
            max_tokens=512,
            system=GUARDRAIL_SYSTEM.format(company_name=company_name),
            temperature=0.1,
        )
        result = parse_json_safe(raw)
        if not result or "decision" not in result:
            logger.warning(
                "pre_triage_guardrail: LLM returned unparseable response for '%s' — passing through",
                grant.get("title", "unknown"),
            )
            return None

        if result["decision"].lower().strip() == "reject":
            return {
                "reason": "llm_rejected",
                "detail": result.get("reason", "Rejected by AI evaluation"),
            }
        return None

    except Exception as e:
        logger.warning(
            "pre_triage_guardrail: LLM call failed for '%s': %s — passing through",
            grant.get("title", "unknown"), e,
        )
        return None


async def pre_triage_guardrail_node(state: GrantState) -> Dict:
    """LangGraph node: filter scored_grants before human triage.

    Uses LLM evaluation to reject unfit grants, passes the rest through.
    """
    scored_grants = state.get("scored_grants", [])
    if not scored_grants:
        return {
            "scored_grants": [],
            "audit_log": state.get("audit_log", []) + [{
                "node": "pre_triage_guardrail",
                "ts": datetime.now(timezone.utc).isoformat(),
                "passed": 0,
                "rejected": 0,
            }],
        }

    passed: List[Dict] = []
    rejected: List[Dict] = []
    audit_details: List[Dict] = []

    # ── Separate triage grants from non-triage (auto_pass/hold pass through) ─
    triage_grants: List[Dict] = []
    for grant in scored_grants:
        if grant.get("status") != "triage":
            passed.append(grant)
        else:
            triage_grants.append(grant)

    # ── Evaluate triage grants (deadline check + LLM, concurrent) ────────────
    sem = asyncio.Semaphore(5)

    async def evaluate_one(grant: Dict) -> tuple[str, Dict[str, Any] | None]:
        """Returns ("passed"|"rejected", rejection_info_or_None)."""
        # 1. Deterministic deadline check first
        deadline_rejection = _check_deadline(grant)
        if deadline_rejection:
            return "rejected", deadline_rejection

        # 2. LLM evaluation
        async with sem:
            llm_rejection = await _llm_evaluate(grant)
            if llm_rejection:
                return "rejected", llm_rejection
            return "passed", None

    results = await asyncio.gather(*(evaluate_one(g) for g in triage_grants))

    rejected_details: List[tuple[Dict, Dict]] = []  # (grant, rejection_info)

    for grant, (outcome, rejection) in zip(triage_grants, results):
        if outcome == "rejected" and rejection:
            grant_title = grant.get("title") or grant.get("grant_name", "unknown")
            rejected.append(grant)
            rejected_details.append((grant, rejection))
            audit_details.append({
                "grant_id": str(grant.get("_id", "")),
                "title": grant_title[:80],
                "reason": rejection["reason"],
                "detail": rejection["detail"],
            })
        else:
            passed.append(grant)

    # ── Update rejected grants in MongoDB ────────────────────────────────────
    if rejected:
        try:
            from backend.db.mongo import grants_scored, audit_logs
            from bson import ObjectId
            col = grants_scored()
            for grant, rejection in rejected_details:
                gid = grant.get("_id")
                if gid:
                    await col.update_one(
                        {"_id": ObjectId(str(gid)) if not isinstance(gid, ObjectId) else gid},
                        {"$set": {
                            "status": "guardrail_rejected",
                            "rejection_reason": rejection["detail"],
                        }},
                    )

            # Write to audit_logs collection
            await audit_logs().insert_one({
                "node": "pre_triage_guardrail",
                "action": f"Rejected {len(rejected)} grants before triage",
                "details": audit_details,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("pre_triage_guardrail: MongoDB update failed: %s", e)

        # ── Batch notification ───────────────────────────────────────────────
        try:
            from backend.notifications.hub import notify
            body_lines = [f"- {d['title']}: {d['detail']}" for d in audit_details[:5]]
            if len(audit_details) > 5:
                body_lines.append(f"... and {len(audit_details) - 5} more")
            await notify(
                event_type="pre_triage_guardrail",
                title=f"Pre-triage guardrail rejected {len(rejected)} grants",
                body="\n".join(body_lines),
                priority="low",
                metadata={"rejected_count": len(rejected), "details": audit_details},
            )
        except Exception as e:
            logger.debug("pre_triage_guardrail: notification failed: %s", e)

        # ── Log to Notion Agent Runs ─────────────────────────────────────────
        try:
            from backend.integrations.notion_sync import log_agent_run
            await log_agent_run(
                agent="pre_triage_guardrail",
                status="Success",
                trigger="Pipeline",
                started_at=datetime.now(timezone.utc),
                duration_seconds=0,
                errors=0,
                summary=(
                    f"Filtered {len(rejected)} grants "
                    f"(passed {len(passed)}): "
                    + "; ".join(d["detail"][:60] for d in audit_details[:3])
                ),
            )
        except Exception:
            logger.debug("Notion sync skipped (pre_triage_guardrail)", exc_info=True)

    logger.info(
        "Pre-triage guardrail: %d passed, %d rejected out of %d scored grants",
        len(passed), len(rejected), len(scored_grants),
    )

    audit_entry = {
        "node": "pre_triage_guardrail",
        "ts": datetime.now(timezone.utc).isoformat(),
        "passed": len(passed),
        "rejected": len(rejected),
        "rejections": audit_details,
    }

    return {
        "scored_grants": passed,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
