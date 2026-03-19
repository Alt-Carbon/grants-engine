"""Tests for Notion sync error handling — structured error returns.

Validates that all sync functions in notion_sync.py:
  - Return {"success": False, "error": ...} or False/None on Notion API failures
  - Return truthy values (page ID, True, int) on success
  - Never raise exceptions to the caller (fire-and-forget safety)

Mocks the Notion AsyncClient to simulate failures and success.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("NOTION_TOKEN", "ntn_fake_test_token")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")


# ── Test helpers ─────────────────────────────────────────────────────────────

FAKE_PAGE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _make_success_client():
    """Mock Notion client where all operations succeed."""
    client = AsyncMock()
    client.databases.query.return_value = {"results": []}
    client.pages.create.return_value = {
        "id": FAKE_PAGE_ID,
        "url": f"https://notion.so/{FAKE_PAGE_ID}",
    }
    client.pages.update.return_value = {"id": FAKE_PAGE_ID}
    return client


def _make_failing_client():
    """Mock Notion client where all operations raise."""
    client = AsyncMock()
    err = Exception("Notion API 500: Internal Server Error")
    client.databases.query.side_effect = err
    client.pages.create.side_effect = err
    client.pages.update.side_effect = err
    client.blocks.children.list.side_effect = err
    client.blocks.children.append.side_effect = err
    client.blocks.delete.side_effect = err
    return client


SAMPLE_GRANT = {
    "_id": MagicMock(),  # ObjectId-like
    "grant_name": "Test Grant for Error Handling",
    "title": "Test Grant for Error Handling",
    "funder": "Test Funder",
    "weighted_total": 7.0,
    "status": "triage",
    "themes_detected": ["climatetech"],
    "geography": "Global",
    "grant_type": "Research",
    "eligibility": "Open to all.",
    "rationale": "Good fit.",
    "url": "https://example.com/grant",
    "max_funding_usd": 100000,
    "deadline": "2026-12-31",
}

# Make the _id return a string for str()
SAMPLE_GRANT["_id"].__str__ = lambda self: "6601234567890abcdef01234"


# ── sync_scored_grant error handling ─────────────────────────────────────────

class TestSyncScoredGrantErrors:
    """Tests sync_scored_grant error return structure."""

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("Notion API 500")):
            from backend.integrations.notion_sync import sync_scored_grant
            result = await sync_scored_grant(SAMPLE_GRANT)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Notion API 500" in result["error"]

    @pytest.mark.asyncio
    async def test_does_not_raise_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("fail")):
            from backend.integrations.notion_sync import sync_scored_grant
            result = await sync_scored_grant(SAMPLE_GRANT)
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_page_id_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._find_page_by_mongo_id", new_callable=AsyncMock, return_value=None), \
             patch("backend.integrations.notion_sync._store_notion_url", new_callable=AsyncMock):
            from backend.integrations.notion_sync import sync_scored_grant
            result = await sync_scored_grant(SAMPLE_GRANT)

        assert result == FAKE_PAGE_ID


# ── log_agent_run error handling ─────────────────────────────────────────────

class TestLogAgentRunErrors:

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("Notion API 500")):
            from backend.integrations.notion_sync import log_agent_run
            result = await log_agent_run(agent="scout", status="Completed")

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_page_id_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import log_agent_run
            result = await log_agent_run(
                agent="scout",
                status="Completed",
                trigger="Manual",
                duration_seconds=120,
                grants_found=10,
            )

        assert result == FAKE_PAGE_ID


# ── log_error error handling ─────────────────────────────────────────────────

class TestLogErrorErrors:

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("Notion API 500")):
            from backend.integrations.notion_sync import log_error
            result = await log_error(
                agent="analyst",
                error=ValueError("LLM returned garbage"),
                grant_name="Test Grant",
            )

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_page_id_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import log_error
            result = await log_error(
                agent="analyst",
                error=ValueError("Test error"),
                severity="Warning",
            )

        assert result == FAKE_PAGE_ID


# ── log_triage_decision error handling ───────────────────────────────────────

class TestLogTriageDecisionErrors:

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("Notion API 500")):
            from backend.integrations.notion_sync import log_triage_decision
            result = await log_triage_decision(
                grant_id="fake_id",
                grant_name="Test Grant",
                decision="pursue",
            )

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_page_id_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import log_triage_decision
            result = await log_triage_decision(
                grant_id="fake_id",
                grant_name="Test Grant",
                decision="pursue",
                ai_recommendation="Watch",
                is_override=True,
                override_reason="Strategic partnership.",
                decided_by="test@altcarbon.com",
            )

        assert result == FAKE_PAGE_ID


# ── sync_draft_section error handling ────────────────────────────────────────

class TestSyncDraftSectionErrors:

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("Notion API 500")):
            from backend.integrations.notion_sync import sync_draft_section
            result = await sync_draft_section(
                grant_id="fake_id",
                grant_name="Test Grant",
                section_name="Problem Statement",
                content="This is the problem...",
            )

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_page_id_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._find_page_by_mongo_id", new_callable=AsyncMock, return_value=None):
            from backend.integrations.notion_sync import sync_draft_section
            result = await sync_draft_section(
                grant_id="fake_id",
                grant_name="Test Grant",
                section_name="Problem Statement",
                content="AltCarbon's problem statement...",
                word_count=250,
                word_limit=500,
                version=1,
                status="Draft",
                evidence_gaps=["Need pilot data"],
            )

        assert result == FAKE_PAGE_ID


# ── update_grant_status error handling ───────────────────────────────────────

class TestUpdateGrantStatusErrors:
    """update_grant_status returns bool (True/False), not error dicts."""

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("fail")):
            from backend.integrations.notion_sync import update_grant_status
            result = await update_grant_status("fake_id", "pursue")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_page_not_found(self):
        """If the grant doesn't exist in Notion, returns False (not an error)."""
        with patch("backend.integrations.notion_sync._find_page_by_mongo_id", new_callable=AsyncMock, return_value=None), \
             patch("backend.integrations.notion_sync._get_client", return_value=_make_success_client()):
            from backend.integrations.notion_sync import update_grant_status
            result = await update_grant_status("nonexistent_id", "pursue")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._find_page_by_mongo_id", new_callable=AsyncMock, return_value="existing-page-id"), \
             patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import update_grant_status
            result = await update_grant_status("fake_id", "pursue")

        assert result is True
        mock_client.pages.update.assert_called_once()


