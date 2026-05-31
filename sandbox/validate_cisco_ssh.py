#!/usr/bin/env python3
"""Live validation of the CiscoDriver SSH read path against real Cisco IOS.

The Cisco driver's PRIMARY write path is NX-API (Nexus NX-OS), which needs a
licensed Nexus 9000v image (unavailable). Its SSH path is a documented
read-only fallback (test_credentials / reachable / get_running_config /
hostname / get_ports). This validates that fallback against real **IOSv
15.8(3)M2** (qemu/KVM).

Result on first run: test_credentials / reachable / get_running_config /
hostname all PASS against real IOS output (no parser bugs). `get_ports` uses
`show interfaces status`, which is SWITCH-only — on an IOSv ROUTER it returns
empty; that parser still needs a switch image (IOSvL2 / cat9kv) to validate and
is honestly recorded as unvalidated. NX-API remains image-blocked.

Bring-up (IOSv boots fast and reliably; needs e1000 NICs — it does NOT recognise
virtio-net):
    qemu-system-x86_64 -enable-kvm -cpu host -m 1024 -smp 1 \
      -drive file=virtioa.qcow2,if=virtio,index=0,format=qcow2 \
      -netdev user,id=net0,hostfwd=tcp:127.0.0.1:8022-:22 -device e1000,netdev=net0 \
      -serial telnet:127.0.0.1:5025,server,nowait -display none -vga none
  On the serial console answer 'no' to the setup dialog, then:
    enable / configure terminal
    hostname nb-iosv / ip domain-name lab.local
    username admin privilege 15 secret nbsandbox
    crypto key generate rsa modulus 1024 / ip ssh version 2
    interface GigabitEthernet0/0 / ip address dhcp / no shutdown
    line vty 0 4 / login local / transport input ssh
    end / write memory
  Host then reaches SSH at 127.0.0.1:8022 (forwarded to Gi0/0 = 10.0.2.15:22).

Usage:
    python sandbox/validate_cisco_ssh.py --host 127.0.0.1 --port 8022 \
        --username admin --password nbsandbox
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound.drivers.cisco import CiscoDriver  # noqa: E402
from northbound.schemas.driver import ConnectionParams, Credentials  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    conn = ConnectionParams(
        host=args.host, port=args.port, prefer_native_api=False, timeout_seconds=25.0
    )
    d = CiscoDriver(conn, Credentials(username=args.username, password=args.password))
    fails = 0
    try:
        tr = await d.test_credentials()
        print(f"[test_credentials] ok={tr.ok} ver={tr.platform_version!r}")
        fails += 0 if tr.ok else 1
        r = await d.reachable()
        print(f"[reachable]        {r}")
        fails += 0 if r else 1
        cfg = await d.get_running_config()
        print(f"[running_config]   {len(cfg)} bytes")
        fails += 0 if cfg else 1
        host = await d._get_hostname()
        print(f"[hostname]         {host!r}")
        fails += 0 if host else 1
        ports = await d.get_ports()
        print(
            f"[get_ports]        {len(ports)} (switch-only 'show interfaces status'; "
            f"empty on an IOSv router — needs a switch image to validate)"
        )
    finally:
        await d.aclose()

    print(f"\nCisco SSH read path live validation: {'PASS' if fails == 0 else f'FAIL ({fails})'}")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Live CiscoDriver SSH read-path validator (IOSv)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8022)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="nbsandbox")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
