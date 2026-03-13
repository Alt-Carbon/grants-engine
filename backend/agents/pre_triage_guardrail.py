"""Pre-Triage Guardrail — deterministic filter on scored grants before human triage.

No LLM calls. Rejects grants that are expired, off-topic, or clearly below threshold.
Runs AFTER analyst scoring but BEFORE the human triage queue.

Checks (only on grants with status == "triage"):
  1. weighted_total < 4.0 → reject
  2. scores.theme_alignment <= 2 → reject
  3. Deadline expired → reject

Grants with non-triage status (auto_pass, hold) pass through unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.agents.analyst import parse_deadline
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)

SCORE_FLOOR = 4.0
THEME_ALIGNMENT_FLOOR = 2


def _check_grant(grant: Dict) -> Dict[str, Any] | None:
    """Check a single triage grant. Returns rejection reason dict or None if passed."""
    # 1. Low overall score
    weighted_total = grant.get("weighted_total", 0)
    if weighted_total < SCORE_FLOOR:
        return {
            "reason": "low_score",
            "detail": f"weighted_total {weighted_total:.2f} < {SCORE_FLOOR}",
        }

    # 2. Theme alignment too low
    scores = grant.get("scores") or {}
    theme_alignment = scores.get("theme_alignment", 0)
    if theme_alignment <= THEME_ALIGNMENT_FLOOR:
        return {
            "reason": "low_theme_alignment",
            "detail": f"theme_alignment {theme_alignment} <= {THEME_ALIGNMENT_FLOOR}",
        }

    # 3. Deadline expired
    deadline_str = grant.get("deadline")
    if deadline_str:
        deadline_dt = parse_deadline(deadline_str)
        if deadline_dt and deadline_dt < datetime.now(timezone.utc):
            return {
                "reason": "deadline_expired",
                "detail": f"deadline {deadline_str} is in the past",
            }

    return None


async def pre_triage_guardrail_node(state: GrantState) -> Dict:
    """LangGraph node: filter scored_grants before human triage.

    Rejects bad grants (updates MongoDB status), passes the rest through.
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

    for grant in scored_grants:
        # Only filter triage-status grants; let auto_pass/hold/etc pass through
        if grant.get("status") != "triage":
            passed.append(grant)
            continue

        rejection = _check_grant(grant)
        if rejection:
            grant_title = grant.get("title") or grant.get("grant_name", "unknown")
            rejected.append(grant)
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
            from backend.db.mongo import grants_scored
            from backend.db.sqlite import audit_logs
            from bson import ObjectId
            col = grants_scored()
            for grant in rejected:
                gid = grant.get("_id")
                if gid:
                    await col.update_one(
                        {"_id": ObjectId(str(gid)) if not isinstance(gid, ObjectId) else gid},
                        {"$set": {"status": "guardrail_rejected"}},
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
            titles = [d["title"] for d in audit_details[:5]]
            body_lines = [f"- {d['title']}: {d['reason']}" for d in audit_details[:5]]
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
                    + ", ".join(d["reason"] for d in audit_details[:3])
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
