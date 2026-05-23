"""HTML scraping helpers for SwOS-style pages.

SwOS responds to ``/!form_b`` etc. with pipe-delimited / hex-encoded
key=value blobs. Parsing primitives live here; the SwOS-specific glue
lives in the driver later.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup


async def fetch_page(
    url: str,
    *,
    auth: tuple[str, str] | None = None,
    timeout_seconds: float = 10.0,
    verify_tls: bool = False,
) -> BeautifulSoup:
    """GET ``url`` and parse the body as HTML (lxml backend)."""
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        verify=verify_tls,
        auth=auth,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")


def parse_form_b_response(text: str) -> dict[str, str]:
    """Parse SwOS-style ``key:value|key:value|...`` blobs.

    Whitespace around tokens is stripped. Empty tokens are skipped.
    Tokens without a colon are recorded with an empty value — callers can
    decide whether to treat that as an error.
    """
    out: dict[str, str] = {}
    for chunk in text.split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition(":")
        out[key.strip()] = value.strip()
    return out
