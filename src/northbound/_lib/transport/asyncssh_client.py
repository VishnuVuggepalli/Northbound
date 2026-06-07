"""Async SSH command runner using asyncssh.

Most switches dislike concurrent SSH sessions, so the default semaphore is 1.

``known_hosts`` semantics (honest about what asyncssh actually does):

* ``"insecure"`` → pass ``known_hosts=None``, which DISABLES host-key
  checking entirely (asyncssh accepts ANY host key). This is convenient but
  offers no MITM protection — **LAB USE ONLY**. It is the default so lab
  bring-up works out of the box, but it is genuinely insecure.
* ``"strict"`` → real host-key verification. Requires ``known_hosts_path`` to
  point at a known_hosts file; that path is passed straight to asyncssh.
  If the path is unset we **fail closed** with a clear error rather than
  silently accepting any host (``None``) or rejecting every host (``()``,
  which asyncssh treats as "nothing is known" → every connection fails).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

# "insecure": accept any host key (known_hosts=None) — lab only.
# "strict": verify against known_hosts_path (fail closed if unset).
KnownHostsMode = Literal["insecure", "strict"]


@dataclass(frozen=True)
class SshParams:
    host: str
    username: str
    port: int = 22
    password: str | None = None
    private_key: str | None = None  # PEM contents
    timeout_seconds: float = 10.0
    max_concurrency: int = 1
    # Default lab-friendly but INSECURE (no host-key checking). Production
    # must set "strict" + known_hosts_path. See module docstring.
    known_hosts_mode: KnownHostsMode = "insecure"
    known_hosts_path: str | None = None  # required when mode == "strict"


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
        """Resolve the asyncssh ``known_hosts`` argument for the chosen mode.

        Raises:
            ValueError: ``strict`` mode without a ``known_hosts_path`` —
                fail closed rather than silently accept-all or reject-all.
        """
        if self._params.known_hosts_mode == "strict":
            path = self._params.known_hosts_path
            if not path:
                raise ValueError(
                    "SSH known_hosts_mode='strict' requires known_hosts_path; "
                    "refusing to connect without a verification source "
                    "(fail-closed)"
                )
            return path
        # "insecure": disable host-key checking entirely (accept any). Lab only.
        return None

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
