"""Shared FastAPI dependency functions for route authentication."""
from __future__ import annotations

from typing import Optional

from fastapi import Header


def verify_cron(x_cron_secret: Optional[str] = Header(default=None)):
    from backend.platform.services.auth_service import verify_cron_secret

    verify_cron_secret(x_cron_secret)


def verify_internal(
    x_internal_secret: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    from backend.platform.services.auth_service import verify_internal_secret

    verify_internal_secret(x_internal_secret)


def get_user_email(x_user_email: Optional[str] = Header(default=None)) -> str:
    """Extract user email from request headers. Validates domain server-side."""
    from backend.platform.services.auth_service import normalize_user_email

    return normalize_user_email(x_user_email, allow_system=True)


def get_authenticated_user_email(x_user_email: Optional[str] = Header(default=None)) -> str:
    """Extract a real authenticated user email for user-scoped endpoints."""
    from backend.platform.services.auth_service import normalize_user_email

    return normalize_user_email(x_user_email, allow_system=False)
