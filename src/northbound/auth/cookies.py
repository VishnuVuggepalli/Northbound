"""Auth session cookies (httpOnly) — the hardened browser session transport.

The access token rides in ``nb_access`` (sent on every request, path=/); the
refresh token rides in ``nb_refresh`` scoped to ``/api/auth`` so it only leaves
the browser for the refresh/logout endpoints. Both are httpOnly (no JS access →
XSS can't read them) and SameSite=Lax (same-origin SPA; blocks cross-site CSRF
on state-changing navigations). Secure is set outside development.

API clients (scripts, tests) may keep using ``Authorization: Bearer`` — the
deps layer accepts either, so this is additive, not a breaking change.
"""

from __future__ import annotations

from fastapi import Response

from northbound.config import Settings

ACCESS_COOKIE = "nb_access"
REFRESH_COOKIE = "nb_refresh"
_REFRESH_PATH = "/api/auth"


def set_session_cookies(
    response: Response, *, access_token: str, refresh_token: str, settings: Settings
) -> None:
    """Set the access + refresh cookies with hardened flags."""
    secure = settings.auth_cookie_secure
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=_REFRESH_PATH,
    )


def clear_session_cookies(response: Response) -> None:
    """Delete both auth cookies (logout). Paths must match those used to set."""
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=_REFRESH_PATH)
