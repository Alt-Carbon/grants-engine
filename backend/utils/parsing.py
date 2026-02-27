"""Shared JSON parsing and async retry utilities.

Used by scout.py, analyst.py, and any other agent that calls LLMs and needs
robust JSON extraction from responses that may include code fences, leading
prose, or unexpectedly return arrays instead of objects.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_json_safe(text: str) -> dict:
    """Extract and parse a JSON object from LLM output.

    Handles all common LLM response formats:
    - Code fences: ```json { ... } ``` or ``` { ... } ```
    - Leading/trailing prose before or after the JSON block
    - Arrays wrapping a single object: [{ ... }] → returns the first object
    - Trailing commas in objects/arrays (relaxed fix)

    Returns an empty dict on any parse failure — never raises.
    """
    if not text:
        return {}

    text = text.strip()

    # ── 1. Extract blocks from code fences ────────────────────────────────────
    if "```" in text:
        # split("```") gives alternating [outside, inside, outside, inside, ...]
        parts = text.split("```")
        for block in parts[1::2]:  # every odd-indexed segment is inside fences
            block = block.strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            result = _try_load(block)
            if result is not None:
                return result

    # ── 2. Try direct parse of the full text ──────────────────────────────────
    result = _try_load(text)
    if result is not None:
        return result

    # ── 3. Balanced-brace extraction (first { ... } block in surrounding prose) ─
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i, ch in enumerate(text[brace_start:], brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start : i + 1]
                    result = _try_load(candidate)
                    if result is not None:
                        return result
                    # Retry with trailing-comma fix
                    clean = re.sub(r",\s*([}\]])", r"\1", candidate)
                    result = _try_load(clean)
                    if result is not None:
                        return result
                    break  # malformed — don't keep searching

    logger.debug("parse_json_safe: could not extract JSON. text[:120]=%r", text[:120])
    return {}


def _try_load(text: str) -> Optional[dict]:
    """Attempt json.loads; return dict result or None on failure."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        # Unwrap single-element list: [{ ... }]
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            return obj[0]
    except (json.JSONDecodeError, ValueError):
        pass
    return None


async def retry_async(
    coro_factory: Callable[[], Any],
    retries: int = 3,
    base_delay: float = 1.5,
    label: str = "",
    exceptions: Tuple[type, ...] = (Exception,),
) -> Optional[Any]:
    """Retry an async operation with exponential backoff.

    Args:
        coro_factory: Zero-argument callable that returns a *new* coroutine
                      each time it is called (do not pass the coroutine itself
                      — it can only be awaited once).
        retries:      Maximum number of attempts (including the first).
        base_delay:   Seconds to wait before the first retry; doubles each time.
        label:        Human-readable tag for log messages.
        exceptions:   Exception types to catch and retry on.

    Returns the result on success, None if all retries are exhausted.
    """
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return await coro_factory()
        except exceptions as exc:
            last_error = exc
            if attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.debug(
                    "retry_async '%s': attempt %d/%d failed (%s: %s) — retrying in %.1fs",
                    label, attempt + 1, retries, type(exc).__name__, exc, delay,
                )
                await asyncio.sleep(delay)

    logger.warning(
        "retry_async '%s': all %d attempts failed — last error: %s",
        label, retries, last_error,
    )
    return None
