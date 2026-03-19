"""Shared pytest fixtures for backend tests.

Provides mock MongoDB collections, realistic grant objects, and scored grant fixtures
used across all test modules.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Set required env vars before any backend imports touch Settings
os.environ.setdefault("NOTION_TOKEN", "ntn_fake_test_token")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")


# ── MongoDB mock fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_mongo_collection():
    """A mock MongoDB collection with common async methods stubbed."""
    coll = AsyncMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.find = MagicMock()  # find() returns a cursor, not a coroutine
    coll.find.return_value.to_list = AsyncMock(return_value=[])
    coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake_id"))
    coll.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    coll.count_documents = AsyncMock(return_value=0)
    return coll


# ── Grant object fixtures ────────────────────────────────────────────────────

@pytest.fixture
def sample_grant():
    """A realistic raw grant object as it comes from the scout."""
    return {
        "_id": "6601234567890abcdef01234",
        "grant_name": "EU Horizon Climate Innovation Fund",
        "title": "EU Horizon Climate Innovation Fund",
        "funder": "European Commission",
        "url": "https://ec.europa.eu/horizon/climate-innovation-2026",
        "application_url": "https://ec.europa.eu/horizon/apply",
        "amount": "EUR 500,000",
        "max_funding": 500000,
        "max_funding_usd": 500000,
        "currency": "USD",
        "deadline": "2026-06-30",
        "geography": "EU-wide",
        "grant_type": "Research & Innovation",
        "eligibility": "Open to SMEs and research institutions in EU member states.",
        "themes_detected": ["climatetech", "agritech"],
        "themes_text": "Climate Tech, Agri Tech",
        "status": "triage",
        "about_opportunity": "Fund supports climate innovation projects.",
        "eligibility_details": "Must demonstrate TRL 4-6.",
        "application_process": "Two-stage evaluation.",
        "notes": "",
    }


@pytest.fixture
def scored_grant(sample_grant):
    """A realistic scored grant as produced by the analyst agent."""
    return {
        **sample_grant,
        "scores": {
            "theme_alignment": 8,
            "eligibility_confidence": 7,
            "funding_amount": 9,
            "deadline_urgency": 6,
            "geography_fit": 5,
            "competition_level": 7,
        },
        "weighted_total": 7.35,
        "recommended_action": "pursue",
        "rationale": "Strong alignment with AltCarbon's biochar technology and EU climate targets.",
        "reasoning": "High funding, good theme fit, moderate competition.",
        "evidence_found": ["Published ERW research", "Frontier CDR credits"],
        "evidence_gaps": ["No prior EU framework participation"],
        "red_flags": [],
        "funder_context": "European Commission historically funds CDR projects.",
        "scoring_error": False,
        "scored_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
    }


@pytest.fixture
def minimal_grant():
    """A grant with only the absolute minimum fields."""
    return {
        "_id": "660aaabbbccc000111222333",
        "grant_name": "Bare Minimum Grant",
        "status": "triage",
    }
