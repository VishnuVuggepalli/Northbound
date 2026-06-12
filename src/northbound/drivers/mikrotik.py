"""MikroTik RouterOS driver — REST API (v7.1+).

RouterOS exposes a JSON REST wrapper over the console at ``/rest`` (HTTP Basic
auth). Every value in a reply is a STRING — even numbers/booleans — so all
parsing here coerces from strings. Refs:
https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API

Reads (ports, VLANs, L3, neighbors, system) come from menu ``print`` GETs.
Writes use ``PATCH /rest/<menu>/<.id>`` and are applied IMMEDIATELY — RouterOS
has no native commit-confirm, so ``apply_change`` returns no confirm token
(mirrors the Pica8 plain-commit path) and ``confirm``/``revert`` are unsupported.

The writable subset is the safe, well-defined one: interface ``comment``
(description), admin ``disabled`` (enable/disable), and the access VLAN via a
bridge port's ``pvid``. Trunk/tagged-VLAN edits touch the bridge VLAN table
(tagged/untagged member lists) and are intentionally NOT auto-applied here.

NOTE: implemented against the published REST contract; field names/VLAN mapping
should be confirmed against a live RouterOS box before production use.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

import httpx

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams
from northbound.drivers.base import (
    AuthError,
    Driver,
    DriverError,
    NotSupported,
    ReachabilityError,
)
from northbound.drivers.registry import register
from northbound.schemas.driver import (
    ApplyResult,
    AuthMethod,
    ConfigDiff,
    ConnectionParams,
    Credentials,
    DeviceFacts,
    DiscoveryResult,
    DriverCapabilities,
    L3Interface,
    MacEntry,
    MgmtService,
    Neighbor,
    PortChange,
    PortState,
    ProtocolDetail,
    ProtocolStatus,
    ProtocolTable,
    SystemInfo,
    TestResult,
    VlanInfo,
)

_OPS_KEY = "rest_ops"  # diff.metadata: list of {"method","path","body"} to apply


@register
class MikrotikDriver(Driver):
    """MikroTik RouterOS via the REST API (httpx + HTTP Basic)."""

    platform_id = "mikrotik"
    display_name = "MikroTik RouterOS"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=False,  # RouterOS REST commits immediately
        native_api_available=True,
        supports_snmp_read=True,
        supports_lldp=True,
        max_concurrency=5,
        auth_methods=[AuthMethod.PASSWORD],
        web_ui_url_template="https://{mgmt_ip}/",
    )

    def __init__(
        self,
        conn: ConnectionParams,
        creds: Credentials,
        *,
        http: Any | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._http = http  # injected transport (tests); built lazily otherwise
        self._auth = HttpxClient.basic_auth_header(creds.username or "", creds.password or "")

    # ---------- transport ----------

    def _client(self) -> Any:
        if self._http is None:
            scheme = "https" if (self._conn.port or 443) != 80 else "http"
            base = f"{scheme}://{self._conn.host}:{self._conn.port or (443 if scheme == 'https' else 80)}"
            # Lab boxes ship self-signed certs; REST over https won't verify.
            self._http = HttpxClient(
                HttpxParams(
                    base_url=base,
                    timeout_seconds=self._conn.timeout_seconds,
                    max_concurrency=self.capabilities.max_concurrency,
                    verify_tls=False,
                )
            )
        return self._http

    async def aclose(self) -> None:
        http, self._http = self._http, None
        if http is not None:
            with contextlib.suppress(Exception):  # close must never raise
                await http.aclose()

    def _check(self, resp: httpx.Response) -> Any:
        """Raise our taxonomy on error status; else return parsed JSON."""
        if resp.status_code in (401, 403):
            raise AuthError(f"mikrotik: authentication failed ({resp.status_code})")
        if resp.status_code >= 500:
            raise DriverError(f"mikrotik: server error {resp.status_code}")
        if resp.status_code >= 400:
            raise DriverError(f"mikrotik: request failed {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as exc:
            raise DriverError(f"mikrotik: invalid JSON response: {exc}") from exc

    async def _get(self, menu: str) -> list[dict[str, Any]]:
        """GET ``/rest/<menu>`` → list of string-valued dicts."""
        try:
            resp = await self._client().get(f"/rest/{menu}", headers=self._auth)
        except httpx.HTTPError as exc:
            raise ReachabilityError(f"mikrotik: cannot reach {menu}: {exc}") from exc
        data = self._check(resp)
        return data if isinstance(data, list) else []

    async def _patch(self, menu: str, item_id: str, body: dict[str, str]) -> None:
        try:
            resp = await self._client().request(
                "PATCH", f"/rest/{menu}/{item_id}", headers=self._auth, json=body
            )
        except httpx.HTTPError as exc:
            raise ReachabilityError(f"mikrotik: cannot patch {menu}/{item_id}: {exc}") from exc
        self._check(resp)

    # ---------- onboarding / read ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            rows = await self._get("system/resource")
        except (AuthError, ReachabilityError, DriverError) as exc:
            return TestResult(
                ok=False, latency_ms=_ms(start), platform_version=None, error=str(exc)
            )
        ver = ""
        if rows:
            ver = " ".join(
                str(rows[0].get(k, "")) for k in ("board-name", "version") if rows[0].get(k)
            ).strip()
        return TestResult(ok=True, latency_ms=_ms(start), platform_version=ver or None)

    async def reachable(self) -> bool:
        try:
            await self._get("system/resource")
            return True
        except (AuthError, ReachabilityError, DriverError):
            return False

    async def discover(self) -> DiscoveryResult:
        identity = await self._get("system/identity")
        hostname = str(identity[0].get("name", "")) if identity else ""
        ports = await self.get_ports()
        running = await self.get_running_config()
        return DiscoveryResult(
            hostname=hostname,
            ports=tuple(ports),
            running_config=running,
            services={"lldp": self.capabilities.supports_lldp},
        )

    async def get_running_config(self) -> str:
        """POST /rest/export → config text. Best-effort across reply shapes."""
        try:
            resp = await self._client().request("POST", "/rest/export", headers=self._auth, json={})
            data = self._check(resp)
        except (AuthError, ReachabilityError, DriverError, httpx.HTTPError):
            return ""
        if isinstance(data, list):
            # rows like [{"ret": "<line>"}] or [{"...": "..."}] — join string values
            lines = [str(v) for row in data if isinstance(row, dict) for v in row.values()]
            return "\n".join(lines)
        if isinstance(data, dict):
            return "\n".join(str(v) for v in data.values())
        return str(data)

    async def backup_config(self) -> str:
        cfg = await self.get_running_config()
        return cfg if cfg else "# mikrotik: empty export\n"

    async def get_ports(self) -> list[PortState]:
        interfaces = await self._get("interface")
        ethernet = await self._get("interface/ethernet")
        bridge_ports = await self._get("interface/bridge/port")
        bridge_vlans = await self._get("interface/bridge/vlan")
        return _merge_ports(interfaces, ethernet, bridge_ports, bridge_vlans)

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        try:
            rows = await self._get("ip/neighbor")
        except DriverError:
            return []
        out = [_neighbor_from(r) for r in rows if r.get("interface")]
        if port is not None:
            out = [n for n in out if n.system_description and f"[{port}]" in n.system_description]
        return out

    async def get_vlans(self) -> list[VlanInfo]:
        rows = await self._get("interface/bridge/vlan")
        seen: dict[int, int] = {}
        for r in rows:
            for vid in _parse_vlan_ids(str(r.get("vlan-ids", ""))):
                members = _csv(r.get("tagged")) + _csv(r.get("untagged"))
                seen[vid] = seen.get(vid, 0) + len([m for m in members if m])
        return [VlanInfo(vlan_id=v, port_count=c) for v, c in sorted(seen.items())]

    async def get_l3_interfaces(self) -> list[L3Interface]:
        addrs = await self._get("ip/address")
        interfaces = {str(i.get("name")): i for i in await self._get("interface")}
        out: list[L3Interface] = []
        for a in addrs:
            ifname = str(a.get("interface", ""))
            iface = interfaces.get(ifname, {})
            out.append(
                L3Interface(
                    name=ifname,
                    kind=_l3_kind(str(iface.get("type", ""))),
                    ipv4=str(a.get("address", "")),
                    mtu=_int(iface.get("mtu")),
                    enabled=not _bool(a.get("disabled")),
                )
            )
        return out

    async def get_system_info(self) -> SystemInfo:
        resource = await self._get("system/resource")
        services = await self._get("ip/service")
        res = resource[0] if resource else {}
        facts = DeviceFacts(
            model=str(res.get("board-name", "")),
            os_version=str(res.get("version", "")),
            uptime=str(res.get("uptime", "")),
        )
        svc = tuple(
            MgmtService(
                name=str(s.get("name", "")),
                enabled=not _bool(s.get("disabled")),
                port=_int(s.get("port")),
            )
            for s in services
            if s.get("name")
        )
        protocols = (ProtocolStatus(name="lldp", enabled=True),)

        # L2 forwarding (MAC) table from the bridge host table. mac_supported is
        # True once we successfully read it (even if empty) so the UI can tell
        # "no hosts learned" apart from "driver can't read it".
        mac_table: tuple[MacEntry, ...] = ()
        mac_supported = True
        try:
            hosts = await self._get("interface/bridge/host")
            mac_table = tuple(_mac_entry(h) for h in hosts if h.get("mac-address"))
        except DriverError:
            mac_supported = False

        return SystemInfo(
            protocols=protocols,
            services=svc,
            facts=facts,
            mac_table=mac_table,
            mac_supported=mac_supported,
        )

    async def get_protocol_detail(self, slug: str) -> ProtocolDetail:
        """Live operational tables for the System tab's Diagnostics slugs.

        Each maps to a RouterOS REST menu read. An unknown slug returns empty
        (base behaviour); a read failure is surfaced as ``error`` so the UI shows
        "couldn't read" rather than a misleading "no entries".
        """
        builders = {
            "Counters": ("interface", _counters_table),
            "ARP": ("ip/arp", _arp_table),
            "Routing": ("ip/route", _route_table),
        }
        spec = builders.get(slug)
        if spec is None:
            return ProtocolDetail(slug=slug)
        menu, build = spec
        try:
            rows = await self._get(menu)
        except DriverError as exc:
            return ProtocolDetail(slug=slug, error=str(exc))
        return ProtocolDetail(slug=slug, tables=(build(rows),))

    # ---------- write (immediate REST PATCH; no commit-confirm) ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        if change.tagged_vlans is not None or change.port_mode == "trunk":
            raise NotSupported(
                "mikrotik: trunk/tagged-VLAN edits modify the bridge VLAN table and "
                "are not auto-applied; configure trunk membership in Winbox/Webfig."
            )
        interfaces = await self._get("interface")
        iface = next((i for i in interfaces if str(i.get("name")) == port), None)
        if iface is None:
            raise DriverError(f"mikrotik: interface {port!r} not found")
        iface_id = str(iface.get(".id", ""))

        ops: list[dict[str, Any]] = []
        summary: list[str] = []
        if change.description is not None:
            ops.append(
                {
                    "method": "PATCH",
                    "path": f"interface/{iface_id}",
                    "body": {"comment": change.description},
                }
            )
            summary.append(f"comment={change.description!r}")
        if change.enabled is not None:
            ops.append(
                {
                    "method": "PATCH",
                    "path": f"interface/{iface_id}",
                    "body": {"disabled": "false" if change.enabled else "true"},
                }
            )
            summary.append(f"disabled={'false' if change.enabled else 'true'}")
        if change.untagged_vlan is not None:
            bridge_ports = await self._get("interface/bridge/port")
            bp = next((b for b in bridge_ports if str(b.get("interface")) == port), None)
            if bp is None:
                raise DriverError(
                    f"mikrotik: {port!r} is not a bridge port; cannot set access VLAN"
                )
            ops.append(
                {
                    "method": "PATCH",
                    "path": f"interface/bridge/port/{bp.get('.id')}",
                    "body": {"pvid": str(change.untagged_vlan)},
                }
            )
            summary.append(f"pvid={change.untagged_vlan}")
        if not ops:
            raise DriverError("mikrotik: no supported field set in change")

        return ConfigDiff(
            summary=f"Update {port}: {', '.join(summary)}",
            raw_before=f"/interface {port}\n  ! (previous state not captured)\n",
            raw_after="\n".join(f"PATCH /rest/{o['path']} {o['body']}" for o in ops) + "\n",
            commands=tuple(f"{o['method']} /rest/{o['path']} {o['body']}" for o in ops),
            # metadata is str→str; ops are JSON-encoded and decoded in apply_change.
            metadata={_OPS_KEY: json.dumps(ops)},
        )

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        raw = diff.metadata.get(_OPS_KEY)
        ops = json.loads(raw) if raw else []
        if not ops:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error="mikrotik: diff carries no REST operations",
            )
        try:
            for op in ops:
                menu, _, item_id = str(op["path"]).rpartition("/")
                await self._patch(menu, item_id, op["body"])
        except (AuthError, ReachabilityError, DriverError) as exc:
            return ApplyResult(
                success=False, confirm_token=None, confirm_deadline_at=None, error=str(exc)
            )
        # RouterOS has no commit-confirm: the change is already permanent.
        return ApplyResult(success=True, confirm_token=None, confirm_deadline_at=None, error=None)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def _ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _bool(v: object) -> bool:
    """RouterOS encodes booleans as the strings 'true'/'false'."""
    return str(v).strip().lower() in ("true", "yes")


def _int(v: object) -> int | None:
    s = str(v).strip()
    return int(s) if s.isdigit() else None


def _csv(v: object) -> list[str]:
    return [tok.strip() for tok in str(v or "").split(",") if tok.strip()]


def _speed_mbps(v: object) -> int | None:
    """'1Gbps'->1000, '100Mbps'->100, '10Gbps'->10000, '' -> None."""
    s = str(v or "").strip().lower().replace("bps", "")
    if not s:
        return None
    try:
        if s.endswith("g"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("m"):
            return int(float(s[:-1]))
        return int(float(s))
    except ValueError:
        return None


def _parse_vlan_ids(value: str) -> list[int]:
    """'10' -> [10]; '10-12' -> [10,11,12]; '10,20-21' -> [10,20,21]."""
    out: list[int] = []
    for tok in value.split(","):
        tok = tok.strip()
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            if lo.strip().isdigit() and hi.strip().isdigit():
                out.extend(range(int(lo), int(hi) + 1))
        elif tok.isdigit():
            out.append(int(tok))
    return out


def _l3_kind(iface_type: str) -> str:
    t = iface_type.lower()
    if t == "vlan":
        return "svi"
    if t in ("bonding", "bond"):
        return "aggregated"
    return "management"


def _mac_entry(row: dict[str, Any]) -> MacEntry:
    """One /interface/bridge/host row → MacEntry.

    RouterOS REST returns every value as a string — including booleans (``"true"``
    / ``"false"``) and numbers — so each field is coerced explicitly. ``vid`` is
    present only when the bridge runs vlan-filtering; absent → no VLAN context
    (``None``, not 0). A host owned by the bridge itself (``local``) is labelled
    Local; a non-dynamic entry is Static; otherwise Dynamic.
    """
    vid = row.get("vid")
    if str(row.get("local", "")).lower() == "true":
        kind = "Local"
    elif str(row.get("dynamic", "")).lower() == "false":
        kind = "Static"
    else:
        kind = "Dynamic"
    age = row.get("age")
    return MacEntry(
        vlan=int(vid) if vid not in (None, "") else None,
        mac=str(row.get("mac-address", "")),
        interface=str(row.get("on-interface", "")),
        type=kind,
        age=str(age) if age else None,
    )


def _human_bytes(v: object) -> str:
    """RouterOS REST returns counters as strings; render a byte count human-
    readably ("1.5 GB"). Non-numeric/absent → em dash."""
    try:
        n = float(int(str(v)))
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _counters_table(rows: list[dict[str, Any]]) -> ProtocolTable:
    """/interface rows → interface traffic counters. Only fields confirmed on the
    generic /interface menu are used (rx/tx byte+packet, tx-queue-drop)."""
    out = tuple(
        (
            str(r.get("name", "")),
            _human_bytes(r.get("rx-byte")),
            _human_bytes(r.get("tx-byte")),
            str(r.get("rx-packet", "") or ""),
            str(r.get("tx-packet", "") or ""),
            str(r.get("tx-queue-drop", "") or ""),
        )
        for r in rows
        if r.get("name")
    )
    return ProtocolTable(
        title="Interface counters",
        columns=("Interface", "RX", "TX", "RX pkts", "TX pkts", "TX drops"),
        rows=out,
    )


def _arp_status(row: dict[str, Any]) -> str:
    """Prefer the explicit ``status`` enum; fall back to the ``complete`` flag."""
    status = row.get("status")
    if status:
        return str(status)
    return "complete" if str(row.get("complete", "")).lower() == "true" else "incomplete"


def _arp_table(rows: list[dict[str, Any]]) -> ProtocolTable:
    """/ip/arp rows → ARP table (IP ↔ MAC ↔ port, resolution status)."""
    out = tuple(
        (
            str(r.get("address", "")),
            str(r.get("mac-address", "") or "—"),
            str(r.get("interface", "")),
            _arp_status(r),
        )
        for r in rows
        if r.get("address")
    )
    return ProtocolTable(
        title="ARP entries",
        columns=("IP address", "MAC", "Interface", "Status"),
        rows=out,
    )


def _route_table(rows: list[dict[str, Any]]) -> ProtocolTable:
    """/ip/route rows → IPv4 FIB. ``immediate-gw`` (v7) is the resolved next-hop
    after recursion; ``gateway`` is what was configured."""
    out = tuple(
        (
            str(r.get("dst-address", "")),
            str(r.get("gateway", "") or ""),
            str(r.get("immediate-gw", "") or ""),
            str(r.get("distance", "") or ""),
            "yes" if str(r.get("active", "")).lower() == "true" else "no",
        )
        for r in rows
        if r.get("dst-address")
    )
    return ProtocolTable(
        title="IPv4 routes",
        columns=("Destination", "Gateway", "Next-hop", "Distance", "Active"),
        rows=out,
    )


def _neighbor_from(row: dict[str, Any]) -> Neighbor:
    """RouterOS /ip/neighbor row → Neighbor; local port encoded as '[ifname] '."""
    local = str(row.get("interface", ""))
    sysname = row.get("identity") or row.get("system-description")
    return Neighbor(
        chassis_id=str(row.get("mac-address", "")),
        port_id=str(row.get("interface-name", "") or row.get("interface", "")),
        system_name=str(sysname) if sysname else None,
        system_description=f"[{local}] {row.get('platform', '')}".strip(),
    )


def _merge_ports(
    interfaces: list[dict[str, Any]],
    ethernet: list[dict[str, Any]],
    bridge_ports: list[dict[str, Any]],
    bridge_vlans: list[dict[str, Any]],
) -> list[PortState]:
    """Join /interface + /interface/ethernet + bridge port/vlan → PortState.

    untagged = bridge port ``pvid`` (access VLAN); tagged = VLAN ids whose bridge
    VLAN row lists the interface as a ``tagged`` member.
    """
    speed_by_name = {str(e.get("name")): e.get("speed") for e in ethernet}
    pvid_by_name = {str(b.get("interface")): _int(b.get("pvid")) for b in bridge_ports}

    tagged_by_name: dict[str, list[int]] = {}
    for row in bridge_vlans:
        vids = _parse_vlan_ids(str(row.get("vlan-ids", "")))
        for name in _csv(row.get("tagged")):
            tagged_by_name.setdefault(name, []).extend(vids)

    out: list[PortState] = []
    for i in interfaces:
        name = str(i.get("name", ""))
        if not name:
            continue
        out.append(
            PortState(
                name=name,
                admin_up=not _bool(i.get("disabled")),
                link_up=_bool(i.get("running")),
                speed_mbps=_speed_mbps(speed_by_name.get(name)),
                duplex=None,
                mac=(str(i.get("mac-address")) or None),
                mtu=_int(i.get("mtu") or i.get("actual-mtu")),
                untagged_vlan=pvid_by_name.get(name),
                tagged_vlans=tuple(sorted(set(tagged_by_name.get(name, [])))),
                description=str(i.get("comment") or ""),
                host_model="",
                bmc_ip="",
                notes="",
                services={},
            )
        )
    return out
