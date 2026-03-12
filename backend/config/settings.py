"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
