"""NetconfClient — verify the asyncio.to_thread wrapping + arg passing."""

from __future__ import annotations

from typing import Any

import pytest

from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def get_config(self, source: str) -> str:
        self.calls.append(("get_config", (source,), {}))
        return f"<config source={source}/>"

    def edit_config(
        self,
        target: str,
        config: str,
        default_operation: str | None,
        test_option: str | None,
        error_option: str | None,
    ) -> str:
        self.calls.append(
            (
                "edit_config",
                (target, config, default_operation, test_option, error_option),
                {},
            )
        )
        return "ok"

    def commit(self, confirmed: bool, timeout: int | None) -> str:
        self.calls.append(("commit", (confirmed, timeout), {}))
        return "committed"

    def discard_changes(self) -> str:
        self.calls.append(("discard_changes", (), {}))
        return "discarded"

    def close_session(self) -> None:
        self.closed = True


def _make_client() -> tuple[NetconfClient, _FakeManager]:
    fake = _FakeManager()
    client = NetconfClient(
        NetconfParams(host="10.0.0.1", username="u", password="p"),
        manager_factory=lambda: fake,
    )
    return client, fake


@pytest.mark.asyncio
async def test_get_config_runs_via_to_thread() -> None:
    client, fake = _make_client()
    result = await client.get_config("running")
    assert result == "<config source=running/>"
    assert fake.calls[0][0] == "get_config"


@pytest.mark.asyncio
async def test_edit_config_passes_args() -> None:
    client, fake = _make_client()
    await client.edit_config("candidate", "<x/>", default_operation="merge")
    name, args, _ = fake.calls[0]
    assert name == "edit_config"
    assert args == ("candidate", "<x/>", "merge", None, None)


@pytest.mark.asyncio
async def test_commit_confirmed_with_timeout() -> None:
    client, fake = _make_client()
    await client.commit(confirmed=True, timeout=60)
    name, args, _ = fake.calls[0]
    assert name == "commit"
    assert args == (True, 60)


@pytest.mark.asyncio
async def test_close_marks_session_closed() -> None:
    client, fake = _make_client()
    await client.get_config()
    await client.close()
    assert fake.closed is True
