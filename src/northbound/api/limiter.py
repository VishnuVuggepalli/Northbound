"""Shared slowapi rate limiter.

Kept in its own module so routers and ``main`` reference the same instance
without a circular import. Keyed by client IP (``get_remote_address``).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# Login throttle: 5 attempts / 5 minutes / IP (see plan.md "Auth + RBAC").
LOGIN_RATE_LIMIT = "5/5minutes"

limiter = Limiter(key_func=get_remote_address)
