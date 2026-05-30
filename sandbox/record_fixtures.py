#!/usr/bin/env python3
"""NB_RECORD capture harness — record REAL device responses into fixtures.

This is the antidote to the circular-fixture problem flagged in the
validation gate: the Arista/Cisco/Pica8 contract fixtures were hand-authored
from vendor docs by the same agent that wrote the parsers, so a shared wrong
guess passes green. Capturing from a *live* device and diffing against the
authored fixtures turns every mismatch into a real parser bug.

What it does:
  1. Instantiates the REAL driver (no mocked transport) against a live device.
  2. Calls the read surface: test_credentials / get_ports / get_running_config
     / get_neighbors, plus a dry render_change.
  3. Dumps the RAW transport responses (eAPI JSON / NX-API JSON / NETCONF XML)
     to tests/fixtures/<platform>/<name>.captured.json with a provenance
     header (device model, NOS version, capture timestamp, host).

It captures raw wire responses by wrapping the driver's transport so the
exact bytes the parser sees are what we persist — not the post-parse objects.

Usage:
  python sandbox/record_fixtures.py --platform arista --host 172.20.20.X \\
      --username admin --password nbsandbox --scheme http

  python sandbox/record_fixtures.py --platform cisco  --host <ip> ...
  python sandbox/record_fixtures.py --platform pica8  --host <ip> --username admin --password ...

Then diff:
  python sandbox/record_fixtures.py --diff --platform arista
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path
from typing import Any

# Make the package importable when run from the repo root.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams  # noqa: E402
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange  # noqa: E402

_FIXTURE_DIR = _REPO / "tests" / "fixtures"


def _provenance(host: str, platform: str, model: str | None, version: str | None) -> dict[str, Any]:
    return {
        "_provenance": {
            "captured_from": "live-device",
            "platform": platform,
            "host": host,
            "device_model": model,
            "nos_version": version,
            "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "tool": "sandbox/record_fixtures.py",
        }
    }


# ---------------------------------------------------------------------------
# Arista / Cisco — wrap HttpxClient.post to tee every eAPI/NX-API exchange.
# ---------------------------------------------------------------------------


class _RecordingHttpxClient(HttpxClient):
    """HttpxClient that records every (request-body, response-json) pair."""

    def __init__(self, params: HttpxParams) -> None:
        super().__init__(params)
        self.exchanges: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: object | None = None,
    ) -> Any:
        resp = await super().post(url, headers=headers, json=json)
        try:
            body = resp.json()
        except Exception:
            body = {"_raw_text": resp.text}
        self.exchanges.append(
            {"url": url, "request": json, "status": resp.status_code, "response": body}
        )
        return resp


async def _record_arista(args: argparse.Namespace) -> int:
    from northbound.drivers.arista import AristaDriver

    scheme = args.scheme
    port = args.port or (443 if scheme == "https" else 80)
    rec = _RecordingHttpxClient(
        HttpxParams(base_url=f"{scheme}://{args.host}:{port}", verify_tls=False)
    )
    conn = ConnectionParams(host=args.host, port=port)
    creds = Credentials(username=args.username, password=args.password)
    driver = AristaDriver(conn, creds, http=rec)
    return await _exercise(driver, rec, "arista", args)


async def _record_cisco(args: argparse.Namespace) -> int:
    from northbound.drivers.cisco import CiscoDriver

    scheme = args.scheme
    port = args.port or (443 if scheme == "https" else 80)
    rec = _RecordingHttpxClient(
        HttpxParams(base_url=f"{scheme}://{args.host}:{port}", verify_tls=False)
    )
    conn = ConnectionParams(host=args.host, port=port)
    creds = Credentials(username=args.username, password=args.password)
    driver = CiscoDriver(conn, creds, http=rec)
    return await _exercise(driver, rec, "cisco", args)


async def _record_pica8(args: argparse.Namespace) -> int:
    """Capture raw NETCONF XML by driving the real NetconfClient."""
    from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams
    from northbound.drivers.pica8 import Pica8Driver

    nc = NetconfClient(
        NetconfParams(
            host=args.host,
            username=args.username or "admin",
            password=args.password,
            port=args.port or 830,
        )
    )
    conn = ConnectionParams(host=args.host, port=args.port or 830)
    creds = Credentials(username=args.username, password=args.password)
    driver = Pica8Driver(conn, creds, netconf=nc)  # type: ignore[call-arg]

    out_dir = _FIXTURE_DIR / "pica8"
    out_dir.mkdir(parents=True, exist_ok=True)
    captured: dict[str, Any] = {}
    # get_config returns raw XML — persist it verbatim.
    running_xml = await nc.get_config("running")
    captured["get_config_running.xml"] = running_xml
    try:
        ports = await driver.get_ports()
        captured["_parsed_ports_count"] = len(ports)
    except Exception as exc:
        captured["_parsed_ports_error"] = repr(exc)

    prov = _provenance(args.host, "pica8", model=None, version=None)
    (out_dir / "get_config_running.captured.xml").write_text(running_xml)
    (out_dir / "capture-manifest.captured.json").write_text(
        json.dumps({**prov, "captured": list(captured.keys())}, indent=2)
    )
    print(f"[pica8] wrote {out_dir}/get_config_running.captured.xml")
    await nc.close()
    return 0


async def _exercise(
    driver: Any, rec: _RecordingHttpxClient, platform: str, args: argparse.Namespace
) -> int:
    """Run the read surface, then dump raw exchanges per command."""
    out_dir = _FIXTURE_DIR / platform
    out_dir.mkdir(parents=True, exist_ok=True)

    model: str | None = None
    version: str | None = None

    print(f"[{platform}] test_credentials ...")
    tr = await driver.test_credentials()
    print(f"    ok={tr.ok} version={tr.platform_version} latency={tr.latency_ms:.0f}ms")
    version = tr.platform_version

    for label, coro in (
        ("get_running_config", driver.get_running_config()),
        ("get_ports", driver.get_ports()),
        ("get_neighbors", driver.get_neighbors()),
    ):
        try:
            res = await coro
            n = len(res) if isinstance(res, (list, str)) else "?"
            print(f"[{platform}] {label}: {n} items")
        except Exception as exc:
            print(f"[{platform}] {label}: ERROR {exc!r}")

    # dry render (no apply) to capture the command shape the device would get.
    try:
        diff = await driver.render_change(
            "Ethernet1", PortChange(description="nb-capture", untagged_vlan=10)
        )
        print(f"[{platform}] render_change commands: {diff.commands}")
    except Exception as exc:
        print(f"[{platform}] render_change: {exc!r}")

    # Persist each raw exchange keyed by the first command in the request.
    prov = _provenance(args.host, platform, model, version)
    by_cmd: dict[str, Any] = {}
    for ex in rec.exchanges:
        req = ex.get("request") or {}
        params = req.get("params", {}) if isinstance(req, dict) else {}
        cmds = params.get("cmds") or params.get("cmd")
        key = (cmds[0] if isinstance(cmds, list) and cmds else str(cmds)) or "unknown"
        safe = key.replace(" ", "_").replace("/", "_")[:60]
        by_cmd.setdefault(safe, []).append(ex["response"])

    for safe, responses in by_cmd.items():
        payload = {**prov, "command": safe, "raw_responses": responses}
        path = out_dir / f"{safe}.captured.json"
        path.write_text(json.dumps(payload, indent=2))
        print(f"    wrote {path}")

    print(f"[{platform}] captured {len(rec.exchanges)} raw exchanges into {out_dir}")
    return 0


# ---------------------------------------------------------------------------
# Diff: compare captured raw responses against the authored contract fixtures.
# ---------------------------------------------------------------------------


def _diff(platform: str) -> int:
    out_dir = _FIXTURE_DIR / platform
    captured = sorted(out_dir.glob("*.captured.*"))
    if not captured:
        print(f"No captured fixtures for '{platform}' yet. Run a capture first.")
        return 1
    authored = sorted(p for p in out_dir.glob("*.json") if ".captured." not in p.name)
    print(f"== {platform}: {len(captured)} captured, {len(authored)} authored ==")
    print("Captured (real device):")
    for c in captured:
        print(f"  {c.name}")
    print("Authored (hand-written, used by contract suite):")
    for a in authored:
        print(f"  {a.name}")
    print(
        "\nManual diff step: open each captured raw_responses[] blob and compare the\n"
        "field names/shape against the matching authored fixture. Any divergence in\n"
        "keys the parser reads (e.g. interfaceStatus values, lldpNeighbors nesting,\n"
        "switchportInfo field names) is a REAL parser bug to fix in the driver."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Northbound live-device fixture recorder")
    ap.add_argument("--platform", choices=["arista", "cisco", "pica8"], required=False)
    ap.add_argument("--host")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--scheme", choices=["http", "https"], default="http")
    ap.add_argument("--diff", action="store_true", help="diff captured vs authored fixtures")
    args = ap.parse_args()

    if args.diff:
        if not args.platform:
            print("--diff requires --platform")
            return 2
        return _diff(args.platform)

    if not args.platform or not args.host:
        ap.error("capture mode requires --platform and --host")

    runner = {
        "arista": _record_arista,
        "cisco": _record_cisco,
        "pica8": _record_pica8,
    }[args.platform]
    return asyncio.run(runner(args))


if __name__ == "__main__":
    raise SystemExit(main())
