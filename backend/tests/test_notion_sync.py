"""Dry-run tests for Notion Mission Control sync (Version A).

Mocks the Notion client so no real API calls are made.
Validates:
  1. sync_scored_grant — property structure, upsert logic
  2. log_agent_run — create row with correct fields
  3. update_agent_run — update existing page
  4. log_error — error page with traceback body
  5. log_triage_decision — triage decision with override tracking
  6. sync_draft_section — upsert with content body
  7. update_grant_status — status-only update
  8. backfill_grants — bulk sync
  9. Fire-and-forget safety — no exceptions propagate
"""
from __future__ import annotations

import asyncio
import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_PAGE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_MONGO_ID = str(ObjectId())

SAMPLE_GRANT = {
    "_id": ObjectId(FAKE_MONGO_ID),
    "grant_name": "EU Horizon Climate Innovation Fund",
    "title": "EU Horizon Climate Innovation Fund",
    "funder": "European Commission",
    "weighted_total": 7.8,
    "status": "triage",
    "themes_detected": ["climatetech", "agritech"],
    "geography": "EU-wide",
    "grant_type": "Research & Innovation",
    "eligibility": "Open to SMEs and research institutions in EU member states. Must demonstrate TRL 4-6.",
    "rationale": "Strong alignment with AltCarbon's biochar technology and EU climate targets.",
    "recommended_action": "Pursue",
    "url": "https://ec.europa.eu/horizon/climate-innovation-2026",
    "max_funding_usd": 500000,
    "deadline": "2026-06-30",
    "scored_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
}


# ── Test helpers ─────────────────────────────────────────────────────────────

def make_mock_client():
    """Create a mock Notion AsyncClient with all methods stubbed."""
    client = AsyncMock()

    # databases.query returns empty by default (no existing page)
    client.databases.query.return_value = {"results": []}

    # pages.create returns a fake page
    client.pages.create.return_value = {"id": FAKE_PAGE_ID, "url": f"https://notion.so/{FAKE_PAGE_ID}"}

    # pages.update returns the same
    client.pages.update.return_value = {"id": FAKE_PAGE_ID}

    # blocks.children.list returns empty (for _replace_page_children)
    client.blocks.children.list.return_value = {"results": [], "has_more": False}

    # blocks.children.append returns empty
    client.blocks.children.append.return_value = {"results": []}

    return client


def run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestResults:
    passed = 0
    failed = 0
    errors = []

    @classmethod
    def ok(cls, name):
        cls.passed += 1
        print(f"  PASS  {name}")

    @classmethod
    def fail(cls, name, reason):
        cls.failed += 1
        cls.errors.append((name, reason))
        print(f"  FAIL  {name}: {reason}")

    @classmethod
    def summary(cls):
        total = cls.passed + cls.failed
        print(f"\n{'='*60}")
        print(f"  Results: {cls.passed}/{total} passed, {cls.failed} failed")
        if cls.errors:
            print(f"\n  Failures:")
            for name, reason in cls.errors:
                print(f"    - {name}: {reason}")
        print(f"{'='*60}")
        return cls.failed == 0


