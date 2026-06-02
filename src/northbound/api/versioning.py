"""API versioning via the ``Accept`` header (vendor media type).

Northbound speaks one API version today (v1). A client MAY pin it explicitly with
``Accept: application/vnd.northbound.v1+json``; a request that pins a *different*
version gets 406 (Not Acceptable) rather than being served a contract it didn't
ask for. Requests that don't pin a version (``application/json``, ``*/*``, a
browser's Accept, or none) are served v1 unchanged — versioning is opt-in.

Every response carries ``X-API-Version`` so clients can detect the served
version without parsing bodies.
"""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_VERSION = "1"
API_VERSION_HEADER = "X-API-Version"

# Matches the vendor media type and captures the pinned version, e.g.
# "application/vnd.northbound.v2+json" -> "2". Case-insensitive.
_VENDOR_RE = re.compile(r"application/vnd\.northbound\.v(\d+)\+json", re.IGNORECASE)


def _requested_version(accept: str) -> str | None:
    """Return the pinned version from an Accept header, or None if unpinned."""
    match = _VENDOR_RE.search(accept or "")
    return match.group(1) if match else None


class ApiVersionMiddleware:
    """Reject an unsupported pinned version (406); stamp ``X-API-Version`` on all."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        pinned = _requested_version(request.headers.get("accept", ""))
        if pinned is not None and pinned != API_VERSION:
            response: Response = JSONResponse(
                status_code=406,
                content={
                    "detail": (
                        f"Unsupported API version v{pinned}; this server speaks "
                        f"v{API_VERSION}. Use Accept: application/vnd.northbound."
                        f"v{API_VERSION}+json or application/json."
                    )
                },
                headers={API_VERSION_HEADER: API_VERSION},
            )
            await response(scope, receive, send)
            return

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((API_VERSION_HEADER.encode(), API_VERSION.encode()))
            await send(message)

        await self.app(scope, receive, send_with_version)
