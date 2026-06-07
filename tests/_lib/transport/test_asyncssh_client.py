"""SshClient — minimal smoke tests.

Real SSH against a fixture server is overkill for Wave A. These tests
exercise param plumbing and connect-failure surface against a dead host.
The full integration is `@pytest.mark.integration` and skipped here.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from northbound._lib.transport.asyncssh_client import SshClient, SshParams


def test_known_hosts_arg_insecure_returns_none() -> None:
    """'insecure' → known_hosts=None → asyncssh accepts ANY host key (lab)."""
    client = SshClient(
        SshParams(
            host="127.0.0.1",
            username="u",
            password="p",
            known_hosts_mode="insecure",
        )
    )
    assert client._known_hosts_arg() is None


def test_default_mode_is_insecure() -> None:
    client = SshClient(SshParams(host="127.0.0.1", username="u", password="p"))
    assert client._known_hosts_arg() is None


def test_known_hosts_arg_strict_returns_path_when_set() -> None:
    """'strict' with a path → real verification against that known_hosts file."""
    client = SshClient(
        SshParams(
            host="127.0.0.1",
            username="u",
            password="p",
            known_hosts_mode="strict",
            known_hosts_path="/etc/ssh/known_hosts",
        )
    )
    assert client._known_hosts_arg() == "/etc/ssh/known_hosts"


def test_known_hosts_arg_strict_without_path_fails_closed() -> None:
    """'strict' with no path must FAIL CLOSED, not accept-all or reject-all."""
    client = SshClient(
        SshParams(
            host="127.0.0.1",
            username="u",
            password="p",
            known_hosts_mode="strict",
        )
    )
    with pytest.raises(ValueError, match="known_hosts_path"):
        client._known_hosts_arg()


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


# ---------------------------------------------------------------------------
# Opt-in LIVE integration test — runs only against a real device.
#
# Set NB_LIVE_SSH_HOST (and optionally NB_LIVE_SSH_USER / NB_LIVE_SSH_PASS /
# NB_LIVE_SSH_PORT) to point at the sandbox FRR node (sandbox/bring-up.sh).
# Skipped when unset so the default suite stays hermetic. This is the live
# validation of the SSH transport against real network-OS software (FRR
# vtysh), standing in for the FreeBSD/FRR read path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_ssh_run_returns_real_output() -> None:
    host = os.environ.get("NB_LIVE_SSH_HOST")
    if not host:
        pytest.skip("NB_LIVE_SSH_HOST not set — live SSH device unavailable")
    client = SshClient(
        SshParams(
            host=host,
            port=int(os.environ.get("NB_LIVE_SSH_PORT", "22")),
            username=os.environ.get("NB_LIVE_SSH_USER", "nbadmin"),
            password=os.environ.get("NB_LIVE_SSH_PASS", "nbsandbox"),
            known_hosts_mode="insecure",
            timeout_seconds=15.0,
        )
    )
    out = await client.run("uname -a")
    assert out.strip(), "live device returned empty output for uname -a"
