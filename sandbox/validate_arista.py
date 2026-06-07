#!/usr/bin/env python3
"""Live validation of Northbound's real AristaDriver against vEOS (eAPI).

This is FULL driver validation — read paths AND the commit-confirm write path
(`configure session` + `commit timer`, confirm, and revert) — against a real
Arista EOS instance (vEOS-lab in qemu/KVM). It found THREE real production bugs
that mock-only unit tests had hidden (all now fixed):

  1. Privileged reads (e.g. `show running-config`) were sent WITHOUT entering
     enable mode → eAPI code 1002 "invalid command". Fix: _run_cmds now prepends
     `enable` to every batch and strips its result.
  2. eAPI JSON-RPC error codes {1000,1001,1002} were mapped to AuthError, but
     those are COMMAND-execution errors, not auth (auth fails at HTTP 401). A
     privileged-command failure thus mis-reported as bad credentials. Fix:
     _AUTH_ERROR_CODES emptied.
  3. confirm/revert re-entered the session as two commands
     (`configure session NAME` then `commit`), which FAILS on a session in
     'pendingCommitTimer' state. Fix: single-line `configure session NAME commit`
     / `configure session NAME abort`.

Bring-up (vEOS-lab in qemu/KVM — boots without a license keygen):
  1. Obtain a vEOS GNS3 package (Aboot `cdrom.iso` + `hda.qcow2`).
  2. Boot — note vEOS maps the FIRST NIC to Management1, so add extra NICs for
     Ethernet1+:
        qemu-system-x86_64 -enable-kvm -cpu host -m 2560 -smp 2 \
          -drive file=hda.qcow2,if=ide,index=0,format=qcow2 \
          -drive file=cdrom.iso,if=ide,index=2,media=cdrom -boot order=cd \
          -netdev user,id=net0,hostfwd=tcp:127.0.0.1:8443-:443 -device e1000,netdev=net0 \
          -netdev user,id=net1 -device e1000,netdev=net1 \
          -netdev user,id=net2 -device e1000,netdev=net2 \
          -serial telnet:127.0.0.1:5023,server,nowait -display none -vga none
  3. On the serial console (telnet 127.0.0.1 5023): log in `admin`, run
     `zerotouch disable` (reloads), then after reboot configure:
        enable / configure
        username admin privilege 15 role network-admin secret nbsandbox
        interface Management1 / ip address dhcp        (qemu user-net → 10.0.2.15)
        management api http-commands / no shutdown / protocol https
        end / write memory
     The host then reaches eAPI at https://127.0.0.1:8443 (forwarded to Mgmt1:443).

Usage:
  python sandbox/validate_arista.py --host 127.0.0.1 --port 8443 \
      --username admin --password nbsandbox --port-name Ethernet1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound.drivers.arista import AristaDriver  # noqa: E402
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    conn = ConnectionParams(host=args.host, port=args.port, timeout_seconds=20.0)
    creds = Credentials(username=args.username, password=args.password)
    port = args.port_name
    d = AristaDriver(conn, creds)
    fails = 0
    try:
        tr = await d.test_credentials()
        print(f"[test_credentials] ok={tr.ok} ver={tr.platform_version} {tr.latency_ms:.0f}ms")
        fails += 0 if tr.ok else 1
        print(f"[reachable]        {await d.reachable()}")
        cfg = await d.get_running_config()
        print(f"[running_config]   {len(cfg)} bytes")
        fails += 0 if cfg else 1
        ports = await d.get_ports()
        print(f"[get_ports]        {len(ports)} ports: {[p.name for p in ports][:6]}")
        fails += 0 if ports else 1

        # WRITE PATH 1: apply + CONFIRM
        diff = await d.render_change(
            port, PortChange(description="nb-live-confirm", untagged_vlan=20)
        )
        res = await d.apply_change(diff, confirm_seconds=120)
        print(f"[apply_change]     success={res.success} token={res.confirm_token} err={res.error}")
        fails += 0 if res.success else 1
        if res.success and res.confirm_token:
            await d.confirm(res.confirm_token)
            e = next((p for p in await d.get_ports() if p.name == port), None)
            ok = e is not None and e.untagged_vlan == 20 and e.description == "nb-live-confirm"
            print(
                f"[confirm+verify]   {port} vlan={e.untagged_vlan} desc={e.description!r} -> {'OK' if ok else 'MISMATCH'}"
            )
            fails += 0 if ok else 1

        # WRITE PATH 2: apply + REVERT (must not leak)
        diff2 = await d.render_change(
            port, PortChange(description="nb-should-not-stick", untagged_vlan=99)
        )
        res2 = await d.apply_change(diff2, confirm_seconds=120)
        print(f"[apply_change#2]   success={res2.success} token={res2.confirm_token}")
        if res2.success and res2.confirm_token:
            await d.revert(res2.confirm_token)
            e2 = next((p for p in await d.get_ports() if p.name == port), None)
            reverted = (
                e2 is not None and e2.untagged_vlan == 20 and e2.description == "nb-live-confirm"
            )
            print(
                f"[revert+verify]    {port} vlan={e2.untagged_vlan} desc={e2.description!r} -> {'OK (unchanged)' if reverted else 'LEAKED'}"
            )
            fails += 0 if reverted else 1
    finally:
        await d.aclose()

    print(f"\nArista driver live validation: {'PASS' if fails == 0 else f'FAIL ({fails})'}")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Live AristaDriver validator (vEOS eAPI)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="nbsandbox")
    ap.add_argument("--port-name", default="Ethernet1")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
