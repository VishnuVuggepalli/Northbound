"""Shared slowapi rate limiter.

Kept in its own module so routers and ``main`` reference the same instance
without a circular import.

The login limiter is keyed on a **composite** of client IP + submitted
username. Two reasons:

* A single shared proxy / NAT IP must not collapse every user into one bucket
  (which would let one attacker lock everyone out, or be defeated by everyone
  sharing the budget).
* Password-spraying one password across many usernames from one IP is also
  bounded, because each (ip, username) pair gets its own 5/5min budget.

The real client IP is resolved via :func:`get_remote_address`, which reads
``request.client.host``. Behind a reverse proxy that is the proxy's IP unless
``ProxyHeadersMiddleware`` is wired (see ``main`` + ``Settings.trust_proxy_headers``)
so the forwarded client IP is used instead — and only from trusted proxy hops.
"""

from __future__ import annotations

import json
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

# Login throttle: 5 attempts / 5 minutes per (ip, username). Overridable via
# NB_LOGIN_RATE_LIMIT (e.g. "100/minute" in dev) so local testing isn't locked
# out after a few mistyped passwords; production keeps the strict default.
LOGIN_RATE_LIMIT = os.environ.get("NB_LOGIN_RATE_LIMIT", "5/5minutes")

# Registration throttle: bound account-creation spam per (ip, username).
# Overridable via NB_REGISTER_RATE_LIMIT for local testing.
REGISTER_RATE_LIMIT = os.environ.get("NB_REGISTER_RATE_LIMIT", "5/hour")


def _submitted_username(request: Request) -> str:
    """Best-effort extract the submitted username from the cached login body.

    FastAPI parses + validates the request body before invoking the
    limiter-wrapped endpoint, so ``request._body`` is already populated when
    this key func runs. We never raise: a missing/garbled body falls back to a
    constant bucket so the IP limit still applies.
    """
    raw = getattr(request, "_body", None)
    if not raw:
        return "?"
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return "?"
    if isinstance(parsed, dict):
        username = parsed.get("username")
        if isinstance(username, str) and username:
            return username
    return "?"


def login_rate_key(request: Request) -> str:
    """Composite rate-limit key: ``<client-ip>|<submitted-username>``."""
    return f"{get_remote_address(request)}|{_submitted_username(request)}"


limiter = Limiter(key_func=get_remote_address)
