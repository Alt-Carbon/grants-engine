"""Unit tests for _apply_hard_rules() and _parse_date().

No API keys, no MongoDB, no network calls — pure Python only.

Run:
    python -m pytest backend/benchmarks/test_hard_rules.py -v
    python -m backend.benchmarks.test_hard_rules
"""
import sys
import unittest
from unittest.mock import MagicMock

# ── Inject mocks BEFORE importing analyst ──────────────────────────────────────
# analyst.py has module-level imports from DB, LLM, and graph modules.
# We stub them out here so no connection attempt is made.
_MOCK_MODS = [
    "backend.db.mongo",
    "backend.graph.state",
    "backend.utils.llm",
    "backend.utils.parsing",
    "httpx",
    "bson",
]
for _m in _MOCK_MODS:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

# SONNET constant is referenced at analyst module level
sys.modules["backend.utils.llm"].SONNET = "claude-sonnet-4-6"

from backend.agents.analyst import _apply_hard_rules, _parse_date  # noqa: E402


class TestApplyHardRules(unittest.TestCase):
    """12 deterministic tests for _apply_hard_rules().

    Rule 1: minimum funding threshold (default $3,000)
    Rule 2: deadline already passed
    """

    # ── Funding threshold ─────────────────────────────────────────────────────

    def test_01_below_threshold(self):
        """$2,999 is below the $3,000 minimum — must be disqualified."""
        result = _apply_hard_rules({"max_funding_usd": 2999})
        self.assertIsNotNone(result, "Expected disqualification for $2,999")
        self.assertIn("3,000", result, "Reason should mention the $3,000 threshold")

    def test_02_exactly_at_threshold(self):
        """$3,000 exactly — at the boundary, must PASS (rule is strictly less-than)."""
        result = _apply_hard_rules({"max_funding_usd": 3000})
        self.assertIsNone(result, "Expected $3,000 to pass (≥ minimum boundary)")

    def test_03_zero_funding(self):
        """max_funding_usd=0 is treated as unknown/unset via falsy OR — must pass."""
        result = _apply_hard_rules({"max_funding_usd": 0})
        self.assertIsNone(result, "max_funding_usd=0 should pass (treated as unknown)")

    def test_04_none_funding(self):
        """max_funding_usd=None — funding unknown, benefit of doubt, must pass."""
        result = _apply_hard_rules({"max_funding_usd": None})
        self.assertIsNone(result, "None funding should pass (no information to disqualify)")

    def test_05_fallback_max_funding_field(self):
        """max_funding=2000 (fallback field when max_funding_usd absent) — must fail."""
        result = _apply_hard_rules({"max_funding": 2000})
        self.assertIsNotNone(result, "max_funding=2000 should fail via fallback field check")
        self.assertIn("3,000", result)

    # ── Deadline ──────────────────────────────────────────────────────────────

    def test_06_past_deadline(self):
        """Deadline in 2020 has clearly passed — must be disqualified."""
        result = _apply_hard_rules({"deadline": "2020-01-01"})
        self.assertIsNotNone(result, "Passed deadline should be disqualified")
        self.assertIn("Deadline", result, "Reason should mention 'Deadline'")

    def test_07_future_deadline(self):
        """Deadline in 2099 is in the future — must pass."""
        result = _apply_hard_rules({"deadline": "2099-12-31"})
        self.assertIsNone(result, "Far-future deadline should pass")

    def test_08_rolling_deadline(self):
        """'rolling' is in _ROLLING_TERMS and is not parseable as a date — must pass."""
        result = _apply_hard_rules({"deadline": "rolling"})
        self.assertIsNone(result, "'rolling' deadline should pass (rolling term, not a date)")

    def test_09_ongoing_deadline(self):
        """'ongoing' is in _ROLLING_TERMS — must pass."""
        result = _apply_hard_rules({"deadline": "ongoing"})
        self.assertIsNone(result, "'ongoing' deadline should pass")

    def test_10_none_deadline(self):
        """deadline=None — no date to parse, must pass."""
        result = _apply_hard_rules({"deadline": None})
        self.assertIsNone(result, "None deadline should pass")

    def test_11_empty_string_deadline(self):
        """deadline='' — empty string, must pass (falsy guard in _parse_date)."""
        result = _apply_hard_rules({"deadline": ""})
        self.assertIsNone(result, "Empty string deadline should pass")

    # ── Combined rules ────────────────────────────────────────────────────────

    def test_12_both_fail_funding_wins(self):
        """Both funding AND deadline fail — Rule 1 (funding) is checked first and wins."""
        result = _apply_hard_rules({"max_funding": 500, "deadline": "2020-01-01"})
        self.assertIsNotNone(result, "Should disqualify when both rules are violated")
        # Rule 1 (funding) executes before Rule 2 (deadline)
        self.assertIn(
            "3,000", result,
            "Funding rule should be the reported disqualification reason (Rule 1 before Rule 2)",
        )


class TestParseDate(unittest.TestCase):
    """Sanity checks for _parse_date() — exercises the date parsing paths."""

    def test_iso_format_parses(self):
        d = _parse_date("2026-09-30")
        self.assertIsNotNone(d)
        self.assertEqual(d.year, 2026)
        self.assertEqual(d.month, 9)
        self.assertEqual(d.day, 30)

    def test_rolling_terms_return_none(self):
        for term in ("rolling", "ongoing", "open", "tbd", "year-round"):
            with self.subTest(term=term):
                self.assertIsNone(_parse_date(term), f"'{term}' should return None")

    def test_none_returns_none(self):
        self.assertIsNone(_parse_date(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_parse_date(""))

    def test_slash_format_parses(self):
        d = _parse_date("31/12/2027")
        self.assertIsNotNone(d)
        self.assertEqual(d.year, 2027)

    def test_written_month_parses(self):
        d = _parse_date("March 15, 2028")
        self.assertIsNotNone(d)
        self.assertEqual(d.year, 2028)
        self.assertEqual(d.month, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
