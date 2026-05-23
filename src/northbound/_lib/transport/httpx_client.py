"""Thin async HTTPX wrapper.

Adds the few things every driver wants: a per-instance concurrency
semaphore, sane defaults for self-signed lab certs (opt-in), and small
auth helpers so drivers don't reinvent headers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class HttpxParams:
    base_url: str
    timeout_seconds: float = 10.0
    max_concurrency: int = 5
    verify_tls: bool = True  # set False ONLY for self-signed lab certs


class HttpxClient:
    def __init__(self, params: HttpxParams) -> None:
        self._params = params
        self._sem = asyncio.Semaphore(params.max_concurrency)
        self._client = httpx.AsyncClient(
            base_url=params.base_url,
            timeout=params.timeout_seconds,
            verify=params.verify_tls,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpxClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @staticmethod
    def basic_auth_header(username: str, password: str) -> dict[str, str]:
        import base64

        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    @staticmethod
    def bearer_auth_header(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: object | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with self._sem:
            return await self._client.request(
                method, url, headers=headers, json=json, params=params
            )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("GET", url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        return await self.request("POST", url, headers=headers, json=json)
