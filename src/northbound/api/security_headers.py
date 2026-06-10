"""Security headers + cross-origin write guard (pure-ASGI, mirrors versioning).

Two concerns, one cheap middleware:

1. **Response headers** on every HTTP response — clickjacking (X-Frame-Options /
   frame-ancestors), MIME sniffing (nosniff), referrer leakage, and a CSP that
   acts as the second line of defence behind React's escaping. ``unsafe-inline``
   for styles is required by React inline ``style={}`` attributes (used by the
   design system); scripts stay self-only. HSTS is added only when auth cookies
   are Secure (i.e. the deployment is HTTPS-fronted) — browsers ignore it over
   plain HTTP anyway.

2. **Origin check on state-changing requests** (SameSite=Lax gap, M-7): Lax
   blocks cross-site subresource cookies but NOT top-level form POSTs. JSON body
   parsing already rejects classic form posts, leaving the body-less POSTs
   (logout/refresh) as nuisance-CSRF targets. Browsers always send ``Origin`` on
   cross-site POSTs, so: an Origin that matches neither the request's own Host
   nor the configured allowlist → 403. Requests WITHOUT an Origin header
   (curl/API clients/same-origin GETs) pass. Enforcement is skipped in
   development: the Vite dev proxy runs ``changeOrigin: true``, so Host is
   rewritten to the API target while the browser's Origin stays the dev server —
   a guaranteed false positive.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from northbound.config import get_settings

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

_BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"content-security-policy", _CSP.encode()),
)

_HSTS = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


def _origin_allowed(origin: str, host: str | None, extra_allowed: frozenset[str]) -> bool:
    """True when the Origin's netloc matches the request's own Host (same-origin)
    or the operator allowlist. ``null`` (sandboxed iframes, data: pages) is never
    same-origin."""
    if origin in extra_allowed:
        return True
    netloc = urlsplit(origin).netloc
    return bool(netloc) and host is not None and netloc == host


class SecurityHeadersMiddleware:
    """Stamp security headers on every response; 403 cross-origin writes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enforce_origin: bool | None = None,
        hsts: bool | None = None,
        extra_allowed: frozenset[str] | None = None,
    ) -> None:
        """Knobs default from settings; explicit kwargs override (tests)."""
        self.app = app
        settings = get_settings()
        self._enforce_origin = (
            enforce_origin if enforce_origin is not None else settings.environment != "development"
        )
        self._extra_allowed = (
            extra_allowed if extra_allowed is not None else frozenset(settings.allowed_origins)
        )
        self._hsts = hsts if hsts is not None else settings.auth_cookie_secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if (
            self._enforce_origin
            and request.method in _UNSAFE_METHODS
            and (origin := request.headers.get("origin")) is not None
            and not _origin_allowed(origin, request.headers.get("host"), self._extra_allowed)
        ):
            response: Response = JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request rejected"},
            )
            await self._send_with_headers(response, scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(_BASE_HEADERS)
                if self._hsts:
                    headers.append(_HSTS)
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _send_with_headers(
        self, response: Response, scope: Scope, receive: Receive, send: Send
    ) -> None:
        response.raw_headers.extend(_BASE_HEADERS)
        if self._hsts:
            response.raw_headers.append(_HSTS)
        await response(scope, receive, send)
