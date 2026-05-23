"""GET /api/platforms contract."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from northbound.main import app


@pytest.mark.asyncio
async def test_list_platforms_returns_list_with_mock() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/platforms")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1

    mock_entries = [p for p in body if p["platform_id"] == "mock"]
    assert len(mock_entries) == 1
    mock = mock_entries[0]
    assert mock["display_name"] == "Mock (testing)"

    caps = mock["capabilities"]
    for key in (
        "writable",
        "supports_commit_confirm",
        "native_api_available",
        "supports_snmp_read",
        "supports_lldp",
        "max_concurrency",
        "auth_methods",
        "web_ui_url_template",
    ):
        assert key in caps, f"capability missing: {key}"
    assert caps["writable"] is True
    assert isinstance(caps["auth_methods"], list)
