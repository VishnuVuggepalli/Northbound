"""Async SNMP client built on puresnmp.

Wave A: v2c first-class, v3 stubbed. Per-instance semaphore enforces
``max_concurrency``. A recorded-replay mode (``NB_SNMP_REPLAY_DIR``) lets
tests run offline against canned JSON responses keyed by host + OID.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class _SnmpTransport(Protocol):
    """Minimal async surface we need from the underlying SNMP client.

    Defined as a Protocol so tests can substitute a fake without touching
    network code paths or the puresnmp import.
    """

    async def get(self, oid: str) -> Any: ...
    async def walk(self, oid: str) -> list[tuple[str, Any]]: ...
    async def multiget(self, oids: list[str]) -> list[Any]: ...


@dataclass(frozen=True)
class SnmpV2cParams:
    host: str
    community: str
    port: int = 161
    timeout_seconds: float = 5.0
    max_concurrency: int = 5


class SnmpClient:
    """Thin async wrapper around puresnmp.

    Construct with either real ``SnmpV2cParams`` (uses puresnmp) or pass a
    ``transport=`` for tests. v3 is intentionally unimplemented in Wave A.
    """

    def __init__(
        self,
        params: SnmpV2cParams,
        *,
        transport: _SnmpTransport | None = None,
    ) -> None:
        self._params = params
        self._sem = asyncio.Semaphore(params.max_concurrency)
        self._transport = transport
        self._replay_dir = self._resolve_replay_dir()

    @staticmethod
    def _resolve_replay_dir() -> Path | None:
        raw = os.environ.get("NB_SNMP_REPLAY_DIR")
        return Path(raw) if raw else None

    @classmethod
    def v3(cls, *args: object, **kwargs: object) -> SnmpClient:
        raise NotImplementedError("SNMPv3 not implemented in Wave A")

    def _replay_path(self, oid: str) -> Path | None:
        if self._replay_dir is None:
            return None
        # OIDs contain dots; replace to keep filenames sane.
        safe = oid.replace(".", "_")
        return self._replay_dir / self._params.host / f"{safe}.json"

    async def _from_replay(self, oid: str) -> Any | None:
        path = self._replay_path(oid)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text())

    def _real_transport(self) -> _SnmpTransport:
        if self._transport is not None:
            return self._transport
        # Lazy import so the module imports cleanly when puresnmp isn't on
        # the path (e.g. unit-test isolation).
        from puresnmp import V2C, Client, PyWrapper

        client = PyWrapper(
            Client(
                self._params.host,
                V2C(self._params.community),
                port=self._params.port,
            )
        )
        # PyWrapper exposes async get/walk/multiget compatible with Protocol.
        return client  # type: ignore[return-value]

    async def get(self, oid: str) -> Any:
        replayed = await self._from_replay(oid)
        if replayed is not None:
            return replayed
        async with self._sem:
            transport = self._real_transport()
            return await asyncio.wait_for(transport.get(oid), timeout=self._params.timeout_seconds)

    async def walk(self, oid_prefix: str) -> list[tuple[str, Any]]:
        replayed = await self._from_replay(oid_prefix + ".walk")
        if replayed is not None:
            return [(k, v) for k, v in replayed]
        async with self._sem:
            transport = self._real_transport()
            return await asyncio.wait_for(
                transport.walk(oid_prefix), timeout=self._params.timeout_seconds
            )

    async def bulk_get(self, oids: list[str]) -> list[Any]:
        # Try replay only if every oid has a fixture; otherwise punt to live.
        if self._replay_dir is not None:
            replayed: list[Any] = []
            for oid in oids:
                value = await self._from_replay(oid)
                if value is None:
                    replayed = []
                    break
                replayed.append(value)
            if replayed:
                return replayed
        async with self._sem:
            transport = self._real_transport()
            return await asyncio.wait_for(
                transport.multiget(oids), timeout=self._params.timeout_seconds
            )
