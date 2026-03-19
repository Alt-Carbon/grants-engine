"""Application settings loaded from environment variables."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict


# Default scoring weights — must sum to 1.0, all 6 dimensions required.
_DEFAULT_SCORING_WEIGHTS: Dict[str, float] = {
    "theme_alignment":        0.25,
    "eligibility_confidence": 0.20,
    "funding_amount":         0.20,
    "deadline_urgency":       0.15,
    "geography_fit":          0.10,
    "competition_level":      0.10,
}

# Default exchange rates: units of foreign currency per 1 USD.
_DEFAULT_EXCHANGE_RATES: Dict[str, float] = {
    "USD": 1.0,
    "INR": 83.5,
    "EUR": 0.92,
    "GBP": 0.79,
    "CAD": 1.36,
    "AUD": 1.53,
    "SGD": 1.34,
    "JPY": 149.0,
    "BRL": 4.97,
    "ZAR": 18.6,
    "KES": 129.0,
    "NGN": 1540.0,
}


def _parse_scoring_weights(v: str) -> Dict[str, float]:
    """Parse SCORING_WEIGHTS env var (JSON string) or return default."""
    if not v:
        return _DEFAULT_SCORING_WEIGHTS
    try:
        parsed = json.loads(v)
        if isinstance(parsed, dict) and len(parsed) == 6:
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return _DEFAULT_SCORING_WEIGHTS


def _parse_exchange_rates(v: str) -> Dict[str, float]:
    """Parse EXCHANGE_RATES env var (JSON string) or return default."""
    if not v:
        return _DEFAULT_EXCHANGE_RATES
    try:
        parsed = json.loads(v)
        if isinstance(parsed, dict) and all(isinstance(r, (int, float)) for r in parsed.values()):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return _DEFAULT_EXCHANGE_RATES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"

    # AI Gateway (primary — routes to all models via OpenAI-compatible API)
    ai_gateway_url: str = "https://ai-gateway.vercel.sh/v1"
    ai_gateway_api_key: str = ""

    # Anthropic direct (fallback if no gateway key)
    anthropic_api_key: str = ""

    # OpenAI (no longer used — Pinecone Integrated Inference handles embeddings)
    openai_api_key: str = ""

    # Knowledge sources
    notion_token: str = ""
    notion_knowledge_base_page_id: str = ""  # Optional: scope sync to this page + descendants
    notion_webhook_secret: str = ""  # For HMAC signature validation on webhook events
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # Pinecone (vector DB — optional, falls back to MongoDB)
    pinecone_api_key: str = ""
    pinecone_index_name: str = "grants-engine"

    # Cloudflare Browser Rendering (renders JS-heavy pages)
    cloudflare_account_id: str = ""
    cloudflare_browser_token: str = ""

    # Slack (MCP server)
    slack_bot_token: str = ""
    slack_team_id: str = ""

    # Search tools
    tavily_api_key: str = ""
    exa_api_key: str = ""
    perplexity_api_key: str = ""
    jina_api_key: str = ""

    # Backend auth
    cron_secret: str = "dev-cron-secret"
    internal_secret: str = "dev-internal-secret"

    # LangSmith (optional)
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "altcarbon-grants"

    # Agent config defaults
    scout_frequency_hours: int = 48
    pursue_threshold: float = 6.5
    watch_threshold: float = 5.0
    min_grant_funding: int = 3000

    # AltCarbon themes
    themes: List[str] = [
        "climatetech",
        "agritech",
        "ai_for_sciences",
        "applied_earth_sciences",
        "social_impact",
        "deeptech",
    ]

    # Scoring weights (JSON string env var, parsed at access time)
    scoring_weights: str = ""

    # Pre-triage guardrail thresholds
    score_floor: float = 4.0
    theme_alignment_floor: int = 2

    # Chunking parameters (Company Brain)
    chunk_size: int = 400        # words per chunk
    chunk_overlap: int = 80      # word overlap between chunks
    min_chunk_words: int = 40    # minimum words to keep a chunk

    # Company identity
    company_name: str = "AltCarbon"
    company_domain: str = "altcarbon.com"

    # LLM model overrides (override per-agent model in backend/utils/llm.py)
    scout_model: str = ""
    analyst_heavy_model: str = ""
    drafter_model: str = ""

    # ── Analyst guardrails ──
    red_flag_penalty: float = 0.5
    red_flag_max_penalty: float = 2.0
    min_funding_inr: float = 150_000

    # ── Currency exchange rates (JSON) ──
    exchange_rates: str = ""

    # ── Reviewer guardrails ──
    reviewer_revision_threshold: float = 6.0
    reviewer_export_threshold: float = 6.5

    # ── Drafter guardrails ──
    default_section_word_limit: int = 500
    max_revision_attempts: int = 3

    # ── Scout guardrails ──
    scout_enrichment_timeout: int = 45
    scout_crawl_timeout: int = 180
    jina_concurrency: int = 3
    jina_delay: float = 1.0

    def get_scoring_weights(self) -> Dict[str, float]:
        """Return parsed scoring weights dict."""
        return _parse_scoring_weights(self.scoring_weights)

    def get_exchange_rates(self) -> Dict[str, float]:
        """Return parsed exchange rates dict."""
        return _parse_exchange_rates(self.exchange_rates)


@lru_cache
def get_settings() -> Settings:
    return Settings()
