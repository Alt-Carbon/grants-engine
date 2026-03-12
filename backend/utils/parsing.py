"""Shared JSON parsing, async retry, and API health-tracking utilities.

Used by scout.py, analyst.py, and any other agent that calls LLMs and needs
robust JSON extraction from responses that may include code fences, leading
prose, or unexpectedly return arrays instead of objects.

Also provides `APIHealthTracker` — a singleton that detects credit/quota
exhaustion for external APIs (Tavily, Exa, Jina, Perplexity) and tracks
cooldowns so callers skip dead services instead of wasting time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── API Health Tracker ────────────────────────────────────────────────────────

# Signals in exception messages/status codes that indicate credit/quota exhaustion
_CREDIT_SIGNALS = (
    "429", "rate limit", "rate_limit",
    "402", "payment required", "insufficient",
    "quota", "exceeded", "billing", "credits",
    "resource_exhausted", "too many requests",
    "limit reached", "spending limit", "usage limit",
    "plan limit", "subscription", "free tier",
)

_CREDIT_STATUS_CODES = {429, 402, 403}


def _is_api_credit_error(exc: Exception) -> bool:
    """Return True if the exception indicates an API credit/quota issue."""
    exc_str = str(exc).lower()
    if any(s in exc_str for s in _CREDIT_SIGNALS):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    # httpx.HTTPStatusError stores status on response
    if status is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", None)
    if status in _CREDIT_STATUS_CODES:
        return True
    return False


class APIHealthTracker:
    """Tracks credit/quota exhaustion for external services.

    Usage:
        tracker = api_health  # module-level singleton
        if tracker.is_exhausted("tavily"):
            skip tavily calls...

        try:
            result = await tavily_call()
            tracker.record_success("tavily")
        except Exception as exc:
            tracker.record_error("tavily", exc)
            if tracker.is_exhausted("tavily"):
                ... service just went down ...
    """

    def __init__(self, cooldown_secs: int = 600):
        self._cooldown = cooldown_secs  # 10 min default
        self._exhausted: Dict[str, float] = {}  # service → expiry timestamp
        self._last_errors: Dict[str, str] = {}  # service → last error message
        self._exhausted_at: Dict[str, str] = {}  # service → ISO timestamp
        self._success_counts: Dict[str, int] = {}  # successful calls since last check

    def is_exhausted(self, service: str) -> bool:
        """Check if a service is in the cooldown window."""
        expiry = self._exhausted.get(service)
        if expiry is None:
            return False
        if time.time() > expiry:
            self._exhausted.pop(service, None)
            self._last_errors.pop(service, None)
            self._exhausted_at.pop(service, None)
            logger.info("Service %s cooldown expired — re-enabling", service)
            return False
        return True

    def record_error(self, service: str, exc: Exception) -> bool:
        """Record an error. Returns True if the service was just marked exhausted."""
        if _is_api_credit_error(exc):
            self._exhausted[service] = time.time() + self._cooldown
            self._last_errors[service] = str(exc)[:300]
            self._exhausted_at[service] = datetime.now(timezone.utc).isoformat()
            logger.warning(
                "API %s marked EXHAUSTED for %ds: %s",
                service, self._cooldown, str(exc)[:200],
            )
            # Fire-and-forget Notion log (only when event loop is running)
            try:
                asyncio.create_task(self._log_to_notion(service, str(exc)[:300]))
            except RuntimeError:
                pass  # no running event loop (e.g. in tests)
            return True
        return False

    def record_success(self, service: str) -> None:
        """Record a successful call — clears exhaustion if cooldown was a false positive."""
        self._success_counts[service] = self._success_counts.get(service, 0) + 1
        # If service was marked exhausted but just worked, clear it
        if service in self._exhausted:
            self._exhausted.pop(service, None)
            self._last_errors.pop(service, None)
            self._exhausted_at.pop(service, None)
            logger.info("Service %s recovered (successful call) — cleared exhaustion", service)

    def get_status(self) -> Dict[str, Any]:
        """Return health status for all tracked services — used by /status/api-health."""
        # Clean expired entries
        now = time.time()
        for svc in list(self._exhausted):
            if now > self._exhausted[svc]:
                self._exhausted.pop(svc, None)
                self._last_errors.pop(svc, None)
                self._exhausted_at.pop(svc, None)

        all_services = ["tavily", "exa", "perplexity", "jina"]
        result: Dict[str, Any] = {}
        for svc in all_services:
            if svc in self._exhausted:
                remaining = int(self._exhausted[svc] - now)
                result[svc] = {
                    "status": "exhausted",
                    "exhausted_at": self._exhausted_at.get(svc),
                    "cooldown_remaining_secs": remaining,
                    "last_error": self._last_errors.get(svc, ""),
                }
            else:
                result[svc] = {"status": "ok"}
        return result

    async def _log_to_notion(self, service: str, error_msg: str) -> None:
        """Log service exhaustion to Notion Mission Control (fire-and-forget)."""
        try:
            from backend.integrations.notion_sync import log_error
            await log_error(
                agent="api_health",
                error=Exception(f"API credit exhaustion: {service}"),
                tb=f"Service: {service}\nError: {error_msg}\nCooldown: {self._cooldown}s",
                severity="Warning",
            )
        except Exception:
            logger.debug("Notion API health log skipped for %s", service, exc_info=True)


# Module-level singleton
api_health = APIHealthTracker(cooldown_secs=600)


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


class CreditExhaustedError(Exception):
    """Raised when retry_async detects a credit/quota error — stops retrying immediately."""

    def __init__(self, service: str, original: Exception):
        self.service = service
        self.original = original
        super().__init__(f"{service} credit/quota exhausted: {original}")


async def retry_async(
    coro_factory: Callable[[], Any],
    retries: int = 3,
    base_delay: float = 1.5,
    label: str = "",
    exceptions: Tuple[type, ...] = (Exception,),
    service: str = "",
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
        service:      Optional service name (e.g. "tavily", "exa"). If set,
                      credit/quota errors are detected and propagated immediately
                      as CreditExhaustedError instead of retrying.

    Returns the result on success, None if all retries are exhausted.
    Raises CreditExhaustedError if a credit/quota error is detected and
    service name is provided.
    """
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return await coro_factory()
        except exceptions as exc:
            last_error = exc
            # If this looks like a credit/quota error, stop retrying immediately
            if service and _is_api_credit_error(exc):
                api_health.record_error(service, exc)
                raise CreditExhaustedError(service, exc) from exc
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
