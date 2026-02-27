"""Shared filter helpers used across Triage and Pipeline views."""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Amount bucket definitions ─────────────────────────────────────────────────
AMOUNT_OPTIONS = [
    "Any amount",
    "< $10K",
    "$10K – $50K",
    "$50K – $100K",
    "$100K – $500K",
    "$500K+",
    "Not specified",
]

_AMOUNT_RANGES: dict[str, tuple[Optional[int], Optional[int]]] = {
    "< $10K":         (None, 9_999),
    "$10K – $50K":    (10_000, 50_000),
    "$50K – $100K":   (50_000, 100_000),
    "$100K – $500K":  (100_000, 500_000),
    "$500K+":         (500_000, None),
}


def amount_bucket_to_range(bucket: str) -> tuple[Optional[int], Optional[int]]:
    """Return (min_funding, max_funding) MongoDB params for the given bucket label."""
    return _AMOUNT_RANGES.get(bucket, (None, None))


def filter_amount_not_specified(grants: list, bucket: str) -> list:
    """For the 'Not specified' bucket, keep only grants with no max_funding."""
    if bucket != "Not specified":
        return grants
    return [g for g in grants if not g.get("max_funding")]


# ── Deadline bucket definitions ───────────────────────────────────────────────
DEADLINE_OPTIONS = [
    "Any deadline",
    "Due within 30 days",
    "Due within 60 days",
    "Due within 3 months",
    "Due within 6 months",
    "No deadline set",
]

_DEADLINE_DAYS: dict[str, int] = {
    "Due within 30 days": 30,
    "Due within 60 days": 60,
    "Due within 3 months": 90,
    "Due within 6 months": 180,
}

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
]


def _parse_deadline(deadline_str: str) -> Optional[datetime]:
    """Try to parse a deadline string into a datetime. Returns None if unparseable."""
    if not deadline_str:
        return None
    s = deadline_str.strip()
    # Skip obvious non-dates
    if s.lower() in ("not specified", "rolling", "tbd", "ongoing", "open", "–", "-", ""):
        return None

    # Try known formats
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # Try extracting YYYY-MM-DD from anywhere in the string
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            tzinfo=timezone.utc)
        except ValueError:
            pass

    # Try DD Month YYYY or Month YYYY
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                     "%d %B %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def apply_deadline_filter(grants: list, deadline_option: str) -> list:
    """Filter grants by deadline option. Returns filtered list."""
    if deadline_option == "Any deadline":
        return grants

    now = datetime.now(timezone.utc)

    if deadline_option == "No deadline set":
        return [g for g in grants
                if _parse_deadline(g.get("deadline", "")) is None]

    days = _DEADLINE_DAYS.get(deadline_option)
    if days is None:
        return grants

    cutoff = now + timedelta(days=days)
    result = []
    for g in grants:
        dl = _parse_deadline(g.get("deadline", ""))
        if dl is not None and now <= dl <= cutoff:
            result.append(g)
    return result


def active_filter_labels(
    search: str,
    theme: str,
    status: str,
    grant_type: str,
    amount: str,
    deadline: str,
    min_score: float = 0.0,
) -> list[str]:
    """Return a list of human-readable active filter labels for display."""
    labels = []
    if search:
        labels.append('Search: "' + search + '"')
    if theme:
        labels.append(f"Theme: {theme.replace('_', ' ').title()}")
    if status:
        labels.append(f"Status: {status}")
    if grant_type:
        labels.append(f"Type: {grant_type.title()}")
    if amount and amount != "Any amount":
        labels.append(f"Amount: {amount}")
    if deadline and deadline != "Any deadline":
        labels.append(f"Deadline: {deadline}")
    if min_score > 0:
        labels.append(f"Min score: {min_score}")
    return labels
