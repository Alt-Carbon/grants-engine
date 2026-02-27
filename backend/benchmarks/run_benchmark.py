"""Analyst agent accuracy benchmark runner.

Usage:
    python -m backend.benchmarks.run_benchmark
    python -m backend.benchmarks.run_benchmark --only-hard-rules   # fast, no API key
    python -m backend.benchmarks.run_benchmark --fixture bezos_cdr_2026
    python -m backend.benchmarks.run_benchmark --save-results

Cost estimate per full run: ~$0.05 (20 Claude Sonnet calls, no Perplexity).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock

# ── Stub MongoDB and LangGraph state BEFORE importing analyst ──────────────────
# _score_grant / _apply_hard_rules / _build_scored_doc never touch the DB.
# Mocking prevents connection errors when running outside the full stack.
for _m in ["backend.db.mongo", "backend.graph.state", "bson"]:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

# ── Import analyst internals (safe after mocking) ──────────────────────────────
from backend.agents.analyst import (  # noqa: E402
    _apply_hard_rules,
    _score_grant,
    DEFAULT_WEIGHTS,
)
from backend.benchmarks.fixtures import (  # noqa: E402
    ALL_FIXTURES,
    LLM_FIXTURES,
    HARD_RULE_FIXTURES,
    GrantFixture,
)

# ─────────────────────────────────────────────────────────────────────────────
# Required fields — 29 top-level + 6 score sub-dimensions = 35 total
# (scores dict is one top-level key that contains 6 dimensions)
# ─────────────────────────────────────────────────────────────────────────────
REQUIRED_TOP_LEVEL_FIELDS = [
    "raw_grant_id", "url_hash", "content_hash", "grant_name", "title",
    "funder", "grant_type", "url", "application_url", "amount",
    "max_funding", "max_funding_usd", "currency", "deadline", "geography",
    "eligibility", "themes_detected", "scores", "weighted_total",
    "rationale", "reasoning", "evidence_found", "evidence_gaps", "red_flags",
    "funder_context", "recommended_action", "status", "scored_at", "scoring_error",
]
REQUIRED_SCORE_DIMENSIONS = list(DEFAULT_WEIGHTS.keys())
# Total: 29 top-level + 6 score dims = 35 checkable fields per document
TOTAL_REQUIRED_FIELDS = len(REQUIRED_TOP_LEVEL_FIELDS) + len(REQUIRED_SCORE_DIMENSIONS)


# ─────────────────────────────────────────────────────────────────────────────
# Canonical hard-rule test cases (12 deterministic checks, no LLM)
# Mirrors test_hard_rules.py but run inline for the terminal report.
# ─────────────────────────────────────────────────────────────────────────────
_HARD_RULE_CASES: list[tuple] = [
    # (label, grant_dict, expect_fail, description)
    (
        "below_threshold_2999",
        {"max_funding_usd": 2999},
        True,
        "max_funding_usd=2,999 → below $3K minimum",
    ),
    (
        "at_threshold_3000",
        {"max_funding_usd": 3000},
        False,
        "max_funding_usd=3,000 → exactly at limit, passes",
    ),
    (
        "zero_funding",
        {"max_funding_usd": 0},
        False,
        "max_funding_usd=0 → unknown (falsy), passes",
    ),
    (
        "none_funding",
        {"max_funding_usd": None},
        False,
        "max_funding_usd=None → unknown, passes",
    ),
    (
        "fallback_field_2000",
        {"max_funding": 2000},
        True,
        "max_funding=2,000 (fallback field) → fails",
    ),
    (
        "past_deadline_2020",
        {"deadline": "2020-01-01"},
        True,
        "deadline='2020-01-01' → has passed",
    ),
    (
        "future_deadline_2099",
        {"deadline": "2099-12-31"},
        False,
        "deadline='2099-12-31' → future, passes",
    ),
    (
        "rolling_deadline",
        {"deadline": "rolling"},
        False,
        "deadline='rolling' → rolling term, passes",
    ),
    (
        "ongoing_deadline",
        {"deadline": "ongoing"},
        False,
        "deadline='ongoing' → rolling term, passes",
    ),
    (
        "none_deadline",
        {"deadline": None},
        False,
        "deadline=None → no date, passes",
    ),
    (
        "empty_deadline",
        {"deadline": ""},
        False,
        "deadline='' → empty, passes",
    ),
    (
        "both_fail_funding_wins",
        {"max_funding": 500, "deadline": "2020-01-01"},
        True,
        "both fail: funding=$500 AND deadline=2020 → funding rule wins (Rule 1)",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Runners
# ─────────────────────────────────────────────────────────────────────────────

def run_hard_rules_section() -> tuple[int, int, list[dict]]:
    """Execute the 12 canonical hard-rule checks. Returns (passed, total, rows)."""
    rows = []
    passed = 0
    for label, grant_dict, expect_fail, desc in _HARD_RULE_CASES:
        result = _apply_hard_rules(grant_dict)
        got_fail = result is not None
        ok = got_fail == expect_fail
        if ok:
            passed += 1
        rows.append(
            {
                "label": label,
                "desc": desc,
                "expected_fail": expect_fail,
                "got": result,
                "pass": ok,
            }
        )
    return passed, len(_HARD_RULE_CASES), rows


def check_hard_rule_fixture(fixture: GrantFixture) -> dict:
    """Verify that a hard-rule fixture is caught by _apply_hard_rules."""
    reason = _apply_hard_rules(fixture.grant)
    ok = reason is not None
    return {
        "id": fixture.id,
        "name": fixture.name,
        "expected": "auto_pass",
        "got_action": "auto_pass" if ok else "PASSED_HARD_RULES_UNEXPECTEDLY",
        "score": 0.0,
        "pass": ok,
        "reasoning": reason or "",
        "error": None if ok else "Hard rule did not trigger — expected disqualification",
    }


async def score_fixture(fixture: GrantFixture) -> dict:
    """Score one LLM fixture via _score_grant(). Returns a result row."""
    t0 = time.perf_counter()
    try:
        doc = await _score_grant(
            grant=fixture.grant,
            funder_context="",      # skip Perplexity — reduces cost, keeps benchmark fast
            weights=DEFAULT_WEIGHTS,
            min_funding=3_000,
        )
        elapsed = time.perf_counter() - t0

        action = doc["recommended_action"]
        score = doc["weighted_total"]

        accepted = fixture.accept_actions or [fixture.expected_action]
        action_ok = action in accepted

        score_ok = True
        if fixture.score_min is not None and score < fixture.score_min:
            score_ok = False
        if fixture.score_max is not None and score > fixture.score_max:
            score_ok = False

        return {
            "id": fixture.id,
            "name": fixture.name,
            "expected": fixture.expected_action,
            "accept_actions": accepted,
            "got_action": action,
            "score": score,
            "score_min": fixture.score_min,
            "score_max": fixture.score_max,
            "action_ok": action_ok,
            "score_ok": score_ok,
            "pass": action_ok and score_ok,
            "elapsed": round(elapsed, 2),
            "doc": doc,
            "error": None,
        }
    except Exception as exc:
        return {
            "id": fixture.id,
            "name": fixture.name,
            "expected": fixture.expected_action,
            "accept_actions": fixture.accept_actions or [fixture.expected_action],
            "got_action": "ERROR",
            "score": 0.0,
            "score_min": fixture.score_min,
            "score_max": fixture.score_max,
            "action_ok": False,
            "score_ok": False,
            "pass": False,
            "elapsed": round(time.perf_counter() - t0, 2),
            "doc": None,
            "error": str(exc),
        }


def check_field_completeness(llm_results: list[dict]) -> tuple[bool, list[str]]:
    """Verify all required fields exist in every successfully scored document."""
    issues: list[str] = []
    for r in llm_results:
        doc = r.get("doc")
        if not doc:
            continue
        for f in REQUIRED_TOP_LEVEL_FIELDS:
            if f not in doc:
                issues.append(f"{r['id']}: missing top-level field '{f}'")
        scores_dict = doc.get("scores") or {}
        for dim in REQUIRED_SCORE_DIMENSIONS:
            if dim not in scores_dict:
                issues.append(f"{r['id']}: missing score dimension '{dim}'")
    return len(issues) == 0, issues


def compute_calibration(all_results: list[dict]) -> dict:
    """Compute average weighted_total per action bucket and check ordering."""
    buckets: dict[str, list[float]] = {"pursue": [], "watch": [], "auto_pass": []}
    for r in all_results:
        action = r.get("got_action", "")
        score = r.get("score", 0.0)
        if action in buckets:
            buckets[action].append(score)

    avgs: dict[str, float] = {
        k: round(sum(v) / len(v), 2) if v else 0.0
        for k, v in buckets.items()
    }
    cal_ok = avgs.get("pursue", 0) > avgs.get("watch", 0) > avgs.get("auto_pass", 0)
    return {"averages": avgs, "calibration_ok": cal_ok}


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────
_W = 44
_BAR = "━" * _W
_CHK = "✓"
_CRS = "✗"


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.0f}%" if d else "N/A"


def print_report(
    hr_passed: int,
    hr_total: int,
    hr_rows: list[dict],
    hard_fixture_results: list[dict],
    llm_results: list[dict],
    calibration: dict,
    field_ok: bool,
    field_issues: list[str],
    only_hard_rules: bool = False,
) -> None:
    print(f"\n{_BAR}")
    print("  ALTCARBON ANALYST BENCHMARK REPORT")
    print(_BAR)

    # ── Hard-rule canonical tests ──────────────────────────────────────────────
    print(f"\nHARD RULES  ({hr_total} cases, no LLM)")
    for r in hr_rows:
        mark = _CHK if r["pass"] else _CRS
        expect_str = "disqualifies" if r["expected_fail"] else "passes    "
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {mark}  {r['label']:<32}  → {expect_str}")
        if not r["pass"]:
            print(f"           expected_fail={r['expected_fail']}  got={r['got']!r}")
    print(f"  Score: {hr_passed}/{hr_total} ({_pct(hr_passed, hr_total)})")

    if only_hard_rules:
        print(f"\n{_BAR}")
        print(f"OVERALL (hard rules only): {hr_passed}/{hr_total} ({_pct(hr_passed, hr_total)})")
        print(f"{_BAR}\n")
        return

    # ── Hard-rule fixture verification ─────────────────────────────────────────
    hr_fix_passed = sum(1 for r in hard_fixture_results if r["pass"])
    print(f"\nHARD-RULE FIXTURE VERIFICATION  ({len(hard_fixture_results)} fixtures)")
    for r in hard_fixture_results:
        mark = _CHK if r["pass"] else _CRS
        reas = (r.get("reasoning") or "")[:70]
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {mark}  {r['id']:<32}  {reas!r}")
        if r.get("error"):
            print(f"           ERROR: {r['error']}")
    print(f"  Score: {hr_fix_passed}/{len(hard_fixture_results)} ({_pct(hr_fix_passed, len(hard_fixture_results))})")

    # ── LLM accuracy ──────────────────────────────────────────────────────────
    print(f"\nACCURACY BENCHMARK  ({len(llm_results)} LLM-scored fixtures)")
    print(f"  {'ID':<30} {'Expected':<10} {'Got':<10} {'Score':>6}  Status")
    print("  " + "-" * (_W + 10))

    by_expected: dict[str, tuple[int, int]] = {}
    for r in llm_results:
        mark = _CHK if r["pass"] else _CRS
        score_str = f"{r['score']:5.1f}" if r.get("score") is not None else "  -  "
        got = r["got_action"][:9]
        exp = r["expected"][:9]
        print(f"  {r['id']:<30} {exp:<10} {got:<10} {score_str}  {'PASS' if r['pass'] else 'FAIL'}  {mark}")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")
        p, t = by_expected.get(r["expected"], (0, 0))
        by_expected[r["expected"]] = (p + (1 if r["pass"] else 0), t + 1)

    total_llm_passed = sum(1 for r in llm_results if r["pass"])
    print()
    for action in ["pursue", "watch", "auto_pass"]:
        p, t = by_expected.get(action, (0, 0))
        if t:
            label = f"{action.replace('_', '-')} accuracy:"
            print(f"  {label:<26} {p}/{t}  ({_pct(p, t)})")
    print(f"  {'Overall accuracy:':<26} {total_llm_passed}/{len(llm_results)}  ({_pct(total_llm_passed, len(llm_results))})")

    # ── Calibration ────────────────────────────────────────────────────────────
    avgs = calibration["averages"]
    cal_ok = calibration["calibration_ok"]
    print(f"\nCALIBRATION CHECK")
    print(f"  Avg pursue score:    {avgs.get('pursue', 0):.1f}")
    print(f"  Avg watch score:     {avgs.get('watch', 0):.1f}")
    print(f"  Avg auto_pass score: {avgs.get('auto_pass', 0):.1f}")
    cal_str = f"PASS {_CHK} (pursue > watch > auto_pass)" if cal_ok else f"FAIL {_CRS} (ordering violated)"
    print(f"  Calibration: {cal_str}")

    # ── Field completeness ─────────────────────────────────────────────────────
    print(f"\nFIELD COMPLETENESS  ({TOTAL_REQUIRED_FIELDS} required fields per document)")
    if field_ok:
        print(f"  All {TOTAL_REQUIRED_FIELDS} required fields present: PASS {_CHK}")
    else:
        print(f"  FAIL {_CRS} — {len(field_issues)} issue(s):")
        for issue in field_issues[:15]:
            print(f"    - {issue}")
        if len(field_issues) > 15:
            print(f"    ... and {len(field_issues) - 15} more")

    # ── Overall ────────────────────────────────────────────────────────────────
    # 12 hard-rule unit tests + 20 LLM accuracy tests = 32 total checks
    total_checks = hr_total + len(llm_results)
    total_passed = hr_passed + total_llm_passed
    print(f"\n{_BAR}")
    print(f"OVERALL: {total_passed}/{total_checks} checks passed ({_pct(total_passed, total_checks)})")
    print(f"{_BAR}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main async entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_benchmark(args: argparse.Namespace) -> None:
    # Always run the canonical hard-rule section (instant, no LLM)
    hr_passed, hr_total, hr_rows = run_hard_rules_section()

    if args.only_hard_rules:
        print_report(
            hr_passed, hr_total, hr_rows,
            hard_fixture_results=[],
            llm_results=[],
            calibration={"averages": {}, "calibration_ok": True},
            field_ok=True,
            field_issues=[],
            only_hard_rules=True,
        )
        return

    # Select fixtures
    if args.fixture:
        selected_llm = [f for f in LLM_FIXTURES if f.id == args.fixture]
        selected_hard = [f for f in HARD_RULE_FIXTURES if f.id == args.fixture]
        if not selected_llm and not selected_hard:
            all_ids = [f.id for f in ALL_FIXTURES]
            print(f"ERROR: fixture '{args.fixture}' not found.")
            print(f"Available IDs: {', '.join(all_ids)}")
            sys.exit(1)
    else:
        selected_llm = LLM_FIXTURES
        selected_hard = HARD_RULE_FIXTURES

    # Hard-rule fixture verification (no LLM)
    hard_fixture_results = [check_hard_rule_fixture(f) for f in selected_hard]

    # LLM scoring (concurrent, max 5 simultaneous calls)
    if selected_llm:
        print(f"\nScoring {len(selected_llm)} fixture(s) via Claude Sonnet… (may take ~1 min)")
        sem = asyncio.Semaphore(5)

        async def _score(f: GrantFixture) -> dict:
            async with sem:
                return await score_fixture(f)

        llm_results = list(await asyncio.gather(*(_score(f) for f in selected_llm)))
    else:
        llm_results = []

    # Calibration: combine LLM results with hard-rule fixture results (score=0, auto_pass)
    calibration_inputs = llm_results + [
        {"got_action": "auto_pass", "score": 0.0}
        for r in hard_fixture_results
        if r["pass"]
    ]
    calibration = compute_calibration(calibration_inputs)

    field_ok, field_issues = check_field_completeness(llm_results)

    print_report(
        hr_passed, hr_total, hr_rows,
        hard_fixture_results=hard_fixture_results,
        llm_results=llm_results,
        calibration=calibration,
        field_ok=field_ok,
        field_issues=field_issues,
    )

    if args.save_results:
        safe_results = [
            {k: v for k, v in r.items() if k != "doc"}
            for r in llm_results
        ]
        output = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "hard_rules": {
                "passed": hr_passed,
                "total": hr_total,
                "results": hr_rows,
            },
            "hard_rule_fixtures": hard_fixture_results,
            "llm_accuracy": {
                "passed": sum(1 for r in llm_results if r["pass"]),
                "total": len(llm_results),
                "results": safe_results,
            },
            "calibration": calibration,
            "field_completeness": {"ok": field_ok, "issues": field_issues},
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(__file__).parent / f"results_{ts}.json"
        out_path.write_text(json.dumps(output, indent=2, default=str))
        print(f"Results saved → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AltCarbon Analyst Agent Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--only-hard-rules",
        action="store_true",
        help="Run only the 12 canonical hard-rule tests (no LLM, no API key needed)",
    )
    parser.add_argument(
        "--fixture",
        metavar="ID",
        help="Run a single fixture by ID (e.g. bezos_cdr_2026)",
    )
    parser.add_argument(
        "--save-results",
        action="store_true",
        help="Dump full results to a timestamped JSON file in backend/benchmarks/",
    )
    args = parser.parse_args()
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
