"""build_limiter: shared rate-limit storage wiring for multi-worker.

Default (no NB_RATELIMIT_STORAGE_URI) → slowapi's in-memory storage, correct
for a single worker. When the URI is set, it must reach the Limiter so all
workers share one counter store.
"""

from __future__ import annotations

import pytest

from northbound import config
from northbound.api.limiter import build_limiter


def _settings_with(uri: str | None) -> config.Settings:
    return config.Settings(ratelimit_storage_uri=uri)


def test_default_uses_in_memory_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_settings", lambda: _settings_with(None))
    limiter = build_limiter()
    # slowapi defaults to the in-process memory backend when no URI is given.
    assert limiter._storage_uri in (None, "memory://")


def test_configured_uri_is_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("memory://"))
    limiter = build_limiter()
    assert limiter._storage_uri == "memory://"


def _request_with(scope_extra: dict | None = None, body: bytes | None = None):
    """Build a real starlette Request; cache `body` via the PUBLIC API path."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": [],
        "query_string": b"",
        "client": ("203.0.113.9", 1234),
        **(scope_extra or {}),
    }
    request = Request(scope)
    if body is not None:
        # Mirror what FastAPI's body parsing leaves behind: a cached body.
        # If Starlette ever renames its internal cache, _submitted_username
        # must be updated — this test is the canary.
        request._body = body
    return request


def test_login_rate_key_reads_cached_body() -> None:
    from northbound.api.limiter import login_rate_key

    req = _request_with(body=b'{"username": "alice", "password": "x"}')
    assert login_rate_key(req) == "203.0.113.9|alice"


def test_login_rate_key_falls_back_without_body() -> None:
    from northbound.api.limiter import login_rate_key

    assert login_rate_key(_request_with()) == "203.0.113.9|?"


def test_write_rate_key_prefers_verified_state_sub() -> None:
    """get_current_user stashes the verified sub on request.state — the key
    func must use it (covers cookie sessions with no Authorization header,
    and skips a second JWT decode for Bearer ones)."""
    from northbound.api.limiter import write_rate_key

    req = _request_with()
    req.state.auth_sub = "user-123"
    assert write_rate_key(req) == "user:user-123"


def test_write_rate_key_ip_fallback_when_unauthenticated() -> None:
    from northbound.api.limiter import write_rate_key

    assert write_rate_key(_request_with()) == "ip:203.0.113.9"
