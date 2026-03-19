"""Tests for Pydantic model validations and domain checks in main.py.

Covers:
  - TriageResumeRequest: valid/invalid decisions, override_reason max_length
  - SectionReviewRequest: valid/invalid actions
  - UpdateGrantStatusRequest: valid/invalid statuses
  - StartDraftRequest: override_reason max_length
  - DrafterChatRequest: message max_length
  - ManualGrantRequest: field max_lengths
  - get_user_email: domain validation
"""
from __future__ import annotations

import os
import sys

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("NOTION_TOKEN", "ntn_fake_test_token")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")

from pydantic import ValidationError

from backend.main import (
    DrafterChatRequest,
    ManualGrantRequest,
    SectionReviewRequest,
    StartDraftRequest,
    TriageResumeRequest,
    UpdateGrantStatusRequest,
    _VALID_REVIEW_ACTIONS,
    _VALID_STATUSES,
    _VALID_TRIAGE_DECISIONS,
)


# ── TriageResumeRequest ─────────────────────────────────────────────────────

class TestTriageResumeRequest:
    """Validates the TriageResumeRequest Pydantic model."""

    def test_valid_pursue(self):
        req = TriageResumeRequest(
            thread_id="t1", grant_id="g1", decision="pursue"
        )
        assert req.decision == "pursue"

    def test_valid_watch(self):
        req = TriageResumeRequest(
            thread_id="t1", grant_id="g1", decision="watch"
        )
        assert req.decision == "watch"

    def test_valid_pass(self):
        req = TriageResumeRequest(
            thread_id="t1", grant_id="g1", decision="pass"
        )
        assert req.decision == "pass"

    def test_all_valid_decisions(self):
        """Every value in _VALID_TRIAGE_DECISIONS is accepted."""
        for d in _VALID_TRIAGE_DECISIONS:
            req = TriageResumeRequest(
                thread_id="t1", grant_id="g1", decision=d
            )
            assert req.decision == d

    def test_invalid_decision_delete(self):
        with pytest.raises(ValidationError, match="decision must be one of"):
            TriageResumeRequest(
                thread_id="t1", grant_id="g1", decision="delete"
            )

    def test_invalid_decision_empty(self):
        with pytest.raises(ValidationError):
            TriageResumeRequest(
                thread_id="t1", grant_id="g1", decision=""
            )

    def test_invalid_decision_uppercase(self):
        """Decision values are case-sensitive — 'Pursue' is rejected."""
        with pytest.raises(ValidationError, match="decision must be one of"):
            TriageResumeRequest(
                thread_id="t1", grant_id="g1", decision="Pursue"
            )

    def test_invalid_decision_auto_pass(self):
        """'auto_pass' is a status, not a valid triage decision."""
        with pytest.raises(ValidationError, match="decision must be one of"):
            TriageResumeRequest(
                thread_id="t1", grant_id="g1", decision="auto_pass"
            )

    def test_override_reason_within_limit(self):
        req = TriageResumeRequest(
            thread_id="t1",
            grant_id="g1",
            decision="pursue",
            human_override=True,
            override_reason="A" * 1000,  # exactly at limit
        )
        assert len(req.override_reason) == 1000

    def test_override_reason_exceeds_limit(self):
        with pytest.raises(ValidationError):
            TriageResumeRequest(
                thread_id="t1",
                grant_id="g1",
                decision="pursue",
                human_override=True,
                override_reason="A" * 1001,  # 1 over limit
            )

    def test_notes_max_length(self):
        req = TriageResumeRequest(
            thread_id="t1",
            grant_id="g1",
            decision="watch",
            notes="B" * 2000,
        )
        assert len(req.notes) == 2000

    def test_notes_exceeds_max_length(self):
        with pytest.raises(ValidationError):
            TriageResumeRequest(
                thread_id="t1",
                grant_id="g1",
                decision="watch",
                notes="B" * 2001,
            )

    def test_optional_fields_default_none(self):
        req = TriageResumeRequest(
            thread_id="t1", grant_id="g1", decision="pursue"
        )
        assert req.notes is None
        assert req.override_reason is None
        assert req.human_override is False


# ── SectionReviewRequest ─────────────────────────────────────────────────────

class TestSectionReviewRequest:
    """Validates the SectionReviewRequest Pydantic model."""

    def test_valid_approve(self):
        req = SectionReviewRequest(
            thread_id="t1", section_name="Problem Statement", action="approve"
        )
        assert req.action == "approve"

    def test_valid_revise(self):
        req = SectionReviewRequest(
            thread_id="t1", section_name="Budget", action="revise",
            instructions="Add more detail to line items."
        )
        assert req.action == "revise"

    def test_all_valid_actions(self):
        for a in _VALID_REVIEW_ACTIONS:
            req = SectionReviewRequest(
                thread_id="t1", section_name="s", action=a
            )
            assert req.action == a

    def test_invalid_action_reject(self):
        with pytest.raises(ValidationError, match="action must be one of"):
            SectionReviewRequest(
                thread_id="t1", section_name="s", action="reject"
            )

    def test_invalid_action_delete(self):
        with pytest.raises(ValidationError, match="action must be one of"):
            SectionReviewRequest(
                thread_id="t1", section_name="s", action="delete"
            )

    def test_instructions_max_length(self):
        req = SectionReviewRequest(
            thread_id="t1", section_name="s", action="revise",
            instructions="X" * 5000,
        )
        assert len(req.instructions) == 5000

    def test_instructions_exceeds_max_length(self):
        with pytest.raises(ValidationError):
            SectionReviewRequest(
                thread_id="t1", section_name="s", action="revise",
                instructions="X" * 5001,
            )


