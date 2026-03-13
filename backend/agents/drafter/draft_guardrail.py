"""Draft Guardrail — AI-powered gate between grant_reader and drafter.

Runs two layers of checks:
  1. Deterministic: deadline freshness (re-parse from grant doc)
  2. LLM-powered: thematic scope, eligibility, exclusions, open/closed status

On failure: updates grant status → guardrail_rejected, fires notification, logs to Notion.
On LLM error: fail-open (pass through with warning) — don't block on infra errors.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from backend.agents.analyst import parse_deadline
from backend.utils.llm import chat, ANALYST_LIGHT

logger = logging.getLogger(__name__)

# ── AltCarbon profile for LLM context ────────────────────────────────────────
_PROFILE_PATH = "backend/knowledge/altcarbon_profile.md"


def _load_profile() -> str:
    try:
        with open(_PROFILE_PATH) as f:
            return f.read()[:6000]
    except Exception:
        return (
            "Alt Carbon: Indian deep-tech climate & data science startup. "
            "CDR via Enhanced Rock Weathering (ERW) and Biochar. "
            "HQ Bengaluru (IISc Campus), operations Darjeeling & Eastern India. "
            "For-profit, growth-stage. Sectors: Climate Tech, AgriTech, Earth Sciences, Deep Tech."
        )


# ── Deterministic check ──────────────────────────────────────────────────────

def _check_deadline_fresh(grant: Dict, grant_requirements: Dict) -> Dict[str, Any]:
    """Re-check deadline from both scored record and parsed grant doc."""
    now = datetime.now(timezone.utc)

    # Try parsed grant doc deadline first (most up-to-date)
    submission = (grant_requirements or {}).get("submission") or {}
    doc_deadline_str = submission.get("deadline")
    doc_dt = parse_deadline(doc_deadline_str) if doc_deadline_str else None

    # Fall back to scored record deadline
    scored_deadline_str = grant.get("deadline")
    scored_dt = parse_deadline(scored_deadline_str) if scored_deadline_str else None

    deadline_dt = doc_dt or scored_dt

    if deadline_dt is None:
        return {"check": "deadline_fresh", "passed": True, "reason": "No parseable deadline — treat as open"}

    if deadline_dt < now:
        return {
            "check": "deadline_fresh",
            "passed": False,
            "reason": f"Grant deadline {deadline_dt.strftime('%Y-%m-%d')} has expired (now: {now.strftime('%Y-%m-%d')})",
        }

    return {"check": "deadline_fresh", "passed": True, "reason": f"Deadline {deadline_dt.strftime('%Y-%m-%d')} is still open"}


# ── LLM-powered checks ──────────────────────────────────────────────────────

GUARDRAIL_PROMPT = """You are a grant eligibility screener for Alt Carbon, an Indian climate-tech startup.

COMPANY PROFILE:
{profile}

GRANT DOCUMENT (parsed):
Title: {title}
Funder: {funder}
Eligibility checklist: {eligibility}
Evaluation criteria: {criteria}
Budget: {budget}
Submission: {submission}

GRANT RAW TEXT (first 4000 chars):
{raw_doc}

Evaluate this grant on 4 dimensions. For each, give a verdict (pass/fail) and a one-line reason.

1. THEMATIC SCOPE — Does this grant fund work in CDR, climate tech, agritech, earth sciences, or deep tech? Would Alt Carbon's ERW/Biochar work be considered in-scope?
2. ELIGIBILITY — Can Alt Carbon (Indian for-profit startup, growth-stage, based in Bengaluru) meet ALL mandatory eligibility requirements? Check geography, org type, sector, and stage requirements.
3. GRANT STATUS — Based on the full text, is this grant program currently open for applications? Or is it closed, expired, future cycle only, or invitation-only?
4. EXCLUSIONS — Does any "what we don't fund" or exclusion section specifically exclude Alt Carbon's type of work (CDR, soil amendment, rock weathering, biochar, climate tech)?

