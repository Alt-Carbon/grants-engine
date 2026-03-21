"""Reusable authentication helpers for internal backend APIs."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException

from backend.config.settings import get_settings


def verify_internal_secret(x_internal_secret: Optional[str]) -> None:
    expected = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")
    if x_internal_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


def verify_cron_secret(x_cron_secret: Optional[str]) -> None:
    expected = os.environ.get("CRON_SECRET", "dev-cron-secret")
    if x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret")


def normalize_user_email(
    x_user_email: Optional[str],
    *,
    allow_system: bool,
) -> str:
    """Normalize a caller identity from request headers."""
    if not x_user_email:
        if allow_system:
            return "system"
        raise HTTPException(status_code=401, detail="Missing authenticated user email")

    email = x_user_email.strip().lower()
    if not email:
        if allow_system:
            return "system"
        raise HTTPException(status_code=401, detail="Missing authenticated user email")

    if "@" not in email:
        if allow_system and email == "system":
            return email
        raise HTTPException(status_code=401, detail="Invalid authenticated user email")

    allowed_domain = get_settings().company_domain.strip().lower()
    if not email.endswith(f"@{allowed_domain}"):
        raise HTTPException(
            status_code=403,
            detail=f"Unauthorized email domain. Only @{allowed_domain} allowed.",
        )
    return email
