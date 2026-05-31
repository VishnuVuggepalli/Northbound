#!/usr/bin/env python3
"""Live validation of the CiscoDriver NX-API write path against NX-OS.

This validates the Cisco driver's PRIMARY path — NX-API (JSON-RPC `/ins`) — incl.
the commit-confirm write flow (checkpoint + config, confirm drops the checkpoint,
revert rolls back to it): the R4-fixed path. Validated against **Titanium
NX-OSv 7.3(0)D1(1)** in qemu/KVM.

It found THREE real production bugs (all fixed; mock unit tests had returned
canned data regardless of the real NX-API contract):

 1. Wrong Content-Type — httpx default `application/json` is rejected by NX-OS
    (HTTP 400 "Invalid request"); NX-API needs `application/json-rpc`.
 2. Wrong multi-command form — a `` ; ``-joined single `cli` string is rejected
    (code -32602 "invalid special characters"); NX-API needs a JSON-RPC command
    ARRAY (one object per command).
 3. Missing `switchport` — on NX-OS a routed-by-default port rejects
    `switchport mode access` ("% Invalid command") until made L2 with a bare
    `switchport`.

Bring-up (Titanium NX-OS — GNS3 `titanium-final.7.3.0.D1.1.tgz`, hda.qcow2):
    qemu-system-x86_64 -enable-kvm -cpu host -m 4096 -smp 2 \
      -drive file=hda.qcow2,if=ide,index=0,format=qcow2 \
      -netdev user,id=net0,hostfwd=tcp:127.0.0.1:8080-:80,hostfwd=tcp:127.0.0.1:8443-:443 \
      -device e1000,netdev=net0 \
      -serial telnet:127.0.0.1:5027,server,nowait -display none -vga none
  Console login admin/admin, then:
    configure terminal
    feature nxapi
    interface mgmt0 / ip address 10.0.2.15/24 / no shutdown
    vrf context management / ip route 0.0.0.0/0 10.0.2.2
    nxapi http port 80 / nxapi https port 443
    end / copy running-config startup-config

Transport note: Titanium's emulated NX-API HTTPS does not complete the TLS
handshake (emulator limitation), so this validator points at HTTP (8080) via an
injected HttpxClient. The JSON-RPC contract + checkpoint/rollback logic — what we
validate — are identical over HTTP/HTTPS; production uses HTTPS.

Usage:
    python sandbox/validate_cisco_nxapi.py --base-url http://127.0.0.1:8080 \
        --username admin --password admin --port-name Ethernet2/1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams  # noqa: E402
from northbound.drivers.cisco import CiscoDriver  # noqa: E402
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    http = HttpxClient(HttpxParams(base_url=args.base_url, verify_tls=False))
    d = CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=True, timeout_seconds=30.0),
        Credentials(username=args.username, password=args.password),
        http=http,
    )
    port = args.port_name
    fails = 0
    try:
        tr = await d.test_credentials()
        print(f"[test_credentials] ok={tr.ok} ver={tr.platform_version!r}")
        fails += 0 if tr.ok else 1
        print(f"[reachable]        {await d.reachable()}")
        cfg = await d.get_running_config()
        print(f"[running_config]   {len(cfg)} bytes")
        fails += 0 if cfg else 1
        ports = await d.get_ports()
        print(f"[get_ports]        {len(ports)} ports (NX-API show interface)")
        fails += 0 if ports else 1

        # WRITE PATH: render -> apply (checkpoint + config array) -> confirm
        diff = await d.render_change(port, PortChange(untagged_vlan=30))
        res = await d.apply_change(diff, confirm_seconds=120)
        print(f"[apply_change]     success={res.success} token={res.confirm_token} err={res.error}")
        fails += 0 if res.success else 1
        if res.success and res.confirm_token:
            await d.confirm(res.confirm_token)
            e = next((p for p in await d.get_ports() if p.name == port), None)
            ok = e is not None and e.untagged_vlan == 30
            print(
                f"[confirm+verify]   {port} vlan={e.untagged_vlan if e else '?'} -> {'OK' if ok else 'MISMATCH'}"
            )
            fails += 0 if ok else 1

        # WRITE PATH 2: apply -> revert (rollback to checkpoint) must undo
        diff2 = await d.render_change(port, PortChange(untagged_vlan=77))
        res2 = await d.apply_change(diff2, confirm_seconds=120)
        print(f"[apply_change#2]   success={res2.success} token={res2.confirm_token}")
        if res2.success and res2.confirm_token:
            await d.revert(res2.confirm_token)
            e2 = next((p for p in await d.get_ports() if p.name == port), None)
            reverted = e2 is not None and e2.untagged_vlan == 30
            print(
                f"[revert+verify]    {port} vlan={e2.untagged_vlan if e2 else '?'} -> {'OK (rolled back)' if reverted else 'LEAKED'}"
            )
            fails += 0 if reverted else 1
    finally:
        await d.aclose()

    print(f"\nCisco NX-API path live validation: {'PASS' if fails == 0 else f'FAIL ({fails})'}")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Live CiscoDriver NX-API validator (NX-OS)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--port-name", default="Ethernet2/1")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
