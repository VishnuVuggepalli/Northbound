"""HttpxClient — verify auth helpers + behavior against a MockTransport."""

from __future__ import annotations

import httpx
import pytest

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams


def test_basic_auth_header_is_b64_username_password() -> None:
    header = HttpxClient.basic_auth_header("alice", "s3cret")
    # Authorization: Basic YWxpY2U6czNjcmV0
    assert header == {"Authorization": "Basic YWxpY2U6czNjcmV0"}


def test_bearer_auth_header_format() -> None:
    assert HttpxClient.bearer_auth_header("xyz") == {"Authorization": "Bearer xyz"}


@pytest.mark.asyncio
async def test_get_uses_underlying_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True})

    client = HttpxClient(HttpxParams(base_url="http://example.test", verify_tls=False))
    # Swap in mock transport on the underlying AsyncClient.
    client._client._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]

    response = await client.get(
        "/api/v1/status",
        headers=HttpxClient.bearer_auth_header("tok"),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert seen["auth_header"] == "Bearer tok"
    assert seen["url"] == "http://example.test/api/v1/status"
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_raises() -> None:
    def slow_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated")

    client = HttpxClient(HttpxParams(base_url="http://example.test", timeout_seconds=0.01))
    client._client._transport = httpx.MockTransport(slow_handler)  # type: ignore[attr-defined]

    with pytest.raises(httpx.ConnectTimeout):
        await client.get("/x")
    await client.aclose()
