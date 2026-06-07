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
