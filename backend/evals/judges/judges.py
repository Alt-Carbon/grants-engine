"""Judge executors — call LLM with judge prompts, parse scores, log results.

Each judge function:
1. Formats the prompt with the agent's output
2. Calls the LLM
3. Parses the JSON response
4. Logs the result to scores.jsonl
5. Returns the parsed scores

Usage:
    from backend.evals.judges.judges import judge_draft_section
    result = await judge_draft_section(section_data, grant_data, prompt_version="v1.0")
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from backend.evals.judges.prompts import (
    SCOUT_JUDGE_PROMPT,
    DRAFTER_JUDGE_PROMPT,
    REVIEWER_JUDGE_PROMPT,
    OUTCOME_JUDGE_PROMPT,
)

logger = logging.getLogger(__name__)

SCORES_FILE = Path(__file__).parent.parent / "results" / "scores.jsonl"


def _parse_json(raw: str) -> Dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _log_score(entry: Dict) -> None:
    """Append a score entry to the JSONL log."""
    SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCORES_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


async def _call_judge(prompt: str, temperature: float = 0.1) -> Dict:
    """Call the LLM judge and parse the JSON response."""
    from backend.utils.llm import chat, ANALYST_HEAVY
    raw = await chat(prompt, model=ANALYST_HEAVY, max_tokens=1500, temperature=temperature)
    return _parse_json(raw)


# ── Scout Judge ───────────────────────────────────────────────────────────────

async def judge_scout_result(
    grant: Dict,
    prompt_version: str = "v1.0",
) -> Dict:
    """Evaluate a single scraped grant opportunity."""
    prompt = SCOUT_JUDGE_PROMPT.format(
        title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", "Unknown"),
        url=grant.get("url", ""),
        geography=grant.get("geography", "Not specified"),
        funding=grant.get("amount") or grant.get("max_funding_usd") or "Not specified",
        deadline=grant.get("deadline", "Not specified"),
        eligibility=grant.get("eligibility", "Not specified"),
        themes=", ".join(grant.get("themes_detected", [])),
        raw_content=(grant.get("raw_content", "") or "")[:2000],
    )

    result = await _call_judge(prompt)

    _log_score({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "scout",
        "prompt_version": prompt_version,
        "grant_id": grant.get("url_hash", ""),
        "grant_title": grant.get("title", ""),
        "scores": result.get("scores", {}),
        "overall": result.get("overall", 0),
        "reasoning": result.get("reasoning", ""),
    })

    return result


# ── Drafter Judge ─────────────────────────────────────────────────────────────

async def judge_draft_section(
    section_name: str,
    content: str,
    word_count: int,
    word_limit: int,
    grant: Dict,
    criteria: List[Dict] = None,
    prompt_version: str = "v1.0",
) -> Dict:
    """Evaluate a single draft section."""
    criteria_text = ""
    if criteria:
        criteria_text = "\n".join(
            f"- {c.get('criterion', '')}: {c.get('description', '')} ({c.get('weight', '')})"
            for c in criteria
        )
    else:
        criteria_text = "No explicit criteria — evaluate for clarity, evidence, and impact."

    prompt = DRAFTER_JUDGE_PROMPT.format(
        grant_title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", "Unknown"),
        themes=", ".join(grant.get("themes_detected", [])),
        criteria=criteria_text,
        section_name=section_name,
        word_limit=word_limit,
        word_count=word_count,
        content=content[:8000],
    )

    result = await _call_judge(prompt)

    _log_score({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "drafter",
        "prompt_version": prompt_version,
        "grant_id": str(grant.get("_id", "")),
        "grant_title": grant.get("title", ""),
        "section": section_name,
        "scores": result.get("scores", {}),
        "overall": result.get("overall", 0),
        "top_weakness": result.get("top_weakness", ""),
    })

    return result


# ── Reviewer Meta-Judge ───────────────────────────────────────────────────────

async def judge_reviewer(
    review: Dict,
    grant: Dict,
    draft_excerpt: str,
    perspective: str,
    prompt_version: str = "v1.0",
) -> Dict:
    """Evaluate a reviewer agent's feedback quality."""
    prompt = REVIEWER_JUDGE_PROMPT.format(
        grant_title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", "Unknown"),
        perspective=perspective,
        draft_excerpt=draft_excerpt[:4000],
        reviewer_score=review.get("overall_score", "N/A"),
        verdict=review.get("verdict", "N/A"),
        summary=review.get("summary", ""),
        top_issues=json.dumps(review.get("top_issues", [])),
        strengths=json.dumps(review.get("strengths", [])),
    )

    result = await _call_judge(prompt)

    _log_score({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": f"reviewer_{perspective}",
        "prompt_version": prompt_version,
        "grant_id": str(grant.get("_id", "")),
        "grant_title": grant.get("title", ""),
        "scores": result.get("scores", {}),
        "overall": result.get("overall", 0),
        "missed_issues": result.get("missed_issues", []),
        "false_positives": result.get("false_positives", []),
    })

    return result