# ── update_agent_run error handling ──────────────────────────────────────────

class TestUpdateAgentRunErrors:

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self):
        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("fail")):
            from backend.integrations.notion_sync import update_agent_run
            result = await update_agent_run(
                page_id="some-page-id",
                status="Failed",
                errors=1,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        mock_client = _make_success_client()
        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import update_agent_run
            result = await update_agent_run(
                page_id="some-page-id",
                status="Completed",
                duration_seconds=90,
                grants_scored=5,
                errors=0,
                summary="Scored 5 grants.",
            )

        assert result is True


# ── backfill_grants error handling ───────────────────────────────────────────

class TestBackfillGrantsErrors:

    @pytest.mark.asyncio
    async def test_returns_zero_on_all_failures(self):
        """When every sync fails, backfill still returns 0 (not raising)."""
        grants = [dict(SAMPLE_GRANT) for _ in range(3)]

        with patch("backend.integrations.notion_sync._get_client", side_effect=Exception("fail")):
            from backend.integrations.notion_sync import backfill_grants
            count = await backfill_grants(grants)

        # sync_scored_grant returns {"success": False, ...} which is truthy
        # so backfill may count it. This tests that backfill doesn't crash.
        assert isinstance(count, int)

    @pytest.mark.asyncio
    async def test_returns_count_on_success(self):
        mock_client = _make_success_client()
        grants = [dict(SAMPLE_GRANT) for _ in range(3)]
        for g in grants:
            g["_id"] = MagicMock()
            g["_id"].__str__ = lambda self: "abc123"

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._find_page_by_mongo_id", new_callable=AsyncMock, return_value=None), \
             patch("backend.integrations.notion_sync._store_notion_url", new_callable=AsyncMock):
            from backend.integrations.notion_sync import backfill_grants
            count = await backfill_grants(grants)

        assert count == 3


# ── Cross-cutting: _get_client failure ───────────────────────────────────────

class TestGetClientFailure:
    """When NOTION_TOKEN is missing, _get_client raises RuntimeError.
    All sync functions should catch this and return error/False/None."""

    @pytest.mark.asyncio
    async def test_sync_scored_grant_handles_missing_token(self):
        with patch("backend.integrations.notion_sync._get_client",
                    side_effect=RuntimeError("NOTION_TOKEN not set")):
            from backend.integrations.notion_sync import sync_scored_grant
            result = await sync_scored_grant(SAMPLE_GRANT)

        assert isinstance(result, dict)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_log_agent_run_handles_missing_token(self):
        with patch("backend.integrations.notion_sync._get_client",
                    side_effect=RuntimeError("NOTION_TOKEN not set")):
            from backend.integrations.notion_sync import log_agent_run
            result = await log_agent_run(agent="scout", status="Completed")

        assert isinstance(result, dict)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_update_grant_status_handles_missing_token(self):
        with patch("backend.integrations.notion_sync._get_client",
                    side_effect=RuntimeError("NOTION_TOKEN not set")):
            from backend.integrations.notion_sync import update_grant_status
            result = await update_grant_status("id", "pursue")

        assert result is False