# ── UpdateGrantStatusRequest ─────────────────────────────────────────────────

class TestUpdateGrantStatusRequest:
    """Validates the UpdateGrantStatusRequest Pydantic model."""

    def test_valid_statuses(self):
        """Every value in _VALID_STATUSES is accepted."""
        for s in _VALID_STATUSES:
            req = UpdateGrantStatusRequest(grant_id="g1", status=s)
            assert req.status == s

    def test_invalid_status_deleted(self):
        with pytest.raises(ValidationError, match="status must be one of"):
            UpdateGrantStatusRequest(grant_id="g1", status="deleted")

    def test_invalid_status_empty(self):
        with pytest.raises(ValidationError):
            UpdateGrantStatusRequest(grant_id="g1", status="")

    def test_invalid_status_uppercase(self):
        with pytest.raises(ValidationError, match="status must be one of"):
            UpdateGrantStatusRequest(grant_id="g1", status="Pursue")

    def test_invalid_status_random(self):
        with pytest.raises(ValidationError, match="status must be one of"):
            UpdateGrantStatusRequest(grant_id="g1", status="invalid")

    def test_all_known_statuses_present(self):
        """Verify the set covers at least the core pipeline statuses."""
        core_statuses = {
            "triage", "pursue", "pursuing", "watch", "drafting",
            "draft_complete", "submitted", "won", "passed", "auto_pass",
            "human_passed", "hold", "reported",
        }
        assert core_statuses.issubset(_VALID_STATUSES), (
            f"Missing core statuses: {core_statuses - _VALID_STATUSES}"
        )


# ── StartDraftRequest ────────────────────────────────────────────────────────

class TestStartDraftRequest:
    """Validates the StartDraftRequest Pydantic model."""

    def test_minimal(self):
        req = StartDraftRequest(grant_id="g1")
        assert req.grant_id == "g1"
        assert req.thread_id is None
        assert req.override_guardrails is False

    def test_override_reason_at_limit(self):
        req = StartDraftRequest(
            grant_id="g1",
            override_guardrails=True,
            override_reason="R" * 1000,
        )
        assert len(req.override_reason) == 1000

    def test_override_reason_over_limit(self):
        with pytest.raises(ValidationError):
            StartDraftRequest(
                grant_id="g1",
                override_guardrails=True,
                override_reason="R" * 1001,
            )


# ── DrafterChatRequest ───────────────────────────────────────────────────────

class TestDrafterChatRequest:
    """Validates the DrafterChatRequest Pydantic model."""

    def test_valid_request(self):
        req = DrafterChatRequest(
            grant_id="g1", section_name="Budget", message="Refine the budget."
        )
        assert req.message == "Refine the budget."

    def test_message_at_limit(self):
        req = DrafterChatRequest(
            grant_id="g1", section_name="s", message="M" * 10000
        )
        assert len(req.message) == 10000

    def test_message_over_limit(self):
        with pytest.raises(ValidationError):
            DrafterChatRequest(
                grant_id="g1", section_name="s", message="M" * 10001
            )


# ── ManualGrantRequest ───────────────────────────────────────────────────────

class TestManualGrantRequest:
    """Validates the ManualGrantRequest Pydantic model."""

    def test_valid_minimal(self):
        req = ManualGrantRequest(url="https://example.com/grant")
        assert req.url == "https://example.com/grant"
        assert req.title_override == ""

    def test_title_override_max_length(self):
        req = ManualGrantRequest(
            url="https://example.com", title_override="T" * 500
        )
        assert len(req.title_override) == 500

    def test_title_override_over_limit(self):
        with pytest.raises(ValidationError):
            ManualGrantRequest(
                url="https://example.com", title_override="T" * 501
            )

    def test_notes_over_limit(self):
        with pytest.raises(ValidationError):
            ManualGrantRequest(
                url="https://example.com", notes="N" * 2001
            )


# ── get_user_email ───────────────────────────────────────────────────────────

class TestGetUserEmail:
    """Tests the get_user_email FastAPI dependency function.

    The function is a sync dependency that reads the X-User-Email header.
    We call it directly with the header value to test validation.
    """

    def test_no_header_returns_system(self):
        from backend.main import get_user_email
        assert get_user_email(None) == "system"

    def test_empty_header_returns_system(self):
        from backend.main import get_user_email
        assert get_user_email("") == "system"

    def test_valid_domain(self):
        from backend.main import get_user_email
        result = get_user_email("gowtham@altcarbon.com")
        assert result == "gowtham@altcarbon.com"

    def test_valid_domain_case_insensitive(self):
        from backend.main import get_user_email
        result = get_user_email("Gowtham@AltCarbon.COM")
        assert result == "gowtham@altcarbon.com"

    def test_invalid_domain_rejected(self):
        from backend.main import get_user_email
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_user_email("hacker@evil.com")
        assert exc_info.value.status_code == 403
        assert "Unauthorized email domain" in exc_info.value.detail

    def test_no_at_sign_passes_through(self):
        """A value without '@' is not treated as an email — passes through."""
        from backend.main import get_user_email
        result = get_user_email("system")
        assert result == "system"

    def test_whitespace_stripped(self):
        from backend.main import get_user_email
        result = get_user_email("  gowtham@altcarbon.com  ")
        assert result == "gowtham@altcarbon.com"
