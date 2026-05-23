"""HTML scrape helpers."""

from __future__ import annotations

import httpx
import pytest

from northbound._lib.transport import html_scrape


def test_parse_form_b_response_basic() -> None:
    text = "name:switch01|model:CSS610|uptime:1234"
    assert html_scrape.parse_form_b_response(text) == {
        "name": "switch01",
        "model": "CSS610",
        "uptime": "1234",
    }


def test_parse_form_b_response_skips_empty_tokens() -> None:
    text = "||a:1|  |b:2|"
    assert html_scrape.parse_form_b_response(text) == {"a": "1", "b": "2"}


def test_parse_form_b_response_handles_keyless_token() -> None:
    text = "no-colon-token|a:1"
    out = html_scrape.parse_form_b_response(text)
    assert out["no-colon-token"] == ""
    assert out["a"] == "1"


@pytest.mark.asyncio
async def test_fetch_page_returns_soup(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><h1>hello</h1></body></html>",
        )

    # Patch httpx.AsyncClient to use the mock transport.
    real_async_client = httpx.AsyncClient

    def patched(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(html_scrape.httpx, "AsyncClient", patched)
    soup = await html_scrape.fetch_page("http://swos.local/")
    assert soup.find("h1") is not None
    h1 = soup.find("h1")
    assert h1 is not None
    assert h1.get_text() == "hello"
