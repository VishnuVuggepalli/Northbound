"""SnmpClient — exercise the wrapper, not puresnmp."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from northbound._lib.transport.snmp_client import SnmpClient, SnmpV2cParams


class _FakeTransport:
    """In-memory async SNMP responder."""

    def __init__(
        self,
        values: dict[str, Any] | None = None,
        *,
        delay: float = 0.0,
        track_concurrency: bool = False,
    ) -> None:
        self._values = values or {}
        self._delay = delay
        self.track_concurrency = track_concurrency
        self.active = 0
        self.peak = 0

    async def _hold(self) -> None:
        if self.track_concurrency:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
        finally:
            if self.track_concurrency:
                self.active -= 1

    async def get(self, oid: str) -> Any:
        await self._hold()
        return self._values.get(oid, "unknown")

    async def walk(self, oid: str) -> list[tuple[str, Any]]:
        await self._hold()
        return [(k, v) for k, v in self._values.items() if k.startswith(oid)]

    async def multiget(self, oids: list[str]) -> list[Any]:
        await self._hold()
        return [self._values.get(o, "unknown") for o in oids]


@pytest.mark.asyncio
async def test_get_returns_value_from_transport() -> None:
    fake = _FakeTransport({"1.3.6.1.2.1.1.1.0": "linux"})
    client = SnmpClient(
        SnmpV2cParams(host="10.0.0.1", community="public"),
        transport=fake,
    )
    assert await client.get("1.3.6.1.2.1.1.1.0") == "linux"


@pytest.mark.asyncio
async def test_get_times_out_on_slow_transport() -> None:
    fake = _FakeTransport({"oid": "v"}, delay=0.5)
    client = SnmpClient(
        SnmpV2cParams(
            host="10.0.0.1",
            community="public",
            timeout_seconds=0.05,
        ),
        transport=fake,
    )
    with pytest.raises(asyncio.TimeoutError):
        await client.get("oid")


@pytest.mark.asyncio
async def test_semaphore_caps_concurrency() -> None:
    fake = _FakeTransport(
        {f"oid.{i}": i for i in range(20)},
        delay=0.05,
        track_concurrency=True,
    )
    client = SnmpClient(
        SnmpV2cParams(host="10.0.0.1", community="public", max_concurrency=3),
        transport=fake,
    )
    await asyncio.gather(*[client.get(f"oid.{i}") for i in range(10)])
    assert fake.peak <= 3, f"peak concurrency {fake.peak} exceeded cap 3"


@pytest.mark.asyncio
async def test_walk_returns_pairs() -> None:
    fake = _FakeTransport(
        {
            "1.3.6.1.2.1.2.2.1.2.1": "Ethernet1",
            "1.3.6.1.2.1.2.2.1.2.2": "Ethernet2",
        }
    )
    client = SnmpClient(
        SnmpV2cParams(host="10.0.0.1", community="public"),
        transport=fake,
    )
    rows = await client.walk("1.3.6.1.2.1.2.2.1.2")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_replay_mode_reads_from_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host_dir = tmp_path / "10.0.0.99"
    host_dir.mkdir()
    (host_dir / "1_3_6_1_2_1_1_1_0.json").write_text(json.dumps("replayed-os"))

    monkeypatch.setenv("NB_SNMP_REPLAY_DIR", str(tmp_path))
    client = SnmpClient(
        SnmpV2cParams(host="10.0.0.99", community="public"),
        # No transport — proves replay path doesn't touch real puresnmp.
    )
    assert await client.get("1.3.6.1.2.1.1.1.0") == "replayed-os"


@pytest.mark.asyncio
async def test_v3_constructor_raises() -> None:
    with pytest.raises(NotImplementedError):
        SnmpClient.v3()
