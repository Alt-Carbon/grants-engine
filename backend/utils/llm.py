"""Centralized LLM client — routes all calls through the AI Gateway.

Uses the OpenAI-compatible SDK against the Vercel AI Gateway.
Falls back to direct Anthropic API if no gateway key is set.

Usage:
    from backend.utils.llm import chat, SONNET, HAIKU

    text = await chat("Why is the sky blue?", model=SONNET)
"""
from __future__ import annotations

from openai import AsyncOpenAI


# Model name constants — gateway uses provider/model format
SONNET = "anthropic/claude-sonnet-4-6"
HAIKU  = "anthropic/claude-haiku-4-5-20251001"


def get_client() -> AsyncOpenAI:
    """Return an OpenAI-compatible client pointed at the AI Gateway."""
    from backend.config.settings import get_settings
    s = get_settings()

    if s.ai_gateway_api_key:
        return AsyncOpenAI(
            api_key=s.ai_gateway_api_key,
            base_url=s.ai_gateway_url,
        )
    # Fallback: direct Anthropic via OpenAI-compat endpoint
    return AsyncOpenAI(
        api_key=s.anthropic_api_key,
        base_url="https://api.anthropic.com/v1",
        default_headers={"anthropic-version": "2023-06-01"},
    )


async def chat(
    prompt: str,
    model: str = SONNET,
    max_tokens: int = 1024,
    system: str = "",
) -> str:
    """One-shot chat completion. Returns the text content."""
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.choices[0].message.content or ""
