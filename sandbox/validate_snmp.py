#!/usr/bin/env python3
"""Live validation of the SNMP transport against a real snmpd (net-snmp).

The SNMP transport is not currently wired into any driver read path (drivers
read via eAPI / NX-API / NETCONF / SSH), but the wrapper ships and must be
correct for when it is. This drives the real ``SnmpClient`` against an actual
net-snmp daemon — auth-free, no licensed image.

Running this against a real snmpd found a real bug (now fixed): puresnmp's
``walk`` is an async GENERATOR, but ``SnmpClient.walk`` ``await``-ed it as if it
returned a list → ``TypeError`` ("an asyncio.Future, a coroutine or an awaitable
is required"). The unit-test fake had mirrored the wrong (list-returning) shape,
so green tests hid it.

Bring-up (open, no auth, no image licence):
    docker run -d --name nb-snmpd --network host polinux/snmpd   # community 'public'

Usage:
    python sandbox/validate_snmp.py --host 127.0.0.1 --community public
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound._lib.transport.snmp_client import SnmpClient, SnmpV2cParams  # noqa: E402

_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
_SYS_NAME = "1.3.6.1.2.1.1.5.0"
_SYSTEM = "1.3.6.1.2.1.1"


async def _run(args: argparse.Namespace) -> int:
    c = SnmpClient(
        SnmpV2cParams(host=args.host, community=args.community, port=args.port, timeout_seconds=5.0)
    )
    failures = 0

    try:
        v = await c.get(_SYS_DESCR)
        ok = bool(v)
        print(f"[get  sysDescr.0] {'OK ' if ok else 'EMPTY'} {str(v)[:60]}")
        failures += 0 if ok else 1
    except Exception as exc:
        print(f"[get  sysDescr.0] FAIL {type(exc).__name__}: {str(exc)[:80]}")
        failures += 1

    try:
        rows = await c.walk(_SYSTEM)
        ok = len(rows) > 0
        print(f"[walk system    ] {'OK ' if ok else 'EMPTY'} {len(rows)} rows")
        failures += 0 if ok else 1
    except Exception as exc:
        print(f"[walk system    ] FAIL {type(exc).__name__}: {str(exc)[:80]}")
        failures += 1

    try:
        b = await c.bulk_get([_SYS_DESCR, _SYS_NAME])
        ok = len(b) == 2
        print(f"[bulk_get x2    ] {'OK ' if ok else 'BAD'} {len(b)} values")
        failures += 0 if ok else 1
    except Exception as exc:
        print(f"[bulk_get x2    ] FAIL {type(exc).__name__}: {str(exc)[:80]}")
        failures += 1

    print()
    if failures:
        print(f"SNMP transport live validation: {failures} op(s) failed.")
        return 1
    print("SNMP transport live validation: PASS — real snmpd output received.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Live SNMP transport validator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=161)
    ap.add_argument("--community", default="public")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