# ── Outcome Judge (uses real results for ground truth) ────────────────────────

async def judge_outcome_prediction(
    grant: Dict,
    outcome_doc: Dict,
    review_funder: Optional[Dict] = None,
    review_scientific: Optional[Dict] = None,
    prompt_version: str = "v1.0",
) -> Dict:
    """Evaluate system prediction accuracy against real grant outcome."""
    prompt = OUTCOME_JUDGE_PROMPT.format(
        grant_title=grant.get("title") or grant.get("grant_name", ""),
        funder=grant.get("funder", "Unknown"),
        analyst_score=grant.get("weighted_total", "N/A"),
        funder_review_score=review_funder.get("overall_score", "N/A") if review_funder else "N/A",
        scientific_review_score=review_scientific.get("overall_score", "N/A") if review_scientific else "N/A",
        system_verdict=review_funder.get("verdict", "N/A") if review_funder else "N/A",
        actual_outcome=outcome_doc.get("outcome", "unknown"),
        funder_feedback=outcome_doc.get("feedback", "No feedback provided"),
    )

    result = await _call_judge(prompt)

    _log_score({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "outcome_prediction",
        "prompt_version": prompt_version,
        "grant_id": str(grant.get("_id", "")),
        "grant_title": grant.get("title", ""),
        "actual_outcome": outcome_doc.get("outcome"),
        "analyst_score": grant.get("weighted_total"),
        "scores": result.get("scores", {}),
        "overall": result.get("overall", 0),
        "blind_spots": result.get("blind_spots", []),
        "correctly_predicted": result.get("correctly_predicted", []),
    })

    return result


# ── Score Analysis ────────────────────────────────────────────────────────────

def load_scores(agent: Optional[str] = None) -> List[Dict]:
    """Load all scores from the JSONL log, optionally filtered by agent."""
    if not SCORES_FILE.exists():
        return []
    entries = []
    with open(SCORES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if agent and entry.get("agent") != agent:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def score_summary(agent: Optional[str] = None) -> Dict:
    """Compute summary statistics from the score log."""
    entries = load_scores(agent)
    if not entries:
        return {"total_evals": 0}

    # Group by agent
    by_agent: Dict[str, List[Dict]] = {}
    for e in entries:
        a = e.get("agent", "unknown")
        by_agent.setdefault(a, []).append(e)

    summary = {"total_evals": len(entries), "agents": {}}
    for agent_name, agent_entries in by_agent.items():
        overalls = [e.get("overall", 0) for e in agent_entries if e.get("overall")]
        summary["agents"][agent_name] = {
            "count": len(agent_entries),
            "avg_overall": round(sum(overalls) / len(overalls), 2) if overalls else 0,
            "min_overall": min(overalls) if overalls else 0,
            "max_overall": max(overalls) if overalls else 0,
        }

        # Per-dimension averages
        all_dims: Dict[str, List] = {}
        for e in agent_entries:
            for dim, val in (e.get("scores") or {}).items():
                all_dims.setdefault(dim, []).append(val)
        summary["agents"][agent_name]["dimensions"] = {
            dim: round(sum(vals) / len(vals), 2)
            for dim, vals in all_dims.items()
        }

    return summary


def compare_versions(v1: str, v2: str, agent: Optional[str] = None) -> Dict:
    """Compare scores between two prompt versions."""
    entries = load_scores(agent)
    v1_entries = [e for e in entries if e.get("prompt_version") == v1]
    v2_entries = [e for e in entries if e.get("prompt_version") == v2]

    def _avg(entries: List[Dict]) -> float:
        overalls = [e.get("overall", 0) for e in entries if e.get("overall")]
        return round(sum(overalls) / len(overalls), 2) if overalls else 0

    return {
        "v1": {"version": v1, "count": len(v1_entries), "avg_overall": _avg(v1_entries)},
        "v2": {"version": v2, "count": len(v2_entries), "avg_overall": _avg(v2_entries)},
        "delta": round(_avg(v2_entries) - _avg(v1_entries), 2),
        "improved": _avg(v2_entries) > _avg(v1_entries),
    }
