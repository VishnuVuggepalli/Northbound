#!/usr/bin/env python3
"""Live validation of the NETCONF transport against a real RFC-6241 server.

Unlike the vendor data-plane (Pica8 PicOS, which needs a licensed image), the
NETCONF *transport* and the *confirmed-commit* flow the Pica8 driver depends on
CAN be exercised against an open NETCONF server — Netopeer2/sysrepo — which
implements :candidate and :confirmed-commit.

This drives Northbound's real ``NetconfClient`` (the production wrapper) exactly
as the Pica8 driver does: get-config → edit-config(candidate) → commit confirmed
→ confirming commit → verify. It ALSO reproduces the pre-fix positional
``edit_config`` call to prove it is genuinely rejected.

Two real bugs were found by running this against Netopeer2 (both now fixed):
  * edit_config was called POSITIONALLY — real ncclient is
    edit_config(config, format, target, ...), so our ``target`` mis-mapped into
    ncclient's ``config`` slot.
  * commit passed ``timeout`` as an int — ncclient writes <confirm-timeout> via
    lxml, which requires str text (int → TypeError).

Bring-up (open server, no auth, no licensed image):
    docker run -d --name nb-netconf --network host sysrepo/sysrepo-netopeer2:latest
    # (host networking avoids the docker port-proxy SSH-banner mangling; the
    #  bridge IP is not host-routable in some sandboxes)
    # then disable NACM so the demo user may write a leaf:
    docker exec nb-netconf bash -lc 'printf "%s" \
      "<nacm xmlns=\"urn:ietf:params:xml:ns:yang:ietf-netconf-acm\"><enable-nacm>false</enable-nacm></nacm>" \
      > /tmp/nacm.xml; sysrepocfg --edit=/tmp/nacm.xml -d running -m ietf-netconf-acm'

Usage:
    python sandbox/validate_netconf.py --host 127.0.0.1 --port 830 \
        --username netconf --password netconf
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound._lib.transport.netconf_client import (  # noqa: E402
    NetconfClient,
    NetconfParams,
)

# Safe, writable, reversible leaf in a module Netopeer2 loads by default:
# bump the SSH keepalive idle-time. Does not drop active sessions.
_MARKER = "<idle-time>2</idle-time>"
_EDIT = (
    '<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">'
    '<netconf-server xmlns="urn:ietf:params:xml:ns:yang:ietf-netconf-server">'
    "<listen><endpoint><name>default-ssh</name>"
    "<ssh><tcp-server-parameters><keepalives>"
    "<idle-time>2</idle-time>"
    "</keepalives></tcp-server-parameters></ssh>"
    "</endpoint></listen></netconf-server></config>"
)


async def _run(args: argparse.Namespace) -> int:
    params = NetconfParams(
        host=args.host, port=args.port, username=args.username, password=args.password
    )

    # 1) Prove the OLD positional edit_config pattern fails (regression guard).
    from ncclient import manager  # type: ignore[import-untyped]

    raw = manager.connect(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        hostkey_verify=False,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    old_failed = False
    try:
        raw.edit_config("candidate", _EDIT, None, None, None)  # pre-fix shape
        print("[old-pattern] UNEXPECTED success — fix would be hidden")
    except Exception as exc:
        old_failed = True
        print(f"[old-pattern] correctly broken: {type(exc).__name__}: {str(exc)[:80]}")
    raw.close_session()

    # 2) Drive the REAL production wrapper end to end.
    c = NetconfClient(params)
    try:
        running = await c.get_config(source="running")
        print(f"[get-config]    OK  ({len(running)} bytes)")

        await c.edit_config(target="candidate", config=_EDIT)
        print("[edit-config]   OK  (target='candidate' accepted)")

        await c.commit(confirmed=True, timeout=120)
        print("[commit-confirm] OK  (confirmed-commit, timeout=120)")
        await c.commit()
        print("[commit-confirm] OK  (confirming commit → permanent)")

        present = _MARKER in await c.get_config(source="running")
        print(
            f"[verify]        {'OK ' if present else 'FAIL'} (change in running-config: {present})"
        )
    finally:
        await c.close()

    ok = old_failed and present
    print()
    print(
        f"NETCONF transport + confirmed-commit live validation: "
        f"{'PASS' if ok else 'FAIL'} (old_broken={old_failed}, wrapper_fix_works={present})"
    )
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Live NETCONF transport validator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=830)
    ap.add_argument("--username", default="netconf")
    ap.add_argument("--password", default="netconf")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
