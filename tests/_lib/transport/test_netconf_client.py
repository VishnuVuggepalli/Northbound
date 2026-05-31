"""NetconfClient — verify the asyncio.to_thread wrapping + arg passing."""

from __future__ import annotations

from typing import Any

import pytest

from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams


class _FakeManager:
    """Fake whose signatures MIRROR REAL ncclient (0.7.1), so a wrapper call
    that mis-maps positionally would blow up here just as it does live:

        edit_config(config, format='xml', target='candidate',
                    default_operation=None, test_option=None, error_option=None)
        commit(confirmed=False, timeout=None, persist=None, persist_id=None)
        get_config(source, filter=None, with_defaults=None)
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def get_config(self, source: str, filter: Any = None, with_defaults: Any = None) -> str:
        self.calls.append(("get_config", (source,), {}))
        return f"<config source={source}/>"

    def edit_config(
        self,
        config: str,
        format: str = "xml",
        target: str = "candidate",
        default_operation: str | None = None,
        test_option: str | None = None,
        error_option: str | None = None,
    ) -> str:
        self.calls.append(
            (
                "edit_config",
                (),
                {
                    "config": config,
                    "format": format,
                    "target": target,
                    "default_operation": default_operation,
                    "test_option": test_option,
                    "error_option": error_option,
                },
            )
        )
        return "ok"

    def commit(
        self,
        confirmed: bool = False,
        timeout: int | None = None,
        persist: Any = None,
        persist_id: Any = None,
    ) -> str:
        self.calls.append(("commit", (), {"confirmed": confirmed, "timeout": timeout}))
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
async def test_edit_config_maps_to_real_ncclient_kwargs() -> None:
    """The wrapper's (target, config) MUST land in ncclient's (target, config)
    slots — not positionally, which would put ``target`` into ncclient's
    ``config`` param. Asserts the keyword mapping against a real-signature fake."""
    client, fake = _make_client()
    await client.edit_config("candidate", "<x/>", default_operation="merge")
    name, _, kwargs = fake.calls[0]
    assert name == "edit_config"
    assert kwargs["config"] == "<x/>"  # our XML, NOT "candidate"
    assert kwargs["target"] == "candidate"  # our target, NOT the XML
    assert kwargs["default_operation"] == "merge"
    assert kwargs["format"] == "xml"  # ncclient default preserved


@pytest.mark.asyncio
async def test_commit_confirmed_coerces_timeout_to_str() -> None:
    """ncclient writes <confirm-timeout> via lxml, which requires str text — an
    int raises TypeError against a real server. The wrapper MUST coerce."""
    client, fake = _make_client()
    await client.commit(confirmed=True, timeout=60)
    name, _, kwargs = fake.calls[0]
    assert name == "commit"
    assert kwargs == {"confirmed": True, "timeout": "60"}
    assert isinstance(kwargs["timeout"], str)


@pytest.mark.asyncio
async def test_commit_without_timeout_passes_none() -> None:
    client, fake = _make_client()
    await client.commit(confirmed=False)
    _, _, kwargs = fake.calls[0]
    assert kwargs == {"confirmed": False, "timeout": None}


@pytest.mark.asyncio
async def test_close_marks_session_closed() -> None:
    client, fake = _make_client()
    await client.get_config()
    await client.close()
    assert fake.closed is True
