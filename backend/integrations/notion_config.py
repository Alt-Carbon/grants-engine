"""Notion database IDs and property mappings for Mission Control sync."""
from __future__ import annotations

import os

# ── Knowledge base (Company Brain source) ────────────────────────────────────
# When set, Company Brain syncs ONLY this page and its descendants (AltCarbon knowledge).
# Leave empty to sync all workspace pages (legacy behavior).
NOTION_KNOWLEDGE_BASE_PAGE_ID = os.getenv("NOTION_KNOWLEDGE_BASE_PAGE_ID", "").strip()

# ── Parent page ──────────────────────────────────────────────────────────────
MISSION_CONTROL_PAGE_ID = os.getenv(
    "NOTION_MISSION_CONTROL_PAGE_ID",
    "30b50d0e-c20e-8057-aee5-f775b9902c95",
)

# ── Data-source (collection) IDs ─────────────────────────────────────────────
GRANT_PIPELINE_DS = os.getenv(
    "NOTION_GRANT_PIPELINE_DS",
    "8e9cd5d9-0239-4072-8233-6006aa184e48",
)
AGENT_RUNS_DS = os.getenv(
    "NOTION_AGENT_RUNS_DS",
    "6848a08a-a5ab-4627-989b-22dac3195f42",
)
ERROR_LOGS_DS = os.getenv(
    "NOTION_ERROR_LOGS_DS",
    "2149b3a1-aa9c-456d-8daf-fce6858807be",
)
TRIAGE_DECISIONS_DS = os.getenv(
    "NOTION_TRIAGE_DECISIONS_DS",
    "3fc6834d-18b2-4e95-91dc-06ccca42b679",
)
DRAFT_SECTIONS_DS = os.getenv(
    "NOTION_DRAFT_SECTIONS_DS",
    "c244df69-d74e-4703-ac88-d506c85aabe2",
)
KNOWLEDGE_CONNECTIONS_DS = os.getenv(
    "NOTION_KNOWLEDGE_CONNECTIONS_DS",
    "1ce5cd69-d174-40bc-9c6a-8277e7a692a4",
)
DOCUMENTS_LIST_DS = os.getenv(
    "NOTION_DOCUMENTS_LIST_DS",
    "30d50d0e-c20e-8062-bdb6-000b82620d34",
)
# ── Table of Content (Grants DB — primary knowledge registry) ────────────
TABLE_OF_CONTENT_DS = os.getenv(
    "NOTION_TABLE_OF_CONTENT_DS",
    "31f50d0e-c20e-80d1-b22a-e7124bd9103e",
)

# ── Theme mapping: Table of Content "Content info" → internal theme keys ──
TOC_THEME_MAP = {
    "theme - Climate tech": "climatetech",
    "theme - Agritech": "agritech",
    "theme - AI for sciences": "ai_for_sciences",
    "theme - Advanced earth sciences": "applied_earth_sciences",
    "theme - Deeptech": "deeptech",
    "theme - general": "general",
}

# ── Theme key → Notion multi-select display name ─────────────────────────────
THEME_DISPLAY = {
    "climatetech": "Climate Tech",
    "agritech": "Agri Tech",
    "ai_for_sciences": "AI for Sciences",
    "applied_earth_sciences": "Earth Sciences",
    "social_impact": "Social Impact",
    "deeptech": "Deep Tech",
}

# ── Status mapping: MongoDB status → Notion select option ────────────────────
STATUS_MAP = {
    "triage": "Triage",
    "pursue": "Pursue",
    "pursuing": "Pursue",
    "watch": "Watch",
    "passed": "Pass",
    "human_passed": "Pass",
    "auto_pass": "Auto Pass",
    "drafting": "Drafting",
    "draft_complete": "Submitted",
    "submitted": "Submitted",
    "won": "Won",
}

# ── Priority thresholds (mirror frontend/backend logic) ──────────────────────
def get_priority_label(score: float) -> str:
    if score >= 6.5:
        return "High"
    if score >= 5.0:
        return "Medium"
    return "Low"

# ── Eligibility checklist status → emoji (mirrors GrantDetailSheet STATUS_ICON) ──
CHECKLIST_STATUS_EMOJI = {
    "met": "\u2705",
    "likely_met": "\U0001f7e1",
    "verify": "\U0001f50d",
    "not_met": "\u274c",
}

# ── Score dimension keys → display names ─────────────────────────────────────
SCORE_DIMENSION_DISPLAY = {
    "theme_alignment": "Theme Alignment",
    "eligibility_confidence": "Eligibility Confidence",
    "funding_amount": "Funding Amount",
    "deadline_urgency": "Deadline Urgency",
    "geography_fit": "Geography Fit",
    "competition_level": "Competition Level",
}

# ── Agent name mapping ───────────────────────────────────────────────────────
AGENT_DISPLAY = {
    "scout": "Scout",
    "analyst": "Analyst",
    "drafter": "Drafter",
    "knowledge_sync": "Knowledge Sync",
    "company_brain": "Knowledge Sync",
    "company_brain_load": "Company Brain Load",
    "draft_guardrail": "Draft Guardrail",
    "pre_triage_guardrail": "Pre-Triage Guardrail",
}
