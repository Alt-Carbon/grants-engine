"""Headless browser fetch via agent-browser CLI.

Provides async wrappers around the `agent-browser` Node.js CLI tool for
rendering JS-heavy pages (Notion Sites, SPAs, Cloudflare-protected pages).

Install: npm install -g agent-browser
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# Concurrency: max 2 parallel Chromium sessions (~100-200MB each)
_SEM: Optional[asyncio.Semaphore] = None
_PAGE_LOAD_WAIT = 3.0  # seconds to wait for JS rendering


def _get_sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(2)
    return _SEM


def is_available() -> bool:
    """Check if agent-browser CLI is installed."""
    return shutil.which("agent-browser") is not None


async def _run_cmd(*args: str, timeout: float = 30.0) -> str:
    """Run an agent-browser CLI command. Returns stdout or empty string on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "agent-browser", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            logger.debug("agent-browser %s failed (rc=%d): %s", args[0], proc.returncode, stderr.decode()[:200])
            return ""
        return stdout.decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        logger.debug("agent-browser %s timed out after %.0fs", args[0], timeout)
        try:
            proc.kill()
        except Exception:
            pass
        return ""
    except Exception as e:
        logger.debug("agent-browser %s error: %s", args[0], e)
        return ""


def _extract_text_from_snapshot(snapshot: str) -> str:
    """Parse agent-browser accessibility tree snapshot and extract text content.

    Snapshot format: lines like '@e1 heading "Page Title"' or '@e5 text "Some content"'
    """
    lines = []
    for line in snapshot.splitlines():
        # Extract quoted text content
        match = re.search(r'"(.+)"', line)
        if match:
            text = match.group(1).strip()
            if len(text) > 3:  # skip tiny fragments
                lines.append(text)

    result = "\n".join(lines)
    return result[:80_000]


async def browser_fetch(url: str, timeout: float = 45.0) -> str:
    """Fetch page content via agent-browser headless Chromium.

    Opens URL → waits for JS rendering → takes accessibility snapshot →
    extracts text → closes session.

    Returns extracted text or empty string on failure. Never raises.
    """
    if not is_available():
        logger.debug("agent-browser not installed — skipping browser fetch")
        return ""

    sem = _get_sem()
    async with sem:
        try:
            # Open page
            result = await _run_cmd("open", url, timeout=20.0)
            if not result and "error" not in result.lower():
                pass  # open may return empty on success

            # Wait for JS to render
            await asyncio.sleep(_PAGE_LOAD_WAIT)

            # Take accessibility snapshot
            snapshot = await _run_cmd("snapshot", "-i", timeout=15.0)
            if not snapshot:
                logger.debug("Browser snapshot empty for %s", url[:60])
                return ""

            # Extract text
            text = _extract_text_from_snapshot(snapshot)
            if text:
                logger.debug("Browser fetch got %d chars from %s", len(text), url[:60])
            return text

        except Exception as e:
            logger.debug("Browser fetch failed for %s: %s", url[:60], e)
            return ""
        finally:
            # Always close session
            await _run_cmd("close", timeout=5.0)
