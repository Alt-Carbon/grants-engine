"""Async wrapper around agent-browser CLI for headless page fetching.

agent-browser uses a client-daemon architecture. The daemon auto-starts
on first command. Each session gets an isolated Chromium instance.

Used as a third-tier fallback when Jina Reader + plain HTTP both fail
(JS-rendered pages, Cloudflare challenges, Indian govt portals).

Usage:
    from backend.utils.browser import browser_fetch, is_available

    if is_available():
        content = await browser_fetch("https://birac.nic.in/open-calls")
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil

logger = logging.getLogger(__name__)

# Concurrency: cap parallel browser sessions to avoid memory pressure
# Each Chromium instance uses ~100-200MB
_BROWSER_SEM: asyncio.Semaphore | None = None
_MAX_CONCURRENT = 2
_PAGE_LOAD_WAIT = 3.0  # seconds for JS rendering after navigation


def _get_sem() -> asyncio.Semaphore:
    global _BROWSER_SEM
    if _BROWSER_SEM is None:
        _BROWSER_SEM = asyncio.Semaphore(_MAX_CONCURRENT)
    return _BROWSER_SEM


def is_available() -> bool:
    """Check if agent-browser CLI is installed and on PATH."""
    return shutil.which("agent-browser") is not None


async def _run_cmd(*args: str, timeout: float = 30.0) -> str:
    """Run an agent-browser CLI command and return stdout.

    Returns empty string on any failure (timeout, non-zero exit, etc).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "agent-browser", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        if proc.returncode != 0:
            logger.debug(
                "agent-browser %s failed (rc=%d): %s",
                args[0] if args else "?",
                proc.returncode,
                (stderr or b"").decode()[:200],
            )
            return ""
        return (stdout or b"").decode()
    except asyncio.TimeoutError:
        logger.debug("agent-browser %s timed out after %.0fs", args[0] if args else "?", timeout)
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        return ""
    except Exception as e:
        logger.debug("agent-browser command failed: %s", e)
        return ""


def _extract_text_from_snapshot(snapshot: str) -> str:
    """Extract readable text from agent-browser accessibility tree output.

    The snapshot format has lines like:
      @e1 heading "Grant Program Title"
      @e2 link "Apply Now" url="..."
      @e3 text "Description of the grant..."

    We extract the quoted text content and join with newlines,
    filtering out very short or navigation-only lines.
    """
    lines: list[str] = []
    for line in snapshot.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Extract text between double quotes
        matches = re.findall(r'"([^"]*)"', line)
        for text in matches:
            text = text.strip()
            if len(text) > 2:
                lines.append(text)
    return "\n".join(lines)[:80_000]


async def browser_fetch(url: str, timeout: float = 45.0) -> str:
    """Fetch page content via headless browser. Returns extracted text.

    Workflow:
      1. Open URL in a new browser tab
      2. Wait for JS rendering
      3. Take accessibility snapshot
      4. Extract text content from snapshot
      5. Close the tab

    Returns empty string on any failure (matches _fetch_plain() contract).
    Never raises.
    """
    sem = _get_sem()
    async with sem:
        try:
            return await asyncio.wait_for(
                _browser_fetch_inner(url), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.debug("browser_fetch overall timeout for %s", url[:60])
            return ""
        except Exception as e:
            logger.debug("browser_fetch failed for %s: %s", url[:60], e)
            return ""


async def _browser_fetch_inner(url: str) -> str:
    """Inner implementation — handles open/snapshot/close lifecycle."""
    # Open page
    open_result = await _run_cmd("open", url, timeout=20.0)
    if not open_result:
        logger.debug("agent-browser open failed for %s", url[:60])
        return ""

    try:
        # Wait for JS to render
        await asyncio.sleep(_PAGE_LOAD_WAIT)

        # Take accessibility snapshot (interactive mode for form elements)
        snapshot = await _run_cmd("snapshot", "-i", timeout=15.0)
        if not snapshot:
            logger.debug("agent-browser snapshot empty for %s", url[:60])
            return ""

        # Extract readable text
        content = _extract_text_from_snapshot(snapshot)
        if content:
            logger.debug(
                "Browser fetched %d chars from %s", len(content), url[:60]
            )
        return content

    finally:
        # Always close to prevent session leaks
        await _run_cmd("close", timeout=5.0)


async def browser_fetch_with_interaction(
    url: str,
    click_ref: str | None = None,
    wait_after_click: float = 2.0,
    timeout: float = 60.0,
) -> str:
    """Advanced fetch: open page, optionally click an element, then snapshot.

    Used for pages where content is behind tabs, dropdowns, or "load more" buttons.
    The click_ref should be an element reference from a prior snapshot (e.g. "@e5").

    Returns empty string on any failure. Never raises.
    """
    sem = _get_sem()
    async with sem:
        try:
            return await asyncio.wait_for(
                _browser_interact_inner(url, click_ref, wait_after_click),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.debug("browser_fetch_with_interaction timeout for %s", url[:60])
            return ""
        except Exception as e:
            logger.debug("browser_fetch_with_interaction failed for %s: %s", url[:60], e)
            return ""


async def _browser_interact_inner(
    url: str, click_ref: str | None, wait_after_click: float
) -> str:
    """Inner implementation for interactive browser fetch."""
    open_result = await _run_cmd("open", url, timeout=20.0)
    if not open_result:
        return ""

    try:
        await asyncio.sleep(_PAGE_LOAD_WAIT)

        if click_ref:
            await _run_cmd("click", click_ref, timeout=10.0)
            await asyncio.sleep(wait_after_click)

        snapshot = await _run_cmd("snapshot", "-i", timeout=15.0)
        if not snapshot:
            return ""

        return _extract_text_from_snapshot(snapshot)

    finally:
        await _run_cmd("close", timeout=5.0)
