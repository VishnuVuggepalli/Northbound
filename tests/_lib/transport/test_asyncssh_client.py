"""SshClient — minimal smoke tests.

Real SSH against a fixture server is overkill for Wave A. These tests
exercise param plumbing and connect-failure surface against a dead host.
The full integration is `@pytest.mark.integration` and skipped here.
"""

from __future__ import annotations

import asyncio

import pytest

from northbound._lib.transport.asyncssh_client import SshClient, SshParams


def test_known_hosts_arg_accept_new_returns_none() -> None:
    client = SshClient(
        SshParams(
            host="127.0.0.1",
            username="u",
            password="p",
            known_hosts_mode="accept-new",
        )
    )
    assert client._known_hosts_arg() is None


def test_known_hosts_arg_strict_returns_empty_tuple() -> None:
    client = SshClient(
        SshParams(
            host="127.0.0.1",
            username="u",
            password="p",
            known_hosts_mode="strict",
        )
    )
    assert client._known_hosts_arg() == ()


@pytest.mark.asyncio
async def test_run_against_unreachable_port_times_out_or_errors() -> None:
    """Closed port on localhost: must raise *something*, not hang."""
    client = SshClient(
        SshParams(
            host="127.0.0.1",
            port=1,  # port 1 is reserved + closed
            username="u",
            password="p",
            timeout_seconds=2.0,
        )
    )
    with pytest.raises((OSError, asyncio.TimeoutError, Exception)):
        await client.run("echo hi")
