"""Centralized LLM client — routes all calls through the AI Gateway.

Uses the OpenAI-compatible SDK against the Vercel AI Gateway.
Falls back to direct Anthropic API if no gateway key is set.

Automatic fallback: when a model's API credits are exhausted (429/402/quota errors),
the system tries the next model in the fallback chain and logs the event to
Notion Mission Control for visibility.

Usage:
    from backend.utils.llm import chat, SONNET, HAIKU

    text = await chat("Why is the sky blue?", model=SONNET)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── Per-agent model assignments ──────────────────────────────────────────────
# Scout: GPT-5.4 for grant extraction/scraping
SCOUT_MODEL = "openai/gpt-5.4"

# Analyst: Opus for heavy scoring & deep research, GPT-5.4 for light tasks
ANALYST_HEAVY = "anthropic/claude-opus-4-6"     # scoring, deep research
ANALYST_LIGHT = "openai/gpt-5.4"               # currency resolution, winners, extraction
ANALYST_FUNDER = "google/gemini-3-flash"  # funder enrichment

# Company Brain: GPT-5.4 for chunk tagging
BRAIN_MODEL = "openai/gpt-5.4"

# Drafter: user-selectable (default GPT-5.4, option for Opus)
DRAFTER_DEFAULT = "openai/gpt-5.4"
DRAFTER_MODELS = {
    "gpt-5.4": "openai/gpt-5.4",
    "opus-4.6": "anthropic/claude-opus-4-6",
}

# Backward-compatible aliases (used by agents that haven't migrated yet)
SONNET = ANALYST_HEAVY
HAIKU = ANALYST_LIGHT

# ── Fallback chains ──────────────────────────────────────────────────────────
# When a model's credits/quota are exhausted, try the next in chain.
_FALLBACK_CHAINS: Dict[str, List[str]] = {
    # Opus-tier (heavy: scoring, deep research)
    "anthropic/claude-opus-4-6": [
        "openai/gpt-5.4",
        "anthropic/claude-sonnet-4-6",
    ],
    # GPT-5.4-tier (medium: extraction, drafter, brain)
    "openai/gpt-5.4": [
        "anthropic/claude-opus-4-6",
        "anthropic/claude-sonnet-4-6",
    ],
    # Legacy fallbacks (if any old code references these)
    "anthropic/claude-sonnet-4-6": [
        "openai/gpt-5.4",
        "anthropic/claude-opus-4-6",
    ],
    "google/gemini-3-flash": [
        "openai/gpt-5.4",
        "anthropic/claude-opus-4-6",
    ],
    "google/gemini-2.5-flash-lite": [
        "openai/gpt-5.4",
        "anthropic/claude-opus-4-6",
    ],
    "openai/gpt-5-nano": [
        "openai/gpt-5.4",
        "anthropic/claude-opus-4-6",
    ],
}

# ── Exhausted model tracking ─────────────────────────────────────────────────
# When a model hits a credit/quota error, we mark it as exhausted for a cooldown
# period so subsequent calls skip it immediately instead of wasting time.
_exhausted_models: Dict[str, float] = {}  # model → expiry timestamp
_EXHAUSTION_COOLDOWN_SECS = 300  # 5 minutes before retrying an exhausted model


def _is_exhausted(model: str) -> bool:
    """Check if a model is currently in the exhaustion cooldown window."""
    expiry = _exhausted_models.get(model)
    if expiry is None:
        return False
    if time.time() > expiry:
        _exhausted_models.pop(model, None)
        return False
    return True


def _mark_exhausted(model: str) -> None:
    """Mark a model as credit-exhausted for the cooldown period."""
    _exhausted_models[model] = time.time() + _EXHAUSTION_COOLDOWN_SECS
    logger.warning("Model %s marked as exhausted for %ds", model, _EXHAUSTION_COOLDOWN_SECS)


def _is_credit_error(exc: Exception) -> bool:
    """Return True if the exception indicates credit/quota exhaustion."""
    # OpenAI SDK wraps HTTP errors in specific exception types
    exc_str = str(exc).lower()
    credit_signals = (
        "429", "rate limit", "rate_limit",
        "402", "payment required", "insufficient",
        "quota", "exceeded", "billing", "credits",
        "resource_exhausted", "too many requests",
        "limit reached", "spending limit",
    )
    if any(s in exc_str for s in credit_signals):
        return True

    # Check HTTP status code if available (openai.APIStatusError)
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status in (429, 402, 403):
        return True

    return False


# ── Notion Mission Control logging ───────────────────────────────────────────

async def _log_fallback_to_notion(
    primary_model: str,
    fallback_model: str,
    error_msg: str,
) -> None:
    """Log a model fallback event to Notion Mission Control (fire-and-forget)."""
    try:
        from backend.integrations.notion_sync import log_error
        await log_error(
            agent="llm_router",
            error=Exception(f"Credit exhaustion fallback: {primary_model} → {fallback_model}"),
            tb=f"Primary model: {primary_model}\nFallback model: {fallback_model}\nError: {error_msg}",
            severity="Warning",
        )
    except Exception:
        logger.debug("Notion fallback log skipped", exc_info=True)


async def _log_all_models_failed(models_tried: List[str], error_msg: str) -> None:
    """Log to Mission Control when ALL models in a chain are exhausted."""
    try:
        from backend.integrations.notion_sync import log_error
        await log_error(
            agent="llm_router",
            error=Exception(f"ALL models exhausted: {', '.join(models_tried)}"),
            tb=f"Models tried: {', '.join(models_tried)}\nLast error: {error_msg}",
            severity="Critical",
        )
    except Exception:
        logger.debug("Notion all-failed log skipped", exc_info=True)


# ── Client ───────────────────────────────────────────────────────────────────

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


# ── Core chat with automatic fallback ────────────────────────────────────────

async def _call_model(
    client: AsyncOpenAI,
    model: str,
    messages: list,
    max_tokens: int,
    temperature: Optional[float] = None,
) -> str:
    """Make a single chat completion call. Raises on failure."""
    kwargs: Dict = dict(model=model, max_tokens=max_tokens, messages=messages)
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def chat(
    prompt: str,
    model: str = SONNET,
    max_tokens: int = 1024,
    system: str = "",
    temperature: Optional[float] = None,
) -> str:
    """One-shot chat completion with automatic model fallback.

    If the primary model's credits are exhausted (429/402/quota errors),
    tries each fallback model in order. Logs fallbacks to Mission Control.
    """
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Build the model chain: primary + fallbacks
    chain = [model] + _FALLBACK_CHAINS.get(model, [])
    models_tried: List[str] = []
    last_error: Optional[Exception] = None

    for candidate in chain:
        # Skip models we already know are exhausted
        if _is_exhausted(candidate):
            logger.debug("Skipping exhausted model: %s", candidate)
            models_tried.append(f"{candidate} (skipped-exhausted)")
            continue

        try:
            result = await _call_model(client, candidate, messages, max_tokens, temperature)
            # If we fell back from the primary, log it
            if candidate != model:
                logger.info(
                    "Fallback success: %s → %s (primary was %s)",
                    models_tried[-1] if models_tried else model, candidate, model,
                )
            return result

        except Exception as exc:
            models_tried.append(candidate)
            last_error = exc

            if _is_credit_error(exc):
                _mark_exhausted(candidate)
                error_msg = str(exc)[:200]
                logger.warning(
                    "Credits exhausted for %s: %s — trying next fallback",
                    candidate, error_msg,
                )
                # Log fallback to Mission Control (non-blocking)
                next_candidates = [c for c in chain if c not in models_tried and not _is_exhausted(c)]
                if next_candidates:
                    asyncio.create_task(_log_fallback_to_notion(
                        candidate, next_candidates[0], error_msg,
                    ))
                continue
            else:
                # Non-credit error (network, malformed request, etc.) — don't fallback
                raise

    # All models exhausted
    error_msg = str(last_error)[:300] if last_error else "Unknown error"
    logger.error("ALL models exhausted: %s — error: %s", models_tried, error_msg)
    asyncio.create_task(_log_all_models_failed(models_tried, error_msg))
    raise RuntimeError(
        f"All LLM models exhausted ({', '.join(models_tried)}). "
        f"Last error: {error_msg}"
    )


async def chat_stream(
    prompt: str,
    model: str = SONNET,
    max_tokens: int = 1024,
    system: str = "",
    temperature: Optional[float] = None,
):
    """Streaming chat completion — yields content chunks as they arrive.

    Falls back through model chain if primary model is exhausted.
    Yields strings (content deltas).
    """
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    chain = [model] + _FALLBACK_CHAINS.get(model, [])
    models_tried: List[str] = []
    last_error: Optional[Exception] = None

    for candidate in chain:
        if _is_exhausted(candidate):
            models_tried.append(f"{candidate} (skipped-exhausted)")
            continue

        try:
            kwargs: Dict = dict(
                model=candidate, max_tokens=max_tokens, messages=messages, stream=True
            )
            if temperature is not None:
                kwargs["temperature"] = temperature
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
            return  # success — exit after streaming completes

        except Exception as exc:
            models_tried.append(candidate)
            last_error = exc
            if _is_credit_error(exc):
                _mark_exhausted(candidate)
                continue
            else:
                raise

    error_msg = str(last_error)[:300] if last_error else "Unknown error"
    raise RuntimeError(f"All LLM models exhausted ({', '.join(models_tried)}). Last error: {error_msg}")


def resolve_drafter_model(model_key: str) -> str:
    """Resolve a user-facing drafter model key to the gateway model ID.

    Accepts: "gpt-5.4", "opus-4.6", or a raw gateway model ID.
    Returns: the full gateway model string.
    """
    return DRAFTER_MODELS.get(model_key, model_key)