def test_sync_scored_grant_create():
    """New grant → pages.create called with correct properties."""
    name = "sync_scored_grant (create)"
    try:
        mock_client = make_mock_client()

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._store_notion_url", new_callable=AsyncMock):
            from backend.integrations.notion_sync import sync_scored_grant
            result = run(sync_scored_grant(SAMPLE_GRANT))

        assert result == FAKE_PAGE_ID, f"Expected page ID {FAKE_PAGE_ID}, got {result}"

        # Verify pages.create was called (not update, since no existing page)
        assert mock_client.pages.create.called, "pages.create was not called"
        call_kwargs = mock_client.pages.create.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        # Verify key properties
        assert props["Grant Name"]["title"][0]["text"]["content"] == "EU Horizon Climate Innovation Fund"
        assert props["Score"]["number"] == 7.8
        assert props["Priority"]["select"]["name"] == "High"  # 7.8 >= 6.5
        assert props["Status"]["select"]["name"] == "Triage"
        assert len(props["Themes"]["multi_select"]) == 2
        assert props["Themes"]["multi_select"][0]["name"] == "Climate Tech"
        assert props["Funding USD"]["number"] == 500000
        # AI Recommendation is a rollup in Notion (read-only), so it's not synced as a property
        assert "AI Recommendation" not in props
        assert props["Grant URL"]["url"] == "https://ec.europa.eu/horizon/climate-innovation-2026"
        assert props["Deadline"]["date"]["start"] == "2026-06-30"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_sync_scored_grant_update():
    """Existing grant → pages.update called instead of create."""
    name = "sync_scored_grant (update/upsert)"
    try:
        mock_client = make_mock_client()
        # Simulate finding an existing page
        mock_client.databases.query.return_value = {
            "results": [{"id": "existing-page-id-1234"}]
        }

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._store_notion_url", new_callable=AsyncMock):
            from backend.integrations.notion_sync import sync_scored_grant
            result = run(sync_scored_grant(SAMPLE_GRANT))

        assert result == "existing-page-id-1234", f"Expected existing page ID, got {result}"
        assert mock_client.pages.update.called, "pages.update was not called for existing grant"
        assert not mock_client.pages.create.called, "pages.create should NOT be called for existing grant"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_log_agent_run():
    """Log a completed scout run → creates page with correct props."""
    name = "log_agent_run (scout completed)"
    try:
        mock_client = make_mock_client()
        started = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import log_agent_run
            result = run(log_agent_run(
                agent="scout",
                status="Completed",
                trigger="Manual",
                started_at=started,
                duration_seconds=145,
                grants_found=12,
                errors=0,
                summary="Discovered 30 grants, saved 12 new.",
            ))

        assert result == FAKE_PAGE_ID
        call_kwargs = mock_client.pages.create.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        assert props["Agent"]["select"]["name"] == "Scout"
        assert props["Status"]["select"]["name"] == "Completed"
        assert props["Trigger"]["select"]["name"] == "Manual"
        assert props["Grants Found"]["number"] == 12
        assert props["Errors"]["number"] == 0
        assert "2m 25s" in props["Duration"]["rich_text"][0]["text"]["content"]

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_update_agent_run():
    """Update a running agent → pages.update with new status and stats."""
    name = "update_agent_run (Running → Completed)"
    try:
        mock_client = make_mock_client()

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import update_agent_run
            result = run(update_agent_run(
                page_id="some-run-page-id",
                status="Completed",
                duration_seconds=90,
                grants_scored=5,
                errors=0,
                summary="Scored 5 grants: 2 pursue, 1 watch, 2 auto_pass.",
            ))

        assert result is True
        assert mock_client.pages.update.called
        call_kwargs = mock_client.pages.update.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        assert props["Status"]["select"]["name"] == "Completed"
        assert props["Grants Scored"]["number"] == 5

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_log_error():
    """Log an exception → creates error page with traceback in body."""
    name = "log_error (with traceback)"
    try:
        mock_client = make_mock_client()

        exc = ValueError("LLM returned invalid JSON for scoring")
        try:
            raise exc
        except ValueError:
            import traceback
            tb = traceback.format_exc()

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import log_error
            result = run(log_error(
                agent="analyst",
                error=exc,
                tb=tb,
                grant_name="EU Horizon Fund",
                severity="Critical",
            ))

        assert result == FAKE_PAGE_ID
        call_kwargs = mock_client.pages.create.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        assert "LLM returned invalid JSON" in props["Error"]["title"][0]["text"]["content"]
        assert props["Agent"]["select"]["name"] == "Analyst"
        assert props["Severity"]["select"]["name"] == "Critical"
        assert props["Error Type"]["rich_text"][0]["text"]["content"] == "ValueError"
        assert props["Resolved"]["checkbox"] is False

        # Check that traceback was included as page children (code blocks)
        children = call_kwargs.kwargs.get("children") or call_kwargs[1].get("children")
        assert children is not None and len(children) > 0, "Traceback code blocks not included"
        assert children[0]["type"] == "code"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_log_triage_decision():
    """Log a human triage decision (override)."""
    name = "log_triage_decision (override)"
    try:
        mock_client = make_mock_client()

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import log_triage_decision
            result = run(log_triage_decision(
                grant_id=FAKE_MONGO_ID,
                grant_name="EU Horizon Climate Innovation Fund",
                decision="pursue",
                ai_recommendation="Watch",
                is_override=True,
                override_reason="Strong partnership with ICAR makes this strategic despite lower score.",
                decided_by="gowtham@altcarbon.com",
            ))

        assert result == FAKE_PAGE_ID
        call_kwargs = mock_client.pages.create.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        assert "Pursue" in props["Decision"]["title"][0]["text"]["content"]
        assert props["Action"]["select"]["name"] == "Pursue"
        assert props["Is Override"]["checkbox"] is True
        assert props["AI Recommendation"]["select"]["name"] == "Watch"
        assert "ICAR" in props["Override Reason"]["rich_text"][0]["text"]["content"]
        assert props["Decided By"]["rich_text"][0]["text"]["content"] == "gowtham@altcarbon.com"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_sync_draft_section_create():
    """Sync a new draft section → creates page with content body."""
    name = "sync_draft_section (create)"
    try:
        mock_client = make_mock_client()

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import sync_draft_section
            result = run(sync_draft_section(
                grant_id=FAKE_MONGO_ID,
                grant_name="EU Horizon Climate Innovation Fund",
                section_name="Project Overview",
                content="AltCarbon proposes a novel biochar-based carbon sequestration system...",
                word_count=478,
                word_limit=500,
                version=1,
                status="Draft",
                evidence_gaps=["Specific pilot results from Assam deployment", "Carbon sequestration measurement data"],
            ))

        assert result == FAKE_PAGE_ID
        call_kwargs = mock_client.pages.create.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        assert "Project Overview" in props["Section"]["title"][0]["text"]["content"]
        assert props["Word Count"]["number"] == 478
        assert props["Word Limit"]["number"] == 500
        assert props["Version"]["number"] == 1
        assert props["Status"]["select"]["name"] == "Draft"
        assert "Assam" in props["Evidence Gaps"]["rich_text"][0]["text"]["content"]

        # Check content body
        children = call_kwargs.kwargs.get("children") or call_kwargs[1].get("children")
        assert children is not None and len(children) > 0, "Section content not included as body"
        assert "biochar" in children[0]["paragraph"]["rich_text"][0]["text"]["content"]

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_push_complete_draft_to_notion_create():
    """Push a complete draft to the grant's own page in the Pipeline DB."""
    name = "push_complete_draft_to_notion (append to grant page)"
    try:
        mock_client = make_mock_client()
        # _find_page_by_mongo_id returns the grant page
        mock_client.databases.query.return_value = {
            "results": [{"id": FAKE_PAGE_ID}]
        }
        sections = {
            "Executive Summary": {
                "content": "AltCarbon proposes a scalable biochar intervention for smallholder farms.",
                "word_count": 11,
                "word_limit": 300,
                "within_limit": True,
            },
            "Budget": {
                "content": "Budget requests cover field pilots, MRV sampling, and implementation staffing.",
                "word_count": 11,
                "word_limit": 400,
                "within_limit": True,
            },
        }

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import push_complete_draft_to_notion
            result = run(push_complete_draft_to_notion(
                grant_id=FAKE_MONGO_ID,
                grant_name="EU Horizon Climate Innovation Fund",
                sections=sections,
                version=2,
                evidence_gaps=["Need 2025 pilot sequestration results"],
                funder="European Commission",
                deadline="2026-06-30",
            ))

        assert result == FAKE_PAGE_ID
        # Should append blocks to the existing grant page, not create a new page
        assert mock_client.blocks.children.append.called, "blocks.children.append should be called"
        call_kwargs = mock_client.blocks.children.append.call_args
        block_id = call_kwargs.kwargs.get("block_id") or call_kwargs[1].get("block_id")
        children = call_kwargs.kwargs.get("children") or call_kwargs[1].get("children")
        assert block_id == FAKE_PAGE_ID
        assert children is not None and len(children) > 0
        # First block should be a divider, second a callout
        assert children[0]["type"] == "divider"
        assert children[1]["type"] == "callout"

        # Should also update status to Drafting
        assert mock_client.pages.update.called

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_update_grant_status():
    """Update just the status of an existing grant."""
    name = "update_grant_status"
    try:
        mock_client = make_mock_client()
        mock_client.databases.query.return_value = {
            "results": [{"id": "existing-grant-page"}]
        }

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import update_grant_status
            result = run(update_grant_status(FAKE_MONGO_ID, "pursue"))

        assert result is True
        call_kwargs = mock_client.pages.update.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")
        assert props["Status"]["select"]["name"] == "Pursue"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_backfill_grants():
    """Backfill multiple grants → calls sync_scored_grant for each."""
    name = "backfill_grants (3 grants)"
    try:
        mock_client = make_mock_client()

        grants = []
        for i in range(3):
            g = dict(SAMPLE_GRANT)
            g["_id"] = ObjectId()
            g["grant_name"] = f"Test Grant {i+1}"
            grants.append(g)

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._store_notion_url", new_callable=AsyncMock):
            from backend.integrations.notion_sync import backfill_grants
            count = run(backfill_grants(grants))

        assert count == 3, f"Expected 3 synced, got {count}"
        assert mock_client.pages.create.call_count == 3

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_fire_and_forget_safety():
    """If Notion client raises, sync functions return None/False — never raise."""
    name = "fire-and-forget (errors swallowed)"
    try:
        mock_client = make_mock_client()
        mock_client.databases.query.side_effect = Exception("Notion API 500")
        mock_client.pages.create.side_effect = Exception("Notion API 500")

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client):
            from backend.integrations.notion_sync import (
                sync_scored_grant, log_agent_run, log_error,
                log_triage_decision, sync_draft_section, update_grant_status,
                push_complete_draft_to_notion,
            )

            # None of these should raise
            r1 = run(sync_scored_grant(SAMPLE_GRANT))
            r2 = run(log_agent_run(agent="scout", status="Completed"))
            r3 = run(log_error(agent="scout", error=Exception("test")))
            r4 = run(log_triage_decision(grant_id="x", grant_name="x", decision="pursue"))
            r5 = run(sync_draft_section(grant_id="x", grant_name="x", section_name="x", content="x"))
            r6 = run(update_grant_status("x", "pursue"))
            r7 = run(push_complete_draft_to_notion(
                grant_id="x",
                grant_name="x",
                sections={"Executive Summary": {"content": "test"}},
            ))

        assert r1 is None
        assert r2 is None
        assert r3 is None
        assert r4 is None
        assert r5 is None
        assert r6 is False
        assert r7 is None

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_priority_labels():
    """Priority label thresholds: >=6.5 High, >=5.0 Medium, <5.0 Low."""
    name = "priority labels"
    try:
        from backend.integrations.notion_config import get_priority_label
        assert get_priority_label(8.0) == "High"
        assert get_priority_label(6.5) == "High"
        assert get_priority_label(6.4) == "Medium"
        assert get_priority_label(5.0) == "Medium"
        assert get_priority_label(4.9) == "Low"
        assert get_priority_label(0) == "Low"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_status_mapping():
    """All MongoDB statuses map to valid Notion select options."""
    name = "status mapping"
    try:
        from backend.integrations.notion_config import STATUS_MAP
        expected_notion = {"Triage", "Pursue", "Watch", "Pass", "Auto Pass", "Drafting", "Submitted", "Won"}
        actual_notion = set(STATUS_MAP.values())
        assert actual_notion.issubset(expected_notion), f"Unexpected Notion statuses: {actual_notion - expected_notion}"

        # Check all known MongoDB statuses are mapped
        mongo_statuses = ["triage", "pursue", "pursuing", "watch", "passed", "human_passed",
                          "auto_pass", "drafting", "draft_complete", "submitted", "won"]
        for s in mongo_statuses:
            assert s in STATUS_MAP, f"MongoDB status '{s}' not in STATUS_MAP"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_theme_display():
    """All 6 themes have display names."""
    name = "theme display mapping"
    try:
        from backend.integrations.notion_config import THEME_DISPLAY
        expected_keys = {"climatetech", "agritech", "ai_for_sciences", "applied_earth_sciences", "social_impact", "deeptech"}
        assert set(THEME_DISPLAY.keys()) == expected_keys, f"Missing themes: {expected_keys - set(THEME_DISPLAY.keys())}"

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


