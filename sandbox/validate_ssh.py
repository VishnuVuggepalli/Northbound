#!/usr/bin/env python3
"""Live validation of the asyncssh transport against a real SSH/FRR device.

This is the one transport that CAN be exercised against real network-OS
software in the build sandbox (FRR over SSH stands in for the FreeBSD/FRR
read path: `vtysh -c "show running-config"`). cEOS eAPI, NX-API, and Pica8
NETCONF need auth/licensed images that are not obtainable here — see
supporting material/vendor-docs/validation-status.md.

It drives `northbound._lib.transport.asyncssh_client.SshClient` exactly as a
read-only SSH driver would, against the sandbox FRR node, and asserts real
command output comes back.

Usage:
  python sandbox/validate_ssh.py --host 172.20.20.X --username nbadmin --password nbsandbox
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound._lib.transport.asyncssh_client import SshClient, SshParams  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    client = SshClient(
        SshParams(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            known_hosts_mode="insecure",  # lab-only; see asyncssh_client honest modes
            timeout_seconds=15.0,
        )
    )
    # The FreeBSD/FRR read path uses these exact commands (vendor-docs §5).
    commands = [
        "uname -a",
        'vtysh -c "show running-config"',
        'vtysh -c "show ip bgp summary"',
    ]
    failures = 0
    for cmd in commands:
        try:
            out = await client.run(cmd)
            ok = bool(out.strip())
            status = "OK " if ok else "EMPTY"
            print(f"[{status}] {cmd}")
            head = "\n".join(out.strip().splitlines()[:4])
            if head:
                print("    " + head.replace("\n", "\n    "))
            if not ok:
                failures += 1
        except Exception as exc:
            print(f"[FAIL] {cmd}: {exc!r}")
            failures += 1

    print()
    if failures:
        print(f"SSH transport live validation: {failures} command(s) failed.")
        return 1
    print("SSH transport live validation: PASS — real device output received.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Live asyncssh transport validator")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--username", default="nbadmin")
    ap.add_argument("--password", default="nbsandbox")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
