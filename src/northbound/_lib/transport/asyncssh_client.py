"""Async SSH command runner using asyncssh.

Most switches dislike concurrent SSH sessions, so the default semaphore is
1. ``known_hosts`` strategy is a config switch — lab clusters use
``accept-new``, production must use a real known_hosts file.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

KnownHostsMode = Literal["accept-new", "strict"]


@dataclass(frozen=True)
class SshParams:
    host: str
    username: str
    port: int = 22
    password: str | None = None
    private_key: str | None = None  # PEM contents
    timeout_seconds: float = 10.0
    max_concurrency: int = 1
    known_hosts_mode: KnownHostsMode = "accept-new"


class SshClient:
    """Minimal async-ssh facade.

    Connections are short-lived — opened per ``run()`` call. Persistent
    sessions are a later optimization; doing it right requires care around
    server-side keepalive and TCP RSTs from devices that idle-kill SSH.
    """

    def __init__(self, params: SshParams) -> None:
        self._params = params
        self._sem = asyncio.Semaphore(params.max_concurrency)

    def _known_hosts_arg(self) -> object:
        # asyncssh accepts None to disable known_hosts (accept any),
        # which is acceptable for lab use only.
        return None if self._params.known_hosts_mode == "accept-new" else ()

    async def run(self, command: str) -> str:
        # Lazy import keeps unit tests free of the asyncssh dependency cost.
        import asyncssh

        async with self._sem:
            connect_kwargs: dict[str, object] = {
                "host": self._params.host,
                "port": self._params.port,
                "username": self._params.username,
                "known_hosts": self._known_hosts_arg(),
            }
            if self._params.private_key is not None:
                connect_kwargs["client_keys"] = [self._params.private_key]
            if self._params.password is not None:
                connect_kwargs["password"] = self._params.password

            async def _do() -> str:
                async with asyncssh.connect(**connect_kwargs) as conn:  # type: ignore[arg-type]
                    result = await conn.run(command, check=False)
                    stdout = result.stdout
                    if isinstance(stdout, bytes):
                        return stdout.decode(errors="replace")
                    return stdout or ""

            return await asyncio.wait_for(_do(), timeout=self._params.timeout_seconds)