def test_missing_optional_fields():
    """Grant with minimal fields (no deadline, no funding, no URL) still syncs."""
    name = "sync_scored_grant (minimal fields)"
    try:
        mock_client = make_mock_client()
        minimal_grant = {
            "_id": ObjectId(),
            "grant_name": "Bare Minimum Grant",
            "status": "triage",
            "weighted_total": 3.2,
        }

        with patch("backend.integrations.notion_sync._get_client", return_value=mock_client), \
             patch("backend.integrations.notion_sync._store_notion_url", new_callable=AsyncMock):
            from backend.integrations.notion_sync import sync_scored_grant
            result = run(sync_scored_grant(minimal_grant))

        assert result == FAKE_PAGE_ID
        call_kwargs = mock_client.pages.create.call_args
        props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")

        assert props["Grant Name"]["title"][0]["text"]["content"] == "Bare Minimum Grant"
        assert props["Score"]["number"] == 3.2
        assert props["Priority"]["select"]["name"] == "Low"
        assert "Grant URL" not in props  # No URL → no property
        assert "Funding USD" not in props  # No funding → no property
        assert "Deadline" not in props  # No deadline → no property

        TestResults.ok(name)
    except Exception as e:
        TestResults.fail(name, str(e))


# ── Run all tests ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Notion Sync Dry-Run Tests (Version A)")
    print("  No real API calls — all Notion interactions mocked")
    print("=" * 60)
    print()

    # Need to set a fake token so the client init doesn't fail
    os.environ["NOTION_TOKEN"] = "ntn_fake_test_token_for_dry_run"

    # Reset the module-level client singleton before each test
    import backend.integrations.notion_sync as ns

    tests = [
        test_priority_labels,
        test_status_mapping,
        test_theme_display,
        test_sync_scored_grant_create,
        test_sync_scored_grant_update,
        test_missing_optional_fields,
        test_log_agent_run,
        test_update_agent_run,
        test_log_error,
        test_log_triage_decision,
        test_sync_draft_section_create,
        test_push_complete_draft_to_notion_create,
        test_update_grant_status,
        test_backfill_grants,
        test_fire_and_forget_safety,
    ]

    for test_fn in tests:
        # Reset client singleton between tests
        ns._client = None
        test_fn()

    print()
    success = TestResults.summary()
    sys.exit(0 if success else 1)