Respond ONLY with valid JSON:
{{
  "thematic_scope": {{"verdict": "pass"|"fail", "reason": "..."}},
  "eligibility": {{"verdict": "pass"|"fail", "reason": "..."}},
  "grant_status": {{"verdict": "pass"|"fail", "reason": "..."}},
  "exclusions": {{"verdict": "pass"|"fail", "reason": "..."}},
  "overall_verdict": "pass"|"fail",
  "rejection_reason": "one-line summary if failed, null if passed"
}}"""


async def _llm_guardrail_check(
    grant: Dict,
    grant_requirements: Dict,
    raw_doc: str,
    profile: str,
) -> Dict[str, Any]:
    """Run LLM-powered eligibility/scope check."""
    eligibility = grant_requirements.get("eligibility_checklist", [])
    criteria = grant_requirements.get("evaluation_criteria", [])
    budget = grant_requirements.get("budget", {})
    submission = grant_requirements.get("submission", {})

    prompt = GUARDRAIL_PROMPT.format(
        profile=profile,
        title=grant.get("title") or grant.get("grant_name") or "Unknown",
        funder=grant.get("funder") or "Unknown",
        eligibility=json.dumps(eligibility, default=str)[:2000],
        criteria=json.dumps(criteria, default=str)[:1500],
        budget=json.dumps(budget, default=str)[:500],
        submission=json.dumps(submission, default=str)[:500],
        raw_doc=(raw_doc or "")[:4000],
    )

    raw = await chat(prompt, model=ANALYST_LIGHT, max_tokens=1024)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


# ── Main guardrail node ─────────────────────────────────────────────────────

async def draft_guardrail_node(state: dict) -> dict:
    """LangGraph node: validate grant before drafting."""
    from backend.db.mongo import grants_scored, grants_pipeline
    from bson import ObjectId

    grant_id = state.get("selected_grant_id")
    grant_requirements = state.get("grant_requirements") or {}
    raw_doc = state.get("grant_raw_doc") or ""
    override = state.get("override_guardrails", False)

    # Load grant from DB
    grant = {}
    if grant_id:
        try:
            grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
        except Exception:
            pass

    profile = _load_profile()
    checks = []
    overall_passed = True

    # ── 1. Deadline freshness ────────────────────────────────────────────────
    deadline_check = _check_deadline_fresh(grant, grant_requirements)
    checks.append(deadline_check)
    if not deadline_check["passed"]:
        overall_passed = False

    # ── 2. LLM-powered checks ───────────────────────────────────────────────
    llm_result = None
    try:
        llm_result = await _llm_guardrail_check(grant, grant_requirements, raw_doc, profile)
        checks.append({"check": "llm_guardrail", "passed": llm_result.get("overall_verdict") == "pass", "detail": llm_result})
        if llm_result.get("overall_verdict") != "pass":
            overall_passed = False
    except Exception as e:
        # Fail-open: LLM errors don't block drafting
        logger.warning("draft_guardrail: LLM check failed (fail-open): %s", e)
        checks.append({"check": "llm_guardrail", "passed": True, "reason": f"LLM check failed — fail-open: {e}"})

    # ── Override: force pass but preserve check results ──────────────────────
    if override and not overall_passed:
        logger.info("draft_guardrail: override active — forcing pass for grant %s", grant_id)
        overall_passed = True

    result = {
        "passed": overall_passed,
        "checks": checks,
        "llm_result": llm_result,
        "override_applied": override and not all(c["passed"] for c in checks),
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    # ── If failed: update grant status + notify ─────────────────────────────
    if not overall_passed:
        rejection_reason = (
            (llm_result or {}).get("rejection_reason")
            or next((c["reason"] for c in checks if not c["passed"]), "Failed guardrail checks")
        )
        result["rejection_reason"] = rejection_reason

        # Update grant status
        if grant_id:
            try:
                await grants_scored().update_one(
                    {"_id": ObjectId(grant_id)},
                    {"$set": {"status": "guardrail_rejected"}},
                )
            except Exception as e:
                logger.warning("draft_guardrail: failed to update grant status: %s", e)

        # Update pipeline record
        pipeline_id = state.get("pipeline_id")
        if pipeline_id:
            try:
                await grants_pipeline().update_one(
                    {"_id": ObjectId(pipeline_id)},
                    {"$set": {"status": "guardrail_rejected", "guardrail_result": result}},
                )
            except Exception as e:
                logger.warning("draft_guardrail: failed to update pipeline: %s", e)

        # Fire notification
        try:
            from backend.notifications.hub import notify
            grant_title = grant.get("title") or grant.get("grant_name") or grant_id
            await notify(
                event_type="guardrail_rejected",
                title=f"Draft blocked: {grant_title[:60]}",
                body=rejection_reason[:200],
                priority="high",
                metadata={"grant_id": grant_id, "checks": checks},
            )
        except Exception as e:
            logger.warning("draft_guardrail: notification failed: %s", e)

        # Log to Notion
        try:
            from backend.integrations.notion_sync import log_error
            await log_error(
                agent="draft_guardrail",
                error=f"Grant rejected: {rejection_reason}",
                grant_name=grant.get("title") or grant.get("grant_name") or "",
                severity="Warning",
            )
        except Exception as e:
            logger.warning("draft_guardrail: Notion log failed: %s", e)

    audit_entry = {
        "node": "draft_guardrail",
        "ts": datetime.now(timezone.utc).isoformat(),
        "passed": overall_passed,
        "checks_summary": [{"check": c["check"], "passed": c["passed"]} for c in checks],
        "override": override,
    }

    return {
        "draft_guardrail_result": result,
        "audit_log": state.get("audit_log", []) + [audit_entry],
    }
