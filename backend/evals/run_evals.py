"""Unified eval runner for all Grants Engine agents.

Usage:
    python -m backend.evals.run_evals                           # eval all agents
    python -m backend.evals.run_evals --agent drafter           # eval one agent
    python -m backend.evals.run_evals --agent outcome           # eval prediction accuracy
    python -m backend.evals.run_evals --report                  # print score summary
    python -m backend.evals.run_evals --compare v1.0 v1.1       # A/B test prompt versions
    python -m backend.evals.run_evals --prompt-version v1.1     # tag scores with a version

Agents evaluated:
  - scout: evaluates scraped grant quality (relevance, eligibility, data quality)
  - drafter: evaluates draft section quality (funder alignment, evidence, clarity)
  - reviewer: meta-evaluates reviewer feedback quality (specificity, accuracy)
  - outcome: evaluates prediction accuracy against real grant outcomes
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Dict, List, Optional

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Stub MongoDB for CLI usage
from unittest.mock import MagicMock
for _m in ["bson"]:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()


async def eval_scout(prompt_version: str, limit: int = 10) -> List[Dict]:
    """Evaluate recent scout results."""
    from backend.db.mongo import grants_raw
    from backend.evals.judges.judges import judge_scout_result

    docs = await grants_raw().find({}).sort("scraped_at", -1).limit(limit).to_list(limit)
    if not docs:
        print("  No scout results found")
        return []

    results = []
    for doc in docs:
        doc["_id"] = str(doc.get("_id", ""))
        try:
            result = await judge_scout_result(doc, prompt_version=prompt_version)
            results.append(result)
            title = (doc.get("title") or "")[:40]
            print(f"  {result.get('overall', 0):.1f}/5  {title}")
        except Exception as e:
            print(f"  ERROR: {doc.get('title', '')[:40]} — {e}")

    if results:
        avg = sum(r.get("overall", 0) for r in results) / len(results)
        print(f"\n  Scout avg: {avg:.2f}/5 ({len(results)} evaluated)")

    return results


async def eval_drafter(prompt_version: str, limit: int = 5) -> List[Dict]:
    """Evaluate recent draft sections."""
    from backend.db.mongo import grant_drafts, grants_scored
    from backend.evals.judges.judges import judge_draft_section
    from bson import ObjectId

    drafts = await grant_drafts().find({}).sort("created_at", -1).limit(limit).to_list(limit)
    if not drafts:
        print("  No drafts found")
        return []

    results = []
    for draft in drafts:
        grant_id = draft.get("grant_id", "")
        grant = {}
        if grant_id:
            try:
                grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
            except Exception:
                pass

        deep = grant.get("deep_analysis") or {}
        criteria = deep.get("evaluation_criteria") or []

        for sec_name, sec_data in (draft.get("sections") or {}).items():
            try:
                result = await judge_draft_section(
                    section_name=sec_name,
                    content=sec_data.get("content", ""),
                    word_count=sec_data.get("word_count", 0),
                    word_limit=sec_data.get("word_limit", 500),
                    grant=grant,
                    criteria=criteria,
                    prompt_version=prompt_version,
                )
                results.append(result)
                print(f"  {result.get('overall', 0):.1f}/5  {sec_name[:30]}  weakness: {result.get('top_weakness', '')[:50]}")
            except Exception as e:
                print(f"  ERROR: {sec_name} — {e}")

    if results:
        avg = sum(r.get("overall", 0) for r in results) / len(results)
        print(f"\n  Drafter avg: {avg:.2f}/5 ({len(results)} sections evaluated)")

    return results


async def eval_reviewer(prompt_version: str, limit: int = 5) -> List[Dict]:
    """Meta-evaluate recent reviewer outputs."""
    from backend.db.mongo import draft_reviews, grants_scored, grant_drafts
    from backend.evals.judges.judges import judge_reviewer
    from bson import ObjectId

    reviews = await draft_reviews().find({}).sort("created_at", -1).limit(limit * 2).to_list(limit * 2)
    if not reviews:
        print("  No reviews found")
        return []

    results = []
    for review in reviews[:limit]:
        grant_id = review.get("grant_id", "")
        grant = {}
        draft_text = ""
        if grant_id:
            try:
                grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
                draft = await grant_drafts().find_one({"grant_id": grant_id}, sort=[("version", -1)])
                if draft:
                    sections = draft.get("sections", {})
                    draft_text = "\n\n".join(f"## {n}\n{s.get('content', '')}" for n, s in sections.items())
            except Exception:
                pass

        perspective = review.get("perspective", "unknown")
        try:
            result = await judge_reviewer(
                review=review,
                grant=grant,
                draft_excerpt=draft_text[:4000],
                perspective=perspective,
                prompt_version=prompt_version,
            )
            results.append(result)
            grant_title = (grant.get("title") or "")[:30]
            print(f"  {result.get('overall', 0):.1f}/5  {perspective:<12}  {grant_title}")
        except Exception as e:
            print(f"  ERROR: {perspective} review — {e}")

    if results:
        avg = sum(r.get("overall", 0) for r in results) / len(results)
        print(f"\n  Reviewer avg: {avg:.2f}/5 ({len(results)} evaluated)")

    return results


async def eval_outcomes(prompt_version: str) -> List[Dict]:
    """Evaluate prediction accuracy against real grant outcomes."""
    from backend.db.mongo import grant_outcomes, grants_scored, draft_reviews
    from backend.evals.judges.judges import judge_outcome_prediction
    from bson import ObjectId

    outcomes = await grant_outcomes().find({"outcome": {"$in": ["won", "rejected"]}}).to_list(50)
    if not outcomes:
        print("  No outcomes recorded — record won/rejected grants first")
        return []

    results = []
    for outcome in outcomes:
        grant_id = outcome.get("grant_id", "")
        grant = {}
        funder_review = None
        scientific_review = None

        if grant_id:
            try:
                grant = await grants_scored().find_one({"_id": ObjectId(grant_id)}) or {}
                reviews = await draft_reviews().find({"grant_id": grant_id}).to_list(5)
                for r in reviews:
                    if r.get("perspective") == "funder":
                        funder_review = r
                    elif r.get("perspective") == "scientific":
                        scientific_review = r
            except Exception:
                pass

        try:
            result = await judge_outcome_prediction(
                grant=grant,
                outcome_doc=outcome,
                review_funder=funder_review,
                review_scientific=scientific_review,
                prompt_version=prompt_version,
            )
            results.append(result)
            title = outcome.get("grant_title", "")[:30]
            actual = outcome.get("outcome", "?")
            print(f"  {result.get('overall', 0):.1f}/5  {actual:<10}  {title}  blind_spots: {len(result.get('blind_spots', []))}")
        except Exception as e:
            print(f"  ERROR: {outcome.get('grant_title', '')[:30]} — {e}")

    if results:
        avg = sum(r.get("overall", 0) for r in results) / len(results)
        print(f"\n  Outcome prediction avg: {avg:.2f}/5 ({len(results)} evaluated)")

    return results


def print_report() -> None:
    """Print summary of all eval scores."""
    from backend.evals.judges.judges import score_summary

    summary = score_summary()
    if summary["total_evals"] == 0:
        print("No eval scores recorded yet. Run evals first.")
        return

    print(f"\n{'=' * 50}")
    print("  GRANTS ENGINE — EVAL REPORT")
    print(f"{'=' * 50}")
    print(f"\n  Total evaluations: {summary['total_evals']}\n")

    for agent, data in summary.get("agents", {}).items():
        print(f"  {agent.upper()}")
        print(f"    Evals: {data['count']}  |  Avg: {data['avg_overall']:.2f}/5  |  Range: {data['min_overall']:.1f} - {data['max_overall']:.1f}")
        dims = data.get("dimensions", {})
        if dims:
            dim_strs = [f"{k}: {v:.1f}" for k, v in dims.items()]
            print(f"    Dimensions: {', '.join(dim_strs)}")
        print()

    print(f"{'=' * 50}\n")


def print_comparison(v1: str, v2: str, agent: Optional[str] = None) -> None:
    """Print A/B comparison between prompt versions."""
    from backend.evals.judges.judges import compare_versions

    result = compare_versions(v1, v2, agent)
    agent_label = agent.upper() if agent else "ALL AGENTS"

    print(f"\n  A/B COMPARISON — {agent_label}")
    print(f"  {v1}: avg {result['v1']['avg_overall']:.2f}/5 ({result['v1']['count']} evals)")
    print(f"  {v2}: avg {result['v2']['avg_overall']:.2f}/5 ({result['v2']['count']} evals)")
    delta = result["delta"]
    direction = "improved" if result["improved"] else "regressed" if delta < 0 else "unchanged"
    print(f"  Delta: {'+' if delta > 0 else ''}{delta:.2f} ({direction})\n")


async def run_all(prompt_version: str) -> None:
    """Run evals for all agents."""
    print("\n--- SCOUT EVAL ---")
    await eval_scout(prompt_version)

    print("\n--- DRAFTER EVAL ---")
    await eval_drafter(prompt_version)

    print("\n--- REVIEWER EVAL ---")
    await eval_reviewer(prompt_version)

    print("\n--- OUTCOME PREDICTION EVAL ---")
    await eval_outcomes(prompt_version)

    print("\n--- SUMMARY ---")
    print_report()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grants Engine Agent Evaluator")
    parser.add_argument("--agent", choices=["scout", "drafter", "reviewer", "outcome"], help="Evaluate a specific agent")
    parser.add_argument("--report", action="store_true", help="Print score summary")
    parser.add_argument("--compare", nargs=2, metavar=("V1", "V2"), help="Compare two prompt versions")
    parser.add_argument("--prompt-version", default="v1.0", help="Tag scores with a prompt version")
    parser.add_argument("--limit", type=int, default=5, help="Max items to evaluate per agent")
    args = parser.parse_args()

    if args.report:
        print_report()
        return

    if args.compare:
        print_comparison(args.compare[0], args.compare[1], args.agent)
        return

    if args.agent:
        agent_fn = {
            "scout": lambda: eval_scout(args.prompt_version, args.limit),
            "drafter": lambda: eval_drafter(args.prompt_version, args.limit),
            "reviewer": lambda: eval_reviewer(args.prompt_version, args.limit),
            "outcome": lambda: eval_outcomes(args.prompt_version),
        }[args.agent]
        asyncio.run(agent_fn())
    else:
        asyncio.run(run_all(args.prompt_version))


if __name__ == "__main__":
    main()
