"""Smoke tests for the audit fix changes.

No API keys, no MongoDB, no network — pure Python unit tests.

Run:
    python3 -m pytest backend/tests/test_smoke_audit_fixes.py -v
"""
import sys
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# ── Stub external modules before importing application code ──────────────────
_MOCK_MODS = [
    "backend.db.mongo",
    "backend.db.pinecone_store",
    "backend.graph.state",
    "backend.utils.llm",
    "backend.utils.parsing",
    "backend.config.settings",
    "backend.agents.drafter.theme_profiles",
    "backend.agents.preference_learner",
    "backend.agents.feedback_learner",
    "backend.agents.agent_context",
    "backend.integrations.notion_sync",
    "httpx",
    "bson",
]
for _m in _MOCK_MODS:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

# Stub LLM constants
sys.modules["backend.utils.llm"].DRAFTER_DEFAULT = "test-model"
sys.modules["backend.utils.llm"].ANALYST_LIGHT = "test-model"
sys.modules["backend.utils.llm"].ANALYST_HEAVY = "test-model"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Temperature fallback — `is not None` fix
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemperatureFallback(unittest.TestCase):
    """Verify that temperature=0 is respected (not treated as falsy)."""

    def test_zero_temperature_not_falsy(self):
        """0 is a valid temperature — must not fall through to default."""
        # Simulate the fixed logic from main.py
        grant_temp = 0
        theme_temp = 0.7
        global_temp = 0.4
        default_temp = 0.4

        _gt = grant_temp
        _tt = theme_temp
        _dt = global_temp
        _at = default_temp
        result = _gt if _gt is not None else (_tt if _tt is not None else (_dt if _dt is not None else _at))

        self.assertEqual(result, 0, "Temperature 0 should be used, not skipped")

    def test_none_temperature_falls_through(self):
        """None should fall through to the next level."""
        _gt = None
        _tt = None
        _dt = 0.3
        _at = 0.4
        result = _gt if _gt is not None else (_tt if _tt is not None else (_dt if _dt is not None else _at))

        self.assertEqual(result, 0.3, "Should fall through None to global (0.3)")

    def test_all_none_uses_default(self):
        """All None → use agent default."""
        _gt = None
        _tt = None
        _dt = None
        _at = 0.4
        result = _gt if _gt is not None else (_tt if _tt is not None else (_dt if _dt is not None else _at))

        self.assertEqual(result, 0.4, "All None should use agent default (0.4)")

    def test_drafter_node_temperature_fix(self):
        """Simulate the drafter_node.py theme_settings temperature fix."""
        theme_settings = {"temperature": 0}
        drafter_cfg = {"temperature": 0.5}

        # Fixed logic
        result = theme_settings.get("temperature") if theme_settings.get("temperature") is not None else drafter_cfg.get("temperature")
        self.assertEqual(result, 0, "Theme temperature 0 should override drafter_cfg")

        # Old broken logic (for comparison)
        broken = theme_settings.get("temperature") or drafter_cfg.get("temperature")
        self.assertEqual(broken, 0.5, "Old logic would wrongly skip 0")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Source stripping helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestSourceStripping(unittest.TestCase):
    """Verify _strip_sources removes attribution blocks."""

    @staticmethod
    def _strip_sources(text: str) -> str:
        """Copy of the helper from main.py."""
        import re
        text = re.sub(
            r"\n---\n\*{0,2}Sources?\*{0,2}:?.*",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ).rstrip()
        return text

    def test_strips_bold_sources(self):
        content = "Some draft content here.\n\n---\n**Sources:** Company Profile, Grant Analysis"
        result = self._strip_sources(content)
        self.assertEqual(result, "Some draft content here.")

    def test_strips_plain_sources(self):
        content = "Draft text.\n\n---\nSources: Company Profile"
        result = self._strip_sources(content)
        self.assertEqual(result, "Draft text.")

    def test_strips_multiline_sources(self):
        content = "Draft.\n\n---\n**Sources:**\n- Company Profile\n- Knowledge Base\n- Notion (Live)"
        result = self._strip_sources(content)
        self.assertEqual(result, "Draft.")

    def test_no_sources_unchanged(self):
        content = "Clean content with no source block."
        result = self._strip_sources(content)
        self.assertEqual(result, content)

    def test_strips_source_singular(self):
        content = "Text here.\n\n---\n**Source:** Grant Analysis"
        result = self._strip_sources(content)
        self.assertEqual(result, "Text here.")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Word limit hard enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestWordLimitEnforcement(unittest.TestCase):
    """Verify hard truncation logic from section_writer.py."""

    @staticmethod
    def _enforce_word_limit(content: str, word_limit: int):
        """Copy of the enforcement logic."""
        word_count = len(content.split())
        word_limit_exceeded = False

        if word_count > word_limit * 1.1:
            words = content.split()
            truncated = " ".join(words[:word_limit])
            last_period = truncated.rfind(".")
            if last_period > len(truncated) * 0.7:
                truncated = truncated[:last_period + 1]
            content = truncated
            word_count = len(content.split())
            word_limit_exceeded = True

        return content, word_count, word_limit_exceeded

    def test_within_limit_not_truncated(self):
        content = " ".join(["word"] * 100)
        result, wc, exceeded = self._enforce_word_limit(content, 200)
        self.assertFalse(exceeded)
        self.assertEqual(wc, 100)

    def test_slightly_over_not_truncated(self):
        """Within 10% over → not truncated."""
        content = " ".join(["word"] * 108)
        result, wc, exceeded = self._enforce_word_limit(content, 100)
        self.assertFalse(exceeded)
        self.assertEqual(wc, 108)

    def test_over_10_percent_truncated(self):
        """More than 10% over → truncated to word_limit."""
        content = " ".join(["word"] * 150)
        result, wc, exceeded = self._enforce_word_limit(content, 100)
        self.assertTrue(exceeded)
        self.assertLessEqual(wc, 100)

    def test_truncation_prefers_sentence_boundary(self):
        """Truncation should end at a period if possible."""
        # Build content with a period at word 80
        words = ["word"] * 79 + ["end."] + ["word"] * 70  # 150 words
        content = " ".join(words)
        result, wc, exceeded = self._enforce_word_limit(content, 100)
        self.assertTrue(exceeded)
        self.assertTrue(result.endswith("."), f"Expected sentence boundary, got: ...{result[-20:]}")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Coherence gate for ready_for_export
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoherenceGate(unittest.TestCase):
    """Verify coherence score is a hard gate for ready_for_export."""

    @staticmethod
    def _compute_ready(funder_verdict, scientific_verdict, coherence_score):
        """Copy of the logic from dual_reviewer.py."""
        verdicts = [funder_verdict, scientific_verdict]
        ready = all(v in ("strong_submit", "submit_with_revisions") for v in verdicts) and coherence_score >= 5.0
        return ready

    def test_high_scores_low_coherence_not_ready(self):
        """9/9 substance but 2/10 coherence → NOT ready."""
        ready = self._compute_ready("strong_submit", "strong_submit", 2.0)
        self.assertFalse(ready, "Low coherence should block export")

    def test_all_good_is_ready(self):
        ready = self._compute_ready("strong_submit", "submit_with_revisions", 7.5)
        self.assertTrue(ready)

    def test_coherence_exactly_5_is_ready(self):
        ready = self._compute_ready("strong_submit", "strong_submit", 5.0)
        self.assertTrue(ready)

    def test_coherence_4_9_not_ready(self):
        ready = self._compute_ready("strong_submit", "strong_submit", 4.9)
        self.assertFalse(ready)

    def test_bad_verdict_good_coherence_not_ready(self):
        ready = self._compute_ready("major_revisions", "strong_submit", 8.0)
        self.assertFalse(ready)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Cross-reviewer contradiction detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestContradictionDetection(unittest.TestCase):
    """Verify contradiction detection logic."""

    @staticmethod
    def _detect_contradiction(funder_verdict, scientific_verdict):
        """Copy of the logic from dual_reviewer.py."""
        submit_verdicts = {"strong_submit", "submit_with_revisions"}
        reject_verdicts = {"major_revisions", "do_not_submit"}
        if (funder_verdict in submit_verdicts and scientific_verdict in reject_verdicts) or \
           (scientific_verdict in submit_verdicts and funder_verdict in reject_verdicts):
            return {
                "funder_verdict": funder_verdict,
                "scientific_verdict": scientific_verdict,
                "explanation": f"Funder says '{funder_verdict}' but scientific says '{scientific_verdict}'.",
            }
        return None

    def test_submit_vs_major_revisions(self):
        result = self._detect_contradiction("strong_submit", "major_revisions")
        self.assertIsNotNone(result)
        self.assertIn("funder_verdict", result)

    def test_do_not_submit_vs_submit(self):
        result = self._detect_contradiction("do_not_submit", "submit_with_revisions")
        self.assertIsNotNone(result)

    def test_both_submit_no_contradiction(self):
        result = self._detect_contradiction("strong_submit", "submit_with_revisions")
        self.assertIsNone(result)

    def test_both_reject_no_contradiction(self):
        result = self._detect_contradiction("major_revisions", "do_not_submit")
        self.assertIsNone(result)

    def test_same_verdict_no_contradiction(self):
        result = self._detect_contradiction("strong_submit", "strong_submit")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Prior sections summary construction
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriorSectionsSummary(unittest.TestCase):
    """Verify the cross-section context builder."""

    @staticmethod
    def _build_summary(approved_sections):
        """Copy of logic from drafter_node.py."""
        if not approved_sections:
            return ""
        summary_parts = []
        for sec_name, sec_data in approved_sections.items():
            content = sec_data.get("content", "")
            sentences = [s.strip() for s in content.split(".") if s.strip()][:3]
            summary = ". ".join(sentences) + "." if sentences else ""
            wc = sec_data.get("word_count", 0)
            summary_parts.append(f"**{sec_name}** ({wc} words): {summary[:300]}")
        return "\n".join(summary_parts)

    def test_empty_sections_empty_string(self):
        self.assertEqual(self._build_summary({}), "")

    def test_single_section_summary(self):
        sections = {
            "Problem Statement": {
                "content": "Climate change is accelerating. ERW offers a path. Alt Carbon deploys basalt.",
                "word_count": 12,
            }
        }
        result = self._build_summary(sections)
        self.assertIn("**Problem Statement**", result)
        self.assertIn("12 words", result)
        self.assertIn("Climate change is accelerating", result)

    def test_truncates_to_3_sentences(self):
        sections = {
            "Long Section": {
                "content": "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five.",
                "word_count": 10,
            }
        }
        result = self._build_summary(sections)
        self.assertIn("Sentence three", result)
        self.assertNotIn("Sentence four", result)

    def test_multiple_sections(self):
        sections = {
            "Section A": {"content": "Content A.", "word_count": 2},
            "Section B": {"content": "Content B.", "word_count": 2},
        }
        result = self._build_summary(sections)
        self.assertIn("**Section A**", result)
        self.assertIn("**Section B**", result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. WRITE_PROMPT contains key improvements
# ═══════════════════════════════════════════════════════════════════════════════

class TestWritePromptImprovements(unittest.TestCase):
    """Verify the WRITE_PROMPT contains expected improvements."""

    @classmethod
    def setUpClass(cls):
        # Import is safe because we stubbed dependencies above
        from backend.agents.drafter.section_writer import WRITE_PROMPT
        cls.prompt = WRITE_PROMPT

    def test_has_inline_examples(self):
        self.assertIn("WRONG:", self.prompt)
        self.assertIn("RIGHT:", self.prompt)

    def test_has_expanded_banned_list(self):
        self.assertIn('"novel"', self.prompt)
        self.assertIn('"transformative"', self.prompt)
        self.assertIn('"pioneering"', self.prompt)

    def test_has_section_specific_guidance(self):
        self.assertIn("SECTION-SPECIFIC GUIDANCE:", self.prompt)
        self.assertIn("Problem Statement", self.prompt)
        self.assertIn("Lead with the gap", self.prompt)

    def test_has_preflight_checklist(self):
        self.assertIn("Before finishing, re-read and check", self.prompt)

    def test_has_paragraph_structure_example(self):
        self.assertIn("Finding → Evidence → Implication → Justification", self.prompt)
        self.assertIn("LA-ICP-MS reduces per-sample", self.prompt)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. SELF_CRITIQUE_PROMPT has rubrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestSelfCritiqueRubrics(unittest.TestCase):
    """Verify SELF_CRITIQUE_PROMPT has scoring rubrics."""

    @classmethod
    def setUpClass(cls):
        from backend.agents.drafter.section_writer import SELF_CRITIQUE_PROMPT
        cls.prompt = SELF_CRITIQUE_PROMPT

    def test_has_rubric_scores(self):
        self.assertIn("1 = Multiple evaluation criteria completely missing", self.prompt)
        self.assertIn("5 = Every criterion explicitly addressed", self.prompt)

    def test_has_specificity_rubric(self):
        self.assertIn("automatic score of 1 if ANY found", self.prompt)

    def test_has_funder_alignment_rubric(self):
        self.assertIn("1 = Generic", self.prompt)
        self.assertIn("5 = Reads as if written specifically", self.prompt)

    def test_quotes_weaknesses(self):
        self.assertIn("quote the problematic sentence", self.prompt)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. REVISION_PROMPT is substantial
# ═══════════════════════════════════════════════════════════════════════════════

class TestRevisionPrompt(unittest.TestCase):
    """Verify REVISION_PROMPT is no longer minimal."""

    @classmethod
    def setUpClass(cls):
        from backend.agents.drafter.section_writer import REVISION_PROMPT
        cls.prompt = REVISION_PROMPT

    def test_has_revision_rules(self):
        self.assertIn("REVISION RULES:", self.prompt)

    def test_has_preserve_evidence(self):
        self.assertIn("Preserve all factual content", self.prompt)

    def test_has_word_limit_reminder(self):
        self.assertIn("word limit", self.prompt)

    def test_not_minimal(self):
        self.assertGreater(len(self.prompt), 500, "REVISION_PROMPT should be substantial (>500 chars)")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Context limit increases
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextLimits(unittest.TestCase):
    """Verify context limits were increased."""

    def test_evidence_gap_max_attempts_is_5(self):
        from backend.agents.drafter.section_writer import EVIDENCE_RESOLVE_MAX_ATTEMPTS
        self.assertEqual(EVIDENCE_RESOLVE_MAX_ATTEMPTS, 5)

    def test_section_context_default_is_10000(self):
        import inspect
        from backend.agents.drafter.section_writer import get_section_context
        sig = inspect.signature(get_section_context)
        default = sig.parameters["max_chars"].default
        self.assertEqual(default, 10000)


if __name__ == "__main__":
    unittest.main()
